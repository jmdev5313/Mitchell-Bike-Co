"""The Customer's side, reached only through their private link token.

Everything here is scoped to the token's one work order. The Customer sees sent
messages and their own replies, never drafts or the shop's internal notes.

Payment uses Stripe Checkout in test mode: the Customer is sent to Stripe's
hosted page for the quoted total, and the payment is confirmed with Stripe when
they come back (or when /checkout/confirm is called), never from the browser's
word alone.
"""

import sqlite3
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.deps import get_db, get_stripe, public_base_url
from shop import customer_links, events, flow, garage, messages, payments, procurement
from shop import work_orders as wo
from shop.errors import NotFound

router = APIRouter(prefix="/api/customer/{token}", tags=["customer"])


class Decision(BaseModel):
    approved: bool


class Reply(BaseModel):
    body: str = Field(min_length=1)


def customer_view(conn: sqlite3.Connection, work_order_id: int) -> dict[str, Any]:
    order = wo.summary(conn, work_order_id)
    bike = garage.bike_profile(conn, order["customer_bike_id"])
    thread = [
        {
            "id": m.id,
            "from": "shop" if m.direction == "to_customer" else "you",
            "body": m.body,
            "quoted_total_cents": m.quoted_total_cents,
            "at": m.sent_at,
        }
        for m in messages.list_messages(conn, work_order_id)
        if m.status != "draft"
    ]
    open_quote = next(
        (m["id"] for m in reversed(thread) if m["quoted_total_cents"] is not None), None
    ) if order["status"] == "quoted" else None
    paid_at = next((p.paid_at for p in payments.list_payments(conn, work_order_id) if p.status == "paid"), None)
    paid = paid_at is not None
    can_pay = order["status"] == "done" and not paid
    received = [po["received_at"] for po in procurement.list_purchase_orders(conn, work_order_id) if po["received_at"]]
    ordered = any(po["status"] != "cancelled" for po in procurement.list_purchase_orders(conn, work_order_id))
    return {
        "shop": "Mitchell Bike Co.",
        "work_order_id": work_order_id,
        "customer": bike["customer"],
        "bike": {"nickname": bike["nickname"], "model": bike["model"]},
        "status": order["status"],
        "quote": {
            "total_cents": order["quoted_total_cents"],
            "lines": [
                {"name": line["name"], "category": line["category"], "qty": line["qty"],
                 "unit_price_cents": line["unit_price_cents"]}
                for line in order["lines"]
            ],
        } if order["quoted_total_cents"] is not None else None,
        "open_quote_message_id": open_quote,
        "scheduled_for": order["scheduled_for"],
        "timeline": {
            "decided_at": order["decided_at"],
            "parts_ordered": ordered,
            "parts_received_at": max(received) if received else None,
            "finished_at": order["finished_at"],
            "paid_at": paid_at,
        },
        "paid": paid,
        "can_pay": can_pay,
        "messages": thread,
    }


def _work_order(conn: sqlite3.Connection, token: str) -> int:
    return customer_links.work_order_for(conn, token)


def _record_visit(conn: sqlite3.Connection, token: str, work_order_id: int) -> None:
    """Note the Customer opening their link: the first time, and after the shop sends something new.
    Reloads in between aren't recorded."""
    link = conn.execute("SELECT last_visit_at FROM customer_links WHERE token = ?", (token,)).fetchone()
    newest = conn.execute(
        """SELECT MAX(sent_at) FROM customer_messages
           WHERE work_order_id = ? AND direction = 'to_customer' AND status = 'sent'""",
        (work_order_id,),
    ).fetchone()[0]
    last = link["last_visit_at"]
    if last is None:
        events.record(conn, work_order_id, "customer", "link_opened", "Opened their link for the first time")
    elif newest and newest > last:
        events.record(conn, work_order_id, "customer", "link_opened", "Opened their link and read the new message")
    with conn:
        conn.execute("UPDATE customer_links SET last_visit_at = ? WHERE token = ?", (events.now(), token))


@router.get("")
def view(token: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The Customer's view of their work order: the thread, the quote, and where it stands."""
    work_order_id = _work_order(conn, token)
    _record_visit(conn, token, work_order_id)
    return customer_view(conn, work_order_id)


@router.post("/messages/{message_id}/decision")
def decide(token: str, message_id: int, decision: Decision, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Approve or decline the quote carried by a message the shop sent."""
    work_order_id = _work_order(conn, token)
    message = messages.get_message(conn, message_id)
    if message.work_order_id != work_order_id:
        raise NotFound(f"no message with id {message_id}")  # don't reveal other work orders' messages
    flow.customer_decides(conn, message_id, decision.approved)  # on approval, the shop places the planned orders
    return customer_view(conn, work_order_id)


@router.post("/replies")
def reply(token: str, body: Reply, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Send the shop a message."""
    work_order_id = _work_order(conn, token)
    messages.receive_message(conn, work_order_id, body.body)
    text = body.body.strip()
    events.record(conn, work_order_id, "customer", "replied", f"Asked: \u201c{text[:140]}{'…' if len(text) > 140 else ''}\u201d")
    return customer_view(conn, work_order_id)


def _confirm(conn: sqlite3.Connection, stripe_client: Any, work_order_id: int, session_id: str) -> str:
    """Check one checkout session with Stripe and record the payment if it's paid.

    Returns the payment's status. The session must belong to this work order.
    """
    payment = payments.payment_for_session(conn, session_id)
    if payment.work_order_id != work_order_id:
        raise NotFound(f"no payment for checkout session {session_id}")
    if payment.status != "pending":
        return payment.status
    try:
        session = stripe_client.v1.checkout.sessions.retrieve(session_id)
    except stripe.StripeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"could not check the payment with Stripe: {e.user_message or e}")
    if str(session.client_reference_id) != str(work_order_id) or session.currency != "usd":
        raise HTTPException(status.HTTP_409_CONFLICT, "checkout session does not match this work order")
    if session.payment_status == "paid":
        done = payments.complete_payment(conn, payment.id, session.amount_total)
        events.record(conn, work_order_id, "customer", "paid",
                      f"Paid ${done.amount_cents // 100:,}.{done.amount_cents % 100:02d} in Stripe test mode (no money moved)")
        return done.status
    return payment.status


@router.post("/checkout")
def start_checkout(
    token: str, conn: sqlite3.Connection = Depends(get_db), stripe_client: Any = Depends(get_stripe)
) -> dict[str, str]:
    """Start paying for a finished repair. Returns the Stripe Checkout page to send the Customer to."""
    work_order_id = _work_order(conn, token)
    view = customer_view(conn, work_order_id)
    if view["paid"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "this repair is already paid")
    payment = payments.start_payment(conn, work_order_id)  # refuses unless the repair is done
    try:
        session = _create_session(stripe_client, token, work_order_id, view, payment)
    except stripe.StripeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Stripe refused the checkout: {e.user_message or e}")
    payments.attach_checkout_session(conn, payment.id, session.id)
    return {"checkout_url": session.url, "payment_id": str(payment.id)}


def _create_session(stripe_client: Any, token: str, work_order_id: int, view: dict, payment: Any) -> Any:
    base = public_base_url()
    return stripe_client.v1.checkout.sessions.create(
        {
            "mode": "payment",
            "client_reference_id": str(work_order_id),
            "metadata": {"work_order_id": str(work_order_id), "payment_id": str(payment.id)},
            "line_items": [{
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": payment.amount_cents,
                    "product_data": {
                        "name": f"Bike repair, demo (test mode, no charge): {view['bike']['nickname'] or view['bike']['model']}",
                        "description": f"Mitchell Bike Co. is a fictional demo shop. Work order {work_order_id}.",
                    },
                },
            }],
            # Said again on Stripe's own page, next to its Pay button (Stripe also shows a TEST MODE badge).
            "custom_text": {"submit": {"message": "Demo only. Stripe test mode: no real payment is taken. "
                                                  "Use test card 4242 4242 4242 4242, any future date, any CVC."}},
            "success_url": f"{base}/api/customer/{token}/checkout/return?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base}/c/{token}?checkout=cancelled",
        },
        # Payment ids restart when the database is rebuilt, and Stripe remembers keys for
        # 24 hours, so the key also carries the work order's unique link token.
        {"idempotency_key": f"mitchell-{token}-payment-{payment.id}"},
    )


@router.get("/checkout/return", include_in_schema=False)
def checkout_return(
    token: str, session_id: str, conn: sqlite3.Connection = Depends(get_db), stripe_client: Any = Depends(get_stripe)
) -> RedirectResponse:
    """Where Stripe sends the Customer after paying: confirm with Stripe, then show their work order."""
    _confirm(conn, stripe_client, _work_order(conn, token), session_id)
    return RedirectResponse(f"{public_base_url()}/c/{token}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/checkout/confirm")
def confirm_checkout(
    token: str, conn: sqlite3.Connection = Depends(get_db), stripe_client: Any = Depends(get_stripe)
) -> dict[str, Any]:
    """Check this work order's open checkouts with Stripe, for a Customer who closed the page early."""
    work_order_id = _work_order(conn, token)
    for payment in payments.list_payments(conn, work_order_id):
        if payment.status == "pending" and payment.stripe_session_id:
            if _confirm(conn, stripe_client, work_order_id, payment.stripe_session_id) == "paid":
                break
    return customer_view(conn, work_order_id)
