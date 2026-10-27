"""Multi-source collector reusing the original 4D evaluator and Reddit fallback chain."""
import asyncio
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .common.runtime import stable_id, integer, string_list, SourceUnavailable
from .common.urls import clean_url, fetch_bytes, fetch_json
from .vendor import pain_point_radar_engine as original
from .vendor import pain_point_radar_v3_anti_block as resilient

WEIGHTS = {'frustrating': 18, 'manual': 15, 'hours every week': 22, 'too expensive': 20,
           'broken': 16, 'wish there was': 25, 'hate': 15, 'workaround': 18,
           'spreadsheet': 14, 'api limit': 16, 'no tool': 24, 'alternative to': 20, 'painful': 18}


def compute_pain_score(title, text, points=0, comments=0):
    blob = (title + ' ' + text).lower()
    score = 25 + sum(weight for phrase, weight in WEIGHTS.items() if phrase in blob)
    return min(100, max(0, score + min(20, max(0, int(points or 0)) // 5)
                       + min(15, max(0, int(comments or 0)) // 3)))


def settings(data):
    mode = data.get('mode', 'online')
    if mode not in {'demo', 'offline', 'online'}:
        raise ValueError('mode must be demo, offline or online')
    sources = string_list(data.get('sources', ['hackernews', 'github_issues']), 'sources', 3)
    if not set(sources) <= {'hackernews', 'github_issues', 'reddit'}:
        raise ValueError('Unsupported source')
    subs = string_list(data.get('subreddits', ['SaaS', 'smallbusiness']), 'subreddits', 5)
    if any(not re.fullmatch(r'[A-Za-z0-9_]{1,21}', sub) for sub in subs):
        raise ValueError('Invalid subreddit')
    return dict(mode=mode, sources=sources, subreddits=subs,
                keywords=string_list(data.get('keywords', ['manual spreadsheet', 'wish there was a tool']), 'keywords', 10),
                maxItems=integer(data.get('maxItems', 20), 'maxItems', 1, 200),
                minPainScore=integer(data.get('minPainScore', 45), 'minPainScore', 0, 100))


def normalize(raw):
    title = raw.get('title', '')
    body = raw.get('text', '')
    if not isinstance(title, str) or not title.strip() or not isinstance(body, str):
        raise ValueError('Source record needs a title and text')
    source = raw['source']
    url = clean_url(raw['url'])
    score = compute_pain_score(title, body, raw.get('points', 0), raw.get('comments', 0))
    signal = original.RawSignal(source, str(raw.get('native_id', url)), title, body, '', url, '', '')
    evaluation = asdict(original.heuristic_evaluate_signal(signal))
    return dict(id=stable_id('pp_', url), source=source, title=title, snippet=body[:1000] or title,
                url=url, keyword_matched=raw.get('keyword', ''), pain_score=score,
                suggested_saas_angle=evaluation['mvp_solution_concept'],
                pain_to_revenue_score=evaluation['overall_score'],
                verdict=evaluation['verdict'] if raw.get('is_fixture') else 'WATCHLIST / human review required',
                scoring_method='deterministic heuristic; validate before investment',
                is_fixture=bool(raw.get('is_fixture', False)),
                ingestion_endpoint=raw.get('ingestion_endpoint', ''),
                extracted_at=datetime.now(timezone.utc).isoformat())


def hn_items(keyword, limit, get_json=fetch_json):
    endpoint = 'https://hn.algolia.com/api/v1/search_by_date?' + urlencode({
        'query': keyword, 'tags': '(story,comment)', 'hitsPerPage': limit})
    payload = get_json(endpoint)
    if not isinstance(payload, dict) or not isinstance(payload.get('hits'), list):
        raise ValueError('Invalid HN response')
    rows = []
    for hit in payload['hits']:
        if not isinstance(hit, dict) or not str(hit.get('objectID', '')).isdigit():
            continue
        rows.append(dict(source='hackernews', native_id=hit['objectID'],
                         title=hit.get('title') or hit.get('story_title') or '',
                         text=resilient.plain_text(hit.get('story_text') or hit.get('comment_text') or ''),
                         url='https://news.ycombinator.com/item?id=' + str(hit['objectID']),
                         points=hit.get('points') or 0, comments=hit.get('num_comments') or 0,
                         keyword=keyword, ingestion_endpoint=endpoint))
    return rows


def github_items(keyword, limit, get_json=fetch_json):
    endpoint = 'https://api.github.com/search/issues?' + urlencode({
        'q': keyword + ' is:issue is:open', 'per_page': min(limit, 100), 'sort': 'updated'})
    payload = get_json(endpoint)
    if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
        raise ValueError('Invalid GitHub response')
    return [dict(source='github_issues', native_id=item.get('id'), title=item.get('title') or '',
                 text=item.get('body') or '', url=item['html_url'],
                 comments=item.get('comments', 0), points=(item.get('reactions') or {}).get('total_count', 0),
                 keyword=keyword, ingestion_endpoint=endpoint)
            for item in payload['items'] if isinstance(item, dict) and item.get('html_url')]


def reddit_items(subreddit, limit):
    # Reuse original JSON -> Atom -> archive chain, replacing its transport with
    # size-limited, public-network validated requests. No proxy bypass or fake data.
    resilient._fetch_bytes = lambda url, retries=2: _legacy_fetch(url)
    signals, success = resilient.collect_reddit_signals(subreddit, retries=2, limit=min(limit, 100))
    if not success:
        raise RuntimeError('Reddit JSON, Atom and archive unavailable')
    return [dict(source='reddit', native_id=s.post_id, title=s.title, text=s.body,
                 url=s.url, ingestion_endpoint=s.ingestion_endpoint) for s in signals]


def _legacy_fetch(url):
    try:
        return fetch_bytes(url)
    except (OSError, ValueError):
        return None


def source_batches(config):
    for source in config['sources']:
        if source == 'reddit':
            for sub in config['subreddits']:
                yield source, lambda sub=sub: reddit_items(sub, config['maxItems'])
        else:
            fetcher = hn_items if source == 'hackernews' else github_items
            for keyword in config['keywords']:
                yield source, lambda keyword=keyword, fetcher=fetcher: fetcher(keyword, min(100, config['maxItems']))


async def collect(config, actor=None):
    diagnostics = []
    seen = set()
    count = 0
    successes = 0
    if config['mode'] in {'demo', 'offline'}:
        raw = json.loads((Path(__file__).parents[1] / 'fixtures/pain_points.json').read_text(encoding='utf-8'))
        batches = [('fixture', lambda: raw)]
    else:
        batches = source_batches(config)
    try:
        for source, fetcher in batches:
            try:
                rows = await asyncio.to_thread(fetcher)
                successes += 1
            except (OSError, ValueError, RuntimeError) as exc:
                diagnostics.append({'source': source, 'error_type': type(exc).__name__})
                continue
            for raw in rows:
                if config['mode'] in {'demo', 'offline'} and raw['source'] not in config['sources']:
                    continue
                try:
                    item = normalize(raw)
                except (ValueError, TypeError, KeyError):
                    diagnostics.append({'source': source, 'error_type': 'MalformedRecord'})
                    continue
                if item['id'] in seen or item['pain_score'] < config['minPainScore']:
                    continue
                seen.add(item['id'])
                yield item
                count += 1
                if count >= config['maxItems']:
                    return
        if not successes:
            raise SourceUnavailable('All configured public pain-point sources failed')
    finally:
        if actor:
            await actor.set_value('SOURCE_DIAGNOSTICS', diagnostics)


async def collect_fallback(config):
    config = dict(config, mode='offline', sources=['hackernews', 'github_issues', 'reddit'], minPainScore=0)
    async for item in collect(config):
        yield item
