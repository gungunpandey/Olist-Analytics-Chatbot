from app.agent.fallback_agent import (
    FallbackAgent,
    extract_limit,
    extract_state,
    extract_year,
)
from app.mcp_server import queries as q


def make_agent(fixture_db):
    async def run_tool(name: str, params: dict) -> dict:
        return q.TOOL_FUNCTIONS[name](fixture_db, **params)
    return FallbackAgent(run_tool)


def test_extract_year():
    assert extract_year("revenue in 2017") == ("2017-01-01", "2017-12-31")
    assert extract_year("first half of 2017") == ("2017-01-01", "2017-06-30")
    assert extract_year("last year sales") == ("2017-01-01", "2017-12-31")
    assert extract_year("no year here") is None


def test_extract_state_and_limit():
    assert extract_state("sellers in São Paulo") == "SP"
    assert extract_state("orders from rio de janeiro") == "RJ"
    assert extract_state("top sellers in SP today") == "SP"
    assert extract_state("nothing here") is None
    assert extract_limit("top 10 sellers") == 10
    assert extract_limit("show top 5") == 5
    assert extract_limit("all sellers") is None


async def test_revenue_question_routes_to_trends(fixture_db):
    agent = make_agent(fixture_db)
    resp = await agent.answer("Show monthly revenue trend for 2017")
    assert resp.status == "ok"
    assert resp.agent_used == "fallback"
    assert resp.tool_calls[0].tool == "get_order_trends"
    assert resp.tool_calls[0].params["from_date"] == "2017-01-01"
    assert resp.chart is not None
    assert resp.chart.chartjs_config["type"] == "bar"     # fallback = always bar
    assert any("Fallback agent" in a for a in resp.assumptions)


async def test_seller_question_with_state_and_limit(fixture_db):
    agent = make_agent(fixture_db)
    resp = await agent.answer("Top 10 sellers by revenue in São Paulo")
    assert resp.tool_calls[0].tool == "get_seller_performance"
    assert resp.tool_calls[0].params["state"] == "SP"
    assert resp.tool_calls[0].params["limit"] == 10
    assert resp.chart.chartjs_config["type"] == "bar"


async def test_payment_question(fixture_db):
    agent = make_agent(fixture_db)
    resp = await agent.answer("What share of payments are credit card vs boleto?")
    assert resp.tool_calls[0].tool == "get_payment_breakdown"
    assert resp.status == "ok"


async def test_no_date_assumption_stated(fixture_db):
    agent = make_agent(fixture_db)
    resp = await agent.answer("Which product categories generate the most revenue?")
    assert any("full dataset" in a for a in resp.assumptions)


async def test_out_of_scope_refused(fixture_db):
    agent = make_agent(fixture_db)
    resp = await agent.answer("What is Tesla's stock price?")
    assert resp.status == "refused"
    assert resp.chart is None
    assert resp.message


async def test_empty_result_is_no_data(fixture_db):
    agent = make_agent(fixture_db)
    resp = await agent.answer("seller revenue in AC")   # no sellers in Acre fixture
    assert resp.status == "no_data"
    assert resp.chart is None
