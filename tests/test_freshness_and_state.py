"""Regression coverage for repeated runs, stale feeds and false confidence."""

import contextlib
import csv
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pain_point_radar_v3_anti_block as radar
import radar_quality as quality


def signal(url="https://news.ycombinator.com/item?id=123", age=1, body=None):
    return radar.SourceSignal(
        "hn_algolia",
        "123",
        "Tools",
        body or "Tired of manually matching invoices every day",
        "test",
        url,
        (dt.datetime.now(quality.UTC) - dt.timedelta(days=age)).isoformat(),
        "tired of manually",
        "https://hn.algolia.com/api/v1/search_by_date",
        radar.utc_now(),
    )


class QualityTests(unittest.TestCase):
    def test_freshness_rejects_old_invalid_and_future_dates(self):
        fresh = signal()
        invalid = signal("invalid")
        invalid.created_utc = "not-a-date"
        selected, counts = quality.select_fresh(
            [fresh, fresh, signal("old", 31), signal("future", -1), invalid], {}, 30
        )
        self.assertEqual(selected, [fresh])
        self.assertEqual(
            counts, {"duplicate": 1, "stale": 1, "invalid_date": 1, "future": 1}
        )

    def test_cleaning_excludes_navigation_scripts_and_styles(self):
        self.assertEqual(
            radar.plain_text(
                "<nav>wish there was a tool</nav><script>bad()</script><style>bad</style><p>real</p>"
            ),
            "  real",
        )

    def test_html_200_is_not_feed_success(self):
        with patch.object(radar, "_fetch_bytes", return_value=b"<html>blocked</html>"):
            self.assertEqual(radar.fetch_reddit_rss("SaaS"), ([], False))
        self.assertEqual(radar.FETCH_EVENTS[-1]["error"], "unexpected_atom_root")

    def test_hn_query_includes_server_publication_window(self):
        import urllib.parse

        with patch.object(radar, "_fetch_json", return_value={"hits": []}) as fetch:
            radar.fetch_hn_algolia(max_age_days=7)
        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(fetch.call_args.args[0]).query
        )
        cutoff = int(query["numericFilters"][0].split(">")[1])
        self.assertAlmostEqual(cutoff, radar.time.time() - 7 * 86400, delta=2)

    def test_irony_cannot_trigger_unverified_opportunity_alert(self):
        item = signal(
            body="I wish there was a tool to share my documents with intelligence agencies"
        )
        evaluated = quality.evaluate(item)
        self.assertTrue(evaluated.verdict.startswith("WATCHLIST"))
        self.assertIn("possible_irony", evaluated.scoring_rationale)
        self.assertEqual(evaluated.id, quality.stable_id(item.url))

    def test_three_runs_preserve_seen_even_after_empty_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = [
                "--output-csv",
                str(root / "scan.csv"),
                "--seen-state",
                str(root / "seen.json"),
                "--diagnostics-json",
                str(root / "diag.json"),
                "--generate-tweet",
            ]
            item = signal()
            for expected in (1, 0, 0):
                with (
                    patch.object(
                        radar, "collect_reddit_signals", return_value=([item], True)
                    ),
                    patch.object(radar, "fetch_hn_algolia", return_value=([], True)),
                    contextlib.redirect_stdout(io.StringIO()) as log,
                ):
                    self.assertEqual(radar.main(args), 0)
                with (root / "scan.csv").open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), expected)
                self.assertNotIn("Opportunity Alert", log.getvalue())
            self.assertIn(
                item.url, json.loads((root / "seen.json").read_text())["seen"]
            )
            self.assertEqual(
                json.loads((root / "diag.json").read_text())["exported"], 0
            )

    def test_failed_sources_preserve_both_csv_and_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output, state, diag = (
                root / "scan.csv",
                root / "seen.json",
                root / "diag.json",
            )
            output.write_text("Source_URL\nhttps://example.com/old\n", encoding="utf-8")
            state.write_text('{"version":1,"seen":{"https://example.com/a":"now"}}')
            before = (output.read_bytes(), state.read_bytes())
            with (
                patch.object(radar, "collect_reddit_signals", return_value=([], False)),
                patch.object(radar, "fetch_hn_algolia", return_value=([], False)),
            ):
                self.assertEqual(
                    radar.main(
                        [
                            "--output-csv",
                            str(output),
                            "--seen-state",
                            str(state),
                            "--diagnostics-json",
                            str(diag),
                        ]
                    ),
                    1,
                )
            self.assertEqual(before, (output.read_bytes(), state.read_bytes()))
            self.assertTrue(json.loads(diag.read_text())["csv_preserved"])

    def test_existing_csv_repairs_seen_and_malformed_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            csv_path, state = root / "scan.csv", root / "seen.json"
            csv_path.write_text(
                "Source_URL,Retrieved_At_UTC\nhttps://example.com/a,now\n"
            )
            self.assertIn("https://example.com/a", quality.load_seen(state, csv_path))
            state.write_text("{broken")
            with self.assertRaises(ValueError):
                quality.load_seen(state, csv_path)


if __name__ == "__main__":
    unittest.main()
