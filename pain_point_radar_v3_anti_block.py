#!/usr/bin/env python3
"""Pain Point Radar V3.1: resilient public-source collection and provenance.

Author: rongjiedu0-code. License: Apache-2.0 (see LICENSE).
Public Reddit Atom -> Arctic Shift archive, plus HN Algolia.
OAuth remains optional. Each source is independently diagnosed and labeled.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import random
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import pain_point_radar_engine as engine
import radar_quality as quality
from reddit_oauth import RedditClient

USER_AGENT = "PainPointRadar/3.1 (+https://github.com/rongjiedu0-code/pain-point-radar)"
RETRYABLE = {429, 500, 502, 503, 504}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
ATOM = {"a": "http://www.w3.org/2005/Atom"}
FETCH_EVENTS = []
REDDIT_STATUS = {}
REDDIT_CLIENT = None
REDDIT_TRANSPORT = "public"
MAX_AGE_DAYS = 30


@dataclass
class SourceSignal(engine.RawSignal):
    ingestion_endpoint: str = ""
    retrieved_at_utc: str = ""


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    parser = _PlainHTML()
    parser.feed(value if isinstance(value, str) else "")
    return " ".join(parser.parts)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _fetch_bytes(url, retries=3):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/atom+xml, application/rss+xml;q=0.9, */*;q=0.8",
        },
    )
    for attempt in range(retries):
        retry_after = None
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("response exceeds size limit")
                print(f"[Source] HTTP {getattr(response, 'status', 200)} {url}")
                FETCH_EVENTS.append(
                    {
                        "url": url,
                        "http_status": getattr(response, "status", 200),
                        "bytes": len(raw),
                    }
                )
                return raw
        except urllib.error.HTTPError as exc:
            status = exc.code
            header = exc.headers.get("Retry-After", "") if exc.headers else ""
            if header.isdigit():
                retry_after = int(header)
            exc.close()
            print(f"[Warn] HTTP {status} {url}", file=sys.stderr)
            FETCH_EVENTS.append(
                {"url": url, "http_status": status, "error": "http_error"}
            )
            if status not in RETRYABLE or (
                retry_after is not None and retry_after > 60
            ):
                return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"[Warn] {type(exc).__name__} fetching {url}", file=sys.stderr)
            FETCH_EVENTS.append({"url": url, "error": type(exc).__name__})
        if attempt + 1 < retries:
            time.sleep(
                max(
                    retry_after or 0,
                    min(60, 2 ** (attempt + 1) + random.uniform(0.5, 1.5)),
                )
            )
    return None


def _fetch_json(url, retries):
    raw = _fetch_bytes(url, retries)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        print(f"[Warn] Invalid JSON {url}", file=sys.stderr)
        FETCH_EVENTS.append({"url": url, "error": "invalid_json"})
        return None


def _validate_args(subreddit, retries, limit):
    if not re.fullmatch(r"[A-Za-z0-9_]{1,21}", subreddit):
        raise ValueError("Invalid subreddit name")
    if not 1 <= retries <= 5 or not 1 <= limit <= 100:
        raise ValueError("retries must be 1-5 and limit must be 1-100")


def fetch_sub_reddit_json(subreddit: str, retries: int = 3, limit: int = 25) -> dict:
    _validate_args(subreddit, retries, limit)
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
    payload = _fetch_json(url, retries)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("data"), dict)
        or not isinstance(payload["data"].get("children"), list)
    ):
        return {}
    return payload


def _reddit_signal(data, subreddit, source, endpoint):
    title, body = data.get("title") or "", data.get("selftext") or ""
    if not isinstance(title, str) or not isinstance(body, str):
        return None
    if body.strip() in {"[removed]", "[deleted]"}:
        return None
    matched = engine.scan_text_for_intent(title + "\n" + body)
    post_id = str(data.get("id", ""))
    if not matched or not re.fullmatch(r"[A-Za-z0-9]+", post_id):
        return None
    try:
        created = datetime.datetime.fromtimestamp(
            float(data.get("created_utc", 0)), datetime.timezone.utc
        ).isoformat()
    except (ValueError, TypeError, OSError, OverflowError):
        created = ""
    return SourceSignal(
        source_channel=f"{source}:r/{subreddit}",
        post_id=post_id,
        title=title,
        body=body[:1000],
        author=str(data.get("author", "[anonymous]")),
        url=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/",
        created_utc=created,
        matched_keyword=matched,
        ingestion_endpoint=endpoint,
        retrieved_at_utc=utc_now(),
    )


def signals_from_payload(payload, subreddit):
    endpoint = f"https://www.reddit.com/r/{subreddit}/new.json"
    signals = []
    for child in payload.get("data", {}).get("children", []):
        if not isinstance(child, dict) or not isinstance(child.get("data"), dict):
            continue
        signal = _reddit_signal(child["data"], subreddit, "reddit_json", endpoint)
        if signal:
            signals.append(signal)
    return signals


def fetch_reddit_rss(subreddit, retries=3, limit=25):
    _validate_args(subreddit, retries, limit)
    endpoint = f"https://old.reddit.com/r/{subreddit}/new/.rss"
    raw = _fetch_bytes(endpoint, retries)
    if raw is None:
        return [], False
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        print(f"[Warn] Invalid Atom XML {endpoint}", file=sys.stderr)
        FETCH_EVENTS.append({"url": endpoint, "error": "invalid_atom_xml"})
        return [], False
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        print(
            f"[Warn] Expected Atom feed, received {root.tag}: {endpoint}",
            file=sys.stderr,
        )
        FETCH_EVENTS.append(
            {"url": endpoint, "error": "unexpected_atom_root", "root": root.tag}
        )
        return [], False
    signals = []
    entries = root.findall("a:entry", ATOM)[:limit]
    for entry in entries:
        title = entry.findtext("a:title", "", ATOM)
        content = entry.find("a:content", ATOM)
        body = plain_text("".join(content.itertext()) if content is not None else "")
        matched = engine.scan_text_for_intent(title + "\n" + body)
        post_id = entry.findtext("a:id", "", ATOM).removeprefix("t3_")
        links = entry.findall("a:link", ATOM)
        href = next(
            (
                link.get("href", "")
                for link in links
                if link.get("rel", "alternate") == "alternate"
            ),
            "",
        )
        parsed = urllib.parse.urlsplit(href)
        link_match = re.fullmatch(
            r"/r/([A-Za-z0-9_]+)/comments/([A-Za-z0-9]+)(?:/.*)?", parsed.path
        )
        if link_match and parsed.hostname in {
            "www.reddit.com",
            "old.reddit.com",
            "reddit.com",
        }:
            if link_match.group(1).lower() != subreddit.lower():
                continue
            post_id = link_match.group(2)
        elif href:
            continue
        if not matched or not re.fullmatch(r"[A-Za-z0-9]+", post_id):
            continue
        signals.append(
            SourceSignal(
                source_channel=f"reddit_rss:r/{subreddit}",
                post_id=post_id,
                title=title,
                body=body[:1000],
                author=entry.findtext("a:author/a:name", "", ATOM),
                url=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/",
                created_utc=entry.findtext("a:published", "", ATOM)
                or entry.findtext("a:updated", "", ATOM),
                matched_keyword=matched,
                ingestion_endpoint=endpoint,
                retrieved_at_utc=utc_now(),
            )
        )
    print(
        f"[Source] Reddit RSS r/{subreddit}: {len(entries)} entries; {len(signals)} signals"
    )
    return signals, True


def fetch_arctic_shift(subreddit, retries=3, limit=25, before=None):
    _validate_args(subreddit, retries, limit)
    query = urllib.parse.urlencode(
        {
            "subreddit": subreddit,
            "limit": limit,
            "sort": "desc",
            "after": int(time.time() - MAX_AGE_DAYS * 86400),
        }
    )
    if before is not None:
        query += "&" + urllib.parse.urlencode({"before": before})
    endpoint = "https://arctic-shift.photon-reddit.com/api/posts/search?" + query
    payload = _fetch_json(endpoint, retries)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return [], False
    FETCH_EVENTS.append(
        {
            "url": endpoint,
            "records": len(payload["data"]),
            "sample_publication_dates": [
                x.get("created_utc") for x in payload["data"][:3] if isinstance(x, dict)
            ],
            "oldest_created_utc": min(
                (
                    x.get("created_utc")
                    for x in payload["data"]
                    if isinstance(x, dict)
                    and isinstance(x.get("created_utc"), (int, float))
                ),
                default=None,
            ),
            "returned_records": len(payload["data"]),
        }
    )
    signals = []
    for data in payload["data"]:
        if (
            not isinstance(data, dict)
            or str(data.get("subreddit", subreddit)).lower() != subreddit.lower()
        ):
            continue
        data = dict(data)
        data["id"] = str(data.get("id", "")).removeprefix("t3_")
        signal = _reddit_signal(data, subreddit, "arctic_shift_archive", endpoint)
        if signal:
            signals.append(signal)
    print(
        f"[Source] Arctic Shift archive r/{subreddit}: {len(payload['data'])} records; {len(signals)} signals"
    )
    return signals, True


def collect_public_reddit_signals(subreddit, retries=3, limit=25):
    """Public Atom feed with a separately labeled third-party archive fallback."""
    signals, success = fetch_reddit_rss(subreddit, retries, limit)
    if success:
        return signals, True
    signals, success = fetch_arctic_shift(subreddit, retries, limit)
    if success and not signals:
        # Up to four pages; sparse intent matches must not be fabricated.
        previous = None
        for _ in range(3):
            event = FETCH_EVENTS[-1] if FETCH_EVENTS else {}
            oldest = event.get("oldest_created_utc")
            if (
                event.get("returned_records", 0) < limit
                or oldest is None
                or oldest <= time.time() - MAX_AGE_DAYS * 86400
                or oldest == previous
            ):
                break
            previous = oldest
            found, available = fetch_arctic_shift(subreddit, retries, limit, oldest)
            signals.extend(found)
            if not available or signals:
                break
    return signals, success


def collect_reddit_signals(subreddit, retries=3, limit=25):
    global REDDIT_CLIENT
    if REDDIT_CLIENT is None:
        REDDIT_CLIENT = RedditClient()
    if REDDIT_TRANSPORT == "public":
        signals, success = collect_public_reddit_signals(subreddit, retries, limit)
        REDDIT_STATUS[subreddit] = (
            "public_source_available" if success else "public_sources_unavailable"
        )
        return signals, success
    start = len(REDDIT_CLIENT.events)
    payload, status = REDDIT_CLIENT.listing(subreddit, limit, retries)
    FETCH_EVENTS.extend(REDDIT_CLIENT.events[start:])
    REDDIT_STATUS[subreddit] = status
    if status != "ok":
        print(f"[Reddit] r/{subreddit}: {status}", file=sys.stderr)
        return [], False
    signals = signals_from_payload(payload, subreddit)
    endpoint = f"https://oauth.reddit.com/r/{subreddit}/new"
    for signal in signals:
        signal.source_channel = f"reddit_oauth:r/{subreddit}"
        signal.ingestion_endpoint = endpoint
    print(
        f"[Reddit OAuth] r/{subreddit}: {len(payload['data']['children'])} posts; {len(signals)} signals"
    )
    return signals, True


def fetch_hn_algolia(
    retries=3, limit=25, query='"wish there was a tool"', max_age_days=30
):
    # Parentheses mean OR. tags=story,comment would require both tags.
    params = urllib.parse.urlencode(
        {
            "query": query,
            "tags": "(story,comment)",
            "hitsPerPage": limit,
            "numericFilters": f"created_at_i>{int(time.time() - max_age_days * 86400)}",
        }
    )
    endpoint = "https://hn.algolia.com/api/v1/search_by_date?" + params
    payload = _fetch_json(endpoint, retries)
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        return [], False
    signals = []
    for hit in payload["hits"]:
        if not isinstance(hit, dict):
            continue
        body = plain_text(hit.get("comment_text") or hit.get("story_text") or "")
        title = plain_text(hit.get("title") or hit.get("story_title") or body[:120])
        matched = engine.scan_text_for_intent(title + "\n" + body)
        post_id = str(hit.get("objectID", ""))
        if not matched or not post_id.isdigit():
            continue
        signals.append(
            SourceSignal(
                source_channel="hn_algolia",
                post_id=post_id,
                title=title,
                body=body[:1000],
                author=str(hit.get("author", "")),
                url=f"https://news.ycombinator.com/item?id={post_id}",
                created_utc=str(hit.get("created_at", "")),
                matched_keyword=matched,
                ingestion_endpoint=endpoint,
                retrieved_at_utc=utc_now(),
            )
        )
    print(
        f"[Source] HN Algolia: {len(payload['hits'])} records; {len(signals)} signals (global, not subreddit coverage)"
    )
    return signals, True


def export_with_provenance(opportunities, signals, output):
    """Keep the V2 ledger schema and append explicit ingestion provenance."""
    metadata = {signal.url: signal for signal in signals}
    output = Path(output)
    with tempfile.TemporaryDirectory(dir=output.resolve().parent) as folder:
        temporary = Path(folder) / "scan.csv"
        engine.export_to_csv(opportunities, temporary)
        with temporary.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            rows = list(reader)
        extra = [
            "Source_Channel",
            "Source_Post_ID",
            "Source_Created_UTC",
            "Retrieved_At_UTC",
            "Ingestion_Endpoint",
            "Scoring_Method",
            "Review_Status",
            "Review_Reason",
        ]
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields + extra)
            writer.writeheader()
            for row in rows:
                signal = metadata[row["Source_URL"]]
                row.update(
                    dict(
                        zip(
                            extra,
                            [
                                signal.source_channel,
                                signal.post_id,
                                signal.created_utc,
                                signal.retrieved_at_utc,
                                signal.ingestion_endpoint,
                                "keyword_category_heuristic",
                                "human_review_required",
                                quality.review_reason(signal),
                            ],
                        )
                    )
                )
                writer.writerow(row)
        temporary.replace(output)


def main(argv=None):
    global REDDIT_CLIENT, REDDIT_TRANSPORT, MAX_AGE_DAYS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddits", default="SaaS,smallbusiness,SideProject")
    parser.add_argument(
        "--limit", type=int, choices=range(1, 101), metavar="1-100", default=15
    )
    parser.add_argument("--retries", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--output-csv", default="radar_latest_scan.csv")
    parser.add_argument(
        "--hn-query", action="append", help="Repeat for up to 5 HN queries"
    )
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument(
        "--reddit-transport", choices=["public", "oauth"], default="public"
    )
    parser.add_argument(
        "--always-hn", action="store_true", help="Collect HN even when Reddit succeeds"
    )
    parser.add_argument("--seen-state", default="radar_seen.json")
    parser.add_argument("--diagnostics-json", default="radar_diagnostics.json")
    parser.add_argument(
        "--check-reddit",
        action="store_true",
        help="Check Reddit only; never write CSV or seen-state",
    )
    parser.add_argument(
        "--require-reddit",
        action="store_true",
        help="Fail if any requested subreddit is unavailable, even if HN works",
    )
    parser.add_argument("--mock-self-test", action="store_true")
    parser.add_argument("--generate-tweet", action="store_true")
    args = parser.parse_args(argv)
    if args.mock_self_test:
        return engine.run_mock_self_test(Path("."))
    if not 1 <= args.max_age_days <= 365:
        parser.error("--max-age-days must be 1-365")
    queries = args.hn_query or [
        '"wish there was a tool"',
        '"tired of manually"',
        '"looking for a tool"',
    ]
    if len(queries) > 5 or any(not query.strip() for query in queries):
        parser.error("Provide 1-5 nonempty --hn-query values")
    paths = [
        Path(p).resolve()
        for p in (args.output_csv, args.seen_state, args.diagnostics_json)
    ]
    if len(set(paths)) != 3:
        parser.error("CSV, seen-state and diagnostics must use distinct paths")
    try:
        seen = quality.load_seen(args.seen_state, args.output_csv)
    except (OSError, ValueError) as exc:
        parser.error(f"Cannot load deduplication state: {exc}")
    FETCH_EVENTS.clear()
    REDDIT_STATUS.clear()
    REDDIT_CLIENT = RedditClient()
    REDDIT_TRANSPORT = args.reddit_transport
    MAX_AGE_DAYS = args.max_age_days
    started = utc_now()
    source_status = {}

    def report(status, **extra):
        quality.atomic_json(
            args.diagnostics_json,
            dict(
                started_at_utc=started,
                completed_at_utc=utc_now(),
                exit_code=status,
                max_age_days=args.max_age_days,
                source_status=source_status,
                fetch_events=FETCH_EVENTS,
                **extra,
            ),
        )

    subs = list(
        dict.fromkeys(s.strip() for s in args.subreddits.split(",") if s.strip())
    )
    if not subs or any(not re.fullmatch(r"[A-Za-z0-9_]{1,21}", sub) for sub in subs):
        parser.error("Provide valid comma-separated subreddit names")
    signals, failures = [], 0
    for sub in subs:
        collected, success = collect_reddit_signals(sub, args.retries, args.limit)
        signals.extend(collected)
        failures += not success
        source_status[f"r/{sub}"] = {
            "success": success,
            "matched": len(collected),
            "status": REDDIT_STATUS.get(sub, "custom_collector"),
        }
    if args.check_reddit:
        status = 2 if failures else 0
        report(
            status,
            coverage="unavailable"
            if failures == len(subs)
            else ("degraded" if failures else "requested_sources_available"),
            check_only=True,
            csv_preserved=True,
            matched=len(signals),
            reddit_configuration=REDDIT_CLIENT.configuration_status()
            if REDDIT_TRANSPORT == "oauth"
            else "public_rss_arctic_shift",
        )
        return status
    hn_success = False
    if (
        args.always_hn
        or failures
        or not quality.select_fresh(signals, seen, args.max_age_days)[0]
    ):
        for query in dict.fromkeys(queries):
            hn_signals, success = fetch_hn_algolia(
                args.retries, args.limit, query, args.max_age_days
            )
            hn_success |= success
            signals.extend(hn_signals)
            source_status[f"hn_algolia:{query}"] = {
                "success": success,
                "matched": len(hn_signals),
            }
        if failures and hn_success:
            print(
                f"[Coverage] Degraded: {failures} subreddit sources unavailable; HN fallback retrieved instead"
            )
    if failures == len(subs) and not hn_success:
        print(
            "[Error] All sources failed; existing CSV left untouched", file=sys.stderr
        )
        report(1, coverage="unavailable", exported=0, csv_preserved=True)
        return 1
    signals, filtered = quality.select_fresh(signals, seen, args.max_age_days)
    opportunities = [quality.evaluate(signal) for signal in signals]
    opportunities.sort(key=lambda opp: opp.overall_score, reverse=True)
    export_with_provenance(opportunities, signals, args.output_csv)
    seen.update(
        {signal.url: signal.retrieved_at_utc or utc_now() for signal in signals}
    )
    quality.atomic_json(args.seen_state, {"version": 1, "seen": seen})
    print(
        f"[Radar V3.1] Exported {len(opportunities)} opportunities; {failures} subreddit sources unavailable; HN fallback={hn_success}"
    )
    status = 2 if failures and (args.require_reddit or not hn_success) else 0
    report(
        status,
        coverage="degraded" if failures else "requested_sources_available",
        exported=len(opportunities),
        filtered=filtered,
        csv_preserved=False,
        human_review_required=True,
    )
    if args.generate_tweet:
        print(
            "[Review] Automatic opportunity alerts suppressed: all rule-scored leads require human review."
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
