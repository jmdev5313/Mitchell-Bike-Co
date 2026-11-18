"""The demo's repair stories: each is an eval scenario, and the seed backs up its twist."""

from datetime import date

from demo.stories import BY_KEY, STORIES, race_day
from evals import suite
from shop.compat import check_fit
from shop.stock import stock_status


def bike(conn, email):
    return conn.execute(
        "SELECT cb.id FROM customer_bikes cb JOIN customers c ON c.id = cb.customer_id WHERE c.email = ?", (email,)
    ).fetchone()[0]


def test_every_story_is_an_eval_scenario_with_the_same_group():
    scenarios = {s.key: s for s in suite.discover()}
    assert len(STORIES) == 6
    for story in STORIES:
        assert story.key in scenarios, story.key
        assert scenarios[story.key].group == story.group


def test_the_road_story_names_a_race_three_days_out():
    assert race_day(date(2026, 11, 17)) == "Friday, November 20"
    assert "Friday, November 20" in BY_KEY["race-day"].mechanic_message(date(2026, 11, 17))


def test_the_seed_backs_up_each_twist(conn):
    tom, frank, ruth = (bike(conn, BY_KEY[k].email) for k in ("race-day", "modern-gears", "roadster-tires"))
    assert check_fit(conn, "AD-C12-36R", tom).fits and not stock_status(conn, "AD-C12-36R").in_stock
    assert not check_fit(conn, "AD-C12-44W", tom).fits  # a road derailleur can't shift a 44t cog
    assert not any(check_fit(conn, sku, frank).fits for sku in ("AD-C12-36R", "AD-C12-44W", "AD-CH12"))
    assert check_fit(conn, "FS-TR635-38", ruth).fits and not check_fit(conn, "FS-TR700-40", ruth).fits
    marcus, dana = bike(conn, BY_KEY["brake-fade"].email), bike(conn, BY_KEY["speed-limit"].email)
    assert check_fit(conn, "FS-RT160-CL", marcus).fits
    assert check_fit(conn, "AD-CH10", dana).fits and check_fit(conn, "AD-C10-32", dana).fits
