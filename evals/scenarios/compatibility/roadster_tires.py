"""Ruth's roadster: "28 inch" isn't 700c.

Her 1950s roadster has 635 mm rims (28 x 1 1/2). A 700c tire, also sold as "28 inch" in
some places, is smaller and won't fit. Two of the 635 tires are in stock.
"""

from demo.stories import BY_KEY
from evals.common import Scenario
from evals.scenarios._quote import quote_turn

STORY = BY_KEY["roadster-tires"]


def check_lines(report, skus, services):
    report.add("quote has the 28 x 1 1/2 tires", "FS-TR635-38" in skus, f"parts: {skus}")
    report.add("quote does not have the 700c tire", "FS-TR700-40" not in skus, f"parts: {skus}")


def two_tires(conn, report, work_order_id, today, replies):
    qty = sum(r[0] for r in conn.execute(
        """SELECT l.qty FROM work_order_lines l JOIN parts p ON p.id = l.part_id
           WHERE l.work_order_id = ? AND p.sku = 'FS-TR635-38'""", (work_order_id,)))
    report.add("quoted two tires", qty == 2, f"qty: {qty}", required=False)


SCENARIO = Scenario(
    key=STORY.key, group=STORY.group,
    title="A vintage roadster's \"28 inch\" isn't 700c",
    play=quote_turn(STORY.email, STORY.mechanic_message, check_lines, extra=two_tires),
)
