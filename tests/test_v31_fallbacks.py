"""Public-source fallbacks must report real provenance without mock substitution."""

import contextlib
import csv
import io
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pain_point_radar_v3_anti_block as radar


class FallbackTests(unittest.TestCase):
    def test_json_denial_uses_atom_and_stops_on_success(self):
        xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>t3_abc123</id><title>Wish there was a tool for invoices</title>
        <content type="html">&lt;p&gt;Manual receipts&lt;/p&gt;</content>
        <published>2026-01-01T00:00:00Z</published>
        <author><name>/u/example</name></author></entry></feed>"""
        with (
            patch.object(radar, "fetch_sub_reddit_json", return_value={}),
            patch.object(radar, "_fetch_bytes", return_value=xml),
            patch.object(radar, "fetch_pullpush") as archive,
        ):
            signals, success = radar.collect_public_reddit_signals("SaaS")
        self.assertTrue(success)
        archive.assert_not_called()
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].source_channel, "reddit_rss:r/SaaS")
        self.assertEqual(signals[0].created_utc, "2026-01-01T00:00:00Z")
        self.assertNotIn("<p>", signals[0].body)

    def test_malformed_rss_advances_to_pullpush_archive(self):
        payload = {
            "data": [
                {
                    "id": "abc",
                    "subreddit": "SaaS",
                    "title": "Tired of manually reconciling invoices",
                    "selftext": "Workaround costs hours",
                    "created_utc": 1,
                }
            ]
        }
        with (
            patch.object(radar, "fetch_sub_reddit_json", return_value={}),
            patch.object(radar, "_fetch_bytes", return_value=b"<html>blocked</html>"),
            patch.object(radar, "_fetch_json", return_value=payload),
        ):
            signals, success = radar.collect_public_reddit_signals("SaaS")
        self.assertTrue(success)
        self.assertEqual(signals[0].source_channel, "pullpush_archive:r/SaaS")
        self.assertIn("1970", signals[0].created_utc)
        self.assertIn("api.pullpush.io", signals[0].ingestion_endpoint)

    def test_hn_tags_are_or_and_comments_have_canonical_source(self):
        payload = {
            "hits": [
                {
                    "objectID": "123",
                    "story_title": "Building tools",
                    "comment_text": "<p>I wish there was a tool for invoices</p>",
                    "created_at": "2025-01-01T00:00:00Z",
                    "author": "test",
                }
            ]
        }
        with patch.object(radar, "_fetch_json", return_value=payload) as fetch:
            signals, success = radar.fetch_hn_algolia()
        self.assertTrue(success)
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(fetch.call_args.args[0]).query
        )
        self.assertEqual(query["tags"], ["(story,comment)"])
        self.assertEqual(signals[0].source_channel, "hn_algolia")
        self.assertEqual(signals[0].url, "https://news.ycombinator.com/item?id=123")

    def test_global_hn_fallback_runs_once_and_preserves_coverage_warning(self):
        signal = radar.SourceSignal(
            "hn_algolia",
            "123",
            "Wish there was a tool for invoices",
            "Manual reconciliation",
            "test",
            "https://news.ycombinator.com/item?id=123",
            radar.utc_now(),
            "wish there was a tool",
            "https://hn.algolia.com/api/v1/search_by_date",
            radar.utc_now(),
        )
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scan.csv"
            with (
                patch.object(radar, "collect_reddit_signals", return_value=([], False)),
                patch.object(
                    radar, "fetch_hn_algolia", return_value=([signal, signal], True)
                ) as hn,
                contextlib.redirect_stdout(io.StringIO()) as log,
            ):
                status = radar.main(
                    [
                        "--output-csv",
                        str(target),
                        "--seen-state",
                        str(Path(folder) / "seen.json"),
                        "--diagnostics-json",
                        str(Path(folder) / "diagnostics.json"),
                        "--hn-query",
                        '"wish there was a tool"',
                    ]
                )
            hn.assert_called_once()
            self.assertEqual(status, 0)
            self.assertIn("Degraded", log.getvalue())
            with target.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Source_Channel"], "hn_algolia")
            self.assertEqual(rows[0]["Source_Created_UTC"], signal.created_utc)
            self.assertEqual(rows[0]["Retrieved_At_UTC"], signal.retrieved_at_utc)

    def test_valid_empty_feeds_differ_from_source_errors(self):
        with patch.object(radar, "_fetch_json", return_value={"hits": []}):
            self.assertEqual(radar.fetch_hn_algolia(), ([], True))
        with patch.object(radar, "_fetch_json", return_value={"error": "unavailable"}):
            self.assertEqual(radar.fetch_hn_algolia(), ([], False))
        with patch.object(radar, "_fetch_json", return_value={"data": "bad"}):
            self.assertEqual(radar.fetch_pullpush("SaaS"), ([], False))

    def test_archive_deleted_content_and_wrong_subreddit_are_ignored(self):
        with patch.object(
            radar,
            "_fetch_json",
            return_value={
                "data": [
                    {
                        "id": "abc",
                        "subreddit": "SaaS",
                        "title": "Wish there was a tool",
                        "selftext": "[deleted]",
                    },
                    {
                        "id": "def",
                        "subreddit": "other",
                        "title": "Wish there was a tool",
                    },
                ]
            },
        ):
            self.assertEqual(radar.fetch_pullpush("SaaS"), ([], True))


if __name__ == "__main__":
    unittest.main()
