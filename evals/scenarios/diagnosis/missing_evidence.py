"""Missing evidence: ask for the one measurement that settles it, then quote.

The Mechanic reports Emma Clark's skipping gears but no chain measurement. Her history
says the chain was replaced at 5,000 km and the cassette came secondhand with the wheels.
The prompt says to ask when one measurement would settle it, so the Agent should ask for
the chain wear before locking a quote. Then, given 0.75%, it should build the hero quote.
"""

from datetime import date

from evals import checks
from evals.common import Report, Scenario, record_turn
from shop import work_orders as wo

HERO_CASSETTE = "AD-C11-34W"
FIRST = "Emma Clark's gravel bike is on the stand. She says the gears skip when she pedals hard. Work out what it needs."
SECOND = ("My chain checker reads 0.75%. Go ahead: build the work order and quote, and draft her a message "
          "with the quote.")


def locked_quotes(conn) -> list[int]:
    return [r[0] for r in conn.execute("SELECT id FROM work_orders WHERE quoted_total_cents IS NOT NULL")]


async def play(agent, conn, report: Report, today: date) -> None:
    result = await agent.send(FIRST)
    record_turn(report, result)
    report.add("turn 1 finished", result.stop_reason == "end_turn", result.stop_reason)
    report.add("did not lock a quote before the chain was measured", not locked_quotes(conn),
               f"locked: {locked_quotes(conn)}")
    reply = (result.reply or "").lower()
    report.add("asked for the chain measurement", "chain" in reply and ("?" in reply or "measure" in reply),
               (result.reply or "")[:300], required=False)

    result = await agent.send(SECOND)
    record_turn(report, result)
    report.add("turn 2 finished", result.stop_reason == "end_turn", result.stop_reason)
    bike = checks.bike_of(conn, "emma.clark@example.com")
    work_order_id = checks.work_order_for_bike(conn, report, bike)
    if work_order_id is None:
        return
    skus, _, _ = checks.quote_lines(conn, work_order_id)
    report.add("quote has the cassette that fits the upgraded wheels", HERO_CASSETTE in skus, f"parts: {skus}")
    checks.parts_fit(conn, report, skus, bike)
    checks.quote_message(conn, report, work_order_id, today)
    checks.nothing_ordered(conn, report)
    report.add("diagnosis cites the measurement", "0.75" in (wo.summary(conn, work_order_id)["diagnosis"] or ""),
               required=False)


SCENARIO = Scenario(
    key="missing-evidence",
    group="diagnosis",
    title="Missing evidence: ask for the measurement, then quote",
    play=play,
)
