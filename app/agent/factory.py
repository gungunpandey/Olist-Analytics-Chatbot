"""AGENT_MODE switch. The ONLY place allowed to know which agent runs."""
import asyncio

from app.agent.base import ILLMAgent
from app.agent.fallback_agent import FallbackAgent
from app.agent.llm_agent import LLMAgent
from app.agent.models import AgentResponse
from app.config import settings


class ResilientAgent(ILLMAgent):
    """Primary agent with automatic fallback on timeout or error."""

    def __init__(self, primary: ILLMAgent, fallback: ILLMAgent):
        self._primary, self._fallback = primary, fallback

    async def answer(self, question: str) -> AgentResponse:
        try:
            return await asyncio.wait_for(
                self._primary.answer(question),
                timeout=settings.agent_timeout_seconds)
        except Exception:  # noqa: BLE001 — any LLM failure degrades gracefully
            resp = await self._fallback.answer(question)
            resp.assumptions.append(
                "LLM agent unavailable or timed out — answered by the "
                "rule-based fallback.")
            return resp


def build_agent(tool_client) -> ILLMAgent:
    async def run_tool(name: str, params: dict) -> dict:
        return await tool_client.call(name, params)

    fallback = FallbackAgent(run_tool)
    if settings.agent_mode.lower() == "fallback":
        return fallback
    return ResilientAgent(LLMAgent(tool_client), fallback)
