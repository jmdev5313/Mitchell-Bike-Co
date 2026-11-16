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
    }


@router.get("/work-orders")
def list_work_orders(status: str | None = None, conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    """All work orders, newest first. Filter with ?status=quoted, for example."""
    return wo.list_work_orders(conn, status)


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
