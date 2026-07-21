"""LLM agent tests with a scripted fake OpenAI-compatible client (no network)."""
import json

from app.agent.factory import ResilientAgent
from app.agent.llm_agent import LLMAgent
from app.agent.models import AgentResponse
from app.mcp_server import queries as q


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = json.dumps(arguments)


class FakeToolCall:
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, tool_calls=None, content=None):
        self.tool_calls = tool_calls or None
        self.content = content


class _Choice:
    def __init__(self, message):
        self.message = message


class _Completion:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class FakeCompletions:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Completion(self._script.pop(0))


class FakeChat:
    def __init__(self, script):
        self.completions = FakeCompletions(script)


class FakeLLM:
    def __init__(self, script):
        self.chat = FakeChat(script)


class FakeToolClient:
    """Runs tools directly against the fixture DB, records calls."""
    def __init__(self, conn):
        self._conn = conn
        self.called = []

    async def list_tools(self):
        return [{"name": n, "description": n, "input_schema":
                 {"type": "object", "properties": {}}} for n in q.TOOL_FUNCTIONS]

    async def call(self, name, params, timeout=None):
        self.called.append((name, params))
        if name == "always_times_out":
            return {"ok": False, "error": {"code": "timeout", "message": "timed out",
                                           "details": {}}}
        return q.TOOL_FUNCTIONS[name](self._conn, **params)


def script_happy_path():
    return [
        FakeMessage(tool_calls=[
            FakeToolCall("t1", "get_order_trends",
                         {"from_date": "2017-01-01", "to_date": "2017-12-31"}),
        ]),
        FakeMessage(tool_calls=[
            FakeToolCall("t2", "submit_answer", {
                "status": "ok",
                "assumptions": [],
                "data_shape": "time_series_single",
                "title": "Monthly revenue 2017",
                "series_specs": [{"tool_call_index": 0, "label_field": "month",
                                  "series": [{"name": "Revenue",
                                              "value_field": "revenue"}]}],
                "insight": "Revenue trends upward through 2017.",
            }),
        ]),
    ]


async def test_llm_happy_path(fixture_db):
    tc = FakeToolClient(fixture_db)
    agent = LLMAgent(tc, llm_client=FakeLLM(script_happy_path()))
    resp = await agent.answer("Show monthly revenue trend for 2017")
    assert resp.status == "ok" and resp.agent_used == "llm"
    assert resp.chart.chartjs_config["type"] == "line"
    assert resp.chart.chartjs_config["data"]["labels"] == ["2017-01", "2017-02", "2017-06"]
    assert resp.chart.chartjs_config["data"]["datasets"][0]["data"] == [110.0, 385.0, 330.0]
    assert resp.tool_calls[0].tool == "get_order_trends"
    assert resp.chart.justification


async def test_llm_refusal(fixture_db):
    script = [FakeMessage(tool_calls=[
        FakeToolCall("t1", "submit_answer",
                     {"status": "refused", "message": "No stock data here."})])]
    agent = LLMAgent(FakeToolClient(fixture_db), llm_client=FakeLLM(script))
    resp = await agent.answer("Tesla stock price?")
    assert resp.status == "refused" and resp.chart is None
    assert "stock" in resp.message.lower()


async def test_llm_partial_when_a_tool_fails(fixture_db):
    script = [
        FakeMessage(tool_calls=[
            FakeToolCall("t1", "get_order_trends", {}),
            FakeToolCall("t2", "always_times_out", {}),
        ]),
        FakeMessage(tool_calls=[FakeToolCall("t3", "submit_answer", {
            "status": "ok", "data_shape": "time_series_single",
            "title": "Trends",
            "series_specs": [{"tool_call_index": 0, "label_field": "month",
                              "series": [{"name": "Revenue", "value_field": "revenue"}]}],
            "insight": "x", "caveats": ["second source timed out"],
        })]),
    ]
    agent = LLMAgent(FakeToolClient(fixture_db), llm_client=FakeLLM(script))
    resp = await agent.answer("q")
    assert resp.status == "partial"
    assert "always_times_out" in resp.message


async def test_llm_ambiguous_shape_gives_two_options(fixture_db):
    script = [
        FakeMessage(tool_calls=[
            FakeToolCall("t1", "get_category_performance", {"limit": 5})]),
        FakeMessage(tool_calls=[FakeToolCall("t2", "submit_answer", {
            "status": "ok", "data_shape": "ranking",
            "alternative_shape": "category_comparison", "title": "Top categories",
            "series_specs": [{"tool_call_index": 0, "label_field": "category",
                              "series": [{"name": "Revenue", "value_field": "revenue"}]}],
            "insight": "x",
        })]),
    ]
    agent = LLMAgent(FakeToolClient(fixture_db), llm_client=FakeLLM(script))
    resp = await agent.answer("top categories")
    assert resp.chart is not None and resp.chart_alternative is not None
    assert resp.chart.chartjs_config["options"].get("indexAxis") == "y"
    assert resp.chart_alternative.chartjs_config["options"].get("indexAxis") != "y"


async def test_resilient_falls_back_on_llm_error(fixture_db):
    class ExplodingAgent:
        async def answer(self, question):
            raise RuntimeError("api down")

    from app.agent.fallback_agent import FallbackAgent

    async def run_tool(name, params):
        return q.TOOL_FUNCTIONS[name](fixture_db, **params)

    resilient = ResilientAgent(ExplodingAgent(), FallbackAgent(run_tool))
    resp = await resilient.answer("Show monthly revenue trend for 2017")
    assert resp.agent_used == "fallback"
    assert any("unavailable or timed out" in a for a in resp.assumptions)
    assert isinstance(resp, AgentResponse)
