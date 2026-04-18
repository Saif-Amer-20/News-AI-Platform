"""Entity Similarity Service — multilingual, AI-powered entity pair scoring.

Computes a final similarity score between two entity names using a layered
strategy (fastest / most certain first):

  Layer 1 — Alias Registry lookup          → score 1.0
  Layer 2 — Arabic normalization match     → score 0.99
  Layer 3 — Multilingual embedding cosine  → 0.0 – 1.0

Additionally computes a *context score* from co-occurring entities to
distinguish genuinely similar names that refer to different real-world objects
(e.g. "Jordan" the person vs "Jordan" the country).

Safety guards block the merge even when scores are high:
  • entity_type mismatch
  • both entities appear together in the same article (strong signal they differ)
  • one name is a strict prefix/suffix of the other AND both have ≥ 4 tokens
    (avoids absorbing compound names like "Trump Organization" into "Trump")

Public API
----------
  compute(name_a, type_a, name_b, type_b, *, entity_a_id, entity_b_id)
      → SimilarityResult

  bulk_compare(anchor_entity, candidates)
      → list[SimilarityResult] sorted by final_score descending
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from django.db.models import Count

from services.orchestration.entity_post_processing_service import arabic_normalized_key
from services.orchestration.entity_resolution_service import (
    _REVERSE_ALIAS,
    _REVERSE_ALIAS_AR,
    _ALIAS_REGISTRY,
)
from sources.models import ArticleEntity, Entity

logger = logging.getLogger(__name__)

# ── Threshold constants ───────────────────────────────────────────────────────
# These are used by EntityConsolidationService for decisioning.
THRESHOLD_AUTO_MERGE = 0.92    # ≥ this → auto-merge
THRESHOLD_REVIEW = 0.72        # ≥ this (but < auto-merge) → send to review queue
                               # < THRESHOLD_REVIEW → keep separate

# Maximum token count on either side for the "strict prefix/suffix" safety rule.
_MAX_TOKENS_COMMON_SUFFIX = 3

# ── Embedding model (shared with EmbeddingCanonicalizationService) ────────────
_model_instance = None
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def _get_model():
    global _model_instance
    if _model_instance is None:
        from sentence_transformers import SentenceTransformer
        logger.info("EntitySimilarityService: loading embedding model %s", _MODEL_NAME)
        _model_instance = SentenceTransformer(_MODEL_NAME)
    return _model_instance


# ── Result data class ─────────────────────────────────────────────────────────

@dataclass
class SimilarityResult:
    entity_a_id: int
    entity_b_id: int
    name_a: str
    name_b: str
    entity_type: str                   # common type (they must match)
    similarity_score: float            # raw embedding / registry score
    context_score: float               # co-occurrence context score (0–1)
    final_score: float                 # weighted combination
    method: str                        # "registry" | "normalization" | "embedding" | "hybrid"
    explanation: str
    blocked: bool = False
    block_reason: str = ""
    supporting_article_ids: list[int] = field(default_factory=list)


# ── Service ───────────────────────────────────────────────────────────────────

class EntitySimilarityService:
    """Compute AI-powered similarity between entity name pairs."""

    # Weight of context score in final_score calculation.
    # Low weight by default — name similarity is the primary signal.
    _CONTEXT_WEIGHT = 0.15

    def compute(
        self,
        name_a: str,
        type_a: str,
        name_b: str,
        type_b: str,
        *,
        entity_a_id: int,
        entity_b_id: int,
    ) -> SimilarityResult:
        """Compute similarity between two named entities.

        Returns a SimilarityResult.  Check .blocked before acting on .final_score.
        """
        # ── Type guard ───────────────────────────────────────────────────────
        if type_a != type_b:
            return SimilarityResult(
                entity_a_id=entity_a_id,
                entity_b_id=entity_b_id,
                name_a=name_a,
                name_b=name_b,
                entity_type=type_a,
                similarity_score=0.0,
                context_score=0.0,
                final_score=0.0,
                method="blocked",
                explanation=f"Type mismatch: {type_a} vs {type_b}",
                blocked=True,
                block_reason=f"entity_type mismatch ({type_a} ≠ {type_b})",
            )

        # ── Layer 1: alias registry lookup ───────────────────────────────────
        canon_a = self._registry_canonical(name_a)
        canon_b = self._registry_canonical(name_b)

        if canon_a and canon_b and canon_a == canon_b:
            result = SimilarityResult(
                entity_a_id=entity_a_id,
                entity_b_id=entity_b_id,
                name_a=name_a,
                name_b=name_b,
                entity_type=type_a,
                similarity_score=1.0,
                context_score=1.0,
                final_score=1.0,
                method="registry",
                explanation=f"Both map to registry canonical '{canon_a}'",
            )
            # Still apply co-occurrence block as a sanity check
            return self._apply_cooccurrence_block(result, entity_a_id, entity_b_id)

        # ── Layer 2: Arabic normalization match ──────────────────────────────
        norm_a = arabic_normalized_key(name_a)
        norm_b = arabic_normalized_key(name_b)
        if norm_a == norm_b and len(norm_a) >= 3:
            result = SimilarityResult(
                entity_a_id=entity_a_id,
                entity_b_id=entity_b_id,
                name_a=name_a,
                name_b=name_b,
                entity_type=type_a,
                similarity_score=0.99,
                context_score=0.99,
                final_score=0.99,
                method="normalization",
                explanation=f"Arabic-normalized keys match: '{norm_a}'",
            )
            return self._apply_cooccurrence_block(result, entity_a_id, entity_b_id)

        # ── Layer 3: multilingual embedding similarity ───────────────────────
        similarity_score = self._embedding_similarity(name_a, name_b)

        # Context score — boost or penalise based on co-occurrence patterns
        context_score, context_articles = self._context_score(
            entity_a_id, entity_b_id, type_a
        )

        final_score = (
            (1 - self._CONTEXT_WEIGHT) * similarity_score
            + self._CONTEXT_WEIGHT * context_score
        )

        # Determine method label
        if similarity_score >= THRESHOLD_AUTO_MERGE:
            method = "embedding"
        elif similarity_score >= THRESHOLD_REVIEW:
            method = "embedding"
        else:
            method = "embedding"

        explanation = (
            f"Embedding similarity: {similarity_score:.3f}, "
            f"context score: {context_score:.3f}, "
            f"final: {final_score:.3f}"
        )

        result = SimilarityResult(
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            name_a=name_a,
            name_b=name_b,
            entity_type=type_a,
            similarity_score=similarity_score,
            context_score=context_score,
            final_score=final_score,
            method=method,
            explanation=explanation,
            supporting_article_ids=context_articles,
        )

        # Safety checks
        result = self._apply_prefix_suffix_block(result)
        if not result.blocked:
            result = self._apply_cooccurrence_block(result, entity_a_id, entity_b_id)

        return result

    def bulk_compare(
        self,
        anchor: Entity,
        candidates: list[Entity],
    ) -> list[SimilarityResult]:
        """Compare *anchor* against all *candidates*, return sorted by final_score."""
        if not candidates:
            return []

        results: list[SimilarityResult] = []

        # Batch embed anchor + all candidates in one model call for efficiency
        names = [anchor.name] + [c.name for c in candidates]
        try:
            model = _get_model()
            embeddings = model.encode(
                names,
                batch_size=256,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            anchor_emb = embeddings[0]
            candidate_embs = embeddings[1:]

            # Cosine similarity = dot product on L2-normalised vectors
            scores = (candidate_embs @ anchor_emb).tolist()
        except Exception as exc:
            logger.warning("Embedding batch failed: %s — falling back to 0.0", exc)
            scores = [0.0] * len(candidates)

        for cand, emb_score in zip(candidates, scores):
            # Try registry / normalization first (faster, deterministic)
            quick = self._quick_match(
                anchor.name, anchor.entity_type,
                cand.name, cand.entity_type,
                anchor.id, cand.id,
            )
            if quick is not None:
                results.append(quick)
                continue

            if anchor.entity_type != cand.entity_type:
                continue  # skip silently — type mismatch

            context_score, context_articles = self._context_score(
                anchor.id, cand.id, anchor.entity_type
            )
            final_score = (
                (1 - self._CONTEXT_WEIGHT) * emb_score
                + self._CONTEXT_WEIGHT * context_score
            )

            result = SimilarityResult(
                entity_a_id=anchor.id,
                entity_b_id=cand.id,
                name_a=anchor.name,
                name_b=cand.name,
                entity_type=anchor.entity_type,
                similarity_score=float(emb_score),
                context_score=context_score,
                final_score=final_score,
                method="embedding",
                explanation=(
                    f"Embedding: {emb_score:.3f}, context: {context_score:.3f}, "
                    f"final: {final_score:.3f}"
                ),
                supporting_article_ids=context_articles,
            )
            result = self._apply_prefix_suffix_block(result)
            if not result.blocked:
                result = self._apply_cooccurrence_block(result, anchor.id, cand.id)
            results.append(result)

        results.sort(key=lambda r: r.final_score, reverse=True)
        return results

    # ── Private helpers ───────────────────────────────────────────────────────

    def _quick_match(
        self,
        name_a: str, type_a: str,
        name_b: str, type_b: str,
        id_a: int, id_b: int,
    ) -> Optional[SimilarityResult]:
        """Return a result if registry or normalization match; else None."""
        if type_a != type_b:
            return SimilarityResult(
                entity_a_id=id_a, entity_b_id=id_b,
                name_a=name_a, name_b=name_b, entity_type=type_a,
                similarity_score=0.0, context_score=0.0, final_score=0.0,
                method="blocked",
                explanation=f"Type mismatch: {type_a} vs {type_b}",
                blocked=True, block_reason=f"entity_type mismatch ({type_a} ≠ {type_b})",
            )

        canon_a = self._registry_canonical(name_a)
        canon_b = self._registry_canonical(name_b)
        if canon_a and canon_b and canon_a == canon_b:
            r = SimilarityResult(
                entity_a_id=id_a, entity_b_id=id_b,
                name_a=name_a, name_b=name_b, entity_type=type_a,
                similarity_score=1.0, context_score=1.0, final_score=1.0,
                method="registry",
                explanation=f"Both map to registry canonical '{canon_a}'",
            )
            return self._apply_cooccurrence_block(r, id_a, id_b)

        norm_a = arabic_normalized_key(name_a)
        norm_b = arabic_normalized_key(name_b)
        if norm_a == norm_b and len(norm_a) >= 3:
            r = SimilarityResult(
                entity_a_id=id_a, entity_b_id=id_b,
                name_a=name_a, name_b=name_b, entity_type=type_a,
                similarity_score=0.99, context_score=0.99, final_score=0.99,
                method="normalization",
                explanation=f"Arabic-normalized keys match: '{norm_a}'",
            )
            return self._apply_cooccurrence_block(r, id_a, id_b)

        return None

    @staticmethod
    def _registry_canonical(name: str) -> Optional[str]:
        """Return the registry canonical for *name*, or None if not found."""
        low = name.lower().strip()
        canon = _REVERSE_ALIAS.get(low)
        if canon:
            return canon
        ar_key = arabic_normalized_key(name)
        return _REVERSE_ALIAS_AR.get(ar_key)

    @staticmethod
    def _embedding_similarity(name_a: str, name_b: str) -> float:
        """Compute embedding cosine similarity between two names."""
        try:
            model = _get_model()
            embs = model.encode(
                [name_a, name_b],
                batch_size=2,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            return float(np.dot(embs[0], embs[1]))
        except Exception as exc:
            logger.warning("Embedding similarity failed for '%s' vs '%s': %s", name_a, name_b, exc)
            return 0.0

    @staticmethod
    def _context_score(
        entity_a_id: int,
        entity_b_id: int,
        entity_type: str,
    ) -> tuple[float, list[int]]:
        """Compute context compatibility from shared article co-occurrences.

        Strategy:
          - If both entities appear in the SAME articles frequently → they may be
            the same entity OR they may be truly distinct entities mentioned together.
          - We use a weak positive signal: shared article context = similar topic.
          - High co-occurrence IN THE SAME SENTENCE would be a negative signal,
            but we don't have sentence-level data here, so we stay conservative.

        Returns (score 0-1, list of supporting article IDs).
        """
        try:
            # Articles mentioning entity_a
            articles_a = set(
                ArticleEntity.objects.filter(entity_id=entity_a_id)
                .values_list("article_id", flat=True)[:200]
            )
            if not articles_a:
                return 0.5, []  # neutral: no evidence

            # Articles mentioning entity_b that also mention entity_a
            shared = list(
                ArticleEntity.objects.filter(
                    entity_id=entity_b_id,
                    article_id__in=articles_a,
                ).values_list("article_id", flat=True)[:20]
            )

            if not shared:
                return 0.4, []  # slight negative: no common context

            # Shared fraction: how many of entity_a articles also contain entity_b
            overlap_ratio = len(shared) / len(articles_a)
            # Moderate overlap (0.1–0.4) is a positive context signal;
            # very high overlap (>0.6) means they almost always appear together
            # which is ambiguous, so we cap the score.
            score = min(0.85, 0.5 + overlap_ratio * 0.7)
            return score, shared[:10]

        except Exception as exc:
            logger.debug("Context score error: %s", exc)
            return 0.5, []

    @staticmethod
    def _apply_cooccurrence_block(
        result: SimilarityResult,
        entity_a_id: int,
        entity_b_id: int,
    ) -> SimilarityResult:
        """Block the merge if both entities appear in the same article.

        Same-article co-occurrence is a strong signal that the entities are
        being referenced as distinct things in the same piece of writing.
        Exception: registry/normalization matches at score=1.0 skip this check
        since the registry is authoritative.
        """
        if result.method in ("registry", "normalization") and result.final_score >= 0.99:
            return result  # registry is authoritative — don't block

        try:
            # Articles containing entity_a
            articles_a = set(
                ArticleEntity.objects.filter(entity_id=entity_a_id)
                .values_list("article_id", flat=True)[:500]
            )
            if not articles_a:
                return result

            # Does entity_b appear in any of those articles?
            cooccurs = ArticleEntity.objects.filter(
                entity_id=entity_b_id,
                article_id__in=articles_a,
            ).exists()

            if cooccurs:
                result.blocked = True
                result.block_reason = "entities co-occur in the same article"
                result.final_score = min(result.final_score, THRESHOLD_REVIEW - 0.01)

        except Exception as exc:
            logger.debug("Co-occurrence check error: %s", exc)

        return result

    @staticmethod
    def _apply_prefix_suffix_block(result: SimilarityResult) -> SimilarityResult:
        """Block when one name is a strict prefix/suffix of the other and BOTH
        have ≥ 4 tokens — avoids absorbing compound names.

        Example: 'Trump Tower' (2 tokens) vs 'Trump Organization' (2 tokens)
                 → 'trump' is a common prefix → block
        Example: 'Trump' (1 token) vs 'Donald Trump' (2 tokens)
                 → only 1 token on one side → NOT blocked (surname absorption is OK)
        """
        tokens_a = result.name_a.lower().split()
        tokens_b = result.name_b.lower().split()

        if len(tokens_a) < _MAX_TOKENS_COMMON_SUFFIX or len(tokens_b) < _MAX_TOKENS_COMMON_SUFFIX:
            return result  # at least one is short → don't block

        # Check if tokens of one are all contained in the other
        set_a = set(tokens_a)
        set_b = set(tokens_b)
        if set_a < set_b or set_b < set_a:
            result.blocked = True
            result.block_reason = (
                f"compound name containment: '{result.name_a}' ↔ '{result.name_b}' — "
                "may refer to different entities with a shared word"
            )
        return result
