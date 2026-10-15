"""Acceptance check: require recent, real Reddit-origin AND HN exported signals."""

import json

import pain_point_radar_v3_anti_block as radar
import radar_quality as quality


def main():
    radar.FETCH_EVENTS.clear()
    signals, coverage = [], {}
    for sub in ("SaaS", "smallbusiness", "SideProject"):
        received, success = radar.collect_public_reddit_signals(
            sub, retries=1, limit=25
        )
        signals.extend(received)
        coverage[sub] = {"success": success, "matched": len(received)}
    for query in (
        '"wish there was a tool"',
        '"tired of manually"',
        '"looking for a tool"',
    ):
        received, success = radar.fetch_hn_algolia(1, 25, query, 30)
        signals.extend(received)
        coverage["hn:" + query] = {"success": success, "matched": len(received)}
    fresh, filtered = quality.select_fresh(signals, {}, 30)
    reddit = [
        s
        for s in fresh
        if s.source_channel.startswith(("reddit_rss:", "arctic_shift_archive:"))
    ]
    hn = [s for s in fresh if s.source_channel == "hn_algolia"]
    radar.export_with_provenance(
        [quality.evaluate(s) for s in fresh], fresh, "radar_sources_check.csv"
    )
    report = {
        "passed": bool(reddit and hn),
        "checked_at_utc": radar.utc_now(),
        "max_age_days": 30,
        "reddit_recent_exported": len(reddit),
        "hn_recent_exported": len(hn),
        "filtered": filtered,
        "source_status": coverage,
        "fetch_events": radar.FETCH_EVENTS,
    }
    quality.atomic_json("radar_sources_check.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
