import unittest
import urllib.parse
from unittest.mock import patch

import pain_point_radar_v3_anti_block as radar


class PublicSourceTests(unittest.TestCase):
    def test_namespaced_atom_updated_link_and_html_content(self):
        xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>opaque-feed-id</id><title>Tired of manually matching invoices</title>
        <content type="html">&lt;p&gt;Daily spreadsheet work&lt;/p&gt;</content>
        <link href="https://www.reddit.com/r/SaaS/comments/abc123/title/"/>
        <updated>2026-10-14T12:00:00Z</updated></entry></feed>"""
        with patch.object(radar, "_fetch_bytes", return_value=xml):
            signals, success = radar.fetch_reddit_rss("SaaS")
        self.assertTrue(success)
        self.assertEqual(signals[0].post_id, "abc123")
        self.assertEqual(signals[0].created_utc, "2026-10-14T12:00:00Z")
        self.assertEqual(
            signals[0].url, "https://www.reddit.com/r/SaaS/comments/abc123/"
        )
        self.assertIn("Daily spreadsheet", signals[0].body)
        self.assertNotIn("<p>", signals[0].body)

    def test_arctic_window_and_archive_provenance(self):
        payload = {
            "data": [
                {
                    "id": "t3_abc123",
                    "subreddit": "SaaS",
                    "title": "Tired of manually matching invoices",
                    "selftext": "Daily work",
                    "created_utc": radar.time.time(),
                }
            ]
        }
        with patch.object(radar, "_fetch_json", return_value=payload) as fetch:
            signals, success = radar.fetch_arctic_shift("SaaS", limit=25)
        self.assertTrue(success)
        self.assertEqual(signals[0].source_channel, "arctic_shift_archive:r/SaaS")
        url = urllib.parse.urlsplit(fetch.call_args.args[0])
        query = urllib.parse.parse_qs(url.query)
        self.assertEqual(url.hostname, "arctic-shift.photon-reddit.com")
        self.assertEqual(query["limit"], ["25"])
        self.assertAlmostEqual(
            int(query["after"][0]), radar.time.time() - 30 * 86400, delta=2
        )

    def test_bad_or_cross_community_atom_link_is_rejected(self):
        for href in (
            "https://evil.example/r/SaaS/comments/abc/",
            "https://www.reddit.com/r/other/comments/abc/",
        ):
            xml = f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>t3_abc</id><title>Tired of manually invoicing</title><link href="{href}"/></entry></feed>'.encode()
            with patch.object(radar, "_fetch_bytes", return_value=xml):
                self.assertEqual(radar.fetch_reddit_rss("SaaS"), ([], True))
