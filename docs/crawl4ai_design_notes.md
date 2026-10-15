# Crawl4AI study and radar adaptations

Reviewed 2026-10-15: official unclecode/crawl4ai source and docs. This change uses design ideas, not copied code and not the Crawl4AI runtime. The default radar remains standard-library-only; no hosted API or browser installation is required.

## Sources and decisions
- [Content selection](https://docs.crawl4ai.com/core/content-selection/): scope extraction and remove irrelevant elements before filtering. Radar's HTML normalizer now excludes script/style/navigation/footer content, and only structured feed records become signals. A 200 response containing an HTML challenge is not an Atom-feed success.
- [CrawlResult model](https://github.com/unclecode/crawl4ai/blob/main/crawl4ai/models.py): distinguish status, extracted content and errors. Radar records per-request HTTP status, parser errors and per-source outcome in a JSON diagnostics file. HTTP 403 is not retried; 429 respects the existing bounded backoff policy.
- [RelevantContentFilter / BM25ContentFilter](https://github.com/unclecode/crawl4ai/blob/main/crawl4ai/content_filter_strategy.py): separate collection from relevance filtering. Radar adds a transport-independent freshness/deduplication/review stage. Keyword relevance cannot establish payment intent or identify sarcasm reliably. All live heuristic scores are WATCHLIST and require human review; obvious irony markers receive an additional review reason. This is not semantic/LLM analysis.
- [Cache modes](https://docs.crawl4ai.com/core/cache-modes/): caching policy should be explicit. Radar fetches live feeds and stores seen source URLs separately from its latest output. The seen ledger is deduplication state, not a page cache. A 30-day publication window prevents old archived posts from being reintroduced as new leads.
- [HN API](https://hn.algolia.com/api): apply numericFilters to publication timestamps, and use three bounded intent queries to improve discovery. A second local timestamp check also filters Reddit/archive results and invalid/future dates.

## Why no browser fallback yet

Current public transport: Atom → Arctic Shift archive (up to four pages per subreddit), with optional OAuth. This supersedes the earlier OAuth-only experiment. Cloud `sources-check` must independently demonstrate recent Reddit-origin and HN exports before merge; it does not claim RSS is usable when the upstream returns HTML.
The observed failure is blocked/malformed public feeds, not a demonstrated JavaScript rendering requirement. Installing Crawl4AI cannot promise authenticated Reddit coverage. An optional browser adapter can be evaluated when a permitted target actually needs rendering; existing HTTP/Atom/archive/HN sources remain explicit and independently diagnosed.

## State and output contract
- `radar_latest_scan.csv`: only new, recent leads for this run; successful zero-new-lead scans replace it with a header-only file. Prior leads remain in Git history and Actions artifacts.
- `radar_seen.json`: cumulative seen canonical source URLs and retrieval timestamps, committed by Actions. Existing CSV URLs bootstrap state; exported URLs survive later empty scans. If state is malformed the job fails instead of silently re-alerting everything.
- State is updated after the atomic CSV replacement. On restart, prior CSV URLs repair a missed state update. A failed fetch of every source preserves the prior CSV and seen ledger; diagnostics say `csv_preserved=true`.
- IDs are SHA-256-derived from canonical source URL and remain stable when sorting changes. No automatic social alert is produced from unverified heuristic scores.
- `radar_diagnostics.json`: request outcomes, parser errors, coverage status, filtered counts and new export count. `exit_code=0` with `coverage=degraded` means a fallback worked, not that requested Reddit communities were covered.

Known limits: no authenticated Reddit adapter, no complete HN pagination, no cross-post semantic deduplication, no verified willingness-to-pay model. The three HN queries are bounded to at most `3 * --limit` records before filtering; users can repeat `--hn-query` up to five times to change coverage.
