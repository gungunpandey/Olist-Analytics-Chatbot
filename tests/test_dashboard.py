from app.agent.models import AgentResponse, ChartOption, SeriesField, SeriesSpec, ToolCallRecord
from app.mcp_server import queries as q
from app.services.dashboard import DashboardStore


class DirectToolClient:
    """call_many against the fixture DB, with a mutable override for tests."""
    def __init__(self, conn):
        self._conn = conn
        self.override = None

    async def call_many(self, calls):
        if self.override is not None:
            return self.override
        return [q.TOOL_FUNCTIONS[name](self._conn, **params) for name, params in calls]


def sample_response() -> AgentResponse:
    return AgentResponse(
        status="ok", question="Show monthly revenue trend for 2017",
        agent_used="llm",
        assumptions=[], data_shape="time_series_single",
        tool_calls=[ToolCallRecord(tool="get_order_trends",
                                   params={"from_date": "2017-01-01",
                                           "to_date": "2017-12-31"})],
        series_specs=[SeriesSpec(tool_call_index=0, label_field="month",
                                 series=[SeriesField(name="Revenue",
                                                     value_field="revenue")])],
        chart=ChartOption(type="line", justification="j",
                          chartjs_config={"type": "line",
                                          "data": {"labels": ["2017-01", "2017-02", "2017-06"],
                                                   "datasets": [{"label": "Revenue",
                                                                 "data": [110.0, 385.0, 330.0]}]},
                                          "options": {}}),
        insight="Revenue grows.")


def test_pin_list_get_delete(tmp_path):
    store = DashboardStore(tmp_path / "app.db")
    pin = store.pin(sample_response())
    assert pin["id"] and pin["question"].startswith("Show monthly")
    assert store.get(pin["id"])["chart"]["type"] == "line"
    assert len(store.list_pins()) == 1
    assert store.delete(pin["id"]) is True
    assert store.list_pins() == []


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "app.db"
    DashboardStore(db).pin(sample_response())
    assert len(DashboardStore(db).list_pins()) == 1   # survives "session" restart


async def test_refresh_no_change(tmp_path, fixture_db):
    store = DashboardStore(tmp_path / "app.db")
    pin = store.pin(sample_response())
    out = await store.refresh(pin["id"], DirectToolClient(fixture_db))
    assert out["change"]["significant"] is False
    assert out["pin"]["refreshed_at"] is not None


async def test_refresh_detects_change(tmp_path, fixture_db):
    store = DashboardStore(tmp_path / "app.db")
    pin = store.pin(sample_response())
    tc = DirectToolClient(fixture_db)
    tc.override = [{"ok": True, "data": [
        {"month": "2017-01", "revenue": 500.0},
        {"month": "2017-02", "revenue": 385.0},
        {"month": "2017-06", "revenue": 330.0},
    ], "meta": {}}]
    out = await store.refresh(pin["id"], tc)
    assert out["change"]["significant"] is True
    # stored snapshot updated -> refreshing again with same data = no change
    out2 = await store.refresh(pin["id"], tc)
    assert out2["change"]["significant"] is False


async def test_refresh_tool_failure_keeps_old_data(tmp_path, fixture_db):
    store = DashboardStore(tmp_path / "app.db")
    pin = store.pin(sample_response())
    tc = DirectToolClient(fixture_db)
    tc.override = [{"ok": False, "error": {"code": "timeout", "message": "boom",
                                           "details": {}}}]
    out = await store.refresh(pin["id"], tc)
    assert out["change"]["significant"] is False
    assert "error" in out
    assert store.get(pin["id"])["chart"]["chartjs_config"]["data"]["datasets"][0]["data"] \
        == [110.0, 385.0, 330.0]
