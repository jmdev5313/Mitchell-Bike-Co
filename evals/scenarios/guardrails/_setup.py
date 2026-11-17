"""Shared starting state: Emma's quote has been sent and is waiting for her answer."""

from datetime import date

from demo.sample import create_sample


def quote_waiting(conn, today: date) -> None:
    create_sample(conn, source="the eval setup")  # work order 1, quote locked at $169.98 and sent, order planned
