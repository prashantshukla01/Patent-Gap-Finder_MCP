"""Celery application configuration.

Uses Redis as both broker and result backend.
"""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "patent_gap_finder",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["patent_gap_finder.workers.search_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,   # 5 min soft limit
    task_time_limit=360,        # 6 min hard limit
    result_expires=86400,       # Keep results 24 hours
)
