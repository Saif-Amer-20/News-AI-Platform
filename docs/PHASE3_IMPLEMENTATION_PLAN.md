# Phase 3 — Implementation Plan

> **Status**: Pending approval  
> **Depends on**: Phase 2 Target Architecture (`docs/PHASE2_TARGET_ARCHITECTURE.md`) — APPROVED  
> **Next**: Phase 4 (Implementation) — blocked until this plan is approved  

---

## Execution Overview

4 waves, executed sequentially. Each wave completes fully before the next begins.
Every change lists the **exact file**, **exact method/section**, and **exact diff description**.

After each wave: `python manage.py migrate`, `docker compose build`, smoke test.

---

## WAVE 0 — Foundation

> Goal: New dependencies installed, model baked into Docker image, DB fields added. No behavior changes yet.

### W0.1 — Update requirements

**File**: `backend/requirements/prod.txt`

Append:
```
langdetect==1.0.9
trafilatura==2.0.0
sentence-transformers==3.3.1
djangorestframework-simplejwt==5.4.0
```

`torch` is auto-installed by `sentence-transformers` (CPU wheel).

---

### W0.2 — Update Dockerfile

**File**: `backend/Dockerfile`

After the `pip install` line and before `COPY backend/ /app/`:

```dockerfile
# Pre-download the multilingual embedding model at build time (~120 MB)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"
```

This caches the model into `/root/.cache/torch/sentence_transformers/` inside the image.
Since the app runs as `app` user, also need:
```dockerfile
RUN mkdir -p /home/app/.cache && cp -r /root/.cache/torch /home/app/.cache/torch 2>/dev/null || true
```
Place this after the `useradd` line so the `app` user can load the model.

---

### W0.3 — Data migration: Article.language

**File**: `backend/sources/models.py` — class `Article`

Add field after `content_hash`:
```python
language = models.CharField(
    max_length=8,
    blank=True,
    default="",
    db_index=True,
    help_text="ISO 639-1 language code detected on ingest.",
)
```

**Migration**: `python manage.py makemigrations sources -n article_language`  
Generates `sources/migrations/0002_article_language.py`. No backfill RunPython needed — new articles get detected, old ones stay `""`.

---

### W0.4 — Data migration: Entity.language

**File**: `backend/sources/models.py` — class `Entity`

Add field after `metadata`:
```python
language = models.CharField(
    max_length=8,
    blank=True,
    default="",
    db_index=True,
    help_text="Language of the entity name.",
)
```

**Migration**: `python manage.py makemigrations sources -n entity_language`  
Generates `sources/migrations/0003_entity_language.py`.

---

### W0.5 — Verify

```bash
docker compose build backend
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'); print(m.encode('test').shape)"
# Expected: (384,)
docker compose run --rm backend python -c "from langdetect import detect; print(detect('هذا نص عربي'))"
# Expected: ar
docker compose run --rm backend python -c "import trafilatura; print(trafilatura.__version__)"
# Expected: 2.0.0
```

---

## WAVE 1 — Core Services

> Goal: Normalization detects language, parsing uses trafilatura, embeddings go multilingual, quality filter becomes language-aware. No caller changes.

### W1.1 — NormalizationService: Arabic normalization + language detection

**File**: `backend/services/orchestration/normalization_service.py`

**Change 1** — Add import at top:
```python
from langdetect import detect as detect_lang
```

**Change 2** — Add `_detect_language` and `_normalize_arabic` and `_looks_arabic` methods to the class:
```python
def _detect_language(self, text: str) -> str:
    try:
        return detect_lang(text[:1000]) if len(text) >= 20 else ""
    except Exception:
        return ""

def _looks_arabic(self, text: str) -> bool:
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return arabic_chars > len(text) * 0.3 if text else False

def _normalize_arabic(self, text: str) -> str:
    import re as _re
    text = text.replace('\u0623', '\u0627').replace('\u0625', '\u0627').replace('\u0622', '\u0627')
    text = text.replace('\u0629', '\u0647')
    text = text.replace('\u0649', '\u064A')
    text = _re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]', '', text)
    return text
```

**Change 3** — Modify `normalize_text` to add Arabic normalization:
```python
def normalize_text(self, value: str, *, lowercase: bool = False) -> str:
    normalized = unicodedata.normalize("NFKC", clean_text(value))
    if self._looks_arabic(normalized):
        normalized = self._normalize_arabic(normalized)
    return normalized.lower() if lowercase else normalized
```

**Change 4** — Modify `normalize` to add language detection and return it:
```python
def normalize(self, raw_item: RawItem, parsed_candidate: ParsedArticleCandidate) -> dict:
    title = self.normalize_text(parsed_candidate.title or raw_item.title_raw)
    content = self.normalize_text(parsed_candidate.content or raw_item.content_raw)
    language = self._detect_language(content)
    normalized_title = self.normalize_text(title, lowercase=True)
    normalized_content = self.normalize_text(content, lowercase=True)
    # ... rest unchanged ...
    return {
        # ... existing keys ...
        "language": language,
    }
```

**Downstream effect**: The returned dict now includes `"language"`. The next consumer is `raw_item_service.create_or_update_article()` which unpacks the dict. We must also update that to save the language field.

---

### W1.2 — RawItemService: Pass language to Article

**File**: `backend/services/orchestration/raw_item_service.py`

**Change**: In `create_or_update_article`, add `"language"` to the `defaults` dict:
```python
defaults={
    # ... existing fields ...
    "language": normalized.get("language", ""),
},
```

Add it after the `"metadata"` line (line ~99).

---

### W1.3 — ArticleParseService: trafilatura content extraction

**File**: `backend/services/orchestration/article_parse_service.py`

**Change 1** — Add import at top:
```python
import trafilatura
```

**Change 2** — Replace the `_parse_html` method body:
```python
def _parse_html(self, raw_item: RawItem):
    html = raw_item.html_raw

    # Primary: trafilatura for robust content extraction
    content = ""
    if html:
        content = trafilatura.extract(html, favor_precision=True) or ""

    # Fallback: existing BS4 extraction if trafilatura comes up empty
    soup = BeautifulSoup(html, "lxml") if html else None
    if not content and soup:
        content = self._extract_content_from_soup(soup) or clean_text(raw_item.content_raw) or html_to_text(raw_item.html_raw)
    if not content:
        content = clean_text(raw_item.content_raw)

    # Metadata extraction stays with BS4 (reliable for structured meta tags)
    if soup:
        title = self._extract_title_from_soup(soup) or clean_text(raw_item.title_raw)
        published_at = self._extract_published_from_soup(soup) or parse_datetime_value(raw_item.metadata.get("published_at"))
        author = self._extract_author_from_soup(soup) or clean_text(raw_item.metadata.get("author"))
        image_url = self._extract_image_from_soup(soup) or raw_item.metadata.get("image_url", "")
    else:
        title = clean_text(raw_item.title_raw)
        published_at = parse_datetime_value(raw_item.metadata.get("published_at"))
        author = clean_text(raw_item.metadata.get("author"))
        image_url = raw_item.metadata.get("image_url", "")

    return title, content, published_at, author, image_url
```

Keep `_extract_content_from_soup` as fallback. Keep all other `_extract_*` methods unchanged.

---

### W1.4 — SemanticSimilarityService: multilingual embeddings

**File**: `backend/services/orchestration/semantic_similarity_service.py`

**Full replacement** of the file internals:

**Change 1** — Replace imports and top-level constants:
```python
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


class SemanticSimilarityService:
    """Multilingual embedding similarity using sentence-transformers."""

    _model = None

    @classmethod
    def _get_model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer
            cls._model = SentenceTransformer(
                'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
            )
            logger.info("Loaded sentence-transformers model")
        return cls._model

    def compute_embedding(self, text: str) -> list[float]:
        model = self._get_model()
        embedding = model.encode(text[:2000], normalize_embeddings=True)
        return embedding.tolist()

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        emb_a = self.compute_embedding(text_a)
        emb_b = self.compute_embedding(text_b)
        return sum(a * b for a, b in zip(emb_a, emb_b))

    def entity_overlap_score(self, entities_a: set[str], entities_b: set[str]) -> float:
        if not entities_a and not entities_b:
            return 0.0
        intersection = entities_a & entities_b
        union = entities_a | entities_b
        return len(intersection) / len(union) if union else 0.0

    def combined_similarity(
        self, text_a: str, text_b: str,
        entities_a: set[str] | None = None,
        entities_b: set[str] | None = None,
        *, text_weight: float = 0.6, entity_weight: float = 0.4,
    ) -> float:
        text_sim = self.compute_similarity(text_a, text_b)
        if entities_a is not None and entities_b is not None:
            entity_sim = self.entity_overlap_score(entities_a, entities_b)
            return text_weight * text_sim + entity_weight * entity_sim
        return text_sim
```

Remove: `_STOP_WORDS`, `_WORD_RE`, `_tokenize`, `_tf_vector`, `_cosine` — all replaced by the model.

**Interface preserved**: `compute_similarity(str, str) -> float`, `compute_embedding(str) -> list[float]`, `entity_overlap_score(set, set) -> float`, `combined_similarity(...)`.

---

### W1.5 — QualityFilterService: language-aware scoring

**File**: `backend/services/orchestration/quality_filter_service.py`

**Change 1** — Add Arabic boilerplate patterns after existing `BOILERPLATE_PATTERNS`:
```python
BOILERPLATE_PATTERNS_AR = [
    re.compile(r"اشترك\s+(الآن|اليوم)", re.IGNORECASE),
    re.compile(r"انقر\s+هنا", re.IGNORECASE),
    re.compile(r"(اشتري|اطلب)\s+(الآن|اليوم)", re.IGNORECASE),
]
```

**Change 2** — In `evaluate()`, extract language and pass to sub-scorers:
```python
def evaluate(self, normalized: dict) -> dict:
    title = normalized.get("title", "")
    content = normalized.get("content", "")
    language = normalized.get("language", "")
    # ... update _caps_score and _boilerplate_score calls ...
```

**Change 3** — Modify `_caps_score` to skip for Arabic:
```python
def _caps_score(self, content: str, language: str = "") -> float:
    if language == "ar":
        return 1.0  # Arabic has no uppercase distinction
    # ... existing logic unchanged ...
```

**Change 4** — Modify `_boilerplate_score` to include Arabic patterns:
```python
def _boilerplate_score(self, content: str, language: str = "") -> float:
    patterns = BOILERPLATE_PATTERNS
    if language == "ar":
        patterns = BOILERPLATE_PATTERNS + BOILERPLATE_PATTERNS_AR
    hits = sum(1 for pat in patterns if pat.search(content))
    # ... rest unchanged ...
```

---

### W1.6 — Verify Wave 1

```bash
docker compose build backend
docker compose up -d backend worker
# Trigger a test ingest of an Arabic RSS source
docker compose exec backend python manage.py shell -c "
from services.orchestration.normalization_service import NormalizationService
ns = NormalizationService()
result = ns.normalize_text('أهلاً بالعالم', lowercase=True)
print('Arabic normalized:', repr(result))
lang = ns._detect_language('هذا نص باللغة العربية لاختبار الكشف عن اللغة')
print('Detected language:', lang)
"
# Expected: Arabic normalized with tashkeel removed, language = 'ar'

docker compose exec backend python manage.py shell -c "
from services.orchestration.semantic_similarity_service import SemanticSimilarityService
sss = SemanticSimilarityService()
emb = sss.compute_embedding('هذا نص عربي')
print('Embedding dim:', len(emb))
sim = sss.compute_similarity('explosion in Baghdad', 'انفجار في بغداد')
print('Cross-lingual similarity:', round(sim, 3))
"
# Expected: dim=384, similarity > 0.3 (semantically related across languages)
```

---

## WAVE 2 — Intelligence Services

> Goal: NER, event classification, dedup, geo-extraction, and OpenSearch indices upgraded. No caller changes.

### W2.1 — EntityExtractionService: LLM-based multilingual NER

**File**: `backend/services/orchestration/entity_extraction_service.py`

**Full replacement** of the service internals. Keep the class name and `extract_and_link` signature.

**Change**: Replace the file content:

```python
from __future__ import annotations

import json
import logging
import re
import unicodedata
from decimal import Decimal

from django.conf import settings

from sources.models import Article, ArticleEntity, Entity

from .entity_resolution_service import EntityResolutionService

logger = logging.getLogger(__name__)


class EntityExtractionService:
    """Extract entities using Groq LLM — multilingual, handles Arabic natively."""

    def __init__(self):
        self.entity_resolution = EntityResolutionService()

    def extract_and_link(self, article: Article) -> list[ArticleEntity]:
        text = f"{article.title}\n{article.content}"[:3000]
        raw_entities = self._extract_via_llm(text)
        if not raw_entities:
            return []

        linked: list[ArticleEntity] = []
        for item in raw_entities:
            name = item.get("name", "").strip()
            entity_type = self._map_type(item.get("type", ""))
            lang = item.get("language", "")
            if not name or not entity_type:
                continue

            normalized = self._normalize_entity_name(name)
            if len(normalized) < 2:
                continue

            canonical = self.entity_resolution.resolve_name(name)
            entity, created = Entity.objects.get_or_create(
                normalized_name=normalized,
                entity_type=entity_type,
                defaults={
                    "name": name,
                    "canonical_name": canonical,
                    "language": lang,
                },
            )
            if not created and not entity.canonical_name:
                self.entity_resolution.resolve_entity(entity)
            if not entity.language and lang:
                entity.language = lang
                entity.save(update_fields=["language", "updated_at"])

            article_entity, _ = ArticleEntity.objects.update_or_create(
                article=article,
                entity=entity,
                defaults={
                    "relevance_score": Decimal("0.70"),
                    "mention_count": 1,
                    "context_snippet": text[:500],
                },
            )
            linked.append(article_entity)

        logger.info("Extracted %d entities from article %s", len(linked), article.id)
        return linked

    def _extract_via_llm(self, text: str) -> list[dict]:
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            logger.warning("GROQ_API_KEY not set — skipping entity extraction")
            return []
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": (
                        "Extract all named entities from the text. "
                        "Return a JSON array of objects with keys: name, type, language. "
                        "type must be one of: person, organization, location. "
                        "language is the ISO 639-1 code of the entity name (e.g. 'ar', 'en'). "
                        "Return ONLY valid JSON, no explanation."
                    )},
                    {"role": "user", "content": text},
                ],
                max_tokens=1000,
                temperature=0.1,
            )
            raw = (response.choices[0].message.content or "").strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3].strip()
            return json.loads(raw)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("LLM entity extraction failed: %s", exc)
            return []

    def _map_type(self, raw_type: str) -> str:
        mapping = {
            "person": Entity.EntityType.PERSON,
            "organization": Entity.EntityType.ORGANIZATION,
            "location": Entity.EntityType.LOCATION,
            "org": Entity.EntityType.ORGANIZATION,
            "loc": Entity.EntityType.LOCATION,
            "per": Entity.EntityType.PERSON,
        }
        return mapping.get(raw_type.lower().strip(), "")

    def _normalize_entity_name(self, name: str) -> str:
        normalized = unicodedata.normalize("NFKC", name)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized
```

**Removed**: `_PROPER_NOUN_RE`, `_ORG_INDICATORS`, `_PERSON_TITLES`, `_LOCATION_INDICATORS`, `_extract_entities` (regex), `_classify_entity` (heuristic), `_compute_relevance`.

**Kept**: `_normalize_entity_name` (reused), `EntityResolutionService` dependency (unchanged).

---

### W2.2 — NarrativeDetectionService: LLM event classification

**File**: `backend/services/orchestration/narrative_detection_service.py`

**Change**: Replace the class while keeping the regex rules as fallback.

Move existing `_RULES` into a `_classify_fallback` method, then make `detect` call LLM first:

```python
from __future__ import annotations

import logging

from django.conf import settings

from sources.models import Article

logger = logging.getLogger(__name__)

_VALID_TYPES = frozenset({
    "strike", "explosion", "protest", "political", "conflict",
    "disaster", "economic", "diplomacy", "crime", "health",
    "technology", "unknown",
})

# Keep existing regex rules as fallback (paste them into _FALLBACK_RULES)
# ... (existing _RULES list stays in the file, renamed to _FALLBACK_RULES) ...


class NarrativeDetectionService:
    """Classify article narrative type via LLM, with regex fallback."""

    def detect(self, article: Article) -> str:
        text = f"{article.title}\n{(article.content or '')[:2000]}"
        result = self._classify_via_llm(text)
        if result and result != "unknown":
            return result
        return self._classify_fallback(text)

    def _classify_via_llm(self, text: str) -> str:
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            return ""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": (
                        "Classify this news article into exactly one event type. "
                        "Choose from: strike, explosion, protest, political, conflict, "
                        "disaster, economic, diplomacy, crime, health, technology, unknown. "
                        "Return ONLY the type label, nothing else."
                    )},
                    {"role": "user", "content": text},
                ],
                max_tokens=20,
                temperature=0.0,
            )
            label = (response.choices[0].message.content or "").strip().lower()
            return label if label in _VALID_TYPES else "unknown"
        except Exception as exc:
            logger.warning("LLM narrative detection failed: %s", exc)
            return ""

    def _classify_fallback(self, text: str) -> str:
        """Regex-based classification (original implementation)."""
        scores: dict[str, float] = {}
        for event_type, weight, pattern in _FALLBACK_RULES:
            matches = pattern.findall(text)
            if matches:
                scores[event_type] = scores.get(event_type, 0.0) + weight * len(matches)
        if not scores:
            return "unknown"
        best_type = max(scores, key=scores.get)
        return best_type if scores[best_type] >= 2.0 else "unknown"
```

Rename existing `_RULES` → `_FALLBACK_RULES` at the top of the file.

---

### W2.3 — DedupService: embedding-based near-duplicate

**File**: `backend/services/orchestration/dedup_service.py`

**Change 1** — Add import and init:
```python
from .semantic_similarity_service import SemanticSimilarityService

class DedupService:
    def __init__(self):
        self.similarity = SemanticSimilarityService()
```

**Change 2** — Replace `_find_near_duplicate` body:
```python
def _find_near_duplicate(self, article: Article) -> Article | None:
    window_start = timezone.now() - timedelta(days=self.window_days)
    candidates = (
        Article.objects.filter(is_duplicate=False, updated_at__gte=window_start)
        .exclude(pk=article.pk)
        .only("id", "normalized_title", "normalized_content", "published_at")
        .order_by("-updated_at")[:self.max_candidates]
    )
    article_text = f"{article.normalized_title} {article.normalized_content[:1000]}"
    article_emb = self.similarity.compute_embedding(article_text)

    for candidate in candidates:
        candidate_text = f"{candidate.normalized_title} {candidate.normalized_content[:1000]}"
        candidate_emb = self.similarity.compute_embedding(candidate_text)
        sim = sum(a * b for a, b in zip(article_emb, candidate_emb))
        if sim >= self.content_similarity_threshold:
            logger.debug(
                "Near-duplicate: article=%s candidate=%s sim=%.2f",
                article.id, candidate.id, sim,
            )
            return candidate
    return None
```

**Keep unchanged**: `_find_exact_hash_duplicate` (fast path), `_find_title_duplicate` (SequenceMatcher for exact title matches), `_find_cluster_duplicate` (update to also use embeddings).

**Change 3** — Also update `_find_cluster_duplicate` to use embeddings:
```python
def _find_cluster_duplicate(self, article: Article) -> Article | None:
    if not article.story_id:
        return None
    siblings = (
        Article.objects.filter(story_id=article.story_id, is_duplicate=False)
        .exclude(pk=article.pk)
        .only("id", "normalized_content", "published_at")
        .order_by("-published_at")[:50]
    )
    article_text = article.normalized_content[:1000]
    article_emb = self.similarity.compute_embedding(article_text)

    for sibling in siblings:
        sibling_emb = self.similarity.compute_embedding(sibling.normalized_content[:1000])
        sim = sum(a * b for a, b in zip(article_emb, sibling_emb))
        if sim >= self.content_similarity_threshold:
            return sibling
    return None
```

---

### W2.4 — GeoExtractionService: Arabic gazetteer

**File**: `backend/services/orchestration/geo_extraction_service.py`

**Change**: Add Arabic entries to `_GEO_GAZETTEER` dict. Insert after the existing English entries:

```python
# ── Arabic equivalents ────────────────────────────────────────────────────
"غزة": ("PS", 31.5, 34.47),
"قطاع غزة": ("PS", 31.4, 34.39),
"الضفة الغربية": ("PS", 31.95, 35.3),
"رام الله": ("PS", 31.9, 35.2),
"القدس": ("IL", 31.77, 35.23),
"تل أبيب": ("IL", 32.09, 34.78),
"بيروت": ("LB", 33.89, 35.5),
"دمشق": ("SY", 33.51, 36.29),
"حلب": ("SY", 36.2, 37.15),
"بغداد": ("IQ", 33.31, 44.37),
"طهران": ("IR", 35.69, 51.39),
"الرياض": ("SA", 24.71, 46.67),
"القاهرة": ("EG", 30.04, 31.24),
"عمّان": ("JO", 31.95, 35.93),
"صنعاء": ("YE", 15.37, 44.19),
"عدن": ("YE", 12.78, 45.03),
"الدوحة": ("QA", 25.29, 51.53),
"دبي": ("AE", 25.2, 55.27),
"أبو ظبي": ("AE", 24.45, 54.65),
"مسقط": ("OM", 23.61, 58.54),
"مدينة الكويت": ("KW", 29.37, 47.98),
"المنامة": ("BH", 26.23, 50.59),
"طرابلس": ("LY", 32.9, 13.18),
"بنغازي": ("LY", 32.12, 20.09),
"تونس": ("TN", 36.81, 10.18),
"الجزائر": ("DZ", 36.75, 3.04),
"الرباط": ("MA", 34.01, -6.84),
"الدار البيضاء": ("MA", 33.57, -7.59),
"الخرطوم": ("SD", 15.59, 32.53),
"موسكو": ("RU", 55.76, 37.62),
"كييف": ("UA", 50.45, 30.52),
"أنقرة": ("TR", 39.93, 32.85),
"إسطنبول": ("TR", 41.01, 28.98),
"بكين": ("CN", 39.9, 116.4),
"طوكيو": ("JP", 35.68, 139.69),
"نيودلهي": ("IN", 28.61, 77.21),
"إسلام آباد": ("PK", 33.69, 73.04),
"كابل": ("AF", 34.53, 69.17),
"واشنطن": ("US", 38.91, -77.04),
"نيويورك": ("US", 40.71, -74.01),
# Arabic country names
"أوكرانيا": ("UA", 48.38, 31.17),
"روسيا": ("RU", 61.52, 105.32),
"سوريا": ("SY", 34.8, 38.99),
"العراق": ("IQ", 33.22, 43.68),
"إيران": ("IR", 32.43, 53.69),
"اليمن": ("YE", 15.55, 48.52),
"لبنان": ("LB", 33.85, 35.86),
"إسرائيل": ("IL", 31.05, 34.85),
"فلسطين": ("PS", 31.95, 35.23),
"مصر": ("EG", 26.82, 30.8),
"ليبيا": ("LY", 26.34, 17.23),
"السودان": ("SD", 12.86, 30.22),
"أفغانستان": ("AF", 33.94, 67.71),
"باكستان": ("PK", 30.38, 69.35),
"الصين": ("CN", 35.86, 104.2),
"تايوان": ("TW", 23.7, 120.96),
"كوريا الشمالية": ("KP", 40.34, 127.51),
"كوريا الجنوبية": ("KR", 35.91, 127.77),
```

No other changes needed to geo extraction. The gazetteer lookup is already language-agnostic (substring match on lowered text).

---

### W2.5 — OpenSearch indices: Arabic analyzer + k-NN + language field

**File**: `backend/services/orchestration/opensearch_service.py`

**Change 1** — Replace `ARTICLE_MAPPING`:

```python
ARTICLE_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "index.knn": True,
        "analysis": {
            "analyzer": {
                "content_analyzer_en": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                },
                "content_analyzer_ar": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "arabic_normalization", "arabic_stemmer"],
                },
            },
            "filter": {
                "arabic_stemmer": {
                    "type": "stemmer",
                    "language": "arabic",
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "article_id": {"type": "integer"},
            "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "title_en": {"type": "text", "analyzer": "content_analyzer_en"},
            "title_ar": {"type": "text", "analyzer": "content_analyzer_ar"},
            "content": {"type": "text"},
            "content_en": {"type": "text", "analyzer": "content_analyzer_en"},
            "content_ar": {"type": "text", "analyzer": "content_analyzer_ar"},
            "language": {"type": "keyword"},
            "url": {"type": "keyword"},
            "author": {"type": "keyword"},
            "source_id": {"type": "integer"},
            "source_name": {"type": "keyword"},
            "source_country": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "story_id": {"type": "integer"},
            "story_title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "event_id": {"type": "integer"},
            "event_type": {"type": "keyword"},
            "published_at": {"type": "date"},
            "quality_score": {"type": "float"},
            "importance_score": {"type": "float"},
            "is_duplicate": {"type": "boolean"},
            "entity_names": {"type": "keyword"},
            "entity_types": {"type": "keyword"},
            "matched_topics": {"type": "keyword"},
            "matched_rule_labels": {"type": "keyword"},
            "content_hash": {"type": "keyword"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 384,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib",
                },
            },
            "indexed_at": {"type": "date"},
        },
    },
}
```

**Change 2** — Update `_article_to_doc` to include new fields:

Add after the existing `"content"` line:
```python
"language": getattr(article, "language", ""),
"title_en": article.title if getattr(article, "language", "") != "ar" else "",
"title_ar": article.title if getattr(article, "language", "") == "ar" else "",
"content_en": (article.content or "")[:10000] if getattr(article, "language", "") != "ar" else "",
"content_ar": (article.content or "")[:10000] if getattr(article, "language", "") == "ar" else "",
```

Add embedding computation:
```python
"embedding": self._compute_embedding(article),
```

Add helper method:
```python
def _compute_embedding(self, article) -> list[float] | None:
    try:
        from services.orchestration.semantic_similarity_service import SemanticSimilarityService
        svc = SemanticSimilarityService()
        text = f"{article.title} {(article.content or '')[:1000]}"
        return svc.compute_embedding(text)
    except Exception:
        logger.debug("Embedding computation failed for article %s", article.id)
        return None
```

**Change 3** — Update `search_articles` to use language-specific fields:

In the `multi_match` query, update `fields`:
```python
"fields": ["title^3", "title_en^3", "title_ar^3", "content", "content_en", "content_ar", "story_title", "entity_names^2"],
```

**Change 4** — Add index migration management command:

**New file**: `backend/sources/management/commands/reindex_opensearch.py`
```python
"""Management command to recreate OpenSearch indices with new mappings."""
from django.core.management.base import BaseCommand
from services.orchestration.opensearch_service import OpenSearchService, ARTICLE_INDEX, EVENT_INDEX

class Command(BaseCommand):
    help = "Delete and recreate OpenSearch indices with updated mappings."

    def handle(self, *args, **options):
        svc = OpenSearchService()
        adapter = svc._adapter
        for idx in [ARTICLE_INDEX, EVENT_INDEX]:
            if adapter._client.indices.exists(index=idx):
                adapter._client.indices.delete(index=idx)
                self.stdout.write(f"Deleted index {idx}")
        svc.ensure_indices()
        self.stdout.write(self.style.SUCCESS("Indices recreated. Run reindex task to populate."))
```

---

### W2.6 — Verify Wave 2

```bash
docker compose build backend
docker compose up -d backend worker

# Test entity extraction
docker compose exec backend python manage.py shell -c "
from services.orchestration.entity_extraction_service import EntityExtractionService
from sources.models import Article
art = Article.objects.filter(content__gt='').first()
if art:
    svc = EntityExtractionService()
    entities = svc.extract_and_link(art)
    for e in entities:
        print(f'  {e.entity.name} ({e.entity.entity_type}) lang={e.entity.language}')
"

# Recreate OpenSearch indices
docker compose exec backend python manage.py reindex_opensearch

# Test search
docker compose exec backend python manage.py shell -c "
from services.orchestration.opensearch_service import OpenSearchService
svc = OpenSearchService()
svc.ensure_indices()
print('Indices OK')
"
```

---

## WAVE 3 — Higher-Order Services

> Goal: Contradiction detection via LLM, Arabic-native AI summaries, language-aware translation. Automatic improvements to story clustering and event resolution (no code changes — they benefit from rebuilt dependencies).

### W3.1 — NarrativeConflictService: LLM contradiction detection

**File**: `backend/services/orchestration/narrative_conflict_service.py`

**Change**: Rewrite `detect()` to call LLM with heuristic fallback.

Keep existing `_NEGATION_PHRASES`, `_CONFLICTING_CLAIM_PHRASE`, `_count_contradiction_signals`, `_average_pairwise_similarity` as `_heuristic_detect` fallback.

```python
class NarrativeConflictService:
    MIN_ARTICLES = 2

    def __init__(self):
        self.similarity = SemanticSimilarityService()

    def detect(self, event: Event) -> bool:
        articles = list(
            Article.objects.filter(story__event=event, is_duplicate=False)
            .select_related("source")[:100]
        )
        if len(articles) < self.MIN_ARTICLES:
            if event.conflict_flag:
                event.conflict_flag = False
                event.save(update_fields=["conflict_flag", "updated_at"])
            return False

        # Try LLM-based detection
        has_conflict = self._detect_via_llm(articles)
        if has_conflict is None:
            # Fallback to heuristic
            has_conflict = self._heuristic_detect(articles)

        if has_conflict != event.conflict_flag:
            event.conflict_flag = has_conflict
            event.save(update_fields=["conflict_flag", "updated_at"])

        if has_conflict:
            logger.warning("Event %s flagged for narrative conflict", event.id)
        return has_conflict

    def _detect_via_llm(self, articles: list[Article]) -> bool | None:
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

            summaries = []
            for a in articles[:10]:
                summaries.append(f"Source: {a.source.name if a.source else 'Unknown'}\n{a.title}\n{(a.content or '')[:500]}")

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": (
                        "You are analyzing news articles about the same event from multiple sources. "
                        "Do any of these sources directly contradict each other on key facts? "
                        "Answer ONLY 'yes' or 'no'."
                    )},
                    {"role": "user", "content": "\n---\n".join(summaries)},
                ],
                max_tokens=10,
                temperature=0.0,
            )
            answer = (response.choices[0].message.content or "").strip().lower()
            return answer.startswith("yes")
        except Exception as exc:
            logger.warning("LLM conflict detection failed: %s", exc)
            return None

    def _heuristic_detect(self, articles: list[Article]) -> bool:
        """Original heuristic: negation patterns + similarity divergence."""
        total_signals = 0
        for article in articles:
            text = f"{article.title} {article.content}"
            total_signals += self._count_contradiction_signals(text)
        avg_similarity = self._average_pairwise_similarity(articles)
        return avg_similarity < 0.35 and total_signals >= 2
```

Add `from django.conf import settings` to imports.

---

### W3.2 — AI Summary: Arabic-native prompts

**File**: `backend/services/ai_summary_service.py`

**Change**: Modify the `SYSTEM_PROMPT` to be language-aware. Replace the hardcoded English prompt with a function:

```python
def _get_system_prompt(article: Article) -> str:
    lang = getattr(article, "language", "")
    if lang == "ar":
        return (
            "أنت محلل استخباراتي خبير ومتنبئ جيوسياسي. "
            "بالنظر إلى مقال إخباري، قدم:\n\n"
            "1. **ملخص شامل**: ملخص مفصل ومنظم يغطي الحقائق الرئيسية والأطراف المعنية "
            "والسياق والخلفية وأهمية الخبر.\n\n"
            "2. **التوقعات والتنبؤات**: بناءً على المعلومات، قدم تحليلات تنبؤية مفصلة:\n"
            "   - ماذا سيحدث على الأرجح على المدى القصير؟\n"
            "   - ما العواقب على المدى المتوسط؟\n"
            "   - ما التداعيات المحتملة على المدى البعيد؟\n"
            "   - ما السيناريوهات الممكنة (أفضل حالة، أسوأ حالة، الأكثر احتمالاً)؟\n\n"
            "صيغة الرد:\n"
            "## الملخص\n<الملخص هنا>\n\n"
            "## التوقعات\n<التوقعات هنا>\n\n"
            "اكتب باللغة العربية. كن شاملاً."
        )
    return SYSTEM_PROMPT  # existing English prompt
```

**Change 2** — In `generate_ai_summary`, replace:
```python
{"role": "system", "content": SYSTEM_PROMPT},
```
with:
```python
{"role": "system", "content": _get_system_prompt(article)},
```

**Change 3** — Skip Arabic auto-translation when article is already Arabic:
```python
# Auto-translate to Arabic (only if source is not Arabic)
if getattr(article, "language", "") != "ar":
    summary_ar, predictions_ar = _translate_to_arabic(summary_text, predictions_text)
    summary_obj.summary_ar = summary_ar
    summary_obj.predictions_ar = predictions_ar
else:
    # Article is Arabic — summary is already in Arabic, translate to English
    summary_obj.summary_ar = summary_text
    summary_obj.predictions_ar = predictions_text
```

---

### W3.3 — Intel Assessment: Arabic-native prompts

**File**: `backend/services/intel_assessment_service.py`

**Change 1** — In `_build_user_prompt`, detect majority language of articles:
```python
def _build_user_prompt(event: Event, articles: list[Article]) -> str:
    # Detect majority language
    ar_count = sum(1 for a in articles if getattr(a, "language", "") == "ar")
    is_arabic_dominant = ar_count > len(articles) / 2

    parts = [
        f"EVENT: {event.title}",
        # ... existing ...
    ]

    if is_arabic_dominant:
        parts.insert(0, "⚠️ RESPOND IN ARABIC. The majority of articles are in Arabic.")

    # ... rest unchanged ...
```

**Change 2** — In `_translate_fields`, skip Arabic translation if the assessment is already in Arabic:
```python
def _translate_fields(obj: EventIntelAssessment) -> None:
    # Check if the summary is already in Arabic
    summary_text = obj.summary or ""
    arabic_chars = sum(1 for c in summary_text if '\u0600' <= c <= '\u06FF')
    if arabic_chars > len(summary_text) * 0.3:
        # Already Arabic — copy to _ar fields directly
        for src_field, dst_field in fields:
            setattr(obj, dst_field, getattr(obj, src_field, "") or "")
        return
    # ... existing translation logic ...
```

---

### W3.4 — Translation Service: language-first

**File**: `backend/services/translation_service.py`

**Change**: In `translate_article`, detect source language and skip if already target:

```python
def translate_article(article: Article, target_language: str = "ar") -> ArticleTranslation:
    # Skip if article is already in the target language
    source_lang = getattr(article, "language", "")
    if source_lang == target_language:
        # Create a "translation" that's just the original text
        translation, _created = ArticleTranslation.objects.get_or_create(
            article=article,
            language_code=target_language,
            defaults={
                "translated_title": article.title,
                "translated_body": article.content or article.normalized_content or "",
                "translation_status": ArticleTranslation.TranslationStatus.COMPLETED,
                "translated_at": timezone.now(),
                "provider": "native",
            },
        )
        return translation

    # ... existing translation logic, but pass source language explicitly ...
    translator = GoogleTranslator(source=source_lang or "auto", target=target_language)
    # ... rest unchanged ...
```

---

### W3.5 — Verify Wave 3

```bash
docker compose build backend
docker compose up -d backend worker

# Story clustering & event resolution: no code changes needed — just verify
docker compose exec backend python manage.py shell -c "
from services.orchestration.narrative_conflict_service import NarrativeConflictService
from sources.models import Event
svc = NarrativeConflictService()
event = Event.objects.first()
if event:
    result = svc.detect(event)
    print(f'Event {event.id}: conflict={result}')
"
```

---

## WAVE 4 — Security & Tuning

> Goal: JWT authentication enforced, RBAC wired, Celery schedule tuned.

### W4.1 — JWT Authentication

**File**: `backend/config/settings/base.py`

**Change 1** — Replace REST_FRAMEWORK config:
```python
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}
```

**Change 2** — Add SimpleJWT config after REST_FRAMEWORK:
```python
from datetime import timedelta  # add to file-level imports

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}
```

---

### W4.2 — Auth URL routes

**File**: `backend/config/urls.py`

**Change**: Add token endpoints:
```python
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

# Add to urlpatterns:
path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
```

---

### W4.3 — Health/prometheus endpoints stay public

**File**: `backend/core/views.py` (or wherever health endpoints are defined)

Ensure health check views have:
```python
from rest_framework.permissions import AllowAny

class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    # ...
```

Also ensure `django_prometheus.urls` remain public (they don't use DRF).

---

### W4.4 — Celery Beat schedule tuning

**File**: `backend/config/settings/base.py`

**Changes to CELERY_BEAT_SCHEDULE**:
- `"refresh-event-intelligence"`: `900.0` → `1800.0` (15 min → 30 min, LLM calls are costlier)
- `"run-anomaly-detection"`: `600.0` → `900.0` (10 min → 15 min)
- No other changes — remaining schedules are reasonable

---

### W4.5 — Verify Wave 4

```bash
docker compose build backend
docker compose up -d

# Test JWT auth flow
curl -X POST http://localhost/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'
# Expected: {"access": "...", "refresh": "..."}

# Test authenticated request
TOKEN=$(curl -s -X POST http://localhost/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | python -c "import sys,json; print(json.load(sys.stdin)['access'])")

curl -H "Authorization: Bearer $TOKEN" http://localhost/api/v1/articles/
# Expected: 200 OK with articles

# Test unauthenticated request is rejected
curl http://localhost/api/v1/articles/
# Expected: 401 Unauthorized

# Test health endpoint stays public
curl http://localhost/api/v1/system/health/
# Expected: 200 OK
```

---

## File Change Summary

| Wave | File | Action | Lines Changed (est.) |
|------|------|--------|---------------------|
| W0 | `backend/requirements/prod.txt` | Append 4 lines | 4 |
| W0 | `backend/Dockerfile` | Add 2 RUN lines | 4 |
| W0 | `backend/sources/models.py` | Add 2 fields | 16 |
| W1 | `backend/services/orchestration/normalization_service.py` | Add methods, modify normalize | 40 |
| W1 | `backend/services/orchestration/raw_item_service.py` | Add 1 field to defaults | 1 |
| W1 | `backend/services/orchestration/article_parse_service.py` | Replace _parse_html | 25 |
| W1 | `backend/services/orchestration/semantic_similarity_service.py` | Full rewrite | 55→45 |
| W1 | `backend/services/orchestration/quality_filter_service.py` | Add Arabic patterns, lang param | 15 |
| W2 | `backend/services/orchestration/entity_extraction_service.py` | Full rewrite | 120→95 |
| W2 | `backend/services/orchestration/narrative_detection_service.py` | Add LLM path + fallback | 50 |
| W2 | `backend/services/orchestration/dedup_service.py` | Embedding-based methods | 30 |
| W2 | `backend/services/orchestration/geo_extraction_service.py` | Add ~55 Arabic gazetteer entries | 55 |
| W2 | `backend/services/orchestration/opensearch_service.py` | New mapping + doc builder + helper | 60 |
| W2 | `backend/sources/management/commands/reindex_opensearch.py` | New file | 15 |
| W3 | `backend/services/orchestration/narrative_conflict_service.py` | Add LLM path + fallback | 40 |
| W3 | `backend/services/ai_summary_service.py` | Arabic prompt + skip logic | 30 |
| W3 | `backend/services/intel_assessment_service.py` | Arabic detection + skip logic | 20 |
| W3 | `backend/services/translation_service.py` | Language-first skip | 15 |
| W4 | `backend/config/settings/base.py` | JWT config + schedule tuning | 20 |
| W4 | `backend/config/urls.py` | Add 2 URL patterns | 5 |
| W4 | `backend/core/views.py` | Add AllowAny to health views | 3 |

**Total**: ~20 files modified, 1 new file, ~570 lines changed.

---

## Rollback Strategy

Each wave is independently rollback-safe:

- **W0**: `pip install -r` original requirements, `migrate` is additive (new columns stay, unused)
- **W1-W3**: Revert service files to git HEAD. Callers unchanged → no cascade.
- **W4**: Revert `base.py` REST_FRAMEWORK to `AllowAny` + remove JWT urls. Instant rollback.

Git branch strategy:
```bash
git checkout -b phase4-implementation
# Do all wave work on this branch
# After each wave: git commit -m "Wave N: description"
# After all waves: PR to main
```

---

## What We Do NOT Touch

- All 25+ orchestration files (except the 5 being rebuilt)
- All 6 connector/adapter files
- All Django model files (except 2 field additions)
- All API views and serializers (except permission class)
- All URL routing (except 2 new auth routes)
- Docker-compose topology (same 15 containers)
- Frontend (no changes)
- Crawlers (no changes)
- Neo4j, MinIO, Redis, Prometheus, Grafana, Loki config

---

> **STOP — Phase 3 complete. Awaiting approval before proceeding to Phase 4 (Implementation).**
