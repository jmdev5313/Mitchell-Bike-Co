import pytest

from shop import db, seed
from shop import work_orders as wo


@pytest.fixture
def conn(tmp_path):
    """A fresh database loaded with the real seed data."""
    connection = db.connect(db.init(tmp_path / "shop.db"))
    seed.load(connection)
    yield connection
    connection.close()


@pytest.fixture
def bike_of(conn):
    """Look up a customer's bike id by email."""
    def lookup(email: str) -> int:
        row = conn.execute(
            """SELECT cb.id FROM customer_bikes cb JOIN customers c ON c.id = cb.customer_id
               WHERE c.email = ?""",
            (email,),
        ).fetchone()
        assert row, f"no bike for {email}"
        return row["id"]
    return lookup


HERO = "emma.clark@example.com"        # Arc with upgraded wheels (HG 8-10 freehub)
STOCK_ARC = "grace.lee@example.com"     # same model, stock wheels (HG 11-speed road)
TEMPO = "tom.okafor@example.com"        # SRAM XDR, 12-speed
LENA = "lena.fischer@example.com"       # bought elsewhere: SRAM XD, 6-bolt, 650b

DRIVETRAIN = "Drivetrain replacement (chain and cassette)"
HERO_QUOTE = 7499 + 3499 + 6000  # cassette + chain + labor = $169.98


@pytest.fixture
def diagnosed(conn, bike_of):
    """The hero work order, diagnosed and ready for parts."""
    work_order = wo.open_work_order(conn, bike_of(HERO), "Gears skip when I pedal hard")
    wo.record_diagnosis(conn, work_order, "Worn chain (0.75%) and cassette")
    return work_order


@pytest.fixture
def quoted(conn, diagnosed):
    wo.add_part(conn, diagnosed, "AD-C11-34W")
    wo.add_part(conn, diagnosed, "AD-CH11")
    wo.add_service(conn, diagnosed, DRIVETRAIN)
    wo.send_quote(conn, diagnosed)
    return diagnosed
