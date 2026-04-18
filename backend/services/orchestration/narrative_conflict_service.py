"""Narrative Conflict Detection Service — flag events with inconsistent reports.

Approach
────────
1. Collect non-duplicate articles for an event from multiple sources.
2. Require minimum source diversity (≥2 distinct sources).
3. Detect strong negation/contradiction signals per article.
4. Perform cross-source claim comparison: look for opposing claims between
   articles from DIFFERENT sources.
5. Compute a confidence score combining: cross-source contradiction count,
   content divergence, and signal density.
6. Flag only when confidence exceeds threshold AND signals come from ≥2 sources.

This is a heuristic engine.  Production-grade contradiction detection would use
an NLI (Natural Language Inference) model.  The architecture is drop-in ready.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from decimal import Decimal

from sources.models import Article, Event

from .semantic_similarity_service import SemanticSimilarityService

logger = logging.getLogger(__name__)

# ── Strong contradiction patterns ─────────────────────────────────────────────
# Only unambiguous negation / refutation phrases.

_STRONG_NEGATION: list[re.Pattern] = [
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
        r"\bno\s+evidence\b",
        r"\bnot\s+true\b",
        r"\bretracted\b",
        r"\bfact.?check\b",
    )
] + [
    re.compile(p)
    for p in (
        r"نفى|ينفي|نفت",
        r"كذب|أكاذيب|ادعاءات\s+كاذبة",
        r"تناقض|يتناقض",
        r"رفض|يرفض|رفضت",
        r"غير\s+صحيح|غير\s+دقيق",
        r"لا\s+دليل|لا\s+صحة",
        r"تكذيب|تفنيد",
        r"تراجع\s+عن",
    )
]

# ── Claim extraction patterns ─────────────────────────────────────────────────
# Used for cross-source claim-level comparison: extract factual assertions
# containing numbers, casualties, or attribution.

_CLAIM_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        # Number-based claims: "killed X", "X dead", "X casualties"
        r"\b(?:killed|dead|died|casualties|wounded|injured)\s+(?:at\s+least\s+)?\d+",
        r"\b\d+\s+(?:killed|dead|died|casualties|wounded|injured)\b",
        # Attribution claims: "X said/claimed/confirmed/denied"
        r"\b(?:said|claimed|confirmed|denied|announced|reported|stated)\s+that\b",
        # Responsibility: "responsible for", "carried out", "behind the"
        r"\b(?:responsible\s+for|carried\s+out|behind\s+the)\b",
        # Ceasefire/truce claims
        r"\b(?:ceasefire|truce)\s+(?:reached|broken|violated|holding)\b",
    )
] + [
    re.compile(p)
    for p in (
        # Arabic: number-based claims
        r"(?:قتل|استشهد|أصيب|جرح)\s+\d+",
        r"\d+\s+(?:قتيل|شهيد|جريح|مصاب)",
        # Arabic: attribution claims
        r"(?:قال|أعلن|أكد|نفى|صرح)\s+(?:إن|أن|بأن)",
    )
]


class NarrativeConflictService:
    """Detect conflicting narratives across an event's articles."""

    # ── Thresholds ──────────────────────────────────────────────
    MIN_ARTICLES = 2
    MIN_SOURCES = 2                    # Hard requirement: signals from ≥2 sources
    DIVERGENCE_THRESHOLD = 0.30        # Raised slightly: avg similarity below this = divergent
    CONFIDENCE_THRESHOLD = 0.50        # Lowered from 0.55 to catch near-miss real conflicts
    MIN_STRONG_SIGNALS = 1             # At least 1 strong negation required
    MIN_CROSS_SOURCE_PAIRS = 1         # At least 1 cross-source contradiction pair

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
            self._set_flag(event, False)
            return False

        # Hard gate: need ≥2 distinct sources in the event
        distinct_sources = {a.source_id for a in articles}
        if len(distinct_sources) < self.MIN_SOURCES:
            self._set_flag(event, False)
            return False

        # ── 1. Per-article signal analysis ──
        article_signals = []  # [(article, strong_count, has_claims, source_id)]
        for article in articles:
            text = f"{article.title} {article.content}"
            strong = self._count_strong_signals(text)
            has_claims = self._has_claims(text)
            article_signals.append((article, strong, has_claims, article.source_id))

        # Group by source
        by_source: dict[int, list[tuple]] = defaultdict(list)
        for entry in article_signals:
            by_source[entry[3]].append(entry)

        # ── 2. Cross-source claim-level comparison ──
        # Find pairs of articles from DIFFERENT sources where both have signals
        cross_source_pairs = 0
        sources_with_strong = set()
        total_strong = 0

        for article, strong, has_claims, source_id in article_signals:
            if strong > 0:
                sources_with_strong.add(source_id)
                total_strong += strong

        # Count cross-source contradiction pairs:
        # article A (source X) has strong signal AND article B (source Y) has strong signal
        source_ids = list(by_source.keys())
        for i in range(len(source_ids)):
            for j in range(i + 1, len(source_ids)):
                s1_has_signal = any(s > 0 for _, s, _, _ in by_source[source_ids[i]])
                s2_has_signal = any(s > 0 for _, s, _, _ in by_source[source_ids[j]])
                s1_has_claims = any(c for _, _, c, _ in by_source[source_ids[i]])
                s2_has_claims = any(c for _, _, c, _ in by_source[source_ids[j]])
                if s1_has_signal and s2_has_signal:
                    cross_source_pairs += 1
                elif (s1_has_signal and s2_has_claims) or (s2_has_signal and s1_has_claims):
                    cross_source_pairs += 0.5  # partial: one contradicts, other makes claims

        # ── 3. Content divergence ──
        avg_similarity = self._average_pairwise_similarity(articles)
        is_divergent = avg_similarity < self.DIVERGENCE_THRESHOLD

        # ── 4. Composite confidence score ──
        # Factors:
        #   - cross_source_pairs: strong indicator (0-1, capped at 2 pairs)
        #   - divergence: content differs significantly (0 or 1)
        #   - signal density: strong signals across multiple sources
        #   - source coverage: what fraction of sources have signals

        signal_source_ratio = len(sources_with_strong) / len(distinct_sources) if distinct_sources else 0
        cross_score = min(cross_source_pairs / 2.0, 1.0)  # cap at 1.0
        divergence_score = 1.0 if is_divergent else 0.0
        density_score = min(total_strong / 4.0, 1.0)  # cap at 1.0

        confidence = (
            0.35 * cross_score          # cross-source contradiction is primary
            + 0.25 * divergence_score   # content divergence adds confidence
            + 0.20 * density_score      # signal density
            + 0.20 * signal_source_ratio  # signals spread across sources
        )

        # ── 5. Decision: all conditions must be met ──
        has_conflict = (
            confidence >= self.CONFIDENCE_THRESHOLD
            and total_strong >= self.MIN_STRONG_SIGNALS
            and len(sources_with_strong) >= self.MIN_SOURCES
            and cross_source_pairs >= self.MIN_CROSS_SOURCE_PAIRS
        )

        self._set_flag(event, has_conflict)

        if has_conflict:
            logger.warning(
                "Event %s flagged (confidence=%.2f, strong=%d, "
                "cross_pairs=%.1f, sources_w_signal=%d/%d, avg_sim=%.2f)",
                event.id, confidence, total_strong,
                cross_source_pairs, len(sources_with_strong),
                len(distinct_sources), avg_similarity,
            )

        return has_conflict

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _set_flag(event: Event, flag: bool):
        if flag != event.conflict_flag:
            event.conflict_flag = flag
            event.save(update_fields=["conflict_flag", "updated_at"])

    @staticmethod
    def _count_strong_signals(text: str) -> int:
        return sum(1 for p in _STRONG_NEGATION if p.search(text))

    @staticmethod
    def _has_claims(text: str) -> bool:
        return any(p.search(text) for p in _CLAIM_PATTERNS)

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
