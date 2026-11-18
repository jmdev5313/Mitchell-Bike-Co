"""The shop's calendar: today, unless the shop's settings pin it to another day.

A recorded run of the Agent replays words written on the day it was recorded ("ready
Thursday, Nov 19"), so a shop replaying it pins its calendar to that day (the `today`
setting) and every promised date lines up. Timestamps (when something happened) stay real.
"""

import sqlite3
from datetime import date

SETTING = "today"


def today(conn: sqlite3.Connection) -> date:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTING,)).fetchone()
    return date.fromisoformat(row[0]) if row else date.today()


def pin(conn: sqlite3.Connection, day: date) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (SETTING, day.isoformat()))
