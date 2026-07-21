# Olist Analytics Chatbot

Plain-English questions → SQL over the Olist e-commerce dataset → the right
chart + a one-line insight → pinnable, refreshable dashboard.

Built as: **MCP tool server** (official Python SDK, 7 tools over SQLite) →
**LLM agent** (OpenRouter tool-calling, hand-written loop — no framework)
behind an `ILLMAgent` interface with a **rule-based fallback** →
deterministic **chart-type selection** → **Chart.js** configs → **FastAPI**
+ a minimal vanilla-JS frontend.

## Setup (one command)

```bash
cp .env.example .env    # put your OPENROUTER_API_KEY in it
docker compose up --build
```

Open http://localhost:8000.

**Model:** any OpenRouter model with native tool-calling. Develop cheap
(`OPENROUTER_MODEL=qwen/qwen-turbo`), demo strong
(`openai/gpt-4o` or `anthropic/claude-sonnet-4.6`) — one env var, nothing
else changes. `AGENT_MODE=fallback` runs the whole system with no LLM at all.

### Local dev (no Docker)

```bash
pip install -r requirements.txt
copy .env.example .env       # fill in the key
uvicorn app.api.main:app --reload --port 8000
```

## Demo video

<video src="https://github.com/gungunpandey/Olist-Analytics-Chatbot/raw/main/Olist_demo.mp4" controls muted width="100%"></video>

▶️ If the inline player doesn't load, watch it here:
**[Olist_demo.mp4](https://github.com/gungunpandey/Olist-Analytics-Chatbot/raw/main/Olist_demo.mp4)**
· [mirror on Google Drive](https://drive.google.com/file/d/1g7DeEqoDY2WX9zwqS9znXiNHRaY2QSxx/view?usp=sharing)

The video runs the LLM agent through every sample query, pins charts, refreshes
a pin **before and after the underlying data changes** (no-change → significant
change), and finishes on the rule-based **fallback** agent (`AGENT_MODE=fallback`,
always a bar chart, no LLM).

## Demo walkthrough (5 queries, in order)

1. **"Show monthly revenue trend for 2017"** → line chart (single metric over
   time), insight, "Chart: line — …" justification. Pin it.
2. **"Which product categories generate the most revenue?"** → horizontal bar
   (ranking), English category names, note the stated full-dataset assumption.
3. **"What share of payments are credit card vs boleto?"** → donut
   (part-to-whole shares).
4. **"Show monthly orders and average review score together for 2017"** →
   dual-axis line (two metrics, one time axis).
5. **"Do sellers with faster delivery get better reviews?"** → scatter, one
   dot per seller (delivery days vs avg review score).

Then: open **Dashboard**, hit **↻ Refresh** on the pinned chart → change badge
("no significant change" on unchanged data). Finally ask **"What is Tesla's
stock price?"** → clean refusal, no chart.

## Architecture

```
question ──▶ ILLMAgent ──▶ MCP client ──stdio──▶ MCP server ──▶ SQLite (olist.db)
              │  (llm | fallback                     │
              │   via AGENT_MODE)                    ▼
              │                    agent selects & calls only the tools it needs:
              │                      • get_order_trends
              │                      • get_category_performance
              │                      • get_seller_performance
              │                      • get_review_analysis
              │                      • get_payment_breakdown
              │                      • get_delivery_performance
              │                      • resolve_category
              ▼
        series_specs ──▶ extract_series() ──▶ build_chart() ──▶ Chart.js config
              │                                    │
              ▼                                    ▼
        insight + assumptions            pin ▶ app.db ▶ refresh ▶ diff
```

## Design decisions

### Chart type selection
The LLM never picks a Chart.js type. It classifies the **data shape** into one
of 7 values (`time_series_single`, `time_series_dual`, `ranking`,
`category_comparison`, `part_to_whole`, `correlation`, `score_distribution`)
and code maps shape → chart deterministically (line / dual-axis line /
horizontal bar desc / vertical bar / donut / scatter / stacked horizontal bar)
per the assignment table. Ambiguous shape → the agent returns an
`alternative_shape` and the UI offers both charts. Every response carries the
chosen type + a one-line justification. A second anti-hallucination seam: the
LLM also never copies numbers — it returns `series_specs` (which fields of
which tool result to plot) and the backend extracts values from the actual
tool output.

### Refresh diff detection
A pin stores the successful tool calls + `series_specs` + a data snapshot.
Refresh replays the tool calls (no LLM involved — deterministic and free),
re-extracts, rebuilds the chart, and compares snapshots. **Significant change**
= any of: (a) chart points added/removed (label set changed), (b) primary
series total moved ≥ 10%, (c) any single shared point moved ≥ 25%. The result
is surfaced as a badge with a human-readable reason. Failed refreshes keep the
previous data and say so.

### What the fallback agent does differently
`AGENT_MODE=fallback` (also auto-engaged when the LLM errors or exceeds
`AGENT_TIMEOUT_SECONDS`): no LLM call at all. It keyword-matches the question
to one tool (payments / delivery / sellers / reviews / categories / trends),
extracts year, "top N" and state (city→UF map) with regexes, and **always
renders a bar chart** — per the assignment. It states its own limitation as an
assumption, refuses unmatched questions, and cannot do multi-tool joins or
two-chart-option answers.

### Other choices worth noting
- **Revenue** = `price + freight` (GMV) for monthly trends; `price` only for
  category/seller rankings. Cancelled orders excluded everywhere; delivery
  metrics use delivered orders only. Stated in tool metadata.
- Category names are **always** joined through
  `product_category_name_translation` (view `products_en`, English name with
  Portuguese fallback), and `resolve_category` maps analyst terms
  ("electronics") to exact category names before filtering.
- Tools return `{"ok": ...}` / structured JSON errors and never raise; the MCP
  client adds per-tool timeouts and a partial-results guarantee (one failed
  tool doesn't kill the answer — the response is marked `partial` and names
  the failed source).
- Dashboard persists in `storage/app.db` on a mounted volume → survives
  container restarts and sessions.

## Running tests

```bash
pip install -r requirements.txt
pytest -q
```
All tests run against small committed fixture CSVs — no dataset download, no
network, no API key needed.

## Env vars

See `.env.example`. `AGENT_MODE=llm|fallback`, `OPENROUTER_API_KEY`,
`OPENROUTER_MODEL`, `AGENT_TIMEOUT_SECONDS`, `TOOL_TIMEOUT_SECONDS`, `PORT`.

---
*Dataset: Brazilian E-Commerce Public Dataset by Olist —
kaggle.com/datasets/olistbr/brazilian-ecommerce — CC BY-NC-SA 4.0*
