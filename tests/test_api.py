import httpx
import pytest
from httpx import ASGITransport

from app.agent.fallback_agent import FallbackAgent
from app.api.main import create_app
from app.mcp_server import queries as q
from app.services.dashboard import DashboardStore


class DirectToolClient:
    def __init__(self, conn):
        self._conn = conn

    async def start(self): ...
    async def stop(self): ...

    async def call(self, name, params, timeout=None):
        return q.TOOL_FUNCTIONS[name](self._conn, **params)

    async def call_many(self, calls):
        return [await self.call(n, p) for n, p in calls]


@pytest.fixture()
async def api(fixture_db, tmp_path):
    tc = DirectToolClient(fixture_db)

    async def run_tool(name, params):
        return await tc.call(name, params)

    app = create_app(tool_client=tc,
                     store=DashboardStore(tmp_path / "app.db"),
                     agent=FallbackAgent(run_tool))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test") as client:
        yield client


async def test_health(api):
    r = await api.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_query_pin_refresh_delete_cycle(api):
    r = await api.post("/api/query",
                       json={"question": "Show monthly revenue trend for 2017"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["chart"]["chartjs_config"]

    r2 = await api.post("/api/pins", json=body)
    assert r2.status_code == 200
    pin_id = r2.json()["id"]

    r3 = await api.get("/api/pins")
    pins = r3.json()["pins"]
    assert len(pins) == 1
    assert "replay" not in pins[0] and "snapshot" not in pins[0]

    r4 = await api.post(f"/api/pins/{pin_id}/refresh")
    assert r4.status_code == 200
    assert r4.json()["change"]["significant"] is False

    r5 = await api.delete(f"/api/pins/{pin_id}")
    assert r5.status_code == 200 and r5.json()["deleted"] is True
    assert (await api.get("/api/pins")).json()["pins"] == []


async def test_pin_without_chart_is_400(api):
    r = await api.post("/api/query", json={"question": "Tesla stock price?"})
    assert r.json()["status"] == "refused"
    r2 = await api.post("/api/pins", json=r.json())
    assert r2.status_code == 400


async def test_refresh_unknown_pin_404(api):
    assert (await api.post("/api/pins/nope/refresh")).status_code == 404


async def test_query_missing_question_422(api):
    assert (await api.post("/api/query", json={})).status_code == 422


async def test_query_stream_emits_progress_and_result(api, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "agent_mode", "fallback")  # no LLM in tests

    r = await api.post("/api/query/stream",
                       json={"question": "Show monthly revenue trend for 2017"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    import json as _json
    events = [_json.loads(line[6:]) for line in r.text.split("\n\n")
              if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert "tool_start" in types and "tool_end" in types
    assert types[-1] == "result"
    result = events[-1]["response"]
    assert result["status"] == "ok" and result["chart"]
