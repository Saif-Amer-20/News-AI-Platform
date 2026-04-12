"""Celery failure handlers — routes exhausted tasks to the dead letter queue."""
from __future__ import annotations

import logging

from celery import current_app
from celery.signals import task_failure, task_retry

logger = logging.getLogger(__name__)


@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None,
                    args=None, kwargs=None, traceback=None,
                    einfo=None, **kw):
    """Route permanently failed tasks to the dead letter queue.

    This fires after max_retries is exhausted.
    """
    task_name = sender.name if sender else "unknown"

    # Determine retry count
    retry_count = 0
    if hasattr(sender, "request"):
        retry_count = getattr(sender.request, "retries", 0)

    try:
        from ops.dlq import DeadLetterItem

        DeadLetterItem.store_failure(
            task_name=task_name,
            task_id=task_id or "",
            args=list(args) if args else [],
            kwargs=dict(kwargs) if kwargs else {},
            exception=exception,
            retry_count=retry_count,
            metadata={
                "signal": "task_failure",
            },
        )
    except Exception as e:
        # If DLQ storage itself fails, at least log it
        logger.error(
            "Failed to store task %s in DLQ: %s (original error: %s)",
            task_name, e, exception,
        )
