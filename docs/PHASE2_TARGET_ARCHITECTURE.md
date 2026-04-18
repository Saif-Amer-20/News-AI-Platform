# Phase 2 — Target Architecture Redesign

> **Status**: Pending approval  
> **Depends on**: Phase 1 Audit Report (`docs/PHASE1_AUDIT_REPORT.md`) — APPROVED  
> **Next**: Phase 3 (Implementation Plan) — blocked until this document is approved  

---

## 1. Architecture Principles

| # | Principle | Rationale |
|---|-----------|-----------|
| 1 | **Language-first** | Every text-processing path must handle Arabic natively, not via post-hoc translation. |
| 2 | **Interface-preserving swaps** | All 5 REBUILD and 15 REWORK targets preserve their existing public method signatures. Callers do not change. |
| 3 | **LLM for reasoning, local models for volume** | Use Groq API (already integrated) for NER, event classification, contradiction detection. Use local `sentence-transformers` for embeddings (high call volume). |
| 4 | **Pre-compute and cache** | Compute article embeddings once on ingest; store in OpenSearch k-NN index. Never recompute. |
| 5 | **Minimal new infrastructure** | No new Docker containers. Add Python packages only. One new ML model download (~120 MB) baked into the Docker image. |

---

## 2. New Python Dependencies

| Package | Version | Purpose | Replaces |
|---------|---------|---------|----------|
| `langdetect` | 1.0.9 | Language detection on ingest | Nothing (new capability) |
| `sentence-transformers` | 3.3.1 | Multilingual embeddings (local model) | TF-IDF cosine in `SemanticSimilarityService` |
| `trafilatura` | 2.0.0 | Robust article content extraction | BeautifulSoup `<p>` parsing in `ArticleParseService` |
| `djangorestframework-simplejwt` | 5.4.0 | JWT authentication | `AllowAny` permissions |
| `torch` | 2.4.1+cpu | PyTorch CPU runtime (dependency of sentence-transformers) | — |

**Removed**: None. `beautifulsoup4` stays (trafilatura falls back to raw HTML when needed; BS4 is still used by crawlers).

**Docker image change**: Add to `backend/Dockerfile` a model download step:
```dockerfile
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"
```
This caches the 120 MB model at build time. No runtime download.

---

## 3. Data Model Changes

### 3.1 Article model — add `language` field

```python
# sources/models.py — Article class
language = models.CharField(
    max_length=8,
    blank=True,
    db_index=True,
    help_text="ISO 639-1 language code detected on ingest (e.g. 'ar', 'en').",
)
```

**Migration**: `0002_article_language.py` — `AddField`, nullable=False default=`""`, backfill existing rows via `RunPython` using `langdetect` on `content`.

### 3.2 Entity model — add `language` field

```python
# sources/models.py — Entity class
language = models.CharField(
    max_length=8,
    blank=True,
    db_index=True,
    help_text="Language of the entity name.",
)
```

**Migration**: `0003_entity_language.py` — `AddField`, default=`""`.

### 3.3 No other model changes

All other fields, relationships, and constraints remain identical. The `metadata` JSONField on Article is already available for storing embedding vectors if needed (but we prefer OpenSearch k-NN for vector storage — see §6).

---

## 4. REBUILD Specifications (5 components)

### 4.1 EntityExtractionService — LLM-based Multilingual NER

**Current**: Regex `[A-Z][a-z]+` pattern matching. English-only. Misses all Arabic entities.

**Target**: Groq LLM-based entity extraction. One API call per article extracts all entities with types and language.

**Interface** (preserved):
```python
class EntityExtractionService:
    def extract_and_link(self, article: Article) -> list[ArticleEntity]:
```

**Internal design**:

```
extract_and_link(article)
  ├─ Build prompt with article.title + article.content[:3000]
  ├─ Call Groq API (llama-3.3-70b-versatile)
  │   System: "Extract named entities. Return JSON array."
  │   User: "Title: {title}\nContent: {content}\n\nExtract all persons, organizations, and locations. Return JSON: [{name, type, language}]"
  ├─ Parse JSON response
  ├─ For each entity:
  │   ├─ Normalize name (NFKC + lowered for matching)
  │   ├─ Entity.objects.get_or_create(normalized_name, entity_type)
  │   ├─ Set entity.language from LLM response
  │   └─ ArticleEntity.objects.update_or_create(article, entity)
  └─ Return list[ArticleEntity]
```

**Why LLM over local NER models**:
- Arabic NER libraries (CAMeL, Stanza) require ~500 MB+ model downloads each
- LLM handles Arabic, English, French, Turkish, etc. in one call
- Cost: ~$0.001/article via Groq (llama-3.3-70b at $0.59/M input tokens, ~1500 tokens/article)
- At 500 articles/day = $0.50/day
- The existing `GroqAdapter` and `GroqService` are already production-ready

**Entity Resolution**: Keep `EntityResolutionService` as-is (it resolves canonical names). Call it after LLM extraction.

**Fallback**: If Groq API fails, log error and return empty list (same as current behavior on regex failure). The caller (`ingest_orchestration.py`) already handles empty entity lists gracefully.

---

### 4.2 SemanticSimilarityService — Multilingual Embeddings

**Current**: TF-IDF cosine similarity with English-only stop words. `compute_embedding()` returns a 128-dim hash vector (placeholder).

**Target**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` for real 384-dim multilingual embeddings. Cosine similarity on dense vectors.

**Interface** (preserved):
```python
class SemanticSimilarityService:
    def compute_similarity(self, text_a: str, text_b: str) -> float:
    def compute_embedding(self, text: str) -> list[float]:
    def entity_overlap_score(self, entities_a: set[str], entities_b: set[str]) -> float:
    def combined_similarity(self, text_a, text_b, entities_a, entities_b, ...) -> float:
```

**Internal design**:

```python
from sentence_transformers import SentenceTransformer

class SemanticSimilarityService:
    _model = None  # Lazy singleton

    @classmethod
    def _get_model(cls):
        if cls._model is None:
            cls._model = SentenceTransformer(
                'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
            )
        return cls._model

    def compute_embedding(self, text: str) -> list[float]:
        model = self._get_model()
        # Truncate to model's max input (128 tokens ≈ 512 chars)
        embedding = model.encode(text[:2000], normalize_embeddings=True)
        return embedding.tolist()

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        emb_a = self.compute_embedding(text_a)
        emb_b = self.compute_embedding(text_b)
        # Cosine similarity of normalized vectors = dot product
        return sum(a * b for a, b in zip(emb_a, emb_b))
```

**Key changes**:
- `compute_embedding()` returns real 384-dim vectors instead of 128-dim hash
- `compute_similarity()` uses dense vector cosine instead of TF-IDF
- `entity_overlap_score()` unchanged (Jaccard is language-agnostic)
- `combined_similarity()` unchanged (weights text + entity scores)
- Model loads lazily on first call, stays in memory (~120 MB)

**Callers** (5 services, no changes needed):
- `event_resolution_service.py` → `compute_similarity()`
- `event_confidence_service.py` → `compute_similarity()`
- `narrative_conflict_service.py` → `compute_similarity()`
- `temporal_evolution_service.py` → `compute_similarity()`
- `story_clustering_orchestration.py` → `compute_similarity()`

---

### 4.3 NarrativeDetectionService — LLM Event Classification

**Current**: 40 English regex rules mapping keywords to 10 event types. Returns `"unknown"` for any Arabic text.

**Target**: Groq LLM-based event classification. One API call per article.

**Interface** (preserved):
```python
class NarrativeDetectionService:
    def detect(self, article: Article) -> str:
```

**Internal design**:

```
detect(article)
  ├─ text = f"{article.title} {article.content[:2000]}"
  ├─ Call Groq API:
  │   System: "Classify the article into exactly one event type. 
  │            Choose from: strike, explosion, protest, political, conflict, 
  │            disaster, economic, diplomacy, crime, health, technology, unknown.
  │            Return ONLY the type label, nothing else."
  │   User: text
  ├─ Validate response ∈ known types
  └─ Return type string (or "unknown" on failure)
```

**Cost**: Same as NER — ~$0.001/article. Combined NER + classification could be merged into a single API call to halve costs (optimization for Phase 4).

**Fallback**: On API failure, fall back to the existing regex rules (keep them as `_classify_fallback()`). This provides graceful degradation.

**Caller**: `event_resolution_service.py` — no changes needed.

---

### 4.4 NarrativeConflictService — LLM Contradiction Detection

**Current**: English negation regex patterns (`denied`, `refuted`, `disputed`, etc.) + TF-IDF divergence check.

**Target**: LLM-based contradiction detection. One API call per event (not per article).

**Interface** (preserved):
```python
class NarrativeConflictService:
    def detect(self, event: Event) -> bool:
```

**Internal design**:

```
detect(event)
  ├─ Collect up to 10 non-duplicate articles for the event
  ├─ If < 2 articles → return False (unchanged)
  ├─ Build summaries: [f"Source: {a.source.name}\n{a.title}\n{a.content[:500]}" for a in articles]
  ├─ Call Groq API:
  │   System: "You are analyzing news articles about the same event.
  │            Do any of these sources directly contradict each other on key facts?
  │            Answer ONLY 'yes' or 'no'."
  │   User: joined summaries
  ├─ Parse response → bool
  ├─ Update event.conflict_flag if changed
  └─ Return bool
```

**Cost**: One call per event refresh cycle. Events refresh every 30 min. With ~50 active events, that's ~50 calls/30 min = $0.05/day.

**Fallback**: On API failure, fall back to pairwise similarity divergence check (keep existing `_average_pairwise_similarity()` and `_count_contradiction_signals()` as `_heuristic_fallback()`).

**Caller**: `event_resolution_service._run_intelligence()` — no changes.

---

### 4.5 Authentication — JWT + RBAC Enforcement

**Current**: All API views use `AllowAny`. RBAC code exists in `accounts/rbac.py` with 4 roles (`intel_analyst`, `intel_manager`, `ops_operator`, `platform_admin`) and full permission matrices — but none of it is wired.

**Target**: JWT-based authentication with role enforcement.

**Changes**:

1. **Settings** (`config/settings/base.py`):
```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}
```

2. **URL routes** (`config/urls.py`):
```python
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns += [
    path("api/auth/token/", TokenObtainPairView.as_view()),
    path("api/auth/token/refresh/", TokenRefreshView.as_view()),
]
```

3. **View-level permissions**: Replace `AllowAny` with `IsAuthenticated` (default) and add `DjangoModelPermissions` on model viewsets to enforce the existing RBAC permission matrix.

4. **Health endpoints** remain `AllowAny` (they already are in `core/views.py`).

5. **`bootstrap_rbac` command**: Already exists at `accounts/management/commands/bootstrap_rbac.py`. No changes needed — it creates groups and assigns permissions from `DEFAULT_GROUP_PERMISSIONS`.

---

## 5. REWORK Specifications (15 components)

### 5.1 Article Model — Language Detection on Ingest

**Change**: Add `language` field (§3.1). Set it during normalization.

**Where**: `NormalizationService.normalize()` — add language detection:
```python
from langdetect import detect as detect_lang

def normalize(self, raw_item, parsed_candidate) -> dict:
    # ... existing normalization ...
    content = self.normalize_text(parsed_candidate.content or raw_item.content_raw)
    language = self._detect_language(content)
    return {
        # ... existing fields ...
        "language": language,
    }

def _detect_language(self, text: str) -> str:
    try:
        return detect_lang(text[:1000]) if len(text) >= 20 else ""
    except Exception:
        return ""
```

The `language` value flows from normalization → article creation in `ingest_orchestration.py` (which already unpacks the normalized dict into Article fields).

---

### 5.2 Entity Model — Language Field

**Change**: Add `language` field (§3.2). Set by `EntityExtractionService` from LLM response (see §4.1).

No separate rework — handled by the EntityExtraction REBUILD.

---

### 5.3 Topic System — Arabic Keyword Support

**Current**: `KeywordRule` model stores keywords in `KeywordRule.pattern` (regex). `TopicMatchingService` runs these patterns against `article.normalized_title` and `article.normalized_content`.

**Issue**: Keywords are authored in English. If a topic tracks "وزارة الدفاع" (Ministry of Defense), the English pattern `ministry.*defense` won't match Arabic content.

**Change**: No code change to `TopicMatchingService` — it already does regex matching, which works on any Unicode text. The change is **operational**: instruct users to add Arabic keyword patterns alongside English ones.

Add a helper method to `TopicMatchingService`:
```python
def _normalize_arabic(self, text: str) -> str:
    """Normalize common Arabic character variants for matching."""
    replacements = {
        'أ': 'ا', 'إ': 'ا', 'آ': 'ا',  # Alef variants → bare Alef
        'ة': 'ه',  # Ta marbuta → Ha
        'ى': 'ي',  # Alef maqsura → Ya
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Strip tashkeel (diacritical marks)
    import re
    text = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]', '', text)
    return text
```

Apply this normalization in `NormalizationService.normalize_text()` when the detected language is Arabic, so both `normalized_title` and `normalized_content` are Arabic-normalized.

---

### 5.4 ArticleParseService — Trafilatura Content Extraction

**Current**: BeautifulSoup `<p>` tag extraction from HTML. Misses content outside `<p>` tags. No boilerplate removal.

**Change**: Replace `_extract_content_from_soup()` with `trafilatura.extract()`:

```python
import trafilatura

def _parse_html(self, raw_item: RawItem):
    html = raw_item.html_raw
    # trafilatura: robust content extraction with boilerplate removal
    content = trafilatura.extract(html, favor_precision=True) or ""
    # Fallback to existing BS4 logic if trafilatura returns empty
    if not content:
        soup = BeautifulSoup(html, "lxml")
        content = self._extract_content_from_soup(soup) or clean_text(raw_item.content_raw)
    # Title, author, date, image: keep existing BS4 extraction (reliable for metadata)
    soup = BeautifulSoup(html, "lxml")
    title = self._extract_title_from_soup(soup) or clean_text(raw_item.title_raw)
    published_at = self._extract_published_from_soup(soup) or parse_datetime_value(raw_item.metadata.get("published_at"))
    author = self._extract_author_from_soup(soup) or clean_text(raw_item.metadata.get("author"))
    image_url = self._extract_image_from_soup(soup) or raw_item.metadata.get("image_url", "")
    return title, content, published_at, author, image_url
```

**Interface**: `parse(raw_item) -> ParsedArticleCandidate` — unchanged.

---

### 5.5 NormalizationService — Arabic Text Normalization

**Current**: `unicodedata.normalize("NFKC", ...)` + lowercase. No Arabic-specific normalization.

**Change**: Add Arabic normalization in `normalize_text()`:

```python
def normalize_text(self, value: str, *, lowercase: bool = False, language: str = "") -> str:
    normalized = unicodedata.normalize("NFKC", clean_text(value))
    if language == "ar" or self._looks_arabic(normalized):
        normalized = self._normalize_arabic(normalized)
    return normalized.lower() if lowercase else normalized

def _looks_arabic(self, text: str) -> bool:
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    return arabic_chars > len(text) * 0.3

def _normalize_arabic(self, text: str) -> str:
    # Alef variants → bare Alef
    text = text.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
    # Ta marbuta → Ha
    text = text.replace('ة', 'ه')
    # Alef maqsura → Ya
    text = text.replace('ى', 'ي')
    # Strip tashkeel
    import re
    text = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]', '', text)
    return text
```

This ensures `normalized_title` and `normalized_content` are properly normalized for Arabic, improving dedup matching, topic matching, and search quality.

---

### 5.6 DedupService — Embedding-Based Near-Duplicate Detection

**Current**: `SequenceMatcher` on `normalized_title` and `normalized_content[:2000]`. O(n) scan against 200 candidates. Slow and inaccurate for multilingual content.

**Change**: Replace `SequenceMatcher` comparisons with embedding cosine similarity:

```python
class DedupService:
    def __init__(self):
        self.similarity = SemanticSimilarityService()

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
                return candidate
        return None
```

**Keep**: `_find_exact_hash_duplicate()` (fast path, language-agnostic). `_find_title_duplicate()` with `SequenceMatcher` is kept as a fast pre-filter before embedding comparison.

**Future optimization** (Phase 4+): Store embeddings in OpenSearch k-NN and use approximate nearest neighbor search instead of O(n) scan. This eliminates the candidate loop entirely.

---

### 5.7 StoryClusteringOrchestration — Benefits Automatically

**Current**: Uses `SemanticSimilarityService.compute_similarity()` and `.entity_overlap_score()` for clustering decisions.

**No direct changes needed**. When `SemanticSimilarityService` is rebuilt (§4.2), story clustering automatically gets multilingual similarity scoring. The clustering logic itself (threshold-based assignment, new-story creation) is sound.

---

### 5.8 EventResolutionService — Benefits Automatically

**Current**: Calls `NarrativeDetectionService.detect()`, `NarrativeConflictService.detect()`, `SemanticSimilarityService.compute_similarity()`, and `GeoExtractionService.extract_geo()`.

**No direct changes needed**. When its dependencies are rebuilt/reworked, event resolution automatically gets multilingual classification, contradiction detection, similarity, and geo extraction. The orchestration logic is sound.

---

### 5.9 GeoExtractionService — Arabic Gazetteer Expansion

**Current**: ~100 English city names in `_GEO_GAZETTEER`. Pattern `_IN_LOCATION_RE` matches `[A-Z][a-z]+` — misses Arabic text entirely.

**Changes**:

1. **Add Arabic entries** to `_GEO_GAZETTEER`:
```python
# Arabic equivalents for existing entries
"غزة": ("PS", 31.5, 34.47),
"القدس": ("IL", 31.77, 35.23),
"بيروت": ("LB", 33.89, 35.5),
"دمشق": ("SY", 33.51, 36.29),
"بغداد": ("IQ", 33.31, 44.37),
"طهران": ("IR", 35.69, 51.39),
"الرياض": ("SA", 24.71, 46.67),
"القاهرة": ("EG", 30.04, 31.24),
"صنعاء": ("YE", 15.37, 44.19),
"الدوحة": ("QA", 25.29, 51.53),
"الخرطوم": ("SD", 15.59, 32.53),
"طرابلس": ("LY", 32.9, 13.18),
"عمّان": ("JO", 31.95, 35.93),
"كابل": ("AF", 34.53, 69.17),
"إسلام آباد": ("PK", 33.69, 73.04),
# ... (full list: ~50 Arabic entries for top locations)
```

2. **Remove English-only regex pattern** `_IN_LOCATION_RE` dependency. The gazetteer lookup is language-agnostic (it does substring matching). The regex pattern for "in <Location>" is supplementary — keep it but don't rely on it for Arabic.

3. **Primary strategy**: After the EntityExtraction REBUILD, location entities will be extracted by the LLM in any language. `_entity_lookup()` (already exists) will match them against the gazetteer. This makes geo-extraction implicitly multilingual.

---

### 5.10 QualityFilterService — Language-Aware Scoring

**Current**: `_unique_word_ratio_score()` uses `.split()` for word tokenization. Arabic text without spaces between words will score differently. `_caps_score()` penalizes ALL-CAPS — Arabic has no uppercase, so this always returns 1.0 for Arabic.

**Changes**:

1. Accept optional `language` parameter:
```python
def evaluate(self, normalized: dict) -> dict:
    language = normalized.get("language", "")
    # ... pass language to sub-scorers ...
```

2. Adjust `_caps_score()`: Skip for Arabic (always 1.0 — no caps distinction).

3. Adjust `_boilerplate_score()`: Add Arabic boilerplate patterns:
```python
BOILERPLATE_PATTERNS_AR = [
    re.compile(r"اشترك\s+(الآن|اليوم)", re.IGNORECASE),  # subscribe now/today
    re.compile(r"انقر\s+هنا", re.IGNORECASE),  # click here
]
```

**Interface**: `evaluate(normalized: dict) -> dict` — unchanged (language already present in `normalized` dict after §5.1).

---

### 5.11 OpenSearch Indices — Arabic Analyzer + k-NN Vector Search

**Current**: Single `content_analyzer` using `snowball` filter (English stemming). No vector fields.

**Target mapping for `newsintel-articles`**:

```python
ARTICLE_MAPPING = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "index.knn": True,  # Enable k-NN plugin
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
            # ... existing fields unchanged ...
            "language": {"type": "keyword"},
            "title_ar": {"type": "text", "analyzer": "content_analyzer_ar"},
            "title_en": {"type": "text", "analyzer": "content_analyzer_en"},
            "content_ar": {"type": "text", "analyzer": "content_analyzer_ar"},
            "content_en": {"type": "text", "analyzer": "content_analyzer_en"},
            "embedding": {
                "type": "knn_vector",
                "dimension": 384,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib",
                },
            },
        },
    },
}
```

**Key additions**:
- `content_analyzer_ar` with Arabic normalization and stemming
- Language-specific text fields: `title_ar`/`title_en`, `content_ar`/`content_en`
- `embedding` as k-NN vector field (384 dimensions, HNSW index)
- `language` keyword field

**Index migration**: This requires deleting and recreating the indices (OpenSearch doesn't support changing analyzers on existing indices). The `ensure_indices()` method must detect the old mapping and reindex.

**Indexing logic** (`OpenSearchService.index_article()`): Route title/content to the correct language field based on `article.language`. Store the embedding vector in the `embedding` field.

---

### 5.12 AI Summary — Arabic-Aware Prompts

**Current**: English-only system prompts in `IntelAssessmentService` and `SummaryService`. Generates English summaries, then post-translates via Google Translate.

**Change**: Detect article language and adjust the prompt:

```python
def _build_summary_prompt(self, article: Article) -> str:
    if article.language == "ar":
        return "أنت محلل استخباراتي. لخص هذا المقال باللغة العربية في 3-5 جمل."
    return "You are an intelligence analyst. Summarize this article in 3-5 sentences."
```

The LLM (llama-3.3-70b) natively handles Arabic generation. This eliminates the translation round-trip for Arabic articles and produces higher-quality summaries.

**Where**: `services/orchestration/summary_service.py` and `services/orchestration/intel_assessment_service.py`.

---

### 5.13 Translation — Language Detection First

**Current**: `TranslationService` always translates content → English via `deep-translator` (Google Translate). No detection of source language.

**Change**: 
1. Use `article.language` (set on ingest, §5.1) to determine source language
2. Skip translation if article is already in the target language
3. Offer bidirectional translation (Arabic↔English) instead of always-to-English

```python
def translate(self, article: Article, target_language: str = "en") -> dict:
    if article.language == target_language:
        return {"translated": False, "text": article.content}
    # Proceed with translation using article.language as source
    translated = self._translate_text(article.content, source=article.language, target=target_language)
    return {"translated": True, "text": translated, "source": article.language}
```

---

### 5.14 Celery Beat Schedule — Reduce Frequency

**Current**: 23+ scheduled tasks, some running every 5 minutes. Intelligence tasks run every 10-30 minutes.

**Changes**:
- Ingestion cycle: Keep at 5 min (reasonable)
- Story clustering: Reduce from 10 min → 15 min (embedding computation is more expensive than TF-IDF)
- Event resolution: Keep at 15 min
- Intel assessment: Keep at 30 min
- Narrative conflict: Reduce from 15 min → 30 min (LLM calls are more expensive than regex)
- Self-learning: Keep at 1-4 hours

These are tuning adjustments. The exact frequencies will be calibrated during Phase 4 based on actual API costs and latency measurements.

---

### 5.15 Frontend i18n — Deferred

**Current**: All UI text in English. No RTL support.

**Status**: DEFERRED to a future phase. The backend changes in this phase produce a fully multilingual data pipeline. Frontend internationalization is a separate UX project that doesn't block backend correctness.

**When ready**, use `next-intl` or similar. The backend API already returns `language` on articles (after §5.1), so the frontend can render RTL layout conditionally.

---

## 6. Dependency Graph

All changes are grouped into implementation waves. Each wave depends only on completed waves.

```
WAVE 0 — Foundation (no dependencies)
├─ Add langdetect, sentence-transformers, trafilatura, simplejwt to requirements
├─ Data migration: Article.language, Entity.language
└─ Docker image: bake sentence-transformers model

WAVE 1 — Core Services (depends on Wave 0)
├─ NormalizationService rework (Arabic normalization + language detection)
├─ ArticleParseService rework (trafilatura)
├─ SemanticSimilarityService REBUILD (embeddings)
└─ QualityFilterService rework (language-aware scoring)

WAVE 2 — Intelligence Services (depends on Wave 1)
├─ EntityExtractionService REBUILD (LLM NER)
├─ NarrativeDetectionService REBUILD (LLM classification)
├─ DedupService rework (embedding-based)
├─ GeoExtractionService rework (Arabic gazetteer)
└─ OpenSearch indices rework (Arabic analyzer + k-NN)

WAVE 3 — Higher-Order Services (depends on Wave 2)
├─ NarrativeConflictService REBUILD (LLM contradiction)
├─ AI Summary rework (Arabic prompts)
├─ Translation rework (language-first)
├─ StoryClusteringOrch (automatic — verify only)
└─ EventResolutionService (automatic — verify only)

WAVE 4 — Security & Tuning (depends on Wave 3)
├─ Authentication REBUILD (JWT + RBAC)
├─ Celery Beat schedule tuning
└─ End-to-end integration testing
```

---

## 7. Migration Strategy

### 7.1 Database Migrations

| Migration | Type | Risk |
|-----------|------|------|
| `0002_article_language` | `AddField` + `RunPython` backfill | Low — nullable add, backfill is read-only |
| `0003_entity_language` | `AddField` | Low — simple column add |

### 7.2 OpenSearch Index Migration

1. Create new indices with `_v2` suffix and new mappings
2. Reindex all existing documents from old indices to new indices
3. Delete old indices, create aliases pointing new indices to old names

This is a zero-downtime migration handled by a management command.

### 7.3 Backward Compatibility

- All public interfaces are preserved → no caller changes
- Language field defaults to `""` → existing articles work without language
- Embedding field in OpenSearch is optional → old articles without embeddings are skipped by k-NN but still found by text search
- JWT auth requires a deployment-day action: create initial superuser token, configure frontend

---

## 8. Cost Projection

| Service | Calls/day | Tokens/call | Cost/day (Groq) |
|---------|-----------|-------------|-----------------|
| NER (EntityExtraction) | 500 | ~1,500 | $0.44 |
| Event Classification (NarrativeDetection) | 500 | ~1,200 | $0.35 |
| Contradiction Detection (NarrativeConflict) | 150 | ~3,000 | $0.27 |
| AI Summary | 200 | ~2,000 | $0.24 |
| Intel Assessment | 100 | ~2,500 | $0.15 |
| **Total** | | | **~$1.45/day** |

Sentence-transformers runs locally — zero API cost.

---

## 9. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Groq API downtime | Medium | High | Regex/heuristic fallback for NER and classification |
| sentence-transformers model size bloats Docker image | Low | Medium | CPU-only PyTorch (~200 MB), model ~120 MB. Total image increase ~350 MB |
| Arabic normalization edge cases | Medium | Low | Iterative refinement; normalization is a single function |
| OpenSearch reindex takes long | Low | Low | Run during maintenance window; zero-downtime alias swap |
| LLM returns malformed JSON for NER | Medium | Low | Validate JSON; retry once; fallback to empty entities |

---

## 10. What Does NOT Change

- **Three-layer architecture** (connectors → integrations → orchestration): Intact
- **Pipeline flow** (ingest → normalize → dedup → enrich → cluster → resolve → index): Intact
- **All 25+ orchestration services**: No changes to their orchestration logic
- **All 6 connectors**: `GroqAdapter`, `OpenSearchAdapter`, `Neo4jAdapter`, `MinioAdapter`, `RedisAdapter`, `CacheService` — intact
- **All Django models** except adding 2 fields (Article.language, Entity.language)
- **All API views and serializers** (except permission class change for auth)
- **Docker-compose topology**: Same 15 containers
- **Frontend**: No changes in this phase
- **Crawlers**: No changes

---

> **STOP — Phase 2 complete. Awaiting approval before proceeding to Phase 3 (Implementation Plan).**
