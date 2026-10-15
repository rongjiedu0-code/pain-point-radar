"""OAuth protocol tests with synthetic credentials and no network access."""

import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

import pain_point_radar_v3_anti_block as radar
from reddit_oauth import TOKEN_URL, RedditClient

ENV = {
    "REDDIT_API_APPROVED": "true",
    "REDDIT_CLIENT_ID": "synthetic-id",
    "REDDIT_CLIENT_SECRET": "synthetic-secret",
    "REDDIT_USER_AGENT": "windows:pain-point-radar:v3.2 (by /u/example)",
}


def response(data, headers=None):
    value = io.BytesIO(json.dumps(data).encode())
    value.status = 200
    value.headers = headers or {}
    return value


def token(name="synthetic-token"):
    return response({"access_token": name, "token_type": "bearer", "expires_in": 3600})


def listing():
    return response({"data": {"children": []}})


class RedditOAuthTests(unittest.TestCase):
    def test_missing_approval_or_credentials_sends_no_request(self):
        for env, expected in (
            ({}, "approval_required"),
            ({"REDDIT_API_APPROVED": "true"}, "credentials_missing"),
            ({**ENV, "REDDIT_USER_AGENT": ""}, "user_agent_missing_or_invalid"),
        ):
            send = Mock()
            self.assertEqual(RedditClient(env, send).listing("SaaS"), ({}, expected))
            send.assert_not_called()

    def test_token_exchange_and_listing_use_correct_hosts_and_cache(self):
        send = Mock(side_effect=[token(), listing(), listing()])
        client = RedditClient(ENV, send)
        self.assertEqual(client.listing("SaaS")[1], "ok")
        self.assertEqual(client.listing("SideProject")[1], "ok")
        requests = [call.args[0] for call in send.call_args_list]
        self.assertEqual(requests[0].full_url, TOKEN_URL)
        self.assertEqual(requests[0].data, b"grant_type=client_credentials")
        self.assertTrue(requests[0].get_header("Authorization").startswith("Basic "))
        self.assertTrue(
            requests[1].full_url.startswith("https://oauth.reddit.com/r/SaaS/new?")
        )
        self.assertEqual(
            requests[1].get_header("Authorization"), "Bearer synthetic-token"
        )
        self.assertNotIn("synthetic-secret", json.dumps(client.events))
        self.assertNotIn("synthetic-token", json.dumps(client.events))

    def test_refresh_token_is_posted_not_logged(self):
        send = Mock(side_effect=[token(), listing()])
        client = RedditClient(
            {**ENV, "REDDIT_REFRESH_TOKEN": "synthetic-refresh"}, send
        )
        self.assertEqual(client.listing("SaaS")[1], "ok")
        self.assertIn(b"grant_type=refresh_token", send.call_args_list[0].args[0].data)
        self.assertNotIn("synthetic-refresh", json.dumps(client.events))

    def test_401_refreshes_once_and_403_does_not_retry(self):
        error = urllib.error.HTTPError(
            "https://oauth.reddit.com", 401, "expired", {}, None
        )
        send = Mock(side_effect=[token(), error, token("second"), listing()])
        self.assertEqual(RedditClient(ENV, send).listing("SaaS")[1], "ok")
        self.assertEqual(send.call_count, 4)
        error = urllib.error.HTTPError(
            "https://oauth.reddit.com", 403, "denied", {}, None
        )
        send = Mock(side_effect=[token(), error])
        self.assertEqual(RedditClient(ENV, send).listing("SaaS")[1], "access_denied")
        self.assertEqual(send.call_count, 2)

    def test_invalid_credentials_not_retried_per_subreddit(self):
        error = urllib.error.HTTPError(TOKEN_URL, 401, "invalid", {}, None)
        send = Mock(side_effect=[error])
        client = RedditClient(ENV, send)
        self.assertEqual(client.listing("SaaS")[1], "authentication_failed")
        self.assertEqual(client.listing("SideProject")[1], "authentication_failed")
        send.assert_called_once()

    def test_rate_limit_blocks_following_community_requests(self):
        error = urllib.error.HTTPError(
            "https://oauth.reddit.com", 429, "slow down", {"Retry-After": "120"}, None
        )
        send = Mock(side_effect=[token(), error])
        client = RedditClient(ENV, send)
        self.assertEqual(client.listing("SaaS")[1], "rate_limited")
        self.assertEqual(client.listing("SideProject")[1], "rate_limited")
        self.assertEqual(send.call_count, 2)

    def test_exhausted_quota_on_success_blocks_next_request(self):
        send = Mock(
            side_effect=[
                token(),
                response(
                    {"data": {"children": []}},
                    {"X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "90"},
                ),
            ]
        )
        client = RedditClient(ENV, send)
        self.assertEqual(client.listing("SaaS")[1], "ok")
        self.assertEqual(client.listing("SideProject")[1], "rate_limited")
        self.assertEqual(send.call_count, 2)

    def test_invalid_token_body_is_rejected_without_logging_body(self):
        send = Mock(return_value=response({"access_token": "synthetic-token"}))
        client = RedditClient(ENV, send)
        self.assertEqual(client.listing("SaaS")[1], "authentication_failed")
        self.assertNotIn("synthetic-token", json.dumps(client.events))

    def test_reddit_only_check_fails_without_approval_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output, state, diag = (
                root / "scan.csv",
                root / "seen.json",
                root / "diag.json",
            )
            output.write_text("Source_URL\nhttps://example.com/old\n")
            state.write_text('{"version":1,"seen":{}}')
            before = output.read_bytes(), state.read_bytes()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(radar, "fetch_hn_algolia") as hn,
            ):
                status = radar.main(
                    [
                        "--check-reddit",
                        "--reddit-transport",
                        "oauth",
                        "--output-csv",
                        str(output),
                        "--seen-state",
                        str(state),
                        "--diagnostics-json",
                        str(diag),
                    ]
                )
            self.assertEqual(status, 2)
            hn.assert_not_called()
            self.assertEqual(before, (output.read_bytes(), state.read_bytes()))
            self.assertEqual(
                json.loads(diag.read_text())["reddit_configuration"],
                "approval_required",
            )

    def test_require_reddit_cannot_pass_due_to_hn_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (
                patch.object(radar, "collect_reddit_signals", return_value=([], False)),
                patch.object(radar, "fetch_hn_algolia", return_value=([], True)),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                status = radar.main(
                    [
                        "--require-reddit",
                        "--output-csv",
                        str(root / "scan.csv"),
                        "--seen-state",
                        str(root / "seen.json"),
                        "--diagnostics-json",
                        str(root / "diag.json"),
                    ]
                )
            self.assertEqual(status, 2)


if __name__ == "__main__":
    unittest.main()
