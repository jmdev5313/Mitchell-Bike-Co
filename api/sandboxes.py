"""A sandbox shop for each visitor of the hosted demo.

With SANDBOXES=1, every visitor gets their own copy of the seeded shop: a SQLite file
in SANDBOX_DIR, chosen by a cookie. Starting a story or resetting then clears only that
visitor's shop, and nobody can see or disturb anyone else's. Without it, everything
uses the one database in DB_PATH, as on a laptop.

The cookie holds a secret; the sandbox's file is named by a hash of it (its key), so
the key can appear in a Customer's link without giving away the workshop. A Customer
link in sandbox mode is "<key>.<token>": the key picks the sandbox, and the token is
the shop's ordinary link token inside it. Sandboxes that haven't been used for
SANDBOX_TTL_HOURS (default 24) are deleted.

Which requests get a sandbox (only /api/ touches the database; pages and static files don't):
- /api/customer/<key>.<token>/...: the link's sandbox, or 404 if there isn't one.
- GET /api/health, /api/demo and /api/demo/stories: the visitor's sandbox if they have
  one, else none. Looking at the front door doesn't make a sandbox.
- everything else: the visitor's sandbox, made fresh if they have none or theirs expired.
"""

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextvars import ContextVar
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any

from shop import db, seed

COOKIE = "mbc_sandbox"
SECRET = re.compile(r"[A-Za-z0-9_-]{32}")  # secrets.token_urlsafe(24)
KEY = re.compile(r"[0-9a-f]{32}")
SEPARATOR = "."  # never in a link token, which is URL-safe base64
TEMPLATE = "template.db"
NO_SANDBOX_NEEDED = {"/api/health", "/api/demo", "/api/demo/stories"}  # GET only

_current: ContextVar[str | None] = ContextVar("sandbox_key", default=None)


def enabled() -> bool:
    return os.environ.get("SANDBOXES", "").strip().lower() in ("1", "true", "yes", "on")


def directory() -> Path:
    return Path(os.environ.get("SANDBOX_DIR", "data/sandboxes"))


def ttl_seconds() -> float:
    return float(os.environ.get("SANDBOX_TTL_HOURS", "24")) * 3600


def current_key() -> str | None:
    """The sandbox this request is using, or None."""
    return _current.get()


def key_for(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()[:32]


def path_for(key: str) -> Path:
    return directory() / f"{key}.db"


def build_template() -> Path:
    """Build the freshly seeded shop that every new sandbox copies. Rebuilt at each start, so seed changes apply."""
    folder = directory()
    folder.mkdir(parents=True, exist_ok=True)
    building = folder / f"{TEMPLATE}.building"
    building.unlink(missing_ok=True)
    conn = db.connect(db.init(building))
    try:
        seed.load(conn)
    finally:
        conn.close()
    target = folder / TEMPLATE
    os.replace(building, target)
    return target


def create() -> tuple[str, str]:
    """A new sandbox copied from the template. Returns its secret (for the cookie) and its key."""
    sweep()
    secret = secrets.token_urlsafe(24)
    key = key_for(secret)
    template = sqlite3.connect(directory() / TEMPLATE)
    copy = sqlite3.connect(path_for(key))
    try:
        template.backup(copy)
    finally:
        copy.close()
        template.close()
    return secret, key


def sweep(now: float | None = None) -> list[str]:
    """Delete sandboxes nobody has used within the time limit. Returns their keys."""
    now = time.time() if now is None else now
    gone = []
    for path in directory().glob("*.db"):
        if KEY.fullmatch(path.stem) and now - path.stat().st_mtime > ttl_seconds():
            for leftover in (path, path.with_name(path.name + "-journal")):
                leftover.unlink(missing_ok=True)
            gone.append(path.stem)
    return gone


def public_token(token: str) -> str:
    """A Customer link token as it leaves the API: in sandbox mode, prefixed with its sandbox."""
    key = current_key()
    return f"{key}{SEPARATOR}{token}" if enabled() and key else token


def bare_token(token: str) -> str:
    """The shop's own link token inside a public one (the reverse of `public_token`)."""
    if not enabled():
        return token
    return token.split(SEPARATOR, 1)[1] if SEPARATOR in token else ""


def _link_key(path: str) -> str | None:
    """The sandbox named by a Customer route's token, if it's well formed and still exists."""
    parts = path.split("/")  # "", "api", "customer", "<key>.<token>", ...
    token = parts[3] if len(parts) > 3 else ""
    key = token.split(SEPARATOR, 1)[0] if SEPARATOR in token else ""
    return key if KEY.fullmatch(key) and path_for(key).exists() else None


def _cookie_key(headers: list[tuple[bytes, bytes]]) -> str | None:
    """The visitor's sandbox from their cookie, if it's well formed and still exists."""
    raw = b"; ".join(value for name, value in headers if name == b"cookie").decode("latin-1")
    try:
        morsel = SimpleCookie(raw).get(COOKIE)
    except CookieError:
        return None
    if morsel is None or not SECRET.fullmatch(morsel.value):
        return None
    key = key_for(morsel.value)
    return key if path_for(key).exists() else None


def _set_cookie(secret: str) -> bytes:
    secure = os.environ.get("PUBLIC_BASE_URL", "").startswith("https://")
    return (f"{COOKIE}={secret}; Path=/; Max-Age={int(ttl_seconds())}; HttpOnly; SameSite=Lax"
            + ("; Secure" if secure else "")).encode()


class SandboxMiddleware:
    """Picks each API request's sandbox (see the module docstring) and makes it the request's database."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not enabled() or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        new_cookie = None
        if path.startswith("/api/customer/"):
            key = _link_key(path)
            if key is None:
                await _not_found(send)
                return
        else:
            key = _cookie_key(scope.get("headers", []))
            if key is None and not (scope["method"] == "GET" and path in NO_SANDBOX_NEEDED):
                secret, key = create()
                new_cookie = _set_cookie(secret)

        if key is None:
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: dict) -> None:
            if new_cookie and message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"set-cookie", new_cookie)]}
            await send(message)

        sandbox = path_for(key)
        os.utime(sandbox)  # used now: keeps it from being swept
        current = _current.set(key)
        try:
            with db.using(sandbox):
                await self.app(scope, receive, send_with_cookie)
        finally:
            _current.reset(current)


async def _not_found(send: Any) -> None:
    body = json.dumps({"detail": "this link is not valid"}).encode()
    await send({"type": "http.response.start", "status": 404,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
