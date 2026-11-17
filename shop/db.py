"""Database access for the shop. No AI code belongs in this package."""

import os
import sqlite3
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    return Path(os.environ.get("DB_PATH", "data/shop.db"))


def connect(path: Path | None = None, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """A connection with rows as dicts and foreign keys on.

    `check_same_thread=False` is for a connection used by one request at a time but possibly
    across threads (FastAPI runs a request's dependencies and endpoint in a thread pool).
    """
    conn = sqlite3.connect(path or db_path(), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(path: Path | None = None) -> Path:
    """Create a fresh database from schema.sql. Refuses to overwrite one."""
    target = path or db_path()
    if target.exists():
        raise SystemExit(f"{target} already exists. Delete it first to rebuild.")
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(target)
    with conn:
        conn.executescript(SCHEMA_PATH.read_text())
    conn.close()
    return target


if __name__ == "__main__":
    if sys.argv[1:] == ["init"]:
        print(f"Created {init()}")
    else:
        raise SystemExit("usage: python -m shop.db init")
