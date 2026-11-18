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

from api import sandboxes
from demo.sample import create_sample
from demo.stories import BY_KEY, STORIES
from shop import db, messages

router = APIRouter(prefix="/api/demo", tags=["demo"])

RESULTS = Path(__file__).resolve().parent.parent / "evals" / "results"
SUITE = Path(__file__).resolve().parent.parent / "evals" / "latest.json"  # committed by `make evals`

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
    """The newest full eval suite (evals/latest.json, committed), or else the newest `make agent-check` run here."""
    if SUITE.exists():
        data = json.loads(SUITE.read_text())
        return {
            "suite": True,
            "passed_runs": data["passed_runs"], "total_runs": data["total_runs"],
            "scenarios": len(data["scenarios"]), "runs_per_scenario": data["runs_per_scenario"],
            "scenarios_all_passed": sum(s["passed_runs"] == s["runs"] for s in data["scenarios"]),
            "cost_usd": data.get("cost_usd"), "model": data.get("model"), "ran_at": data.get("ran_at"),
        }
    files =sorted(RESULTS.glob("hero-*.json")) if RESULTS.exists() else []
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
    return sandboxes.public_token(row["token"]) if row else None


REPAIR = ("approved", "awaiting_parts", "scheduled", "in_progress", "done")


NO_STORY = {"step": 1, "whose": "mechanic", "work_order_id": None, "customer_token": None,
            "customer": None, "next_step": None, "action": None, "total_cents": None, "status": None}


def story(conn) -> dict[str, Any]:
    """Where the hero story stands on the newest work order, for the demo stage's step guide.

    Steps: 1 ask the Agent, 2 send the quote, 3 the Customer approves, 4 the repair,
    5 the Customer pays, 6 finished. `whose` says which side acts next.
    """
    from api.staff import next_step

    row = conn.execute(
        """SELECT w.id, w.status, w.quoted_total_cents, c.name, l.token
           FROM work_orders w JOIN customer_bikes b ON b.id = w.customer_bike_id
           JOIN customers c ON c.id = b.customer_id
           LEFT JOIN customer_links l ON l.work_order_id = w.id
           ORDER BY w.id DESC LIMIT 1"""
    ).fetchone()
    if row is None:
        return dict(NO_STORY)
    status = row["status"]
    step_info = next_step(conn, row["id"], status)
    thread = messages.list_messages(conn, row["id"])
    sent_quote = any(m.status == "sent" and m.quoted_total_cents is not None for m in thread)
    draft_quote = any(m.status == "draft" and m.quoted_total_cents is not None for m in thread)
    if status in ("paid", "declined"):
        step = 6
    elif status == "done" and _told_ready(conn, row["id"], thread):
        step = 5
    elif status in REPAIR:
        step = 4
    elif sent_quote:
        step = 3
    elif draft_quote:
        step = 2
    else:
        step = 1
    # Usually the Customer acts in steps 3 and 5, but a question from her hands the turn back to the shop.
    whose = "nobody" if step == 6 else "customer" if step_info["waiting_on"] == "customer" else "mechanic"
    return {
        "step": step, "whose": whose, "status": status, "work_order_id": row["id"],
        "customer": row["name"], "total_cents": row["quoted_total_cents"],
        "customer_token": sandboxes.public_token(row["token"]) if row["token"] else None,
        "next_step": step_info["text"], "action": (step_info.get("action") or {}).get("kind"),
    }


def _told_ready(conn, work_order_id: int, thread) -> bool:
    """Whether the shop has messaged the Customer since the repair was finished."""
    finished = conn.execute("SELECT finished_at FROM work_orders WHERE id = ?", (work_order_id,)).fetchone()[0]
    return bool(finished) and any(
        m.direction == "to_customer" and m.status == "sent" and (m.sent_at or "") > finished for m in thread
    )


@router.get("")
def demo_status() -> dict[str, Any]:
    """What the front door shows. The passcode and sample link are only given out in demo mode."""
    info: dict[str, Any] = {"demo_mode": demo_mode(), "latest_eval": latest_eval()}
    if demo_mode() and sandboxes.enabled() and sandboxes.current_key() is None:
        # A visitor without a sandbox yet: nothing to show, and looking doesn't make one.
        info.update(staff_passcode=os.environ.get("STAFF_PASSCODE") or None, customer_token=None, story=dict(NO_STORY))
    elif demo_mode():
        conn = db.connect()
        try:
            info["staff_passcode"] = os.environ.get("STAFF_PASSCODE") or None
            info["customer_token"] = _sample_link(conn)
            info["story"] = story(conn)
        finally:
            conn.close()
    return info


def _require_demo_mode(action: str) -> None:
    if not demo_mode():
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{action} is only available in demo mode (DEMO_MODE=1)")


async def _reset(request: Request) -> None:
    await request.app.state.agent_pool.close_database()  # open conversations would point at deleted rows
    from shop import seed

    conn = db.connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        with conn:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")
        conn.execute("PRAGMA foreign_keys = ON")
        seed.load(conn)
    finally:
        conn.close()


@router.post("/reset")
async def reset(request: Request) -> dict[str, Any]:
    """Clear the shop's activity and start again from the seed data, with nothing waiting.

    Work orders, messages, conversations, history, the audit log and payments go.
    The catalog, the Customer, her bike and the suppliers are reloaded exactly as
    seeded, so stock and service history are back where the story starts.
    """
    _require_demo_mode("reset")
    await _reset(request)
    return {"status": "reset"}


def _measured() -> dict[str, dict]:
    """Each scenario's pass rate from the last full eval suite, by key."""
    if not SUITE.exists():
        return {}
    return {s["key"]: {"passed": s["passed_runs"], "runs": s["runs"]}
            for s in json.loads(SUITE.read_text())["scenarios"]}


@router.get("/stories")
def stories() -> list[dict[str, Any]]:
    """The repair stories a visitor can pick, each with its eval's last pass rate."""
    measured = _measured()
    return [
        {"key": s.key, "label": s.label, "title": s.title, "group": s.group, "customer": s.customer, "bike": s.bike,
         "complaint": s.complaint_on(), "watch_for": s.watch_for_on(),
         "photo": f"/static/img/bikes/{s.photo}", "profile": [list(row) for row in s.profile],
         "message": s.mechanic_message(), "measured": measured.get(s.key)}
        for s in STORIES
    ]


@router.post("/stories/{key}/start")
async def start_story(key: str, request: Request) -> dict[str, Any]:
    """Start a story fresh: reset the shop, and return the Mechanic's opening message for it."""
    _require_demo_mode("starting a story")
    story = BY_KEY.get(key)
    if story is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no story {key!r}")
    await _reset(request)
    return {"key": story.key, "customer": story.customer, "message": story.mechanic_message()}


@router.post("/sample")
def sample() -> dict[str, Any]:
    """Add the hero work order with its quote already sent, for trying the Customer's side without the Agent."""
    _require_demo_mode("generating a sample quote")
    conn = db.connect()
    try:
        order, token, _ = create_sample(conn, source="the front door")
    finally:
        conn.close()
    return {"work_order_id": order, "customer_token": sandboxes.public_token(token)}
