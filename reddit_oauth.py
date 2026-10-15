"""Approved, read-only Reddit OAuth ingestion; credentials never enter diagnostics."""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
MAX_BYTES = 5 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Authorization to a redirect destination.
        return None


class RedditClient:
    def __init__(self, environ=None, transport=None):
        env = os.environ if environ is None else environ
        self.approved = env.get("REDDIT_API_APPROVED", "").lower() == "true"
        self.client_id = env.get("REDDIT_CLIENT_ID", "")
        self.client_secret = env.get("REDDIT_CLIENT_SECRET", "")
        self.refresh_token = env.get("REDDIT_REFRESH_TOKEN", "")
        self.user_agent = env.get("REDDIT_USER_AGENT", "")
        self.transport = transport or urllib.request.build_opener(NoRedirect()).open
        self.token = None
        self.expires = 0
        self.blocked_until = 0
        self.auth_failed = False
        self.events = []

    def configuration_status(self):
        if not self.approved:
            return "approval_required"
        if not self.client_id or not self.client_secret:
            return "credentials_missing"
        if not re.fullmatch(r"[^\r\n]+ \(by /u/[A-Za-z0-9_-]+\)", self.user_agent):
            return "user_agent_missing_or_invalid"
        return "configured"

    def _json_request(self, request):
        endpoint = request.full_url
        try:
            with self.transport(request, timeout=15) as response:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    self.events.append({"url": endpoint, "error": "response_too_large"})
                    return None, None
                headers = getattr(response, "headers", {})
                self.events.append(
                    {"url": endpoint, "http_status": getattr(response, "status", 200)}
                )
                try:
                    return json.loads(raw.decode("utf-8")), headers
                except (ValueError, UnicodeError):
                    self.events.append({"url": endpoint, "error": "invalid_json"})
                    return None, headers
        except urllib.error.HTTPError as exc:
            status, headers = exc.code, exc.headers or {}
            exc.close()
            self.events.append(
                {"url": endpoint, "http_status": status, "error": "http_error"}
            )
            return status, headers
        except (urllib.error.URLError, TimeoutError, OSError):
            self.events.append({"url": endpoint, "error": "network_error"})
            return None, None

    def _get_token(self):
        if self.auth_failed:
            return False
        if self.token and time.monotonic() < self.expires:
            return True
        grant = {"grant_type": "client_credentials"}
        if self.refresh_token:
            grant = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        request = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode(grant).encode(),
            headers={
                "Authorization": f"Basic {basic}",
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        payload, _ = self._json_request(request)
        if not isinstance(payload, dict):
            self.auth_failed = True
            return False
        token, lifetime = payload.get("access_token"), payload.get("expires_in")
        if (
            not isinstance(token, str)
            or not token
            or "\r" in token
            or "\n" in token
            or not isinstance(lifetime, (int, float))
            or lifetime <= 0
            or str(payload.get("token_type", "")).lower() != "bearer"
        ):
            self.events.append({"url": TOKEN_URL, "error": "invalid_token_response"})
            self.auth_failed = True
            return False
        self.token = token
        self.expires = time.monotonic() + max(0, lifetime - 30)
        return True

    def listing(self, subreddit, limit=20, retries=3):
        if (
            not re.fullmatch(r"[A-Za-z0-9_]{1,21}", subreddit)
            or not 1 <= limit <= 100
            or not 1 <= retries <= 5
        ):
            raise ValueError("Invalid Reddit listing arguments")
        status = self.configuration_status()
        if status != "configured":
            return {}, status
        if time.monotonic() < self.blocked_until:
            return {}, "rate_limited"
        endpoint = (
            f"https://oauth.reddit.com/r/{subreddit}/new?limit={limit}&raw_json=1"
        )
        refreshed = False
        for attempt in range(retries + 1):
            if not self._get_token():
                return {}, "authentication_failed"
            request = urllib.request.Request(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                },
            )
            payload, headers = self._json_request(request)
            if payload == 401 and not refreshed:
                self.token = None
                refreshed = True
                continue
            if payload == 401:
                self.auth_failed = True
                return {}, "authentication_failed"
            if payload == 429:
                delay = self._number(headers, "Retry-After", 60)
                self.blocked_until = time.monotonic() + max(1, delay)
                # Do not retry earlier than the server allows, even across communities.
                return {}, "rate_limited"
            if (
                isinstance(payload, dict)
                and isinstance(payload.get("data"), dict)
                and isinstance(payload["data"].get("children"), list)
            ):
                if self._number(headers, "X-Ratelimit-Remaining", 1) <= 0:
                    self.blocked_until = time.monotonic() + max(
                        1, self._number(headers, "X-Ratelimit-Reset", 60)
                    )
                return payload, "ok"
            if payload in (500, 502, 503, 504, None) and attempt < retries - 1:
                time.sleep(min(8, 2 ** (attempt + 1)))
                continue
            return {}, "access_denied" if payload == 403 else "listing_failed"
        return {}, "authentication_failed"

    @staticmethod
    def _number(headers, name, default):
        try:
            return float((headers or {}).get(name, default))
        except (ValueError, TypeError):
            return default
