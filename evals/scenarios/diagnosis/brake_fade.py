"""Marcus's fading brakes: the job is a bleed, not parts.

New pads, levers pulling to the bar, brakes never bled: air in the hydraulic system.
The quote must include the brake bleed and no drivetrain work.
"""

from demo.stories import BY_KEY
from evals.common import Scenario
from evals.scenarios._quote import quote_turn

STORY = BY_KEY["brake-fade"]


def check_lines(report, skus, services):
    report.add("quote has the brake bleed", "Brake bleed" in services, f"services: {services}")
    report.add("no drivetrain parts or labor",
               not any("-C1" in s or "-CH" in s for s in skus) and "Drivetrain replacement (chain and cassette)" not in services,
               f"parts: {skus}, services: {services}")
    report.add("no new rotors", not any(s.startswith("FS-RT") for s in skus), f"parts: {skus}", required=False)


SCENARIO = Scenario(
    key=STORY.key, group=STORY.group,
    title="Fading brakes get a bleed, not parts",
    play=quote_turn(STORY.email, STORY.mechanic_message, check_lines),
)
