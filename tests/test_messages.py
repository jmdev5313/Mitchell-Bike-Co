import pytest

from shop import messages
from shop import work_orders as wo
from shop.errors import NotFound, RuleViolation
from tests.conftest import HERO_QUOTE


def test_agent_drafts_and_mechanic_sends_the_quote(conn, quoted):
    draft = messages.draft_message(conn, quoted, "Your repair comes to $169.98.", include_quote=True)
    assert (draft.status, draft.author, draft.quoted_total_cents) == ("draft", "agent", HERO_QUOTE)
    sent = messages.send_draft(conn, draft.id)
    assert sent.status == "sent" and sent.sent_at


def test_quote_message_needs_a_locked_quote(conn, diagnosed):
    with pytest.raises(RuleViolation, match="lock the quote"):
        messages.draft_message(conn, diagnosed, "Here is your quote", include_quote=True)
    # A plain message is fine at any stage.
    assert messages.draft_message(conn, diagnosed, "We're looking at your bike now").quoted_total_cents is None


def test_mechanic_can_edit_a_draft_but_not_a_sent_message(conn, quoted):
    draft = messages.draft_message(conn, quoted, "Draft one")
    assert messages.edit_draft(conn, draft.id, "Draft two").body == "Draft two"
    messages.send_draft(conn, draft.id)
    with pytest.raises(RuleViolation, match="only drafts"):
        messages.edit_draft(conn, draft.id, "Too late")
    with pytest.raises(RuleViolation, match="not a draft"):
        messages.send_draft(conn, draft.id)


def test_stale_quote_message_cannot_be_sent(conn, quoted, quote_sent):
    stale = messages.draft_message(conn, quoted, "Reminder: $169.98", include_quote=True)
    wo.record_customer_decision(conn, quote_sent, approved=True)
    with pytest.raises(RuleViolation, match="no longer open"):
        messages.send_draft(conn, stale.id)


def test_customer_replies_are_recorded_in_order(conn, quoted, quote_sent):
    messages.receive_message(conn, quoted, "Can it be ready by Friday?")
    thread = messages.list_messages(conn, quoted)
    assert [(m.direction, m.status, m.author) for m in thread] == [
        ("to_customer", "sent", "agent"),
        ("from_customer", "received", "customer"),
    ]


def test_only_agent_or_mechanic_draft(conn, quoted):
    with pytest.raises(RuleViolation, match="not 'customer'"):
        messages.draft_message(conn, quoted, "Hi", author="customer")
    assert messages.draft_message(conn, quoted, "Hi", author="mechanic").author == "mechanic"


def test_bad_inputs(conn, quoted):
    with pytest.raises(RuleViolation, match="empty"):
        messages.draft_message(conn, quoted, "   ")
    with pytest.raises(NotFound):
        messages.draft_message(conn, 9999, "Hi")
    with pytest.raises(NotFound):
        messages.get_message(conn, 9999)
    with pytest.raises(NotFound):
        messages.receive_message(conn, 9999, "Hi")
