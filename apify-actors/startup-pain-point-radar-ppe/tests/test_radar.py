import asyncio
import json
import unittest
from unittest.mock import patch
from src import radar_engine as radar
from src.main import run_actor
from src.common.runtime import AmbiguousChargeError
from tests_support import FakeActor, simulated_live_sources
import os


class RadarTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {'OFFLINE_MODE': '0'}))
        self.enterContext(simulated_live_sources())

    async def test_real_collection_bills_start_plus_delivered_items(self):
        actor = FakeActor({'mode': 'online'})
        rows = await run_actor(actor)
        self.assertEqual(len(rows), 3)
        self.assertEqual([x['event_name'] for x in actor.events], ['actor-start'] + ['pain-point-extracted'] * 3)
        self.assertTrue(all(not row['is_fixture'] for row in rows))

    async def test_budget_at_last_paid_item_keeps_that_item(self):
        actor = FakeActor({'mode': 'online'}, max_events=2)
        self.assertEqual(len(await run_actor(actor)), 1)
        self.assertEqual(len(actor.events), 2)

    async def test_zero_budget_never_emits_or_charges_real_records(self):
        actor = FakeActor({'mode': 'online'}, max_events=0)
        self.assertEqual(await run_actor(actor), [])
        self.assertEqual(actor.events, [])

    async def test_start_only_budget_does_not_collect(self):
        actor = FakeActor({'mode': 'online'}, max_events=1)
        self.assertEqual(await run_actor(actor), [])
        self.assertEqual(len(actor.events), 1)

    async def test_restart_deduplicates_after_sdk_cache_expires(self):
        actor = FakeActor({'mode': 'online'})
        await run_actor(actor)
        actor.keys.clear()  # SDK TTL expiration must not permit a second bill.
        self.assertEqual(await run_actor(actor), [])
        self.assertEqual(len(actor.events), 4)
        self.assertEqual(len(actor.items), 3)

    async def test_failed_push_resumes_without_recharge(self):
        actor = FakeActor({'mode': 'online'})
        actor.fail_push = True
        with self.assertRaises(ConnectionError):
            await run_actor(actor)
        actor.fail_push = False
        actor.keys.clear()
        self.assertEqual(len(await run_actor(actor)), 3)
        self.assertEqual(len(actor.events), 4)

    async def test_ambiguous_charge_fails_closed_on_retry(self):
        actor = FakeActor({'mode': 'online'})
        actor.fail_charge = True
        with self.assertRaises(ConnectionError):
            await run_actor(actor)
        actor.fail_charge = False
        with self.assertRaises(AmbiguousChargeError):
            await run_actor(actor)
        self.assertEqual(actor.events, [])

    async def test_invalid_input_is_rejected_before_charge(self):
        for value in (0, -1, True, '20', 201):
            actor = FakeActor({'mode': 'online', 'maxItems': value})
            with self.assertRaises(ValueError):
                await run_actor(actor)
            self.assertEqual(actor.events, [])

    async def test_max_items_and_score_zero_are_respected(self):
        actor = FakeActor({'mode': 'online', 'maxItems': 1, 'minPainScore': 0})
        self.assertEqual(len(await run_actor(actor)), 1)

    async def test_online_failure_never_substitutes_fixtures(self):
        config = radar.settings({'mode': 'online', 'sources': ['hackernews']})
        with patch.object(radar, 'hn_items', side_effect=OSError('blocked')):
            with self.assertRaises(RuntimeError):
                _ = [x async for x in radar.collect(config)]

    async def test_online_empty_feed_is_valid_empty_result(self):
        config = radar.settings({'mode': 'online', 'sources': ['hackernews']})
        with patch.object(radar, 'hn_items', return_value=[]):
            self.assertEqual([x async for x in radar.collect(config)], [])

    async def test_duplicate_urls_across_keywords_and_sources_charge_once(self):
        rows = [{'source': 'hackernews', 'title': 'Wish there was a tool', 'text': 'manual workaround',
                 'url': 'https://example.com/post?id=1&utm_source=x'},
                {'source': 'github_issues', 'title': 'Title changed', 'text': 'manual workaround',
                 'url': 'https://example.com/post?id=1'}]
        actor = FakeActor({'sources': ['hackernews'], 'keywords': ['manual'], 'minPainScore': 0})
        with patch.object(radar, 'hn_items', return_value=rows):
            self.assertEqual(len(await run_actor(actor)), 1)
        self.assertEqual(len(actor.events), 2)


class AdapterTests(unittest.TestCase):
    def test_hn_preserves_comment_provenance_and_or_tags(self):
        urls = []
        def get(url):
            urls.append(url)
            return {'hits': [{'objectID': '123', 'story_title': 'Need a tool', 'comment_text': '<p>manual</p>'}]}
        rows = radar.hn_items('manual', 10, get)
        self.assertEqual(rows[0]['url'], 'https://news.ycombinator.com/item?id=123')
        self.assertEqual(rows[0]['text'], 'manual')
        self.assertIn('%28story%2Ccomment%29', urls[0])

    def test_github_search_is_issues_not_pull_requests(self):
        urls = []
        def get(url):
            urls.append(url)
            return {'items': [{'id': 1, 'html_url': 'https://github.com/a/b/issues/1', 'title': 'manual'}]}
        self.assertEqual(radar.github_items('manual', 5, get)[0]['source'], 'github_issues')
        self.assertIn('is%3Aissue', urls[0])

    def test_reddit_json_denial_falls_back_to_original_atom(self):
        xml = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>t3_abc</id><title>Wish there was a tool</title><content>manual</content></entry></feed>'
        with patch.object(radar.resilient, 'fetch_sub_reddit_json', return_value={}), patch.object(radar, 'fetch_bytes', return_value=xml):
            rows = radar.reddit_items('SaaS', 10)
        self.assertEqual(len(rows), 1)
        self.assertIn('old.reddit.com', rows[0]['ingestion_endpoint'])

    def test_original_veto_scoring_is_preserved(self):
        _, verdict = radar.original.calculate_pain_to_revenue_score(10, 10, 1, 10)
        self.assertTrue(verdict.startswith('DISCARD'))

    def test_score_bounds_and_clean_url_identity(self):
        self.assertEqual(radar.compute_pain_score('manual ' * 100, '', -10, -1), 40)
        self.assertEqual(radar.compute_pain_score(' '.join(radar.WEIGHTS), '', 100, 100), 100)
        base = {'source': 'hackernews', 'title': 'Manual task', 'text': '', 'url': 'https://example.com/x?id=1'}
        other = dict(base, title='Edited title', url=base['url'] + '&utm_campaign=x')
        self.assertEqual(radar.normalize(base)['id'], radar.normalize(other)['id'])

    def test_invalid_sources_and_subreddit(self):
        for data in ({'sources': ['other']}, {'subreddits': ['../SaaS']}, {'keywords': []}, {'mode': 'mock'}):
            with self.assertRaises(ValueError):
                radar.settings(data)


if __name__ == '__main__':
    unittest.main()
