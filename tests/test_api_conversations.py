"""The Mechanic's chat with the Agent over the API, with the scripted fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from agents import conversations
from api.app import app
from tests.test_agent_runtime import FakeModel, agent, message, progress, text, tool_use
from tests.test_api import PASSCODE, STAFF


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def client(conn, tmp_path, monkeypatch, model):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    monkeypatch.setenv("STAFF_PASSCODE", PASSCODE)
    app.state.agent_factory = lambda conversation_id: agent(model, conversation_id)
    with TestClient(app) as c:
        yield c
    del app.state.agent_factory


def events(response) -> list[tuple[str, dict]]:
    out = []
    for chunk in response.text.strip().split("\n\n"):
        kind, data = chunk.split("\n", 1)
        out.append((kind.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_a_turn_streams_progress_tools_and_the_reply(client, model):
    model.responses += [
        message(progress("Finding Emma's bike."), tool_use("t1", "find_customer", query="clark"),
                stop_reason="tool_use"),
        message(tool_use("t2", "check_fit", sku="NOPE", customer_bike_id=1), stop_reason="tool_use"),
        message(text("Emma's Arc has upgraded wheels.")),
    ]
    conversation_id = client.post("/api/conversations", headers=STAFF).json()["conversation_id"]
    response = client.post(f"/api/conversations/{conversation_id}/messages", headers=STAFF,
                           data={"text": "Whose bike is this?"})
    assert response.headers["content-type"].startswith("text/event-stream")
    got = events(response)
    assert [kind for kind, _ in got] == ["progress", "tool_call", "tool_call", "reply"]
    assert got[0][1] == {"text": "Finding Emma's bike."}
    assert got[1][1] == {"name": "find_customer", "server": "catalog", "is_error": False,
                         "summary": "Emma Clark (1 bike)", "result": None}
    assert got[2][1]["is_error"] and "no part with SKU NOPE" in got[2][1]["result"]
    assert got[2][1]["summary"] == "Refused: no part with SKU NOPE"
    assert got[3][1]["text"] == "Emma's Arc has upgraded wheels." and got[3][1]["stop_reason"] == "end_turn"

    view = client.get(f"/api/conversations/{conversation_id}", headers=STAFF).json()
    assert [e["role"] for e in view["entries"]] == ["mechanic", "agent"]
    assert view["entries"][1]["tools"] == [
        {"name": "find_customer", "server": "catalog", "is_error": False, "summary": "Emma Clark (1 bike)"},
        {"name": "check_fit", "server": "catalog", "is_error": True, "summary": "Refused: no part with SKU NOPE"},
    ]
    assert view["entries"][1]["progress"] == ["Finding Emma's bike."]
    assert view["usage"]["input_tokens"] == 300


def test_conversations_stay_open_and_resume(client, model, conn):
    model.responses += [message(text("First.")), message(text("Second."))]
    conversation_id = client.post("/api/conversations", headers=STAFF).json()["conversation_id"]
    for words in ("one", "two"):
        client.post(f"/api/conversations/{conversation_id}/messages", headers=STAFF, data={"text": words})
    assert len(app.state.agent_pool) == 1  # reused, not reopened
    assert len(model.requests[1]["messages"]) == 3  # the second turn saw the first
    listed = client.get("/api/conversations", headers=STAFF).json()
    assert listed[0]["id"] == conversation_id and listed[0]["preview"] == "one" and listed[0]["turns"] == 2


def test_the_work_order_link_comes_back_with_the_reply(client, model):
    model.responses += [
        message(tool_use("t1", "open_work_order", customer_bike_id=1, complaint="Gears skip"), stop_reason="tool_use"),
        message(text("Opened.")),
    ]
    conversation_id = client.post("/api/conversations", headers=STAFF).json()["conversation_id"]
    got = events(client.post(f"/api/conversations/{conversation_id}/messages", headers=STAFF,
                             data={"text": "Open a work order"}))
    assert got[-1][1]["work_order_id"] == 1


def test_photos_reach_the_model(client, model):
    model.responses += [message(text("I see it."))]
    conversation_id = client.post("/api/conversations", headers=STAFF).json()["conversation_id"]
    client.post(f"/api/conversations/{conversation_id}/messages", headers=STAFF,
                data={"text": "Look"}, files=[("photos", ("c.png", b"\x89PNG\r\n\x1a\n", "image/png"))])
    first = model.requests[0]["messages"][0]["content"]
    assert first[0]["type"] == "image" and first[1]["text"] == "Look"


def test_bad_requests(client):
    assert client.post("/api/conversations").status_code == 401
    assert client.get("/api/conversations/nope", headers=STAFF).status_code == 404
    assert client.post("/api/conversations/nope/messages", headers=STAFF, data={"text": "hi"}).status_code == 404
    conversation_id = client.post("/api/conversations", headers=STAFF).json()["conversation_id"]
    bad = client.post(f"/api/conversations/{conversation_id}/messages", headers=STAFF,
                      data={"text": "x"}, files=[("photos", ("a.pdf", b"%PDF", "application/pdf"))])
    assert bad.status_code == 422


def test_a_failed_turn_reports_an_error_event(client, model):
    model.responses += []  # nothing scripted: the fake model raises
    conversation_id = client.post("/api/conversations", headers=STAFF).json()["conversation_id"]
    got = events(client.post(f"/api/conversations/{conversation_id}/messages", headers=STAFF, data={"text": "hi"}))
    assert got[-1][0] == "error" and "the turn failed" in got[-1][1]["detail"]


def test_a_conversation_can_start_on_a_work_order(client, conn):
    from demo.sample import create_sample

    order, _, _ = create_sample(conn)
    conversation_id = client.post("/api/conversations", headers=STAFF, json={"work_order_id": order}).json()["conversation_id"]
    assert client.get(f"/api/conversations/{conversation_id}", headers=STAFF).json()["work_order_id"] == order
    assert client.get(f"/api/work-orders/{order}", headers=STAFF).json()["conversation_ids"] == [conversation_id]
    assert client.post("/api/conversations", headers=STAFF, json={"work_order_id": 999}).status_code == 404


def test_photos_come_back_and_the_hero_photo_is_labelled(client, conn, tmp_path, monkeypatch):
    import base64

    from api import conversations as api_conversations

    hero = tmp_path / "hero.jpg"
    hero.write_bytes(b"\xff\xd8 illustrative cassette")
    monkeypatch.setattr(api_conversations, "HERO_PHOTO", hero)
    other = b"\xff\xd8 a real photo"
    convo = conversations.create(conn, "anthropic", "model")
    block = lambda data: {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                      "data": base64.standard_b64encode(data).decode()}}
    conversations.append(conn, convo.id, "user", [block(hero.read_bytes()), block(other), {"type": "text", "text": "Look"}])
    entry = client.get(f"/api/conversations/{convo.id}", headers=STAFF).json()["entries"][0]
    assert entry["photos"] == 2
    assert [i["illustrative"] for i in entry["images"]] == [True, False]
    assert entry["images"][0]["src"].startswith("data:image/jpeg;base64,")
    hero.unlink()  # no hero photo in the shop: nothing is labelled
    entry = client.get(f"/api/conversations/{convo.id}", headers=STAFF).json()["entries"][0]
    assert [i["illustrative"] for i in entry["images"]] == [False, False]
