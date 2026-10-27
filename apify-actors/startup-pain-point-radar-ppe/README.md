# Startup Pain-Point & SaaS Idea Radar

Zero input now fetches real public Hacker News Algolia and GitHub Issues results. Reddit's JSON/Atom/archive adapters remain available when explicitly selected. Results preserve the source URL and retrieval endpoint and use explainable complaint/scoring heuristics for research.

```json
{"mode":"online","keywords":["manual spreadsheet","wish there was a tool"],"sources":["hackernews","github_issues"],"maxItems":3,"minPainScore":45}
```

`OFFLINE_MODE=1` is the explicit environment switch for offline examples. Legacy `mode=demo` or `mode=offline` input cannot silently keep a cloud run static. If every configured public source fails, the Actor may return clearly labeled free fallback rows: `is_demo=true`, `is_fixture=true`, `source=demo_fallback`, plus a fallback reason. A successful empty search stays empty.

Each real result has `title`, `snippet`, `source`, `url`, `ingestion_endpoint`, `pain_score`, the original heuristic 4D score and a SaaS angle. Live verdicts are **WATCHLIST / human review required**. A keyword score does not establish willingness to pay, competitive whitespace or a validated startup opportunity.

Suggested pricing: `actor-start` $0.02 per real-result run; `pain-point-extracted` $0.008 per real extracted record. Twenty real results would produce $0.18 in custom event charges at those prices; other platform terms may apply.

## Billing and fallback safety

The Actor charges `actor-start` only after its first real result exists, followed by one custom event per real item. Demo/fixture markers are checked before either charge; fallback-only runs never call `Actor.charge()`. Keep the default Dataset item event free. The SDK's short idempotency cache is supplemented with run-scoped KV receipts. Uncertain prior charges fail closed for reconciliation; a crash can duplicate an output row, so consumers should deduplicate on `id`.

If the Actor is not monetized yet, real results can be returned without custom PPE charges. In PPE mode both event definitions must be configured with positive flat prices. Suggested prices are configuration examples, not a claim that monetization or Store publication has already been enabled.

## Local verification

Python 3.11+: `pip install -r requirements-dev.txt`, then `python -m unittest discover -s tests -p "test_*.py" -v`.
Tests use deterministic HTTP boundaries and the real SDK local charging mode; a separate live acceptance probe checks actual public endpoints.
For an explicit free offline run, set `OFFLINE_MODE=1` and `ACTOR_TEST_PAY_PER_EVENT=true`, then run `python -m src`.
For real local collection, use `OFFLINE_MODE=0` with the SDK local test flag. Local simulated fees do not bill money; normal platform compute/storage terms apply when running in the cloud.

Each `.actor/actor.json` sets `dockerContextDir` to `..` relative to the definition so the standalone ZIP and a Git monorepo subdirectory use the same build context. Apache-2.0 attribution is retained in LICENSE, NOTICE and src/vendor.
