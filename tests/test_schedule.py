from datetime import date

import pytest

from shop.errors import RuleViolation
from shop.schedule import ready_date

MONDAY = date(2026, 11, 16)


@pytest.mark.parametrize("lead_time, expected", [
    (0, date(2026, 11, 17)),   # parts in stock: repair the next day
    (2, date(2026, 11, 19)),   # Velo: Wednesday arrival, Thursday ready
    (5, date(2026, 11, 22)),   # Northgate: misses a Friday promise
])
def test_ready_date(lead_time, expected):
    assert ready_date(MONDAY, lead_time) == expected


def test_negative_lead_time_is_refused():
    with pytest.raises(RuleViolation):
        ready_date(MONDAY, -1)
