from __future__ import annotations

from .normalization_service import NormalizationService


class NormalizeOrchestrationService:
    def __init__(self):
        self.service = NormalizationService()

    def normalize(self, raw_item, parsed_candidate) -> dict:
        return self.service.normalize(raw_item, parsed_candidate)
