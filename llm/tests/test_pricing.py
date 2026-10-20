from decimal import Decimal

import pytest
from llm.pricing import MODEL_PRICES, cost_usd
from llm.types import Usage


def test_known_models_are_priced() -> None:
    for model in ("claude-sonnet-5-5", "claude-haiku-5-5", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert model in MODEL_PRICES


def test_cost_usd_combines_input_and_output_token_prices() -> None:
    # Haiku 5.5: priced at $1/MTok input, $5/MTok output in MODEL_PRICES below.
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = cost_usd(usage, "claude-haiku-5-5")
    assert cost == Decimal("6.00")


def test_cost_usd_scales_linearly_with_token_count() -> None:
    usage = Usage(input_tokens=500_000, output_tokens=0)
    cost = cost_usd(usage, "claude-haiku-5-5")
    assert cost == Decimal("0.50")


def test_cost_usd_raises_for_unknown_model() -> None:
    with pytest.raises(KeyError):
        cost_usd(Usage(input_tokens=1, output_tokens=1), "not-a-real-model")
