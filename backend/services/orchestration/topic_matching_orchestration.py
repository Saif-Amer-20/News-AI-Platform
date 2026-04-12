from __future__ import annotations

from .topic_matching_service import TopicMatchingService


class TopicMatchingOrchestrationService:
    def __init__(self):
        self.service = TopicMatchingService()

    def match_article(self, article):
        return self.service.match(article)
