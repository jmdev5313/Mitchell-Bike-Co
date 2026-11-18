"""Limits on the hosted demo's live Agent, so visitors can't run up the API bill.

The Anthropic Console's spend limit on the hosted site's own workspace ($20 a month) is
the hard ceiling. These limits sit under it, so the demo stops politely before Anthropic
refuses calls mid-story:

- AGENT_LIVE=0 switches the live Agent off, anywhere, without a redeploy.
- In sandbox mode (SANDBOXES=1) only, from a small control database next to the
  sandboxes (control.db), which records each Agent turn's estimated cost and each new
  sandbox:
  - AGENT_DAILY_BUDGET_CENTS (default 100) and AGENT_MONTHLY_BUDGET_CENTS (default 1800),
    per UTC day and month, across all visitors;
  - AGENT_TURNS_PER_SANDBOX (default 20) per visitor's shop;
  - with Turnstile keys set, only for a shop that passed the bot check (api/turnstile.py);
  - NEW_SANDBOXES_PER_HOUR (default 5) per network. Networks are told apart by a salted
    hash of the client address (from CLIENT_IP_HEADER, such as Fly-Client-IP, when behind
    a proxy that sets it); the address itself isn't stored.

A turn already running finishes, so a budget can be overshot by up to one turn per open
conversation.
"""

import hashlib
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from typing import Any

from agents.pricing import cost_micros
from api import sandboxes, turnstile

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_turns (
  id INTEGER PRIMARY KEY,
  sandbox TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  model TEXT NOT NULL,
  cost_micros INTEGER NOT NULL,       -- millionths of a dollar, estimated from token usage
  at TEXT NOT NULL                    -- UTC, ISO 8601
);
CREATE INDEX IF NOT EXISTS agent_turns_at ON agent_turns (at);
CREATE INDEX IF NOT EXISTS agent_turns_sandbox ON agent_turns (sandbox);
CREATE TABLE IF NOT EXISTS sandbox_starts (
  sandbox TEXT PRIMARY KEY,
  network TEXT NOT NULL,              -- salted hash of the client address
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sandbox_starts_network ON sandbox_starts (network, at);
CREATE TABLE IF NOT EXISTS sandbox_checks (
  sandbox TEXT PRIMARY KEY,           -- passed the Turnstile bot check (api/turnstile.py)
  at TEXT NOT NULL
);
"""

KEEP_TURNS = timedelta(days=40)
_SALT = os.environ.get("CLIENT_HASH_SALT") or secrets.token_hex(16)  # a fresh salt each start is fine


def _setting(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def live() -> bool:
    return os.environ.get("AGENT_LIVE", "").strip().lower() not in ("0", "false", "no", "off")


def _now() -> datetime:
    return datetime.now(UTC)


def connect() -> sqlite3.Connection:
    folder = sandboxes.directory()
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / "control.db", timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def spent_micros(conn: sqlite3.Connection, since: datetime) -> int:
    return conn.execute("SELECT COALESCE(SUM(cost_micros), 0) FROM agent_turns WHERE at >= ?",
                        (since.isoformat(),)).fetchone()[0]


def agent_refusal(sandbox: str | None, *, check: bool = True) -> str | None:
    """Why the live Agent can't take a turn right now, or None if it can.
    `check=False` leaves out the bot check (the front door asks before anyone has a shop)."""
    if not live():
        return "The live Agent is switched off for now."
    if not sandboxes.enabled():
        return None
    now = _now()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with closing(connect()) as conn:
        if check and turnstile.enabled() and not checked(conn, sandbox):
            return "Start a story from the front door to use the live Agent."
        if spent_micros(conn, day.replace(day=1)) >= _setting("AGENT_MONTHLY_BUDGET_CENTS", 1800) * 10_000:
            return "The live Agent has used this month's budget for the demo. It's back next month."
        if spent_micros(conn, day) >= _setting("AGENT_DAILY_BUDGET_CENTS", 100) * 10_000:
            return "The live Agent has used today's budget for the demo. It's back tomorrow."
        limit = _setting("AGENT_TURNS_PER_SANDBOX", 20)
        used = conn.execute("SELECT COUNT(*) FROM agent_turns WHERE sandbox = ?", (sandbox or "",)).fetchone()[0]
        if used >= limit:
            return f"This demo has used its {limit} Agent turns. Thanks for trying it!"
    return None


def record_turn(sandbox: str | None, conversation_id: str, model: str, usage: dict[str, int]) -> int:
    """Add a turn's estimated cost to the ledger (sandbox mode only). Returns the cost in micro-dollars."""
    cost = cost_micros(model, usage)
    if not sandboxes.enabled():
        return cost
    now = _now()
    with closing(connect()) as conn, conn:
        conn.execute("INSERT INTO agent_turns (sandbox, conversation_id, model, cost_micros, at) VALUES (?, ?, ?, ?, ?)",
                     (sandbox or "", conversation_id, model, cost, now.isoformat()))
        conn.execute("DELETE FROM agent_turns WHERE at < ?", ((now - KEEP_TURNS).isoformat(),))
    return cost


def network(scope: dict[str, Any]) -> str:
    """A salted hash standing for the visitor's network."""
    header = os.environ.get("CLIENT_IP_HEADER", "").strip().lower().encode()
    address = ""
    if header:
        address = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == header), "")
        address = address.split(",")[0].strip()
    if not address and scope.get("client"):
        address = scope["client"][0]
    return hashlib.sha256(f"{_SALT}:{address}".encode()).hexdigest()[:32]


def sandbox_refusal(net: str) -> str | None:
    """Why this network can't start another shop right now, or None if it can."""
    limit = _setting("NEW_SANDBOXES_PER_HOUR", 5)
    since = (_now() - timedelta(hours=1)).isoformat()
    with closing(connect()) as conn:
        started = conn.execute("SELECT COUNT(*) FROM sandbox_starts WHERE network = ? AND at >= ?",
                               (net, since)).fetchone()[0]
    if started >= limit:
        return "Too many new demos have been started from your network in the last hour. Try again later."
    return None


def record_sandbox(key: str, net: str) -> None:
    now = _now()
    with closing(connect()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO sandbox_starts (sandbox, network, at) VALUES (?, ?, ?)",
                     (key, net, now.isoformat()))
        conn.execute("DELETE FROM sandbox_starts WHERE at < ?", ((now - timedelta(days=1)).isoformat(),))


def checked(conn: sqlite3.Connection, sandbox: str | None) -> bool:
    return conn.execute("SELECT 1 FROM sandbox_checks WHERE sandbox = ?", (sandbox or "",)).fetchone() is not None


def is_checked(sandbox: str | None) -> bool:
    with closing(connect()) as conn:
        return checked(conn, sandbox)


def record_check(sandbox: str) -> None:
    with closing(connect()) as conn, conn:
        conn.execute("INSERT OR REPLACE INTO sandbox_checks (sandbox, at) VALUES (?, ?)", (sandbox, _now().isoformat()))


def status(sandbox: str | None) -> dict[str, Any]:
    """Whether the live Agent can take a turn for this visitor, for the front door."""
    reason = agent_refusal(sandbox, check=False)
    return {"live": reason is None, "reason": reason}
