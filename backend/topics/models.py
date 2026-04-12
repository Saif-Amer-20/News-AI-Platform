from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimeStampedModel
from core.utils import build_unique_slug


class Topic(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_topics",
    )
    geography_focus = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topics_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="topics_updated",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = build_unique_slug(Topic, self.name, instance=self, fallback_prefix="topic")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Watchlist(TimeStampedModel):
    class WatchlistType(models.TextChoices):
        ENTITY = "entity", "Entity"
        ORGANIZATION = "organization", "Organization"
        LOCATION = "location", "Location"
        THEME = "theme", "Theme"
        CUSTOM = "custom", "Custom"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="watchlists")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    watchlist_type = models.CharField(
        max_length=20,
        choices=WatchlistType.choices,
        default=WatchlistType.CUSTOM,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_watchlists",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="watchlists_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="watchlists_updated",
    )

    class Meta:
        ordering = ["topic__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["topic", "name"], name="uniq_watchlist_per_topic"),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["watchlist_type"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = build_unique_slug(
                Watchlist,
                f"{self.topic.name}-{self.name}",
                instance=self,
                fallback_prefix="watchlist",
            )
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.topic.name}: {self.name}"


class KeywordRule(TimeStampedModel):
    class RuleType(models.TextChoices):
        KEYWORD = "keyword", "Keyword"
        PHRASE = "phrase", "Phrase"
        BOOLEAN = "boolean", "Boolean"
        REGEX = "regex", "Regex"

    class MatchTarget(models.TextChoices):
        ANY = "any", "Any"
        TITLE = "title", "Title"
        BODY = "body", "Body"
        URL = "url", "URL"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="keyword_rules")
    watchlist = models.ForeignKey(
        Watchlist,
        on_delete=models.CASCADE,
        related_name="keyword_rules",
        null=True,
        blank=True,
    )
    label = models.CharField(max_length=200)
    pattern = models.TextField()
    normalized_pattern = models.CharField(max_length=512, editable=False, blank=True)
    rule_type = models.CharField(
        max_length=20,
        choices=RuleType.choices,
        default=RuleType.KEYWORD,
    )
    match_target = models.CharField(
        max_length=20,
        choices=MatchTarget.choices,
        default=MatchTarget.ANY,
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    case_sensitive = models.BooleanField(default=False)
    is_exclusion = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="keyword_rules_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="keyword_rules_updated",
    )

    class Meta:
        ordering = ["topic__name", "label"]
        indexes = [
            models.Index(fields=["enabled"]),
            models.Index(fields=["rule_type"]),
            models.Index(fields=["match_target"]),
            models.Index(fields=["priority"]),
        ]

    def clean(self) -> None:
        if self.watchlist_id and self.watchlist.topic_id != self.topic_id:
            raise ValidationError("Keyword rule watchlist must belong to the same topic.")

    def save(self, *args, **kwargs):
        self.normalized_pattern = self.pattern.strip()
        if not self.case_sensitive:
            self.normalized_pattern = self.normalized_pattern.lower()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.label} ({self.rule_type})"

