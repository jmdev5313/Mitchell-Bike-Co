"""The visitor front door's data: what this demo is, how to try it, and the latest eval result.

Demo mode (DEMO_MODE=1) is for a shared demo. It hands visitors the workshop
passcode and a sample Customer link so they can try both sides without setup,
and lets them reset the shop to a clean state. Never turn it on for real data.
"""

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from demo.sample import create_sample
from shop import db

router = APIRouter(prefix="/api/demo", tags=["demo"])

RESULTS = Path(__file__).resolve().parent.parent / "evals" / "results"

# Tables in an order that respects foreign keys when clearing them.
TABLES = [
    "work_order_events", "audit_log", "agent_messages", "agent_conversations", "payments",
    "customer_links", "order_plan_lines", "purchase_order_lines", "purchase_orders", "customer_messages",
    "work_order_lines", "work_orders", "service_records", "bike_standards", "customer_bikes", "customers",
    "supplier_parts", "suppliers", "bike_model_standards", "bike_models", "part_requirements", "parts",
    "services", "standard_compat", "standards", "settings",
]


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def latest_eval() -> dict[str, Any] | None:
    """The newest `make agent-check` result, if one has been run here."""
    files = sorted(RESULTS.glob("hero-*.json")) if RESULTS.exists() else []
    if not files:
        return None
    data = json.loads(files[-1].read_text())
    required = [c for c in data["checks"] if c["required"]]
    return {
        "passed": data["passed"],
        "required_passed": sum(c["passed"] for c in required),
        "required_total": len(required),
        "cost_usd": data.get("cost_usd"),
        "model": data.get("model"),
        "ran_at": files[-1].stem.rsplit("-", 1)[-1],
        "tool_calls": sum(len(t["tools"]) for t in data.get("turns", [])),
    }


def _sample_link(conn) -> str | None:
    row = conn.execute(
        """SELECT l.token FROM customer_links l JOIN work_orders w ON w.id = l.work_order_id
           WHERE w.status NOT IN ('paid', 'declined') ORDER BY w.id DESC LIMIT 1"""
    ).fetchone()
    return row["token"] if row else None


@router.get("")
def demo_status() -> dict[str, Any]:
    """What the front door shows. The passcode and sample link are only given out in demo mode."""
    info: dict[str, Any] = {"demo_mode": demo_mode(), "latest_eval": latest_eval()}
    if demo_mode():
        conn = db.connect()
        try:
            info["staff_passcode"] = os.environ.get("STAFF_PASSCODE") or None
            info["customer_token"] = _sample_link(conn)
        finally:
            conn.close()
    return info


@router.post("/reset")
async def reset(request: Request) -> dict[str, Any]:
    """Clear the shop and start again with the seed data and one quote waiting for the Customer."""
    if not demo_mode():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "reset is only available in demo mode (DEMO_MODE=1)")
    await request.app.state.agent_pool.close_all()  # open conversations would point at deleted rows
    from shop import seed

    conn = db.connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        with conn:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")
        conn.execute("PRAGMA foreign_keys = ON")
        seed.load(conn)
        order, token, _ = create_sample(conn, source="the demo reset")
    finally:
        conn.close()
    return {"status": "reset", "work_order_id": order, "customer_token": token}
