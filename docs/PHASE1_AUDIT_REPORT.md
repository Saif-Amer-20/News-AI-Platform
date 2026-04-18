# Phase 1 — Deep Audit & Triage Report

**Generated:** 2025-01-XX  
**Auditor:** Automated Deep Code Audit  
**Scope:** Full platform — backend (63 services, 30+ models, 23 Celery tasks), frontend (16 pages), infrastructure (15 Docker containers)

---

## 1. Executive Summary

The News Intelligence Platform is a functional OSINT system with a well-designed three-layer service architecture (connectors → integrations → orchestration) and a comprehensive data model. The ingestion pipeline, from source fetch through article creation, deduplication, clustering, event resolution, and indexing, is **genuinely operational and well-structured**.

However, the platform suffers from **six systemic weaknesses** that limit it from being a *real* intelligence system:

| # | Problem | Severity | Impact |
|---|---------|----------|--------|
| 1 | **Arabic is bolted-on, not native** | Critical | Arabic content cannot be searched, clustered, deduplicated, or entity-extracted. The platform is effectively English-only for all intelligence processing. |
| 2 | **NER/Entity extraction is English-only regex** | Critical | `EntityExtractionService` uses `[A-Z][a-z]+` regex patterns that cannot match Arabic script, Chinese, or non-Latin scripts at all. Zero Arabic entity extraction. |
| 3 | **Semantic similarity is bag-of-words TF-IDF** | High | `SemanticSimilarityService` uses word-frequency cosine similarity with English-only stop words. No actual semantic understanding. Cannot handle Arabic. |
| 4 | **Narrative/event detection is keyword regex** | High | `NarrativeDetectionService` has 40+ English regex rules. Arabic articles will always classify as "unknown". |
| 5 | **Heavy infrastructure for what it does** | Medium | Neo4j, OpenSearch, MinIO, Prometheus, Loki, Grafana — all legitimately configured, but the platform doesn't leverage embeddings, vector search, or graph analytics that would justify this stack. |
| 6 | **No authentication/authorization** | Medium | `DEFAULT_PERMISSION_CLASSES: [AllowAny]`, no auth classes. The RBAC system exists in code but is unused. |

**Bottom line:** The *architecture* is sound. The *pipeline orchestration* is well-built. But every analytical service that touches language (NER, similarity, narrative detection, quality filtering, dedup) is English-only and uses heuristics where semantic models are needed. Arabic is treated as a post-processing translation step, not a first-class analysis language.

---

## 2. Component-by-Component Triage

### Legend
- **KEEP** — Production-ready, no changes needed
- **REWORK** — Good structure, needs targeted fixes
- **REBUILD** — Correct approach but wrong implementation; replace internals
- **REMOVE** — Provides no value or is dead code

---

### 2.1 Data Model Layer

| Component | File | Verdict | Rationale |
|-----------|------|---------|-----------|
| Source model | `sources/models.py` | **KEEP** | Well-designed with health tracking, trust scoring, flexible parser_config JSON. Supports 6 source types. |
| RawItem / ParsedArticleCandidate | `sources/models.py` | **KEEP** | Clean three-stage pipeline (fetched → parsed → normalized). Content hash dedup is correct. |
| Article model | `sources/models.py` | **REWORK** | Missing: `language` field (critical for multilingual). `normalized_title`/`normalized_content` assume Latin script normalization. Add detected language + language-specific normalization. |
| Story model | `sources/models.py` | **KEEP** | Simple and effective clustering container. |
| Event model | `sources/models.py` | **KEEP** | Good design with 12 event types, geo fields, conflict flags, timeline JSON, metadata JSON. |
| Entity / ArticleEntity | `sources/models.py` | **REWORK** | Model is fine. But extraction is English-only (see service). Add `language` to Entity. |
| ArticleTranslation | `sources/models.py` | **KEEP** | Standard translation storage pattern. |
| ArticleAISummary | `sources/models.py` | **KEEP** | Clean LLM output storage with AR fields. |
| EventIntelAssessment | `sources/models.py` | **KEEP** | Comprehensive intel assessment model with credibility, predictions, diffusion layer. |
| Early Warning models | `sources/models.py` | **KEEP** | AnomalyDetection, SignalCorrelation, PredictiveScore, HistoricalPattern, GeoRadarZone — all well-designed. |
| Self-Learning models | `sources/models.py` | **KEEP** | AnalystFeedback, OutcomeRecord, SourceReputationLog, AdaptiveThreshold, LearningRecord — good feedback loop design. |
| Case models | `cases/models.py` | **KEEP** | Case, CaseMember, CaseNote, CaseReference — clean analyst workflow. |
| Alert models | `alerts/models.py` | **KEEP** | Alert rules and triggered alerts — functional. |
| Topic / KeywordRule | `topics/models.py` | **REWORK** | Good rule engine. But `TopicMatchingService` needs Arabic keyword support. |

### 2.2 Ingestion Pipeline

| Component | File | Verdict | Rationale |
|-----------|------|---------|-----------|
| IngestOrchestrationService | `orchestration/ingest_orchestration.py` | **KEEP** | Excellent pipeline orchestration. 11-step process from fetch to alert evaluation. Error handling is proper. |
| SourceFetchService | `orchestration/source_fetch_service.py` | **KEEP** | Clean strategy pattern dispatching to 6 connector types. |
| RawItemService | `orchestration/raw_item_service.py` | **KEEP** | Proper content hash dedup at persistence layer, MinIO snapshot storage. |
| RSSConnector | `connectors/rss_connector.py` | **KEEP** | Fetches RSS + optionally full article HTML. Correct. |
| HTMLConnector | `connectors/html_connector.py` | **KEEP** | Good multi-strategy extraction (selectors, link discovery, og:tags). |
| SitemapConnector | `connectors/sitemap_connector.py` | **KEEP** | Standard sitemap parsing → HTML fetch. |
| GDELTConnector | `connectors/gdelt_connector.py` | **KEEP** | Thin wrapper to GDELT adapter. |
| NewsAPIConnector / GNewsConnector | `connectors/newsapi_connector.py`, `gnews_connector.py` | **KEEP** | Standard API wrappers. |
| ArticleParseService | `orchestration/article_parse_service.py` | **REWORK** | HTML extraction works but relies on generic selectors. No readability-level extraction (like Mozilla Readability). Would benefit from `trafilatura` or similar. |
| NormalizationService | `orchestration/normalization_service.py` | **REWORK** | Unicode NFKC normalization is correct but `.lower()` doesn't handle Arabic script-specific normalization (tashkeel removal, alef variants, etc.). |

### 2.3 Intelligence Processing

| Component | File | Verdict | Rationale |
|-----------|------|---------|-----------|
| **EntityExtractionService** | `orchestration/entity_extraction_service.py` | **REBUILD** | **Critical flaw.** Uses `[A-Z][a-z]+` regex to find proper nouns. This fundamentally cannot work for Arabic (no uppercase), Chinese, Hebrew, or any non-Latin script. Classification uses English keyword lists (`_ORG_INDICATORS`, `_PERSON_TITLES`). Must be replaced with a multilingual NER model. |
| EntityResolutionService | `orchestration/entity_resolution_service.py` | **REWORK** | Good merge/dedup logic. Static alias registry is useful but limited. Merge algorithm is correct. Need to add Arabic aliases. |
| **SemanticSimilarityService** | `orchestration/semantic_similarity_service.py` | **REBUILD** | Uses term-frequency cosine similarity with English stop words. `_WORD_RE = re.compile(r"[a-z0-9]{2,}")` — this regex matches zero Arabic tokens. `compute_embedding()` is a placeholder hash vector. Must be replaced with multilingual sentence embeddings (e.g., `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`). |
| **NarrativeDetectionService** | `orchestration/narrative_detection_service.py` | **REBUILD** | 40+ English regex rules classify event types. All Arabic/non-English articles get "unknown". Must be replaced with a model-based or LLM-based classifier that works multilingually. |
| NarrativeConflictService | `orchestration/narrative_conflict_service.py` | **REBUILD** | English-only negation patterns (`\bdenied\b`, `\brefuted\b`). Low precision even for English. Must use an NLI model or LLM-based contradiction detection. |
| **DedupService** | `orchestration/dedup_service.py` | **REWORK** | Hash dedup is correct. But `SequenceMatcher` on `normalized_title` works poorly for Arabic (no word boundaries, diacritics). Should use embedding-based near-duplicate detection for non-Latin scripts. |
| StoryClusteringOrchestrationService | `orchestration/story_clustering_orchestration.py` | **REWORK** | Good composite scoring (title 0.30 + semantic 0.35 + entity 0.35). But relies on broken SemanticSimilarityService and EntityExtractionService — fixing those two will fix this by extension. |
| TopicMatchingService | `orchestration/topic_matching_service.py` | **REWORK** | Keyword/regex/boolean rule engine is solid. Works for Arabic if users add Arabic keyword rules. No changes to logic needed, just ensure Unicode handling. |
| EventResolutionService | `orchestration/event_resolution_service.py` | **REWORK** | Good story→event mapping. Depends on narrative detection + geo extraction + similarity — all of which need fixing. Structure is fine. |
| GeoExtractionService | `orchestration/geo_extraction_service.py` | **REWORK** | Has a ~100-city/country gazetteer. Missing Arabic city names (no Arabic gazetteer entries). Regex pattern `[A-Z][a-z]+` for "in <Location>" doesn't match Arabic. Need to add Arabic place names and pattern matching. |
| QualityFilterService | `orchestration/quality_filter_service.py` | **REWORK** | Reasonable heuristics (length, unique words, caps, boilerplate). But `_caps_score` penalizes Arabic (no uppercase → always passes). Boilerplate patterns are English-only. Need language-aware quality assessment. |
| ImportanceScoringService | `orchestration/importance_scoring_service.py` | **KEEP** | Language-independent scoring using source trust, frequency, topics, quality, recency. Works correctly for any language. |
| SourceReliabilityService | `orchestration/source_reliability_service.py` | **KEEP** | Language-independent trust scoring based on quality, dup ratio, health. Correct. |

### 2.4 Intelligence Layer (AI-powered)

| Component | File | Verdict | Rationale |
|-----------|------|---------|-----------|
| AI Summary Service | `services/ai_summary_service.py` | **REWORK** | Uses Groq/LLaMA-3.3-70B. Works well but: (1) system prompt is English-only, (2) "Write in the same language as the article" is unreliable, (3) Arabic translation via `deep-translator` is a post-processing step rather than native generation. Should prompt for Arabic output when input is Arabic. |
| Translation Service | `services/translation_service.py` | **REWORK** | Google Translate via `deep-translator`. Works but: (1) quality is mediocre for intelligence text, (2) 5000-char limit requires chunking, (3) no language detection. Should detect language first and only translate when needed. |
| Intel Assessment Service | `services/intel_assessment_service.py` | **KEEP** | Most sophisticated service. Proper LLM-based cross-source analysis with claims extraction, contradiction detection, credibility scoring, and predictions. JSON-structured output. Arabic translation post-processing. This is the model for how other services should work. |
| Anomaly Detection Service | `services/anomaly_detection_service.py` | **KEEP** | Z-score statistical approach with 5 detector types. Language-independent (works on counts/metrics). Good adaptive threshold integration. |

### 2.5 Early Warning & Predictive Layer

| Component | File | Verdict | Rationale |
|-----------|------|---------|-----------|
| Signal Correlation Service | `orchestration/signal_correlation_service.py` | **KEEP** | 4 correlation types (cross-event, cross-entity, cross-location, temporal). Solid algorithms. Language-independent. |
| Predictive Scoring Service | `orchestration/predictive_scoring_service.py` | **KEEP** | Multi-factor weighted model (anomaly, correlation, historical, diversity, velocity). Good risk trend computation. Language-independent. |
| Geo Radar Service | `orchestration/geo_radar_service.py` | **KEEP** | Grid-based geographic clustering with haversine distance. Concentration/trend scoring. Language-independent. |
| Temporal Evolution Service | `orchestration/temporal_evolution_service.py` | **REWORK** | Good timeline tracking. But redundancy check uses SemanticSimilarityService which is broken for Arabic. Fix the underlying service and this is fine. |

### 2.6 Search & Graph Layer

| Component | File | Verdict | Rationale |
|-----------|------|---------|-----------|
| OpenSearch Service | `orchestration/opensearch_service.py` | **REWORK** | Good index design with proper mappings. But `content_analyzer` uses English `snowball` stemmer. Need Arabic analyzer (`arabic_analyzer` with `arabic_normalization` + `arabic_stemmer` filters). |
| Neo4j Graph Service | `orchestration/neo4j_graph_service.py` | **KEEP** | Clean knowledge graph with proper node types and relationships. Schema constraints are correct. Individual Cypher writes per entity are slow but acceptable at current scale. |
| Event Confidence Service | `orchestration/event_confidence_service.py` | **KEEP** | 4-factor confidence model (source count, diversity, trust, consistency). Language-independent. |
| Geo Confidence Service | `orchestration/geo_confidence_service.py` | **KEEP** | 4-factor geo confidence (mention count, source agreement, specificity, entity-backed). |
| Multi-Source Correlation | `orchestration/multi_source_correlation_service.py` | **KEEP** | Independence clustering by domain+country. Clean correlation reports. |

### 2.7 Integration Adapters

| Component | File | Verdict | Rationale |
|-----------|------|---------|-----------|
| RSSAdapter | `integrations/rss_adapter.py` | **KEEP** | Clean feedparser integration. |
| OpenSearchAdapter | `integrations/opensearch_adapter.py` | **KEEP** | Standard CRUD wrapper. |
| Neo4jAdapter | `integrations/neo4j_adapter.py` | **KEEP** | Standard Cypher execution wrapper. |
| MinIOAdapter | `integrations/minio_adapter.py` | **KEEP** | Raw HTML snapshot storage. |
| ScrapyIngestionAdapter | `integrations/scrapy_ingestion_adapter.py` | **KEEP** | Clean payload-to-RawFetchResult transformer. |
| Common utilities | `integrations/common.py` | **KEEP** | `RawFetchResult`, `clean_text`, `html_to_text`, `parse_datetime_value`, URL normalization — all solid. |

### 2.8 Background Tasks (Celery)

| Component | Verdict | Rationale |
|-----------|---------|-----------|
| Ingestion tasks (fetch, process, parse, normalize, dispatch) | **KEEP** | Clean task delegation to orchestration services. |
| Intelligence tasks (reliability, events, entities, intelligence refresh) | **KEEP** | Proper periodic maintenance. |
| Intel Assessment task | **KEEP** | Selects top 30 events with ≥2 sources. Correct. |
| Early Warning tasks (5 tasks) | **KEEP** | Proper delegation to detection services. |
| Self-Learning tasks (5 tasks) | **KEEP** | Proper feedback loop execution. |
| **Celery Beat schedule** | **REWORK** | 23 scheduled tasks every 5-30 minutes. Anomaly detection every 10 min + signal correlation every 15 min + predictive scoring every 20 min is aggressive. Consider reducing frequency or making event-driven. |

### 2.9 Frontend

| Component | Verdict | Rationale |
|-----------|---------|-----------|
| Next.js 14 + Tailwind 4 | **KEEP** | Modern framework, works well. |
| Dashboard (page.tsx) | **KEEP** | Clean KPI grid + tables with early warning section. |
| Shell / Sidebar | **KEEP** | Working navigation. |
| Self-Learning page | **KEEP** | Recently redesigned to English. |
| 16-page frontend | **REWORK** | All pages work but: (1) no dark mode, (2) no Arabic/RTL support, (3) no language switcher, (4) no real map library (Leaflet/Mapbox). |

### 2.10 Infrastructure

| Component | Verdict | Rationale |
|-----------|---------|-----------|
| Docker Compose (15 containers) | **REWORK** | Well-configured with health checks and networks. But 15 containers is heavy for development. Consider making OpenSearch Dashboards, Grafana, Prometheus, Loki optional via profiles. |
| PostgreSQL 16 | **KEEP** | Solid primary store. |
| Redis 7.2 | **KEEP** | Broker + result backend. |
| OpenSearch 2.13 | **REWORK** | Underutilized — no Arabic analyzer, no vector search (k-NN plugin available). |
| Neo4j 5 | **REWORK** | Has knowledge graph schema but no analytical queries (no path-finding, centrality, community detection). Currently just a store. |
| MinIO | **KEEP** | Raw HTML archival. Low overhead. |
| Prometheus + Grafana + Loki | **KEEP** | Standard observability stack. Optional for dev. |
| Nginx | **KEEP** | Proper reverse proxy with all services. |

### 2.11 Security

| Component | Verdict | Rationale |
|-----------|---------|-----------|
| Authentication | **REBUILD** | `DEFAULT_PERMISSION_CLASSES: [AllowAny]`, no auth classes. RBAC code exists (`accounts/rbac.py`, `bootstrap_rbac.py`) but is completely unused. |
| CSRF / Security headers | **KEEP** | Proper `SecurityMiddleware`, `X-Frame-Options`, CSRF, Content-Type-Nosniff configured. |
| API key exposure | **REWORK** | Groq API key is passed via env vars (correct) but appears in conversation history. Ensure `.env` is in `.gitignore`. |

---

## 3. Root-Cause Analysis

### Root Cause 1: "English-First, Arabic-Later" Design

Every NLP-adjacent service was built with English assumptions:
- Capitalization-based NER (`[A-Z][a-z]+`)
- Latin-character tokenization (`[a-z0-9]{2,}`)
- English stop words, English keyword rules, English negation patterns
- Arabic is always added as a Google Translate post-processing step

**Impact chain:** Arabic articles enter the pipeline → they get normalized (OK) → entity extraction finds zero entities → story clustering has no entity signal and broken TF-IDF → events classify as "unknown" → dedup may miss Arabic near-duplicates → search uses English stemmer → intelligence assessment works (LLM handles Arabic) but builds on impoverished data.

### Root Cause 2: Heuristic Analysis Where Models Are Needed

The platform uses regex/keyword/heuristic approaches for tasks that require ML:
- NER: regex (should be multilingual NER model)
- Similarity: TF-IDF (should be embedding model)
- Event classification: keyword weight (should be zero-shot classifier or LLM)
- Contradiction detection: negation regex (should be NLI model or LLM)
- Content extraction: basic `<p>` tag parsing (should use readability algorithms)

The code itself acknowledges this — multiple comments say "production-grade would use spaCy/transformers" and "architecture is ready for drop-in replacement." The swap points are well-marked.

### Root Cause 3: Infrastructure-Rich but Feature-Shallow

The infrastructure is over-provisioned relative to actual usage:
- **Neo4j**: Has a knowledge graph but no graph algorithms run against it. No centrality, path-finding, or community detection. It's used as a secondary write-only store.
- **OpenSearch**: Has article/event indices but uses basic English analyzer. No vector search, no k-NN, no Arabic text analysis.
- **MinIO**: Stores HTML snapshots but nothing reads them back for analysis.

---

## 4. Proposed Target Architecture

### 4.1 Core Principle: Language-First Processing

```
Source → Fetch → Parse → DETECT LANGUAGE → Language-Specific Normalization
  → Multilingual Entity Extraction (NER model)
  → Multilingual Embedding (sentence-transformers)
  → Language-Aware Dedup (embedding cosine)
  → Multilingual Story Clustering (embedding + entity overlap)
  → Model-Based Event Classification (zero-shot or LLM)
  → Event Resolution (unchanged)
  → LLM Intelligence (works today)
```

### 4.2 Required Model Stack

| Capability | Current | Proposed | Why |
|------------|---------|----------|-----|
| NER | Regex | `CAMeL-Lab/bert-base-arabic-camelbert-msa-ner` or multilingual spaCy | Arabic NER support |
| Embeddings | TF-IDF hash | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim) | 50+ language support, works for Arabic, fast enough |
| Event classification | 40 English regexes | LLM-based (Groq) or `facebook/bart-large-mnli` zero-shot | Multilingual, semantic |
| Contradiction detection | English negation regex | LLM-based (Groq) — already paying for it | More accurate, multilingual |
| Content extraction | BeautifulSoup `<p>` tags | `trafilatura` library | Better article extraction quality |
| Language detection | None | `langdetect` or `lingua` | Required for routing |

### 4.3 Infrastructure Changes

| Change | Rationale |
|--------|-----------|
| Add Arabic analyzer to OpenSearch indices | Enable Arabic full-text search with proper stemming |
| Enable OpenSearch k-NN plugin | Vector similarity search for embeddings-based dedup and clustering |
| Add Docker profiles for observability stack | `docker compose --profile monitoring up` makes dev lighter |
| Keep Neo4j but add graph analytics tasks | Leverage existing graph for entity centrality, event connections |

### 4.4 Security Fix

| Change | Rationale |
|--------|-----------|
| Enable JWT/Token auth on DRF | Close the AllowAny hole |
| Wire up existing RBAC system | Code exists, just needs activation |

---

## 5. Migration Strategy (High-Level)

### Phase 2 deliverable: Detailed architecture specifications for each REBUILD/REWORK component.

### Phase 3 deliverable: Ordered implementation plan with dependency graph.

### Phase 4 approach: Incremental replacement

1. **Add language detection** to Article model and normalization pipeline (non-breaking)
2. **Replace SemanticSimilarityService** internals with multilingual sentence-transformers (swap `compute_similarity` body, keep interface)
3. **Replace EntityExtractionService** internals with multilingual NER model (keep `extract_and_link` interface)
4. **Replace NarrativeDetectionService** with LLM-based classifier (keep `detect` interface)
5. **Replace NarrativeConflictService** with LLM-based contradiction detection (keep `detect` interface)
6. **Add Arabic normalization** to NormalizationService (tashkeel removal, alef normalization)
7. **Add Arabic gazetteer entries** to GeoExtractionService
8. **Add Arabic analyzer** to OpenSearch indices (additive, non-breaking)
9. **Improve article extraction** with trafilatura (swap in ArticleParseService)
10. **Enable authentication** (wire existing RBAC)

Each step preserves existing interfaces. The three-layer architecture (connectors → integrations → orchestration) means each swap is isolated to one service file.

---

## 6. Triage Summary

| Verdict | Count | Components |
|---------|-------|------------|
| **KEEP** | 38 | Source model, Story, Event, EW models, SL models, Case, Alert, IngestOrchestration, all 6 connectors, all adapters, ImportanceScoring, SourceReliability, EventConfidence, GeoConfidence, MultiSourceCorrelation, SignalCorrelation, PredictiveScoring, GeoRadar, AnomalyDetection, IntelAssessment, all Celery tasks, all integration adapters, health checks, Nginx, PostgreSQL, Redis, MinIO, observability |
| **REWORK** | 15 | Article model, Entity model, Topic system, ArticleParseService, NormalizationService, DedupService, StoryClusteringOrch, EventResolutionService, GeoExtractionService, QualityFilterService, OpenSearch indices, AI Summary, Translation, Celery Beat schedule, Frontend (i18n) |
| **REBUILD** | 5 | EntityExtractionService, SemanticSimilarityService, NarrativeDetectionService, NarrativeConflictService, Authentication |
| **REMOVE** | 0 | Nothing is dead code. Everything is wired and functional. |

---

**STOP.** Awaiting approval to proceed to Phase 2: Target Architecture Redesign.
