"""FastAPI wiring: dataset load -> MCP client -> agent -> routes -> static."""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent.factory import build_agent
from app.agent.models import AgentResponse
from app.config import settings
from app.db.loader import load_database
from app.services.dashboard import DashboardStore
from app.services.mcp_client import McpToolClient


class _NotifyingToolClient:
    """Wraps a tool client and reports every tool call to an emit callback —
    powers the live SSE progress feed. Pass-through otherwise."""

    def __init__(self, inner, emit):
        self._inner, self._emit = inner, emit

    async def list_tools(self):
        return await self._inner.list_tools()

    async def call(self, name: str, params: dict, timeout=None) -> dict:
        await self._emit({"type": "tool_start", "tool": name, "params": params})
        result = await self._inner.call(name, params, timeout)
        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        await self._emit({"type": "tool_end", "tool": name,
                          "ok": bool(result.get("ok")),
                          "rows": meta.get("row_count"),
                          "error": (result.get("error") or {}).get("message")
                          if not result.get("ok") else None})
        return result

    async def call_many(self, calls):
        return [await self.call(n, p) for n, p in calls]

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


class QueryIn(BaseModel):
    question: str


def create_app(tool_client=None, store=None, agent=None) -> FastAPI:
    injected = tool_client is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not injected:
            load_database(settings.data_dir, settings.dataset_db_path)
            app.state.tool_client = McpToolClient(settings.dataset_db_path)
            await app.state.tool_client.start()
            app.state.agent = build_agent(app.state.tool_client)
            app.state.store = DashboardStore(settings.app_db_path)
        else:
            app.state.tool_client = tool_client
            app.state.agent = agent
            app.state.store = store
        yield
        if not injected:
            await app.state.tool_client.stop()

    app = FastAPI(title="Olist Analytics Chatbot", lifespan=lifespan)

    if injected:  # tests inject fakes; ASGITransport does not run the lifespan
        app.state.tool_client = tool_client
        app.state.agent = agent
        app.state.store = store

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent_mode": settings.agent_mode}

    @app.post("/api/query")
    async def query(q: QueryIn) -> AgentResponse:
        return await app.state.agent.answer(q.question)

    @app.post("/api/query/stream")
    async def query_stream(q: QueryIn):
        """Same as /api/query but streams live progress over SSE:
        status / tool_start / tool_end events, then one result event."""
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(ev):
            await queue.put(ev)

        async def run():
            try:
                agent = build_agent(_NotifyingToolClient(app.state.tool_client, emit))
                mode = settings.agent_mode.lower()
                detail = ("rule-based keyword matching, no LLM" if mode == "fallback"
                          else f"LLM planning with {settings.openrouter_model}")
                await emit({"type": "status", "agent_mode": mode,
                            "message": f"Agent mode: {mode.upper()} — {detail}"})
                resp = await agent.answer(q.question)
                if resp.agent_used == "fallback" and settings.agent_mode.lower() != "fallback":
                    await emit({"type": "status",
                                "message": "LLM unavailable/timed out — rule-based fallback answered"})
                await emit({"type": "status", "message": "Building chart"})
                await emit({"type": "result", "response": resp.model_dump()})
            except Exception as exc:  # noqa: BLE001 — stream must end cleanly
                await emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                await emit(None)  # sentinel: close the stream

        async def gen():
            task = asyncio.create_task(run())
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            await task

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.post("/api/pins")
    async def create_pin(response: AgentResponse):
        if response.chart is None:
            raise HTTPException(400, "Cannot pin a response without a chart.")
        pin = app.state.store.pin(response)
        return _public(pin)

    @app.get("/api/pins")
    async def list_pins():
        return {"pins": [_public(p) for p in app.state.store.list_pins()]}

    @app.post("/api/pins/{pin_id}/refresh")
    async def refresh_pin(pin_id: str):
        out = await app.state.store.refresh(pin_id, app.state.tool_client)
        if out["pin"] is None:
            raise HTTPException(404, "pin not found")
        return {"pin": _public(out["pin"]), "change": out["change"],
                **({"error": out["error"]} if out.get("error") else {})}

    @app.delete("/api/pins/{pin_id}")
    async def delete_pin(pin_id: str):
        if not app.state.store.delete(pin_id):
            raise HTTPException(404, "pin not found")
        return {"deleted": True}

    if FRONTEND.exists():
        @app.get("/")
        async def index():
            return FileResponse(FRONTEND / "index.html")

        @app.get("/dashboard")
        async def dashboard():
            return FileResponse(FRONTEND / "dashboard.html")

        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    return app


def _public(pin: dict) -> dict:
    return {k: v for k, v in pin.items() if k not in ("replay", "snapshot")}


app = create_app()
