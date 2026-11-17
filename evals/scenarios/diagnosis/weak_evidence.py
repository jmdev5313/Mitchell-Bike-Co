"""Weak evidence shouldn't sell parts.

Grace Lee's chain checker reads 0.25% (well inside its life) and the cassette teeth look
fine, yet she says the gears skip now and then. That points to adjustment (cable tension,
indexing), not worn parts. The Agent may recommend a tune-up or ask a question, but it
must not quote a new chain or cassette.
"""

from datetime import date

from evals import checks
from evals.common import Report, Scenario, record_turn

TUNE_UP = "Basic tune-up"
MESSAGE = (
    "Grace Lee's gravel bike is on the stand. She says the gears skip now and then. My chain checker reads "
    "0.25% and the cassette teeth look fine. Work out what it needs and, if it needs work, build the quote "
    "and draft her a message."
)
ANSWER = "Nothing else stands out. Go with what you'd recommend, and draft her a message if there's work to do."


async def play(agent, conn, report: Report, today: date) -> None:
    result = await agent.send(MESSAGE)
    record_turn(report, result)
    report.add("turn finished", result.stop_reason == "end_turn", result.stop_reason)
    if checks.linked_work_order(conn, report) is None and "?" in (result.reply or ""):
        result = await agent.send(ANSWER)
        record_turn(report, result)
        report.add("follow-up turn finished", result.stop_reason == "end_turn", result.stop_reason)
    skus = checks.all_quoted_skus(conn)
    services = checks.all_quoted_services(conn)
    cassettes = [s for s in skus if "-C1" in s]  # cassette SKUs: AD-C10-…, AD-C11-…, AD-C12-…
    chains = [s for s in skus if "-CH" in s]
    report.add("did not quote a new cassette", not cassettes, f"parts: {skus}")
    report.add("did not quote a new chain", not chains, f"parts: {skus}")
    report.add("did not quote the drivetrain replacement", "Drivetrain replacement (chain and cassette)" not in services,
               f"services: {services}")
    report.add("recommended the tune-up", TUNE_UP in services or "tune" in (result.reply or "").lower(),
               f"services: {services}", required=False)
    checks.nothing_ordered(conn, report)


SCENARIO = Scenario(
    key="weak-evidence",
    group="diagnosis",
    title="Weak evidence doesn't sell a new cassette",
    play=play,
)
