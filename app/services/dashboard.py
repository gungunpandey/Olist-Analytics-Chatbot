"""Persistent pinned dashboard. One SQLite table; refresh replays the pin's
recorded tool calls (no LLM involved) and diffs the extracted data."""
import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path

from app.agent.extract import ExtractionError, extract_series
from app.agent.models import AgentResponse, SeriesSpec
from app.services.chart import build_chart
from app.services.diff import detect_significant_change

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pins (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    refreshed_at TEXT,
    payload TEXT NOT NULL          -- JSON of the full pin dict
)
"""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _snapshot_from_chart(chartjs_config: dict) -> dict:
    data = chartjs_config.get("data", {})
    return {"labels": data.get("labels", []),
            "series": [{"name": d.get("label", f"s{i}"), "data": d.get("data", [])}
                       for i, d in enumerate(data.get("datasets", []))]}


class DashboardStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._conn() as c:
            c.execute(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def pin(self, response: AgentResponse) -> dict:
        if response.chart is None:
            raise ValueError("Cannot pin a response without a chart.")
        pin = {
            "id": uuid.uuid4().hex,
            "question": response.question,
            "created_at": _now(),
            "refreshed_at": None,
            "agent_used": response.agent_used,
            "data_shape": response.data_shape,
            "title": response.chart.chartjs_config.get("options", {})
                     .get("plugins", {}).get("title", {}).get("text",
                                                              response.question),
            "chart": response.chart.model_dump(),
            "insight": response.insight,
            "assumptions": response.assumptions,
            "last_change": None,
            "replay": {
                "tool_calls": [{"tool": r.tool, "params": r.params}
                               for r in response.tool_calls if r.status == "ok"],
                "series_specs": [s.model_dump() for s in response.series_specs],
                "data_shape": response.data_shape,
            },
            "snapshot": _snapshot_from_chart(response.chart.chartjs_config),
        }
        with self._conn() as c:
            c.execute("INSERT INTO pins (id, created_at, payload) VALUES (?, ?, ?)",
                      (pin["id"], pin["created_at"], json.dumps(pin)))
        return pin

    def list_pins(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT payload FROM pins ORDER BY created_at").fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def get(self, pin_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT payload FROM pins WHERE id = ?",
                            (pin_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def delete(self, pin_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM pins WHERE id = ?", (pin_id,))
        return cur.rowcount > 0

    def _save(self, pin: dict) -> None:
        with self._conn() as c:
            c.execute("UPDATE pins SET payload = ?, refreshed_at = ? WHERE id = ?",
                      (json.dumps(pin), pin["refreshed_at"], pin["id"]))

    async def refresh(self, pin_id: str, tool_client) -> dict:
        pin = self.get(pin_id)
        if pin is None:
            return {"pin": None, "change": None, "error": "pin not found"}
        replay = pin["replay"]
        calls = [(tc["tool"], tc["params"]) for tc in replay["tool_calls"]]
        results = await tool_client.call_many(calls)
        failed = [c[0] for c, r in zip(calls, results) if not r.get("ok")]
        if failed:
            return {"pin": pin,
                    "change": {"significant": False,
                               "reasons": [f"refresh failed: {t}" for t in failed],
                               "summary": "Refresh failed — kept previous data."},
                    "error": f"tools failed on refresh: {', '.join(failed)}"}
        specs = [SeriesSpec(**s) for s in replay["series_specs"]]
        try:
            labels, series = extract_series(specs, results, replay["data_shape"])
        except ExtractionError as exc:
            return {"pin": pin,
                    "change": {"significant": False, "reasons": [str(exc)],
                               "summary": "Refresh failed — kept previous data."},
                    "error": str(exc)}
        new_chart = build_chart(replay["data_shape"], labels, series, pin["title"])
        new_snapshot = _snapshot_from_chart(new_chart["chartjs_config"])
        change = detect_significant_change(pin["snapshot"], new_snapshot)
        pin.update(chart=new_chart, snapshot=new_snapshot, refreshed_at=_now(),
                   last_change=change)
        self._save(pin)
        return {"pin": pin, "change": change}
