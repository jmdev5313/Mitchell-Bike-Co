"""Tom's race: promise a date the shop can keep, not the one he hopes for.

His road bike takes an XDR 12-speed cassette, which is out of stock; the only supplier
needs seven days, and his race is in three. (A wide-range XD cassette would fit with a
spacer and is in stock; using it is a fair call, as long as the date is honest.)
"""

from datetime import date, timedelta

from demo.stories import BY_KEY
from evals.common import Scenario, date_mentions
from evals.scenarios._quote import quote_turn
from shop import messages

STORY = BY_KEY["race-day"]


def check_lines(report, skus, services):
    report.add("quote has a 12-speed chain", "AD-CH12" in skus, f"parts: {skus}")
    report.add("quote has a 12-speed cassette", any(s.startswith("AD-C12-") for s in skus), f"parts: {skus}")


def no_false_promise(conn, report, work_order_id, today: date, replies):
    """The draft mustn't promise the race day unless the shop can back it up."""
    race = today + timedelta(days=3)
    from evals.checks import backed_dates

    backed = backed_dates(conn, work_order_id, today)
    drafts = [m for m in messages.list_messages(conn, work_order_id) if m.status == "draft"]
    body = drafts[-1].body if drafts else ""
    # Saying "it won't be ready for your race on <day>" is fine; giving the race day without the
    # date the shop can keep is the false promise.
    mentions_race = any(m in body for m in date_mentions(race))
    gives_backed = any(m in body for d in backed for m in date_mentions(d))
    promised_race = mentions_race and not gives_backed and not any(d <= race for d in backed)
    report.add("the message doesn't promise the race day", not promised_race, body[:300])
    report.add("told the Mechanic whether the race can be met",
               any("race" in r.lower() for r in replies), (replies[-1] if replies else "")[:200], required=False)


SCENARIO = Scenario(
    key=STORY.key, group=STORY.group,
    title="Race day: promise only the date the shop can keep",
    play=quote_turn(STORY.email, STORY.mechanic_message, check_lines, extra=no_false_promise),
)
