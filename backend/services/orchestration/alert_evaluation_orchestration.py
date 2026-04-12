from __future__ import annotations

import logging

from .alert_evaluation_service import AlertEvaluationService

logger = logging.getLogger(__name__)


class AlertEvaluationOrchestrationService:
    def __init__(self):
        self._evaluator: AlertEvaluationService | None = None

    @property
    def evaluator(self) -> AlertEvaluationService:
        if self._evaluator is None:
            self._evaluator = AlertEvaluationService()
        return self._evaluator

    def evaluate_article(self, article) -> None:
        """Evaluate an article against all alert rules.  Failures are logged, not raised."""
        try:
            created = self.evaluator.evaluate(article)
            if created:
                logger.info(
                    "Alert evaluation: %d alert(s) created for article %s",
                    len(created),
                    article.id,
                )
        except Exception:
            logger.warning(
                "Alert evaluation failed for article %s",
                article.id,
                exc_info=True,
            )
