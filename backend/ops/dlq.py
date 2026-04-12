"""Dead letter queue for failed Celery task payloads.

When a task exhausts its retries, the payload is stored in the database
so operators can inspect, replay, or discard failed work items.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime

from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel

logger = logging.getLogger(__name__)


class DeadLetterItem(TimeStampedModel):
    """A failed task payload stored for manual recovery."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        RETRIED = "retried", "Retried"
        DISCARDED = "discarded", "Discarded"

    task_name = models.CharField(max_length=255, db_index=True)
    task_id = models.CharField(max_length=64, blank=True)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    exception_type = models.CharField(max_length=255, blank=True)
    exception_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=150, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["task_name"]),
        ]

    def __str__(self) -> str:
        return f"DLQ: {self.task_name} ({self.status})"

    @classmethod
    def store_failure(
        cls,
        task_name: str,
        task_id: str = "",
        args: list | None = None,
        kwargs: dict | None = None,
        exception: Exception | None = None,
        retry_count: int = 0,
        metadata: dict | None = None,
    ) -> "DeadLetterItem":
        """Store a failed task in the dead letter queue."""
        exc_type = type(exception).__name__ if exception else ""
        exc_msg = str(exception)[:2000] if exception else ""
        tb = traceback.format_exception(exception) if exception else []

        item = cls.objects.create(
            task_name=task_name,
            task_id=task_id,
            args=args or [],
            kwargs=kwargs or {},
            exception_type=exc_type,
            exception_message=exc_msg,
            traceback="".join(tb)[:5000],
            retry_count=retry_count,
            metadata=metadata or {},
        )
        logger.warning(
            "Task %s (id=%s) added to dead letter queue: %s",
            task_name, task_id, exc_msg[:200],
        )
        return item

    def replay(self) -> str:
        """Re-send this task to Celery for processing.

        Returns the new task ID.
        """
        from celery import current_app

        result = current_app.send_task(
            self.task_name,
            args=self.args,
            kwargs=self.kwargs,
        )
        self.status = self.Status.RETRIED
        self.resolved_at = timezone.now()
        self.retry_count += 1
        self.save(update_fields=["status", "resolved_at", "retry_count", "updated_at"])

        logger.info(
            "DLQ item %d replayed as task %s", self.id, result.id,
        )
        return result.id

    def discard(self, resolved_by: str = ""):
        """Mark this item as discarded (will not be retried)."""
        self.status = self.Status.DISCARDED
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by
        self.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])
