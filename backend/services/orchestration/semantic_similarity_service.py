from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter

logger = logging.getLogger(__name__)

# ── Stop words for TF-IDF (compact set) ──────────────────────────────────────
_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "has", "have", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "it", "its", "this", "that",
    "these", "those", "he", "she", "they", "we", "you", "i", "me", "him",
    "her", "us", "them", "my", "your", "his", "our", "their", "which",
    "who", "whom", "what", "where", "when", "how", "not", "no", "as",
    "if", "than", "so", "just", "also", "more", "very", "about", "over",
    "said", "says", "new", "after", "into", "up", "out", "one", "two",
    "all", "been", "being", "other", "some", "such", "only", "then",
    "there", "here",
})

# Word tokenisation (alphanumeric sequences)
_WORD_RE = re.compile(r"[a-z0-9]{2,}")


class SemanticSimilarityService:
    """
    Compute semantic similarity between texts using TF-IDF cosine similarity.

    This is a zero-dependency implementation that works without ML models.
    Architecture is ready for drop-in replacement with embedding vectors:
    swap `compute_similarity()` to compare dense vectors and add
    `compute_embedding()` to produce them.
    """

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Return cosine similarity (0.0 – 1.0) between two texts."""
        vec_a = self._tf_vector(text_a)
        vec_b = self._tf_vector(text_b)
        return self._cosine(vec_a, vec_b)

    def compute_embedding(self, text: str) -> list[float]:
        """
        Placeholder for dense-vector embeddings.

        Currently returns a sparse bag-of-words hash vector (128-dim)
        that can be stored and compared. When an embedding model is
        integrated, replace this method body.
        """
        words = self._tokenize(text)
        dim = 128
        vec = [0.0] * dim
        for word in words:
            idx = int(hashlib.md5(word.encode()).hexdigest(), 16) % dim
            vec[idx] += 1.0
        # L2 normalise
        magnitude = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / magnitude for v in vec]

    def entity_overlap_score(
        self,
        entities_a: set[str],
        entities_b: set[str],
    ) -> float:
        """Jaccard similarity between two entity sets."""
        if not entities_a and not entities_b:
            return 0.0
        intersection = entities_a & entities_b
        union = entities_a | entities_b
        return len(intersection) / len(union) if union else 0.0

    def combined_similarity(
        self,
        text_a: str,
        text_b: str,
        entities_a: set[str] | None = None,
        entities_b: set[str] | None = None,
        *,
        text_weight: float = 0.6,
        entity_weight: float = 0.4,
    ) -> float:
        """
        Weighted combination of text similarity and entity overlap.
        Falls back to pure text similarity when entities are unavailable.
        """
        text_sim = self.compute_similarity(text_a, text_b)

        if entities_a is not None and entities_b is not None:
            entity_sim = self.entity_overlap_score(entities_a, entities_b)
            return text_weight * text_sim + entity_weight * entity_sim

        return text_sim

    # ── Internal helpers ──────────────────────────────────────────

    def _tokenize(self, text: str) -> list[str]:
        words = _WORD_RE.findall(text.lower())
        return [w for w in words if w not in _STOP_WORDS]

    def _tf_vector(self, text: str) -> dict[str, float]:
        tokens = self._tokenize(text)
        if not tokens:
            return {}
        counter = Counter(tokens)
        total = len(tokens)
        return {word: count / total for word, count in counter.items()}

    def _cosine(
        self, vec_a: dict[str, float], vec_b: dict[str, float]
    ) -> float:
        if not vec_a or not vec_b:
            return 0.0
        intersection = set(vec_a.keys()) & set(vec_b.keys())
        dot = sum(vec_a[k] * vec_b[k] for k in intersection)
        mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
        mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
