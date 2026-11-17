"""Wheel size decides the tire: Lena Fischer's bike runs 650b wheels, not the more common 700c."""

from evals.scenarios.compatibility._quote import quote_turn
from evals.common import Scenario

TIRE_650B = "FS-TR650-47"
TIRE_700C = "FS-TR700-40"


def check_lines(report, skus, services):
    report.add("quote has the 650b tire", TIRE_650B in skus, f"parts: {skus}")
    report.add("quote does not have the 700c tire", TIRE_700C not in skus, f"parts: {skus}")


SCENARIO = Scenario(
    key="tire-size",
    group="compatibility",
    title="Wheel size decides the tire",
    play=quote_turn(
        "lena.fischer@example.com",
        "Lena Fischer's front tire is worn through to the casing. Find her bike, build the work order and quote "
        "for a new front tire, and draft her a message with the quote.",
        check_lines,
    ),
)
