"""Celery application instance.

Connects to Redis as message broker and result backend.
Falls back gracefully if Redis/Celery is unavailable (local dev).

Usage:
    celery -A api.celery_app worker --loglevel=info
"""

import os
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("api.celery")

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)

celery_app = None
_celery_available = False

if CELERY_BROKER_URL:
    try:
        from celery import Celery

        celery_app = Celery(
            "tradingagents",
            broker=CELERY_BROKER_URL,
            backend=CELERY_RESULT_BACKEND,
        )

        celery_app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            task_acks_late=True,           # Re-queue if worker dies
            worker_prefetch_multiplier=1,  # Fair scheduling
            task_soft_time_limit=600,      # 10 min soft limit
            task_time_limit=660,           # 11 min hard limit
        )

        # Auto-discover tasks in api.tasks
        celery_app.autodiscover_tasks(["api"])

        _celery_available = True
        logger.info("Celery configured with broker: %s", CELERY_BROKER_URL)

    except ImportError:
        logger.warning("celery package not installed. Using thread fallback.")
else:
    logger.info("CELERY_BROKER_URL not set. Using thread fallback for background tasks.")


def is_celery_available() -> bool:
    """Check if Celery is configured and available."""
    return _celery_available
