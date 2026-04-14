from __future__ import annotations

import logging

from celery import shared_task

from services.integrations.common import IntegrationError
from services.orchestration.ingest_orchestration import IngestOrchestrationService

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(IntegrationError, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def fetch_source_task(self, source_id: int) -> dict:
    logger.info("Starting fetch_source_task for source_id=%s", source_id)
    run = IngestOrchestrationService().fetch_source(source_id=source_id, queue_follow_up=True)
    return {"source_id": source_id, "fetch_run_id": run.id, "status": run.status}


@shared_task(
    bind=True,
    autoretry_for=(IntegrationError, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def process_raw_item_task(self, raw_item_id: int) -> dict:
    logger.info("Starting process_raw_item_task for raw_item_id=%s", raw_item_id)
    article = IngestOrchestrationService().process_raw_item(raw_item_id)
    return {"raw_item_id": raw_item_id, "article_id": article.id if article else None}


@shared_task(
    bind=True,
    autoretry_for=(IntegrationError, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def parse_raw_item_task(self, raw_item_id: int) -> dict:
    logger.info("Starting parse_raw_item_task for raw_item_id=%s", raw_item_id)
    candidate = IngestOrchestrationService().parse_raw_item(raw_item_id)
    return {"raw_item_id": raw_item_id, "candidate_id": candidate.id}


@shared_task(
    bind=True,
    autoretry_for=(IntegrationError, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def normalize_raw_item_task(self, raw_item_id: int) -> dict:
    logger.info("Starting normalize_raw_item_task for raw_item_id=%s", raw_item_id)
    article = IngestOrchestrationService().normalize_raw_item(raw_item_id)
    return {"raw_item_id": raw_item_id, "article_id": article.id if article else None}


# ── Periodic: dispatch fetch tasks for all active sources ─────────────────────


@shared_task(bind=True, ignore_result=True)
def dispatch_active_source_fetches(self) -> None:
    """Scheduled by Celery Beat. Enqueues a fetch_source_task for each active source
    whose fetch interval has elapsed."""
    from django.utils import timezone

    from sources.models import Source

    now = timezone.now()
    active_sources = Source.objects.filter(
        is_active=True,
        status=Source.Status.ACTIVE,
    )
    dispatched = 0
    for source in active_sources:
        interval_minutes = source.effective_fetch_interval()
        if source.last_checked_at:
            elapsed = (now - source.last_checked_at).total_seconds() / 60
            if elapsed < interval_minutes:
                continue
        fetch_source_task.delay(source.id)
        dispatched += 1

    logger.info("dispatch_active_source_fetches: queued %d sources", dispatched)


@shared_task(bind=True, ignore_result=True)
def update_source_reliability_task(self) -> None:
    """Scheduled by Celery Beat. Recalculates trust_score for all active sources."""
    from services.orchestration.source_reliability_service import SourceReliabilityService

    count = SourceReliabilityService().update_all_sources()
    logger.info("update_source_reliability_task: updated %d sources", count)


@shared_task(bind=True, ignore_result=True)
def resolve_orphan_events_task(self) -> None:
    """Scheduled by Celery Beat. Resolves events for stories that lack one."""
    from services.orchestration.event_resolution_service import EventResolutionService
    from sources.models import Story

    service = EventResolutionService()
    orphans = Story.objects.filter(event__isnull=True, article_count__gt=0)
    resolved = 0
    for story in orphans[:200]:
        service.resolve_event(story)
        resolved += 1
    logger.info("resolve_orphan_events_task: resolved %d stories", resolved)


@shared_task(bind=True, ignore_result=True)
def merge_duplicate_entities_task(self) -> None:
    """Scheduled by Celery Beat. Merges duplicate entities to canonical forms."""
    from services.orchestration.entity_resolution_service import EntityResolutionService

    merged = EntityResolutionService().merge_duplicates(batch_size=500)
    logger.info("merge_duplicate_entities_task: merged %d entities", merged)


@shared_task(bind=True, ignore_result=True)
def refresh_event_intelligence_task(self) -> None:
    """Scheduled by Celery Beat. Re-runs confidence, conflict, and geo-confidence
    scoring on recently updated events."""
    from services.orchestration.event_confidence_service import EventConfidenceService
    from services.orchestration.geo_confidence_service import GeoConfidenceService
    from services.orchestration.multi_source_correlation_service import MultiSourceCorrelationService
    from services.orchestration.narrative_conflict_service import NarrativeConflictService
    from sources.models import Event

    confidence_svc = EventConfidenceService()
    conflict_svc = NarrativeConflictService()
    geo_svc = GeoConfidenceService()
    correlation_svc = MultiSourceCorrelationService()

    from django.utils import timezone
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(hours=6)
    events = Event.objects.filter(updated_at__gte=cutoff).order_by("-updated_at")[:100]
    refreshed = 0
    for event in events:
        correlation_svc.correlate(event)
        confidence_svc.score_event(event)
        geo_svc.score(event)
        conflict_svc.detect(event)
        refreshed += 1

    logger.info("refresh_event_intelligence_task: refreshed %d events", refreshed)


# ── OpenSearch & Neo4j bootstrap / reindex ────────────────────────────────────


@shared_task(bind=True, ignore_result=True)
def bootstrap_search_indices_task(self) -> None:
    """One-shot: ensure OpenSearch index mappings exist."""
    from services.orchestration.indexing_orchestration import IndexingOrchestrationService

    IndexingOrchestrationService().ensure_indices()
    logger.info("bootstrap_search_indices_task: indices ensured")


@shared_task(bind=True, ignore_result=True)
def bootstrap_graph_schema_task(self) -> None:
    """One-shot: ensure Neo4j constraints / indexes exist."""
    from services.orchestration.graph_write_orchestration import GraphWriteOrchestrationService

    GraphWriteOrchestrationService().ensure_schema()
    logger.info("bootstrap_graph_schema_task: graph schema ensured")


@shared_task(bind=True, ignore_result=True)
def reindex_articles_task(self) -> None:
    """Bulk-reindex all articles into OpenSearch and Neo4j."""
    from services.orchestration.graph_write_orchestration import GraphWriteOrchestrationService
    from services.orchestration.indexing_orchestration import IndexingOrchestrationService
    from sources.models import Article

    search_svc = IndexingOrchestrationService()
    graph_svc = GraphWriteOrchestrationService()

    search_svc.ensure_indices()
    graph_svc.ensure_schema()

    qs = Article.objects.select_related("source", "story", "story__event").order_by("id")
    total = 0
    for article in qs.iterator(chunk_size=200):
        search_svc.index_article(article)
        graph_svc.write_article_graph(article)
        total += 1

    logger.info("reindex_articles_task: reindexed %d articles", total)


@shared_task(bind=True, ignore_result=True)
def generate_intel_assessments_task(self) -> None:
    """Scheduled by Celery Beat. Generates intelligence assessments for
    recent events that don't have one yet or whose assessment is stale."""
    from datetime import timedelta

    from django.utils import timezone

    from services.intel_assessment_service import generate_intel_assessment
    from sources.models import Event, EventIntelAssessment

    cutoff = timezone.now() - timedelta(hours=12)
    events = (
        Event.objects.filter(updated_at__gte=cutoff, source_count__gte=2)
        .order_by("-importance_score")[:30]
    )
    generated = 0
    for event in events:
        existing = EventIntelAssessment.objects.filter(
            event=event, status=EventIntelAssessment.Status.COMPLETED,
        ).first()
        if existing and existing.generated_at and existing.generated_at >= cutoff:
            continue  # already fresh
        generate_intel_assessment(event)
        generated += 1

    logger.info("generate_intel_assessments_task: processed %d events", generated)


# ── Early Warning & Predictive Intelligence Tasks ─────────────────────────────


@shared_task(bind=True, ignore_result=True)
def run_anomaly_detection_task(self) -> None:
    """Scheduled by Celery Beat. Scans for anomaly signals across all
    dimensions: volume, source diversity, entity, location, narrative."""
    from services.anomaly_detection_service import run_anomaly_scan

    count = run_anomaly_scan()
    logger.info("run_anomaly_detection_task: %d new anomalies detected", count)


@shared_task(bind=True, ignore_result=True)
def run_signal_correlation_task(self) -> None:
    """Scheduled by Celery Beat. Correlates signals across events,
    entities, locations, and time windows."""
    from services.signal_correlation_service import run_signal_correlation

    count = run_signal_correlation()
    logger.info("run_signal_correlation_task: %d correlations created", count)


@shared_task(bind=True, ignore_result=True)
def run_predictive_scoring_task(self) -> None:
    """Scheduled by Celery Beat. Computes predictive scores for recent events."""
    from services.predictive_scoring_service import score_recent_events

    scored = score_recent_events(hours=12, limit=100)
    logger.info("run_predictive_scoring_task: scored %d events", scored)


@shared_task(bind=True, ignore_result=True)
def run_historical_pattern_matching_task(self) -> None:
    """Scheduled by Celery Beat. Matches current events against historical patterns."""
    from services.historical_pattern_service import match_patterns_recent

    matched = match_patterns_recent(hours=12, limit=50)
    logger.info("run_historical_pattern_matching_task: %d patterns matched", matched)


@shared_task(bind=True, ignore_result=True)
def run_geo_radar_task(self) -> None:
    """Scheduled by Celery Beat. Updates geographic hot zones."""
    from services.geo_radar_service import update_geo_radar

    zones = update_geo_radar()
    logger.info("run_geo_radar_task: %d zones updated", zones)


# ═══════════════════════════════════════════════════════════════
#  SELF-LEARNING INTELLIGENCE LAYER
# ═══════════════════════════════════════════════════════════════


@shared_task(bind=True, ignore_result=True)
def auto_evaluate_predictions_task(self) -> None:
    """Scheduled by Celery Beat. Auto-evaluates pending prediction outcomes."""
    from services.outcome_tracking_service import auto_evaluate_predictions

    evaluated = auto_evaluate_predictions(hours=72)
    logger.info("auto_evaluate_predictions_task: %d outcomes evaluated", evaluated)


@shared_task(bind=True, ignore_result=True)
def update_source_reputations_task(self) -> None:
    """Scheduled by Celery Beat. Recalculates source trust from feedback."""
    from services.source_reputation_service import update_source_reputations

    updated = update_source_reputations(days=30)
    logger.info("update_source_reputations_task: %d sources updated", updated)


@shared_task(bind=True, ignore_result=True)
def run_adaptive_learning_cycle_task(self) -> None:
    """Scheduled by Celery Beat. Adjusts anomaly thresholds & weights."""
    from services.adaptive_scoring_service import run_adaptive_learning_cycle

    adjusted = run_adaptive_learning_cycle(days=30)
    logger.info("run_adaptive_learning_cycle_task: %d adjustments made", adjusted)


@shared_task(bind=True, ignore_result=True)
def capture_learning_records_task(self) -> None:
    """Scheduled by Celery Beat. Snapshots scored events into learning store."""
    from services.learning_data_service import capture_learning_records

    captured = capture_learning_records(hours=24, limit=100)
    logger.info("capture_learning_records_task: %d records captured", captured)


@shared_task(bind=True, ignore_result=True)
def bootstrap_adaptive_thresholds_task(self) -> None:
    """Scheduled by Celery Beat. Ensures all default thresholds exist."""
    from services.adaptive_scoring_service import bootstrap_adaptive_thresholds

    created = bootstrap_adaptive_thresholds()
    logger.info("bootstrap_adaptive_thresholds_task: %d thresholds bootstrapped", created)
