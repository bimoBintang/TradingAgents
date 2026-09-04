"""Rate limits on the endpoints that spend money or exchange quota.

`limiter` was constructed and registered on the app, but no endpoint ever
carried an `@limiter.limit` decorator — so nothing was limited. A single
runaway retry loop in the dashboard could fire /api/analyze without bound,
and each call runs the full agent graph: 20+ LLM requests, several on the
most expensive configured model.

The limits are also keyed per account rather than per IP. On IP alone,
one office NAT shares a quota between unrelated tenants while an account
calling from rotating addresses has none.
"""

import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from api.database import SessionLocal
from api.models import User, TaskResult


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def users(db):
    made = []
    for _ in range(2):
        u = User(
            email=f"__test_rl_{uuid.uuid4().hex[:10]}__@example.com",
            name="rl", hashed_password="x",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        made.append(u)
    yield made
    ids = [u.id for u in made]
    try:
        db.query(TaskResult).filter(TaskResult.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


def configured_analyze_limit() -> int:
    """The number of calls allowed, read from the limit actually in force.

    Not overridden via monkeypatch: @limiter.limit binds its argument when
    the route module is imported, so changing the env var afterwards has no
    effect on an already-decorated endpoint. Reading the real value keeps
    the test honest whatever the deployment sets.
    """
    from api.limiter import ANALYZE_RATE_LIMIT

    return int(ANALYZE_RATE_LIMIT.split("/")[0])


@pytest.fixture
def client(users, monkeypatch):
    """A client whose auth override sets request.state.user_id, as the real
    get_current_user() does — the limiter's key_func reads it from there.
    """
    from api.main import app
    from api.auth import get_current_user
    from api.dependencies import get_graph

    # The endpoint spawns a real analysis thread on the fallback path. Left
    # running, it writes to the TaskResult rows this test's teardown is
    # deleting, which surfaces as an unrelated ObjectDeletedError from a
    # background thread. Rate limiting is decided before dispatch, so
    # stubbing it out costs the test nothing.
    monkeypatch.setattr("api.tasks.run_analysis_thread", lambda *a, **k: None)

    current = {"u": users[0]}

    def fake_auth(request: Request) -> User:
        request.state.user_id = current["u"].id
        return current["u"]

    app.dependency_overrides[get_current_user] = fake_auth
    app.dependency_overrides[get_graph] = lambda: MagicMock()
    try:
        yield TestClient(app), current
    finally:
        app.dependency_overrides.clear()


class TestAnalyzeIsLimited:
    def test_the_endpoint_carries_a_limit_at_all(self):
        # The original defect: limiter existed, decorator was never applied.
        import inspect
        from api.routers import analysis

        assert "@limiter.limit" in inspect.getsource(analysis), (
            "/api/analyze must carry a rate limit — each call is 20+ LLM requests"
        )

    def test_requests_beyond_the_limit_are_rejected(self, client):
        c, _ = client
        allowed = configured_analyze_limit()
        codes = [
            c.post("/api/analyze", json={"ticker": "BTC/USDT"}).status_code
            for _ in range(allowed + 2)
        ]
        assert codes[:allowed] == [200] * allowed, f"a call inside the quota failed: {codes}"
        assert codes[allowed] == 429, f"the call past the quota was not limited: {codes}"

    def test_limit_is_keyed_per_account_not_per_ip(self, client, users):
        c, current = client

        # Exhaust the first account's quota.
        for _ in range(configured_analyze_limit() + 2):
            c.post("/api/analyze", json={"ticker": "BTC/USDT"})

        # A different account from the same address must be unaffected.
        current["u"] = users[1]
        second = c.post("/api/analyze", json={"ticker": "BTC/USDT"})
        assert second.status_code < 400, (
            "a second tenant behind the same IP was blocked by the first "
            "tenant's usage — the limit is keyed on IP, not account"
        )


class TestBrokerTestIsLimited:
    def test_the_endpoint_carries_a_limit(self):
        # test-broker sends credentials to a live exchange; exchanges
        # rate-limit and then IP-ban, which takes trading offline for
        # every account on the host.
        import inspect
        from api.routers import config

        assert "@limiter.limit" in inspect.getsource(config)


class TestKeyFunction:
    def test_falls_back_to_ip_when_unauthenticated(self):
        from api.limiter import user_or_ip

        req = MagicMock()
        req.state = MagicMock(spec=[])          # no user_id attribute
        req.client.host = "203.0.113.7"
        req.headers = {}
        assert user_or_ip(req).startswith("ip:")

    def test_prefers_the_account_when_present(self):
        from api.limiter import user_or_ip

        req = MagicMock()
        req.state.user_id = 99
        assert user_or_ip(req) == "user:99"
