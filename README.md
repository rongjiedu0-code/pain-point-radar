<!-- APIFY-PHASE3-START -->
[![Deploy to Apify Store](https://img.shields.io/badge/Apify_Store-Deploy_Actor-orange)](https://console.apify.com/actors)
[![Connect via Apify MCP](https://img.shields.io/badge/Connect_via-Apify_MCP-blue)](https://docs.apify.com/mcp)
[![Apify tests and deployment](https://github.com/rongjiedu0-code/pain-point-radar/actions/workflows/deploy-apify.yml/badge.svg)](https://github.com/rongjiedu0-code/pain-point-radar/actions/workflows/deploy-apify.yml)

## Apify Actors: live collection and analysis

| Actor | Code | Default mode |
|---|---|---|
| `startup-pain-point-radar-ppe` | [Source](apify-actors/startup-pain-point-radar-ppe) | `online` |
| `cn-trend-radar-ppe` | [Source](apify-actors/cn-trend-radar-ppe) | `online` |

Zero input now performs real public API collection or real AST/regex analysis. Set the Actor environment variable `OFFLINE_MODE=1` only for explicit offline demonstration. When every configured public source fails, fallback rows are clearly marked `is_demo=true`, `source=demo_fallback`; they bypass **all** `Actor.charge()` calls, including startup billing. A successful empty search remains empty. Static audit findings map to CWE; CVE identifiers are not invented.

Import this repository in Apify Console. The root `.actor` configuration builds `startup-pain-point-radar-ppe`; the other Actor, if listed above, can use `#main:apify-actors/<actor-name>`. Every Actor has its own build context, schema and Dockerfile. The original local CLI remains available; these optional Actor packages have separate SDK requirements.

```bash
cd apify-actors/startup-pain-point-radar-ppe
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
npx --yes apify-cli@latest push
```

GitHub Actions runs the Actor tests and schema checks on main updates. Add the `APIFY_TOKEN` repository Actions secret to enable actual cloud deployment; without it deployment is explicitly skipped. This badge is a deployment entry point, not a claim that a public Store listing already exists. Configure PPE pricing and publish the Store page in Console. Once published with appropriate access, run the Actor through [Apify MCP](https://docs.apify.com/mcp); no standalone native MCP server is claimed for the batch Actor.
<!-- APIFY-PHASE3-END -->

# 📡 Pain Point Radar (深雷达) — Automated SaaS Pain Discovery & 4D Scoring Engine

[![AI Agent & Pain Point Radar Autopilot](https://github.com/rongjiedu0-code/pain-point-radar/actions/workflows/autopilot.yml/badge.svg)](https://github.com/rongjiedu0-code/pain-point-radar/actions/workflows/autopilot.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)
![Zero Dependencies](https://img.shields.io/badge/Dependencies-Stdlib_Only-orange.svg)

> **Stop guessing what to build. Start quantifying real user frustration.**
> **别再凭空猜需求，用真实用户的痛点为产品方向排序。**

Pain Point Radar reads public Reddit Atom feeds, falls back to the separately labeled Arctic Shift archive, and collects HN Algolia signals. It filters explicit workflow complaints and ranks candidates for manual review. The default public transport needs no API key; OAuth is optional. Everything uses Python's standard library.

### Freshness and review update

Live scans now apply a **30-day publication window**, persist canonical URLs in `radar_seen.json`, use stable URL-derived IDs, and export **only new leads**. A successful scan with no new leads writes a header-only CSV. All live rule-scored leads are labeled **WATCHLIST / human review required**; keyword scores do not demonstrate willingness to pay, and `--generate-tweet` no longer produces an unverified opportunity alert. The V2/mock numeric formula below remains a heuristic reference.

`radar_diagnostics.json` records HTTP/parser failures, source coverage, filter counts and export count. A successful HN fallback can still have `coverage=degraded`; it does not restore Reddit coverage. HTTP 200 with a non-Atom body is diagnosed as a parser/source failure.

借鉴 [Crawl4AI 的内容筛选与结构化结果设计](docs/crawl4ai_design_notes.md)，保持标准库采集；未引入浏览器或付费 API。每条线索需人工核对语境、真实替代成本与付费证据。

```bash
python pain_point_radar_v3_anti_block.py --max-age-days 30 --seen-state radar_seen.json --diagnostics-json radar_diagnostics.json
# Custom intent queries (up to five); defaults cover three English intent phrases.
python pain_point_radar_v3_anti_block.py --hn-query '"tired of manually"' --hn-query '"looking for a tool"'
```

Keep the seen ledger between runs. An existing CSV bootstraps it; do not delete the ledger unless intentionally resetting deduplication. CSV, ledger and diagnostics paths must be distinct and their parent directories must exist.

默认采集链路为 Reddit Atom RSS → Arctic Shift 归档，HN 作为独立来源同步采集（Actions 使用 `--always-hn`）。Atom 解析命名空间下 title/content/link，并优先 published、缺失时使用 updated；归档请求带近30天 after 筛选。每条结果保留来源与时间，评分需人工验证。归档可用不等于 Reddit 官方实时接口恢复。

**Acceptance:** Actions `sources-check` independently fetches and exports recent Reddit-origin and HN signals; it fails unless both have at least one recent record. Results are in `radar_sources_check.csv/json` artifacts. HTTP200 containing HTML fails Atom validation. Source unavailability is never replaced with mock data. `--check-reddit` tests the selected transport only; `--require-reddit` fails a live scan when requested Reddit coverage is incomplete. Optional OAuth instructions are in [中文接入说明](docs/reddit_setup_zh.md).

## 🧮 1. The 4D Pain-to-Revenue Scoring Formula / 四维评分

Each dimension uses a 1–10 scale; the weighted score has a maximum of 100.

$$\text{Score} = (I \times 3.0) + (W \times 2.5) + (P \times 2.5) + (C \times 2.0)$$

| Dimension / 维度 | Weight | 1–3 (Low Signal) | 4–7 (Moderate Friction) | 8–10 (Strong Need) |
| :--- | :--- | :--- | :--- | :--- |
| **Pain Intensity / 痛感 ($I$)** | **30%** | Mild annoyance | Slows daily workflow | Revenue loss, liability, or outage |
| **Workaround Cost / 替代成本 ($W$)** | **25%** | Free one-click tool exists | Multiple brittle tools | Hours of manual work weekly |
| **Ecosystem Budget / 付费能力 ($P$)** | **25%** | Freebie seekers; veto at ≤ 2 | Indie developer budgets | SMB and B2B budgets |
| **Competitive Whitespace / 竞品空白 ($C$)** | **20%** | Strong free incumbent; veto at ≤ 2 | Bloated enterprise tools | Underserved vertical workflow |

The table is an interpretation guide. Current code assigns preset dimension values by keyword category rather than independently measuring willingness to pay or competition.

以上为评分解释口径；当前代码根据关键词类别分配预设分值，并未独立测量每条线索的付费能力或竞争格局。

### Verdict thresholds / 判定阈值

- **PROCEED (≥ 75.0)**: Prioritize for validation / 优先验证。
- **WATCHLIST (60.0–74.9)**: Gather stronger evidence / 继续观察。
- **DISCARD (< 60.0, or veto)**: Drop from the shortlist / 放弃或暂缓。
- **Veto / 一票否决**: $P \leq 2$ or $C \leq 2$ overrides the numeric score.

## ⚡ 2. Quick Start / 零依赖启动

Use Python 3.11+; no pip packages or API keys are required for the default public transport. Explicit `--reddit-transport oauth` requires approved OAuth configuration.

```bash
git clone https://github.com/rongjiedu0-code/pain-point-radar.git
cd pain-point-radar

# Offline demonstration with synthetic signals / 离线模拟演示
python3 pain_point_radar_v3_anti_block.py --mock-self-test

# Live Reddit scan / 实时扫描
python3 pain_point_radar_v3_anti_block.py --subreddits SaaS,smallbusiness,SideProject --limit 15 --output-csv radar_latest_scan.csv

# Legacy flag: reports that human review is required / 提示人工审核门禁
python3 pain_point_radar_v3_anti_block.py --limit 20 --generate-tweet
```

On Windows, use `python` if `python3` is unavailable.

Outputs: `radar_latest_scan.csv`, `radar_seen.json` and `radar_diagnostics.json` for live scans; `pain_point_radar_batch_test.csv` for the offline demonstration. Mock drafts are synthetic demonstrations; nothing is posted to X automatically.

Reddit may reject requests or return no matching signals. Check fetch errors and the CSV before interpreting an empty result as an absence of demand.

### V3.1 multi-source resilience / 多源回退已就绪

[`pain_point_radar_v3_anti_block.py`](pain_point_radar_v3_anti_block.py) now implements the complete scan → intent filter → scoring → CSV/draft CLI. Syntax and offline regression tests pass.

- `--retries 3` sets a bounded attempt count (1–5); transient HTTP 429/5xx and network failures use exponential backoff with jitter.
- Numeric `Retry-After` is respected; waits above 60 seconds stop the source instead of retrying early. HTTP 403 and other non-retryable responses stop immediately.
- Exit status: **0** successful collection, including valid empty feeds or successful HN fallback; **1** all sources failed; **2** partial source failure with no successful HN fallback, or invalid CLI input. HN fallback success is explicitly marked as degraded subreddit coverage. If all sources fail, the existing CSV is preserved.
- The V3 entry point requires `pain_point_radar_engine.py`, `radar_quality.py` and `reddit_oauth.py` beside it. Default `--reddit-transport public` uses Atom then Arctic Shift. `--reddit-transport oauth` retains the optional token-based path. HN runs when Reddit is unavailable, no fresh unseen signals exist, or `--always-hn` is set. Repeat `--hn-query` up to five times to override the three default intent queries; `--limit` applies per query, not to combined output.
- HN uses `tags=(story,comment)` (OR), per the [Algolia API documentation](https://hn.algolia.com/api). HN is a separate community, not replacement coverage of a requested subreddit. Arctic Shift is a third-party archive, not the official live API; bounded pagination examines at most four pages per requested community when intent matches are sparse.
- CSV adds `Source_Channel`, `Source_Post_ID`, `Source_Created_UTC`, `Retrieved_At_UTC`, `Ingestion_Endpoint`, `Scoring_Method`, `Review_Status` and `Review_Reason`. `Source_URL` points to the original Reddit/HN discussion. Archives retain their original publication dates and are labeled `arctic_shift_archive`; old, missing-date and implausibly future-dated results are filtered out.
- Logs report actual HTTP responses and the selected source. There is no proxy rotation, rate-limit bypass, guaranteed HTTP 200, Gemini analysis, V2EX integration, or Markdown summary generation.

V3.1 已接通多源回退、评分、溯源和导出。遇到单源拒绝会停止请求该源并尝试其他公开来源，不伪装模拟数据；是否可用以每次运行日志为准，归档数据不等于刚发布的数据。

```bash
python3 -m py_compile pain_point_radar_v3_anti_block.py
python3 -m unittest discover -s tests -v
```

## 🏆 3. Opportunity Showcase / 方案中的机会示例

The following entries come from the accompanying project brief. They are illustrative opportunity candidates, not verified live scan results or validated revenue opportunities; supporting source links and scoring records are not bundled in this repository.

以下保留项目方案中的展示条目；其来源链接和评分明细尚未随仓库提供，不代表已验证的实时发现或商业收益。

| ID | Brief score | Verdict | Category | Opportunity |
| :--- | :--- | :--- | :--- | :--- |
| **PR-007** | **86.0** | PROCEED | FinOps / Local OCR | Privacy-first receipt extraction and payment reconciliation |
| **PR-001** | **83.5** | PROCEED | Vertical Compliance | Digital intake and liability waivers for appointment businesses |
| **PR-008** | **80.0** | PROCEED | Agent Context | Shared AGENTS.md context synchronization via Git hooks |
| **PR-002** | **77.5** | PROCEED | Remote Agent DevTools | Mobile CLI relay for reviewing local coding-agent work |
| **PR-003** | **76.0** | PROCEED | Growth Automation | Buyer-intent listener for Reddit/HN discussions |

The bundled mock run uses synthetic records starting at **PR-011**; those records are separate from this showcase.

## 🤖 4. Cloud Autopilot / GitHub Actions 自动巡航

See [autopilot.yml](.github/workflows/autopilot.yml). Actions now runs the **V3** CLI for scheduled, push, and manual runs.

1. Daily run at **00:00 UTC / 北京时间 08:00**, pushes to main, and manual dispatch.
2. Syntax and offline regression checks before collection.
3. V3 live Reddit scan → freshness/deduplication → heuristic scoring → review-required CSV export, or an explicitly selected **mock** demonstration. No automatic fallback from live failures to mock data.
4. Job Summary and downloadable log/CSV artifacts preserve the selected mode and exit status. Partial/all-source failures fail the job; partial results remain available.
5. Changed CSV, seen-state and diagnostics files are committed back to the selected branch. Commit/push errors remain visible instead of being suppressed. Logs, CSV and state/diagnostics are retained in Actions artifacts.

Actions 已切换到 V3。实时失败会明确显示，不再用模拟结果替代；手动 mock 模式单独标记。任务并发按分支串行执行，避免自动提交互相覆盖。

## 🛠️ 5. Roadmap / 后续规划

- V2EX ingestion and more configurable source coverage (Reddit Atom, Arctic Shift and HN Algolia are implemented).
- Gemini / local Ollama analysis and Markdown summary output.
- Evidence-backed scoring with traceable sources and human validation.

These integrations are planned; the current CLI does not implement `--summary-md` or Gemini API calls.

## License / 许可证

[Apache License 2.0](LICENSE). Built by [度溶解 / rongjiedu0-code](https://github.com/rongjiedu0-code).

