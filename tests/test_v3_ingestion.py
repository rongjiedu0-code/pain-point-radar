"""Offline tests: no live requests and no claim of bypassing access controls."""

import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pain_point_radar_v3_anti_block as radar


class RadarTests(unittest.TestCase):
    def payload(self):
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "sample",
                            "title": "Tired of manually matching Stripe invoices",
                            "selftext": "Hours spent reconciling receipts",
                            "permalink": "/r/SaaS/comments/sample",
                            "created_utc": 0,
                        }
                    }
                ]
            }
        }

    def response(self, payload):
        return io.BytesIO(json.dumps(payload).encode())

    def test_retry_rate_limit_then_success(self):
        error = urllib.error.HTTPError(
            "https://example.com", 429, "rate limit", {"Retry-After": "7"}, None
        )
        with patch.object(
            radar.urllib.request,
            "urlopen",
            side_effect=[error, self.response(self.payload())],
        ) as request, patch.object(radar.time, "sleep") as sleep:
            self.assertEqual(
                radar.fetch_sub_reddit_json("SaaS", limit=9), self.payload()
            )
            self.assertEqual(sleep.call_args.args[0], 7)
            self.assertEqual(request.call_count, 2)
            self.assertIn("limit=9", request.call_args.args[0].full_url)

    def test_denied_requests_are_not_retried(self):
        error = urllib.error.HTTPError("https://example.com", 403, "denied", {}, None)
        with patch.object(
            radar.urllib.request, "urlopen", side_effect=error
        ) as request, patch.object(radar.time, "sleep") as sleep:
            self.assertEqual(radar.fetch_sub_reddit_json("SaaS"), {})
            request.assert_called_once()
            sleep.assert_not_called()

    def test_failure_preserves_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scan.csv"
            target.write_text("existing scan", encoding="utf-8")
            with patch.object(
                radar, "collect_reddit_signals", return_value=([], False)
            ), patch.object(radar, "fetch_hn_algolia", return_value=([], False)):
                self.assertEqual(
                    radar.main(["--subreddits", "SaaS", "--output-csv", str(target)]), 1
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "existing scan")

    def test_pipeline_exports_scored_real_source_and_partial_failure_status(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "scan.csv"
            signals = radar.signals_from_payload(self.payload(), "SaaS")
            with patch.object(
                radar,
                "collect_reddit_signals",
                side_effect=[(signals, True), ([], False)],
            ), patch.object(
                radar, "fetch_hn_algolia", return_value=([], False)
            ), contextlib.redirect_stdout(io.StringIO()) as out:
                code = radar.main(
                    [
                        "--subreddits",
                        "SaaS,SideProject",
                        "--output-csv",
                        str(target),
                        "--generate-tweet",
                    ]
                )
            self.assertEqual(code, 2)
            with target.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["Verdict"].startswith("PROCEED"))
            self.assertEqual(
                rows[0]["Source_URL"], "https://www.reddit.com/r/SaaS/comments/sample/"
            )
            self.assertEqual(rows[0]["Source_Channel"], "reddit_json:r/SaaS")
            self.assertIn("Opportunity Alert", out.getvalue())

    def test_bad_payload_and_subreddit(self):
        with self.assertRaises(ValueError):
            radar.fetch_sub_reddit_json("../bad")
        with patch.object(
            radar.urllib.request, "urlopen", return_value=self.response([])
        ):
            self.assertEqual(radar.fetch_sub_reddit_json("SaaS"), {})


if __name__ == "__main__":
    unittest.main()
