"""Private links that let a customer see their own work order, without an account.

A link is an unguessable token tied to one work order. Anyone holding it can see
that work order's thread and answer its quote, the way a "view your quote" text
from a shop works, and nothing else.
"""

import secrets
import sqlite3

from shop.errors import NotFound

TOKEN_BYTES = 24  # 192 bits, URL-safe


def link_token(conn: sqlite3.Connection, work_order_id: int) -> str:
    """The work order's token, created the first time it is asked for."""
    if not conn.execute("SELECT 1 FROM work_orders WHERE id = ?", (work_order_id,)).fetchone():
        raise NotFound(f"no work order with id {work_order_id}")
    row = conn.execute("SELECT token FROM customer_links WHERE work_order_id = ?", (work_order_id,)).fetchone()
    if row:
        return row["token"]
    token = secrets.token_urlsafe(TOKEN_BYTES)
    with conn:
        conn.execute("INSERT INTO customer_links (token, work_order_id) VALUES (?, ?)", (token, work_order_id))
    return token


def work_order_for(conn: sqlite3.Connection, token: str) -> int:
    row = conn.execute("SELECT work_order_id FROM customer_links WHERE token = ?", (token or "",)).fetchone()
    if row is None:
        raise NotFound("this link is not valid")
    return row["work_order_id"]
