"""Checks that several scenarios share. Each reads the shop's state, not the Agent's wording."""

import re
import sqlite3
from datetime import date

from agents import conversations
from evals.common import Report, date_mentions
from shop import compat, messages, procurement, schedule
from shop import work_orders as wo

PART_NUMBER = re.compile(r"\b[A-Z]{2}-[A-Z0-9-]{3,}\b")


def bike_of(conn: sqlite3.Connection, email: str) -> int:
    """The customer's bike (each seed customer has one)."""
    return conn.execute(
        "SELECT cb.id FROM customer_bikes cb JOIN customers c ON c.id = cb.customer_id WHERE c.email = ?", (email,)
    ).fetchone()[0]


def linked_work_order(conn: sqlite3.Connection, report: Report) -> int | None:
    """The work order the Agent's conversation acted on first."""
    return conversations.get(conn, report.conversation_id).work_order_id


def quote_lines(conn: sqlite3.Connection, work_order_id: int) -> tuple[list[str], list[str], dict]:
    order = wo.summary(conn, work_order_id)
    skus = [line["sku"] for line in order["lines"] if line["sku"]]
    services = [line["name"] for line in order["lines"] if line["kind"] == "service"]
    return skus, services, order


def work_order_for_bike(conn: sqlite3.Connection, report: Report, bike_id: int) -> int | None:
    work_order_id = linked_work_order(conn, report)
    if not report.add("opened a work order for the bike", work_order_id is not None):
        return None
    on_bike = wo.summary(conn, work_order_id)["customer_bike_id"]
    report.add("the work order is for the right bike", on_bike == bike_id, f"bike {on_bike}, expected {bike_id}")
    return work_order_id


def parts_fit(conn: sqlite3.Connection, report: Report, skus: list[str], bike_id: int) -> None:
    misfits = [sku for sku in skus if not compat.check_fit(conn, sku, bike_id).fits]
    report.add("every part on the quote fits the bike", not misfits, f"don't fit: {misfits}" if misfits else "")


def backed_dates(conn: sqlite3.Connection, work_order_id: int, today: date) -> list[date]:
    """Ready dates the shop can stand behind: the order plan's, or tomorrow when everything is in stock."""
    plan = procurement.order_plan(conn, work_order_id)
    if plan["lines"] and plan["promised_ready_on"]:
        return [date.fromisoformat(plan["promised_ready_on"])]
    if not wo.parts_short(conn, work_order_id):
        return [schedule.ready_date(today, 0)]
    return []


def quote_message(conn: sqlite3.Connection, report: Report, work_order_id: int, today: date):
    """The drafted message with the quote: the locked total, plain words, a date the shop backs up."""
    order = wo.summary(conn, work_order_id)
    total = order["quoted_total_cents"]
    report.add("quote is locked", order["status"] == "quoted", f"status: {order['status']}")
    drafts = [m for m in messages.list_messages(conn, work_order_id)
              if m.status == "draft" and m.quoted_total_cents is not None]
    if not report.add("drafted a message that carries the quote", bool(drafts)):
        return None
    draft = drafts[-1]
    body = draft.body
    if total is not None:
        report.add("message states the quoted total", f"{total / 100:.2f}" in body, body)
    report.add("message uses no part numbers", not PART_NUMBER.search(body), body)
    dates = backed_dates(conn, work_order_id, today)
    report.add(
        "message promises a ready date the shop backs up",
        any(m in body for d in dates for m in date_mentions(d)),
        f"backed: {[d.isoformat() for d in dates] or 'none (an out-of-stock part has no plan)'}",
    )
    return draft


def nothing_ordered(conn: sqlite3.Connection, report: Report) -> None:
    report.add("nothing was ordered before the Customer approved",
               not conn.execute("SELECT 1 FROM purchase_orders").fetchone())


def all_quoted_skus(conn: sqlite3.Connection) -> list[str]:
    """Every part on every work order, so a scenario can check nothing unwanted was added anywhere."""
    return [r[0] for r in conn.execute(
        "SELECT p.sku FROM work_order_lines l JOIN parts p ON p.id = l.part_id WHERE l.part_id IS NOT NULL"
    )]


def all_quoted_services(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT s.name FROM work_order_lines l JOIN services s ON s.id = l.service_id WHERE l.service_id IS NOT NULL"
    )]
