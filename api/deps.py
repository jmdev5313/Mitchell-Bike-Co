"""What every endpoint shares: a database connection and the staff passcode check."""

import os
import secrets
import sqlite3
from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shop import db

bearer = HTTPBearer(auto_error=False, description="The staff passcode from STAFF_PASSCODE in .env")


def get_db() -> Iterator[sqlite3.Connection]:
    # One connection per request. FastAPI may open it in one worker thread and run the
    # endpoint in another, so it can't be pinned to its thread; it is never shared.
    conn = db.connect(check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def require_staff(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    """Staff endpoints need `Authorization: Bearer <STAFF_PASSCODE>`. Fails closed if none is set."""
    expected = os.environ.get("STAFF_PASSCODE", "")
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "STAFF_PASSCODE is not set on the server")
    given = credentials.credentials if credentials else ""
    if not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "staff passcode required", headers={"WWW-Authenticate": "Bearer"}
        )


def get_stripe():
    """A Stripe client for the test-mode key in STRIPE_SECRET_KEY. Live keys are refused."""
    import stripe

    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "STRIPE_SECRET_KEY is not set on the server")
    if not key.startswith(("sk_test_", "rk_test_")):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "only Stripe test-mode keys are allowed")
    return stripe.StripeClient(key)


def public_base_url() -> str:
    """Where this API is reached from a browser, for Stripe's return links."""
    return os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
