"""Per-model $/MTok pricing. Edit this table when prices change; never hardcode elsewhere."""

from dataclasses import dataclass
from decimal import Decimal

from llm.types import Usage


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: Decimal
    output_per_mtok: Decimal


MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5-5": ModelPrice(
        input_per_mtok=Decimal("3.00"), output_per_mtok=Decimal("15.00")
    ),
    "claude-haiku-5-5": ModelPrice(
        input_per_mtok=Decimal("1.00"), output_per_mtok=Decimal("5.00")
    ),
    "gpt-5.6-terra": ModelPrice(
        input_per_mtok=Decimal("2.50"), output_per_mtok=Decimal("10.00")
    ),
    "gpt-5.6-luna": ModelPrice(
        input_per_mtok=Decimal("0.50"), output_per_mtok=Decimal("2.00")
    ),
}


def cost_usd(usage: Usage, model: str) -> Decimal:
    price = MODEL_PRICES[model]
    input_cost = (Decimal(usage.input_tokens) / Decimal(1_000_000)) * price.input_per_mtok
    output_cost = (Decimal(usage.output_tokens) / Decimal(1_000_000)) * price.output_per_mtok
    return input_cost + output_cost
