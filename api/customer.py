"""The Customer's side, reached only through their private link token.

Everything here is scoped to the token's one work order. The Customer sees sent
messages and their own replies, never drafts or the shop's internal notes.
"""

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_db
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
