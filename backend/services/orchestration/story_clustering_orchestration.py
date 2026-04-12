from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from difflib import SequenceMatcher

from django.db.models import Count, Max, Min
from django.utils import timezone

from sources.models import Article, ArticleEntity, Story

from .semantic_similarity_service import SemanticSimilarityService

logger = logging.getLogger(__name__)


class StoryClusteringOrchestrationService:
    """
    Entity-aware, semantically-enhanced story clustering engine.

    Clustering signal = weighted combination of:
    - title similarity  (0.30)
    - semantic / TF-IDF content similarity  (0.35)
    - entity overlap    (0.35)
    """

    # Composite score threshold for joining a story
    composite_threshold = 0.35
    # Time window for story freshness
    story_window_days = 3
    # Maximum stories to compare against
    max_story_candidates = 300

    # Weights
    WEIGHT_TITLE = 0.30
    WEIGHT_SEMANTIC = 0.35
    WEIGHT_ENTITY = 0.35

    def __init__(self):
        self.similarity_service = SemanticSimilarityService()

    def assign_story(self, article: Article) -> Story:
        # If it's a duplicate, inherit the canonical article's story
        if article.is_duplicate and article.duplicate_of:
            canonical = article.duplicate_of
            if canonical.story:
                article.story = canonical.story
                article.save(update_fields=["story", "updated_at"])
                self._refresh_story(canonical.story)
                return canonical.story

        # Gather this article's entity names for overlap comparison
        article_entities = self._get_entity_names(article)

        # Try to find the best matching existing story
        best_story = self._find_best_story(article, article_entities)

        if best_story:
            article.story = best_story
            article.save(update_fields=["story", "updated_at"])
            self._refresh_story(best_story)
            logger.info(
                "Article %s assigned to existing story %s (%.60s)",
                article.id,
                best_story.id,
                best_story.title,
            )
            return best_story

        # No match — create a new story
        story_key = hashlib.sha1(
            article.normalized_title.encode("utf-8")
        ).hexdigest()
        story = Story.objects.create(
            story_key=story_key,
            title=article.title,
            first_published_at=article.published_at,
            last_published_at=article.published_at,
            article_count=1,
        )
        article.story = story
        article.save(update_fields=["story", "updated_at"])
        logger.info(
            "Article %s started new story %s", article.id, story.id
        )
        return story

    def _find_best_story(
        self, article: Article, article_entities: set[str]
    ) -> Story | None:
        window_start = timezone.now() - timedelta(days=self.story_window_days)

        recent_stories = (
            Story.objects.filter(last_published_at__gte=window_start)
            .order_by("-last_published_at")[: self.max_story_candidates]
        )

        best_story = None
        best_score = 0.0

        article_title = article.normalized_title
        article_content = article.normalized_content[:2000]

        for story in recent_stories:
            score = self._score_story_match(
                article_title,
                article_content,
                article_entities,
                story,
            )
            if score > best_score and score >= self.composite_threshold:
                best_score = score
                best_story = story

        if best_story:
            logger.debug(
                "Best story match for article %s: story %s score=%.3f",
                article.id,
                best_story.id,
                best_score,
            )

        return best_story

    def _score_story_match(
        self,
        article_title: str,
        article_content: str,
        article_entities: set[str],
        story: Story,
    ) -> float:
        """Compute composite matching score against a candidate story."""
        story_title = story.title.lower()

        # 1. Title similarity (SequenceMatcher — fast)
        title_sim = SequenceMatcher(None, article_title, story_title).ratio()

        # 2. Semantic content similarity (TF-IDF cosine)
        # Compare with the representative article's content
        rep_article = (
            story.articles.filter(is_duplicate=False)
            .only("normalized_content")
            .order_by("-published_at")
            .first()
        )
        if rep_article:
            semantic_sim = self.similarity_service.compute_similarity(
                article_content, rep_article.normalized_content[:2000]
            )
        else:
            # Fallback: compare with story title only
            semantic_sim = self.similarity_service.compute_similarity(
                article_content, story_title
            )

        # 3. Entity overlap
        story_entities = self._get_story_entity_names(story)
        entity_sim = self.similarity_service.entity_overlap_score(
            article_entities, story_entities
        )

        composite = (
            self.WEIGHT_TITLE * title_sim
            + self.WEIGHT_SEMANTIC * semantic_sim
            + self.WEIGHT_ENTITY * entity_sim
        )
        return composite

    def _get_entity_names(self, article: Article) -> set[str]:
        return set(
            ArticleEntity.objects.filter(article=article)
            .select_related("entity")
            .values_list("entity__normalized_name", flat=True)
        )

    def _get_story_entity_names(self, story: Story) -> set[str]:
        return set(
            ArticleEntity.objects.filter(
                article__story=story,
                article__is_duplicate=False,
            )
            .values_list("entity__normalized_name", flat=True)
            .distinct()
        )

    def _refresh_story(self, story: Story) -> None:
        stats = story.articles.aggregate(
            first_published_at=Min("published_at"),
            last_published_at=Max("published_at"),
            article_count=Count("id"),
        )
        story.first_published_at = stats["first_published_at"]
        story.last_published_at = stats["last_published_at"]
        story.article_count = stats["article_count"] or 0
        story.save(
            update_fields=[
                "first_published_at",
                "last_published_at",
                "article_count",
                "updated_at",
            ]
        )
