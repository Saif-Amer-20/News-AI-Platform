from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from functools import wraps

from celery import shared_task
from django.core.cache import cache

from services.integrations.common import IntegrationError
from services.orchestration.ingest_orchestration import IngestOrchestrationService

logger = logging.getLogger(__name__)


# ── Redis-based distributed task lock ─────────────────────────────────────────

_LOCK_PREFIX = "celery:task_lock:"


@contextmanager
def _task_lock(task_name: str, timeout: int = 7200):
    """Acquire a Redis lock for a task.  Prevents overlapping runs.

    Usage:
        with _task_lock('my_task') as acquired:
            if not acquired:
                return  # another instance running
            do_work()
    """
    lock_key = f"{_LOCK_PREFIX}{task_name}"
    acquired = cache.add(lock_key, "1", timeout)
    try:
        yield acquired
    finally:
        if acquired:
            cache.delete(lock_key)


def _timed_task(func):
    """Decorator that logs task duration and entity count."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        task_name = func.__name__
        t0 = time.monotonic()
        logger.info("[PERF] %s STARTED", task_name)
        try:
            result = func(*args, **kwargs)
            elapsed = time.monotonic() - t0
            logger.info("[PERF] %s COMPLETED in %.1fs", task_name, elapsed)
            return result
        except Exception:
            elapsed = time.monotonic() - t0
            logger.error("[PERF] %s FAILED after %.1fs", task_name, elapsed, exc_info=True)
            raise
    return wrapper

# HTTP 4xx errors that should NOT be retried (they won't resolve)
_NO_RETRY_PATTERN = re.compile(r"\b(403|429|401|402)\b.*\b(Forbidden|Too Many|Unauthorized|Payment)\b", re.I)


def _is_client_error(exc: BaseException) -> bool:
    """Return True if the exception is a 4xx HTTP error that won't resolve on retry."""
    return bool(_NO_RETRY_PATTERN.search(str(exc)))


@shared_task(
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def fetch_source_task(self, source_id: int) -> dict:
    logger.info("Starting fetch_source_task for source_id=%s", source_id)
    try:
        run = IngestOrchestrationService().fetch_source(source_id=source_id, queue_follow_up=True)
        return {"source_id": source_id, "fetch_run_id": run.id, "status": run.status}
    except IntegrationError as exc:
        if _is_client_error(exc):
            logger.warning("fetch_source_task source_id=%s: non-retryable error: %s", source_id, exc)
            return {"source_id": source_id, "status": "failed", "error": str(exc)[:200]}
        raise


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
@_timed_task
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
@_timed_task
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
@_timed_task
def merge_duplicate_entities_task(self) -> None:
    """Scheduled by Celery Beat. Merges duplicate entities to canonical forms.
    Uses Redis lock to prevent overlapping runs."""
    with _task_lock("merge_duplicate_entities", timeout=3600) as acquired:
        if not acquired:
            logger.warning("merge_duplicate_entities_task: skipped — previous run still active")
            return

        from services.orchestration.entity_resolution_service import EntityResolutionService

        merged = EntityResolutionService().merge_duplicates(batch_size=200)
        logger.info("merge_duplicate_entities_task: merged %d entities", merged)


@shared_task(bind=True, ignore_result=True)
@_timed_task
def refresh_event_intelligence_task(self) -> None:
    """Scheduled by Celery Beat. Re-runs confidence, conflict, and geo-confidence
    scoring on recently updated events. Uses Redis lock."""
    with _task_lock("refresh_event_intelligence", timeout=3600) as acquired:
        if not acquired:
            logger.warning("refresh_event_intelligence_task: skipped — previous run still active")
            return

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
        events = Event.objects.filter(updated_at__gte=cutoff).order_by("-updated_at")[:50]
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
@_timed_task
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
@_timed_task
def run_anomaly_detection_task(self) -> None:
    """Scheduled by Celery Beat. Scans for anomaly signals.
    Uses Redis lock to prevent overlapping runs."""
    with _task_lock("anomaly_detection", timeout=1800) as acquired:
        if not acquired:
            logger.warning("run_anomaly_detection_task: skipped — previous run still active")
            return

        from services.anomaly_detection_service import run_anomaly_scan

        count = run_anomaly_scan()
        logger.info("run_anomaly_detection_task: %d new anomalies detected", count)


@shared_task(bind=True, ignore_result=True)
@_timed_task
def run_signal_correlation_task(self) -> None:
    """Scheduled by Celery Beat. Correlates signals. Uses Redis lock."""
    with _task_lock("signal_correlation", timeout=1800) as acquired:
        if not acquired:
            logger.warning("run_signal_correlation_task: skipped — previous run still active")
            return

        from services.signal_correlation_service import run_signal_correlation

        count = run_signal_correlation()
        logger.info("run_signal_correlation_task: %d correlations created", count)


@shared_task(bind=True, ignore_result=True)
@_timed_task
def run_predictive_scoring_task(self) -> None:
    """Scheduled by Celery Beat. Computes predictive scores. Uses Redis lock."""
    with _task_lock("predictive_scoring", timeout=1800) as acquired:
        if not acquired:
            logger.warning("run_predictive_scoring_task: skipped — previous run still active")
            return

        from services.predictive_scoring_service import score_recent_events

        scored = score_recent_events(hours=12, limit=50)
        logger.info("run_predictive_scoring_task: scored %d events", scored)


@shared_task(bind=True, ignore_result=True)
@_timed_task
def run_historical_pattern_matching_task(self) -> None:
    """Scheduled by Celery Beat. Matches current events against historical patterns."""
    from services.historical_pattern_service import match_patterns_recent

    matched = match_patterns_recent(hours=12, limit=50)
    logger.info("run_historical_pattern_matching_task: %d patterns matched", matched)


@shared_task(bind=True, ignore_result=True)
@_timed_task
def run_geo_radar_task(self) -> None:
    """Scheduled by Celery Beat. Updates geographic hot zones. Uses Redis lock."""
    with _task_lock("geo_radar", timeout=1800) as acquired:
        if not acquired:
            logger.warning("run_geo_radar_task: skipped — previous run still active")
            return

        from services.geo_radar_service import update_geo_radar

        zones = update_geo_radar()
        logger.info("run_geo_radar_task: %d zones updated", zones)


# ═══════════════════════════════════════════════════════════════
#  SELF-LEARNING INTELLIGENCE LAYER
# ═══════════════════════════════════════════════════════════════


@shared_task(bind=True, ignore_result=True)
@_timed_task
def auto_evaluate_predictions_task(self) -> None:
    """Scheduled by Celery Beat. Auto-evaluates pending prediction outcomes."""
    from services.outcome_tracking_service import auto_evaluate_predictions

    evaluated = auto_evaluate_predictions(hours=72)
    logger.info("auto_evaluate_predictions_task: %d outcomes evaluated", evaluated)


@shared_task(bind=True, ignore_result=True)
@_timed_task
def update_source_reputations_task(self) -> None:
    """Scheduled by Celery Beat. Recalculates source trust from feedback."""
    from services.source_reputation_service import update_source_reputations

    updated = update_source_reputations(days=30)
    logger.info("update_source_reputations_task: %d sources updated", updated)


@shared_task(bind=True, ignore_result=True)
@_timed_task
def run_adaptive_learning_cycle_task(self) -> None:
    """Scheduled by Celery Beat. Adjusts anomaly thresholds & weights."""
    from services.adaptive_scoring_service import run_adaptive_learning_cycle

    adjusted = run_adaptive_learning_cycle(days=30)
    logger.info("run_adaptive_learning_cycle_task: %d adjustments made", adjusted)


@shared_task(bind=True, ignore_result=True)
@_timed_task
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


# ═══════════════════════════════════════════════════════════════
#  AI-DRIVEN ENTITY CONSOLIDATION PIPELINE
# ═══════════════════════════════════════════════════════════════


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 2},
    ignore_result=True,
)
def consolidate_entities_for_article_task(self, article_id: int) -> None:
    """Per-article AI entity consolidation.

    Called immediately after entity extraction for each processed article.
    Runs lightweight: only examines entities extracted from this article and
    compares them against high-frequency existing canonical entities.

    Queued by IngestOrchestrationService.process_raw_item().
    """
    from services.orchestration.entity_consolidation_service import EntityConsolidationService

    stats = EntityConsolidationService().consolidate_article_entities(article_id)
    logger.info(
        "consolidate_entities_for_article_task article=%d  merged=%d  queued=%d  kept=%d",
        article_id, stats["auto_merged"], stats["queued_for_review"], stats["kept_separate"],
    )


@shared_task(bind=True, ignore_result=True)
@_timed_task
def background_entity_consolidation_task(self) -> None:
    """Periodic background entity consolidation sweep.

    Scheduled by Celery Beat every 2 hours.
    Uses Redis lock to prevent overlapping runs.
    Processes in batches of 50 to limit CPU.
    """
    with _task_lock("background_entity_consolidation", timeout=3600) as acquired:
        if not acquired:
            logger.warning("background_entity_consolidation_task: skipped — previous run still active")
            return

        from services.orchestration.entity_consolidation_service import EntityConsolidationService

        stats = EntityConsolidationService().background_sweep(max_entities=50)
        logger.info(
            "background_entity_consolidation_task: examined=%d merged=%d queued=%d kept=%d",
            stats["examined"], stats["auto_merged"],
            stats["queued_for_review"], stats["kept_separate"],
        )


# ═════════════════════════════════════════════════════════════════════════
# Entity Intelligence Layer Tasks
# ═════════════════════════════════════════════════════════════════════════


@shared_task(bind=True, ignore_result=True)
def build_entity_relationships_for_article_task(self, article_id: int) -> None:
    """Incrementally update entity relationships for a single article.

    Called from the ingestion pipeline immediately after entity extraction.
    Fast — only processes pairs from *this* article.
    """
    try:
        from sources.models import Article
        from services.orchestration.entity_relationship_service import EntityRelationshipService

        article = Article.objects.get(pk=article_id)
        EntityRelationshipService().incremental_update(article)
        logger.debug("build_entity_relationships_for_article_task: article=%s done", article_id)
    except Exception:
        logger.warning(
            "build_entity_relationships_for_article_task failed for article %s",
            article_id, exc_info=True,
        )


@shared_task(bind=True, ignore_result=True)
@_timed_task
def rebuild_entity_relationships_task(self, lookback_days: int = 90) -> None:
    """Full rebuild of the entity relationship graph.

    Scheduled by Celery Beat every 2 hours.
    Uses Redis lock to prevent overlapping runs.
    """
    with _task_lock("rebuild_entity_relationships", timeout=7200) as acquired:
        if not acquired:
            logger.warning("rebuild_entity_relationships_task: skipped — previous run still active")
            return

        from services.orchestration.entity_relationship_service import EntityRelationshipService

        stats = EntityRelationshipService().rebuild_relationships(lookback_days=lookback_days)
        logger.info(
            "rebuild_entity_relationships_task: created=%d updated=%d pruned=%d signals=%d",
            stats["created"], stats["updated"], stats["pruned"], stats["signals"],
        )


@shared_task(bind=True, ignore_result=True)
@_timed_task
def score_entity_intelligence_task(self) -> None:
    """Recompute entity influence scores and emit anomaly signals.

    Scheduled by Celery Beat every 1 hour.
    Uses Redis lock to prevent overlapping runs.
    """
    with _task_lock("score_entity_intelligence", timeout=3600) as acquired:
        if not acquired:
            logger.warning("score_entity_intelligence_task: skipped — previous run still active")
            return

        from services.orchestration.entity_intelligence_service import EntityIntelligenceService

        stats = EntityIntelligenceService().run_scoring()
        logger.info(
            "score_entity_intelligence_task: scored=%d spike_signals=%d growth_signals=%d",
            stats["scored"],
            stats["signals_mention_spike"],
            stats["signals_rapid_growth"],
        )
