"""A planned order that fails: re-order honestly and say the date moved.

Emma approved, but Velo (the planned 2-day supplier) has sold out of her cassette, so the
shop couldn't place the plan. The only other source is Northgate, 5 days. The Agent should
order from Northgate and be honest that the ready date moves three days later: tell the
Mechanic, ideally with a draft to Emma.
"""

from datetime import date

from demo.sample import create_sample
from evals.common import Report, Scenario, date_mentions, record_turn
from shop import flow, messages, schedule
from shop import work_orders as wo

CASSETTE = "AD-C11-34W"
NORTHGATE_LEAD = 5
MESSAGE = ("(Shop update: Emma approved the quote on work order #1, but the planned order failed: Velo Supply Co. "
           "is out of the cassette.) Sort out the parts and tell me where the ready date stands.")


def setup(conn, today: date) -> None:
    _, _, quote_id = create_sample(conn, source="the eval setup")
    conn.execute(
        """UPDATE supplier_parts SET available_qty = 0
           WHERE supplier_id = (SELECT id FROM suppliers WHERE name = 'Velo Supply Co.')
             AND part_id = (SELECT id FROM parts WHERE sku = ?)""", (CASSETTE,))
    conn.commit()
    result = flow.customer_decides(conn, quote_id, approved=True)
    assert result["failed"] and not result["placed"], result  # the scenario needs the plan to fail


async def play(agent, conn, report: Report, today: date) -> None:
    result = await agent.send(MESSAGE)
    record_turn(report, result)
    report.add("turn finished", result.stop_reason == "end_turn", result.stop_reason)
    ordered = conn.execute(
        """SELECT s.name, pol.qty FROM purchase_orders po
           JOIN suppliers s ON s.id = po.supplier_id
           JOIN purchase_order_lines pol ON pol.purchase_order_id = po.id
           JOIN parts p ON p.id = pol.part_id
           WHERE po.work_order_id = 1 AND p.sku = ? AND po.status != 'cancelled'""", (CASSETTE,)).fetchall()
    report.add("ordered the cassette once", len(ordered) == 1 and ordered[0]["qty"] == 1,
               f"orders: {[tuple(o) for o in ordered]}")
    report.add("work order is awaiting parts", wo.status(conn, 1) == "awaiting_parts", f"status: {wo.status(conn, 1)}")

    new_date = schedule.ready_date(today, NORTHGATE_LEAD)
    drafts = [m for m in messages.list_messages(conn, 1) if m.status == "draft"]
    said = (result.reply or "") + " ".join(m.body for m in drafts)
    report.add("said when the bike will now be ready", any(m in said for m in date_mentions(new_date)),
               f"new date {new_date.isoformat()}; reply: {(result.reply or '')[:200]}")
    report.add("drafted Emma a message about the new date",
               any(any(m in d.body for m in date_mentions(new_date)) for d in drafts), required=False)


SCENARIO = Scenario(
    key="order-fails",
    group="procurement",
    title="A planned order fails: re-order and be honest about the date",
    play=play,
    setup=setup,
)
