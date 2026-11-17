"""The control for the hero story: same bike model and symptoms, but stock wheels.

Grace Lee's Halden Arc still has its original wheels, so it takes the catalog model's
11-speed road cassette. An Agent that learned "Halden Arc means the 11-34" would get
this wrong. Everything she needs is in stock, so there's nothing to plan or order.
"""

from evals.scenarios.compatibility._quote import quote_turn
from evals.common import Scenario

CHAIN = "AD-CH11"
UPGRADED_WHEELS_CASSETTE = "AD-C11-34W"
ROAD_CASSETTES = ("AD-C11-28R", "AD-C11-30R")
LABOR = "Drivetrain replacement (chain and cassette)"


def check_lines(report, skus, services):
    report.add("quote has an 11-speed chain", CHAIN in skus, f"parts: {skus}")
    report.add("quote does not have the upgraded-wheels cassette", UPGRADED_WHEELS_CASSETTE not in skus, f"parts: {skus}")
    report.add("quote's cassette is a road 11-speed one", any(s in skus for s in ROAD_CASSETTES),
               f"parts: {skus}", required=False)
    report.add("quote has the drivetrain labor", LABOR in services, f"services: {services}", required=False)


SCENARIO = Scenario(
    key="stock-wheels",
    group="compatibility",
    title="Same model with stock wheels gets the catalog cassette",
    play=quote_turn(
        "grace.lee@example.com",
        "Grace Lee's gravel bike is on the stand. The gears skip under load in the smaller cogs, and my chain "
        "checker reads 0.75%. Find her bike, work out what it needs, build the work order and quote, and draft "
        "her a message with the quote.",
        check_lines,
        answer="It's an 11-28 on there now. Go ahead and build the quote and draft the message.",
    ),
)
