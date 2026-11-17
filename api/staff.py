"""The Mechanic's workspace: work orders, the Customer thread, and the steps after approval."""

import sqlite3
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_db, require_staff
from shop import customer_links, garage, messages, payments, procurement
from shop import work_orders as wo

router = APIRouter(prefix="/api", tags=["staff"], dependencies=[Depends(require_staff)])


class MessageEdit(BaseModel):
    body: str = Field(min_length=1)


class Schedule(BaseModel):
    scheduled_for: str = Field(description="YYYY-MM-DD", examples=["2026-11-19"])


def next_step(conn: sqlite3.Connection, work_order_id: int, status: str) -> dict[str, str]:
    """What happens next on a work order, and who it's waiting on: mechanic, agent, customer, or nobody."""
    thread = messages.list_messages(conn, work_order_id)
    drafts = [m for m in thread if m.status == "draft"]
    sent_quote = any(m.status == "sent" and m.quoted_total_cents is not None for m in thread)
    orders = procurement.list_purchase_orders(conn, work_order_id)
    open_orders = [o for o in orders if o["status"] == "ordered"]
    if status in ("intake", "diagnosed"):
        return ({"text": "Review and send the draft", "waiting_on": "mechanic"} if drafts
                else {"text": "The Agent is building the quote", "waiting_on": "agent"})
    if status == "quoted":
        if any(m.quoted_total_cents is not None for m in drafts):
            return {"text": "Review and send the quote", "waiting_on": "mechanic"}
        if sent_quote:
            return {"text": "Waiting for the Customer to answer the quote", "waiting_on": "customer"}
        return {"text": "The Agent drafts the quote message", "waiting_on": "agent"}
    if status in ("approved", "awaiting_parts"):
        if open_orders:
            return {"text": "Mark parts received when they arrive", "waiting_on": "mechanic"}
        if wo.parts_short(conn, work_order_id):
            return {"text": "The Agent orders the parts", "waiting_on": "agent"}
        return {"text": "Schedule the repair", "waiting_on": "mechanic"}
    return {
        "scheduled": {"text": "Start the repair", "waiting_on": "mechanic"},
        "in_progress": {"text": "Finish the repair", "waiting_on": "mechanic"},
        "done": {"text": "Waiting for the Customer to pay", "waiting_on": "customer"},
        "paid": {"text": "Paid", "waiting_on": "nobody"},
        "declined": {"text": "Declined by the Customer", "waiting_on": "nobody"},
    }.get(status, {"text": status, "waiting_on": "nobody"})


def work_order_detail(conn: sqlite3.Connection, work_order_id: int) -> dict[str, Any]:
    order = wo.summary(conn, work_order_id)
    link = conn.execute(
        "SELECT token FROM customer_links WHERE work_order_id = ?", (work_order_id,)
    ).fetchone()
    return {
        **order,
        "bike": garage.bike_profile(conn, order["customer_bike_id"]),
        "messages": [asdict(m) for m in messages.list_messages(conn, work_order_id)],
        "purchase_orders": procurement.list_purchase_orders(conn, work_order_id),
        "payments": [asdict(p) for p in payments.list_payments(conn, work_order_id)],
        "customer_link_token": link["token"] if link else None,
        "next_step": next_step(conn, work_order_id, order["status"]),
        "conversation_ids": [
            r["id"] for r in conn.execute(
                "SELECT id FROM agent_conversations WHERE work_order_id = ? ORDER BY created_at DESC, rowid DESC",
                (work_order_id,),
            )
        ],
    }


@router.get("/work-orders")
def list_work_orders(status: str | None = None, conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    """All work orders, newest first. Filter with ?status=quoted, for example."""
    return [{**o, "next_step": next_step(conn, o["id"], o["status"])} for o in wo.list_work_orders(conn, status)]


@router.get("/work-orders/{work_order_id}")
def get_work_order(work_order_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A work order with its bike, the Customer thread (drafts included), orders, and payments."""
    return work_order_detail(conn, work_order_id)


@router.patch("/messages/{message_id}")
def edit_draft(message_id: int, edit: MessageEdit, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Edit a draft before sending it."""
    return asdict(messages.edit_draft(conn, message_id, edit.body))


@router.post("/messages/{message_id}/send")
def send_draft(message_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Send a draft to the Customer. Returns the message and the Customer's link token."""
    sent = messages.send_draft(conn, message_id)
    return {"message": asdict(sent), "customer_link_token": customer_links.link_token(conn, sent.work_order_id)}


@router.post("/purchase-orders/{po_id}/receive")
def receive_purchase_order(po_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, str]:
    """The parts arrived: put them on the shelf."""
    procurement.receive_purchase_order(conn, po_id)
    return {"status": "received"}


@router.post("/work-orders/{work_order_id}/schedule")
def schedule_repair(work_order_id: int, body: Schedule, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Book the repair once every part is in stock."""
    wo.schedule_repair(conn, work_order_id, body.scheduled_for)
    return work_order_detail(conn, work_order_id)


@router.post("/work-orders/{work_order_id}/start")
def start_repair(work_order_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    wo.start_repair(conn, work_order_id)
    return work_order_detail(conn, work_order_id)


@router.post("/work-orders/{work_order_id}/finish")
def finish_repair(work_order_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Mark the repair done; its parts come off the shelf."""
    wo.finish_repair(conn, work_order_id)
    return work_order_detail(conn, work_order_id)
