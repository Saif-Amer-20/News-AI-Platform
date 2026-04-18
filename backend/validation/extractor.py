"""Extract validation datasets from existing platform data.

Queries the Articles, Stories, Events, Entities tables and builds
structured evaluation records with pseudo-ground-truth derived from
existing DB relationships.  No synthetic data.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from django.db.models import Count, F, Q

from sources.models import Article, ArticleEntity, Entity, Event, Source, Story

logger = logging.getLogger(__name__)


# ── Evaluation record ─────────────────────────────────────────────────────────


@dataclass
class EvalRecord:
    """One article in the validation set with pseudo-ground-truth."""

    article_id: int
    language: str
    source_id: int
    source_name: str
    title: str
    normalized_title: str
    url: str
    content_snippet: str  # first 2000 chars for text analysis
    content_length: int
    has_story: bool
    story_id: int | None
    has_event: bool
    event_id: int | None
    event_type: str | None
    is_duplicate: bool
    duplicate_of_id: int | None
    content_hash: str
    entity_count: int
    entity_names: list[str]
    entity_types: list[str]
    gt_cluster: str
    gt_event_group: str
    gt_location_country: str
    gt_location_name: str
    gt_has_conflict: bool
    quality_score: float
    importance_score: float
    published_at: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationDataset:
    """Complete validation dataset with statistics."""

    records: list[EvalRecord] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stats": self.stats,
            "records": [r.to_dict() for r in self.records],
        }


# ── Extractor ─────────────────────────────────────────────────────────────────


class ValidationDatasetExtractor:
    """Build a validation dataset from existing platform data."""

    MIN_CONTENT_LENGTH = 200

    def extract(self, max_articles: int = 0) -> ValidationDataset:
        """Extract evaluation records from the database.

        Args:
            max_articles: Maximum articles to include (0 = all eligible).

        Returns:
            ValidationDataset with records and statistics.
        """
        logger.info("Building validation dataset from existing data...")

        # ── 1. Query eligible articles ──
        qs = (
            Article.objects
            .select_related("source", "story", "story__event")
            .prefetch_related("article_entities__entity")
            .annotate(entity_cnt=Count("article_entities"))
        )
        # Only articles with meaningful content
        qs = qs.extra(where=["LENGTH(content) > %s"], params=[self.MIN_CONTENT_LENGTH])

        total_eligible = qs.count()
        logger.info("Total eligible articles (content > %d chars): %d",
                     self.MIN_CONTENT_LENGTH, total_eligible)

        if total_eligible == 0:
            logger.warning("No eligible articles found in database.")
            return ValidationDataset(stats={"total_eligible": 0, "sampled": 0})

        # ── 2. Stratified sampling ──
        articles = self._stratified_sample(qs, max_articles)
        logger.info("Sampled %d articles for validation", len(articles))

        # ── 3. Build evaluation records ──
        records = []
        for article in articles:
            record = self._build_record(article)
            records.append(record)

        # ── 4. Compute statistics ──
        dataset = ValidationDataset(records=records)
        dataset.stats = self._compute_stats(records, total_eligible)

        logger.info(
            "Validation dataset built: %d records, %d languages, %d sources, "
            "%d with stories, %d with events, %d duplicates",
            len(records),
            len(dataset.stats.get("languages", {})),
            dataset.stats.get("unique_sources", 0),
            dataset.stats.get("with_story", 0),
            dataset.stats.get("with_event", 0),
            dataset.stats.get("duplicates", 0),
        )
        return dataset

    # ── Sampling ──────────────────────────────────────────────────────────────

    def _stratified_sample(self, qs, max_articles: int) -> list[Article]:
        """Stratified sample ensuring language, source, and feature diversity."""

        # Priority buckets — we want diverse coverage
        # Bucket 1: articles in stories with events (richest ground truth)
        bucket_event = list(
            qs.filter(story__event__isnull=False)
            .order_by("-published_at")
        )

        # Bucket 2: articles in stories but no event
        bucket_story = list(
            qs.filter(story__isnull=False, story__event__isnull=True)
            .order_by("-published_at")
        )

        # Bucket 3: duplicate articles (for dedup evaluation)
        bucket_dup = list(
            qs.filter(is_duplicate=True)
            .order_by("-published_at")
        )

        # Bucket 4: articles with entities but no story (for NER-only eval)
        bucket_entity = list(
            qs.filter(story__isnull=True, entity_cnt__gt=0)
            .order_by("-published_at")
        )

        # Bucket 5: unclustered, no entities (edge cases)
        bucket_unclustered = list(
            qs.filter(story__isnull=True, entity_cnt=0, is_duplicate=False)
            .order_by("-published_at")[:100]  # cap edge cases
        )

        # Merge and deduplicate
        seen_ids = set()
        merged = []
        for bucket in [bucket_event, bucket_dup, bucket_story, bucket_entity, bucket_unclustered]:
            for article in bucket:
                if article.id not in seen_ids:
                    seen_ids.add(article.id)
                    merged.append(article)

        if max_articles > 0 and len(merged) > max_articles:
            # Ensure language balance in final sample
            merged = self._balance_by_language(merged, max_articles)

        return merged

    def _balance_by_language(self, articles: list[Article], target: int) -> list[Article]:
        """Ensure proportional language representation."""
        by_lang: dict[str, list[Article]] = defaultdict(list)
        for a in articles:
            lang = (a.source.language if a.source else None) or "unknown"
            by_lang[lang].append(a)

        result = []
        total = len(articles)

        for lang, lang_articles in by_lang.items():
            # Proportional allocation, minimum 5% or 10 articles
            proportion = len(lang_articles) / total
            alloc = max(10, int(target * proportion))
            result.extend(lang_articles[:alloc])

        # If under target, pad with remaining
        seen = {a.id for a in result}
        for a in articles:
            if len(result) >= target:
                break
            if a.id not in seen:
                result.append(a)
                seen.add(a.id)

        return result[:target]

    # ── Record building ───────────────────────────────────────────────────────

    def _build_record(self, article: Article) -> EvalRecord:
        """Build a single evaluation record from an Article instance."""

        # Entity info
        entity_links = list(article.article_entities.select_related("entity").all())
        entity_names = [ae.entity.name for ae in entity_links]
        entity_types = [ae.entity.entity_type for ae in entity_links]

        # Story/event info
        story = article.story
        event = story.event if story else None

        # Ground truth cluster: story_id if exists, else 'unclustered_{id}'
        if story:
            gt_cluster = f"story_{story.id}"
        else:
            gt_cluster = f"unclustered_{article.id}"

        # Ground truth event group
        if event:
            gt_event_group = f"event_{event.id}"
        else:
            gt_event_group = "no_event"

        # Ground truth location from event
        gt_location_country = ""
        gt_location_name = ""
        if event:
            gt_location_country = event.location_country or ""
            gt_location_name = event.location_name or ""

        # Ground truth conflict
        gt_has_conflict = bool(event and event.conflict_flag)

        return EvalRecord(
            article_id=article.id,
            language=(article.source.language if article.source else None) or "unknown",
            source_id=article.source_id,
            source_name=article.source.name if article.source else "unknown",
            title=article.title or "",
            normalized_title=article.normalized_title or (article.title or "").lower().strip(),
            url=article.url or "",
            content_snippet=(article.content or "")[:2000],
            content_length=len(article.content or ""),
            has_story=story is not None,
            story_id=story.id if story else None,
            has_event=event is not None,
            event_id=event.id if event else None,
            event_type=event.event_type if event else None,
            is_duplicate=article.is_duplicate,
            duplicate_of_id=article.duplicate_of_id,
            content_hash=article.content_hash,
            entity_count=len(entity_names),
            entity_names=entity_names,
            entity_types=entity_types,
            gt_cluster=gt_cluster,
            gt_event_group=gt_event_group,
            gt_location_country=gt_location_country,
            gt_location_name=gt_location_name,
            gt_has_conflict=gt_has_conflict,
            quality_score=float(article.quality_score),
            importance_score=float(article.importance_score),
            published_at=article.published_at.isoformat() if article.published_at else None,
        )

    # ── Statistics ────────────────────────────────────────────────────────────

    def _compute_stats(self, records: list[EvalRecord], total_eligible: int) -> dict:
        """Compute dataset statistics."""
        if not records:
            return {"total_eligible": total_eligible, "sampled": 0}

        languages = Counter(r.language for r in records)
        sources = Counter(r.source_name for r in records)
        event_types = Counter(r.event_type for r in records if r.event_type)

        with_story = sum(1 for r in records if r.has_story)
        with_event = sum(1 for r in records if r.has_event)
        with_entities = sum(1 for r in records if r.entity_count > 0)
        duplicates = sum(1 for r in records if r.is_duplicate)
        with_conflict = sum(1 for r in records if r.gt_has_conflict)
        with_location = sum(1 for r in records if r.gt_location_country)

        # Unique clusters
        clusters = set(r.gt_cluster for r in records if not r.gt_cluster.startswith("unclustered_"))

        # Content length distribution
        lengths = [r.content_length for r in records]
        avg_length = sum(lengths) / len(lengths) if lengths else 0

        # Hash duplicates (different articles, same content_hash)
        hash_counts = Counter(r.content_hash for r in records)
        hash_dup_groups = sum(1 for c in hash_counts.values() if c > 1)

        return {
            "total_eligible": total_eligible,
            "sampled": len(records),
            "languages": dict(languages),
            "unique_sources": len(sources),
            "top_sources": dict(sources.most_common(10)),
            "event_types": dict(event_types),
            "with_story": with_story,
            "with_event": with_event,
            "with_entities": with_entities,
            "duplicates": duplicates,
            "with_conflict": with_conflict,
            "with_location": with_location,
            "unique_clusters": len(clusters),
            "hash_duplicate_groups": hash_dup_groups,
            "avg_content_length": round(avg_length),
            "min_content_length": min(lengths) if lengths else 0,
            "max_content_length": max(lengths) if lengths else 0,
        }


# ── Pseudo-ground-truth enrichment ───────────────────────────────────────────


class PseudoGroundTruthBuilder:
    """LEGACY: Enrich validation records with pseudo-ground-truth
    inferred from cross-article relationships in the database.
    Kept for backward compatibility."""

    def build_cluster_ground_truth(self, records: list[EvalRecord]) -> dict[str, list[int]]:
        clusters: dict[str, list[int]] = defaultdict(list)
        for r in records:
            clusters[r.gt_cluster].append(r.article_id)
        return {k: v for k, v in clusters.items() if len(v) >= 2}

    def build_dedup_ground_truth(self, records: list[EvalRecord]) -> list[tuple[int, int]]:
        pairs = []
        for r in records:
            if r.duplicate_of_id:
                pairs.append((r.article_id, r.duplicate_of_id))
        hash_to_ids: dict[str, list[int]] = defaultdict(list)
        for r in records:
            hash_to_ids[r.content_hash].append(r.article_id)
        for ids in hash_to_ids.values():
            if len(ids) >= 2:
                for dup_id in ids[1:]:
                    if (dup_id, ids[0]) not in pairs and (ids[0], dup_id) not in pairs:
                        pairs.append((dup_id, ids[0]))
        return pairs

    def build_entity_ground_truth(self, records: list[EvalRecord]) -> dict[str, list[dict]]:
        clusters = self.build_cluster_ground_truth(records)
        record_map = {r.article_id: r for r in records}
        result: dict[str, list[dict]] = {}
        for cluster_key, article_ids in clusters.items():
            if len(article_ids) < 2:
                continue
            entity_counter: Counter[tuple[str, str]] = Counter()
            for aid in article_ids:
                rec = record_map.get(aid)
                if not rec:
                    continue
                seen_in_article = set()
                for name, etype in zip(rec.entity_names, rec.entity_types):
                    key = (name.lower().strip(), etype.lower())
                    if key not in seen_in_article:
                        entity_counter[key] += 1
                        seen_in_article.add(key)
            threshold = len(article_ids) / 2
            consensus = [
                {"name": name, "type": etype}
                for (name, etype), count in entity_counter.items()
                if count >= threshold
            ]
            if consensus:
                result[cluster_key] = consensus
        return result

    def build_conflict_ground_truth(self, records: list[EvalRecord]) -> list[str]:
        conflict_events = set()
        for r in records:
            if r.gt_has_conflict and r.gt_event_group != "no_event":
                conflict_events.add(r.gt_event_group)
        return sorted(conflict_events)

    def build_geo_ground_truth(self, records: list[EvalRecord]) -> dict[int, dict]:
        result = {}
        for r in records:
            if r.gt_location_country:
                result[r.article_id] = {
                    "country": r.gt_location_country,
                    "name": r.gt_location_name,
                }
        return result

    def build_all(self, records: list[EvalRecord]) -> dict[str, Any]:
        return {
            "clusters": self.build_cluster_ground_truth(records),
            "dedup_pairs": self.build_dedup_ground_truth(records),
            "entity_consensus": self.build_entity_ground_truth(records),
            "conflict_events": self.build_conflict_ground_truth(records),
            "geo_truth": self.build_geo_ground_truth(records),
        }


# ── Independent ground-truth builder ─────────────────────────────────────────

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse


# ── Entity normalization utilities ────────────────────────────────────────────

_TITLE_PREFIXES = {
    # English
    "president", "vice president", "prime minister", "minister",
    "secretary", "senator", "congressman", "representative",
    "governor", "mayor", "ambassador", "general", "colonel",
    "commander", "admiral", "captain", "lieutenant", "sergeant",
    "professor", "dr", "doctor", "sir", "lord", "king", "queen",
    "prince", "princess", "sheikh", "imam", "pope", "bishop",
    "archbishop", "cardinal", "reverend", "father", "sister",
    "defence secretary", "defense secretary", "foreign minister",
    "chief", "head", "director", "chairman", "chairwoman",
    "mr", "mrs", "ms", "miss",
    # Arabic
    "الرئيس", "رئيس", "وزير", "الوزير", "نائب", "سفير",
    "الشيخ", "شيخ", "الملك", "ملك", "الأمير", "أمير",
    "الأميرة", "أميرة", "الدكتور", "دكتور", "السيد", "سيد",
    "البابا", "بابا",
}

_ENTITY_STOPWORDS = {
    # English
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and",
    "or", "is", "was", "are", "were", "be", "been", "has", "have",
    "had", "do", "does", "did", "but", "not", "no", "its", "it",
    "this", "that", "with", "from", "by", "as", "said", "says",
    "also", "about", "after", "new", "first", "last",
    "following", "according",
    # Arabic
    "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه",
    "ذلك", "التي", "الذي", "التي", "هو", "هي",
}

_NOISE_PHRASES = {
    "palm sunday mass", "foreign policy", "breaking news",
    "read more", "related articles", "click here",
    "follow us", "share this", "subscribe",
    "getty images", "reuters", "associated press", "ap photo",
    "file photo", "stock photo",
}


def normalize_entity_name(name: str) -> str:
    """Aggressively normalize entity name for matching.

    1. Lowercase + strip whitespace
    2. Unicode NFKD normalize (Arabic form normalization)
    3. Remove title prefixes (president, minister, etc.)
    4. Strip remaining leading articles/stopwords
    """
    s = name.strip().lower()
    # Unicode normalize (helps Arabic alef/hamza forms)
    s = unicodedata.normalize("NFKC", s)
    # Remove title prefixes (longest first for greedy match)
    for prefix in sorted(_TITLE_PREFIXES, key=len, reverse=True):
        if s.startswith(prefix + " "):
            s = s[len(prefix) + 1:].strip()
            break  # one prefix removal is enough
    # Strip leading articles
    for article in ("the ", "al-", "al ", "ال"):
        if s.startswith(article):
            s = s[len(article):].strip()
            break
    return s.strip()


def is_noisy_entity(name: str) -> bool:
    """Return True if entity name is noise and should be filtered."""
    normalized = name.strip().lower()
    # Too short (1-2 chars)
    if len(normalized) <= 2:
        return True
    # Pure stopword
    if normalized in _ENTITY_STOPWORDS:
        return True
    # Known noise phrase
    if normalized in _NOISE_PHRASES:
        return True
    # All digits or punctuation
    if re.match(r'^[\d\W]+$', normalized):
        return True
    # Single character repeated
    if len(set(normalized.replace(" ", ""))) <= 1:
        return True
    return False


# ISO 3166-1 country patterns for text extraction — comprehensive.
# Aligned with the system's geo_extraction_service to avoid false negatives.
# Each entry: country_code → [country name, demonyms, capitals, major cities, Arabic names]
_COUNTRY_PATTERNS: dict[str, list[str]] = {
    "US": ["united states", "u.s.", "usa", "america", "american", "americans",
           "washington d.c.", "washington", "new york", "los angeles",
           "chicago", "houston", "phoenix", "philadelphia", "san antonio",
           "san diego", "dallas", "san francisco", "seattle", "boston",
           "atlanta", "miami", "denver", "detroit", "portland", "las vegas",
           "minneapolis", "charlotte", "austin", "nashville", "baltimore",
           # US state names for indirect references
           "california", "texas", "florida", "virginia", "pennsylvania",
           "ohio", "georgia", "michigan", "illinois", "north carolina",
           "new jersey", "arizona", "massachusetts", "tennessee", "indiana",
           "maryland", "wisconsin", "colorado", "minnesota", "missouri",
           "connecticut", "oregon", "oklahoma", "kentucky", "louisiana",
           "alabama", "mississippi", "arkansas", "iowa", "kansas", "utah",
           "nevada", "nebraska", "hawaii", "maine", "montana", "idaho",
           "west virginia", "south carolina", "south dakota", "north dakota",
           "new mexico", "new hampshire", "rhode island", "delaware",
           "vermont", "wyoming", "alaska",
           "pentagon", "white house", "capitol hill", "wall street",
           "أمريكا", "أمريكي", "الولايات المتحدة", "واشنطن", "نيويورك"],
    "GB": ["united kingdom", "u.k.", "britain", "british", "england",
           "scotland", "wales", "london", "manchester", "birmingham",
           "liverpool", "edinburgh", "glasgow", "oxford", "cambridge",
           "بريطانيا", "بريطاني", "لندن", "إنجلترا"],
    "IL": ["israel", "israeli", "israelis", "tel aviv", "jerusalem",
           "haifa", "netanyahu", "knesset", "idf",
           "إسرائيل", "إسرائيلي", "تل أبيب", "القدس"],
    "PS": ["palestine", "palestinian", "palestinians", "gaza", "gaza strip",
           "west bank", "ramallah", "hamas", "nablus", "hebron", "jenin",
           "فلسطين", "فلسطيني", "غزة", "قطاع غزة",
           "الضفة الغربية", "رام الله"],
    "UA": ["ukraine", "ukrainian", "ukrainians", "kyiv", "kiev",
           "kharkiv", "odesa", "odessa", "lviv", "zaporizhzhia",
           "أوكرانيا", "أوكراني", "كييف"],
    "RU": ["russia", "russian", "russians", "moscow", "kremlin",
           "st. petersburg", "saint petersburg",
           "روسيا", "روسي", "موسكو", "الكرملين"],
    "CN": ["china", "chinese", "beijing", "shanghai", "guangzhou",
           "shenzhen", "hong kong", "الصين", "صيني", "بكين"],
    "IR": ["iran", "iranian", "iranians", "tehran", "isfahan",
           "إيران", "إيراني", "طهران"],
    "IQ": ["iraq", "iraqi", "iraqis", "baghdad", "basra", "mosul", "erbil",
           "kirkuk", "najaf", "karbala",
           "العراق", "عراقي", "بغداد", "البصرة", "الموصل", "أربيل"],
    "SY": ["syria", "syrian", "syrians", "damascus", "aleppo", "idlib",
           "homs", "latakia", "سوريا", "سوري", "دمشق", "حلب"],
    "LB": ["lebanon", "lebanese", "beirut", "hezbollah", "tripoli lebanon",
           "sidon", "لبنان", "لبناني", "بيروت", "حزب الله"],
    "SA": ["saudi arabia", "saudi", "saudis", "riyadh", "jeddah", "mecca",
           "medina", "neom",
           "السعودية", "سعودي", "الرياض", "جدة", "مكة", "المدينة"],
    "AE": ["emirates", "uae", "emirati", "emiratis", "dubai", "abu dhabi",
           "sharjah", "الإمارات", "إماراتي", "دبي", "أبو ظبي"],
    "EG": ["egypt", "egyptian", "egyptians", "cairo", "alexandria",
           "suez", "sinai", "مصر", "مصري", "القاهرة"],
    "TR": ["turkey", "turkish", "turks", "ankara", "istanbul",
           "تركيا", "تركي", "أنقرة", "إسطنبول"],
    "YE": ["yemen", "yemeni", "yemenis", "sanaa", "aden", "houthis", "houthi",
           "اليمن", "يمني", "صنعاء", "عدن", "الحوثي", "الحوثيين"],
    "AF": ["afghanistan", "afghan", "afghans", "kabul", "kandahar", "taliban",
           "أفغانستان", "أفغاني", "كابل", "طالبان"],
    "PK": ["pakistan", "pakistani", "pakistanis", "islamabad", "karachi", "lahore",
           "باكستان", "باكستاني", "إسلام أباد"],
    "IN": ["india", "indian", "indians", "delhi", "new delhi", "mumbai",
           "bangalore", "kolkata", "chennai", "hyderabad",
           "الهند", "هندي", "نيودلهي", "مومباي"],
    "JP": ["japan", "japanese", "tokyo", "osaka",
           "اليابان", "ياباني", "طوكيو"],
    "KR": ["south korea", "korean", "koreans", "seoul", "busan",
           "كوريا الجنوبية", "كوري", "سيول"],
    "KP": ["north korea", "pyongyang", "كوريا الشمالية", "بيونغ يانغ"],
    "DE": ["germany", "german", "germans", "berlin", "munich", "hamburg",
           "frankfurt", "ألمانيا", "ألماني", "برلين"],
    "FR": ["france", "french", "paris", "marseille", "lyon",
           "فرنسا", "فرنسي", "باريس"],
    "IT": ["italy", "italian", "italians", "rome", "milan", "naples",
           "vatican", "vatican city",
           "إيطاليا", "إيطالي", "روما", "الفاتيكان"],
    "ES": ["spain", "spanish", "madrid", "barcelona",
           "إسبانيا", "إسباني", "مدريد"],
    "LY": ["libya", "libyan", "libyans", "tripoli", "benghazi",
           "ليبيا", "ليبي", "طرابلس", "بنغازي"],
    "SD": ["sudan", "sudanese", "khartoum", "darfur",
           "السودان", "سوداني", "الخرطوم", "دارفور"],
    "SO": ["somalia", "somali", "somalis", "mogadishu",
           "الصومال", "صومالي", "مقديشو"],
    "NG": ["nigeria", "nigerian", "nigerians", "abuja", "lagos",
           "نيجيريا", "نيجيري", "أبوجا", "لاغوس"],
    "ET": ["ethiopia", "ethiopian", "ethiopians", "addis ababa",
           "إثيوبيا", "إثيوبي", "أديس أبابا"],
    "MM": ["myanmar", "burmese", "burma", "yangon", "ميانمار"],
    "TW": ["taiwan", "taiwanese", "taipei", "تايوان"],
    "JO": ["jordan", "jordanian", "jordanians", "amman",
           "الأردن", "أردني", "عمّان"],
    "QA": ["qatar", "qatari", "qataris", "doha",
           "قطر", "قطري", "الدوحة"],
    "KW": ["kuwait", "kuwaiti", "kuwaitis",
           "الكويت", "كويتي"],
    "BH": ["bahrain", "bahraini", "bahrainis",
           "البحرين", "بحريني", "المنامة"],
    "OM": ["oman", "omani", "omanis", "muscat",
           "عمان", "عماني", "مسقط"],
    "MA": ["morocco", "moroccan", "moroccans", "rabat", "casablanca",
           "marrakech", "المغرب", "مغربي", "الرباط", "الدار البيضاء"],
    "TN": ["tunisia", "tunisian", "tunisians", "tunis",
           "تونس", "تونسي"],
    "DZ": ["algeria", "algerian", "algerians", "algiers",
           "الجزائر", "جزائري"],
    "PL": ["poland", "polish", "warsaw", "بولندا", "بولندي"],
    "RO": ["romania", "romanian", "bucharest", "رومانيا"],
    "AT": ["austria", "austrian", "vienna", "النمسا"],
    "BE": ["belgium", "belgian", "brussels", "بلجيكا"],
    "NL": ["netherlands", "dutch", "amsterdam", "the hague", "هولندا"],
    "SE": ["sweden", "swedish", "stockholm", "السويد"],
    "NO": ["norway", "norwegian", "oslo", "النرويج"],
    "DK": ["denmark", "danish", "copenhagen", "الدانمارك"],
    "FI": ["finland", "finnish", "helsinki", "فنلندا"],
    "CH": ["switzerland", "swiss", "zurich", "geneva", "bern", "سويسرا"],
    "GR": ["greece", "greek", "greeks", "athens", "اليونان"],
    "PT": ["portugal", "portuguese", "lisbon", "البرتغال"],
    "IE": ["ireland", "irish", "dublin", "أيرلندا"],
    "CZ": ["czech republic", "czech", "prague", "التشيك"],
    "HU": ["hungary", "hungarian", "budapest", "المجر"],
    "KE": ["kenya", "kenyan", "kenyans", "nairobi", "كينيا"],
    "ZA": ["south africa", "south african", "johannesburg", "cape town",
           "pretoria", "جنوب أفريقيا"],
    "GH": ["ghana", "ghanaian", "accra", "غانا"],
    "TZ": ["tanzania", "tanzanian", "dar es salaam", "تنزانيا"],
    "UG": ["uganda", "ugandan", "kampala", "أوغندا"],
    "CD": ["congo", "congolese", "kinshasa", "الكونغو"],
    "CM": ["cameroon", "cameroonian", "yaounde", "الكاميرون"],
    "MX": ["mexico", "mexican", "mexicans", "mexico city",
           "المكسيك", "مكسيكي"],
    "CO": ["colombia", "colombian", "colombians", "bogota", "كولومبيا"],
    "AR": ["argentina", "argentine", "argentines", "buenos aires", "الأرجنتين"],
    "BR": ["brazil", "brazilian", "brazilians", "brasilia", "sao paulo",
           "rio de janeiro", "البرازيل", "برازيلي"],
    "CL": ["chile", "chilean", "santiago", "تشيلي"],
    "PE": ["peru", "peruvian", "lima", "بيرو"],
    "CU": ["cuba", "cuban", "cubans", "havana", "كوبا"],
    "VE": ["venezuela", "venezuelan", "venezuelans", "caracas", "فنزويلا"],
    "CA": ["canada", "canadian", "canadians", "ottawa", "toronto",
           "vancouver", "montreal", "كندا", "كندي"],
    "AU": ["australia", "australian", "australians", "sydney", "melbourne",
           "canberra", "أستراليا", "أسترالي"],
    "NZ": ["new zealand", "new zealander", "wellington", "auckland",
           "نيوزيلندا"],
    "TH": ["thailand", "thai", "bangkok", "تايلاند"],
    "ID": ["indonesia", "indonesian", "indonesians", "jakarta", "إندونيسيا"],
    "MY": ["malaysia", "malaysian", "kuala lumpur", "ماليزيا"],
    "PH": ["philippines", "filipino", "filipinos", "manila", "الفلبين"],
    "VN": ["vietnam", "vietnamese", "hanoi", "ho chi minh", "فيتنام"],
    "SG": ["singapore", "singaporean", "سنغافورة"],
}

# Pre-compile country patterns for fast matching
_COMPILED_GT_PATTERNS: list[tuple[str, re.Pattern]] = []
for _code, _pats in _COUNTRY_PATTERNS.items():
    for _p in sorted(_pats, key=len, reverse=True):  # longest first
        _COMPILED_GT_PATTERNS.append(
            (_code, re.compile(r"\b" + re.escape(_p) + r"\b", re.IGNORECASE))
        )

# Conflict / contradiction indicator words — strong only
# Removed weak journalism transition words (however, in contrast) that caused
# false positives in normal reporting.
_CONFLICT_KEYWORDS = [
    "denied", "denies", "deny", "rejected", "disputes", "disputed",
    "contradicts", "contradicted", "refuted", "refutes",
    "false claim", "misinformation", "no evidence", "not true",
    "retracted", "fact-check",
    "accused", "accuses", "allegation", "allegations",
    "clash", "clashed", "clashes", "fighting",
    "killed", "casualties", "dead", "wounded",
    "ceasefire", "truce", "violation", "violated",
    "blamed", "blames", "condemned", "condemns",
]


class IndependentGroundTruthBuilder:
    """Build ground-truth INDEPENDENTLY of stored system fields.

    Uses text analysis, similarity metrics, and content-based heuristics
    rather than relying on story_id, is_duplicate, event.location_country,
    or event.conflict_flag.
    """

    # ── Clustering: title similarity + time proximity ─────────────────────

    TITLE_SIM_THRESHOLD = 0.55
    TIME_WINDOW_HOURS = 72  # articles within 72h can be about same story

    def build_cluster_ground_truth(
        self, records: list[EvalRecord]
    ) -> dict[str, list[int]]:
        """Cluster articles by title similarity + time proximity.

        Two articles go in the same independent cluster if:
          - normalized_title SequenceMatcher ratio >= TITLE_SIM_THRESHOLD
          - published within TIME_WINDOW_HOURS of each other (if both have dates)
          - from different sources (boosts confidence) or same source if very similar

        Returns mapping: indie_cluster_N → [article_ids] (only clusters with 2+).
        """
        n = len(records)
        # Union-Find for clustering
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Pre-compute parsed publish times
        from datetime import datetime, timedelta
        pub_times = []
        for r in records:
            if r.published_at:
                try:
                    dt = datetime.fromisoformat(r.published_at.replace("Z", "+00:00"))
                    pub_times.append(dt)
                except (ValueError, TypeError):
                    pub_times.append(None)
            else:
                pub_times.append(None)

        # Compare all pairs (O(n^2) — fine for ≤500 articles)
        for i in range(n):
            if not records[i].normalized_title:
                continue
            for j in range(i + 1, n):
                if not records[j].normalized_title:
                    continue

                # Title similarity
                sim = SequenceMatcher(
                    None,
                    records[i].normalized_title,
                    records[j].normalized_title,
                ).ratio()

                if sim < self.TITLE_SIM_THRESHOLD:
                    continue

                # Time proximity check
                time_ok = True
                if pub_times[i] and pub_times[j]:
                    delta = abs((pub_times[i] - pub_times[j]).total_seconds())
                    time_ok = delta <= self.TIME_WINDOW_HOURS * 3600

                if time_ok:
                    union(i, j)

        # Build clusters
        cluster_map: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            root = find(i)
            cluster_map[root].append(records[i].article_id)

        # Return only multi-article clusters with labels
        result = {}
        idx = 0
        for root, ids in cluster_map.items():
            if len(ids) >= 2:
                result[f"indie_cluster_{idx}"] = ids
                idx += 1
        return result

    # ── Dedup: content similarity + URL normalization + independent hash ──

    CONTENT_SIM_THRESHOLD = 0.85  # very high = likely duplicate
    SHINGLE_SIZE = 5  # word-level shingles

    def build_dedup_ground_truth(
        self, records: list[EvalRecord]
    ) -> list[tuple[int, int]]:
        """Find duplicates using independent content analysis.

        Methods:
         1. Independent content hash (SHA256 of normalized content)
         2. URL domain+path match (ignoring query params)
         3. Content shingle overlap (Jaccard) for near-duplicates
        """
        pairs = set()
        n = len(records)

        # Method 1: Independent content hash (SHA256 on normalized snippet)
        indie_hash_map: dict[str, list[int]] = defaultdict(list)
        for r in records:
            text = re.sub(r"\s+", " ", r.content_snippet.lower().strip())
            if len(text) > 100:
                h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
                indie_hash_map[h].append(r.article_id)

        for ids in indie_hash_map.values():
            if len(ids) >= 2:
                for k in range(1, len(ids)):
                    pairs.add((ids[k], ids[0]))

        # Method 2: URL normalization (same domain + path → likely same article)
        url_map: dict[str, list[int]] = defaultdict(list)
        for r in records:
            if r.url:
                parsed = urlparse(r.url)
                # Normalize: strip www, lowercase, remove trailing slash
                domain = parsed.netloc.lower().replace("www.", "")
                path = parsed.path.rstrip("/").lower()
                if path and path != "/":
                    url_key = f"{domain}{path}"
                    url_map[url_key].append(r.article_id)

        for ids in url_map.values():
            if len(ids) >= 2:
                for k in range(1, len(ids)):
                    pair = (ids[k], ids[0])
                    if pair not in pairs and (ids[0], ids[k]) not in pairs:
                        pairs.add(pair)

        # Method 3: Word-level shingle Jaccard for near-duplicates
        def shingles(text: str, k: int = 5) -> set[tuple]:
            words = text.lower().split()
            if len(words) < k:
                return set()
            return {tuple(words[i : i + k]) for i in range(len(words) - k + 1)}

        # Only check articles not already paired, limit to O(n^2) with early exit
        paired_ids = {p[0] for p in pairs} | {p[1] for p in pairs}
        unpaired = [r for r in records if r.article_id not in paired_ids]

        # Pre-compute shingles
        rec_shingles = []
        for r in unpaired:
            rec_shingles.append((r, shingles(r.content_snippet)))

        for i in range(len(rec_shingles)):
            ri, si = rec_shingles[i]
            if not si:
                continue
            for j in range(i + 1, len(rec_shingles)):
                rj, sj = rec_shingles[j]
                if not sj:
                    continue
                # Jaccard similarity
                intersection = len(si & sj)
                union_size = len(si | sj)
                if union_size > 0:
                    jaccard = intersection / union_size
                    if jaccard >= self.CONTENT_SIM_THRESHOLD:
                        pairs.add((rj.article_id, ri.article_id))

        return list(pairs)

    # ── Entity: cross-article consensus within independent clusters ───────

    ENTITY_CONSENSUS_THRESHOLD = 0.75  # 75% of cluster must agree
    MIN_CLUSTER_SIZE_FOR_ENTITIES = 3  # need 3+ articles for reliable consensus

    def build_entity_ground_truth(
        self, records: list[EvalRecord]
    ) -> dict[str, list[dict]]:
        """Build entity GT from cross-article consensus in independent clusters.

        Changes from v1:
          - Match on normalized name only (ignore entity type)
          - Filter noisy/stopword entities before counting
          - Require 75% consensus (was 50%)
          - Require 3+ articles in cluster (was 2+)
          - Normalize: strip titles, prefixes, Arabic forms
        """
        clusters = self.build_cluster_ground_truth(records)
        record_map = {r.article_id: r for r in records}

        result: dict[str, list[dict]] = {}
        for cluster_key, article_ids in clusters.items():
            if len(article_ids) < self.MIN_CLUSTER_SIZE_FOR_ENTITIES:
                continue

            # Count normalized entity names across cluster (ignore type)
            entity_counter: Counter[str] = Counter()
            # Track original type votes per normalized name
            type_votes: dict[str, Counter] = defaultdict(Counter)

            for aid in article_ids:
                rec = record_map.get(aid)
                if not rec:
                    continue
                seen = set()
                for name, etype in zip(rec.entity_names, rec.entity_types):
                    if is_noisy_entity(name):
                        continue
                    norm = normalize_entity_name(name)
                    if not norm or is_noisy_entity(norm):
                        continue
                    if norm not in seen:
                        entity_counter[norm] += 1
                        type_votes[norm][etype.lower()] += 1
                        seen.add(norm)

            threshold = len(article_ids) * self.ENTITY_CONSENSUS_THRESHOLD
            consensus = []
            for norm_name, count in entity_counter.items():
                if count >= threshold:
                    # Use majority type vote
                    best_type = type_votes[norm_name].most_common(1)[0][0]
                    consensus.append({"name": norm_name, "type": best_type})

            if consensus:
                result[cluster_key] = consensus

        return result

    # ── Geo: extract countries from article text ──────────────────────────

    def build_geo_ground_truth(
        self, records: list[EvalRecord]
    ) -> dict[int, dict]:
        """Extract country mentions from article text (title + content).

        Uses pre-compiled regex patterns against a comprehensive country dictionary
        (aligned with the system's geo extraction service).
        Title mentions are weighted 2x to prioritise geographic focus.
        Requires ≥2 weighted mentions to avoid false positives from passing refs.

        Returns per-article dict with:
          - country: top country code (for backward compat)
          - all_countries: set of ALL country codes with ≥2 weighted mentions
        """
        result = {}
        for r in records:
            title_text = (r.title or "").lower()
            body_text = (r.content_snippet or "").lower()
            full_text = f"{title_text} {body_text}"
            if len(full_text) < 50:
                continue

            country_hits: Counter[str] = Counter()
            for code, compiled in _COMPILED_GT_PATTERNS:
                title_matches = len(compiled.findall(title_text))
                body_matches = len(compiled.findall(full_text))
                if title_matches or body_matches:
                    # Title mentions weighted 2x
                    country_hits[code] += title_matches * 2 + body_matches

            if country_hits:
                top_country, top_count = country_hits.most_common(1)[0]
                # Require minimum 2 weighted mentions to avoid false positives
                if top_count >= 2:
                    # All countries that meet the minimum mention threshold
                    valid_countries = {
                        code for code, cnt in country_hits.items() if cnt >= 2
                    }
                    result[r.article_id] = {
                        "country": top_country,
                        "name": top_country,
                        "mention_count": top_count,
                        "all_countries": valid_countries,
                    }
        return result

    # ── Conflict: text-based claim analysis ───────────────────────────────

    def build_conflict_ground_truth(
        self, records: list[EvalRecord]
    ) -> list[str]:
        """Detect potential conflicts/contradictions from article text.

        An independent cluster is flagged as conflicting if:
          - Multiple articles in the cluster contain opposing keyword signals
          - Different sources report conflicting claims (keyword divergence)
          - Requires at least 2 distinct sources with signals
        """
        clusters = self.build_cluster_ground_truth(records)
        record_map = {r.article_id: r for r in records}

        conflict_clusters = []
        for cluster_key, article_ids in clusters.items():
            if len(article_ids) < 2:
                continue

            # Analyze conflict keyword density per article
            article_conflict_scores = []
            article_sources = set()
            sources_with_signals: set[int] = set()
            for aid in article_ids:
                rec = record_map.get(aid)
                if not rec:
                    continue
                article_sources.add(rec.source_id)
                text = f"{rec.title} {rec.content_snippet}".lower()
                score = sum(
                    len(re.findall(r"\b" + re.escape(kw) + r"\b", text))
                    for kw in _CONFLICT_KEYWORDS
                )
                # Normalize by text length (per 1000 chars)
                norm_score = (score / max(len(text), 1)) * 1000
                article_conflict_scores.append(norm_score)
                if norm_score > 1.0:
                    sources_with_signals.add(rec.source_id)

            if not article_conflict_scores:
                continue

            avg_score = sum(article_conflict_scores) / len(article_conflict_scores)
            max_score = max(article_conflict_scores)
            min_score = min(article_conflict_scores)
            source_diversity = len(article_sources)

            # Flag as conflict if:
            # - High average conflict keyword density (> 4 per 1000 chars)
            #   AND signals from at least 2 sources
            # - OR significant variation between articles (disagreement signal)
            #   AND multiple sources with signals
            has_conflict = (
                (avg_score > 4.0 and len(sources_with_signals) >= 2)
                or (
                    source_diversity >= 2
                    and len(sources_with_signals) >= 2
                    and max_score - min_score > 3.0
                )
            )

            if has_conflict:
                conflict_clusters.append(cluster_key)

        return sorted(conflict_clusters)

    def build_all(self, records: list[EvalRecord]) -> dict[str, Any]:
        """Build all independent ground-truth structures."""
        return {
            "clusters": self.build_cluster_ground_truth(records),
            "dedup_pairs": self.build_dedup_ground_truth(records),
            "entity_consensus": self.build_entity_ground_truth(records),
            "conflict_events": self.build_conflict_ground_truth(records),
            "geo_truth": self.build_geo_ground_truth(records),
        }


# ── Source quality extraction ─────────────────────────────────────────────────


@dataclass
class SourceQualityRecord:
    """Quality metrics for a single source."""
    source_id: int
    source_name: str
    language: str
    country: str
    total_articles: int
    total_with_content: int
    total_duplicates: int
    total_with_entities: int
    total_with_story: int
    avg_quality_score: float
    avg_content_length: float
    extraction_success_rate: float
    duplication_rate: float
    noise_ratio: float  # articles with quality_score < 0.3
    quality_class: str  # HIGH, MEDIUM, LOW

    def to_dict(self) -> dict:
        return asdict(self)


class SourceQualityExtractor:
    """Evaluate source quality from existing data."""

    def extract_all(self) -> list[SourceQualityRecord]:
        """Evaluate all active sources."""
        sources = Source.objects.filter(is_active=True)
        records = []
        for source in sources:
            record = self._evaluate_source(source)
            if record:
                records.append(record)
        return sorted(records, key=lambda r: r.avg_quality_score, reverse=True)

    def _evaluate_source(self, source: Source) -> SourceQualityRecord | None:
        articles = Article.objects.filter(source=source)
        total = articles.count()
        if total == 0:
            return None

        with_content = articles.extra(
            where=["LENGTH(content) > %s"], params=[200]
        ).count()

        duplicates = articles.filter(is_duplicate=True).count()

        with_entities = articles.filter(
            article_entities__isnull=False
        ).distinct().count()

        with_story = articles.filter(story__isnull=False).count()

        # Quality scores
        from django.db.models import Avg
        avg_quality = articles.aggregate(avg_q=Avg("quality_score"))["avg_q"] or 0
        avg_quality = float(avg_quality)

        # Content lengths
        lengths = list(articles.values_list("content", flat=True))
        avg_length = sum(len(c or "") for c in lengths) / len(lengths) if lengths else 0

        # Noise: articles with very low quality
        noise_count = articles.filter(quality_score__lt=0.3).count()

        extraction_rate = with_content / total if total else 0
        dup_rate = duplicates / total if total else 0
        noise_rate = noise_count / total if total else 0

        # Classification
        if avg_quality >= 0.6 and extraction_rate >= 0.8 and noise_rate < 0.2:
            quality_class = "HIGH"
        elif avg_quality >= 0.4 and extraction_rate >= 0.5:
            quality_class = "MEDIUM"
        else:
            quality_class = "LOW"

        return SourceQualityRecord(
            source_id=source.id,
            source_name=source.name,
            language=source.language or source.default_language or "unknown",
            country=source.country or source.default_country or "unknown",
            total_articles=total,
            total_with_content=with_content,
            total_duplicates=duplicates,
            total_with_entities=with_entities,
            total_with_story=with_story,
            avg_quality_score=round(avg_quality, 3),
            avg_content_length=round(avg_length),
            extraction_success_rate=round(extraction_rate, 3),
            duplication_rate=round(dup_rate, 3),
            noise_ratio=round(noise_rate, 3),
            quality_class=quality_class,
        )
