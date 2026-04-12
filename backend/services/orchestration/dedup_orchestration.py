from __future__ import annotations

from .dedup_service import DedupService


class DedupOrchestrationService:
    def __init__(self):
        self.service = DedupService()

    def mark_duplicates(self, article):
        return self.service.mark_duplicates(article)
