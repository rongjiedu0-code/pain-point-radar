# China Trend Radar: Live Public Trends and Product Data

Zero input now queries real public Baidu, Bilibili and Toutiao trend APIs, in that order. The Actor emits current keyword/rank snapshots with source endpoints and retrieval timestamps. If one source fails, it tries the next; only an all-source failure permits labeled free fallback examples.

```json
{"mode":"online","startUrls":[],"trendSources":["baidu","bilibili","toutiao"],"maxItems":3,"keywords":[]}
```

Keyword trend records have `record_type=public_trend_keyword`, `title_cn`, an approximate English keyword slug, `source`, `rank`, raw provider heat where available, a rank-derived heuristic and a clean source URL. They are not product listings: `price_rmb` and `price_usd_est` are **null**, never fabricated.

Provide public HTTPS product URLs in `startUrls` to select the original product-page extraction path. It supports CNY/RMB schema.org Product JSON-LD and price meta tags, with real Crawl4AI HTML cleaning, Chinese/English field mapping, URL tracking cleanup and Decimal USD estimates. It does not bypass logins or execute storefront scripts. The configurable RMB/USD rate is a planning assumption rather than a live quote; dictionary slugs are not full machine translations.

Set `OFFLINE_MODE=1` for explicit offline fixtures. Legacy demo/offline input modes alone do not disable live collection. All-source fallback rows are marked `is_demo=true`, `source=demo_fallback` and charged no custom events. A successful empty provider or unmatched filter remains empty.

Suggested pricing: `actor-start` $0.02 per real-result run and `trend-item-extracted` $0.005 per real trend/product record. Twenty real results produce $0.12 in custom event charges at these prices, before other applicable platform costs.

## Billing and fallback safety

The Actor charges `actor-start` only after its first real result exists, followed by one custom event per real item. Demo/fixture markers are checked before either charge; fallback-only runs never call `Actor.charge()`. Keep the default Dataset item event free. The SDK's short idempotency cache is supplemented with run-scoped KV receipts. Uncertain prior charges fail closed for reconciliation; a crash can duplicate an output row, so consumers should deduplicate on `id`.

If the Actor is not monetized yet, real results can be returned without custom PPE charges. In PPE mode both event definitions must be configured with positive flat prices. Suggested prices are configuration examples, not a claim that monetization or Store publication has already been enabled.

## Local verification

Python 3.11+: `pip install -r requirements-dev.txt`, then `python -m unittest discover -s tests -p "test_*.py" -v`.
Tests use deterministic HTTP boundaries and the real SDK local charging mode; a separate live acceptance probe checks actual public endpoints.
For an explicit free offline run, set `OFFLINE_MODE=1` and `ACTOR_TEST_PAY_PER_EVENT=true`, then run `python -m src`.
For real local collection, use `OFFLINE_MODE=0` with the SDK local test flag. Local simulated fees do not bill money; normal platform compute/storage terms apply when running in the cloud.

Each `.actor/actor.json` sets `dockerContextDir` to `..` relative to the definition so the standalone ZIP and a Git monorepo subdirectory use the same build context. Apache-2.0 attribution is retained in LICENSE, NOTICE and src/vendor.
