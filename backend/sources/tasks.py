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
