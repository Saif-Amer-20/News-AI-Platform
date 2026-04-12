from __future__ import annotations

import logging
from datetime import timedelta
from difflib import SequenceMatcher

from django.db.models import Q
from django.utils import timezone

from sources.models import Article

logger = logging.getLogger(__name__)


class DedupService:
    """Advanced deduplication: exact hash, near-duplicate title, and content similarity."""

    # Title similarity thresholds
    title_exact_threshold = 0.96  # Near-exact title match
    title_near_threshold = 0.80  # Near-duplicate title match

    # Content similarity threshold for near-duplicates
    content_similarity_threshold = 0.70

    # Time window for candidate search
    window_days = 7
    max_candidates = 200

    def mark_duplicates(self, article: Article) -> Article:
        # 1. Exact hash match (fastest)
        duplicate_of = self._find_exact_hash_duplicate(article)

        # 2. Near-exact title match
        if not duplicate_of:
            duplicate_of = self._find_title_duplicate(
                article, threshold=self.title_exact_threshold
            )

        # 3. Near-duplicate: similar title + similar content
        if not duplicate_of:
            duplicate_of = self._find_near_duplicate(article)

        # 4. Cluster-aware: same story, very similar content
        if not duplicate_of:
            duplicate_of = self._find_cluster_duplicate(article)

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
        """Title is somewhat similar AND content overlap is high."""
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
            )
            .order_by("-updated_at")[: self.max_candidates]
        )

        article_content_trimmed = article.normalized_content[:2000]

        for candidate in candidates:
            title_ratio = SequenceMatcher(
                None, article.normalized_title, candidate.normalized_title
            ).ratio()
            if title_ratio < self.title_near_threshold:
                continue
            # Only check content if title is reasonably similar
            content_ratio = SequenceMatcher(
                None,
                article_content_trimmed,
                candidate.normalized_content[:2000],
            ).ratio()
            if content_ratio >= self.content_similarity_threshold:
                logger.debug(
                    "Near-duplicate: article=%s candidate=%s title=%.2f content=%.2f",
                    article.id,
                    candidate.id,
                    title_ratio,
                    content_ratio,
                )
                return candidate
        return None

    def _find_cluster_duplicate(self, article: Article) -> Article | None:
        """If article's story already exists, check siblings for content overlap."""
        if not article.story_id:
            return None

        siblings = (
            Article.objects.filter(story_id=article.story_id, is_duplicate=False)
            .exclude(pk=article.pk)
            .only("id", "normalized_content", "published_at")
            .order_by("-published_at")[:50]
        )

        article_content_trimmed = article.normalized_content[:2000]

        for sibling in siblings:
            content_ratio = SequenceMatcher(
                None,
                article_content_trimmed,
                sibling.normalized_content[:2000],
            ).ratio()
            if content_ratio >= self.content_similarity_threshold:
                return sibling
        return None
