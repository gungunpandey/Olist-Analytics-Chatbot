"""Client wrapper around the MCP stdio server. Owns timeouts and the
partial-results guarantee: call()/call_many() NEVER raise."""
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import settings
from app.mcp_server.errors import err


class McpToolClient:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def start(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            env={**os.environ, "OLIST_DB_PATH": str(self._db_path)},
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(
            ClientSession(read, write))
        await self._session.initialize()

    async def stop(self) -> None:
        if self._stack:
            await self._stack.aclose()
            self._stack = self._session = None

    async def list_tools(self) -> list[dict]:
        result = await self._session.list_tools()
        return [{"name": t.name, "description": t.description or "",
                 "input_schema": t.inputSchema} for t in result.tools]

    async def call(self, name: str, params: dict, timeout: float | None = None) -> dict:
        timeout = timeout if timeout is not None else settings.tool_timeout_seconds
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, params), timeout=timeout)
        except asyncio.TimeoutError:
            return err("timeout", f"Tool '{name}' timed out after {timeout}s.",
                       tool=name, params=params)
        except Exception as exc:  # noqa: BLE001 — transport must not crash callers
            return err("transport_error", f"{type(exc).__name__}: {exc}", tool=name)
        # FastMCP returns the dict serialized as JSON text content.
        try:
            payload = json.loads(result.content[0].text)
        except (IndexError, AttributeError, json.JSONDecodeError):
            structured = getattr(result, "structuredContent", None)
            if isinstance(structured, dict):
                payload = structured.get("result", structured)
            else:
                return err("bad_tool_output",
                           f"Tool '{name}' returned unparseable output.")
        if getattr(result, "isError", False) and not isinstance(payload, dict):
            return err("tool_error", str(payload), tool=name)
        return payload

    async def call_many(self, calls: list[tuple[str, dict]]) -> list[dict]:
        return [await self.call(name, params) for name, params in calls]
