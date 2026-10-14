# 📡 Pain Point Radar (深雷达) — Automated SaaS Pain Discovery & 4D Scoring Engine

[![AI Agent & Pain Point Radar Autopilot](https://github.com/rongjiedu0-code/pain-point-radar/actions/workflows/autopilot.yml/badge.svg)](https://github.com/rongjiedu0-code/pain-point-radar/actions/workflows/autopilot.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)
![Zero Dependencies](https://img.shields.io/badge/Dependencies-Stdlib_Only-orange.svg)

> **Stop guessing what to build. Start quantifying real user frustration.**
> **别再凭空猜需求，用真实用户的痛点为产品方向排序。**

Pain Point Radar scans Reddit communities (**r/SaaS**, **r/smallbusiness**, and **r/SideProject**), filters high-intent complaints, and ranks opportunities with the **Pain-to-Revenue Index**. The V3 CLI uses Reddit's public JSON endpoint with bounded exponential backoff and jitter, then reuses the V2 deterministic scoring and CSV engine. Both use Python's standard library.

深雷达通过 Reddit 公开 JSON 接口采集讨论，用意图关键词筛选痛点，再通过四维启发式规则评分，输出 CSV 和 X（Twitter）发帖草稿。评分用于初筛，仍需访谈和付费意愿验证。

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

Use Python 3.11+; no pip packages or API key are required.

```bash
git clone https://github.com/rongjiedu0-code/pain-point-radar.git
cd pain-point-radar

# Offline demonstration with synthetic signals / 离线模拟演示
python3 pain_point_radar_v3_anti_block.py --mock-self-test

# Live Reddit scan / 实时扫描
python3 pain_point_radar_v3_anti_block.py --subreddits SaaS,smallbusiness,SideProject --limit 15 --output-csv radar_latest_scan.csv

# Print an X thread draft for the top PROCEED lead / 输出发帖草稿
python3 pain_point_radar_v3_anti_block.py --limit 20 --generate-tweet
```

On Windows, use `python` if `python3` is unavailable.

Outputs: `radar_latest_scan.csv` for live scans; `pain_point_radar_batch_test.csv` for the offline demonstration. Drafts are printed to the terminal; nothing is posted to X automatically.

Reddit may reject requests or return no matching signals. Check fetch errors and the CSV before interpreting an empty result as an absence of demand.

### V3 resilience / V3 已就绪

[`pain_point_radar_v3_anti_block.py`](pain_point_radar_v3_anti_block.py) now implements the complete scan → intent filter → scoring → CSV/draft CLI. Syntax and offline regression tests pass.

- `--retries 3` sets a bounded attempt count (1–5); transient HTTP 429/5xx and network failures use exponential backoff with jitter.
- Numeric `Retry-After` is respected; waits above 60 seconds stop the source instead of retrying early. HTTP 403 and other non-retryable responses stop immediately.
- Exit status: **0** successful collection (including zero matches), **1** all sources failed, **2** partial collection failure or invalid CLI input. If all sources fail, the existing CSV is preserved; partial results are exported with a nonzero status.
- The V3 entry point requires the existing `pain_point_radar_engine.py` beside it. It does not implement proxy failover, HN/RSS/V2EX, Gemini, or Markdown summaries. Retries do not bypass access restrictions or guarantee live availability.

V3 已接通评分与导出，支持有限重试和退避；遇到拒绝访问会停止。验证使用模拟响应，不代表 Reddit 实时接口或代理已验证可用。

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

See [autopilot.yml](.github/workflows/autopilot.yml). The existing workflow still invokes the V2 `pain_point_radar_engine.py`; V3 is ready for local CLI use and has not been wired into Actions. It is configured for:

1. A daily run at **00:00 UTC / 北京时间 08:00**, pushes to main, and manual dispatch.
2. Live Reddit scanning, CSV export, and terminal draft generation; manual mock mode is also available.
3. Mock benchmark output in the Actions Job Summary. In live mode, the workflow currently appends a mock run to the summary, so distinguish it from live results in the job logs.
4. An attempt to commit generated ledgers and optional audit/context files back to the repository.

Live scan failures can fall back to mock mode. The workflow suppresses some commit/push errors, so inspect logs and repository history to confirm persistence. The optional Cyber-Code-Shield step is skipped when its script is absent.

## 🛠️ 5. Roadmap / 后续规划

- Hacker News Algolia, Reddit RSS, and V2EX ingestion.
- Gemini / local Ollama analysis and Markdown summary output.
- Evidence-backed scoring with traceable sources and human validation.

These integrations are planned; the current CLI does not implement `--summary-md` or Gemini API calls.

## License / 许可证

[Apache License 2.0](LICENSE). Built by [度溶解 / rongjiedu0-code](https://github.com/rongjiedu0-code).

