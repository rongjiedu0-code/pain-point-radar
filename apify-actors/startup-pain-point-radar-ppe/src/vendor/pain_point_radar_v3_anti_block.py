#!/usr/bin/env python3
"""Pain Point Radar V3.1: resilient public-source collection and provenance.

Author: rongjiedu0-code. License: Apache-2.0 (see LICENSE).
Reddit JSON -> Reddit Atom -> PullPush archive -> global HN Algolia fallback.
Rate limits are respected; alternate sources do not guarantee Reddit coverage.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import datetime
from html.parser import HTMLParser
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
from pathlib import Path

from . import pain_point_radar_engine as engine

USER_AGENT = "PainPointRadar/3.1 (+https://github.com/rongjiedu0-code/pain-point-radar)"
RETRYABLE = {429, 500, 502, 503, 504}
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
ATOM = {"a": "http://www.w3.org/2005/Atom"}


@dataclass
class SourceSignal(engine.RawSignal):
    ingestion_endpoint: str = ""
    retrieved_at_utc: str = ""


class _PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
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
                return raw
        except urllib.error.HTTPError as exc:
            status = exc.code
            header = exc.headers.get("Retry-After", "") if exc.headers else ""
            if header.isdigit():
                retry_after = int(header)
            exc.close()
            print(f"[Warn] HTTP {status} {url}", file=sys.stderr)
            if status not in RETRYABLE or (
                retry_after is not None and retry_after > 60
            ):
                return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"[Warn] {type(exc).__name__} fetching {url}", file=sys.stderr)
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
        return [], False
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        return [], False
    signals = []
    entries = root.findall("a:entry", ATOM)[:limit]
    for entry in entries:
        title = entry.findtext("a:title", "", ATOM)
        body = plain_text(entry.findtext("a:content", "", ATOM))
        matched = engine.scan_text_for_intent(title + "\n" + body)
        post_id = entry.findtext("a:id", "", ATOM).removeprefix("t3_")
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
                created_utc=entry.findtext("a:published", "", ATOM),
                matched_keyword=matched,
                ingestion_endpoint=endpoint,
                retrieved_at_utc=utc_now(),
            )
        )
    print(
        f"[Source] Reddit RSS r/{subreddit}: {len(entries)} entries; {len(signals)} signals"
    )
    return signals, True


def fetch_pullpush(subreddit, retries=3, limit=25):
    _validate_args(subreddit, retries, limit)
    query = urllib.parse.urlencode(
        {"subreddit": subreddit, "size": limit, "sort": "desc"}
    )
    endpoint = "https://api.pullpush.io/reddit/search/submission/?" + query
    payload = _fetch_json(endpoint, retries)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return [], False
    signals = []
    for data in payload["data"]:
        if (
            not isinstance(data, dict)
            or str(data.get("subreddit", subreddit)).lower() != subreddit.lower()
        ):
            continue
        signal = _reddit_signal(data, subreddit, "pullpush_archive", endpoint)
        if signal:
            signals.append(signal)
    print(
        f"[Source] PullPush archive r/{subreddit}: {len(payload['data'])} records; {len(signals)} signals"
    )
    return signals, True


def collect_reddit_signals(subreddit, retries=3, limit=25):
    payload = fetch_sub_reddit_json(subreddit, retries, limit)
    if payload:
        signals = signals_from_payload(payload, subreddit)
        print(f"[Source] Reddit JSON r/{subreddit}: {len(signals)} signals")
        return signals, True
    signals, success = fetch_reddit_rss(subreddit, retries, limit)
    if success:
        return signals, True
    return fetch_pullpush(subreddit, retries, limit)


def fetch_hn_algolia(retries=3, limit=25, query='"wish there was a tool"'):
    # Parentheses mean OR. tags=story,comment would require both tags.
    params = urllib.parse.urlencode(
        {"query": query, "tags": "(story,comment)", "hitsPerPage": limit}
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
                            ],
                        )
                    )
                )
                writer.writerow(row)
        temporary.replace(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddits", default="SaaS,smallbusiness,SideProject")
    parser.add_argument(
        "--limit", type=int, choices=range(1, 101), metavar="1-100", default=15
    )
    parser.add_argument("--retries", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--output-csv", default="radar_latest_scan.csv")
    parser.add_argument("--hn-query", default='"wish there was a tool"')
    parser.add_argument("--mock-self-test", action="store_true")
    parser.add_argument("--generate-tweet", action="store_true")
    args = parser.parse_args(argv)
    if args.mock_self_test:
        return engine.run_mock_self_test(Path("."))
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
    hn_success = False
    if failures or not signals:
        hn_signals, hn_success = fetch_hn_algolia(
            args.retries, args.limit, args.hn_query
        )
        signals.extend(hn_signals)
        if failures and hn_success:
            print(
                f"[Coverage] Degraded: {failures} subreddit sources unavailable; HN fallback retrieved instead"
            )
    if failures == len(subs) and not hn_success:
        print(
            "[Error] All sources failed; existing CSV left untouched", file=sys.stderr
        )
        return 1
    signals = list({signal.url: signal for signal in signals}.values())
    opportunities = [
        engine.heuristic_evaluate_signal(signal, 11 + i)
        for i, signal in enumerate(signals)
    ]
    opportunities.sort(key=lambda opp: opp.overall_score, reverse=True)
    export_with_provenance(opportunities, signals, args.output_csv)
    print(
        f"[Radar V3.1] Exported {len(opportunities)} opportunities; {failures} subreddit sources unavailable; HN fallback={hn_success}"
    )
    leads = [opp for opp in opportunities if opp.verdict.startswith("PROCEED")]
    if args.generate_tweet and leads:
        print(engine.generate_x_thread_draft(leads[0]))
    return 2 if failures and not hn_success else 0


if __name__ == "__main__":
    raise SystemExit(main())
