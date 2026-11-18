"""Claude API list prices, to turn token usage into dollars (eval reports) and micro-dollars (the hosted demo's budget).

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


# The same prices in cents per million tokens, so a ledger can add costs without floats.
# Cache writes are 1.25x input. A model not listed is priced as the dearest one listed.
CENTS_PER_MTOK = {
    #                  input  output  cache read  cache write
    "claude-sonnet-5-5": (200, 1000, 10, 250),
    "claude-opus-5-5": (400, 2000, 20, 500),
}


def cost_micros(model: str, usage: dict[str, int]) -> int:
    """Estimated cost of `usage` on `model` in millionths of a dollar, rounded up."""
    input_price, output_price, read_price, write_price = CENTS_PER_MTOK.get(
        model, max(CENTS_PER_MTOK.values(), key=lambda p: p[1])
    )
    hundredths = (  # tokens x cents per million tokens = hundredths of a micro-dollar
        usage.get("input_tokens", 0) * input_price
        + usage.get("output_tokens", 0) * output_price
        + usage.get("cache_read_input_tokens", 0) * read_price
        + usage.get("cache_creation_input_tokens", 0) * write_price
    )
    return -(-hundredths // 100)
