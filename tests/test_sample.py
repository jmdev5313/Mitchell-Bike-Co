"""make sample: a quoted hero work order and a working Customer token."""

from fastapi.testclient import TestClient

from api.app import app
from demo import sample


def test_sample_prints_a_working_customer_token(conn, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    sample.main()
    out = capsys.readouterr().out
    token = next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("Customer token: "))
    view = TestClient(app).get(f"/api/customer/{token}").json()
    assert view["status"] == "quoted" and view["quote"]["total_cents"] == 16998
    assert view["open_quote_message_id"] == 1


def test_sample_done_is_ready_to_pay(conn, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "shop.db"))
    sample.main(["--done"])
    out = capsys.readouterr().out
    token = next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("Customer token: "))
    view = TestClient(app).get(f"/api/customer/{token}").json()
    assert view["status"] == "done" and view["can_pay"] is True
