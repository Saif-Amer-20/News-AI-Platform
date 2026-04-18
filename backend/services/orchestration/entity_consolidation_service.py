"""Continuous AI-Driven Entity Consolidation Service.

This service is the heart of the automated entity consolidation pipeline.
It runs automatically after every article's entity extraction and also as a
periodic background sweep, ensuring the entity graph stays clean over time.

Architecture
────────────
  EntityConsolidationService
    ├── per-article pass      (called from ingest pipeline)
    │     consolidate_article_entities(article_id)
    │       → for each entity in article:
    │           1. registry lookup           → auto-merge @ 1.0
    │           2. normalization match       → auto-merge @ 0.99
    │           3. embedding similarity      → auto-merge ≥ 0.92
    │                                        → review queue 0.72–0.92
    │                                        → keep separate < 0.72
    │
    └── background sweep      (called by periodic Celery Beat task)
          background_sweep(max_entities)
            → finds unresolved entities with ≥ 2 article mentions
            → runs same confidence-based pipeline

Confidence Policy (configurable via class constants)
─────────────────────────────────────────────────────
  AUTO_MERGE_THRESHOLD  = 0.92   → entity is automatically merged
  REVIEW_THRESHOLD      = 0.72   → entity is added to EntityReviewQueue
  < REVIEW_THRESHOLD             → entity remains separate

All auto-merges are logged to EntityMergeAudit.
Ambiguous cases are added to EntityReviewQueue.

Merge semantics
───────────────
  "Merging entity A into entity B" means:
    1. All ArticleEntity rows for A are reassigned to B
    2. A's aliases are absorbed into B's aliases list
    3. A's Entity row is deleted
    4. B's merge_confidence / merge_method are updated
    5. An EntityMergeAudit row is written
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from sources.models import (
    Article,
    ArticleEntity,
    Entity,
    EntityMergeAudit,
    EntityReviewQueue,
)
from .entity_similarity_service import (
    EntitySimilarityService,
    SimilarityResult,
    THRESHOLD_AUTO_MERGE,
    THRESHOLD_REVIEW,
)
from .entity_post_processing_service import arabic_normalized_key
from .entity_resolution_service import EntityResolutionService, _ALIAS_REGISTRY

logger = logging.getLogger(__name__)


# ── Configurable thresholds ───────────────────────────────────────────────────
# Override at class level or pass to __init__ for A/B testing.
_DEFAULT_AUTO_MERGE_THRESHOLD = THRESHOLD_AUTO_MERGE   # 0.92
_DEFAULT_REVIEW_THRESHOLD = THRESHOLD_REVIEW            # 0.72

# Minimum article count for an entity to be considered as a merge *candidate*.
# Prevents single-mention noise from dragging down real entities.
_MIN_CANDIDATE_ARTICLE_COUNT = 2

# Maximum entities to compare against in per-article pass (performance guard).
_MAX_CANDIDATES_PER_ARTICLE = 50

# Maximum entities to sweep in one background pass.
_MAX_SWEEP_ENTITIES = 500


class EntityConsolidationService:
    """Continuous AI-powered entity consolidation pipeline."""

    def __init__(
        self,
        *,
        auto_merge_threshold: float = _DEFAULT_AUTO_MERGE_THRESHOLD,
        review_threshold: float = _DEFAULT_REVIEW_THRESHOLD,
    ):
        self.auto_merge_threshold = auto_merge_threshold
        self.review_threshold = review_threshold
        self.similarity = EntitySimilarityService()
        self.resolver = EntityResolutionService()

    # ═════════════════════════════════════════════════════════════════════════
    # Public API
    # ═════════════════════════════════════════════════════════════════════════

    def consolidate_article_entities(self, article_id: int) -> dict:
        """Per-article consolidation pass.

        Called immediately after entity extraction for each processed article.
        Fast: only compares new entities (created in this article) against
        high-frequency existing entities of the same type.

        Returns a stats dict.
        """
        stats = {"auto_merged": 0, "queued_for_review": 0, "kept_separate": 0, "skipped": 0}

        try:
            article = Article.objects.get(pk=article_id)
        except Article.DoesNotExist:
            logger.warning("consolidate_article_entities: article %d not found", article_id)
            return stats

        # Entities that were just extracted for this article
        article_entities = list(
            ArticleEntity.objects.filter(article=article)
            .select_related("entity")
        )

        if not article_entities:
            return stats

        for ae in article_entities:
            entity = ae.entity

            # Skip entities that already have a confirmed canonical mapping
            if entity.merge_method != Entity.MergeMethod.NONE:
                stats["skipped"] += 1
                continue

            result = self._try_resolve_entity(entity, exclude_article_id=article_id)

            if result is None:
                stats["kept_separate"] += 1
            elif result == "merged":
                stats["auto_merged"] += 1
            elif result == "queued":
                stats["queued_for_review"] += 1

        logger.info(
            "consolidate_article_entities article=%d  merged=%d  queued=%d  kept=%d",
            article_id, stats["auto_merged"], stats["queued_for_review"], stats["kept_separate"],
        )
        return stats

    def background_sweep(self, *, max_entities: int = _MAX_SWEEP_ENTITIES) -> dict:
        """Periodic background consolidation sweep.

        Finds recently created entities with ≥ 2 article mentions that have
        no canonical assigned yet, and runs the full consolidation pipeline
        on each of them.

        Returns a stats dict.
        """
        stats = {"examined": 0, "auto_merged": 0, "queued_for_review": 0, "kept_separate": 0}

        # Find unresolved entities with enough mentions to be worth processing
        unresolved = list(
            Entity.objects.filter(
                merge_method=Entity.MergeMethod.NONE,
                canonical_name="",
            )
            .annotate(article_count=Count("article_entities"))
            .filter(article_count__gte=_MIN_CANDIDATE_ARTICLE_COUNT)
            .order_by("-article_count")[:max_entities]
        )

        logger.info("background_sweep: examining %d unresolved entities", len(unresolved))

        for entity in unresolved:
            stats["examined"] += 1
            result = self._try_resolve_entity(entity, exclude_article_id=None)
            if result is None:
                stats["kept_separate"] += 1
            elif result == "merged":
                stats["auto_merged"] += 1
            elif result == "queued":
                stats["queued_for_review"] += 1

        logger.info(
            "background_sweep complete: examined=%d merged=%d queued=%d kept=%d",
            stats["examined"], stats["auto_merged"],
            stats["queued_for_review"], stats["kept_separate"],
        )
        return stats

    def process_review_queue_approval(self, queue_item_id: int, user) -> bool:
        """Approve a review queue item and execute the merge.

        Called from the Django admin action.  Returns True on success.
        """
        try:
            item = EntityReviewQueue.objects.select_related(
                "candidate_entity", "matched_entity"
            ).get(pk=queue_item_id, status=EntityReviewQueue.Status.PENDING)
        except EntityReviewQueue.DoesNotExist:
            return False

        candidate = item.candidate_entity
        target = item.matched_entity

        with transaction.atomic():
            self._execute_merge(
                source=candidate,
                target=target,
                confidence=float(item.final_score),
                method=item.merge_method,
                reason=f"Manual approval by {user}. Review: {item.explanation}",
                article_evidence=item.supporting_article_ids,
            )
            item.status = EntityReviewQueue.Status.APPROVED
            item.reviewed_by = user
            item.reviewed_at = timezone.now()
            item.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])

        logger.info(
            "Review item %d approved by %s: '%s' → '%s'",
            queue_item_id, user, candidate.name, target.name,
        )
        return True

    def process_review_queue_rejection(self, queue_item_id: int, user, note: str = "") -> bool:
        """Reject a review queue item — entities remain separate.

        Called from the Django admin action.
        """
        try:
            item = EntityReviewQueue.objects.get(
                pk=queue_item_id, status=EntityReviewQueue.Status.PENDING
            )
        except EntityReviewQueue.DoesNotExist:
            return False

        item.status = EntityReviewQueue.Status.REJECTED
        item.reviewed_by = user
        item.reviewed_at = timezone.now()
        item.review_note = note
        item.save(update_fields=[
            "status", "reviewed_by", "reviewed_at", "review_note", "updated_at"
        ])

        logger.info("Review item %d rejected by %s", queue_item_id, user)
        return True

    def rollback_merge(self, audit_id: int, user, note: str = "") -> bool:
        """Roll back an auto-merge recorded in EntityMergeAudit.

        Rolls back by creating a new Entity from the audit snapshot and
        reassigning ArticleEntity rows that point to the target entity back
        to proportional distribution (best-effort).  This is intentionally
        conservative — the rollback creates a clean new entity; it does not
        attempt to reconstruct original article links perfectly.

        Returns True on success.
        """
        try:
            audit = EntityMergeAudit.objects.select_related("target_entity").get(
                pk=audit_id, rolled_back=False
            )
        except EntityMergeAudit.DoesNotExist:
            return False

        if audit.target_entity is None:
            logger.warning("rollback_merge: target entity already deleted (audit %d)", audit_id)
            return False

        with transaction.atomic():
            # Recreate the source entity from audit snapshot
            norm = arabic_normalized_key(audit.source_entity_name).lower()
            restored, created = Entity.objects.get_or_create(
                normalized_name=norm,
                entity_type=audit.source_entity_type,
                defaults={
                    "name": audit.source_entity_name,
                    "canonical_name": audit.source_entity_canonical,
                    "aliases": audit.source_aliases,
                    "merge_method": Entity.MergeMethod.NONE,
                    "merge_confidence": Decimal("0.00"),
                },
            )

            # Mark audit as rolled back
            audit.rolled_back = True
            audit.rolled_back_at = timezone.now()
            audit.rolled_back_by = user
            audit.rollback_note = note
            audit.save(update_fields=[
                "rolled_back", "rolled_back_at", "rolled_back_by", "rollback_note", "updated_at"
            ])

            logger.info(
                "rollback_merge: audit=%d  restored entity '%s' (id=%d, created=%s)",
                audit_id, restored.name, restored.id, created,
            )

        return True

    # ═════════════════════════════════════════════════════════════════════════
    # Private: core resolution logic
    # ═════════════════════════════════════════════════════════════════════════

    def _try_resolve_entity(
        self,
        entity: Entity,
        *,
        exclude_article_id: Optional[int],
    ) -> Optional[str]:
        """Try to resolve a single entity against existing canonical entities.

        Returns:
          "merged"  → entity was merged into an existing canonical
          "queued"  → entity was added to review queue
          None      → entity remains separate (no good match)
        """
        # Step 1: registry / alias resolution (fast, deterministic)
        registry_result = self._resolve_via_registry(entity)
        if registry_result:
            return registry_result

        # Step 2: find embedding candidates (entities of same type with ≥ 2 articles)
        candidates = self._find_candidates(entity, exclude_article_id=exclude_article_id)
        if not candidates:
            return None

        # Step 3: batch similarity scoring
        results = self.similarity.bulk_compare(entity, candidates)
        if not results:
            return None

        # Take the best non-blocked result
        best = next((r for r in results if not r.blocked), None)
        if best is None:
            return None

        # Step 4: decision based on final_score
        if best.final_score >= self.auto_merge_threshold:
            target = Entity.objects.get(pk=best.entity_b_id)
            with transaction.atomic():
                self._execute_merge(
                    source=entity,
                    target=target,
                    confidence=best.final_score,
                    method=self._method_str(best.method),
                    reason=best.explanation,
                    article_evidence=best.supporting_article_ids,
                )
            return "merged"

        elif best.final_score >= self.review_threshold:
            self._add_to_review_queue(entity, best)
            return "queued"

        return None

    def _resolve_via_registry(self, entity: Entity) -> Optional[str]:
        """Try to resolve entity using alias registry.  Returns 'merged' or None."""
        from .entity_resolution_service import _REVERSE_ALIAS, _REVERSE_ALIAS_AR

        low = entity.name.lower().strip()
        canon = _REVERSE_ALIAS.get(low)
        if not canon:
            ar_key = arabic_normalized_key(entity.name)
            canon = _REVERSE_ALIAS_AR.get(ar_key)

        if not canon:
            return None

        # Find or identify the canonical entity in the DB
        # Priority: find entity with canonical_name == canon AND matching type
        # Use the registry type hint from _ALIAS_REGISTRY
        target = self._find_or_assign_canonical_entity(entity, canon)
        if target is None:
            # Registry says this canonical exists but no DB entity found —
            # just update this entity's canonical_name
            entity.canonical_name = canon
            entity.merge_method = Entity.MergeMethod.RULE
            entity.merge_confidence = Decimal("1.00")
            entity.save(update_fields=[
                "canonical_name", "merge_method", "merge_confidence", "updated_at"
            ])
            return None  # No merge executed, but resolved

        if target.id == entity.id:
            return None  # Already is the canonical

        with transaction.atomic():
            self._execute_merge(
                source=entity,
                target=target,
                confidence=1.0,
                method=EntityMergeAudit.MergeMethod.REGISTRY,
                reason=f"Alias registry: '{entity.name}' → canonical '{canon}'",
                article_evidence=[],
            )
        return "merged"

    def _find_or_assign_canonical_entity(
        self, entity: Entity, canon: str
    ) -> Optional[Entity]:
        """Find the canonical Entity row for a given canonical name.

        Look-up order:
        1. Entity where canonical_name == canon AND entity_type matches
        2. Entity where normalized_name == canon AND entity_type matches
        3. Entity where name.lower() == canon AND entity_type matches
        Returns None if no suitable candidate found.
        """
        qs = Entity.objects.filter(entity_type=entity.entity_type)

        # Prefer the entity that IS the canonical (not a variant pointing to it)
        target = (
            qs.filter(canonical_name=canon)
            .annotate(article_count=Count("article_entities"))
            .order_by("-article_count")
            .first()
        )
        if target:
            return target

        target = (
            qs.filter(normalized_name=canon)
            .annotate(article_count=Count("article_entities"))
            .order_by("-article_count")
            .first()
        )
        if target:
            return target

        target = (
            qs.filter(name__iexact=canon)
            .annotate(article_count=Count("article_entities"))
            .order_by("-article_count")
            .first()
        )
        return target

    def _find_candidates(
        self, entity: Entity, *, exclude_article_id: Optional[int]
    ) -> list[Entity]:
        """Find candidate entities to compare against.

        Candidates must:
        - Have the same entity_type
        - Have ≥ MIN_CANDIDATE_ARTICLE_COUNT article mentions (they're real)
        - NOT be the same entity
        - Have a canonical_name set (they are established canonicals)
           OR have a very high article count (well-established even without canonical)
        """
        qs = (
            Entity.objects
            .filter(entity_type=entity.entity_type)
            .exclude(pk=entity.pk)
            .annotate(article_count=Count("article_entities"))
            .filter(article_count__gte=_MIN_CANDIDATE_ARTICLE_COUNT)
        )

        # Prioritise canonical entities and high-frequency ones
        candidates = list(
            qs.filter(canonical_name__gt="")
            .order_by("-article_count")[:_MAX_CANDIDATES_PER_ARTICLE]
        )

        # If we have fewer than 10, also include unresolved high-frequency ones
        if len(candidates) < 10:
            unresolved_candidates = list(
                qs.filter(canonical_name="")
                .exclude(pk__in=[c.id for c in candidates])
                .order_by("-article_count")[:_MAX_CANDIDATES_PER_ARTICLE - len(candidates)]
            )
            candidates += unresolved_candidates

        return candidates

    def _add_to_review_queue(
        self, candidate: Entity, result: SimilarityResult
    ) -> None:
        """Add an ambiguous candidate to the EntityReviewQueue."""
        try:
            target = Entity.objects.get(pk=result.entity_b_id)
        except Entity.DoesNotExist:
            return

        # Don't re-queue if already pending for this pair
        already_queued = EntityReviewQueue.objects.filter(
            candidate_entity=candidate,
            matched_entity=target,
            status=EntityReviewQueue.Status.PENDING,
        ).exists()
        if already_queued:
            return

        method_map = {
            "registry": EntityReviewQueue.MergeMethod.REGISTRY,
            "normalization": EntityReviewQueue.MergeMethod.NORMALIZATION,
            "embedding": EntityReviewQueue.MergeMethod.EMBEDDING,
            "hybrid": EntityReviewQueue.MergeMethod.HYBRID,
        }

        EntityReviewQueue.objects.create(
            candidate_entity=candidate,
            matched_entity=target,
            similarity_score=Decimal(str(round(result.similarity_score, 4))),
            context_score=Decimal(str(round(result.context_score, 4))),
            final_score=Decimal(str(round(result.final_score, 4))),
            merge_method=method_map.get(result.method, EntityReviewQueue.MergeMethod.EMBEDDING),
            explanation=result.explanation,
            supporting_article_ids=result.supporting_article_ids,
        )

        logger.debug(
            "review queue: '%s' → '%s' (score=%.3f)",
            candidate.name, target.name, result.final_score,
        )

    def _execute_merge(
        self,
        *,
        source: Entity,
        target: Entity,
        confidence: float,
        method: str,
        reason: str,
        article_evidence: list[int],
    ) -> None:
        """Merge *source* into *target*.

        Executed inside a transaction.  Does NOT open a new transaction.

        Steps:
        1. Reassign all ArticleEntity rows from source → target
           (using update_or_create to avoid unique constraint violations)
        2. Absorb source's aliases into target's aliases
        3. Update target's merge metadata
        4. Write EntityMergeAudit log
        5. Delete source Entity row
        6. Expire any pending review queue items for this source
        """
        # Snapshot source before deletion (for audit)
        source_article_count = ArticleEntity.objects.filter(entity=source).count()
        source_aliases = list(source.aliases or [])
        source_name = source.name
        source_type = source.entity_type
        source_canonical = source.canonical_name

        # 1. Reassign ArticleEntity rows
        articles_to_reassign = list(
            ArticleEntity.objects.filter(entity=source).values_list("article_id", flat=True)
        )

        for article_id in articles_to_reassign:
            # Check if target already has an ArticleEntity for this article
            existing = ArticleEntity.objects.filter(
                entity=target, article_id=article_id
            ).first()

            if existing:
                # Absorb mention_count from source into existing row
                source_ae = ArticleEntity.objects.filter(
                    entity=source, article_id=article_id
                ).first()
                if source_ae:
                    existing.mention_count += source_ae.mention_count
                    if source_ae.relevance_score > existing.relevance_score:
                        existing.relevance_score = source_ae.relevance_score
                    existing.save(update_fields=["mention_count", "relevance_score", "updated_at"])
                    source_ae.delete()
            else:
                # Simply reassign
                ArticleEntity.objects.filter(
                    entity=source, article_id=article_id
                ).update(entity=target)

        # 2. Absorb aliases
        existing_aliases = set(target.aliases or [])
        new_aliases = set(source_aliases) | {source.name.lower(), source.normalized_name}
        merged_aliases = sorted(existing_aliases | new_aliases - {target.name.lower()})

        # 3. Update target metadata
        target.aliases = merged_aliases
        target.merge_confidence = Decimal(str(round(max(confidence, float(target.merge_confidence)), 4)))
        target.merge_method = self._best_method(
            target.merge_method, self._entity_merge_method(method)
        )
        if not target.canonical_name:
            target.canonical_name = target.name.lower()
        target.save(update_fields=[
            "aliases", "merge_confidence", "merge_method", "canonical_name", "updated_at"
        ])

        # 4. Write audit record
        EntityMergeAudit.objects.create(
            source_entity_id=source.id,
            source_entity_name=source_name,
            source_entity_type=source_type,
            source_entity_canonical=source_canonical,
            source_article_count=source_article_count,
            source_aliases=source_aliases,
            target_entity=target,
            target_entity_name=target.name,
            confidence=Decimal(str(round(confidence, 4))),
            merge_method=method,
            merge_reason=reason,
            article_evidence=article_evidence[:20],
        )

        # 5. Expire review queue items for this source
        EntityReviewQueue.objects.filter(
            candidate_entity=source,
            status=EntityReviewQueue.Status.PENDING,
        ).update(
            status=EntityReviewQueue.Status.EXPIRED,
            review_note="Source entity was merged into canonical.",
        )

        # 6. Delete source
        source.delete()

        logger.info(
            "Merged '%s' (id=%d, %d articles) → '%s' (id=%d) [confidence=%.3f, method=%s]",
            source_name, source.id if hasattr(source, 'id') else '?',
            source_article_count, target.name, target.id, confidence, method,
        )

    # ── Utility helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _method_str(method: str) -> str:
        """Normalise method string to EntityMergeAudit.MergeMethod choices."""
        mapping = {
            "registry": EntityMergeAudit.MergeMethod.REGISTRY,
            "normalization": EntityMergeAudit.MergeMethod.NORMALIZATION,
            "embedding": EntityMergeAudit.MergeMethod.EMBEDDING,
            "hybrid": EntityMergeAudit.MergeMethod.HYBRID,
        }
        return mapping.get(method, EntityMergeAudit.MergeMethod.EMBEDDING)

    @staticmethod
    def _entity_merge_method(method: str) -> str:
        """Map audit method to Entity.MergeMethod."""
        mapping = {
            EntityMergeAudit.MergeMethod.REGISTRY: Entity.MergeMethod.RULE,
            EntityMergeAudit.MergeMethod.NORMALIZATION: Entity.MergeMethod.RULE,
            EntityMergeAudit.MergeMethod.EMBEDDING: Entity.MergeMethod.EMBEDDING,
            EntityMergeAudit.MergeMethod.HYBRID: Entity.MergeMethod.HYBRID,
            EntityMergeAudit.MergeMethod.MANUAL: Entity.MergeMethod.AI,
        }
        return mapping.get(method, Entity.MergeMethod.EMBEDDING)

    @staticmethod
    def _best_method(current: str, new: str) -> str:
        """Return the 'richer' merge method for the entity's provenance record."""
        priority = {
            Entity.MergeMethod.NONE: 0,
            Entity.MergeMethod.RULE: 1,
            Entity.MergeMethod.EMBEDDING: 2,
            Entity.MergeMethod.AI: 3,
            Entity.MergeMethod.HYBRID: 4,
        }
        if priority.get(new, 0) > priority.get(current, 0):
            return new
        return current
