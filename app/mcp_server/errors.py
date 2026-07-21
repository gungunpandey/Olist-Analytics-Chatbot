"""Structured tool results + input validation. Tools never raise."""
import datetime as dt
import functools
import traceback
from typing import Any

from app.config import DATASET_MAX_DATE, DATASET_MIN_DATE

BR_STATES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


def ok(data: Any, **meta: Any) -> dict:
    return {"ok": True, "data": data, "meta": meta}


def err(code: str, message: str, **details: Any) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "details": details}}


def is_err(x: Any) -> bool:
    return isinstance(x, dict) and x.get("ok") is False


def safe_tool(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — tools must never crash the agent
            return err(
                "internal_error",
                f"{type(exc).__name__}: {exc}",
                trace=traceback.format_exc(limit=3),
            )
    return wrapper


def _parse_iso(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def parse_date_range(from_date: str | None, to_date: str | None):
    lo, hi = dt.date.fromisoformat(DATASET_MIN_DATE), dt.date.fromisoformat(DATASET_MAX_DATE)
    f = _parse_iso(from_date) if from_date else lo
    t = _parse_iso(to_date) if to_date else hi
    if f is None or t is None:
        return err("bad_input", "Dates must be ISO format YYYY-MM-DD.",
                   from_date=from_date, to_date=to_date)
    if f > t:
        return err("bad_input", "from_date must be <= to_date.",
                   from_date=from_date, to_date=to_date)
    f, t = max(f, lo), min(t, hi)
    if f > t:
        return err("empty_range", "Requested range is entirely outside the dataset "
                   f"span {DATASET_MIN_DATE}..{DATASET_MAX_DATE}.")
    return (f.isoformat(), t.isoformat())


def validate_state(state: str | None):
    if state is None or state == "":
        return None
    s = str(state).strip().upper()
    if s not in BR_STATES:
        return err("bad_input", f"Unknown Brazilian state code '{state}'. "
                   "Use a two-letter UF code like SP, RJ, MG.", state=state)
    return s


def validate_limit(limit, default: int = 10, max_: int = 100):
    if limit is None:
        return default
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return err("bad_input", f"limit must be an integer, got {limit!r}.")
    if not 1 <= n <= max_:
        return err("bad_input", f"limit must be between 1 and {max_}, got {n}.")
    return n


def validate_sort(sort):
    if sort is None:
        return "desc"
    s = str(sort).strip().lower()
    if s not in ("asc", "desc"):
        return err("bad_input", f"sort must be 'asc' or 'desc', got {sort!r}.")
    return s


def order_by(metric, allowed: dict[str, str], sort: str):
    """Build a safe ORDER BY clause. `allowed` maps public metric name -> SQL column."""
    if metric not in allowed:
        return err("bad_input",
                   f"metric must be one of {sorted(allowed)}, got {metric!r}.")
    return f"ORDER BY {allowed[metric]} {sort.upper()}"
