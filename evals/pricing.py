"""Claude API list prices, to turn a run's token usage into dollars.

US dollars per million tokens. Cache writes use the 5-minute rate (1.25x input).
Check https://platform.claude.com/docs/en/about-claude/pricing before relying on
these for anything but an estimate.
"""

PRICES = {
    #                  input  output  cache read
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
}
CACHE_WRITE_MULTIPLIER = 1.25


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    """Estimated cost of `usage` on `model`, or None if the model's price isn't listed."""
    if model not in PRICES:
        return None
    input_price, output_price, cache_read_price = PRICES[model]
    per_token = 1 / 1_000_000
    return (
        usage.get("input_tokens", 0) * input_price
        + usage.get("cache_creation_input_tokens", 0) * input_price * CACHE_WRITE_MULTIPLIER
        + usage.get("cache_read_input_tokens", 0) * cache_read_price
        + usage.get("output_tokens", 0) * output_price
    ) * per_token
