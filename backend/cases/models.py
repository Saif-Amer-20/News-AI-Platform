from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel
from core.utils import build_unique_slug


class Case(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ON_HOLD = "on_hold", "On Hold"
        CLOSED = "closed", "Closed"
        ARCHIVED = "archived", "Archived"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Classification(models.TextChoices):
        INTERNAL = "internal", "Internal"
        RESTRICTED = "restricted", "Restricted"
        CONFIDENTIAL = "confidential", "Confidential"

    title = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    classification = models.CharField(
        max_length=20,
        choices=Classification.choices,
        default=Classification.INTERNAL,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_cases",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cases_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cases_updated",
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["classification"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = build_unique_slug(Case, self.title, instance=self, fallback_prefix="case")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class CaseMember(TimeStampedModel):
    class Role(models.TextChoices):
        LEAD = "lead", "Lead"
        ANALYST = "analyst", "Analyst"
        VIEWER = "viewer", "Viewer"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="case_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ANALYST)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="case_memberships_assigned",
    )

    class Meta:
        ordering = ["case__title", "user__username"]
        constraints = [
            models.UniqueConstraint(fields=["case", "user"], name="uniq_case_member"),
        ]

    def __str__(self) -> str:
        return f"{self.case.title} - {self.user.get_username()}"


class CaseNote(TimeStampedModel):
    class NoteType(models.TextChoices):
        ANALYST_NOTE = "analyst_note", "Analyst Note"
        FINDING = "finding", "Finding"
        UPDATE = "update", "Update"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="case_notes_authored",
    )
    note_type = models.CharField(
        max_length=24,
        choices=NoteType.choices,
        default=NoteType.ANALYST_NOTE,
    )
    body = models.TextField()
    is_pinned = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.case.title} - {self.note_type}"


class CaseReference(TimeStampedModel):
    class ReferenceType(models.TextChoices):
        TOPIC = "topic", "Topic"
        SOURCE = "source", "Source"
        ALERT = "alert", "Alert"
        EXTERNAL = "external", "External"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="references")
    reference_type = models.CharField(
        max_length=20,
        choices=ReferenceType.choices,
        default=ReferenceType.EXTERNAL,
    )
    title = models.CharField(max_length=255)
    target_app_label = models.CharField(max_length=50, blank=True)
    target_model = models.CharField(max_length=50, blank=True)
    target_object_id = models.CharField(max_length=64, blank=True)
    external_url = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="case_references_added",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["reference_type"]),
        ]

    def clean(self) -> None:
        if self.reference_type == self.ReferenceType.EXTERNAL:
            if not self.external_url:
                raise ValidationError("External references must include an external URL.")
            return

        target_fields = [self.target_app_label, self.target_model, self.target_object_id]
        if not all(target_fields):
            raise ValidationError(
                "Internal case references must include target app, model, and object ID."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.case.title} - {self.title}"


class CaseArticle(TimeStampedModel):
    """Link an Article to a Case for investigation."""

    class Relevance(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="articles")
    article = models.ForeignKey(
        "sources.Article",
        on_delete=models.CASCADE,
        related_name="case_links",
    )
    notes = models.TextField(blank=True)
    relevance = models.CharField(
        max_length=20,
        choices=Relevance.choices,
        default=Relevance.MEDIUM,
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["case", "article"], name="uniq_case_article"),
        ]

    def __str__(self) -> str:
        return f"Case {self.case_id} ← Article {self.article_id}"


class CaseEntity(TimeStampedModel):
    """Link an Entity to a Case for investigation."""

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="entities")
    entity = models.ForeignKey(
        "sources.Entity",
        on_delete=models.CASCADE,
        related_name="case_links",
    )
    notes = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["case", "entity"], name="uniq_case_entity"),
        ]

    def __str__(self) -> str:
        return f"Case {self.case_id} ← Entity {self.entity_id}"


class CaseEvent(TimeStampedModel):
    """Link an Event to a Case for investigation."""

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="events")
    event = models.ForeignKey(
        "sources.Event",
        on_delete=models.CASCADE,
        related_name="case_links",
    )
    notes = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["case", "event"], name="uniq_case_event"),
        ]

    def __str__(self) -> str:
        return f"Case {self.case_id} ← Event {self.event_id}"


class SavedSearch(TimeStampedModel):
    """A saved search query with parameters that can be re-executed."""

    class SearchType(models.TextChoices):
        ARTICLE = "article", "Article"
        EVENT = "event", "Event"
        ENTITY = "entity", "Entity"
        ALERT = "alert", "Alert"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    search_type = models.CharField(
        max_length=20,
        choices=SearchType.choices,
        default=SearchType.ARTICLE,
    )
    query_params = models.JSONField(
        default=dict,
        help_text="Serialized query parameters.",
    )
    is_global = models.BooleanField(default=False, help_text="Visible to all users.")
    is_pinned = models.BooleanField(default=False)
    last_executed_at = models.DateTimeField(null=True, blank=True)
    execution_count = models.PositiveIntegerField(default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="saved_searches",
    )
    case = models.ForeignKey(
        Case,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="saved_searches",
    )

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_saved_search_per_user"),
        ]
        indexes = [
            models.Index(fields=["search_type"]),
            models.Index(fields=["is_global"]),
        ]

    def __str__(self) -> str:
        return self.name

