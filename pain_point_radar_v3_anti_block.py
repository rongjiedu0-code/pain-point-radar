#!/usr/bin/env python3
"""Pain Point Radar V3: bounded retries and backoff for public Reddit JSON.

Author: rongjiedu0-code. License: Apache-2.0 (see LICENSE).
Reuses the V2 scoring/CSV engine. No access-control bypass or proxy failover.
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pain_point_radar_engine as engine

USER_AGENT = "PainPointRadar/3.0 (+https://github.com/rongjiedu0-code/pain-point-radar)"
RETRYABLE = {429, 500, 502, 503, 504}


def fetch_sub_reddit_json(subreddit: str, retries: int = 3, limit: int = 25) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_]{1,21}", subreddit):
        raise ValueError("Invalid subreddit name")
    if not 1 <= retries <= 5 or not 1 <= limit <= 100:
        raise ValueError("retries must be 1-5 and limit must be 1-100")
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        retry_after = None
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict) or not isinstance(payload["data"].get("children"), list):
                raise ValueError("Unexpected Reddit response structure")
            return payload
        except urllib.error.HTTPError as exc:
            status = exc.code
            header = exc.headers.get("Retry-After", "") if exc.headers else ""
            if header.isdigit():
                retry_after = int(header)
            exc.close()
            if status not in RETRYABLE or (retry_after is not None and retry_after > 60):
                print(f"[Warn] r/{subreddit}: HTTP {status}; stopping", file=sys.stderr)
                return {}
        except urllib.error.URLError:
            pass
        except (TimeoutError, OSError):
            pass
        except (ValueError, UnicodeError):
            print(f"[Warn] r/{subreddit}: invalid JSON response", file=sys.stderr)
            return {}
        if attempt + 1 < retries:
            time.sleep(max(retry_after or 0, min(60, 2 ** (attempt + 1) + random.uniform(0.5, 1.5))))
    print(f"[Warn] r/{subreddit}: fetch failed after {retries} attempts", file=sys.stderr)
    return {}


def signals_from_payload(payload, subreddit):
    signals = []
    for child in payload.get("data", {}).get("children", []):
        if not isinstance(child, dict) or not isinstance(child.get("data"), dict):
            continue
        data = child["data"]
        title, body = data.get("title") or "", data.get("selftext") or ""
        if not isinstance(title, str) or not isinstance(body, str):
            continue
        matched = engine.scan_text_for_intent(title + "\n" + body)
        if not matched:
            continue
        try:
            created = datetime.datetime.fromtimestamp(float(data.get("created_utc", 0)), datetime.timezone.utc).isoformat()
        except (ValueError, TypeError, OSError, OverflowError):
            created = ""
        signals.append(engine.RawSignal(
            source_channel=f"r/{subreddit}", post_id=str(data.get("id", "")),
            title=title, body=body[:1000], author=str(data.get("author", "[anonymous]")),
            url="https://www.reddit.com" + str(data.get("permalink", "")),
            created_utc=created, matched_keyword=matched))
    return signals


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddits", default="SaaS,smallbusiness,SideProject")
    parser.add_argument("--limit", type=int, choices=range(1, 101), metavar="1-100", default=15)
    parser.add_argument("--retries", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--output-csv", default="radar_latest_scan.csv")
    parser.add_argument("--mock-self-test", action="store_true")
    parser.add_argument("--generate-tweet", action="store_true")
    args = parser.parse_args(argv)
    if args.mock_self_test:
        return engine.run_mock_self_test(Path("."))
    subs = list(dict.fromkeys(s.strip() for s in args.subreddits.split(",") if s.strip()))
    if not subs or any(not re.fullmatch(r"[A-Za-z0-9_]{1,21}", sub) for sub in subs):
        parser.error("Provide valid comma-separated subreddit names")
    signals, failures = [], 0
    for sub in subs:
        payload = fetch_sub_reddit_json(sub, args.retries, args.limit)
        if not payload:
            failures += 1
            continue
        signals.extend(signals_from_payload(payload, sub))
    if failures == len(subs):
        print("[Error] All sources failed; existing CSV left untouched", file=sys.stderr)
        return 1
    opportunities = [engine.heuristic_evaluate_signal(s, 11 + i) for i, s in enumerate(signals)]
    opportunities.sort(key=lambda opp: opp.overall_score, reverse=True)
    engine.export_to_csv(opportunities, Path(args.output_csv))
    print(f"[Radar V3] Exported {len(opportunities)} opportunities; {failures} sources failed")
    leads = [opp for opp in opportunities if opp.verdict.startswith("PROCEED")]
    if args.generate_tweet and leads:
        print(engine.generate_x_thread_draft(leads[0]))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
