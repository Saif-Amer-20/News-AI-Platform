"""Narrative Conflict Detection Service — flag events with inconsistent reports.

Approach
────────
1. Collect non-duplicate articles for an event.
2. Detect negation / contradiction patterns between article pairs.
3. Compute pairwise content divergence (inverse semantic similarity).
4. If divergence is high *and* contradiction patterns are found → set conflict_flag.

This is a heuristic engine.  Production-grade contradiction detection would use
an NLI (Natural Language Inference) model.  The architecture is drop-in ready.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal

from sources.models import Article, Event

from .semantic_similarity_service import SemanticSimilarityService

logger = logging.getLogger(__name__)

# ── Contradiction signal patterns ─────────────────────────────────────────────
# These patterns suggest one article may contradict another.

_NEGATION_PHRASES: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdenied\b",
        r"\bdenies\b",
        r"\brefuted\b",
        r"\bcontradicts?\b",
        r"\bdisputed?\b",
        r"\brejected?\b",
        r"\bfalse\s+claim\b",
        r"\bmisinformation\b",
        r"\binaccurate\b",
        r"\bunconfirmed\b",
        r"\bno\s+evidence\b",
        r"\bno\s+casualties\b",
        r"\bnot\s+true\b",
        r"\brumou?r\b",
        r"\bretracted\b",
        r"\bcorrection\b",
        r"\bfact.?check\b",
    )
]

_CONFLICTING_CLAIM_PHRASE = re.compile(
    r"\b(however|but|contrary|on the other hand|while others|some say|disputed)\b",
    re.IGNORECASE,
)


class NarrativeConflictService:
    """Detect conflicting narratives across an event's articles."""

    # Minimum number of articles to attempt conflict detection
    MIN_ARTICLES = 2

    # If average pairwise similarity is below this → divergent
    DIVERGENCE_THRESHOLD = 0.35

    # Minimum contradiction signals needed alongside divergence
    MIN_CONTRADICTION_SIGNALS = 2

    def __init__(self):
        self.similarity = SemanticSimilarityService()

    def detect(self, event: Event) -> bool:
        """
        Analyse event articles for narrative conflicts.
        Sets ``event.conflict_flag`` and returns the flag value.
        """
        articles = list(
            Article.objects.filter(
                story__event=event,
                is_duplicate=False,
            )
            .select_related("source")[:100]
        )

        if len(articles) < self.MIN_ARTICLES:
            if event.conflict_flag:
                event.conflict_flag = False
                event.save(update_fields=["conflict_flag", "updated_at"])
            return False

        # 1. Count contradiction signals across all articles
        total_signals = 0
        for article in articles:
            text = f"{article.title} {article.content}"
            total_signals += self._count_contradiction_signals(text)

        # 2. Compute pairwise content divergence
        avg_similarity = self._average_pairwise_similarity(articles)
        is_divergent = avg_similarity < self.DIVERGENCE_THRESHOLD

        # 3. Composite decision
        has_conflict = (
            is_divergent and total_signals >= self.MIN_CONTRADICTION_SIGNALS
        )

        if has_conflict != event.conflict_flag:
            event.conflict_flag = has_conflict
            event.save(update_fields=["conflict_flag", "updated_at"])

        if has_conflict:
            logger.warning(
                "Event %s flagged for narrative conflict "
                "(avg_sim=%.2f, signals=%d)",
                event.id,
                avg_similarity,
                total_signals,
            )

        return has_conflict

    # ── Internals ─────────────────────────────────────────────────

    def _count_contradiction_signals(self, text: str) -> int:
        count = 0
        for pattern in _NEGATION_PHRASES:
            if pattern.search(text):
                count += 1
        if _CONFLICTING_CLAIM_PHRASE.search(text):
            count += 1
        return count

    def _average_pairwise_similarity(self, articles: list[Article]) -> float:
        """Sample pairwise similarity (cap at 30 pairs)."""
        titles = [a.normalized_title or a.title.lower() for a in articles]
        contents = [
            (a.normalized_content or a.content)[:500].lower()
            for a in articles
        ]

        pairs = 0
        total_sim = 0.0
        max_pairs = 30
        for i in range(len(articles)):
            for j in range(i + 1, len(articles)):
                title_sim = self.similarity.compute_similarity(titles[i], titles[j])
                content_sim = self.similarity.compute_similarity(contents[i], contents[j])
                total_sim += 0.4 * title_sim + 0.6 * content_sim
                pairs += 1
                if pairs >= max_pairs:
                    break
            if pairs >= max_pairs:
                break

        return total_sim / pairs if pairs else 0.50
