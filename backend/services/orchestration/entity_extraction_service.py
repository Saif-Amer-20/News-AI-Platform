from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from decimal import Decimal

from sources.models import Article, ArticleEntity, Entity

from .entity_resolution_service import EntityResolutionService

logger = logging.getLogger(__name__)

# ── Regex-based Named Entity Recognition ─────────────────────────────────────
# Production-grade NER would use spaCy / transformers. This regex+heuristic
# approach works without external ML models and can be swapped out later.

# Capitalised multi-word sequences likely to be proper nouns
_PROPER_NOUN_RE = re.compile(
    r"\b([A-Z][a-z]{2,}(?:\s+(?:al-|bin\s|von\s|de\s|van\s)?[A-Z][a-z]{2,}){1,4})\b"
)

# Organisation indicators
_ORG_INDICATORS = {
    "ministry", "department", "agency", "bureau", "commission", "committee",
    "council", "authority", "corporation", "company", "group", "inc",
    "ltd", "foundation", "institute", "university", "bank", "fund",
    "union", "party", "army", "force", "forces", "nato", "united nations",
    "un", "eu", "who", "imf", "opec", "cia", "fbi", "nsa", "pentagon",
    "hamas", "hezbollah", "taliban", "isis", "isil",
}

# Person title indicators
_PERSON_TITLES = {
    "president", "minister", "prime minister", "secretary", "general",
    "commander", "director", "chief", "chairman", "chairwoman",
    "ambassador", "governor", "senator", "representative", "king",
    "queen", "prince", "sheikh", "ayatollah", "pope", "dr", "prof",
    "mr", "mrs", "ms",
}

# Location indicators
_LOCATION_INDICATORS = {
    "city", "province", "region", "district", "state", "capital",
    "border", "strait", "sea", "ocean", "river", "mountain", "island",
    "peninsula", "airport", "port", "base",
}


class EntityExtractionService:
    """Extract persons, organizations, and locations from article text."""

    def __init__(self):
        self.entity_resolution = EntityResolutionService()

    def extract_and_link(self, article: Article) -> list[ArticleEntity]:
        """Extract entities from article content and create DB records."""
        text = f"{article.title} {article.content}"
        raw_entities = self._extract_entities(text)

        if not raw_entities:
            return []

        linked: list[ArticleEntity] = []

        for entity_name, entity_type, count, snippet in raw_entities:
            normalized = self._normalize_entity_name(entity_name)
            if len(normalized) < 2:
                continue

            # Resolve to canonical form via the alias registry
            canonical = self.entity_resolution.resolve_name(entity_name)

            entity, created = Entity.objects.get_or_create(
                normalized_name=normalized,
                entity_type=entity_type,
                defaults={
                    "name": entity_name,
                    "canonical_name": canonical,
                },
            )
            # Backfill canonical_name on existing entities that lack it
            if not created and not entity.canonical_name:
                self.entity_resolution.resolve_entity(entity)

            relevance = self._compute_relevance(count, len(text))

            article_entity, created = ArticleEntity.objects.update_or_create(
                article=article,
                entity=entity,
                defaults={
                    "relevance_score": relevance,
                    "mention_count": count,
                    "context_snippet": snippet[:500],
                },
            )
            linked.append(article_entity)

        logger.info(
            "Extracted %d entities from article %s", len(linked), article.id
        )
        return linked

    def _extract_entities(
        self, text: str
    ) -> list[tuple[str, str, int, str]]:
        """Return list of (name, entity_type, mention_count, context_snippet)."""
        results: list[tuple[str, str, int, str]] = []
        seen_normalized: set[str] = set()

        # Find all proper-noun sequences
        matches = _PROPER_NOUN_RE.finditer(text)
        name_counter: Counter[str] = Counter()
        name_first_context: dict[str, str] = {}
        name_original: dict[str, str] = {}

        for match in matches:
            raw_name = match.group(1).strip()
            norm = self._normalize_entity_name(raw_name)
            if len(norm) < 3:
                continue
            name_counter[norm] += 1
            if norm not in name_first_context:
                start = max(0, match.start() - 60)
                end = min(len(text), match.end() + 60)
                name_first_context[norm] = text[start:end].strip()
            if norm not in name_original:
                name_original[norm] = raw_name

        for norm, count in name_counter.most_common(50):
            if norm in seen_normalized:
                continue
            seen_normalized.add(norm)

            entity_type = self._classify_entity(
                name_original[norm], name_first_context.get(norm, "")
            )
            results.append((
                name_original[norm],
                entity_type,
                count,
                name_first_context.get(norm, ""),
            ))

        return results

    def _classify_entity(self, name: str, context: str) -> str:
        """Classify an entity as person, organization, or location."""
        name_lower = name.lower()
        context_lower = context.lower()
        combined = f"{name_lower} {context_lower}"

        # Check organisation indicators
        for indicator in _ORG_INDICATORS:
            if indicator in name_lower:
                return Entity.EntityType.ORGANIZATION

        # Check if context has org indicators near the name
        for indicator in _ORG_INDICATORS:
            if indicator in context_lower:
                # If indicator is close to the name it's likely an org reference
                idx = context_lower.find(indicator)
                name_idx = context_lower.find(name_lower[:10])
                if name_idx >= 0 and abs(idx - name_idx) < 40:
                    return Entity.EntityType.ORGANIZATION

        # Check person title indicators in context
        for title in _PERSON_TITLES:
            pattern = rf"\b{re.escape(title)}\b"
            if re.search(pattern, context_lower):
                title_idx = context_lower.find(title)
                name_idx = context_lower.find(name_lower[:8])
                if name_idx >= 0 and 0 <= name_idx - title_idx < 30:
                    return Entity.EntityType.PERSON

        # Check location indicators
        for indicator in _LOCATION_INDICATORS:
            if indicator in combined:
                return Entity.EntityType.LOCATION

        # Default: two-word names are likely persons, longer → org
        word_count = len(name.split())
        if word_count <= 3:
            return Entity.EntityType.PERSON
        return Entity.EntityType.ORGANIZATION

    def _normalize_entity_name(self, name: str) -> str:
        normalized = unicodedata.normalize("NFKC", name)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized

    def _compute_relevance(self, mentions: int, text_length: int) -> Decimal:
        """More mentions relative to text → higher relevance."""
        if text_length < 100:
            return Decimal("0.50")
        density = mentions / (text_length / 500)
        if density >= 2.0:
            return Decimal("1.00")
        if density >= 1.0:
            return Decimal("0.80")
        if density >= 0.5:
            return Decimal("0.60")
        return Decimal("0.40")
