from __future__ import annotations

import logging
import re

from sources.models import Article

logger = logging.getLogger(__name__)

# ── Event-type classification rules ──────────────────────────────────────────
# Each rule: (event_type, weight, compiled regex pattern)
# Patterns are checked against normalised title+content. The event type with
# the highest cumulative weight wins.

_RULES: list[tuple[str, float, re.Pattern]] = [
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
]


class NarrativeDetectionService:
    """Classify an article's narrative/event type using weighted keyword rules."""

    # Minimum cumulative weight to assign a type (below → "unknown")
    min_confidence_weight = 2.0

    def detect(self, article: Article) -> str:
        """Return an Event.EventType value string."""
        text = f"{article.normalized_title} {article.normalized_content}"
        return self._classify(text)

    def _classify(self, text: str) -> str:
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
            "Narrative detection: best=%s score=%.1f all=%s",
            best_type,
            scores[best_type],
            scores,
        )
        return best_type
