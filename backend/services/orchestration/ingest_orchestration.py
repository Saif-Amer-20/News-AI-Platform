from __future__ import annotations

import logging

from django.db import models
from django.utils import timezone

from services.integrations.common import IntegrationError
from sources.models import (
    Article,
    ParsedArticleCandidate,
    RawItem,
    Source,
    SourceFetchError,
    SourceFetchRun,
    SourceHealthEvent,
)

from .alert_evaluation_orchestration import AlertEvaluationOrchestrationService
from .article_parse_service import ArticleParseService
from .dedup_orchestration import DedupOrchestrationService
from .entity_extraction_service import EntityExtractionService
from .event_resolution_service import EventResolutionService
from .graph_write_orchestration import GraphWriteOrchestrationService
from .importance_scoring_service import ImportanceScoringService
from .indexing_orchestration import IndexingOrchestrationService
from .normalize_orchestration import NormalizeOrchestrationService
from .quality_filter_service import QualityFilterService
from .raw_item_service import RawItemService
from .source_fetch_service import SourceFetchService
from .source_reliability_service import SourceReliabilityService
from .story_clustering_orchestration import StoryClusteringOrchestrationService
from .topic_matching_orchestration import TopicMatchingOrchestrationService

logger = logging.getLogger(__name__)


class IngestOrchestrationService:
    def __init__(self):
        self.source_fetch_service = SourceFetchService()
        self.raw_item_service = RawItemService()
        self.article_parse_service = ArticleParseService()
        self.normalize_orchestration = NormalizeOrchestrationService()
        self.quality_filter = QualityFilterService()
        self.topic_matching_orchestration = TopicMatchingOrchestrationService()
        self.dedup_orchestration = DedupOrchestrationService()
        self.entity_extraction = EntityExtractionService()
        self.story_clustering_orchestration = StoryClusteringOrchestrationService()
        self.event_resolution = EventResolutionService()
        self.importance_scoring = ImportanceScoringService()
        self.source_reliability = SourceReliabilityService()
        self.indexing_orchestration = IndexingOrchestrationService()
        self.graph_write_orchestration = GraphWriteOrchestrationService()
        self.alert_evaluation_orchestration = AlertEvaluationOrchestrationService()

    def fetch_source(self, *, source_id: int, queue_follow_up: bool = True) -> SourceFetchRun:
        source = Source.objects.get(pk=source_id)
        fetch_run = SourceFetchRun.objects.create(source=source, status=SourceFetchRun.Status.RUNNING)

        if not source.is_active or source.status != Source.Status.ACTIVE:
            fetch_run.status = SourceFetchRun.Status.FAILED
            fetch_run.finished_at = timezone.now()
            fetch_run.detail = {"message": "Source is inactive or paused."}
            fetch_run.save(update_fields=["status", "finished_at", "detail", "updated_at"])
            return fetch_run

        # Fetch over HTTP — outside DB transaction to avoid long locks
        try:
            raw_results = self.source_fetch_service.fetch_source(source)
        except Exception as exc:
            logger.exception("Source fetch failed for source_id=%s", source.id)
            fetch_run.status = SourceFetchRun.Status.FAILED
            fetch_run.finished_at = timezone.now()
            fetch_run.detail = {"error": str(exc)[:2000]}
            fetch_run.save(update_fields=["status", "finished_at", "detail", "updated_at"])
            SourceFetchError.objects.create(
                source=source, fetch_run=fetch_run, url=source.fetch_url, error=str(exc)[:2000],
            )
            SourceHealthEvent.objects.create(
                source=source,
                health_status=Source.HealthStatus.FAILING,
                detail=str(exc)[:2000],
                payload={"fetch_run_id": fetch_run.id},
            )
            raise IntegrationError(str(exc)) from exc

        # Persist results inside a transaction
        try:
            raw_items = self.raw_item_service.persist_fetch_results(
                source=source,
                fetch_run=fetch_run,
                raw_results=raw_results,
            )

            fetch_run.items_fetched = len(raw_results)
            fetch_run.items_created = len(raw_items)
            fetch_run.status = (
                SourceFetchRun.Status.COMPLETED if raw_items else SourceFetchRun.Status.PARTIAL
            )
            fetch_run.finished_at = timezone.now()
            fetch_run.detail = {"queued_follow_up": queue_follow_up}
            fetch_run.save(
                update_fields=[
                    "items_fetched",
                    "items_created",
                    "status",
                    "finished_at",
                    "detail",
                    "updated_at",
                ]
            )

            SourceHealthEvent.objects.create(
                source=source,
                health_status=Source.HealthStatus.HEALTHY,
                detail=f"Fetched {len(raw_items)} raw items.",
                payload={"fetch_run_id": fetch_run.id},
            )

            if queue_follow_up:
                from sources.tasks import process_raw_item_task

                for raw_item in raw_items:
                    process_raw_item_task.delay(raw_item.id)
            return fetch_run
        except Exception as exc:
            logger.exception("Source fetch failed for source_id=%s", source.id)
            fetch_run.status = SourceFetchRun.Status.FAILED
            fetch_run.finished_at = timezone.now()
            fetch_run.detail = {"error": str(exc)}
            fetch_run.save(update_fields=["status", "finished_at", "detail", "updated_at"])
            SourceFetchError.objects.create(
                source=source,
                fetch_run=fetch_run,
                url=source.fetch_url,
                error=str(exc),
            )
            SourceHealthEvent.objects.create(
                source=source,
                health_status=Source.HealthStatus.FAILING,
                detail=str(exc),
                payload={"fetch_run_id": fetch_run.id},
            )
            raise IntegrationError(str(exc)) from exc

    def parse_raw_item(self, raw_item_id: int) -> ParsedArticleCandidate:
        raw_item = RawItem.objects.select_related("source").get(pk=raw_item_id)
        return self.article_parse_service.parse(raw_item)

    def normalize_raw_item(self, raw_item_id: int):
        raw_item = RawItem.objects.select_related("source").get(pk=raw_item_id)
        parsed_candidate = self.parse_raw_item(raw_item_id)
        normalized = self.normalize_orchestration.normalize(raw_item, parsed_candidate)
        normalized["content_hash"] = self.raw_item_service.content_hash_for_article(
            normalized["title"],
            normalized["content"],
        )

        # ── Quality filter ──────────────────────────────────────
        quality_result = self.quality_filter.evaluate(normalized)
        normalized["quality_score"] = quality_result["quality_score"]

        if not quality_result["quality_passed"]:
            logger.info(
                "RawItem %s rejected by quality filter (score=%.2f)",
                raw_item_id,
                quality_result["quality_score"],
            )
            raw_item.status = RawItem.Status.FAILED
            raw_item.error_message = f"Quality filter rejected (score={quality_result['quality_score']})"
            raw_item.save(update_fields=["status", "error_message", "updated_at"])
            # Update source low-quality count
            Source.objects.filter(pk=raw_item.source_id).update(
                total_low_quality=models.F("total_low_quality") + 1
            )
            return None

        article = self.raw_item_service.create_or_update_article(
            raw_item=raw_item,
            parsed_candidate=parsed_candidate,
            normalized=normalized,
        )
        return article

    def process_raw_item(self, raw_item_id: int):
        """
        Full intelligence pipeline:
        RawItem → Parse → Normalize → Quality Filter → Article
               → Dedup → Entity Extraction → Cluster
               → Event Resolution → Confidence → Score
               → Index → Graph → Alert

        The Confidence step (inside event resolution) runs:
        - Temporal evolution tracking
        - Multi-source correlation
        - Event confidence scoring
        - Geo confidence scoring
        - Narrative conflict detection
        """
        # Steps 1-4: Parse, Normalize, Quality Filter, Create Article
        article = self.normalize_raw_item(raw_item_id)
        if article is None:
            return None  # Rejected by quality filter

        # Step 5: Deduplication (advanced: hash + title + content + cluster-aware)
        article = self.dedup_orchestration.mark_duplicates(article)

        # Step 6: Topic matching
        article = self.topic_matching_orchestration.match_article(article)

        # Step 7: Entity extraction (persons, locations, organisations)
        self.entity_extraction.extract_and_link(article)

        # Step 7b: AI entity consolidation (async — does not block ingestion)
        # Queues a Celery task that compares the new entities against existing
        # canonical entities and auto-merges or routes to review queue.
        try:
            from sources.tasks import consolidate_entities_for_article_task
            consolidate_entities_for_article_task.delay(article.id)
        except Exception:
            logger.debug("Entity consolidation task queue failed", exc_info=True)

        # Step 7c: Entity relationship update (async — updates co-occurrence graph)
        try:
            from sources.tasks import build_entity_relationships_for_article_task
            build_entity_relationships_for_article_task.delay(article.id)
        except Exception:
            logger.debug("Entity relationship task queue failed", exc_info=True)

        # Step 8: Story clustering (entity-aware + semantic similarity)
        story = self.story_clustering_orchestration.assign_story(article)

        # Step 9: Event resolution (narrative detection + geo + story→event mapping)
        event = None
        if story:
            event = self.event_resolution.resolve_event(story)

        # Step 10: Importance scoring (article + story)
        article = self.importance_scoring.score_article(article)
        if story:
            self.importance_scoring.score_story(story)

        # Step 11: Indexing, graph, alerts
        self.indexing_orchestration.index_article(article)
        if event:
            self.indexing_orchestration.index_event(event)
        self.graph_write_orchestration.write_article_graph(article)
        self.alert_evaluation_orchestration.evaluate_article(article)

        # Update raw item / parsed candidate status
        if article.raw_item:
            article.raw_item.status = RawItem.Status.ARTICLE_CREATED
            article.raw_item.error_message = ""
            article.raw_item.save(update_fields=["status", "error_message", "updated_at"])
        if article.parsed_candidate:
            article.parsed_candidate.status = ParsedArticleCandidate.Status.ARTICLE_CREATED
            article.parsed_candidate.error_message = ""
            article.parsed_candidate.save(update_fields=["status", "error_message", "updated_at"])

        # Async source reliability update (every 50 articles)
        self._maybe_update_source_reliability(article)

        return article

    def _maybe_update_source_reliability(self, article) -> None:
        """Recalculate source trust every 50 articles to avoid per-article overhead."""
        try:
            count = Article.objects.filter(source=article.source).count()
            if count > 0 and count % 50 == 0:
                self.source_reliability.update_source_stats(article.source)
        except Exception:
            logger.debug("Source reliability update skipped", exc_info=True)
