"""The web pages are served by the API, and the Customer page gets what it needs."""

from fastapi.testclient import TestClient

from api.app import app
from shop import customer_links, messages
from shop import work_orders as wo
from shop.procurement import create_purchase_order, receive_purchase_order


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    return TestClient(app)


def test_customer_page_and_assets_are_served(conn, tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    page = c.get("/c/any-token")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert page.headers["referrer-policy"] == "no-referrer"
    assert '<script type="module" src="/static/js/customer.js">' in page.text
    assert "Stripe test mode" in page.text  # the demo footer
    for asset in ("/static/css/shop.css", "/static/js/customer.js", "/static/js/dom.js"):
        response = c.get(asset)
        assert response.status_code == 200, asset
        assert response.headers["cache-control"] == "no-cache", asset  # an updated script is picked up on the next load


def test_customer_view_has_the_timeline(conn, tmp_path, monkeypatch, approved):
    velo = conn.execute("SELECT id FROM suppliers WHERE name = 'Velo Supply Co.'").fetchone()[0]
    receive_purchase_order(conn, create_purchase_order(conn, approved, velo, [("AD-C11-34W", 1)]).id)
    wo.schedule_repair(conn, approved, "2026-11-19")
    wo.start_repair(conn, approved)
    wo.finish_repair(conn, approved)
    view = client(tmp_path, monkeypatch).get(f"/api/customer/{customer_links.link_token(conn, approved)}").json()
    assert view["work_order_id"] == approved
    t = view["timeline"]
    assert t["decided_at"] and t["parts_ordered"] and t["parts_received_at"] and t["finished_at"]
    assert t["paid_at"] is None
    assert [line["category"] for line in view["quote"]["lines"]] == ["cassette", "chain", "labor"]


def test_drafts_never_reach_the_customer_page_data(conn, tmp_path, monkeypatch, quoted, quote_sent):
    messages.draft_message(conn, quoted, "Internal: check the rotor too")
    view = client(tmp_path, monkeypatch).get(f"/api/customer/{customer_links.link_token(conn, quoted)}").json()
    assert all("Internal" not in m["body"] for m in view["messages"])


def test_workshop_page_is_served(conn, tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    page = c.get("/workshop")
    assert page.status_code == 200 and '<script type="module" src="/static/js/workshop.js">' in page.text
    for asset in ("/static/js/workshop.js", "/static/js/staff.js", "/static/js/agent.js"):
        assert c.get(asset).status_code == 200, asset


def test_next_step_follows_the_work_order(conn, tmp_path, monkeypatch, diagnosed):
    from api.staff import next_step
    from shop import flow, procurement
    from shop import messages as msgs

    assert next_step(conn, diagnosed, "diagnosed")["waiting_on"] == "agent"
    wo.add_part(conn, diagnosed, "AD-C11-34W")
    wo.lock_quote(conn, diagnosed)
    procurement.set_order_plan(conn, diagnosed, [("AD-C11-34W", 1, 1)])
    draft = msgs.draft_message(conn, diagnosed, "Hi Emma", include_quote=True)
    step = next_step(conn, diagnosed, "quoted")
    assert step["waiting_on"] == "mechanic" and step["action"] == {"kind": "send_draft", "message_id": draft.id, "label": "Send to Emma"}
    msgs.send_draft(conn, draft.id)
    assert next_step(conn, diagnosed, "quoted")["waiting_on"] == "customer"
    msgs.receive_message(conn, diagnosed, "Can it be ready by Friday?")
    step = next_step(conn, diagnosed, "quoted")
    assert step["action"]["kind"] == "ask_agent" and "Can it be ready by Friday?" in step["action"]["prompt"]
    msgs.send_draft(conn, msgs.draft_message(conn, diagnosed, "Yes, Thursday works").id)  # answered
    flow.customer_decides(conn, draft.id, approved=True)  # the shop places the planned order
    step = next_step(conn, diagnosed, "awaiting_parts")
    assert step["action"]["kind"] == "receive" and step["action"]["label"] == "Mark AD-C11-34W received"
    procurement.receive_purchase_order(conn, step["action"]["purchase_order_id"])
    step = next_step(conn, diagnosed, "awaiting_parts")
    assert step["action"]["kind"] == "book"
    assert step["action"]["date"] == conn.execute("SELECT promised_ready_on FROM work_orders WHERE id = ?", (diagnosed,)).fetchone()[0]
    wo.schedule_repair(conn, diagnosed, step["action"]["date"])
    assert next_step(conn, diagnosed, "scheduled")["action"]["kind"] == "start"
    wo.start_repair(conn, diagnosed)
    assert next_step(conn, diagnosed, "in_progress")["action"]["label"] == "Repair done"
    wo.finish_repair(conn, diagnosed)
    assert next_step(conn, diagnosed, "done")["action"]["kind"] == "ask_agent"  # tell the Customer it's ready
    msgs.send_draft(conn, msgs.draft_message(conn, diagnosed, "Your bike is ready").id)
    assert next_step(conn, diagnosed, "done")["waiting_on"] == "customer"


def test_approval_without_a_plan_asks_the_agent_to_order(conn, quote_sent, quoted):
    from api.staff import next_step
    from shop import flow

    result = flow.customer_decides(conn, quote_sent, approved=True)
    assert result["placed"] == [] and result["failed"] == []
    step = next_step(conn, quoted, "approved")
    assert step["waiting_on"] == "mechanic" and step["action"]["kind"] == "ask_agent"
    assert "No order was planned" in step["text"]


def test_list_and_detail_carry_next_step_and_conversations(conn, tmp_path, monkeypatch, quoted):
    from agents import conversations

    monkeypatch.setenv("STAFF_PASSCODE", "pc")
    convo = conversations.create(conn, "anthropic")
    conversations.link_work_order(conn, convo.id, quoted)
    c = client(tmp_path, monkeypatch)
    staff = {"Authorization": "Bearer pc"}
    [row] = c.get("/api/work-orders", headers=staff).json()
    assert row["next_step"]["waiting_on"] == "agent"  # quote locked, no message drafted yet
    detail = c.get(f"/api/work-orders/{quoted}", headers=staff).json()
    assert detail["conversation_ids"] == [convo.id]


def test_request_connections_can_cross_worker_threads(conn, tmp_path, monkeypatch):
    """FastAPI may open a request's connection in one worker thread and use it in another."""
    import threading
    from api.deps import get_db

    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    gen = get_db()
    request_conn = next(gen)
    errors = []
    worker = threading.Thread(target=lambda: errors.extend(
        [] if request_conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0] else ["no parts"]))
    worker.start()
    worker.join()
    gen.close()
    assert errors == []
