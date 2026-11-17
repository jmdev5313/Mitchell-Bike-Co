"""A one-turn "build the quote" scenario, shared by the compatibility checks."""

from collections.abc import Callable
from datetime import date

from evals import checks
from evals.common import Report, record_turn


DEFAULT_ANSWER = "Use your best judgment for this bike and go ahead: build the work order and quote, and draft the message."


def quote_turn(email: str, message: str, check_lines: Callable[[Report, list[str], list[str]], None],
               answer: str = DEFAULT_ANSWER):
    """A play(): the Mechanic asks for a quote; then judge the work order, the lines and the message.

    The Agent may ask one clarifying question first (its prompt says to, when one fact would settle
    it). If it hasn't opened a work order after the first turn, the Mechanic answers with `answer`.
    """

    async def play(agent, conn, report: Report, today: date) -> None:
        result = await agent.send(message)
        record_turn(report, result)
        report.add("turn finished", result.stop_reason == "end_turn", result.stop_reason)
        asked = checks.linked_work_order(conn, report) is None
        if asked:
            result = await agent.send(answer)
            record_turn(report, result)
            report.add("follow-up turn finished", result.stop_reason == "end_turn", result.stop_reason)
        report.add("built the quote without a clarifying question", not asked,
                   "asked first: " + (report.turns[0]["reply"] or "")[:200] if asked else "", required=False)
        bike = checks.bike_of(conn, email)
        work_order_id = checks.work_order_for_bike(conn, report, bike)
        if work_order_id is None:
            return
        skus, services, _ = checks.quote_lines(conn, work_order_id)
        check_lines(report, skus, services)
        checks.parts_fit(conn, report, skus, bike)
        checks.quote_message(conn, report, work_order_id, today)
        checks.nothing_ordered(conn, report)

    return play
