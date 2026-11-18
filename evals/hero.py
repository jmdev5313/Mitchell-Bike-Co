"""Live check: the hero story against the real model, judged by what ends up in the database.

Two Mechanic turns, with the Mechanic's send and the Customer's approval acted
out in between:
  1. Diagnose Emma's bike, build and lock the quote, draft her a message.
  2. After she approves: order the parts.

Each check reads the shop's state (work order, quote, drafted message, purchase
order, audit log), not the Agent's wording. Required checks decide pass or fail;
advisory checks are reported but don't fail the run.

It spends real tokens (tens of cents on Claude Sonnet 5.5) and uses its own
database, data/check.db. Run: make agent-check
"""

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from agents import config, conversations
from agents.runtime import AgentRuntime, open_agent
from evals.common import Check, Report, date_mentions, record_turn  # noqa: F401  (re-exported)
from agents.pricing import cost_usd
from shop import db, flow, messages, procurement, schedule, seed
from shop import work_orders as wo

CHECK_DB = Path(os.environ.get("CHECK_DB_PATH", "data/check.db"))
RESULTS_DIR = Path("evals/results")

HERO_CASSETTE = "AD-C11-34W"
CATALOG_CASSETTE = "AD-C11-28R"
CHAIN = "AD-CH11"
LABOR = "Drivetrain replacement (chain and cassette)"
HERO_TOTAL = 7499 + 3499 + 6000

TURN_1 = (
    "Emma Clark's gravel bike is on the stand. The gears skip under load in the smaller cogs, "
    "and my chain checker reads 0.75%. Find her bike, work out what it needs, build the work "
    "order and quote, and draft her a message with the quote."
)
TURN_2 = "Emma approved the quote. Check the cassette is on order and tell me what's next."


def check_quote_turn(conn: sqlite3.Connection, report: Report, today: date) -> dict | None:
    """After turn 1: the right work order, quote, and drafted message. Returns the draft."""
    work_order_id = conversations.get(conn, report.conversation_id).work_order_id
    if not report.add("opened a work order for the bike", work_order_id is not None):
        return None
    order = wo.summary(conn, work_order_id)
    skus = [line["sku"] for line in order["lines"] if line["sku"]]
    services = [line["name"] for line in order["lines"] if line["kind"] == "service"]

    report.add("quote has the cassette that fits the upgraded wheels", HERO_CASSETTE in skus, f"parts: {skus}")
    report.add("quote does not have the catalog cassette", CATALOG_CASSETTE not in skus)
    report.add("quote has a chain", CHAIN in skus, f"parts: {skus}")
    report.add("quote has the drivetrain labor", LABOR in services, f"services: {services}")
    report.add("quote is locked", order["status"] == "quoted", f"status: {order['status']}")
    report.add(
        f"quoted total is ${HERO_TOTAL / 100:.2f}",
        order["quoted_total_cents"] == HERO_TOTAL,
        f"quoted: {order['quoted_total_cents']}",
    )
    report.add(
        "diagnosis cites the evidence",
        bool(order["diagnosis"]) and "0.75" in order["diagnosis"],
        f"diagnosis: {order['diagnosis']!r}",
        required=False,
    )

    drafts = [m for m in messages.list_messages(conn, work_order_id) if m.status == "draft"]
    quote_drafts = [m for m in drafts if m.quoted_total_cents is not None]
    if not report.add("drafted a message that carries the quote", bool(quote_drafts)):
        return None
    draft = quote_drafts[-1]
    body = draft.body
    report.add("message states the quoted total", f"{HERO_TOTAL / 100:.2f}" in body, body)
    report.add("message uses no part numbers", not re.search(r"\b[A-Z]{2}-[A-Z0-9-]{3,}\b", body), body)

    # The promised date must be one estimate_ready_date can back up for a supplier of the cassette.
    supplier_dates = {
        row["name"]: schedule.ready_date(today, row["lead_time_days"])
        for row in conn.execute(
            """SELECT s.name, s.lead_time_days FROM supplier_parts sp
               JOIN suppliers s ON s.id = sp.supplier_id JOIN parts p ON p.id = sp.part_id
               WHERE p.sku = ?""",
            (HERO_CASSETTE,),
        )
    }
    promised = [name for name, day in supplier_dates.items() if any(m in body for m in date_mentions(day))]
    report.add(
        "message promises a ready date the supplier lead time backs up",
        bool(promised),
        f"backed-up dates: { {n: d.isoformat() for n, d in supplier_dates.items()} }",
    )
    report.add(
        "nothing was ordered before the Customer approved",
        not conn.execute("SELECT 1 FROM purchase_orders").fetchone(),
    )
    plan = procurement.order_plan(conn, work_order_id)
    planned = [line for line in plan["lines"] if line["sku"] == HERO_CASSETTE]
    report.add(
        "planned the cassette order with the quote",
        bool(planned) and plan["promised_ready_on"] is not None,
        f"plan: {[(l['sku'], l['supplier']) for l in plan['lines']]}, promised {plan['promised_ready_on']}",
    )
    if planned and plan["promised_ready_on"]:
        report.add(
            "message promises the plan's ready date",
            any(m in body for m in date_mentions(date.fromisoformat(plan["promised_ready_on"]))),
            f"plan promises {plan['promised_ready_on']}",
        )
    return {"id": draft.id, "promised_supplier": promised[0] if promised else None,
            "supplier_dates": supplier_dates}


def check_order_turn(conn: sqlite3.Connection, report: Report, draft: dict) -> None:
    """After turn 2: one order for the cassette, from a supplier that meets the promised date."""
    work_order_id = conversations.get(conn, report.conversation_id).work_order_id
    orders = conn.execute(
        """SELECT po.id, s.name AS supplier, s.lead_time_days, p.sku, pol.qty
           FROM purchase_orders po
           JOIN suppliers s ON s.id = po.supplier_id
           JOIN purchase_order_lines pol ON pol.purchase_order_id = po.id
           JOIN parts p ON p.id = pol.part_id
           WHERE po.work_order_id = ? AND po.status != 'cancelled'""",
        (work_order_id,),
    ).fetchall()
    cassette = [o for o in orders if o["sku"] == HERO_CASSETTE]
    if not report.add("ordered the cassette", len(cassette) == 1 and cassette[0]["qty"] == 1,
                      f"order lines: {[dict(o) for o in orders]}"):
        return
    promised = draft["promised_supplier"]
    if promised:
        promised_date = draft["supplier_dates"][promised]
        ordered_date = draft["supplier_dates"][cassette[0]["supplier"]]
        report.add(
            "supplier meets the date the Customer was promised",
            ordered_date <= promised_date,
            f"promised {promised_date} ({promised}), ordered from {cassette[0]['supplier']} ({ordered_date})",
        )
    report.add("did not order the chain, which is in stock",
               not any(o["sku"] == CHAIN for o in orders), required=False)
    report.add("work order is awaiting parts", wo.status(conn, work_order_id) == "awaiting_parts",
               f"status: {wo.status(conn, work_order_id)}")


async def play(agent: AgentRuntime, conn: sqlite3.Connection, report: Report, today: date) -> None:
    """The hero story's turns and checks, for a runtime that's already open."""
    result = await agent.send(TURN_1)
    record_turn(report, result)
    report.add("turn 1 finished", result.stop_reason == "end_turn", result.stop_reason)
    draft = check_quote_turn(conn, report, today)

    if draft and report.passed:
        messages.send_draft(conn, draft["id"])
        approval = flow.customer_decides(conn, draft["id"], approved=True)  # the shop places the plan
        report.add("the shop placed the planned order on approval", bool(approval["placed"]) and not approval["failed"],
                   f"placed {approval['placed']}, failed {approval['failed']}")
        result = await agent.send(
            f"(Shop update: The mechanic sent message {draft['id']} to the customer. "
            f"The customer approved the quote in message {draft['id']}, and the shop placed the planned order.)\n\n{TURN_2}"
        )
        record_turn(report, result)
        report.add("turn 2 finished", result.stop_reason == "end_turn", result.stop_reason)
        check_order_turn(conn, report, draft)


async def run(make_agent: Callable[[], AgentRuntime], today: date | None = None) -> Report:
    today = today or date.today()
    conn = db.connect()
    agent = make_agent()
    async with agent:
        report = Report(agent.name, getattr(agent, "model", None), agent.conversation_id)
        await play(agent, conn, report, today)

    refused = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE conversation_id = ? AND result_summary LIKE 'refused:%'",
        (report.conversation_id,),
    ).fetchone()[0]
    report.add("tool calls the shop refused", True, f"{refused} refused", required=False)
    conn.close()
    if report.model:
        report.cost_usd = cost_usd(report.model, report.usage)
    return report


def print_report(report: Report) -> None:
    print(f"\nHero check: {report.runtime} ({report.model}), conversation {report.conversation_id}\n")
    for i, turn in enumerate(report.turns, 1):
        print(f"Turn {i} tools: {', '.join(turn['tools']) or 'none'}")
        print(f"Turn {i} reply: {turn['reply']}\n")
    for c in report.checks:
        mark = "PASS" if c.passed else ("FAIL" if c.required else "note")
        print(f"  [{mark}] {c.name}" + (f"  ({c.detail})" if c.detail and (not c.passed or not c.required) else ""))
    usage = ", ".join(f"{k} {v:,}" for k, v in report.usage.items())
    cost = f"${report.cost_usd:.3f}" if report.cost_usd is not None else "unknown"
    print(f"\nTokens: {usage}\nEstimated cost: {cost}")
    print(f"\n{'PASSED' if report.passed else 'FAILED'}")


def save_report(report: Report) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"hero-{report.runtime}-{stamp}.json"
    path.write_text(json.dumps({**asdict(report), "passed": report.passed}, indent=2, default=str))
    return path


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the hero story against the real model.")
    parser.add_argument("--runtime", default="anthropic")
    args = parser.parse_args(argv)
    config.load_env()

    CHECK_DB.unlink(missing_ok=True)
    seed_conn = db.connect(db.init(CHECK_DB))
    seed.load(seed_conn)
    seed_conn.close()
    os.environ["DB_PATH"] = str(CHECK_DB)

    report = await run(lambda: open_agent(args.runtime))
    print_report(report)
    print(f"Saved {save_report(report)}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
