"""No login: every request acts as the single owner."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.models import Base, User, UserConfig, PortfolioState
from api.auth import get_or_create_owner


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        yield s


def test_creates_owner_once_with_config_and_portfolio(db):
    a = get_or_create_owner(db)
    b = get_or_create_owner(db)
    assert a.id == b.id and db.query(User).count() == 1
    assert db.query(UserConfig).filter_by(user_id=a.id).count() == 1
    assert db.query(PortfolioState).filter_by(user_id=a.id).count() == 1


def test_existing_first_user_is_the_owner(db):
    db.add_all([User(email="old@x", name="Old", hashed_password="x"),
                User(email="other@x", name="Other", hashed_password="x")])
    db.commit()
    assert get_or_create_owner(db).email == "old@x"
    assert db.query(User).count() == 2  # nothing created


class _Ctx:
    def __init__(self, s): self.s = s
    def __enter__(self): return self.s
    def __exit__(self, *a): return False


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from api.main import app
    from api.database import get_db
    from unittest.mock import patch
    app.dependency_overrides[get_db] = lambda: db
    # the websocket routes open their own session via SessionLocal
    with patch("api.routers.websocket.SessionLocal", lambda: _Ctx(db)):
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()


def test_api_needs_no_credentials_and_admin_is_gone(client):
    assert client.get("/api/portfolio").status_code == 200
    assert client.get("/api/admin/stats").status_code == 404


def test_websocket_connects_without_token(client):
    with client.websocket_connect("/ws/portfolio") as ws:
        assert ws.receive_json() is not None
