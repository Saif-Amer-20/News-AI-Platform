from __future__ import annotations

import json
import logging
import re

from django.conf import settings

from sources.models import Article

logger = logging.getLogger(__name__)

# ── Event-type classification rules ──────────────────────────────────────────
# Each rule: (event_type, weight, compiled regex pattern)
# Patterns are checked against normalised title+content. The event type with
# the highest cumulative weight wins.

_RULES: list[tuple[str, float, re.Pattern]] = [
    # ── English rules ────────────────────────────────────────────
    # Strike / military strike
    ("strike", 3.0, re.compile(r"\b(?:air\s?strike|missile\s?strike|drone\s?strike|military\s?strike)\b", re.I)),
    ("strike", 2.0, re.compile(r"\b(?:bombed|bombing|bombard|shelling|shelled)\b", re.I)),
    ("strike", 1.5, re.compile(r"\b(?:airstrike|strikes?\s+(?:on|against|hit|target))\b", re.I)),
    ("strike", 1.0, re.compile(r"\b(?:rocket|mortar|artillery)\s+(?:fire|attack|hit)\b", re.I)),
    # Explosion
    ("explosion", 3.0, re.compile(r"\b(?:explosion|exploded|detonation|detonated|blast)\b", re.I)),
    ("explosion", 2.0, re.compile(r"\b(?:car\s?bomb|suicide\s?bomb|ied|improvised\s+explosive)\b", re.I)),
    ("explosion", 1.5, re.compile(r"\b(?:blew\s+up|went\s+off|blasts?)\b", re.I)),
    # Protest
    ("protest", 3.0, re.compile(r"\b(?:protest(?:s|ers|ed|ing)?|demonstration|rally|rallies)\b", re.I)),
    ("protest", 2.0, re.compile(r"\b(?:march(?:ed|ing)?|sit-in|picket|uprising|unrest)\b", re.I)),
    ("protest", 1.5, re.compile(r"\b(?:tear\s?gas|water\s?cannon|riot(?:s|ing)?)\b", re.I)),
    ("protest", 1.0, re.compile(r"\b(?:crowd|chant(?:ed|ing)?|banner|placard)\b", re.I)),
    # Political event
    ("political", 3.0, re.compile(r"\b(?:election|voted|ballot|referendum|inaugurat)\b", re.I)),
    ("political", 2.5, re.compile(r"\b(?:parliament|congress|senate|legislation|law\s?passed)\b", re.I)),
    ("political", 2.0, re.compile(r"\b(?:prime\s+minister|president|cabinet|coalition|opposition)\b", re.I)),
    ("political", 1.5, re.compile(r"\b(?:political\s+(?:crisis|party|reform|scandal))\b", re.I)),
    ("political", 1.0, re.compile(r"\b(?:govern(?:ment|or)|minister|diplomat)\b", re.I)),
    # Armed conflict
    ("conflict", 3.0, re.compile(r"\b(?:war|warfare|combat|battle|offensive)\b", re.I)),
    ("conflict", 2.5, re.compile(r"\b(?:troops|soldiers|military\s+operation|invasion|occupied)\b", re.I)),
    ("conflict", 2.0, re.compile(r"\b(?:casualties|killed\s+in\s+(?:action|fighting)|wounded)\b", re.I)),
    ("conflict", 1.5, re.compile(r"\b(?:ceasefire|truce|armistice|frontline)\b", re.I)),
    # Natural disaster
    ("disaster", 3.0, re.compile(r"\b(?:earthquake|tsunami|hurricane|typhoon|cyclone|tornado)\b", re.I)),
    ("disaster", 2.5, re.compile(r"\b(?:flood(?:s|ed|ing)?|wildfire|landslide|volcanic\s+eruption)\b", re.I)),
    ("disaster", 2.0, re.compile(r"\b(?:devastation|disaster|catastrophe|emergency\s+(?:response|relief))\b", re.I)),
    # Economic
    ("economic", 2.5, re.compile(r"\b(?:inflation|recession|gdp|stock\s+market|economic\s+(?:crisis|growth))\b", re.I)),
    ("economic", 2.0, re.compile(r"\b(?:sanctions?|tariff|trade\s+(?:war|deal|agreement))\b", re.I)),
    ("economic", 1.5, re.compile(r"\b(?:central\s+bank|interest\s+rate|currency|debt\s+crisis)\b", re.I)),
    # Diplomacy
    ("diplomacy", 3.0, re.compile(r"\b(?:peace\s+(?:deal|talks|agreement|treaty|negotiations?))\b", re.I)),
    ("diplomacy", 2.0, re.compile(r"\b(?:summit|bilateral|multilateral|diplomatic\s+(?:ties|relations))\b", re.I)),
    ("diplomacy", 1.5, re.compile(r"\b(?:ambassador|envoy|mediat(?:e|ion|or))\b", re.I)),
    # Crime
    ("crime", 3.0, re.compile(r"\b(?:assassination|assassinated|murder(?:ed)?|kidnapp?(?:ed|ing)?)\b", re.I)),
    ("crime", 2.0, re.compile(r"\b(?:arrest(?:ed)?|detained|prison(?:er)?|court\s+(?:ruling|sentence))\b", re.I)),
    ("crime", 1.5, re.compile(r"\b(?:smuggling|trafficking|corruption|fraud)\b", re.I)),
    # Health
    ("health", 3.0, re.compile(r"\b(?:pandemic|epidemic|outbreak|virus|vaccine)\b", re.I)),
    ("health", 2.0, re.compile(r"\b(?:covid|corona|cholera|ebola|malaria|polio)\b", re.I)),
    ("health", 1.5, re.compile(r"\b(?:quarantine|lockdown|infection|WHO|health\s+emergency)\b", re.I)),
    # Technology
    ("technology", 2.5, re.compile(r"\b(?:cyber\s?attack|hack(?:ed|ing)?|data\s+breach|ransomware)\b", re.I)),
    ("technology", 2.0, re.compile(r"\b(?:artificial\s+intelligence|AI\s+(?:model|system)|satellite\s+launch)\b", re.I)),

    # ── Arabic rules ─────────────────────────────────────────────
    # Strike
    ("strike", 3.0, re.compile(r"(?:غارة|ضربة\s+(?:جوية|صاروخية)|قصف)")),
    ("strike", 2.0, re.compile(r"(?:صاروخ|قذيفة|هاون|مدفعية)")),
    # Explosion
    ("explosion", 3.0, re.compile(r"(?:انفجار|تفجير|عبوة\s+ناسفة)")),
    ("explosion", 2.0, re.compile(r"(?:سيارة\s+مفخخة|حزام\s+ناسف)")),
    # Protest
    ("protest", 3.0, re.compile(r"(?:احتجاج|تظاهر|مظاهرة|اعتصام)")),
    ("protest", 2.0, re.compile(r"(?:غاز\s+مسيل|خراطيم\s+المياه|شغب)")),
    # Political
    ("political", 3.0, re.compile(r"(?:انتخاب|تصويت|استفتاء|برلمان)")),
    ("political", 2.0, re.compile(r"(?:رئيس\s+(?:الوزراء|الجمهورية)|حكومة|ائتلاف|معارضة)")),
    # Conflict
    ("conflict", 3.0, re.compile(r"(?:حرب|معركة|هجوم\s+عسكري|عملية\s+عسكرية)")),
    ("conflict", 2.0, re.compile(r"(?:قتلى|جرحى|ضحايا|جنود|قوات)")),
    ("conflict", 1.5, re.compile(r"(?:وقف\s+إطلاق\s+النار|هدنة)")),
    # Disaster
    ("disaster", 3.0, re.compile(r"(?:زلزال|تسونامي|إعصار|فيضان)")),
    ("disaster", 2.0, re.compile(r"(?:كارثة|طوارئ|إغاثة|انهيار\s+أرضي)")),
    # Economic
    ("economic", 2.5, re.compile(r"(?:تضخم|ركود|اقتصاد|بورصة|سوق\s+المال)")),
    ("economic", 2.0, re.compile(r"(?:عقوبات|رسوم\s+جمركية|اتفاق\s+تجاري)")),
    # Diplomacy
    ("diplomacy", 3.0, re.compile(r"(?:اتفاق\s+سلام|مفاوضات|معاهدة)")),
    ("diplomacy", 2.0, re.compile(r"(?:قمة|سفير|وساطة|علاقات\s+دبلوماسية)")),
    # Crime
    ("crime", 3.0, re.compile(r"(?:اغتيال|قتل|خطف|اعتقال)")),
    ("crime", 2.0, re.compile(r"(?:محكمة|حكم|تهريب|فساد)")),
    # Health
    ("health", 3.0, re.compile(r"(?:وباء|جائحة|فيروس|لقاح)")),
    ("health", 2.0, re.compile(r"(?:حجر\s+صحي|إغلاق|عدوى|طوارئ\s+صحية)")),
]

# Valid event types the LLM may return
_VALID_TYPES = frozenset({
    "strike", "explosion", "protest", "political", "conflict",
    "disaster", "economic", "diplomacy", "crime", "health", "technology",
})

# Minimum chars to justify an LLM fallback call
_MIN_LLM_LENGTH = 200


class NarrativeDetectionService:
    """Classify an article's narrative/event type: regex-first, LLM fallback."""

    min_confidence_weight = 2.0

    def detect(self, article: Article) -> str:
        """Return an Event.EventType value string."""
        text = f"{article.normalized_title} {article.normalized_content}"

        # 1. Fast regex classification
        result = self._classify_regex(text)
        if result != "unknown":
            return result

        # 2. LLM fallback for unclassified articles with enough content
        if len(text) >= _MIN_LLM_LENGTH:
            llm_result = self._classify_llm(text)
            if llm_result != "unknown":
                return llm_result

        return "unknown"

    def _classify_regex(self, text: str) -> str:
        scores: dict[str, float] = {}
        for event_type, weight, pattern in _RULES:
            matches = pattern.findall(text)
            if matches:
                scores[event_type] = scores.get(event_type, 0.0) + weight * len(matches)

        if not scores:
            return "unknown"

        best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
        if scores[best_type] < self.min_confidence_weight:
            return "unknown"

        logger.debug(
            "Narrative detection (regex): best=%s score=%.1f all=%s",
            best_type, scores[best_type], scores,
        )
        return best_type

    def _classify_llm(self, text: str) -> str:
        """Call Groq LLM for event classification. Returns type or 'unknown'."""
        api_key = getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            return "unknown"

        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
            )

            truncated = text[:3000]
            valid_list = ", ".join(sorted(_VALID_TYPES))

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a news event classifier. Classify the news text into "
                            f"exactly one of these types: {valid_list}. "
                            "If none fit, respond with 'unknown'. "
                            "Respond with ONLY the type name, nothing else."
                        ),
                    },
                    {"role": "user", "content": truncated},
                ],
                max_tokens=20,
                temperature=0.0,
            )

            result = (response.choices[0].message.content or "").strip().lower()
            if result in _VALID_TYPES:
                logger.debug("Narrative detection (LLM): %s", result)
                return result

        except Exception:
            logger.exception("LLM narrative classification failed")

        return "unknown"
