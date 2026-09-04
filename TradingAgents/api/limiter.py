"""Rate Limiter for the FastAPI application.

Limits here are not about server load. The endpoints they protect each
spend real money or real reputation on an outside service:

  * /api/analyze runs the full agent graph — 20+ LLM calls per request,
    several of them on the most expensive model configured. An accidental
    retry loop in the dashboard is a billing incident.
  * /api/config/test-broker sends credentials to an exchange. Exchanges
    rate-limit and then IP-ban; burning that quota takes live trading
    offline for everyone on the host, not just the caller.

So the limits are deliberately tight, and keyed per account.
"""

import os

from slowapi import Limiter, _rate_limit_exceeded_handler  # noqa: F401 (re-exported)
from slowapi.util import get_remote_address


def user_or_ip(request) -> str:
    """Key limits by authenticated account, falling back to IP.

    get_current_user() puts the resolved id on request.state (see
    api/auth.py). Keying on IP alone is wrong in both directions for a
    multi-tenant SaaS: an office behind one NAT shares a single quota
    between unrelated accounts, and one account calling from rotating
    addresses is effectively unlimited.

    The IP fallback still matters — it covers requests that fail auth or
    that never had it — so an unauthenticated flood is not free.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is not None:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=user_or_ip)

# Overridable per deployment: a shared demo instance wants far less than a
# single-tenant box. Kept as strings because that is slowapi's own format.
ANALYZE_RATE_LIMIT = os.getenv("ANALYZE_RATE_LIMIT", "10/hour")
BROKER_TEST_RATE_LIMIT = os.getenv("BROKER_TEST_RATE_LIMIT", "10/minute")
