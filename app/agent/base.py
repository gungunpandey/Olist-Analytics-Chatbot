from abc import ABC, abstractmethod

from app.agent.models import AgentResponse


class ILLMAgent(ABC):
    """The one interface the rest of the system sees. Implementations:
    LLMAgent (OpenRouter tool-calling) and FallbackAgent (keyword rules)."""

    @abstractmethod
    async def answer(self, question: str) -> AgentResponse: ...
