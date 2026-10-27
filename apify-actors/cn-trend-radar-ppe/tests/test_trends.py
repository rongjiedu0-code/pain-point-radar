import json
import threading
import unittest
import urllib.request
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.common.urls import clean_url, validate_public_url
from src.trend_engine import settings, normalize, english_slug, extract_page, clean_html, collect
from src.main import run_actor
from tests_support import FakeActor, simulated_live_sources
import os

HTML = (Path(__file__).parents[1] / 'fixtures/product.html').read_text(encoding='utf-8')


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.config = settings({'mode': 'offline', 'rmbPerUsd': '7.20'})

    def test_chinese_english_fields_and_decimal_price(self):
        row = normalize({'标题': '无线蓝牙耳机', '价格': '￥129.90', '热度': 87,
                         '链接': 'https://example.com/p?id=1&spm=abc'}, self.config)
        self.assertEqual(row['title_en_slug'], 'wireless-bluetooth-earbuds')
        self.assertEqual(row['price_rmb'], '129.90')
        self.assertEqual(row['price_usd_est'], '18.04')
        self.assertEqual(row['clean_url'], 'https://example.com/p?id=1')

    def test_price_rounding_and_explicit_rate(self):
        config = settings({'mode': 'offline', 'rmbPerUsd': '2'})
        row = normalize({'title': 'cup', 'price': '0.01', 'url': 'https://example.com/p'}, config)
        self.assertEqual(row['price_usd_est'], '0.01')
        self.assertIn('not a live rate', row['fx_rate_as_of'])

    def test_invalid_prices_and_rates(self):
        for value in ('NaN', 'Infinity', '-1', 'abc', '12,3', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize({'title': 'cup', 'price': value, 'url': 'https://example.com/p'}, self.config)
        for value in ('0', '-1', 'NaN'):
            with self.assertRaises(ValueError):
                settings({'mode': 'offline', 'rmbPerUsd': value})

    def test_tracking_cleaning_preserves_product_identity(self):
        url = 'https://EXAMPLE.com:443/item?sku=blue&id=123&utm_source=x&Spm=abc&fbclid=a#share'
        self.assertEqual(clean_url(url), 'https://example.com/item?id=123&sku=blue')
        self.assertEqual(clean_url(clean_url(url)), clean_url(url))

    def test_edited_title_and_tracking_do_not_change_id(self):
        base = {'title': 'old', 'price': '2', 'url': 'https://example.com/p?id=2'}
        changed = dict(base, title='new', url=base['url'] + '&utm_medium=cpc')
        self.assertEqual(normalize(base, self.config)['id'], normalize(changed, self.config)['id'])

    def test_slug_dictionary_translation_override_and_hash(self):
        self.assertEqual(english_slug('智能手表')[0], 'smart-watch')
        self.assertEqual(english_slug('未知商品')[1], 'hash_fallback')
        self.assertEqual(english_slug('未知商品', {'未知商品': 'Travel Bag'})[0], 'travel-bag')

    def test_clean_pipeline_removes_scripts_and_navigation(self):
        cleaned = clean_html('https://example.com', HTML, 'stdlib')
        self.assertNotIn('IGNORE_NAV', cleaned)
        self.assertNotIn('IGNORE_FOOTER', cleaned)
        self.assertNotIn('@context', cleaned)

    def test_real_crawl4ai_cleaning_retains_product_content(self):
        cleaned = clean_html('https://example.com', HTML, 'crawl4ai')
        self.assertIn('无线蓝牙耳机', cleaned)
        self.assertNotIn('IGNORE_NAV', cleaned)
        self.assertNotIn('IGNORE_FOOTER', cleaned)
        rows = extract_page('https://example.com/page', HTML, 'crawl4ai')
        self.assertEqual(rows[0]['price_rmb'], '129.90')

    def test_jsonld_product_extraction(self):
        rows = extract_page('https://example.com/page', HTML)
        self.assertEqual(rows[0]['title_cn'], '无线蓝牙耳机')
        self.assertEqual(rows[0]['price_rmb'], '129.90')
        self.assertGreater(rows[0]['hot_score'], 0)

    def test_non_cny_price_is_not_mislabeled(self):
        self.assertEqual(extract_page('https://example.com/p', HTML.replace('"CNY"', '"USD"')), [])

    def test_meta_fallback_and_relative_product_url(self):
        html = '<meta property="og:title" content="咖啡杯"><meta property="product:price:amount" content="72"><meta property="product:price:currency" content="CNY">'
        self.assertEqual(extract_page('https://example.com/p', html)[0]['title_cn'], '咖啡杯')

    def test_schema_org_graph_and_offer_array(self):
        html = '<script type="application/ld+json">' + json.dumps({'@graph': [{'@type': 'Product', 'name': '杯',
                   'offers': [{'price': '12', 'priceCurrency': 'CNY'}]}]}) + '</script>'
        self.assertEqual(len(extract_page('https://example.com/p', html)), 1)

    def test_invalid_url_and_ssrf_are_rejected(self):
        for url in ('file:///etc/passwd', 'https://name:pass@example.com/p', 'javascript:alert(1)', 'https://example.com/\\bad'):
            with self.assertRaises(ValueError):
                clean_url(url)
        for url in ('https://127.0.0.1/p', 'https://169.254.169.254/p', 'https://[::1]/p'):
            with self.assertRaises(ValueError):
                validate_public_url(url)


class LiveBillingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {'OFFLINE_MODE': '0'}))
        self.enterContext(simulated_live_sources())

    async def test_live_charges_one_event_per_unique_record(self):
        actor = FakeActor({'mode': 'online'})
        rows = await run_actor(actor)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(not row['is_fixture'] for row in rows))
        self.assertEqual([x['event_name'] for x in actor.events], ['actor-start'] + ['trend-item-extracted'] * 3)

    async def test_budget_stop_and_restart(self):
        actor = FakeActor({'mode': 'online'}, max_events=2)
        self.assertEqual(len(await run_actor(actor)), 1)
        actor.keys.clear()
        self.assertEqual(await run_actor(actor), [])
        self.assertEqual(len(actor.events), 2)

    async def test_keyword_filter_and_maxitems(self):
        actor = FakeActor({'mode': 'online', 'keywords': ['咖啡'], 'maxItems': 1})
        self.assertEqual((await run_actor(actor))[0]['title_cn'], '便携咖啡杯')
        self.assertEqual(len(actor.events), 2)

    async def test_online_failure_never_becomes_a_fixture(self):
        config = settings({'startUrls': ['https://example.com/p'], 'cleaningBackend': 'stdlib'})
        def broken(url):
            raise OSError('blocked')
        with self.assertRaises(RuntimeError):
            _ = [row async for row in collect(config, fetcher=broken)]


class OnlineHTTPTests(unittest.IsolatedAsyncioTestCase):
    """Real loopback HTTP transport, no external availability assumption or skips.

    Test supplies trusted transport explicitly; production input never enables loopback.
    """
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = HTML.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    async def test_online_http_fetch_parse_map_and_currency(self):
        config = settings({'startUrls': ['https://example.com/product'], 'cleaningBackend': 'stdlib'})
        def trusted_fetch(url):
            with urllib.request.urlopen('http://127.0.0.1:' + str(self.server.server_port), timeout=3) as response:
                return response.read()
        rows = [row async for row in collect(config, fetcher=trusted_fetch)]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['is_fixture'])
        self.assertEqual(rows[0]['price_usd_est'], '18.04')

    async def test_online_end_to_end_with_ppe_delivery(self):
        from src.common.runtime import execute
        actor = FakeActor({'startUrls': ['https://example.com/product'], 'cleaningBackend': 'stdlib'})
        def trusted_fetch(url):
            with urllib.request.urlopen('http://127.0.0.1:' + str(self.server.server_port), timeout=3) as response:
                return response.read()
        rows = await execute(actor, settings, lambda config: collect(config, actor, trusted_fetch),
                             'trend-item-extracted', 'cn-trend-radar-ppe')
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(actor.events), 2)


if __name__ == '__main__':
    unittest.main()
