"""Entity extraction service — local multilingual NER via transformers."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from decimal import Decimal

from transformers import pipeline as hf_pipeline

from sources.models import Article, ArticleEntity, Entity

from .entity_post_processing_service import EntityPostProcessor
from .entity_resolution_service import EntityResolutionService

logger = logging.getLogger(__name__)

# Pre-downloaded into the Docker image (see Dockerfile).
_NER_MODEL = "Davlan/xlm-roberta-base-ner-hrl"

# Map model entity labels → our EntityType
_LABEL_MAP = {
    "PER": Entity.EntityType.PERSON,
    "ORG": Entity.EntityType.ORGANIZATION,
    "LOC": Entity.EntityType.LOCATION,
}

# ── Entity filtering constants ─────────────────────────────────────────────

# Minimum NER model confidence score to accept an entity span
_MIN_NER_CONFIDENCE = 0.90

# Minimum character length for a valid entity name (after normalization)
_MIN_ENTITY_LENGTH = 3

# English + Arabic stopwords / generic words that the NER model frequently
# mis-tags as entities.  Kept compact — covers the high-frequency noise.
_ENTITY_STOPWORDS: set[str] = {
    # English
    "the", "a", "an", "this", "that", "it", "its", "he", "she", "they",
    "we", "you", "his", "her", "their", "our", "my", "who", "which",
    "what", "where", "when", "how", "why", "also", "just", "new", "said",
    "says", "would", "could", "should", "may", "might", "will", "has",
    "have", "had", "been", "being", "was", "were", "are", "but", "not",
    "all", "any", "some", "more", "most", "than", "from", "with", "for",
    "about", "after", "before", "between", "under", "over", "into",
    "today", "yesterday", "tomorrow", "now", "then", "here", "there",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
    "reuters", "associated press", "ap", "afp",
    # Common boilerplate / website navigation entities
    "google play", "apple store", "app store", "play store",
    "follow us", "sign up", "log in", "subscribe",
    "terms of service", "privacy policy", "cookie policy",
    "cnn", "bbc", "nbc", "cbs", "abc", "fox news", "msnbc",
    "al jazeera", "sky news",
    # Arabic common words
    "في", "من", "إلى", "على", "عن", "هذا", "هذه", "ذلك", "تلك",
    "التي", "الذي", "الذين", "أن", "إن", "كان", "كانت", "قال", "قالت",
    "بين", "بعد", "قبل", "خلال", "حتى", "منذ", "أيضا", "لكن",
    "اليوم", "أمس", "غدا",
}

# Generic / common nouns that NER often tags as ORG or LOC
_GENERIC_WORDS: set[str] = {
    "government", "army", "military", "police", "ministry", "officials",
    "state", "country", "region", "city", "capital", "airport", "hospital",
    "university", "parliament", "congress", "senate", "court", "council",
    "president", "minister", "king", "prince", "general", "commander",
    "foreign", "defense", "interior", "spokesman", "spokesperson",
    "الحكومة", "الجيش", "الشرطة", "الوزارة", "المسؤولين",
    "الدولة", "المنطقة", "المدينة", "العاصمة", "الرئيس", "الوزير",
}

# Regex patterns that indicate boilerplate text sections (footer, nav, etc.)
_BOILERPLATE_RE = re.compile(
    r'(?i)(?:'
    r'(?:download|get)\s+(?:the\s+)?(?:app|it)\s+(?:on|from|at)'
    r'|follow\s+(?:us\s+)?on\s+(?:twitter|facebook|instagram|x|youtube|tiktok)'
    r'|sign\s+up\s+(?:for\s+)?(?:our\s+)?(?:newsletter|email)'
    r'|subscribe\s+(?:to\s+)?(?:our\s+)?(?:newsletter|channel)'
    r'|manage\s+(?:your\s+)?(?:account|settings|preferences)'
    r'|terms\s+(?:of\s+)?(?:service|use)\s*[\|·]'
    r'|©\s*\d{4}'
    r'|all\s+rights\s+reserved'
    r'|click\s+here\s+to\s+'
    r'|advertisement\b|sponsored\s+content'
    r'|related\s+(?:articles?|stories|coverage)'
    r'|more\s+(?:from|on)\s+(?:cnn|bbc|reuters|al\s+jazeera|nbc|abc|fox)'
    r'|share\s+(?:this|on)\s+(?:twitter|facebook|email|whatsapp)'
    r'|most\s+read\s+(?:stories|articles|news)'
    r')',
)


class EntityExtractionService:
    """Extract persons, organizations, and locations using a local multilingual NER model."""

    _ner_pipeline = None

    def __init__(self):
        self.entity_resolution = EntityResolutionService()
        self.post_processor = EntityPostProcessor()

    @classmethod
    def _get_ner(cls):
        if cls._ner_pipeline is None:
            logger.info("Loading NER model: %s", _NER_MODEL)
            cls._ner_pipeline = hf_pipeline(
                "ner",
                model=_NER_MODEL,
                aggregation_strategy="simple",
            )
        return cls._ner_pipeline

    def extract_and_link(self, article: Article) -> list[ArticleEntity]:
        """Extract entities from article content and create DB records."""
        text = f"{article.title} {article.content}"
        raw_entities = self._extract_entities(text)

        if not raw_entities:
            return []

        # ── Post-processing layer ──────────────────────────────────────────────
        # Normalise names, filter noise, and deduplicate within this article's
        # batch (e.g. "Trump" + "Donald Trump" → one canonical entity).
        processed = self.post_processor.process(raw_entities)
        if not processed:
            return []

        linked: list[ArticleEntity] = []

        for pe in processed:
            # Use cleaned display_name for storage; resolve against registry.
            canonical = self.entity_resolution.resolve_name(pe.display_name)
            if canonical == pe.display_name.lower():
                # No registry hit — use the post-processor's canonical key.
                canonical = pe.canonical_name

            normalized = self._normalize_entity_name(pe.display_name)
            if len(normalized) < _MIN_ENTITY_LENGTH:
                continue

            entity, created = Entity.objects.get_or_create(
                normalized_name=normalized,
                entity_type=pe.entity_type,
                defaults={
                    "name": pe.display_name,
                    "canonical_name": canonical,
                },
            )

            # Merge new aliases into the existing entity's alias list.
            if pe.aliases:
                existing_aliases: set[str] = set(entity.aliases or [])
                new_aliases = {a.lower() for a in pe.aliases} - existing_aliases - {normalized}
                if new_aliases:
                    entity.aliases = sorted(existing_aliases | new_aliases)
                    entity.save(update_fields=["aliases", "updated_at"])

            if not created and not entity.canonical_name:
                self.entity_resolution.resolve_entity(entity)

            relevance = self._compute_relevance(pe.mention_count, len(text))

            article_entity, _ = ArticleEntity.objects.update_or_create(
                article=article,
                entity=entity,
                defaults={
                    "relevance_score": relevance,
                    "mention_count": pe.mention_count,
                    "context_snippet": pe.context_snippet[:500],
                },
            )
            linked.append(article_entity)

        logger.info(
            "Extracted %d entities from article %s (raw=%d, after post-processing=%d)",
            len(linked), article.id, len(raw_entities), len(processed),
        )
        return linked

    @staticmethod
    def _strip_boilerplate(text: str) -> str:
        """Remove boilerplate sections (footers, navigation, ads) before NER."""
        # Cut at first boilerplate pattern occurrence
        match = _BOILERPLATE_RE.search(text)
        if match:
            text = text[:match.start()]
        # Also trim the last 15% of text which often contains footers/related links
        max_len = int(len(text) * 0.85)
        if len(text) > 600:  # only trim if text is long enough
            text = text[:max_len]
        return text.strip()

    def _extract_entities(
        self, text: str
    ) -> list[tuple[str, str, int, str]]:
        """Return list of (name, entity_type, mention_count, context_snippet)."""
        ner = self._get_ner()

        # Strip boilerplate before truncation
        cleaned = self._strip_boilerplate(text)

        # Truncate to stay within model context (~512 tokens ≈ 3000 chars)
        truncated = cleaned[:3000]

        try:
            ner_results = ner(truncated)
        except Exception:
            logger.exception("NER model inference failed")
            return []

        # Group and deduplicate entities
        entity_counter: Counter[tuple[str, str]] = Counter()
        entity_first_context: dict[tuple[str, str], str] = {}
        entity_original: dict[tuple[str, str], str] = {}

        # Accumulate max confidence per entity for threshold filtering
        entity_max_score: dict[tuple[str, str], float] = {}

        for ent in ner_results:
            label = ent.get("entity_group", "")
            entity_type = _LABEL_MAP.get(label)
            if not entity_type:
                continue

            # Confidence gate — reject low-confidence spans early
            score = ent.get("score", 0.0)
            if score < _MIN_NER_CONFIDENCE:
                continue

            word = ent.get("word", "").strip()
            if not word or len(word) < 2:
                continue
            word = re.sub(r"\s+", " ", word).strip()

            norm = self._normalize_entity_name(word)

            # Length gate
            if len(norm) < _MIN_ENTITY_LENGTH:
                continue

            # Stopword / generic word gate
            if norm in _ENTITY_STOPWORDS or norm in _GENERIC_WORDS:
                continue

            # Filter all-digit tokens (dates, numbers)
            if norm.replace(" ", "").isdigit():
                continue

            key = (norm, entity_type)

            entity_counter[key] += 1
            entity_max_score[key] = max(entity_max_score.get(key, 0.0), score)
            if key not in entity_first_context:
                start = max(0, ent.get("start", 0) - 60)
                end = min(len(truncated), ent.get("end", 0) + 60)
                entity_first_context[key] = truncated[start:end].strip()
            if key not in entity_original:
                entity_original[key] = word

        results = []
        for (norm, entity_type), count in entity_counter.most_common(30):
            results.append((
                entity_original[(norm, entity_type)],
                entity_type,
                count,
                entity_first_context.get((norm, entity_type), ""),
            ))

        return results

    def _normalize_entity_name(self, name: str) -> str:
        normalized = unicodedata.normalize("NFKC", name)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized

    def _compute_relevance(self, mentions: int, text_length: int) -> Decimal:
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
