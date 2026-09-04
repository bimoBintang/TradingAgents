"""Shared pytest setup.

Tests that touch the database import `SessionLocal` directly rather than
starting the FastAPI app, so they never run the lifespan hook that calls
`Base.metadata.create_all()`. Any table added since the dev database was
last created would then be missing, and the failure surfaces as a
confusing "no such table" deep inside a service call.

Creating the schema once per session here is idempotent (create_all only
adds what is absent) and keeps DB-backed tests independent of whether
migrations have been applied to the local dev database.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    from api.database import engine
    from api.models import Base

    Base.metadata.create_all(bind=engine)
