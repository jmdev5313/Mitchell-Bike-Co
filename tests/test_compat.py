import pytest

from shop.compat import check_fit, fit_report
from shop.errors import NotFound
from tests.conftest import HERO, LENA, STOCK_ARC, TEMPO


def test_catalog_cassette_does_not_fit_upgraded_wheels(conn, bike_of):
    result = check_fit(conn, "AD-C11-28R", bike_of(HERO))
    assert not result.fits
    assert result.problems == [
        "freehub: needs Shimano HG 11-speed road, bike has Shimano HG 8-10 speed"
    ]


def test_same_cassette_fits_the_stock_bike(conn, bike_of):
    result = check_fit(conn, "AD-C11-28R", bike_of(STOCK_ARC))
    assert result.fits and not result.notes


def test_wide_range_cassette_fits_upgraded_wheels(conn, bike_of):
    result = check_fit(conn, "AD-C11-34W", bike_of(HERO))
    assert result.fits and not result.notes


def test_exception_fits_with_a_note(conn, bike_of):
    result = check_fit(conn, "AD-C11-34W", bike_of(STOCK_ARC))
    assert result.fits
    assert result.notes == [
        "freehub: fits Shimano HG 11-speed road, needs a 1.85 mm spacer behind the cassette"
    ]


def test_xd_cassette_on_xdr_needs_spacer(conn, bike_of):
    # The freehub takes the XD cassette with a spacer, but the road derailleur can't shift its 44t cog.
    result = check_fit(conn, "AD-C12-44W", bike_of(TEMPO))
    assert any("1.85 mm spacer" in n for n in result.notes)
    assert not result.fits and len(result.problems) == 1 and "rear_derailleur" in result.problems[0].replace(" ", "_")


def test_exceptions_only_go_one_way(conn, bike_of):
    # An XDR cassette does not fit an XD freehub.
    assert not check_fit(conn, "AD-C12-36R", bike_of(LENA)).fits
    # A Centerlock rotor does not fit a 6-bolt hub.
    assert not check_fit(conn, "FS-RT160-CL", bike_of(LENA)).fits
    # A 6-bolt rotor fits a Centerlock hub with an adapter.
    assert "adapter" in check_fit(conn, "FS-RT160-6B", bike_of(HERO)).notes[0]


def test_every_mismatch_is_reported(conn, bike_of):
    result = check_fit(conn, "AD-C10-32", bike_of(TEMPO))
    assert [p.split(":")[0] for p in result.problems] == ["drivetrain_speed", "freehub"]


def test_fit_report_for_the_hero_bike(conn, bike_of):
    report = fit_report(conn, bike_of(HERO), "cassette")
    assert [r.sku for r in report if r.fits] == ["AD-C11-34W"]
    assert len(report) == 6


def test_unknown_part_or_bike(conn, bike_of):
    with pytest.raises(NotFound):
        check_fit(conn, "NOPE", bike_of(HERO))
    with pytest.raises(NotFound):
        check_fit(conn, "AD-C11-28R", 9999)
