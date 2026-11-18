"""Cloudflare Turnstile: a bot check before a visitor's shop can use the live Agent.

With TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY set (and SANDBOXES=1), starting a live
story needs a Turnstile token from the story preview. The server checks it with
Cloudflare and marks the visitor's shop as checked (in the guards' control database); the
live Agent only takes turns for a checked shop. Most visitors pass without seeing
anything. A recorded run spends nothing, so it needs no check.

Cloudflare's test keys work locally: site key 1x00000000000000000000AA with secret
1x0000000000000000000000000000000AA always passes.
"""

import json
import os
import urllib.parse
import urllib.request

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def site_key() -> str | None:
    return os.environ.get("TURNSTILE_SITE_KEY", "").strip() or None


def enabled() -> bool:
    return bool(site_key() and os.environ.get("TURNSTILE_SECRET_KEY", "").strip())


def verify(token: str | None) -> bool:
    """Ask Cloudflare whether the token is good. Blocking: call it from a worker thread."""
    if not token:
        return False
    data = urllib.parse.urlencode({"secret": os.environ["TURNSTILE_SECRET_KEY"].strip(), "response": token}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(VERIFY_URL, data=data), timeout=10) as response:
            return bool(json.load(response).get("success"))
    except (OSError, ValueError):
        return False
