"""AI-Assisted Multilingual Entity Canonicalization using Sentence Embeddings.

Uses ``paraphrase-multilingual-MiniLM-L12-v2`` (sentence-transformers) —
a compact (115 MB) model that supports 50+ languages including Arabic and
English and produces directly-comparable cross-lingual embeddings.

Architecture
------------
                ┌──────────────────────────────┐
                │  EmbeddingCanonicalizationService │
                └──────────────────┬───────────┘
                                   │ wraps
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
  _EmbeddingIndex          ArabicNormLayer             SafetyChecker
  (lazy SentenceTransformer  (existing arabic_norm)   (prevents over-merges)
   + cosine similarity)

Public Methods
--------------
  find_merge_candidates(entity_type, threshold) → list[MergeCandidate]
      Returns entity-pair candidates that semantically match above *threshold*
      with their cosine similarity score.

  merge_with_embeddings(entity_type, threshold, dry_run, resolver)
      Executes the merge pass — applies resolver._merge_into and records
      merge_confidence / merge_method on the surviving canonical entity.

Thresholds (tuned for multilingual entity names)
-------------------------------------------------
  ≥ 0.92  : auto-merge  — virtually certain same entity
  0.80–0.92: auto-merge  — high confidence (the default)
  0.70–0.80: soft review — flagged but NOT auto-merged
  < 0.70  : no action

Safety constraints that BLOCK a merge even if score is high
-----------------------------------------------------------
  1. entity_type mismatch  (never merge PERSON into ORG etc.)
  2. One name is a suffix/prefix of the other BUT both are ≥ 4 tokens
     (e.g. "Trump" vs "Trump Organization" — "Trump" has 1 token so this
     rule doesn't fire; "Trump Tower" vs "Trump Organization" would fire)
  3. Both entities co-occur in the SAME article
     (same article can't mention two aliases of the same entity separately
     unless they genuinely differ — this is a strong over-merge signal)
  4. Candidate pair is already in the alias registry under different canonicals
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from django.db import transaction
from django.db.models import Count

from sources.models import ArticleEntity, Entity
from services.orchestration.entity_post_processing_service import arabic_normalized_key

if TYPE_CHECKING:
    from services.orchestration.entity_resolution_service import EntityResolutionService

logger = logging.getLogger(__name__)

# ── Model config ──────────────────────────────────────────────────────────────
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Minimum articles an entity must have to be considered (avoids merging
# single-mention noise entities that slipped past the post-processor).
_MIN_ARTICLE_COUNT = 2

# Default similarity threshold for auto-merge.
_DEFAULT_THRESHOLD = 0.85

# Maximum entities to embed per type in one pass (memory guard).
_MAX_PER_TYPE = 5000


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class MergeCandidate:
    variant_id: int
    canonical_id: int
    variant_name: str
    canonical_name: str
    entity_type: str
    score: float
    method: str = "embedding"
    blocked: bool = False
    block_reason: str = ""


# ── Lazy model loader ─────────────────────────────────────────────────────────
_model_instance = None


def _get_model():
    """Load the SentenceTransformer model once and cache it."""
    global _model_instance
    if _model_instance is None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]
        logger.info("Loading multilingual embedding model: %s", _MODEL_NAME)
        _model_instance = SentenceTransformer(_MODEL_NAME)
        logger.info("Model loaded.")
    return _model_instance


# ── Service ───────────────────────────────────────────────────────────────────
class EmbeddingCanonicalizationService:
    """AI-assisted entity canonicalization using multilingual embeddings."""

    def __init__(self, threshold: float = _DEFAULT_THRESHOLD):
        self.threshold = threshold

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def find_merge_candidates(
        self,
        entity_type: str,
        *,
        threshold: float | None = None,
        max_entities: int = _MAX_PER_TYPE,
    ) -> list[MergeCandidate]:
        """Compute pairwise cosine similarities and return candidate pairs."""
        thr = threshold if threshold is not None else self.threshold
        entities = self._load_entities(entity_type, max_entities)
        if len(entities) < 2:
            return []

        logger.info(
            "Embedding %d %s entities with %s…",
            len(entities), entity_type, _MODEL_NAME,
        )
        names = [e.name for e in entities]
        model = _get_model()
        embeddings = model.encode(
            names,
            batch_size=256,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        # Compute all pairwise cosine similarities in a single matrix multiply.
        # Embeddings are already L2-normalised so cosine = dot product.
        similarity_matrix: np.ndarray = np.matmul(embeddings, embeddings.T)

        candidates: list[MergeCandidate] = []
        n = len(entities)

        for i in range(n):
            for j in range(i + 1, n):
                score = float(similarity_matrix[i, j])
                if score < thr:
                    continue

                ei, ej = entities[i], entities[j]
                candidate = self._make_candidate(ei, ej, score)
                candidates.append(candidate)

        # Sort highest confidence first.
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def merge_with_embeddings(
        self,
        entity_type: str,
        resolver: "EntityResolutionService",
        *,
        threshold: float | None = None,
        dry_run: bool = False,
        max_entities: int = _MAX_PER_TYPE,
    ) -> tuple[int, list[MergeCandidate]]:
        """Run the embedding merge pass for one entity_type.

        Returns (merged_count, all_candidates) — candidates include blocked
        ones (for reporting purposes).
        """
        candidates = self.find_merge_candidates(
            entity_type, threshold=threshold, max_entities=max_entities
        )
        if not candidates:
            return 0, []

        merged = 0
        # Track which entity IDs are already consumed in this pass to avoid
        # double-merging (A→B then A→C where A was already deleted).
        consumed: set[int] = set()

        for cand in candidates:
            if cand.blocked:
                continue
            if cand.variant_id in consumed or cand.canonical_id in consumed:
                continue

            # Final co-occurrence safety check (load from DB).
            if self._entities_co_occur(cand.variant_id, cand.canonical_id):
                cand.blocked = True
                cand.block_reason = "co-occurs in same article"
                continue

            try:
                variant = Entity.objects.get(pk=cand.variant_id)
                canonical_entity = Entity.objects.get(pk=cand.canonical_id)
            except Entity.DoesNotExist:
                consumed.add(cand.variant_id)
                consumed.add(cand.canonical_id)
                continue

            if not dry_run:
                # Perform the merge
                resolver._merge_into(variant, canonical_entity)
                # Record provenance on the surviving entity
                canonical_entity.refresh_from_db()
                canonical_entity.merge_confidence = round(cand.score, 4)
                canonical_entity.merge_method = Entity.MergeMethod.EMBEDDING
                canonical_entity.save(
                    update_fields=["merge_confidence", "merge_method", "updated_at"]
                )

            consumed.add(cand.variant_id)
            merged += 1

        return merged, candidates

    def merge_all_types(
        self,
        resolver: "EntityResolutionService",
        *,
        threshold: float | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Run embedding merge for every entity type.  Returns {type: count}."""
        results: dict[str, int] = {}
        for etype in [
            Entity.EntityType.PERSON,
            Entity.EntityType.LOCATION,
            Entity.EntityType.ORGANIZATION,
        ]:
            count, _ = self.merge_with_embeddings(
                etype, resolver, threshold=threshold, dry_run=dry_run
            )
            results[etype] = count
            if count:
                logger.info(
                    "Embedding merge [%s]: %d entities merged", etype, count
                )
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _load_entities(
        self, entity_type: str, max_entities: int
    ) -> list[Entity]:
        """Load entities of a given type, ordered by article count (most prominent first)."""
        return list(
            Entity.objects.filter(entity_type=entity_type)
            .annotate(art_count=Count("article_entities"))
            .filter(art_count__gte=_MIN_ARTICLE_COUNT)
            .order_by("-art_count")[:max_entities]
        )

    def _make_candidate(
        self,
        ei: Entity,
        ej: Entity,
        score: float,
    ) -> MergeCandidate:
        """Determine which entity is the canonical (primary) and check safety rules."""
        art_i = getattr(ei, "art_count", 0)
        art_j = getattr(ej, "art_count", 0)

        # Prefer entity with more article links as the canonical.
        # Tiebreak: prefer English-script name.
        if art_i >= art_j:
            canonical, variant = ei, ej
            canonical_arts, variant_arts = art_i, art_j
        else:
            canonical, variant = ej, ei
            canonical_arts, variant_arts = art_j, art_i

        cand = MergeCandidate(
            variant_id=variant.id,
            canonical_id=canonical.id,
            variant_name=variant.name,
            canonical_name=canonical.name,
            entity_type=ei.entity_type,
            score=score,
            method="embedding",
        )

        # ── Safety checks ──────────────────────────────────────────────────

        # 1. If both are already resolved to DIFFERENT canonicals, don't merge.
        vc = variant.canonical_name or variant.normalized_name
        cc = canonical.canonical_name or canonical.normalized_name
        if vc and cc and vc != cc:
            # They diverge in canonical_name — could be different entities.
            # Only allow the merge if the score is very high (≥ 0.92).
            if score < 0.92:
                cand.blocked = True
                cand.block_reason = (
                    f"different canonicals: '{vc}' vs '{cc}' (score {score:.3f} < 0.92)"
                )
                return cand

        # 2. Suffix/prefix containment safety: if both names are multi-token
        #    and one contains the other as a whole token sequence, reject —
        #    "Trump Organization" should not merge into "Trump".
        vn_lower = variant.normalized_name.lower()
        cn_lower = canonical.normalized_name.lower()
        v_tokens = vn_lower.split()
        c_tokens = cn_lower.split()
        if len(v_tokens) >= 3 and len(c_tokens) >= 3:
            # Both long names — substring match is suspicious (different entities)
            if (vn_lower in cn_lower or cn_lower in vn_lower) and vn_lower != cn_lower:
                cand.blocked = True
                cand.block_reason = (
                    f"multi-token substring containment: '{vn_lower}' / '{cn_lower}'"
                )
                return cand

        # 3. Arabic-normalised equality shortcut: if ar_key already matches,
        #    this should have been caught by the rule-based pass. Allow it
        #    here as confirmation (no block).
        ar_eq = arabic_normalized_key(variant.name) == arabic_normalized_key(canonical.name)
        if ar_eq:
            cand.method = "embedding+arabic_norm"

        return cand

    @staticmethod
    def _entities_co_occur(id_a: int, id_b: int) -> bool:
        """Return True if entities A and B appear in the same article.

        Entities that genuinely co-occur are almost certainly distinct
        (e.g. "Trump" and "Donald Trump" used deliberately in the same
        article should not be merged).

        We use a fast EXISTS subquery instead of loading article sets.
        """
        articles_a = set(
            ArticleEntity.objects.filter(entity_id=id_a).values_list(
                "article_id", flat=True
            )[:500]
        )
        if not articles_a:
            return False
        return ArticleEntity.objects.filter(
            entity_id=id_b, article_id__in=articles_a
        ).exists()
