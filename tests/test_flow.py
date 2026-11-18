"""The order plan, the shop ordering on approval, and the work order's history."""

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from api.app import app
from mcp_servers import procurement as procurement_server
from mcp_servers import work_orders as work_orders_server
from shop import customer_links, events, flow, messages, procurement
from shop import work_orders as wo
from shop.errors import RuleViolation

STAFF = {"Authorization": "Bearer pc"}


@pytest.fixture
def client(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    monkeypatch.setenv("STAFF_PASSCODE", "pc")
    return TestClient(app)


# --- The plan and the shop's automatic order ---------------------------------

def test_plan_then_approval_places_the_order(conn, quoted, quote_sent):
    from datetime import date
    plan = procurement.set_order_plan(conn, quoted, [("AD-C11-34W", 1, 1)], today=date(2026, 11, 16))
    assert plan["promised_ready_on"] == "2026-11-19"  # Velo: 2 days + 1 repair day
    assert plan["lines"][0]["supplier"] == "Velo Supply Co." and plan["lines"][0]["total_cents"] == 4250
    result = flow.customer_decides(conn, quote_sent, approved=True)
    assert result["status"] == "approved" and not result["failed"]
    assert [(po["supplier"], po["skus"], po["total_cents"]) for po in result["placed"]] == [
        ("Velo Supply Co.", ["AD-C11-34W"], 4250)
    ]
    assert wo.status(conn, quoted) == "awaiting_parts"
    kinds = [(e["actor"], e["kind"]) for e in events.history(conn, quoted)]
    assert kinds == [("customer", "approved"), ("shop", "order_placed")]


def test_a_failed_plan_is_recorded_for_the_agent_to_fix(conn, quoted, quote_sent):
    procurement.set_order_plan(conn, quoted, [("AD-C11-34W", 1, 1)])
    conn.execute("UPDATE supplier_parts SET available_qty = 0 WHERE supplier_id = 1")  # Velo sold out
    result = flow.customer_decides(conn, quote_sent, approved=True)
    assert result["placed"] == [] and "supplier has 0" in result["failed"][0]["reason"]
    [failed] = [e for e in events.history(conn, quoted) if e["kind"] == "order_failed"]
    assert failed["is_error"] and failed["actor"] == "shop"


def test_declining_orders_nothing(conn, quoted, quote_sent):
    procurement.set_order_plan(conn, quoted, [("AD-C11-34W", 1, 1)])
    result = flow.customer_decides(conn, quote_sent, approved=False)
    assert result == {"status": "declined", "placed": [], "failed": []}
    assert not conn.execute("SELECT 1 FROM purchase_orders").fetchone()


@pytest.mark.parametrize("lines, match", [
    ([("AD-C11-34W", 1, 2)], "work order has 1, plan asks for 2"),
    ([("AD-C11-28R", 1, 1)], "work order has 0"),
    ([("AD-C11-34W", 3, 1)], "does not carry"),
    ([("AD-C11-34W", 2, 5)], "work order has 1"),
])
def test_plans_follow_the_rules(conn, quoted, lines, match):
    with pytest.raises(RuleViolation, match=match):
        procurement.set_order_plan(conn, quoted, lines)


def test_no_plan_after_the_customer_decides(conn, quoted, quote_sent):
    flow.customer_decides(conn, quote_sent, approved=True)
    with pytest.raises(RuleViolation, match="before the customer decides"):
        procurement.set_order_plan(conn, quoted, [("AD-C11-34W", 1, 1)])


# --- History written by each actor -------------------------------------------

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_agent_tool_calls_land_in_history(conn, tmp_path, monkeypatch, quoted):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    async with Client(procurement_server.server) as c:
        await c.call_tool("plan_order", {"work_order_id": quoted, "lines": [{"sku": "AD-C11-34W", "supplier_id": 1, "qty": 1}]})
        await c.call_tool("create_purchase_order", {"work_order_id": quoted, "supplier_id": 1, "lines": [{"sku": "AD-C11-34W", "qty": 1}]})
    async with Client(work_orders_server.server) as c:
        await c.call_tool("get_work_order", {"work_order_id": quoted})  # lookups aren't history
    history = events.history(conn, quoted)
    assert [(e["actor"], e["kind"], e["is_error"]) for e in history] == [
        ("agent", "tool:plan_order", False), ("agent", "tool:create_purchase_order", True)]
    assert history[0]["summary"].startswith("Plan: AD-C11-34W from Velo Supply Co.")
    assert history[0]["detail"] == {"tool": "plan_order", "server": "procurement"}
    assert "after the customer approves the quote" in history[1]["summary"]


def test_mechanic_and_customer_actions_land_in_history(client, conn, quoted):
    procurement.set_order_plan(conn, quoted, [("AD-C11-34W", 1, 1)])
    draft = messages.draft_message(conn, quoted, "Your repair comes to $169.98.", include_quote=True)
    client.patch(f"/api/messages/{draft.id}", headers=STAFF, json={"body": "Hi Emma, it's $169.98."})
    token = client.post(f"/api/messages/{draft.id}/send", headers=STAFF).json()["customer_link_token"]
    client.get(f"/api/customer/{token}")
    client.get(f"/api/customer/{token}")  # a reload: not recorded again
    client.post(f"/api/customer/{token}/replies", json={"body": "Can it be ready by Friday?"})
    client.post(f"/api/customer/{token}/messages/{draft.id}/decision", json={"approved": True})
    history = [(e["actor"], e["summary"]) for e in events.history(conn, quoted)]
    assert history == [
        ("mechanic", "Edited the Agent's draft before sending"),
        ("mechanic", "Sent Emma the $169.98 quote"),
        ("customer", "Opened their link for the first time"),
        ("customer", "Asked: “Can it be ready by Friday?”"),
        ("customer", "Approved the $169.98 quote"),
        ("shop", "Placed the planned order: AD-C11-34W from Velo Supply Co., $42.50"),
    ]


def test_badges_count_what_others_did_since_the_mechanic_looked(client, conn, quoted, quote_sent):
    token = customer_links.link_token(conn, quoted)
    client.get(f"/api/customer/{token}")
    [row] = client.get("/api/work-orders", headers=STAFF).json()
    assert row["unseen_count"] == 1 and row["unseen_actor"] == "customer"
    before = client.get("/api/activity/latest", headers=STAFF).json()
    assert client.post(f"/api/work-orders/{quoted}/seen", headers=STAFF).json() == {"status": "seen"}
    [row] = client.get("/api/work-orders", headers=STAFF).json()
    assert row["unseen_count"] == 0
    client.post(f"/api/customer/{token}/replies", json={"body": "Thanks"})
    after = client.get("/api/activity/latest", headers=STAFF).json()
    assert after["latest_event_id"] > before["latest_event_id"]
    assert after["needs_you"] == 1  # a Customer reply waits on the mechanic
    detail = client.get(f"/api/work-orders/{quoted}", headers=STAFF).json()
    assert [e["summary"] for e in detail["unseen"]] == ["Asked: “Thanks”"]


def test_approving_a_job_with_everything_in_stock_starts_it(conn):
    """Nothing to order: the shop books the repair for today and starts it at approval."""
    from datetime import date

    from shop import events, messages
    from shop import work_orders as wo

    bike = conn.execute("SELECT cb.id FROM customer_bikes cb JOIN customers c ON c.id = cb.customer_id "
                        "WHERE c.email = 'grace.lee@example.com'").fetchone()[0]
    order = wo.open_work_order(conn, bike, "Skipping")
    wo.record_diagnosis(conn, order, "Worn")
    wo.add_part(conn, order, "AD-C11-28R")
    wo.add_part(conn, order, "AD-CH11")
    wo.lock_quote(conn, order)
    quote = messages.draft_message(conn, order, "Hi Grace", include_quote=True)
    messages.send_draft(conn, quote.id)
    result = flow.customer_decides(conn, quote.id, approved=True)
    assert result["started"] is True and result["placed"] == []
    assert wo.status(conn, order) == "in_progress"
    booked = conn.execute("SELECT scheduled_for FROM work_orders WHERE id = ?", (order,)).fetchone()[0]
    assert booked == date.today().isoformat()
    assert events.history(conn, order)[-1]["actor"] == "shop"


def test_a_job_still_waiting_for_parts_doesnt_start(conn):
    from demo.sample import create_sample
    from shop import work_orders as wo

    order, _, quote_id = create_sample(conn)
    result = flow.customer_decides(conn, quote_id, approved=True)
    assert result["placed"] and result["started"] is False
    assert wo.status(conn, order) == "awaiting_parts"
