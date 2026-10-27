"""Public HTML/JSON-LD product prototype; no login, synthetic live data or LLM cost."""
import asyncio
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlencode

from .common.runtime import stable_id, integer, string_list, SourceUnavailable
from .common.urls import clean_url, fetch_bytes, fetch_json

FIELDS = {'标题': 'title_cn', '商品名称': 'title_cn', 'title': 'title_cn', 'name': 'title_cn',
          '价格': 'price_rmb', '人民币价格': 'price_rmb', 'price': 'price_rmb',
          '热度': 'hot_score', 'hot': 'hot_score', '链接': 'url', '商品链接': 'url'}
WORDS = {'无线': 'wireless', '蓝牙': 'bluetooth', '耳机': 'earbuds', '便携': 'portable',
         '咖啡': 'coffee', '杯': 'cup', '智能': 'smart', '手表': 'watch', '手机': 'phone',
         '支架': 'stand', '收纳': 'storage', '桌面': 'desk', '灯': 'lamp', '充电': 'charging'}


def decimal_value(value, name, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(name + ' must be numeric')
    text = re.sub(r'^(?:CNY|RMB|[¥￥])\s*', '', str(value).strip(), flags=re.I)
    if ',' in text:
        if not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', text):
            raise ValueError('Invalid thousands separator')
        text = text.replace(',', '')
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(name + ' must be numeric') from exc
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0) or result > Decimal('1000000000'):
        raise ValueError(name + ' is outside its supported range')
    return result


def english_slug(title, overrides=None):
    overrides = overrides or {}
    if title in overrides:
        candidate = overrides[title]
        method = 'user_translation'
    else:
        candidate = title
        for word in sorted(WORDS, key=len, reverse=True):
            candidate = candidate.replace(word, ' ' + WORDS[word] + ' ')
        method = 'dictionary_keywords' if candidate != title else 'ascii_or_hash'
    tokens = re.findall(r'[a-z0-9]+', candidate.lower())
    if not tokens:
        return stable_id('cn-product-', title)[:27], 'hash_fallback'
    return '-'.join(tokens)[:120], method


def settings(data):
    mode = data.get('mode', 'online')
    if mode not in {'demo', 'offline', 'online'}:
        raise ValueError('mode must be demo, offline or online')
    raw_urls = data.get('startUrls', [])
    if not isinstance(raw_urls, list):
        raise ValueError('startUrls must be a list')
    urls = string_list(raw_urls, 'startUrls', 20) if mode == 'online' and raw_urls else []
    urls = [clean_url(url) for url in urls]
    if any(not url.startswith('https://') for url in urls):
        raise ValueError('Public collection requires HTTPS startUrls')
    backend = data.get('cleaningBackend', 'crawl4ai')
    if backend not in {'stdlib', 'crawl4ai'}:
        raise ValueError('Unknown cleaningBackend')
    mapping = data.get('titleTranslations', {})
    if not isinstance(mapping, dict) or len(mapping) > 200 or any(
            not isinstance(k, str) or not isinstance(v, str) or not v.strip() or len(k) > 500 or len(v) > 500
            for k, v in mapping.items()):
        raise ValueError('titleTranslations must map Chinese titles to English titles')
    keywords = data.get('keywords', [])
    if keywords:
        keywords = string_list(keywords, 'keywords', 20)
    elif not isinstance(keywords, list):
        raise ValueError('keywords must be a string list')
    trend_sources = string_list(data.get('trendSources', ['baidu', 'bilibili', 'toutiao']), 'trendSources', 3)
    if not set(trend_sources) <= {'baidu', 'bilibili', 'toutiao'}:
        raise ValueError('Unknown public trend source')
    return dict(mode=mode, startUrls=urls, trendSources=trend_sources, cleaningBackend=backend, titleTranslations=mapping,
                keywords=keywords, maxItems=integer(data.get('maxItems', 20), 'maxItems', 1, 200),
                rmbPerUsd=str(decimal_value(data.get('rmbPerUsd', '7.20'), 'rmbPerUsd')),
                fxRateAsOf=data.get('fxRateAsOf', 'user-supplied planning estimate; not a live rate'))


def normalize(raw, config):
    mapped = dict(raw)
    for source, target in FIELDS.items():
        if target not in mapped and source in mapped:
            mapped[target] = mapped[source]
    title = mapped.get('title_cn')
    if not isinstance(title, str) or not title.strip():
        raise ValueError('Missing title')
    title = title.strip()
    url = clean_url(mapped.get('clean_url') or mapped.get('url'))
    price = decimal_value(mapped.get('price_rmb'), 'price_rmb', allow_zero=True)
    rate = Decimal(config['rmbPerUsd'])
    usd = (price / rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    hot = decimal_value(mapped.get('hot_score', 0), 'hot_score', allow_zero=True)
    slug, method = english_slug(title, config['titleTranslations'])
    return dict(id=stable_id('trend_', url), title_cn=title, title_en_slug=slug,
                title_mapping_method=method, price_rmb=str(price), price_usd_est=str(usd),
                rmb_per_usd=str(rate), fx_rate_as_of=config['fxRateAsOf'],
                hot_score=float(min(Decimal(100), hot)), clean_url=url,
                is_fixture=bool(mapped.get('is_fixture', False)),
                extracted_at=datetime.now(timezone.utc).isoformat())


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jsonld = []
        self.meta = {}
        self.visible = []
        self.title = []
        self.script = None
        self.in_title = False
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script':
            self.script = [] if attrs.get('type', '').lower() == 'application/ld+json' else False
        if tag in {'style', 'nav', 'footer', 'noscript'}:
            self.suppressed += 1
        if tag == 'title':
            self.in_title = True
        if tag == 'meta':
            self.meta[attrs.get('property') or attrs.get('name') or ''] = attrs.get('content', '')

    def handle_endtag(self, tag):
        if tag == 'script':
            if isinstance(self.script, list):
                self.jsonld.append(''.join(self.script))
            self.script = None
        if tag in {'style', 'nav', 'footer', 'noscript'}:
            self.suppressed = max(0, self.suppressed - 1)
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if isinstance(self.script, list):
            self.script.append(data)
        elif self.script is None and not self.suppressed:
            self.visible.append(data)
            if self.in_title:
                self.title.append(data)


def clean_html(url, html, backend):
    if backend == 'crawl4ai':
        from crawl4ai import LXMLWebScrapingStrategy
        # HTML-only strategy: no browser, remote scripts or additional network fetches.
        result = LXMLWebScrapingStrategy().scrap(url, html, word_count_threshold=0,
                                               excluded_tags=['nav', 'footer', 'script', 'style'])
        if not result.success:
            raise ValueError('Crawl4AI HTML cleaning failed')
        return result.cleaned_html
    parser = PageParser()
    parser.feed(html)
    return ' '.join(parser.visible)


def _products(value):
    if isinstance(value, list):
        for item in value:
            yield from _products(item)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        if 'Product' in ([types] if isinstance(types, str) else types):
            yield value
        for key in ('@graph', 'itemListElement', 'item'):
            if key in value:
                yield from _products(value[key])


def extract_page(url, html, backend='stdlib'):
    parser = PageParser()
    parser.feed(html)
    cleaned = clean_html(url, html, backend)
    clean_parser = PageParser()
    clean_parser.feed(cleaned)
    text = re.sub(r'\s+', ' ', ' '.join(clean_parser.visible)).strip()
    rows = []
    for block in parser.jsonld:
        try:
            payload = json.loads(block)
        except ValueError:
            continue
        for product in _products(payload):
            offers = product.get('offers') or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if not isinstance(offers, dict):
                continue
            # Never assume USD or JPY prices are RMB.
            if offers.get('priceCurrency', '').upper() not in {'CNY', 'RMB'}:
                continue
            price = offers.get('price', offers.get('lowPrice'))
            if price is None:
                continue
            rating = product.get('aggregateRating') or {}
            rating_count = rating.get('ratingCount', rating.get('reviewCount', 0)) if isinstance(rating, dict) else 0
            try:
                hot = min(100, math.log10(max(0, float(rating_count)) + 1) * 25)
            except (ValueError, TypeError, OverflowError):
                hot = 0
            rows.append(dict(title_cn=product.get('name'), price_rmb=price, hot_score=hot,
                             url=urljoin(url, product.get('url') or offers.get('url') or url),
                             cleaned_excerpt=text[:500]))
    if rows:
        return rows
    currency = parser.meta.get('product:price:currency', '').upper()
    price = parser.meta.get('product:price:amount')
    title = parser.meta.get('og:title') or ''.join(parser.title).strip()
    if title and price is not None and currency in {'CNY', 'RMB'}:
        return [dict(title_cn=title, price_rmb=price, url=url, hot_score=0, cleaned_excerpt=text[:500])]
    return []


async def collect(config, actor=None, fetcher=fetch_bytes):
    if config['mode'] == 'online' and not config['startUrls']:
        async for row in collect_public_trends(config, actor):
            yield row
        return
    diagnostics, seen = [], set()
    successes = 0
    if config['mode'] in {'demo', 'offline'}:
        raw = json.loads((Path(__file__).parents[1] / 'fixtures/trends.json').read_text(encoding='utf-8'))
        batches = [('fixture', raw)]
    else:
        batches = [(url, None) for url in config['startUrls']]
    try:
        for url, raw in batches:
            if raw is None:
                try:
                    html = (await asyncio.to_thread(fetcher, url)).decode('utf-8-sig')
                    raw = await asyncio.to_thread(extract_page, url, html, config['cleaningBackend'])
                    successes += 1
                except (OSError, ValueError) as exc:
                    diagnostics.append({'error_type': type(exc).__name__, 'url_hash': stable_id('url_', url)})
                    continue
            else:
                successes += 1
            for row in raw:
                try:
                    item = normalize(row, config)
                except (ValueError, TypeError):
                    diagnostics.append({'error_type': 'MalformedProduct'})
                    continue
                if config['keywords'] and not any(k.lower() in (item['title_cn'] + ' ' + item['title_en_slug']).lower()
                                                  for k in config['keywords']):
                    continue
                if item['id'] in seen:
                    continue
                seen.add(item['id'])
                yield item
                if len(seen) >= config['maxItems']:
                    return
        if not successes:
            raise SourceUnavailable('All configured public product sources failed')
    finally:
        if actor:
            await actor.set_value('SOURCE_DIAGNOSTICS', diagnostics)


TREND_ENDPOINTS = {
    'baidu': 'https://top.baidu.com/api/board?platform=wise&tab=realtime',
    'bilibili': 'https://s.search.bilibili.com/main/hotword',
    'toutiao': 'https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc',
}


def _baidu_words(value):
    if isinstance(value, list):
        for row in value:
            yield from _baidu_words(row)
    elif isinstance(value, dict):
        if isinstance(value.get('word'), str) and not value.get('isTop'):
            yield value
        for key in ('data', 'cards', 'content'):
            if key in value:
                yield from _baidu_words(value[key])


def public_trend_rows(source, get_json=fetch_json):
    endpoint = TREND_ENDPOINTS[source]
    payload = get_json(endpoint)
    if not isinstance(payload, dict):
        raise ValueError('Trend response is not an object')
    if source == 'baidu':
        if payload.get('success') is not True or not isinstance(payload.get('data'), dict):
            raise ValueError('Baidu trend response failed')
        entries = list(_baidu_words(payload))
    elif source == 'bilibili':
        entries = payload.get('list') or (payload.get('data') or {}).get('trending', {}).get('list')
        if payload.get('code', 0) != 0 or not isinstance(entries, list):
            raise ValueError('Bilibili trend response failed')
    else:
        entries = payload.get('data')
        if not isinstance(entries, list):
            raise ValueError('Toutiao trend response failed')
    rows = []
    for position, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            continue
        title = entry.get('word') or entry.get('keyword') or entry.get('show_name') or entry.get('Title')
        if not isinstance(title, str) or not title.strip():
            continue
        if source == 'baidu':
            url = 'https://www.baidu.com/s?' + urlencode({'wd': title})
        elif source == 'bilibili':
            url = 'https://search.bilibili.com/all?' + urlencode({'keyword': title})
        else:
            url = entry.get('Url') or 'https://www.toutiao.com/search/?' + urlencode({'keyword': title})
        rows.append(dict(title_cn=title.strip(), url=url, rank=position,
                         raw_heat=entry.get('hotScore') or entry.get('HotValue') or entry.get('heat_score'),
                         source=source + '_public_trends', ingestion_endpoint=endpoint))
    return rows


async def collect_public_trends(config, actor=None):
    diagnostics, seen = [], set()
    successes = 0
    try:
        for source in config['trendSources']:
            try:
                rows = await asyncio.to_thread(public_trend_rows, source)
                successes += 1
            except (OSError, ValueError, RuntimeError) as exc:
                diagnostics.append(dict(source=source, error_type=type(exc).__name__))
                continue
            for row in rows:
                title = row['title_cn']
                if config['keywords'] and not any(keyword.lower() in title.lower() for keyword in config['keywords']):
                    continue
                url = clean_url(row['url'])
                identity = stable_id('trend_', url)
                if identity in seen:
                    continue
                seen.add(identity)
                slug, method = english_slug(title, config['titleTranslations'])
                yield dict(id=identity, title_cn=title, title_en_slug=slug, title_mapping_method=method,
                           record_type='public_trend_keyword', price_rmb=None, price_usd_est=None,
                           price_status='not applicable to a trend keyword; no product price fabricated',
                           hot_score=max(0, 100 - (row['rank'] - 1) * 2),
                           hot_score_method='rank-derived heuristic, not sales or growth rate',
                           rank=row['rank'], raw_heat=row['raw_heat'], clean_url=url,
                           source=row['source'], ingestion_endpoint=row['ingestion_endpoint'],
                           is_demo=False, is_fixture=False, rmb_per_usd=config['rmbPerUsd'],
                           fx_rate_as_of=config['fxRateAsOf'], extracted_at=datetime.now(timezone.utc).isoformat())
                if len(seen) >= config['maxItems']:
                    return
        if not successes:
            raise SourceUnavailable('All configured public trend APIs failed')
    finally:
        if actor:
            await actor.set_value('SOURCE_DIAGNOSTICS', diagnostics)


async def collect_fallback(config):
    config = dict(config, mode='offline', keywords=[])
    async for item in collect(config):
        yield item
