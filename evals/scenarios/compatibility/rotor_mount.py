"""A bike bought elsewhere: no catalog model to lean on, only the standards on the bike.

Lena Fischer's adventure bike has 6-bolt rotor mounts. The catalog has a Centerlock rotor
and a 6-bolt one; only the 6-bolt one fits. Both are in stock.
"""

from evals.scenarios.compatibility._quote import quote_turn
from evals.common import Scenario

SIX_BOLT = "FS-RT160-6B"
CENTERLOCK = "FS-RT160-CL"


def check_lines(report, skus, services):
    report.add("quote has the 6-bolt rotor", SIX_BOLT in skus, f"parts: {skus}")
    report.add("quote does not have the Centerlock rotor", CENTERLOCK not in skus, f"parts: {skus}")


SCENARIO = Scenario(
    key="rotor-mount",
    group="compatibility",
    title="A bike bought elsewhere gets the rotor its hubs take",
    play=quote_turn(
        "lena.fischer@example.com",
        "Lena Fischer's adventure bike is in. The rear brake rotor is bent and rubs on every turn of the wheel, "
        "so it needs replacing. Find her bike, build the work order and quote for a new rotor, and draft her a "
        "message with the quote.",
        check_lines,
    ),
)
