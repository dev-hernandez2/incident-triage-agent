"""Picks a provider by model name prefix and exposes complete()/cost_usd()."""

from decimal import Decimal

from llm.anthropic_provider import AnthropicProvider
from llm.openai_provider import OpenAIProvider
from llm.pricing import cost_usd
from llm.types import CompletionResult, Message, Usage


class LLMClient:
    def __init__(
        self,
        model: str,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        self._model = model
        if model.startswith("claude-"):
            import anthropic

            self._provider: AnthropicProvider | OpenAIProvider = AnthropicProvider(
                client=anthropic.Anthropic(api_key=anthropic_api_key), model=model
            )
        elif model.startswith("gpt-"):
            import openai

            self._provider = OpenAIProvider(
                client=openai.OpenAI(api_key=openai_api_key), model=model
            )
        else:
            raise ValueError(f"no provider for model {model!r}")

    def complete(
        self, messages: list[Message], tools: list[dict[str, object]], system: str
    ) -> CompletionResult:
        return self._provider.complete(messages=messages, tools=tools, system=system)

    def cost_usd(self, usage: Usage) -> Decimal:
        return cost_usd(usage, self._model)
