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

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.deps import get_db, get_stripe, public_base_url
from shop import customer_links, garage, messages, payments
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
    paid = any(p.status == "paid" for p in payments.list_payments(conn, work_order_id))
    can_pay = order["status"] == "done" and not paid
    return {
        "shop": "Mitchell Bike Co.",
        "customer": bike["customer"],
        "bike": {"nickname": bike["nickname"], "model": bike["model"]},
        "status": order["status"],
        "quote": {
            "total_cents": order["quoted_total_cents"],
            "lines": [
                {"name": line["name"], "qty": line["qty"], "unit_price_cents": line["unit_price_cents"]}
                for line in order["lines"]
            ],
        } if order["quoted_total_cents"] is not None else None,
        "open_quote_message_id": open_quote,
        "scheduled_for": order["scheduled_for"],
        "paid": paid,
        "can_pay": can_pay,
        "messages": thread,
    }


def _work_order(conn: sqlite3.Connection, token: str) -> int:
    return customer_links.work_order_for(conn, token)


@router.get("")
def view(token: str, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The Customer's view of their work order: the thread, the quote, and where it stands."""
    return customer_view(conn, _work_order(conn, token))


@router.post("/messages/{message_id}/decision")
def decide(token: str, message_id: int, decision: Decision, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Approve or decline the quote carried by a message the shop sent."""
    work_order_id = _work_order(conn, token)
    message = messages.get_message(conn, message_id)
    if message.work_order_id != work_order_id:
        raise NotFound(f"no message with id {message_id}")  # don't reveal other work orders' messages
    wo.record_customer_decision(conn, message_id, decision.approved)
    return customer_view(conn, work_order_id)


@router.post("/replies")
def reply(token: str, body: Reply, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Send the shop a message."""
    work_order_id = _work_order(conn, token)
    messages.receive_message(conn, work_order_id, body.body)
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
    session = stripe_client.v1.checkout.sessions.retrieve(session_id)
    if str(session.client_reference_id) != str(work_order_id) or session.currency != "usd":
        raise HTTPException(status.HTTP_409_CONFLICT, "checkout session does not match this work order")
    if session.payment_status == "paid":
        return payments.complete_payment(conn, payment.id, session.amount_total).status
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
    base = public_base_url()
    session = stripe_client.v1.checkout.sessions.create(
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
                        "name": f"Bike repair: {view['bike']['nickname'] or view['bike']['model']}",
                        "description": f"Mitchell Bike Co. work order {work_order_id}",
                    },
                },
            }],
            "success_url": f"{base}/api/customer/{token}/checkout/return?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{base}/api/customer/{token}",
        },
        {"idempotency_key": f"mitchell-payment-{payment.id}"},
    )
    payments.attach_checkout_session(conn, payment.id, session.id)
    return {"checkout_url": session.url, "payment_id": str(payment.id)}


@router.get("/checkout/return", include_in_schema=False)
def checkout_return(
    token: str, session_id: str, conn: sqlite3.Connection = Depends(get_db), stripe_client: Any = Depends(get_stripe)
) -> RedirectResponse:
    """Where Stripe sends the Customer after paying: confirm with Stripe, then show their work order."""
    _confirm(conn, stripe_client, _work_order(conn, token), session_id)
    return RedirectResponse(f"{public_base_url()}/api/customer/{token}", status_code=status.HTTP_303_SEE_OTHER)


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
