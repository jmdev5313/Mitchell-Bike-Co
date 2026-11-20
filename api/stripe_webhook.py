"""Stripe's webhook: Stripe tells the shop when a checkout finishes, even if the Customer never comes back.

Each event is verified against STRIPE_WEBHOOK_SECRET and then treated only as a nudge:
the shop retrieves the session from Stripe and settles it exactly as when the Customer
returns (`customer._confirm`). So the return link and the webhook can arrive in either
order, or both, and the payment is recorded once.

In the hosted demo the session's metadata names the visitor's sandbox, which is how the
event finds the right shop (the request carries no cookie). Events for sessions the shop
doesn't know (another app on the same Stripe account, a rebuilt database, a sandbox that
has been swept) are acknowledged and ignored, so Stripe doesn't keep retrying them.
"""

import json
import os
from contextlib import nullcontext
from typing import Any

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from api import customer, sandboxes
from api.deps import get_stripe
from shop import db, payments
from shop.errors import NotFound

router = APIRouter(prefix="/api/stripe", tags=["stripe"])

PATH = "/api/stripe/webhook"
HANDLED = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
}


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    stripe_signature: str | None = Header(None),
    stripe_client: Any = Depends(get_stripe),
) -> dict[str, Any]:
    """Receive a Stripe event about a checkout session."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "STRIPE_WEBHOOK_SECRET is not set on the server")
    payload = (await request.body()).decode("utf-8")
    try:
        stripe.WebhookSignature.verify_header(payload, stripe_signature, secret, tolerance=300)
    except stripe.SignatureVerificationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the Stripe signature doesn't match")
    event = json.loads(payload)
    if event.get("type") not in HANDLED:
        return {"received": True, "ignored": "not a checkout event the shop handles"}
    session = event["data"]["object"]
    sandbox = (session.get("metadata") or {}).get("sandbox")
    return await run_in_threadpool(_handle, stripe_client, event["type"], session["id"], sandbox)


def _handle(stripe_client: Any, kind: str, session_id: str, sandbox: str | None) -> dict[str, Any]:
    if sandboxes.enabled():
        path = sandboxes.existing(sandbox)
        if path is None:
            return {"received": True, "ignored": "no such sandbox (it may have expired)"}
        shop_db = db.using(path)
    else:
        shop_db = nullcontext()
    with shop_db:
        conn = db.connect()
        try:
            try:
                payment = payments.payment_for_session(conn, session_id)
            except NotFound:
                return {"received": True, "ignored": "unknown checkout session"}
            settled = customer._confirm(conn, stripe_client, payment.work_order_id, session_id,
                                        failed=kind == "checkout.session.async_payment_failed")
            return {"received": True, "payment": settled}
        finally:
            conn.close()
