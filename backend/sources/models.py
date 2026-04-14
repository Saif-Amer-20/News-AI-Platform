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


class EventIntelAssessment(TimeStampedModel):
    """Full intelligence assessment for an event: diffusion, cross-source
    comparison, credibility scoring, and probabilistic forecasts."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class VerificationStatus(models.TextChoices):
        VERIFIED = "verified", "Verified"
        LIKELY_TRUE = "likely_true", "Likely True"
        MIXED = "mixed", "Mixed / Conflicting"
        UNVERIFIED = "unverified", "Unverified"
        LIKELY_MISLEADING = "likely_misleading", "Likely Misleading"

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="intel_assessment",
    )

    # ── Story diffusion layer ─────────────────────────────────
    coverage_count = models.PositiveIntegerField(
        default=0, help_text="Total articles covering this event.",
    )
    distinct_source_count = models.PositiveIntegerField(
        default=0, help_text="Number of distinct sources.",
    )
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    source_list = models.JSONField(
        default=list, blank=True,
        help_text='[{"source_id":1,"name":"...","trust":0.7,"country":"US","articles":3,"first":"ISO","last":"ISO"}]',
    )
    article_links = models.JSONField(
        default=list, blank=True,
        help_text='[{"id":1,"title":"...","url":"...","source":"...","published_at":"ISO"}]',
    )
    publication_timeline = models.JSONField(
        default=list, blank=True,
        help_text='[{"ts":"ISO","source":"...","article_id":1,"title":"..."}]',
    )

    # ── Cross-source comparison layer ─────────────────────────
    claims = models.JSONField(
        default=list, blank=True,
        help_text='[{"claim":"...","sources":["src1"],"status":"agreed|contradicted|unique"}]',
    )
    agreements = models.JSONField(default=list, blank=True)
    contradictions = models.JSONField(default=list, blank=True)
    missing_details = models.JSONField(default=list, blank=True)
    late_emerging_claims = models.JSONField(default=list, blank=True)

    # ── AI assessment layer ───────────────────────────────────
    summary = models.TextField(blank=True, help_text="What happened.")
    source_agreement_summary = models.TextField(blank=True)
    contradiction_summary = models.TextField(blank=True)
    dominant_narrative = models.TextField(blank=True)
    uncertain_elements = models.TextField(blank=True)
    analyst_reasoning = models.TextField(blank=True)

    # ── Arabic translations ───────────────────────────────────
    summary_ar = models.TextField(blank=True)
    source_agreement_summary_ar = models.TextField(blank=True)
    contradiction_summary_ar = models.TextField(blank=True)
    dominant_narrative_ar = models.TextField(blank=True)
    uncertain_elements_ar = models.TextField(blank=True)
    analyst_reasoning_ar = models.TextField(blank=True)

    # ── Credibility layer ─────────────────────────────────────
    credibility_score = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text="0-1 composite credibility.",
    )
    confidence_score = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text="0-1 how confident we are in the credibility score.",
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    credibility_factors = models.JSONField(
        default=dict, blank=True,
        help_text="Breakdown of scoring factors.",
    )

    # ── Prediction / forecast layer ───────────────────────────
    escalation_probability = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
    )
    continuation_probability = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
    )
    hidden_link_probability = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
    )
    monitoring_recommendation = models.TextField(blank=True)
    forecast_signals = models.JSONField(
        default=dict, blank=True,
        help_text="Detailed forecast signals from LLM.",
    )

    # ── Meta ──────────────────────────────────────────────────
    model_used = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )
    generated_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["verification_status"]),
            models.Index(fields=["credibility_score"]),
        ]

    def __str__(self) -> str:
        return f"Intel Assessment for event {self.event_id}"


# ══════════════════════════════════════════════════════════════════════════════
# Early Warning & Predictive Intelligence Layer
# ══════════════════════════════════════════════════════════════════════════════


class AnomalyDetection(TimeStampedModel):
    """Detected anomaly signals: volume spikes, source diversity, entity
    surges, geographic shifts, narrative breaks."""

    class AnomalyType(models.TextChoices):
        VOLUME_SPIKE = "volume_spike", "Volume Spike"
        SOURCE_DIVERSITY = "source_diversity", "Source Diversity Change"
        ENTITY_SURGE = "entity_surge", "Entity Mention Surge"
        LOCATION_SURGE = "location_surge", "Location Activity Surge"
        NARRATIVE_SHIFT = "narrative_shift", "Narrative Shift"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        DISMISSED = "dismissed", "Dismissed"
        EXPIRED = "expired", "Expired"

    anomaly_type = models.CharField(max_length=24, choices=AnomalyType.choices)
    severity = models.CharField(max_length=12, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)

    # Metrics
    metric_name = models.CharField(max_length=120, blank=True)
    baseline_value = models.FloatField(default=0)
    current_value = models.FloatField(default=0)
    deviation_factor = models.FloatField(
        default=0, help_text="How many standard deviations above baseline.",
    )
    confidence = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.50"))

    # Links
    event = models.ForeignKey(
        Event, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="anomalies",
    )
    entity = models.ForeignKey(
        Entity, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="anomalies",
    )
    location_country = models.CharField(max_length=4, blank=True)
    location_name = models.CharField(max_length=255, blank=True)

    # Evidence
    evidence = models.JSONField(
        default=dict, blank=True,
        help_text="Supporting data points, time-series, related article IDs.",
    )
    related_event_ids = models.JSONField(default=list, blank=True)
    related_entity_ids = models.JSONField(default=list, blank=True)

    detected_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["anomaly_type", "severity"]),
            models.Index(fields=["status"]),
            models.Index(fields=["detected_at"]),
            models.Index(fields=["location_country"]),
        ]
        ordering = ["-detected_at"]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.anomaly_type}: {self.title}"


class SignalCorrelation(TimeStampedModel):
    """Cross-dimensional signal correlation linking weak signals across
    events, entities, locations, and time windows."""

    class CorrelationType(models.TextChoices):
        CROSS_EVENT = "cross_event", "Cross-Event"
        CROSS_ENTITY = "cross_entity", "Cross-Entity"
        CROSS_LOCATION = "cross_location", "Cross-Location"
        TEMPORAL = "temporal", "Temporal Proximity"
        SOURCE_PATTERN = "source_pattern", "Source Pattern"

    class Strength(models.TextChoices):
        WEAK = "weak", "Weak"
        MODERATE = "moderate", "Moderate"
        STRONG = "strong", "Strong"

    correlation_type = models.CharField(max_length=20, choices=CorrelationType.choices)
    strength = models.CharField(max_length=12, choices=Strength.choices, default=Strength.WEAK)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    correlation_score = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
    )

    # Linked objects
    event_a = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="correlations_as_a",
        null=True, blank=True,
    )
    event_b = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="correlations_as_b",
        null=True, blank=True,
    )
    entity_ids = models.JSONField(default=list, blank=True)
    anomaly_ids = models.JSONField(default=list, blank=True)

    # Reasoning
    reasoning = models.TextField(blank=True, help_text="Explainable reasoning for this correlation.")
    evidence = models.JSONField(default=dict, blank=True)
    supporting_signals = models.JSONField(
        default=list, blank=True,
        help_text='[{"signal_type": "...", "detail": "...", "weight": 0.3}]',
    )

    detected_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["correlation_type"]),
            models.Index(fields=["strength"]),
            models.Index(fields=["detected_at"]),
        ]
        ordering = ["-correlation_score", "-detected_at"]

    def __str__(self) -> str:
        return f"[{self.strength}] {self.correlation_type}: {self.title}"


class PredictiveScore(TimeStampedModel):
    """Probabilistic scores per event: escalation, continuation,
    misleading-signal, and monitoring priority."""

    event = models.OneToOneField(
        Event, on_delete=models.CASCADE, related_name="predictive_score",
    )

    escalation_probability = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text="0-1: Will the situation escalate within 48h?",
    )
    continuation_probability = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text="0-1: Will the event continue developing?",
    )
    misleading_probability = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text="0-1: Probability of misleading / disinformation signal.",
    )
    monitoring_priority = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
        help_text="0-1: Composite priority score.",
    )

    # Factor breakdown
    anomaly_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    correlation_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    historical_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    source_diversity_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    velocity_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))

    # Explanations
    reasoning = models.TextField(blank=True)
    reasoning_ar = models.TextField(blank=True)
    risk_trend = models.CharField(
        max_length=16, blank=True,
        help_text="rising | stable | declining",
    )
    weak_signals = models.JSONField(
        default=list, blank=True,
        help_text='[{"signal": "...", "weight": 0.2, "source": "anomaly|correlation|pattern"}]',
    )

    model_used = models.CharField(max_length=64, blank=True)
    scored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["monitoring_priority"]),
            models.Index(fields=["escalation_probability"]),
        ]

    def __str__(self) -> str:
        return f"Predictive Score for event {self.event_id}"


class HistoricalPattern(TimeStampedModel):
    """Matched historical pattern — how current events compare to past
    event signatures and what outcomes followed."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name="historical_patterns",
    )
    matched_event = models.ForeignKey(
        Event, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="matched_as_pattern",
        help_text="The historical event this pattern is compared against.",
    )

    pattern_name = models.CharField(max_length=300, blank=True)
    similarity_score = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("0.00"),
    )
    matching_dimensions = models.JSONField(
        default=list, blank=True,
        help_text='["event_type", "location", "entity_overlap", "source_pattern"]',
    )
    historical_outcome = models.TextField(
        blank=True, help_text="What happened after the historical event.",
    )
    predicted_trajectory = models.TextField(
        blank=True, help_text="Projected trajectory based on pattern.",
    )
    predicted_trajectory_ar = models.TextField(blank=True)
    confidence = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        indexes = [
            models.Index(fields=["similarity_score"]),
        ]
        ordering = ["-similarity_score"]

    def __str__(self) -> str:
        return f"Pattern match ({self.similarity_score}) for event {self.event_id}"


class GeoRadarZone(TimeStampedModel):
    """Hot zone detected by the geo-radar — geographic concentrations of
    events with anomalous activity."""

    class ZoneStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        COOLING = "cooling", "Cooling Down"
        EXPIRED = "expired", "Expired"

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)

    # Center point
    center_lat = models.DecimalField(max_digits=9, decimal_places=6)
    center_lon = models.DecimalField(max_digits=9, decimal_places=6)
    radius_km = models.FloatField(default=50, help_text="Radius in km.")
    location_country = models.CharField(max_length=4, blank=True)
    location_name = models.CharField(max_length=255, blank=True)

    # Metrics
    event_count = models.PositiveIntegerField(default=0)
    event_concentration = models.FloatField(
        default=0, help_text="Events per 100km².",
    )
    avg_severity = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    anomaly_count = models.PositiveIntegerField(default=0)
    temporal_trend = models.CharField(
        max_length=16, blank=True,
        help_text="intensifying | stable | subsiding",
    )

    # Related
    event_ids = models.JSONField(default=list, blank=True)
    anomaly_ids = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=12, choices=ZoneStatus.choices, default=ZoneStatus.ACTIVE,
    )
    first_detected_at = models.DateTimeField(default=timezone.now)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["event_concentration"]),
            models.Index(fields=["location_country"]),
        ]
        ordering = ["-event_concentration"]

    def __str__(self) -> str:
        return f"GeoRadar: {self.title} ({self.event_count} events)"


# ═══════════════════════════════════════════════════════════════
#  SELF-LEARNING INTELLIGENCE LAYER
# ═══════════════════════════════════════════════════════════════


class AnalystFeedback(TimeStampedModel):
    """Structured analyst feedback for alerts, events, predictions, cases."""

    class TargetType(models.TextChoices):
        ALERT = "alert", "Alert"
        EVENT = "event", "Event"
        PREDICTION = "prediction", "Prediction"
        CASE = "case", "Case"
        ANOMALY = "anomaly", "Anomaly"

    class FeedbackType(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        FALSE_POSITIVE = "false_positive", "False Positive"
        MISLEADING = "misleading", "Misleading"
        USEFUL = "useful", "Useful"
        ESCALATED_CORRECTLY = "escalated_correctly", "Escalated Correctly"
        DISMISSED_CORRECTLY = "dismissed_correctly", "Dismissed Correctly"

    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    target_id = models.PositiveIntegerField()
    feedback_type = models.CharField(max_length=24, choices=FeedbackType.choices)
    comment = models.TextField(blank=True, default="")
    analyst = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analyst_feedbacks",
    )
    confidence = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.00"),
        help_text="Analyst confidence in the feedback (0-1).",
    )
    context_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Snapshot of scores/metrics at feedback time for audit.",
    )

    class Meta:
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["feedback_type"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.feedback_type} on {self.target_type}#{self.target_id}"


class OutcomeRecord(TimeStampedModel):
    """Tracks expected vs actual outcomes for predictions/early warnings."""

    class AccuracyStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCURATE = "accurate", "Accurate"
        PARTIALLY_ACCURATE = "partially_accurate", "Partially Accurate"
        INACCURATE = "inaccurate", "Inaccurate"
        INDETERMINATE = "indeterminate", "Indeterminate"

    target_type = models.CharField(max_length=16, choices=AnalystFeedback.TargetType.choices)
    target_id = models.PositiveIntegerField()
    expected_outcome = models.TextField(blank=True, default="")
    actual_outcome = models.TextField(blank=True, default="")
    accuracy_status = models.CharField(
        max_length=24, choices=AccuracyStatus.choices, default=AccuracyStatus.PENDING,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True, default="")
    prediction_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Original prediction scores at prediction time.",
    )
    outcome_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Metric values at resolution time.",
    )

    class Meta:
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["accuracy_status"]),
            models.Index(fields=["resolved_at"]),
        ]
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_id"],
                name="unique_outcome_per_target",
            ),
        ]

    def __str__(self) -> str:
        return f"Outcome {self.accuracy_status} for {self.target_type}#{self.target_id}"


class SourceReputationLog(TimeStampedModel):
    """Audit log for source trust_score changes driven by learning."""

    class ChangeReason(models.TextChoices):
        FALSE_POSITIVE = "false_positive", "False Positive Contribution"
        USEFUL_SIGNAL = "useful_signal", "Useful Signal Contribution"
        CONSISTENCY = "consistency", "Consistency Check"
        HISTORICAL_PRECISION = "historical_precision", "Historical Precision"
        MANUAL_OVERRIDE = "manual_override", "Manual Override"
        PERIODIC_RECALC = "periodic_recalc", "Periodic Recalculation"

    source = models.ForeignKey(
        "sources.Source", on_delete=models.CASCADE, related_name="reputation_logs",
    )
    previous_trust = models.DecimalField(max_digits=4, decimal_places=2)
    new_trust = models.DecimalField(max_digits=4, decimal_places=2)
    change_delta = models.DecimalField(max_digits=5, decimal_places=3)
    reason = models.CharField(max_length=32, choices=ChangeReason.choices)
    evidence = models.JSONField(
        default=dict, blank=True,
        help_text="Data supporting the trust change.",
    )
    is_rollback = models.BooleanField(default=False)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rolled_back_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        indexes = [
            models.Index(fields=["source", "-created_at"]),
            models.Index(fields=["reason"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Source {self.source_id} trust: {self.previous_trust}→{self.new_trust} ({self.reason})"


class AdaptiveThreshold(TimeStampedModel):
    """Stores learned thresholds and weights — auditable, rollback-able."""

    class ParamType(models.TextChoices):
        ANOMALY_THRESHOLD = "anomaly_threshold", "Anomaly Threshold"
        PREDICTIVE_WEIGHT = "predictive_weight", "Predictive Weight"
        SOURCE_TRUST_WEIGHT = "source_trust_weight", "Source Trust Weight"
        ESCALATION_SENSITIVITY = "escalation_sensitivity", "Escalation Sensitivity"

    param_name = models.CharField(
        max_length=120, unique=True,
        help_text="Unique key, e.g. 'anomaly.volume_spike_threshold'.",
    )
    param_type = models.CharField(max_length=32, choices=ParamType.choices)
    current_value = models.DecimalField(max_digits=8, decimal_places=4)
    previous_value = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    default_value = models.DecimalField(max_digits=8, decimal_places=4)
    min_value = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("0.0"))
    max_value = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("10.0"))
    adjustment_reason = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["param_type"]),
            models.Index(fields=["param_name"]),
        ]
        ordering = ["param_name"]

    def __str__(self) -> str:
        return f"{self.param_name}={self.current_value} (v{self.version})"


class LearningRecord(TimeStampedModel):
    """Training/evaluation data store — features, scores, feedback, outcomes."""

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, null=True, blank=True,
        related_name="learning_records",
    )
    record_type = models.CharField(
        max_length=32,
        help_text="E.g. prediction_evaluation, anomaly_evaluation, feedback_record.",
    )
    features = models.JSONField(
        default=dict, blank=True,
        help_text="Event features: type, source_count, importance, etc.",
    )
    prediction_scores = models.JSONField(
        default=dict, blank=True,
        help_text="Prediction scores at evaluation time.",
    )
    anomaly_metrics = models.JSONField(
        default=dict, blank=True,
        help_text="Anomaly detection metrics at evaluation time.",
    )
    feedback_summary = models.JSONField(
        default=dict, blank=True,
        help_text="Analyst feedback aggregation.",
    )
    outcome = models.JSONField(
        default=dict, blank=True,
        help_text="Final outcome data from OutcomeRecord.",
    )
    accuracy_label = models.CharField(
        max_length=24, blank=True, default="",
        help_text="Ground truth label: accurate, inaccurate, etc.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["record_type"]),
            models.Index(fields=["accuracy_label"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"LearningRecord({self.record_type}) event={self.event_id}"
