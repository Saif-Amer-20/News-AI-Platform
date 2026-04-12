from __future__ import annotations

import logging
import re
from decimal import Decimal

logger = logging.getLogger(__name__)

# Minimum content length (characters) to pass quality filter
MIN_CONTENT_LENGTH = 100
# Minimum unique word ratio (anti-spam)
MIN_UNIQUE_WORD_RATIO = 0.20
# Maximum caps ratio (anti-spam / shouting detection)
MAX_CAPS_RATIO = 0.60
# Penalty for boilerplate patterns
BOILERPLATE_PATTERNS = [
    re.compile(r"subscribe\s+(now|today|here)", re.IGNORECASE),
    re.compile(r"click\s+here\s+to", re.IGNORECASE),
    re.compile(r"(buy\s+now|order\s+today|limited\s+offer)", re.IGNORECASE),
]


class QualityFilterService:
    """Assigns a quality_score (0.00–1.00) and rejects low-quality content."""

    def evaluate(self, normalized: dict) -> dict:
        """Return dict with quality_score and quality_passed boolean."""
        title = normalized.get("title", "")
        content = normalized.get("content", "")

        scores: list[float] = []

        # 1. Content length score
        length_score = self._length_score(content)
        scores.append(length_score)

        # 2. Title quality
        title_score = self._title_score(title)
        scores.append(title_score)

        # 3. Unique word ratio
        word_score = self._unique_word_ratio_score(content)
        scores.append(word_score)

        # 4. Caps ratio (lower is better for normal text)
        caps_score = self._caps_score(content)
        scores.append(caps_score)

        # 5. Boilerplate penalty
        boilerplate_score = self._boilerplate_score(content)
        scores.append(boilerplate_score)

        quality_score = round(sum(scores) / len(scores), 2) if scores else 0.0
        quality_passed = quality_score >= 0.30 and len(content) >= MIN_CONTENT_LENGTH

        logger.debug(
            "Quality evaluation: score=%.2f passed=%s length=%d",
            quality_score,
            quality_passed,
            len(content),
        )

        return {
            "quality_score": Decimal(str(quality_score)),
            "quality_passed": quality_passed,
        }

    def _length_score(self, content: str) -> float:
        length = len(content)
        if length < 50:
            return 0.0
        if length < MIN_CONTENT_LENGTH:
            return 0.2
        if length < 300:
            return 0.5
        if length < 800:
            return 0.8
        return 1.0

    def _title_score(self, title: str) -> float:
        if not title or len(title.strip()) < 5:
            return 0.0
        if len(title) > 300:
            return 0.4
        return 1.0

    def _unique_word_ratio_score(self, content: str) -> float:
        words = content.lower().split()
        if len(words) < 5:
            return 0.0
        ratio = len(set(words)) / len(words)
        if ratio < MIN_UNIQUE_WORD_RATIO:
            return 0.1
        if ratio < 0.40:
            return 0.5
        return 1.0

    def _caps_score(self, content: str) -> float:
        alpha_chars = [c for c in content if c.isalpha()]
        if not alpha_chars:
            return 0.5
        caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if caps_ratio > MAX_CAPS_RATIO:
            return 0.1
        return 1.0

    def _boilerplate_score(self, content: str) -> float:
        hits = sum(1 for pat in BOILERPLATE_PATTERNS if pat.search(content))
        if hits == 0:
            return 1.0
        if hits == 1:
            return 0.6
        return 0.2
