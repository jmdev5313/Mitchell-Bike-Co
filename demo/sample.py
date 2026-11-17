"""Add a ready-made hero work order to the database, so the API can be tried by hand.

It does what the Agent and the Mechanic would: opens a work order for Emma's
bike, adds the parts that fit and the labor, locks the quote, drafts the quote
message, and sends it. Then it prints the Customer link token, which the
Customer endpoints in the API docs ask for. No model is called.

With --done, it also acts out the rest: the Customer approves, the cassette is
ordered and received, and the repair is finished, so the work order is ready to
pay through Stripe Checkout (test mode).

Each run adds another work order. `make reset` starts clean.

Run: make sample   (or: make sample ARGS=--done)
"""

import sys

from agents import config
from shop import customer_links, db, events, flow, messages, procurement
from shop import work_orders as wo

EMMA = "emma.clark@example.com"


def create_sample(conn, done: bool = False, source: str = "make sample") -> tuple[int, str, int]:
    """Emma's hero work order, built through the shop's rules with no model call.

    Returns (work order id, Customer link token, quote message id).
    """
    bike = conn.execute(
        """SELECT cb.id FROM customer_bikes cb JOIN customers c ON c.id = cb.customer_id
           WHERE c.email = ?""",
        (EMMA,),
    ).fetchone()
    if bike is None:
        raise LookupError("Emma's bike isn't in the database. Run `make reset` first.")

    order = wo.open_work_order(conn, bike["id"], "My gears skip when I pedal hard.")
    wo.record_diagnosis(conn, order, "Chain worn to 0.75%; cassette worn (came secondhand with the wheels).")
    wo.add_part(conn, order, "AD-C11-34W")
    wo.add_part(conn, order, "AD-CH11")
    wo.add_service(conn, order, "Drivetrain replacement (chain and cassette)")
    total = wo.lock_quote(conn, order)
    velo = conn.execute("SELECT id FROM suppliers WHERE name = 'Velo Supply Co.'").fetchone()[0]
    procurement.set_order_plan(conn, order, [("AD-C11-34W", velo, 1)])  # the shop orders this on approval
    draft = messages.draft_message(
        conn, order, include_quote=True,
        body=(f"Hi Emma, the chain and the gear cluster on your back wheel are worn out, which is why "
              f"the gears skip. Replacing both comes to ${total / 100:.2f}, parts and labor."),
    )
    messages.send_draft(conn, draft.id)
    events.record(conn, order, "shop", "sample", f"Created by {source} (no Agent): quote sent to Emma")
    token = customer_links.link_token(conn, order)
    if done:
        placed = flow.customer_decides(conn, draft.id, approved=True)["placed"]  # the shop places the plan
        procurement.receive_purchase_order(conn, placed[0]["id"])
        promised = conn.execute("SELECT promised_ready_on FROM work_orders WHERE id = ?", (order,)).fetchone()[0]
        wo.schedule_repair(conn, order, promised)
        wo.start_repair(conn, order)
        wo.finish_repair(conn, order)
    return order, token, draft.id


def main(argv: list[str] | None = None) -> None:
    done = "--done" in (argv or [])
    config.load_env()
    conn = db.connect()
    try:
        order, token, quote_id = create_sample(conn, done)
    except LookupError as e:
        raise SystemExit(str(e))
    total = conn.execute("SELECT quoted_total_cents FROM work_orders WHERE id = ?", (order,)).fetchone()[0]
    draft_id = quote_id
    conn.close()

    if done:
        print(f"Added work order {order} for Emma: approved, repaired, ready to pay ${total / 100:.2f}.\n")
        print(f"Customer token: {token}")
        print(f"Customer page:  http://127.0.0.1:8000/c/{token}  (with make api running)\n")
        print("Open the Customer page and press Pay. In Stripe's test checkout, use card")
        print("4242 4242 4242 4242, any future date, any CVC and postcode. Stripe sends you")
        print("back to the Customer page, now showing the receipt.")
        return
    print(f"Added work order {order} for Emma, with a sent ${total / 100:.2f} quote (message {draft_id}).\n")
    print(f"Customer token: {token}")
    print(f"Customer page:  http://127.0.0.1:8000/c/{token}  (with make api running)\n")
    print("In the API docs (make api, then http://127.0.0.1:8000/docs):")
    print("  Customer: GET /api/customer/{token}, pasting the token above")
    print(f"  Customer: POST /api/customer/{{token}}/messages/{draft_id}/decision with {{\"approved\": true}}")
    print(f"  Staff:    GET /api/work-orders/{order}, after Authorize with STAFF_PASSCODE from .env")


if __name__ == "__main__":
    main(sys.argv[1:])
