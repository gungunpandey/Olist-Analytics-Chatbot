"""Shared pydantic contracts between agents, chart builder, dashboard, API."""
from typing import Literal

from pydantic import BaseModel


class ToolCallRecord(BaseModel):
    tool: str
    params: dict = {}
    status: Literal["ok", "error", "timeout"] = "ok"
    error: str | None = None


class SeriesField(BaseModel):
    name: str                 # display name, e.g. "Revenue"
    value_field: str          # field in the tool's row dicts, e.g. "revenue"
    axis: Literal["y", "y1"] | None = None


class SeriesSpec(BaseModel):
    """How to turn tool results into chart data. Reused verbatim on refresh."""
    tool_call_index: int      # which entry of tool_calls provides the rows
    label_field: str          # row field used as x labels (or scatter dot label)
    series: list[SeriesField]
    x_field: str | None = None   # correlation only: row field for x values
    y_field: str | None = None   # correlation only: row field for y values


class ChartOption(BaseModel):
    type: str
    justification: str
    chartjs_config: dict


class AgentResponse(BaseModel):
    status: Literal["ok", "refused", "no_data", "partial"]
    question: str
    agent_used: Literal["llm", "fallback"]
    assumptions: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    data_shape: str | None = None
    alternative_shape: str | None = None           # shape of chart_alternative
    series_specs: list[SeriesSpec] = []
    chart: ChartOption | None = None
    chart_alternative: ChartOption | None = None   # set when shape is ambiguous
    insight: str | None = None
    message: str | None = None                     # refusals / errors / partial notes
