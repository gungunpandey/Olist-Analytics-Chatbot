"""OpenRouter tool-calling agent (hand-written loop, no framework).

The model plans tool calls over the OpenAI-compatible chat completions API;
deterministic code extracts data and builds the chart (extract.py / chart.py).
Swap models with the OPENROUTER_MODEL env var — nothing else changes.
"""
import json

from app.agent.base import ILLMAgent
from app.agent.extract import ExtractionError, extract_series
from app.agent.models import (
    AgentResponse,
    ChartOption,
    SeriesSpec,
    ToolCallRecord,
)
from app.agent.prompts import SUBMIT_ANSWER_TOOL, SYSTEM_PROMPT
from app.config import settings
from app.services.chart import build_chart, fmt_value

MAX_ITERATIONS = 8


class LLMProtocolError(RuntimeError):
    """Model never called submit_answer — triggers the fallback."""


def _to_openai_tool(name: str, description: str, schema: dict) -> dict:
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": schema}}


class LLMAgent(ILLMAgent):
    def __init__(self, tool_client, llm_client=None):
        self._tools = tool_client
        if llm_client is None:
            from openai import AsyncOpenAI
            llm_client = AsyncOpenAI(base_url=settings.openrouter_base_url,
                                     api_key=settings.openrouter_api_key)
        self._llm = llm_client

    async def answer(self, question: str) -> AgentResponse:
        mcp_tools = await self._tools.list_tools()
        tool_defs = [_to_openai_tool(t["name"], t["description"], t["input_schema"])
                     for t in mcp_tools]
        tool_defs.append(_to_openai_tool(SUBMIT_ANSWER_TOOL["name"],
                                         SUBMIT_ANSWER_TOOL["description"],
                                         SUBMIT_ANSWER_TOOL["input_schema"]))

        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question}]
        records: list[ToolCallRecord] = []
        results: list[dict] = []
        submitted: dict | None = None

        for _ in range(MAX_ITERATIONS):
            completion = await self._llm.chat.completions.create(
                model=settings.openrouter_model,
                messages=messages,
                tools=tool_defs,
                max_tokens=2000,
            )
            msg = completion.choices[0].message
            if not msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or ""})
                messages.append({"role": "user", "content":
                                 "Continue: call the tools you need, then submit_answer."})
                continue

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name,
                                             "arguments": tc.function.arguments}}
                               for tc in msg.tool_calls],
            })

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if tc.function.name == "submit_answer":
                    submitted = args
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": "received"})
                    break
                envelope = await self._tools.call(tc.function.name, args)
                status = "ok" if envelope.get("ok") else (
                    "timeout" if envelope.get("error", {}).get("code") == "timeout"
                    else "error")
                records.append(ToolCallRecord(
                    tool=tc.function.name, params=args, status=status,
                    error=None if status == "ok" else envelope["error"]["message"]))
                results.append(envelope)
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(envelope, default=str)[:20000]})
            if submitted is not None:
                break

        if submitted is None:
            raise LLMProtocolError("model never called submit_answer")
        return self._finalize(question, submitted, records, results)

    def _finalize(self, question: str, sub: dict,
                  records: list[ToolCallRecord], results: list[dict]) -> AgentResponse:
        assumptions = list(sub.get("assumptions") or [])
        caveats = list(sub.get("caveats") or [])
        base = dict(question=question, agent_used="llm",
                    assumptions=assumptions, tool_calls=records)

        if sub.get("status") in ("refused", "no_data"):
            return AgentResponse(status=sub["status"],
                                 message=sub.get("message")
                                 or "This question cannot be answered from the "
                                    "Olist dataset.", **base)

        shape = sub.get("data_shape")
        specs = [SeriesSpec(**s) for s in (sub.get("series_specs") or [])]
        title = sub.get("title") or question
        try:
            labels, series = extract_series(specs, results, shape)
            # A one-point "trend" is not a trend — show a bar, offer the line.
            if shape == "time_series_single" and len(labels) == 1:
                sub.setdefault("alternative_shape", shape)
                shape = "category_comparison"
            chart = ChartOption(**build_chart(shape, labels, series, title))
        except (ExtractionError, ValueError, KeyError, TypeError) as exc:
            return AgentResponse(status="no_data",
                                 message=f"Could not build a chart: {exc}", **base)
        if not labels and shape != "correlation" or (
                shape == "correlation" and not series[0]["points"]):
            return AgentResponse(status="no_data",
                                 message="The query returned no rows for those "
                                         "filters.", **base)

        alt = None
        if sub.get("alternative_shape") and sub["alternative_shape"] != shape:
            try:
                alt = ChartOption(**build_chart(sub["alternative_shape"],
                                                labels, series, title))
            except (ExtractionError, ValueError):
                alt = None

        failed = [r.tool for r in records if r.status != "ok"]
        status = "partial" if failed else "ok"
        message = (f"Partial results: {', '.join(failed)} failed/timed out."
                   if failed else (sub.get("message") or None))
        if caveats:
            message = ((message + " ") if message else "") + " ".join(caveats)

        insight = sub.get("insight") or ""
        # Ground the insight with a real number from extracted data (R$ when monetary).
        if series and shape != "correlation" and series[0]["data"]:
            vals = [v for v in series[0]["data"] if v is not None]
            if vals:
                i = series[0]["data"].index(max(vals))
                peak = fmt_value(series[0]["name"], max(vals))
                insight = (insight.rstrip(".") +
                           f" (peak: {labels[i]} = {peak}).")

        return AgentResponse(status=status, data_shape=shape,
                             alternative_shape=sub.get("alternative_shape"),
                             series_specs=specs,
                             chart=chart, chart_alternative=alt, insight=insight,
                             message=message, **base)
