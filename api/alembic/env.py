"""Alembic environment configuration.

Reads DATABASE_URL from .env and applies migrations
against the same engine used by the FastAPI app.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# Add project root to path so we can import api.models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

load_dotenv()

# Alembic Config object
config = context.config

# Override sqlalchemy.url from env var
database_url = os.getenv("DATABASE_URL", "sqlite:///./tradingagents.db")
if database_url.startswith("libsql://"):
    database_url = database_url.replace("libsql://", "sqlite+libsql://")
config.set_main_option("sqlalchemy.url", database_url)

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import models so Alembic can detect schema
from api.models import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to DB and applies."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
