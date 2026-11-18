"""The Mechanic's workspace: work orders, the Customer thread, and the steps after approval.

Every action here is also written to the work order's history (`shop.events`) as
the mechanic's, next to the agent's tool calls and the customer's actions.
"""

import sqlite3
from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_db, require_staff
from shop import customer_links, events, flow, garage, messages, payments, procurement
from shop import work_orders as wo

router = APIRouter(prefix="/api", tags=["staff"], dependencies=[Depends(require_staff)])


class MessageEdit(BaseModel):
    body: str = Field(min_length=1)


class Schedule(BaseModel):
    scheduled_for: str = Field(description="YYYY-MM-DD", examples=["2026-11-19"])


def _first_name(conn: sqlite3.Connection, work_order_id: int) -> str:
    row = conn.execute(
        "SELECT c.name FROM work_orders w JOIN customers c ON c.id = w.customer_id WHERE w.id = ?", (work_order_id,)
    ).fetchone()
    return row["name"].split(" ")[0] if row else "the Customer"


def _long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%A}, {d:%b} {d.day}"


def next_step(conn: sqlite3.Connection, work_order_id: int, status: str) -> dict[str, Any]:
    """What happens next on a work order, who it's waiting on (mechanic, agent, customer,
    shop or nobody), and the one action that moves it forward, when there is one."""
    name = _first_name(conn, work_order_id)
    thread = messages.list_messages(conn, work_order_id)
    drafts = [m for m in thread if m.status == "draft"]
    sent = [m for m in thread if m.status != "draft"]
    orders = procurement.list_purchase_orders(conn, work_order_id)
    open_orders = [o for o in orders if o["status"] == "ordered"]
    finished_at = conn.execute("SELECT finished_at, promised_ready_on FROM work_orders WHERE id = ?",
                               (work_order_id,)).fetchone()

    if drafts:
        quote = drafts[-1].quoted_total_cents is not None
        return {"text": f"Review and send the {'quote' if quote else 'draft'} to {name}", "waiting_on": "mechanic",
                "action": {"kind": "send_draft", "message_id": drafts[-1].id, "label": f"Send to {name}"}}
    if status not in ("paid", "declined") and sent and sent[-1].direction == "from_customer":
        reply = sent[-1].body
        return {"text": f"{name} replied: draft an answer", "waiting_on": "mechanic",
                "action": {"kind": "ask_agent", "label": "Ask the Agent to answer",
                           "prompt": f"{name} replied on work order #{work_order_id}: “{reply}” Draft an answer I can send."}}
    if status in ("intake", "diagnosed"):
        return {"text": "The Agent is building the quote", "waiting_on": "agent"}
    if status == "quoted":
        if any(m.quoted_total_cents is not None for m in sent):
            return {"text": f"Waiting for {name} to answer the quote", "waiting_on": "customer"}
        return {"text": "The Agent drafts the quote message", "waiting_on": "agent"}
    if status in ("approved", "awaiting_parts"):
        if open_orders:
            po = open_orders[0]
            skus = ", ".join(line["sku"] for line in po["lines"])
            return {"text": f"Mark parts received when they arrive ({skus} from {po['supplier']})", "waiting_on": "mechanic",
                    "action": {"kind": "receive", "purchase_order_id": po["id"], "label": f"Mark {skus} received"}}
        if wo.parts_short(conn, work_order_id):
            failed = conn.execute(
                "SELECT 1 FROM work_order_events WHERE work_order_id = ? AND kind = 'order_failed'", (work_order_id,)
            ).fetchone()
            why = "The planned order failed" if failed else "No order was planned"
            return {"text": f"{why}: ask the Agent to order the parts", "waiting_on": "mechanic",
                    "action": {"kind": "ask_agent", "label": "Ask the Agent to order",
                               "prompt": f"{name} approved work order #{work_order_id}, but the parts aren't ordered yet "
                                         f"({why.lower()}). Order what's needed from a supplier that still meets the promised date."}}
        when = finished_at["promised_ready_on"] or date.today().isoformat()
        return {"text": f"Book the repair for {_long_date(when)}", "waiting_on": "mechanic",
                "action": {"kind": "book", "date": when, "label": f"Book for {_long_date(when)}"}}
    if status == "scheduled":
        return {"text": "Start the repair", "waiting_on": "mechanic", "action": {"kind": "start", "label": "Start repair"}}
    if status == "in_progress":
        return {"text": "Finish the repair", "waiting_on": "mechanic", "action": {"kind": "finish", "label": "Repair done"}}
    if status == "done":
        told = finished_at["finished_at"] and any(
            m.direction == "to_customer" and (m.sent_at or "") > finished_at["finished_at"] for m in sent
        )
        if not told:
            return {"text": f"Tell {name} the bike is ready", "waiting_on": "mechanic",
                    "action": {"kind": "ask_agent", "label": "Ask the Agent to draft it",
                               "prompt": f"The repair on work order #{work_order_id} is done. Draft {name} a short message "
                                         "that the bike is ready to pick up and can be paid for from the link."}}
        return {"text": f"Waiting for {name} to pay", "waiting_on": "customer"}
    return {
        "paid": {"text": "Paid", "waiting_on": "nobody"},
        "declined": {"text": f"Declined by {name}", "waiting_on": "nobody"},
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
        "order_plan": procurement.order_plan(conn, work_order_id),
        "payments": [asdict(p) for p in payments.list_payments(conn, work_order_id)],
        "customer_link_token": link["token"] if link else None,
        "next_step": next_step(conn, work_order_id, order["status"]),
        "history": events.history(conn, work_order_id),
        "unseen": events.unseen(conn, work_order_id),
        "conversation_ids": [
            r["id"] for r in conn.execute(
                "SELECT id FROM agent_conversations WHERE work_order_id = ? ORDER BY created_at DESC, rowid DESC",
                (work_order_id,),
            )
        ],
    }


@router.get("/activity/latest")
def latest_activity(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The newest history event and how many work orders need the mechanic. Screens poll this."""
    needs_you = sum(
        next_step(conn, o["id"], o["status"])["waiting_on"] == "mechanic" for o in wo.list_work_orders(conn)
    )
    return {"latest_event_id": events.latest_id(conn), "needs_you": needs_you}


@router.get("/work-orders")
def list_work_orders(status: str | None = None, conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    """All work orders, newest first, with the next step and what's new since a mechanic last looked."""
    out = []
    for o in wo.list_work_orders(conn, status):
        new = events.unseen(conn, o["id"])
        out.append({**o, "next_step": next_step(conn, o["id"], o["status"]),
                    "unseen_count": len(new), "unseen_latest": new[-1]["summary"] if new else None,
                    "unseen_actor": new[-1]["actor"] if new else None})
    return out


@router.get("/work-orders/{work_order_id}")
def get_work_order(work_order_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """A work order with its bike, the Customer thread (drafts included), orders, plan, payments and history."""
    return work_order_detail(conn, work_order_id)


@router.post("/work-orders/{work_order_id}/seen")
def mark_seen(work_order_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, str]:
    """The mechanic has looked at this work order: clear its new-activity badge."""
    wo.status(conn, work_order_id)  # 404 for an unknown work order
    events.mark_seen(conn, work_order_id)
    return {"status": "seen"}


@router.patch("/messages/{message_id}")
def edit_draft(message_id: int, edit: MessageEdit, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Edit a draft before sending it."""
    msg = messages.edit_draft(conn, message_id, edit.body)
    events.record(conn, msg.work_order_id, "mechanic", "draft_edited", "Edited the Agent's draft before sending")
    return asdict(msg)


@router.post("/messages/{message_id}/send")
def send_draft(message_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Send a draft to the Customer. Returns the message and the Customer's link token."""
    sent = messages.send_draft(conn, message_id)
    name = _first_name(conn, sent.work_order_id)
    cents = sent.quoted_total_cents
    what = f"the ${cents // 100:,}.{cents % 100:02d} quote" if cents is not None else "a message"
    events.record(conn, sent.work_order_id, "mechanic", "message_sent", f"Sent {name} {what}")
    return {"message": asdict(sent), "customer_link_token": customer_links.link_token(conn, sent.work_order_id)}


@router.post("/purchase-orders/{po_id}/receive")
def receive_purchase_order(po_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The parts arrived: put them on the shelf."""
    procurement.receive_purchase_order(conn, po_id)
    po = conn.execute("SELECT work_order_id FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    lines = next(o for o in procurement.list_purchase_orders(conn, po["work_order_id"]) if o["id"] == po_id)
    events.record(conn, po["work_order_id"], "mechanic", "parts_received",
                  f"Marked {', '.join(line['sku'] for line in lines['lines'])} received from {lines['supplier']}")
    started = flow.start_when_ready(conn, po["work_order_id"])  # the last part in: the shop books and starts it
    return {"status": "received", "repair_started": started}


@router.post("/work-orders/{work_order_id}/schedule")
def schedule_repair(work_order_id: int, body: Schedule, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Book the repair once every part is in stock."""
    wo.schedule_repair(conn, work_order_id, body.scheduled_for)
    events.record(conn, work_order_id, "mechanic", "scheduled", f"Booked the repair for {_long_date(body.scheduled_for)}")
    return work_order_detail(conn, work_order_id)


@router.post("/work-orders/{work_order_id}/start")
def start_repair(work_order_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    wo.start_repair(conn, work_order_id)
    events.record(conn, work_order_id, "mechanic", "started", "Started the repair")
    return work_order_detail(conn, work_order_id)


@router.post("/work-orders/{work_order_id}/finish")
def finish_repair(work_order_id: int, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Mark the repair done; its parts come off the shelf."""
    wo.finish_repair(conn, work_order_id)
    events.record(conn, work_order_id, "mechanic", "finished", "Finished the repair")
    return work_order_detail(conn, work_order_id)


@router.get("/audit")
def audit_log(
    conversation_id: str | None = None,
    refused_only: bool = False,
    limit: int = 300,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Every tool call the Agent made, newest first: tool, MCP server, arguments, result, refusals.

    Written by the MCP servers themselves, so it's the same whichever agent runtime called.
    """
    import json

    from agents import activity

    where, params = [], []
    if conversation_id:
        where.append("a.conversation_id = ?")
        params.append(conversation_id)
    if refused_only:
        where.append("a.result_summary LIKE 'refused:%'")
    # The work order comes from the Agent's conversation, or else from the call's own arguments
    # (a scripted client like `make demo` has no conversation).
    sql = f"""SELECT a.id, a.at, a.conversation_id, a.runtime, a.tool, a.args_json, a.result_summary,
                     COALESCE(c.work_order_id, json_extract(a.args_json, '$.work_order_id')) AS work_order_id
              FROM audit_log a LEFT JOIN agent_conversations c ON c.id = a.conversation_id
              {"WHERE " + " AND ".join(where) if where else ""}
              ORDER BY a.id DESC LIMIT ?"""
    rows = conn.execute(sql, (*params, max(1, min(limit, 1000)))).fetchall()
    totals = conn.execute(
        "SELECT COUNT(*), SUM(result_summary LIKE 'refused:%') FROM audit_log"
    ).fetchone()
    return {
        "total": totals[0], "refused": totals[1] or 0,
        "entries": [
            {
                "id": r["id"], "at": r["at"], "conversation_id": r["conversation_id"], "work_order_id": r["work_order_id"],
                "runtime": r["runtime"], "tool": r["tool"], "server": activity.server_for(r["tool"]),
                "arguments": json.loads(r["args_json"]), "result": r["result_summary"],
                "refused": (r["result_summary"] or "").startswith("refused:"),
            }
            for r in rows
        ],
    }
