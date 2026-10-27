import unittest
from unittest.mock import patch
from src.trend_engine import public_trend_rows, settings, collect_public_trends
from src.common.runtime import SourceUnavailable


class PublicTrendAdapterTests(unittest.TestCase):
    def test_baidu_nested_cards_and_pinned_header(self):
        data = {'success': True, 'data': {'cards': [{'content': [{'content': [
            {'word': 'Pinned headline', 'isTop': True}, {'word': 'Actual live keyword', 'index': 1}]}]}]}}
        rows = public_trend_rows('baidu', lambda url: data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title_cn'], 'Actual live keyword')
        self.assertIn('baidu.com', rows[0]['url'])

    def test_bilibili_actual_list_payload(self):
        rows = public_trend_rows('bilibili', lambda url: {'code': 0, 'list': [{'keyword': '手机芯片', 'heat_score': 123}]})
        self.assertEqual(rows[0]['raw_heat'], 123)
        self.assertEqual(rows[0]['source'], 'bilibili_public_trends')

    def test_toutiao_actual_payload(self):
        rows = public_trend_rows('toutiao', lambda url: {'data': [{'Title': '公开热词', 'HotValue': '2000', 'Url': 'https://www.toutiao.com/trending/1'}]})
        self.assertEqual(rows[0]['title_cn'], '公开热词')

    def test_malformed_or_denied_provider_is_failure_not_fake_data(self):
        for source, payload in [('baidu', {'success': False}), ('bilibili', {'code': -1}), ('toutiao', {'data': 'blocked'})]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                public_trend_rows(source, lambda url: payload)


class PublicTrendCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_needs_no_start_urls(self):
        self.assertEqual(settings({})['startUrls'], [])

    async def test_failed_first_provider_falls_through_to_real_second_provider(self):
        config = settings({'trendSources': ['baidu', 'bilibili']})
        def fetch(source):
            if source == 'baidu':
                raise OSError('unavailable')
            return [{'title_cn': '真实热词', 'url': 'https://example.com/trend', 'source': 'bilibili_public_trends',
                     'rank': 1, 'raw_heat': 1234, 'ingestion_endpoint': 'https://s.search.bilibili.com/main/hotword'}]
        with patch('src.trend_engine.public_trend_rows', side_effect=fetch):
            rows = [row async for row in collect_public_trends(config)]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['is_demo'])
        self.assertIsNone(rows[0]['price_rmb'])
        self.assertIsNone(rows[0]['price_usd_est'])

    async def test_all_providers_failed_raises_typed_error(self):
        with patch('src.trend_engine.public_trend_rows', side_effect=OSError('offline')):
            with self.assertRaises(SourceUnavailable):
                _ = [row async for row in collect_public_trends(settings({}))]

    async def test_successful_empty_provider_stays_empty(self):
        with patch('src.trend_engine.public_trend_rows', return_value=[]):
            self.assertEqual([row async for row in collect_public_trends(settings({}))], [])
