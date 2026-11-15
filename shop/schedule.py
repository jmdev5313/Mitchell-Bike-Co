"""Ready dates the shop can stand behind.

The agent may only promise the customer a date this rule backs up: the parts
arrive after the supplier's lead time, and the repair takes one more day.
Calendar days; the shop is open every day.
"""

from datetime import date, timedelta

from shop.errors import RuleViolation

REPAIR_DAYS = 1


def ready_date(order_date: date, lead_time_days: int = 0) -> date:
    """Earliest ready date for a job ordered on `order_date`.

    `lead_time_days` is 0 when every part is in stock, otherwise the slowest
    supplier's lead time.
    """
    if lead_time_days < 0:
        raise RuleViolation("lead time cannot be negative")
    return order_date + timedelta(days=lead_time_days + REPAIR_DAYS)
