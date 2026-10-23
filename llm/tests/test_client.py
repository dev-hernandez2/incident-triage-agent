from decimal import Decimal

import pytest
from llm.client import LLMClient
from llm.types import Usage


def test_claude_model_selects_anthropic_provider() -> None:
    client = LLMClient(model="claude-haiku-5-5", anthropic_api_key="fake-key")
    from llm.anthropic_provider import AnthropicProvider

    assert isinstance(client._provider, AnthropicProvider)


def test_gpt_model_selects_openai_provider() -> None:
    client = LLMClient(model="gpt-5.6-luna", openai_api_key="fake-key")
    from llm.openai_provider import OpenAIProvider

    assert isinstance(client._provider, OpenAIProvider)


def test_unknown_model_prefix_raises() -> None:
    with pytest.raises(ValueError, match="no provider"):
        LLMClient(model="llama-mystery")


def test_cost_usd_delegates_to_pricing_table() -> None:
    client = LLMClient(model="claude-haiku-5-5", anthropic_api_key="fake-key")
    cost = client.cost_usd(Usage(input_tokens=1_000_000, output_tokens=0))
    assert cost == Decimal("1.00")


def test_model_property_exposes_the_configured_model_name() -> None:
    client = LLMClient(model="claude-haiku-5-5", anthropic_api_key="fake-key")
    assert client.model == "claude-haiku-5-5"
