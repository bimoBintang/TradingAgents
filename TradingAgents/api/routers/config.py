"""Config endpoints — read and update runtime configuration (per-user).

The owner's config is stored in the `user_configs` table.
API credentials are encrypted via Fernet and never stored in config_json.
"""

import json
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from api.schemas import ConfigResponse, ConfigUpdateRequest, BrokerTestRequest, BrokerTestResponse
from api.auth import get_current_user
from api.database import get_db
from api.dependencies import CONFIG_PATH  # noqa: F401  (tests patch this name)
from api.models import User
from api.user_context import get_user_config, save_user_config
from api.limiter import limiter, BROKER_TEST_RATE_LIMIT
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.execution.brokers.broker_base import BrokerConnectionError

logger = logging.getLogger("api.routers.config")
router = APIRouter(prefix="/api", tags=["Config"])

SENSITIVE_KEYS = {"api_key", "api_secret", "password", "telegram_bot_token"}


@router.get("/config", response_model=ConfigResponse)
async def read_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's runtime config (secrets masked)."""
    config = get_user_config(db, user.id)

    safe = _sanitise(config)
    return ConfigResponse(config=safe)


@router.put("/config", response_model=ConfigResponse)
async def update_config(
    body: ConfigUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Merge partial updates into the user's config and persist to DB.

    Credentials are encrypted before storage. Other fields are
    deep-merged into the existing config_json.
    """
    save_user_config(db, user.id, body.updates)

    # Return updated config
    config = get_user_config(db, user.id)
    safe = _sanitise(config)
    return ConfigResponse(config=safe)


@router.delete("/config/reset", response_model=ConfigResponse)
async def reset_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset the user's config to factory defaults."""
    import copy
    from api.models import UserConfig

    uc = db.query(UserConfig).filter(UserConfig.user_id == user.id).first()
    if uc:
        uc.config_json = "{}"
        uc.encrypted_api_key = ""
        uc.encrypted_api_secret = ""
        uc.encrypted_password = ""
        db.commit()

    safe = _sanitise(copy.deepcopy(DEFAULT_CONFIG))
    return ConfigResponse(config=safe)


@router.post("/config/test-broker", response_model=BrokerTestResponse)
@limiter.limit(BROKER_TEST_RATE_LIMIT)
async def test_broker_connection(
    request: Request,
    body: BrokerTestRequest,
    user: User = Depends(get_current_user),
):
    """Test whether the given broker/exchange credentials are valid and
    actually reachable — without persisting anything.

    Builds a throwaway broker instance via the same factory used at
    startup (`_create_broker`), which already runs `broker.health_check()`
    right after construction — an UNGUARDED balance fetch
    (`fetch_balance_strict()`, not `get_balance()`) so bad key/secret,
    missing passphrase, wrong sandbox flag, or network errors actually
    raise instead of being swallowed into a fake-success zeroed balance.
    Any failure surfaces here as a clear success=False response instead
    of a 500 (or worse, a false "valid").
    """
    # Local import: avoids pulling the full TradingAgentsGraph module
    # graph (heavy, LLM-client-loading) into every /api/config import.
    from tradingagents.graph.trading_graph import _create_broker

    # The paper broker is a local simulator — it never touches api_key/
    # api_secret, so its health_check() always succeeds trivially. Testing
    # it would falsely report ANY typed-in credentials as "valid". Refuse
    # up front instead of letting that lie through.
    if body.broker == "paper":
        return BrokerTestResponse(
            success=False,
            broker_name="paper",
            message="Paper Trading is a local simulator with no real account — "
                    "there's nothing to test. Select a real exchange or broker above first.",
        )

    # A ccxt broker with no exchange selected can't be tested either.
    if body.broker == "ccxt" and not body.exchange:
        return BrokerTestResponse(
            success=False,
            broker_name="ccxt",
            message="No exchange selected — pick one of the exchange cards above before testing.",
        )

    test_config = {
        "execution": {
            "broker": body.broker,
            "exchange": body.exchange,
            "api_key": body.api_key,
            "api_secret": body.api_secret,
            "password": body.password,
            "sandbox": body.sandbox,
            "market_type": body.market_type,
            "quote_currency": body.quote_currency,
        },
        "portfolio": {"initial_cash": 10000.0},
    }

    try:
        # ccxt/alpaca calls are blocking network I/O — keep them off the event loop.
        # _create_broker() already ran health_check() (fetch_balance_strict())
        # internally and would have raised by now if credentials were bad —
        # this second strict call is purely to get real numbers to display,
        # NOT the validity check itself. Deliberately NOT broker.get_balance():
        # that swallows errors and returns a zeroed dict, which would defeat
        # the whole point of this endpoint.
        broker = await run_in_threadpool(_create_broker, test_config)
        balance = await run_in_threadpool(broker.fetch_balance_strict)
        logger.info(
            "Broker test OK — user=%s broker=%s exchange=%s",
            user.id, body.broker, body.exchange,
        )
        return BrokerTestResponse(
            success=True,
            broker_name=broker.name,
            message=f"Connected to {broker.name} — credentials are valid.",
            balance=balance,
        )
    except BrokerConnectionError as e:
        logger.warning("Broker test FAILED (connection) — user=%s: %s", user.id, e)
        return BrokerTestResponse(
            success=False,
            broker_name=body.exchange or body.broker,
            message=str(e.detail or e),
        )
    except (ValueError, ImportError) as e:
        logger.warning("Broker test FAILED (config) — user=%s: %s", user.id, e)
        return BrokerTestResponse(
            success=False,
            broker_name=body.exchange or body.broker,
            message=str(e),
        )
    except Exception as e:
        logger.error("Broker test FAILED (unexpected) — user=%s: %s", user.id, e)
        return BrokerTestResponse(
            success=False,
            broker_name=body.exchange or body.broker,
            message=f"Unexpected error: {e}",
        )


def _sanitise(config: dict) -> dict:
    """Mask sensitive fields before returning to clients."""
    import copy

    safe = copy.deepcopy(config)

    # Mask API secrets
    for section_key in ("execution", "notifications"):
        section = safe.get(section_key, {})
        for secret_key in SENSITIVE_KEYS:
            if section.get(secret_key):
                section[secret_key] = "****" + section[secret_key][-4:] if len(section[secret_key]) > 4 else "****"

    return safe
