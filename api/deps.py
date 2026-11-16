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
    conn = db.connect()
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
