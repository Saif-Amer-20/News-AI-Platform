from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel
from core.utils import build_unique_slug


class Source(TimeStampedModel):
    class SourceType(models.TextChoices):
        RSS = "rss", "RSS"
        SITEMAP = "sitemap", "Sitemap"
        HTML = "html", "HTML"
        API = "api", "API"

    class ParserType(models.TextChoices):
        RSS = "rss", "RSS"
        SITEMAP = "sitemap", "Sitemap"
        HTML = "html", "HTML"
        GDELT = "gdelt", "GDELT"
        NEWSAPI = "newsapi", "NewsAPI"
        GNEWS = "gnews", "GNews"
        SCRAPY_INGESTION = "scrapy_ingestion", "Scrapy Ingestion"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        DISABLED = "disabled", "Disabled"

    class HealthStatus(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        HEALTHY = "healthy", "Healthy"
        DEGRADED = "degraded", "Degraded"
        FAILING = "failing", "Failing"

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    source_type = models.CharField(
        max_length=24,
        choices=SourceType.choices,
        default=SourceType.RSS,
    )
    parser_type = models.CharField(
        max_length=32,
        choices=ParserType.choices,
        default=ParserType.RSS,
    )
    base_url = models.URLField(blank=True)
    endpoint_url = models.URLField(blank=True)
    language = models.CharField(max_length=16, blank=True)
    country = models.CharField(max_length=2, blank=True)
    trust_score = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.50"),
    )
    total_articles_fetched = models.PositiveIntegerField(default=0)
    total_duplicates = models.PositiveIntegerField(default=0)
    total_low_quality = models.PositiveIntegerField(default=0)
    avg_quality_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.50"),
    )
    is_active = models.BooleanField(default=True)
    fetch_interval_minutes = models.PositiveIntegerField(default=30)
    default_language = models.CharField(max_length=16, blank=True)
    default_country = models.CharField(max_length=2, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    health_status = models.CharField(
        max_length=20,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
    )
    polling_interval_minutes = models.PositiveIntegerField(default=30)
    request_timeout_seconds = models.PositiveIntegerField(default=30)
    is_public = models.BooleanField(default=True)
    parser_config = models.JSONField(default=dict, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sources_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sources_updated",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["source_type"]),
            models.Index(fields=["parser_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["health_status"]),
            models.Index(fields=["is_active"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = build_unique_slug(Source, self.name, instance=self, fallback_prefix="source")
        if not self.language and self.default_language:
            self.language = self.default_language
        if not self.country and self.default_country:
            self.country = self.default_country
        if not self.fetch_interval_minutes and self.polling_interval_minutes:
            self.fetch_interval_minutes = self.polling_interval_minutes
        super().save(*args, **kwargs)

    @property
    def fetch_url(self) -> str:
        return self.endpoint_url or self.base_url

    def effective_fetch_interval(self) -> int:
        return self.fetch_interval_minutes or self.polling_interval_minutes

    def __str__(self) -> str:
        return self.name


class SourceHealthEvent(TimeStampedModel):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="health_events")
    health_status = models.CharField(
        max_length=20,
        choices=Source.HealthStatus.choices,
        default=Source.HealthStatus.UNKNOWN,
    )
    status_code = models.PositiveIntegerField(null=True, blank=True)
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    detail = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["health_status"]),
            models.Index(fields=["created_at"]),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        update_fields = {
            "health_status": self.health_status,
            "last_checked_at": self.created_at or timezone.now(),
        }
        if self.health_status in {Source.HealthStatus.HEALTHY, Source.HealthStatus.DEGRADED}:
            update_fields["last_success_at"] = self.created_at or timezone.now()
            update_fields["last_error_message"] = ""
        if self.health_status == Source.HealthStatus.FAILING:
            update_fields["last_failure_at"] = self.created_at or timezone.now()
            update_fields["last_error_message"] = self.detail

        Source.objects.filter(pk=self.source_id).update(**update_fields)

    def __str__(self) -> str:
        return f"{self.source.name} - {self.health_status}"


class SourceFetchRun(TimeStampedModel):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="fetch_runs")
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    items_fetched = models.PositiveIntegerField(default=0)
    items_created = models.PositiveIntegerField(default=0)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source.name} fetch at {self.started_at:%Y-%m-%d %H:%M:%S}"


class SourceFetchError(TimeStampedModel):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="fetch_errors")
    fetch_run = models.ForeignKey(
        SourceFetchRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="errors",
    )
    url = models.URLField(blank=True)
    error = models.TextField()
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.source.name} error at {self.timestamp:%Y-%m-%d %H:%M:%S}"


class RawItem(TimeStampedModel):
    class Status(models.TextChoices):
        FETCHED = "fetched", "Fetched"
        PARSED = "parsed", "Parsed"
        NORMALIZED = "normalized", "Normalized"
        ARTICLE_CREATED = "article_created", "Article Created"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="raw_items")
    fetch_run = models.ForeignKey(
        SourceFetchRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="raw_items",
    )
    url = models.URLField(max_length=1000)
    title_raw = models.TextField(blank=True)
    content_raw = models.TextField(blank=True)
    html_raw = models.TextField(blank=True)
    fetched_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.FETCHED)
    error_message = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    raw_storage_key = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-fetched_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "url", "content_hash"],
                name="uniq_raw_item_source_url_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["fetched_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source.name} - {self.url}"


class ParsedArticleCandidate(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARSED = "parsed", "Parsed"
        NORMALIZED = "normalized", "Normalized"
        ARTICLE_CREATED = "article_created", "Article Created"
        FAILED = "failed", "Failed"

    raw_item = models.OneToOneField(
        RawItem,
        on_delete=models.CASCADE,
        related_name="parsed_candidate",
    )
    title = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    author = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["published_at"]),
        ]

    def __str__(self) -> str:
        return f"Candidate for raw item {self.raw_item_id}"


class Story(TimeStampedModel):
    story_key = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    first_published_at = models.DateTimeField(null=True, blank=True)
    last_published_at = models.DateTimeField(null=True, blank=True)
    article_count = models.PositiveIntegerField(default=0)
    importance_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        db_index=True,
    )
    event = models.ForeignKey(
        "Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stories",
    )

    class Meta:
        ordering = ["-last_published_at", "-updated_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = build_unique_slug(Story, self.title, instance=self, fallback_prefix="story")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class Article(TimeStampedModel):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="articles")
    raw_item = models.OneToOneField(
        RawItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="article",
    )
    parsed_candidate = models.OneToOneField(
        ParsedArticleCandidate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="article",
    )
    story = models.ForeignKey(
        Story,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    duplicate_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="duplicates",
    )
    url = models.URLField(max_length=1000, db_index=True)
    canonical_url = models.URLField(max_length=1000, blank=True)
    title = models.CharField(max_length=500)
    normalized_title = models.CharField(max_length=500, db_index=True)
    content = models.TextField()
    normalized_content = models.TextField()
    published_at = models.DateTimeField(null=True, blank=True)
    author = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    matched_rule_labels = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_duplicate = models.BooleanField(default=False)
    importance_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        db_index=True,
    )
    quality_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        db_index=True,
    )
    matched_topics = models.ManyToManyField("topics.Topic", blank=True, related_name="articles")
    entities = models.ManyToManyField(
        "Entity",
        through="ArticleEntity",
        blank=True,
        related_name="articles",
    )

    class Meta:
        ordering = ["-published_at", "-updated_at"]
        indexes = [
            models.Index(fields=["content_hash"]),
            models.Index(fields=["is_duplicate"]),
            models.Index(fields=["published_at"]),
        ]

    def __str__(self) -> str:
        return self.title


class Event(TimeStampedModel):
    """Represents a real-world occurrence that one or more stories describe."""

    class EventType(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        STRIKE = "strike", "Strike"
        EXPLOSION = "explosion", "Explosion"
        PROTEST = "protest", "Protest"
        POLITICAL = "political", "Political Event"
        CONFLICT = "conflict", "Armed Conflict"
        DISASTER = "disaster", "Natural Disaster"
        ECONOMIC = "economic", "Economic Event"
        DIPLOMACY = "diplomacy", "Diplomacy"
        CRIME = "crime", "Crime"
        HEALTH = "health", "Health Event"
        TECHNOLOGY = "technology", "Technology"
        OTHER = "other", "Other"

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    event_type = models.CharField(
        max_length=24,
        choices=EventType.choices,
        default=EventType.UNKNOWN,
        db_index=True,
    )
    location_name = models.CharField(max_length=300, blank=True)
    location_country = models.CharField(max_length=2, blank=True)
    location_lat = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    location_lon = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    first_reported_at = models.DateTimeField(null=True, blank=True)
    last_reported_at = models.DateTimeField(null=True, blank=True)
    story_count = models.PositiveIntegerField(default=0)
    source_count = models.PositiveIntegerField(default=0)
    importance_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        db_index=True,
    )
    confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        db_index=True,
    )
    geo_confidence = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    conflict_flag = models.BooleanField(default=False, db_index=True)
    timeline_json = models.JSONField(
        default=list,
        blank=True,
        help_text="Chronological list of event updates [{ts, summary, source_id}].",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_reported_at", "-updated_at"]
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["first_reported_at"]),
            models.Index(fields=["last_reported_at"]),
            models.Index(fields=["confidence_score"]),
            models.Index(fields=["conflict_flag"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = build_unique_slug(Event, self.title, instance=self, fallback_prefix="event")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"[{self.get_event_type_display()}] {self.title}"


class Entity(TimeStampedModel):
    """A named entity (person, location, organization) extracted from articles."""

    class EntityType(models.TextChoices):
        PERSON = "person", "Person"
        LOCATION = "location", "Location"
        ORGANIZATION = "organization", "Organization"

    name = models.CharField(max_length=300)
    normalized_name = models.CharField(max_length=300, db_index=True)
    canonical_name = models.CharField(
        max_length=300,
        blank=True,
        db_index=True,
        help_text="Canonical form of this entity (e.g. 'United States' for 'USA').",
    )
    aliases = models.JSONField(
        default=list,
        blank=True,
        help_text="Known alternative names / abbreviations for this entity.",
    )
    entity_type = models.CharField(
        max_length=16,
        choices=EntityType.choices,
        db_index=True,
    )
    country = models.CharField(max_length=2, blank=True)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["normalized_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["normalized_name", "entity_type"],
                name="uniq_entity_name_type",
            ),
        ]
        indexes = [
            models.Index(fields=["entity_type"]),
        ]
        verbose_name_plural = "entities"

    def __str__(self) -> str:
        return f"{self.name} ({self.get_entity_type_display()})"


class ArticleEntity(TimeStampedModel):
    """Through-model linking an Article to an Entity with per-occurrence metadata."""

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="article_entities",
    )
    entity = models.ForeignKey(
        Entity,
        on_delete=models.CASCADE,
        related_name="article_entities",
    )
    relevance_score = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.50"),
    )
    mention_count = models.PositiveIntegerField(default=1)
    context_snippet = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["article", "entity"],
                name="uniq_article_entity",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity.name} in article {self.article_id}"


class ArticleTranslation(TimeStampedModel):
    """Persisted translation of an Article into a target language."""

    class TranslationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    language_code = models.CharField(max_length=10, db_index=True)
    translated_title = models.CharField(max_length=1000, blank=True)
    translated_body = models.TextField(blank=True)
    translation_status = models.CharField(
        max_length=16,
        choices=TranslationStatus.choices,
        default=TranslationStatus.PENDING,
    )
    translated_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["article", "language_code"],
                name="uniq_article_translation_lang",
            ),
        ]
        indexes = [
            models.Index(fields=["language_code"]),
            models.Index(fields=["translation_status"]),
        ]

    def __str__(self) -> str:
        return f"Translation ({self.language_code}) for article {self.article_id}"


class ArticleAISummary(TimeStampedModel):
    """AI-generated comprehensive summary and predictions for an article."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    article = models.OneToOneField(
        Article,
        on_delete=models.CASCADE,
        related_name="ai_summary",
    )
    summary = models.TextField(blank=True)
    predictions = models.TextField(blank=True)
    summary_ar = models.TextField(blank=True)
    predictions_ar = models.TextField(blank=True)
    model_used = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    generated_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"AI Summary for article {self.article_id}"
