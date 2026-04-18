from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class ValidationTag(TimeStampedModel):
    """Human annotation for validation — optional manual tagging.

    Allows a reviewer to confirm or correct the pseudo-ground-truth
    for a small subset of articles.
    """

    class TagType(models.TextChoices):
        CLUSTER_CORRECT = "cluster_correct", "Cluster assignment correct"
        CLUSTER_WRONG = "cluster_wrong", "Cluster assignment wrong"
        DUP_CORRECT = "dup_correct", "Duplicate flag correct"
        DUP_WRONG = "dup_wrong", "Duplicate flag wrong — not a duplicate"
        DUP_MISSED = "dup_missed", "Missed duplicate — should be flagged"
        ENTITY_MISSING = "entity_missing", "Entity missed by extraction"
        ENTITY_WRONG = "entity_wrong", "Entity extracted incorrectly"
        GEO_CORRECT = "geo_correct", "Geo location correct"
        GEO_WRONG = "geo_wrong", "Geo location incorrect"
        CONFLICT_CORRECT = "conflict_correct", "Conflict flag correct"
        CONFLICT_WRONG = "conflict_wrong", "Conflict flag incorrect"
        QUALITY_OVERRIDE = "quality_override", "Quality score override"

    article = models.ForeignKey(
        "sources.Article",
        on_delete=models.CASCADE,
        related_name="validation_tags",
    )
    tag_type = models.CharField(max_length=32, choices=TagType.choices, db_index=True)
    correct_value = models.TextField(
        blank=True,
        help_text="The correct value (e.g. correct cluster key, correct entity name).",
    )
    notes = models.TextField(blank=True)
    tagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tag_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_tag_type_display()} — Article {self.article_id}"


class ValidationRun(TimeStampedModel):
    """Record of each benchmark run for trend tracking."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    articles_sampled = models.PositiveIntegerField(default=0)
    report_json = models.JSONField(default=dict, blank=True)
    elapsed_seconds = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00")
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Validation run {self.id} — {self.status} ({self.articles_sampled} articles)"
