"""Frank's restomod: be honest about what an old bike can take.

He wants 12-speed, but his rear wheel's freehub only takes up to 10-speed cassettes, and
every 12-speed cassette the shop stocks needs an XD or XDR freehub. A new wheel isn't in
the catalog. Nothing 12-speed may be quoted, every quoted part must fit, and the answer
should explain the wheel.
"""

from datetime import date

from demo.stories import BY_KEY
from evals import checks
from evals.common import Report, Scenario, record_turn

STORY = BY_KEY["modern-gears"]
ANSWER = "Understood. Is there anything worth doing for him today with what we have? If so, quote it; if not, just tell me."


async def play(agent, conn, report: Report, today: date) -> None:
    result = await agent.send(STORY.mechanic_message(today))
    record_turn(report, result)
    report.add("turn finished", result.stop_reason == "end_turn", result.stop_reason)
    if "?" in (result.reply or "") and not conn.execute("SELECT 1 FROM work_orders WHERE quoted_total_cents IS NOT NULL").fetchone():
        result = await agent.send(ANSWER)
        record_turn(report, result)
        report.add("follow-up turn finished", result.stop_reason == "end_turn", result.stop_reason)
    skus = checks.all_quoted_skus(conn)
    twelve = [s for s in skus if s.startswith("AD-C12-") or s == "AD-CH12"]
    report.add("did not quote any 12-speed parts", not twelve, f"parts: {skus}")
    bike = checks.bike_of(conn, STORY.email)
    checks.parts_fit(conn, report, skus, bike)
    checks.nothing_ordered(conn, report)
    said = " ".join(t["reply"] or "" for t in report.turns).lower()
    report.add("explained the freehub or wheel", "freehub" in said or "wheel" in said, said[:200], required=False)


SCENARIO = Scenario(
    key=STORY.key, group=STORY.group,
    title="A restomod gets an honest answer about 12-speed",
    play=play,
)
