"""The front door, demo mode, the demo reset, and the audit log."""

import json

import pytest
from fastapi.testclient import TestClient

from api import demo
from api.app import app
from demo.sample import create_sample
from shop import customer_links

STAFF = {"Authorization": "Bearer pc"}


@pytest.fixture
def client(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    monkeypatch.setenv("STAFF_PASSCODE", "pc")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setattr(demo, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(demo, "SUITE", tmp_path / "latest.json")
    with TestClient(app) as c:
        yield c


def test_front_door_is_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "Be the Mechanic" in page.text and "Be the Customer" in page.text
    assert client.get("/static/js/home.js").status_code == 200
    stage = client.get("/demo")
    assert stage.status_code == 200 and "stage.js" in stage.text
    assert client.get("/static/js/stage.js").status_code == 200 and client.get("/static/js/cue.js").status_code == 200


def test_outside_demo_mode_nothing_is_handed_out(client, conn):
    create_sample(conn)
    info = client.get("/api/demo").json()
    assert info == {"demo_mode": False, "latest_eval": None}
    assert client.post("/api/demo/reset").status_code == 403


def test_demo_mode_hands_out_the_passcode_and_a_sample_link(client, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    order, token, _ = create_sample(conn)
    info = client.get("/api/demo").json()
    assert info["demo_mode"] and info["staff_passcode"] == "pc" and info["customer_token"] == token


def test_demo_reset_clears_activity_and_leaves_nothing_waiting(client, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    for _ in range(3):
        create_sample(conn, done=True)
    parts = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    assert client.post("/api/demo/reset").json() == {"status": "reset"}
    for table in ("work_orders", "purchase_orders", "customer_messages", "work_order_events", "audit_log", "payments"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == parts
    assert conn.execute("SELECT COUNT(*) FROM customers WHERE name = 'Emma Clark'").fetchone()[0] == 1
    assert client.get("/api/demo").json()["customer_token"] is None


def test_sample_quote_is_separate_and_demo_only(client, conn, monkeypatch):
    assert client.post("/api/demo/sample").status_code == 403
    monkeypatch.setenv("DEMO_MODE", "1")
    client.post("/api/demo/reset")
    result = client.post("/api/demo/sample").json()
    assert customer_links.work_order_for(conn, result["customer_token"]) == result["work_order_id"]
    assert client.get(f"/api/customer/{result['customer_token']}").json()["status"] == "quoted"
    assert client.get("/api/demo").json()["customer_token"] == result["customer_token"]


def test_latest_eval_is_read_from_the_newest_result(client, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    checks = [{"name": "a", "passed": True, "required": True}, {"name": "b", "passed": True, "required": True},
              {"name": "c", "passed": False, "required": False}]
    (results / "hero-anthropic-20261101T000000Z.json").write_text(json.dumps(
        {"passed": False, "checks": [], "turns": [], "model": "old"}))
    (results / "hero-anthropic-20261117T020551Z.json").write_text(json.dumps(
        {"passed": True, "checks": checks, "cost_usd": 0.068, "model": "claude-sonnet-5-5",
         "turns": [{"tools": ["a", "b"]}, {"tools": ["c"]}]}))
    assert client.get("/api/demo").json()["latest_eval"] == {
        "passed": True, "required_passed": 2, "required_total": 2, "cost_usd": 0.068,
        "model": "claude-sonnet-5-5", "ran_at": "20261117T020551Z", "tool_calls": 3,
    }


def test_audit_log_lists_tool_calls_and_refusals(client, conn):
    conn.executemany(
        "INSERT INTO audit_log (runtime, tool, args_json, result_summary) VALUES (?, ?, ?, ?)",
        [("anthropic", "check_fit", '{"sku": "AD-C11-34W"}', '{"fits": true}'),
         ("anthropic", "add_part", '{"work_order_id": 7, "sku": "AD-C11-28R"}', "refused: AD-C11-28R does not fit this bike")],
    )
    conn.commit()
    assert client.get("/api/audit").status_code == 401
    data = client.get("/api/audit", headers=STAFF).json()
    assert (data["total"], data["refused"]) == (2, 1)
    assert [(e["tool"], e["server"], e["refused"]) for e in data["entries"]] == [
        ("add_part", "work orders", True), ("check_fit", "catalog", False)]
    assert data["entries"][0]["arguments"] == {"work_order_id": 7, "sku": "AD-C11-28R"}
    # No conversation (a scripted client): the work order comes from the call's arguments, when it has one.
    assert [e["work_order_id"] for e in data["entries"]] == [7, None]
    refused = client.get("/api/audit?refused_only=true", headers=STAFF).json()["entries"]
    assert [e["tool"] for e in refused] == ["add_part"]


def test_the_story_follows_the_newest_work_order(client, conn, monkeypatch):
    from shop import flow, messages

    monkeypatch.setenv("DEMO_MODE", "1")
    client.post("/api/demo/reset")
    assert client.get("/api/demo").json()["story"]["step"] == 1
    order, token, quote_id = create_sample(conn)
    story = client.get("/api/demo").json()["story"]
    assert (story["step"], story["whose"], story["customer_token"]) == (3, "customer", token)
    flow.customer_decides(conn, quote_id, approved=True)
    story = client.get("/api/demo").json()["story"]
    assert (story["step"], story["whose"]) == (4, "mechanic")
    client.post("/api/demo/reset")
    order, _, _ = create_sample(conn, done=True)
    story = client.get("/api/demo").json()["story"]
    assert (story["step"], story["next_step"]) == (4, "Tell Emma the bike is ready")
    ready = messages.draft_message(conn, order, "Your bike is ready.", author="mechanic")
    messages.send_draft(conn, ready.id)
    assert client.get("/api/demo").json()["story"]["step"] == 5
    messages.receive_message(conn, order, "See you Friday!")
    story = client.get("/api/demo").json()["story"]
    assert (story["step"], story["whose"]) == (5, "mechanic")  # her question hands the turn back, same step


def test_the_suite_summary_wins_over_the_hero_check(client, tmp_path):
    from evals import suite

    result = {"ran_at": "20261118T000000Z", "model": "claude-sonnet-5-5", "runs_per_scenario": 3,
              "passed_runs": 5, "total_runs": 6, "cost_usd": 0.31,
              "scenarios": [{"key": "a", "group": "story", "title": "A", "passed_runs": 3, "runs": 3, "reports": []},
                            {"key": "b", "group": "story", "title": "B", "passed_runs": 2, "runs": 3, "reports": []}]}
    suite.write_latest(result, tmp_path / "latest.json")
    assert client.get("/api/demo").json()["latest_eval"] == {
        "suite": True, "passed_runs": 5, "total_runs": 6, "scenarios": 2, "runs_per_scenario": 3,
        "scenarios_all_passed": 1, "cost_usd": 0.31, "model": "claude-sonnet-5-5", "ran_at": "20261118T000000Z"}


def test_stories_are_listed_with_their_eval_results(client, tmp_path):
    from evals import suite

    suite.write_latest({"ran_at": "20261118T000000Z", "model": "m", "runs_per_scenario": 3, "passed_runs": 3,
                        "total_runs": 3, "cost_usd": 0.1,
                        "scenarios": [{"key": "hero", "group": "story", "title": "Hero", "passed_runs": 3, "runs": 3}]},
                       tmp_path / "latest.json")
    stories = client.get("/api/demo/stories").json()
    assert [s["key"] for s in stories][:2] == ["hero", "race-day"] and len(stories) == 6
    hero = stories[0]
    assert hero["measured"] == {"passed": 3, "runs": 3} and stories[1]["measured"] is None
    assert hero["photo"] == "/static/img/bikes/gravel.jpg"
    assert client.get(hero["photo"]).status_code == 200


def test_starting_a_story_resets_the_shop_and_is_demo_only(client, conn, monkeypatch):
    assert client.post("/api/demo/stories/hero/start").status_code == 403
    monkeypatch.setenv("DEMO_MODE", "1")
    create_sample(conn)
    started = client.post("/api/demo/stories/race-day/start").json()
    assert started["key"] == "race-day" and "Tom Okafor" in started["message"]
    assert conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == 0
    assert client.post("/api/demo/stories/nope/start").status_code == 404


def test_the_about_page_is_served(client):
    page = client.get("/about")
    assert page.status_code == 200 and "Why a bike shop?" in page.text and "Human in the loop" in page.text
    assert "told through a bike shop" in client.get("/").text
