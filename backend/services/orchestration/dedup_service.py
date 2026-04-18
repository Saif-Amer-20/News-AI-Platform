from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse

from django.utils import timezone

from sources.models import Article

from .semantic_similarity_service import SemanticSimilarityService

logger = logging.getLogger(__name__)


def _shingle_set(text: str, k: int = 5) -> set[str]:
    """Extract character k-shingles from text (lowered, whitespace-collapsed)."""
    text = re.sub(r"\s+", " ", text.strip().lower())
    if len(text) < k:
        return {text}
    return {text[i : i + k] for i in range(len(text) - k + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _paragraph_hash(text: str) -> str:
    """Hash the first ~500 chars of normalized text for fast comparison."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())[:500]
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


class DedupService:
    """Deduplication: URL, content hash, paragraph hash, near-duplicate title, and embedding-based similarity."""

    title_exact_threshold = 0.96
    title_near_threshold = 0.65      # lowered to catch more reformulated titles
    content_similarity_threshold = 0.75  # lowered slightly for better recall
    content_hash_shingle_threshold = 0.75  # lowered Jaccard threshold

    window_days = 7
    max_candidates = 200

    def __init__(self):
        self._sim = SemanticSimilarityService()

    def mark_duplicates(self, article: Article) -> Article:
        # 1. Exact content hash match (fastest)
        duplicate_of = self._find_exact_hash_duplicate(article)

        # 2. URL normalization (same domain+path = same article)
        if not duplicate_of:
            duplicate_of = self._find_url_duplicate(article)

        # 3. Paragraph hash: first 500 chars hash match (catches republished content)
        if not duplicate_of:
            duplicate_of = self._find_paragraph_hash_duplicate(article)

        # 4. Near-exact title match
        if not duplicate_of:
            duplicate_of = self._find_title_duplicate(
                article, threshold=self.title_exact_threshold
            )

        # 5. Near-duplicate: similar title + embedding content check with time proximity
        if not duplicate_of:
            duplicate_of = self._find_near_duplicate(article)

        # 6. Cluster-aware: same story, embedding content overlap
        if not duplicate_of:
            duplicate_of = self._find_cluster_duplicate(article)

        # 7. Content shingle fallback: catch near-copies with different titles
        if not duplicate_of:
            duplicate_of = self._find_shingle_duplicate(article)

        if duplicate_of:
            article.is_duplicate = True
            article.duplicate_of = duplicate_of
            logger.info(
                "Article %s marked as duplicate of %s",
                article.id,
                duplicate_of.id,
            )
        else:
            article.is_duplicate = False
            article.duplicate_of = None

        article.save(update_fields=["is_duplicate", "duplicate_of", "updated_at"])
        return article

    def _find_exact_hash_duplicate(self, article: Article) -> Article | None:
        return (
            Article.objects.filter(content_hash=article.content_hash, is_duplicate=False)
            .exclude(pk=article.pk)
            .order_by("published_at", "id")
            .first()
        )

    def _find_url_duplicate(self, article: Article) -> Article | None:
        """Find duplicate by normalized URL (same domain + path)."""
        if not article.url:
            return None
        try:
            parsed = urlparse(article.url)
            domain = parsed.netloc.lower().replace("www.", "")
            path = parsed.path.rstrip("/").lower()
            if not path or path == "/":
                return None
        except Exception:
            return None

        window_start = timezone.now() - timedelta(days=self.window_days)
        candidates = (
            Article.objects.filter(
                is_duplicate=False,
                updated_at__gte=window_start,
            )
            .exclude(pk=article.pk)
            .only("id", "url", "published_at")
            .order_by("-updated_at")[:self.max_candidates]
        )
        for candidate in candidates:
            if not candidate.url:
                continue
            try:
                c_parsed = urlparse(candidate.url)
                c_domain = c_parsed.netloc.lower().replace("www.", "")
                c_path = c_parsed.path.rstrip("/").lower()
                if domain == c_domain and path == c_path:
                    return candidate
            except Exception:
                continue
        return None

    def _find_paragraph_hash_duplicate(self, article: Article) -> Article | None:
        """Find duplicate by hashing first 500 chars of normalized content."""
        content = article.normalized_content or article.content or ""
        if len(content) < 200:
            return None
        target_hash = _paragraph_hash(content)

        window_start = timezone.now() - timedelta(days=self.window_days)
        candidates = (
            Article.objects.filter(
                is_duplicate=False,
                updated_at__gte=window_start,
            )
            .exclude(pk=article.pk)
            .only("id", "normalized_content", "content", "published_at")
            .order_by("-updated_at")[:self.max_candidates]
        )
        for candidate in candidates:
            c_content = candidate.normalized_content or candidate.content or ""
            if len(c_content) < 200:
                continue
            if _paragraph_hash(c_content) == target_hash:
                return candidate
        return None

    def _find_title_duplicate(
        self, article: Article, *, threshold: float
    ) -> Article | None:
        window_start = timezone.now() - timedelta(days=self.window_days)
        candidates = (
            Article.objects.filter(
                is_duplicate=False, updated_at__gte=window_start
            )
            .exclude(pk=article.pk)
            .order_by("-updated_at")[: self.max_candidates]
        )
        for candidate in candidates:
            ratio = SequenceMatcher(
                None, article.normalized_title, candidate.normalized_title
            ).ratio()
            if ratio >= threshold:
                return candidate
        return None

    def _find_near_duplicate(self, article: Article) -> Article | None:
        """Title is somewhat similar AND embedding content similarity is high.

        Uses graduated time proximity boost:
          - ≤2h: 0.10 boost (strong — breaking news copies)
          - ≤6h: 0.07 boost
          - ≤12h: 0.05 boost
          - ≤24h: 0.03 boost

        Title similarity also modulates: very high title sim (≥0.85)
        gets an additional 0.04 content threshold reduction.

        Cross-source boost: articles from the same source get a small
        additional 0.02 reduction (same outlet republishing).
        """
        window_start = timezone.now() - timedelta(days=self.window_days)
        candidates = (
            Article.objects.filter(
                is_duplicate=False, updated_at__gte=window_start
            )
            .exclude(pk=article.pk)
            .only(
                "id",
                "normalized_title",
                "normalized_content",
                "published_at",
                "source_id",
            )
            .order_by("-updated_at")[: self.max_candidates]
        )

        for candidate in candidates:
            title_ratio = SequenceMatcher(
                None, article.normalized_title, candidate.normalized_title
            ).ratio()
            if title_ratio < self.title_near_threshold:
                continue

            # Graduated time proximity boost
            time_boost = 0.0
            if article.published_at and candidate.published_at:
                delta_hours = abs(
                    (article.published_at - candidate.published_at).total_seconds()
                ) / 3600
                if delta_hours <= 2:
                    time_boost = 0.10
                elif delta_hours <= 6:
                    time_boost = 0.07
                elif delta_hours <= 12:
                    time_boost = 0.05
                elif delta_hours <= 24:
                    time_boost = 0.03

            # High title similarity bonus
            title_bonus = 0.04 if title_ratio >= 0.85 else 0.0

            # Cross-source boost: same source republishing
            source_bonus = 0.02 if article.source_id == candidate.source_id else 0.0

            effective_threshold = (
                self.content_similarity_threshold
                - time_boost
                - title_bonus
                - source_bonus
            )

            # Embedding-based content similarity (multilingual)
            content_sim = self._sim.compute_similarity(
                article.normalized_content[:2000],
                candidate.normalized_content[:2000],
            )
            if content_sim >= effective_threshold:
                logger.debug(
                    "Near-duplicate: article=%s candidate=%s title=%.2f "
                    "content=%.2f time_boost=%.2f title_bonus=%.2f source_bonus=%.2f",
                    article.id, candidate.id, title_ratio, content_sim,
                    time_boost, title_bonus, source_bonus,
                )
                return candidate
        return None

    def _find_cluster_duplicate(self, article: Article) -> Article | None:
        """If article's story already exists, check siblings for content overlap.

        Uses a lower threshold than the general near-dup check since we
        already have a cluster signal (same story).
        """
        if not article.story_id:
            return None

        cluster_threshold = self.content_similarity_threshold - 0.05  # easier within cluster

        siblings = (
            Article.objects.filter(story_id=article.story_id, is_duplicate=False)
            .exclude(pk=article.pk)
            .only("id", "normalized_content", "published_at")
            .order_by("-published_at")[:50]
        )

        for sibling in siblings:
            content_sim = self._sim.compute_similarity(
                article.normalized_content[:2000],
                sibling.normalized_content[:2000],
            )
            if content_sim >= cluster_threshold:
                return sibling
        return None

    def _find_shingle_duplicate(self, article: Article) -> Article | None:
        """Content hashing fallback: Jaccard similarity on character shingles.

        Catches near-copies that have different titles but almost identical
        body text (e.g., wire service articles redistributed by different outlets).
        Only runs on articles with sufficient content.
        """
        content = article.normalized_content or article.content or ""
        if len(content) < 300:
            return None

        target_shingles = _shingle_set(content[:2000])

        window_start = timezone.now() - timedelta(days=self.window_days)
        candidates = (
            Article.objects.filter(
                is_duplicate=False,
                updated_at__gte=window_start,
            )
            .exclude(pk=article.pk)
            .only("id", "normalized_content", "content", "published_at")
            .order_by("-updated_at")[:100]  # smaller batch — shingle is heavier
        )
        for candidate in candidates:
            c_content = candidate.normalized_content or candidate.content or ""
            if len(c_content) < 300:
                continue
            c_shingles = _shingle_set(c_content[:2000])
            if _jaccard(target_shingles, c_shingles) >= self.content_hash_shingle_threshold:
                logger.debug(
                    "Shingle duplicate: article=%s candidate=%s",
                    article.id, candidate.id,
                )
                return candidate
        return None
