"""Custom Prometheus metrics for the News Intelligence Platform.

Provides application-level metrics beyond what django-prometheus gives
out of the box. Import and use in views/tasks/services.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

# ═══════════════════════════════════════════════════════════════════════════════
# INGESTION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

articles_ingested_total = Counter(
    "newsintel_articles_ingested_total",
    "Total articles ingested",
    ["source_type", "source_name"],
)

articles_deduplicated_total = Counter(
    "newsintel_articles_deduplicated_total",
    "Articles identified as duplicates",
)

stories_created_total = Counter(
    "newsintel_stories_created_total",
    "Stories created by clustering",
)

events_created_total = Counter(
    "newsintel_events_created_total",
    "Events created",
    ["event_type"],
)

entities_extracted_total = Counter(
    "newsintel_entities_extracted_total",
    "Entities extracted from articles",
    ["entity_type"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY & INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════════

quality_score_histogram = Histogram(
    "newsintel_article_quality_score",
    "Distribution of article quality scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

importance_score_histogram = Histogram(
    "newsintel_article_importance_score",
    "Distribution of article importance scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

confidence_score_histogram = Histogram(
    "newsintel_event_confidence_score",
    "Distribution of event confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# ═══════════════════════════════════════════════════════════════════════════════
# ALERTS
# ═══════════════════════════════════════════════════════════════════════════════

alerts_triggered_total = Counter(
    "newsintel_alerts_triggered_total",
    "Total alerts triggered",
    ["alert_type", "severity"],
)

alerts_open_gauge = Gauge(
    "newsintel_alerts_open",
    "Currently open alerts",
    ["severity"],
)

alert_response_time_seconds = Histogram(
    "newsintel_alert_response_time_seconds",
    "Time from trigger to acknowledgement",
    buckets=[60, 300, 600, 1800, 3600, 7200, 14400, 28800, 86400],
)

# ═══════════════════════════════════════════════════════════════════════════════
# EXTERNAL SERVICES
# ═══════════════════════════════════════════════════════════════════════════════

external_request_duration = Histogram(
    "newsintel_external_request_duration_seconds",
    "Duration of external service requests",
    ["service", "operation"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

external_request_errors_total = Counter(
    "newsintel_external_request_errors_total",
    "Total external service request errors",
    ["service", "operation"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

source_fetch_duration = Histogram(
    "newsintel_source_fetch_duration_seconds",
    "Duration of source fetch operations",
    ["source_type"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

source_fetch_errors_total = Counter(
    "newsintel_source_fetch_errors_total",
    "Total source fetch errors",
    ["source_type", "error_type"],
)

active_sources_gauge = Gauge(
    "newsintel_active_sources",
    "Number of active sources",
    ["source_type"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# CASES
# ═══════════════════════════════════════════════════════════════════════════════

cases_open_gauge = Gauge(
    "newsintel_cases_open",
    "Currently open cases",
    ["priority"],
)

cases_created_total = Counter(
    "newsintel_cases_created_total",
    "Total cases created",
)

# ═══════════════════════════════════════════════════════════════════════════════
# PLATFORM INFO
# ═══════════════════════════════════════════════════════════════════════════════

platform_info = Info(
    "newsintel_platform",
    "Platform build information",
)
