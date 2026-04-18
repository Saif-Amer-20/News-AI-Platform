"""Semantic similarity service — multilingual embeddings via sentence-transformers."""

from __future__ import annotations

import logging

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Model is pre-downloaded into the Docker image (see Dockerfile).
_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class SemanticSimilarityService:
    """
    Compute semantic similarity using multilingual sentence embeddings.

    Uses ``paraphrase-multilingual-MiniLM-L12-v2`` (384-dim, ~120 MB)
    which natively supports Arabic, English and 50+ other languages.
    The model is loaded lazily on first use and shared across calls.
    """

    _model: SentenceTransformer | None = None

    @classmethod
    def _get_model(cls) -> SentenceTransformer:
        if cls._model is None:
            logger.info("Loading sentence-transformer model: %s", _MODEL_NAME)
            cls._model = SentenceTransformer(_MODEL_NAME)
        return cls._model

    # ── Public API (same interface as before) ─────────────────────

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Return cosine similarity (0.0 – 1.0) between two texts."""
        if not text_a or not text_b:
            return 0.0
        model = self._get_model()
        embeddings = model.encode([text_a, text_b], normalize_embeddings=True)
        score = float(np.dot(embeddings[0], embeddings[1]))
        return max(0.0, min(score, 1.0))

    def compute_embedding(self, text: str) -> list[float]:
        """Return a 384-dim L2-normalised embedding vector."""
        if not text:
            return [0.0] * 384
        model = self._get_model()
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()

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
