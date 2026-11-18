"""The hosted demo's sandboxes: each visitor gets their own shop, chosen by a cookie."""

import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from api import sandboxes
from api.app import app
from shop import db
from tests.test_agent_runtime import FakeModel, agent, message, text, tool_use

STAFF = {"Authorization": "Bearer pc"}


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def opened():
    """The database each Agent conversation was opened in."""
    return []


@pytest.fixture
def client(tmp_path, monkeypatch, model, opened):
    monkeypatch.setenv("SANDBOXES", "1")
    monkeypatch.setenv("SANDBOX_DIR", str(tmp_path / "sandboxes"))
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("STAFF_PASSCODE", "pc")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shared.db"))
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    def factory(conversation_id):
        opened.append(db.db_path())
        return agent(model, conversation_id)

    app.state.agent_factory = factory
    with TestClient(app) as c:
        yield c
    del app.state.agent_factory
    assert not (tmp_path / "shared.db").exists(), "a request fell back to the shared database"


def new_visitor(client) -> str:
    """Arrive as someone new and start a shop. Returns their sandbox key."""
    client.cookies.clear()
    response = client.post("/api/demo/reset")
    assert response.status_code == 200 and sandboxes.COOKIE in response.headers["set-cookie"]
    return sandboxes.key_for(client.cookies[sandboxes.COOKIE])


def set_cookie(client, secret: str) -> None:
    client.cookies.clear()
    client.cookies.set(sandboxes.COOKIE, secret, domain="testserver.local")  # where the server's cookie lands


def be(client, key_secret: dict, key: str) -> None:
    set_cookie(client, key_secret[key])


def visitors(client, n: int) -> dict[str, str]:
    """n visitors, by key, with the cookie secret for each."""
    out = {}
    for _ in range(n):
        key = new_visitor(client)
        out[key] = client.cookies[sandboxes.COOKIE]
    return out


def sandbox_files(tmp_path) -> set[str]:
    return {p.name for p in (tmp_path / "sandboxes").glob("*.db")} - {"control.db"}  # the guards' ledger


def test_looking_at_the_front_door_makes_no_sandbox(client, tmp_path):
    info = client.get("/api/demo")
    assert info.status_code == 200 and "set-cookie" not in info.headers
    body = info.json()
    assert body["staff_passcode"] == "pc" and body["customer_token"] is None and body["story"]["step"] == 1
    assert client.get("/api/demo/stories").status_code == 200
    assert sandbox_files(tmp_path) == {"template.db"}


def test_each_visitor_gets_their_own_shop(client, tmp_path):
    secrets = visitors(client, 2)
    a, b = secrets
    be(client, secrets, a)
    token_a = client.post("/api/demo/sample").json()["customer_token"]
    assert len(client.get("/api/work-orders", headers=STAFF).json()) == 1

    be(client, secrets, b)
    assert client.get("/api/work-orders", headers=STAFF).json() == []
    assert client.post("/api/demo/reset").status_code == 200  # B's reset...

    be(client, secrets, a)
    assert len(client.get("/api/work-orders", headers=STAFF).json()) == 1  # ...leaves A's shop alone
    assert client.get("/api/demo").json()["customer_token"] == token_a
    assert sandbox_files(tmp_path) == {"template.db", f"{a}.db", f"{b}.db"}


def test_a_story_start_resets_only_the_visitors_shop(client):
    secrets = visitors(client, 2)
    a, b = secrets
    be(client, secrets, a)
    client.post("/api/demo/sample")
    be(client, secrets, b)
    assert client.post("/api/demo/stories/hero/start").status_code == 200
    be(client, secrets, a)
    assert len(client.get("/api/work-orders", headers=STAFF).json()) == 1


def test_a_customer_link_carries_its_sandbox(client):
    secrets = visitors(client, 2)
    a, b = secrets
    be(client, secrets, a)
    sample = client.post("/api/demo/sample").json()
    token = sample["customer_token"]
    assert token.startswith(f"{a}.")
    detail = client.get(f"/api/work-orders/{sample['work_order_id']}", headers=STAFF).json()
    assert detail["customer_link_token"] == token

    client.cookies.clear()  # the Customer's own phone: no workshop cookie
    view = client.get(f"/api/customer/{token}")
    assert view.status_code == 200 and view.json()["customer"] == "Emma Clark"
    assert "set-cookie" not in view.headers

    bare = token.split(".", 1)[1]
    for wrong in (f"{b}.{bare}", bare, f"{'0' * 32}.{bare}", f"../{bare}", f"{a}."):
        assert client.get(f"/api/customer/{wrong}").status_code == 404, wrong


def test_unused_sandboxes_are_swept_and_a_returning_visitor_starts_fresh(client, tmp_path):
    secrets = visitors(client, 1)
    (a,) = secrets
    be(client, secrets, a)
    client.post("/api/demo/sample")
    old = time.time() - sandboxes.ttl_seconds() - 60
    os.utime(sandboxes.path_for(a), (old, old))

    new_visitor(client)  # making a sandbox sweeps the stale ones
    assert f"{a}.db" not in sandbox_files(tmp_path) and "template.db" in sandbox_files(tmp_path)

    be(client, secrets, a)
    response = client.get("/api/work-orders", headers=STAFF)
    assert response.json() == [] and sandboxes.COOKIE in response.headers["set-cookie"]
    assert sandboxes.key_for(client.cookies[sandboxes.COOKIE]) != a


def test_a_cookie_the_shop_never_made_gets_a_new_sandbox(client):
    set_cookie(client, "x" * 32)
    response = client.get("/api/work-orders", headers=STAFF)
    assert response.status_code == 200 and sandboxes.COOKIE in response.headers["set-cookie"]


def test_the_agent_works_in_the_visitors_sandbox(client, model, opened):
    secrets = visitors(client, 2)
    a, b = secrets
    be(client, secrets, a)
    conversation = client.post("/api/conversations", headers=STAFF).json()["conversation_id"]
    assert opened == [sandboxes.path_for(a)]
    model.responses += [
        message(tool_use("t1", "find_customer", query="clark"), stop_reason="tool_use"),
        message(text("Found Emma.")),
    ]
    turn = client.post(f"/api/conversations/{conversation}/messages", headers=STAFF, data={"text": "Emma's bike"})
    assert "event: reply" in turn.text

    def audit_rows(key: str) -> int:
        with sqlite3.connect(sandboxes.path_for(key)) as conn:
            return conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]

    assert audit_rows(a) == 1 and audit_rows(b) == 0  # the tool call landed in A's shop

    be(client, secrets, b)
    assert client.get(f"/api/conversations/{conversation}", headers=STAFF).status_code == 404
    assert client.post(f"/api/conversations/{conversation}/messages", headers=STAFF,
                       data={"text": "hi"}).status_code == 404
    client.post("/api/demo/reset")
    assert len(app.state.agent_pool) == 1  # B's reset doesn't close A's conversation

    be(client, secrets, a)
    client.post("/api/demo/reset")
    assert len(app.state.agent_pool) == 0


def test_without_sandbox_mode_tokens_are_unchanged(monkeypatch):
    monkeypatch.delenv("SANDBOXES", raising=False)
    assert sandboxes.public_token("abc") == "abc" and sandboxes.bare_token("abc") == "abc"


def test_sweep_only_deletes_stale_sandboxes(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_DIR", str(tmp_path))
    stale, fresh = tmp_path / f"{'a' * 32}.db", tmp_path / f"{'b' * 32}.db"
    other = tmp_path / "template.db"
    for path in (stale, fresh, other):
        path.write_bytes(b"")
    old = time.time() - sandboxes.ttl_seconds() - 1
    for path in (stale, other):
        os.utime(path, (old, old))
    assert sandboxes.sweep() == ["a" * 32]
    assert not stale.exists() and fresh.exists() and other.exists()
