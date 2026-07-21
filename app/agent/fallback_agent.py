"""Rule-based agent: keyword matching, always a bar chart, zero LLM calls."""
import re
from typing import Awaitable, Callable

from app.agent.base import ILLMAgent
from app.agent.extract import ExtractionError, extract_series
from app.agent.models import (
    AgentResponse,
    ChartOption,
    SeriesField,
    SeriesSpec,
    ToolCallRecord,
)
from app.config import DATASET_MAX_DATE, DATASET_MIN_DATE
from app.mcp_server.errors import BR_STATES
from app.services.chart import build_chart, fmt_value

_PLACE_TO_STATE = {
    "sao paulo": "SP", "são paulo": "SP",
    "rio de janeiro": "RJ", "rio": "RJ",
    "minas gerais": "MG", "belo horizonte": "MG",
    "bahia": "BA", "salvador": "BA",
    "brasilia": "DF", "brasília": "DF",
    "curitiba": "PR", "parana": "PR", "paraná": "PR",
    "porto alegre": "RS", "rio grande do sul": "RS",
    "recife": "PE", "pernambuco": "PE",
    "fortaleza": "CE", "ceara": "CE", "ceará": "CE",
}

_WORD_NUMS = {"five": 5, "ten": 10, "twenty": 20}


def extract_year(q: str):
    ql = q.lower()
    m = re.search(r"\b(2016|2017|2018)\b", ql)
    if m:
        y = m.group(1)
        if "first half" in ql or "h1" in ql:
            return (f"{y}-01-01", f"{y}-06-30")
        if "second half" in ql or "h2" in ql:
            return (f"{y}-07-01", f"{y}-12-31")
        return (f"{y}-01-01", f"{y}-12-31")
    if "last year" in ql:
        return ("2017-01-01", "2017-12-31")   # dataset anchor, not wall clock
    return None


def extract_state(q: str):
    ql = q.lower()
    for place, uf in _PLACE_TO_STATE.items():
        if place in ql:
            return uf
    for tok in re.findall(r"\b([A-Z]{2})\b", q):
        if tok in BR_STATES:
            return tok
    return None


def extract_limit(q: str):
    ql = q.lower()
    m = re.search(r"top\s+(\d+)", ql)
    if m:
        return int(m.group(1))
    m = re.search(r"top\s+(five|ten|twenty)", ql)
    if m:
        return _WORD_NUMS[m.group(1)]
    return None


# Ordered rules: (keywords-any, tool, param builder, label_field, value fields)
# First rule whose keywords appear in the question wins.
def _rules():
    return [
        (("payment", "credit card", "boleto", "installment", "voucher"),
         "get_payment_breakdown",
         lambda q, f, t, st, lim: {"from_date": f, "to_date": t, "group_by": "type"},
         "payment_type", [("Total value", "total_value")]),
        (("deliver", "delay", "late", "on-time", "on time", "shipping"),
         "get_delivery_performance",
         lambda q, f, t, st, lim: {"from_date": f, "to_date": t, "group_by": "state",
                                   "sort": "asc", "limit": lim},
         "state", [("On-time rate", "on_time_rate")]),
        (("seller",),
         "get_seller_performance",
         lambda q, f, t, st, lim: {"from_date": f, "to_date": t, "state": st,
                                   "limit": lim, "metric": "revenue", "sort": "desc"},
         "seller_id", [("Revenue", "revenue")]),
        (("review", "rating", "score", "satisf"),
         "get_review_analysis",
         lambda q, f, t, st, lim: {"from_date": f, "to_date": t, "state": st,
                                   "group_by": "score"},
         "review_score", [("Reviews", "review_count")]),
        (("categor", "product", "electronic", "bath", "furniture", "beauty",
          "toy", "fashion", "sport", "book"),
         "get_category_performance",
         lambda q, f, t, st, lim: {"from_date": f, "to_date": t, "limit": lim or 10,
                                   "metric": "revenue", "sort": "desc"},
         "category", [("Revenue", "revenue")]),
        (("revenue", "sales", "order", "trend", "month", "volume"),
         "get_order_trends",
         lambda q, f, t, st, lim: {"from_date": f, "to_date": t},
         "month", [("Revenue", "revenue")]),
    ]


class FallbackAgent(ILLMAgent):
    def __init__(self, run_tool: Callable[[str, dict], Awaitable[dict]]):
        self._run_tool = run_tool

    async def answer(self, question: str) -> AgentResponse:
        ql = question.lower()
        dates = extract_year(question)
        f, t = dates if dates else (None, None)
        st, lim = extract_state(question), extract_limit(question)

        matched = None
        for keywords, tool, build_params, label_field, fields in _rules():
            if any(k in ql for k in keywords):
                matched = (tool, build_params(question, f, t, st, lim),
                           label_field, fields)
                break

        assumptions = ["Fallback agent (no LLM): keyword matching, bar chart only."]
        if dates is None:
            assumptions.append(
                "No date range specified — using full dataset "
                f"({DATASET_MIN_DATE} to {DATASET_MAX_DATE})."
            )

        if matched is None:
            return AgentResponse(
                status="refused", question=question, agent_used="fallback",
                assumptions=assumptions,
                message="I can only answer questions about the Olist e-commerce "
                        "dataset: orders, revenue, categories, sellers, reviews, "
                        "payments and delivery performance (2016–2018).")

        tool, params, label_field, fields = matched
        params = {k: v for k, v in params.items() if v is not None}
        result = await self._run_tool(tool, params)
        record = ToolCallRecord(tool=tool, params=params,
                                status="ok" if result.get("ok") else "error",
                                error=None if result.get("ok")
                                      else result["error"]["message"])

        if not result.get("ok"):
            return AgentResponse(status="no_data", question=question,
                                 agent_used="fallback", assumptions=assumptions,
                                 tool_calls=[record],
                                 message=f"Query failed: {result['error']['message']}")
        if not result["data"]:
            return AgentResponse(status="no_data", question=question,
                                 agent_used="fallback", assumptions=assumptions,
                                 tool_calls=[record],
                                 message="The query returned no rows for those "
                                         "filters. Try widening the date range or "
                                         "removing filters.")

        shape = "ranking" if lim else "category_comparison"   # both render as bar
        specs = [SeriesSpec(tool_call_index=0, label_field=label_field,
                            series=[SeriesField(name=n, value_field=vf)
                                    for n, vf in fields])]
        try:
            labels, series = extract_series(specs, [result], shape)
        except ExtractionError as exc:
            return AgentResponse(status="no_data", question=question,
                                 agent_used="fallback", assumptions=assumptions,
                                 tool_calls=[record], message=str(exc))
        chart = build_chart(shape, labels, series, question)
        chart["justification"] = ("Fallback mode always renders a bar chart. "
                                  + chart["justification"])
        top = max(zip(labels, series[0]["data"]), key=lambda p: (p[1] is not None, p[1]))
        insight = (f"Highest value: {top[0]} at {fmt_value(series[0]['name'], top[1])} "
                   f"({series[0]['name']}, fallback keyword analysis).")
        return AgentResponse(status="ok", question=question, agent_used="fallback",
                             assumptions=assumptions, tool_calls=[record],
                             data_shape=shape, series_specs=specs,
                             chart=ChartOption(**chart), insight=insight)
