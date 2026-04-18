from __future__ import annotations

import logging
import re
from collections import Counter
from decimal import Decimal

from sources.models import Article, Entity

logger = logging.getLogger(__name__)

# ── Geo gazetteer ─────────────────────────────────────────────────────────────
# Compact lookup for common geopolitical locations → (country_code, lat, lon).

_GEO_GAZETTEER: dict[str, tuple[str, float, float]] = {
    # Middle East
    "gaza": ("PS", 31.5, 34.47),
    "gaza strip": ("PS", 31.4, 34.39),
    "west bank": ("PS", 31.95, 35.3),
    "ramallah": ("PS", 31.9, 35.2),
    "jerusalem": ("IL", 31.77, 35.23),
    "tel aviv": ("IL", 32.09, 34.78),
    "beirut": ("LB", 33.89, 35.5),
    "damascus": ("SY", 33.51, 36.29),
    "aleppo": ("SY", 36.2, 37.15),
    "baghdad": ("IQ", 33.31, 44.37),
    "basra": ("IQ", 30.51, 47.81),
    "mosul": ("IQ", 36.34, 43.14),
    "erbil": ("IQ", 36.19, 44.01),
    "tehran": ("IR", 35.69, 51.39),
    "riyadh": ("SA", 24.71, 46.67),
    "jeddah": ("SA", 21.49, 39.19),
    "mecca": ("SA", 21.39, 39.86),
    "cairo": ("EG", 30.04, 31.24),
    "amman": ("JO", 31.95, 35.93),
    "sanaa": ("YE", 15.37, 44.19),
    "aden": ("YE", 12.78, 45.03),
    "doha": ("QA", 25.29, 51.53),
    "dubai": ("AE", 25.2, 55.27),
    "abu dhabi": ("AE", 24.45, 54.65),
    "muscat": ("OM", 23.61, 58.54),
    "kuwait city": ("KW", 29.37, 47.98),
    "manama": ("BH", 26.23, 50.59),
    # North Africa
    "tripoli": ("LY", 32.9, 13.18),
    "benghazi": ("LY", 32.12, 20.09),
    "tunis": ("TN", 36.81, 10.18),
    "algiers": ("DZ", 36.75, 3.04),
    "rabat": ("MA", 34.01, -6.84),
    "casablanca": ("MA", 33.57, -7.59),
    "khartoum": ("SD", 15.59, 32.53),
    # Europe
    "london": ("GB", 51.51, -0.13),
    "paris": ("FR", 48.86, 2.35),
    "berlin": ("DE", 52.52, 13.41),
    "moscow": ("RU", 55.76, 37.62),
    "kyiv": ("UA", 50.45, 30.52),
    "kiev": ("UA", 50.45, 30.52),
    "brussels": ("BE", 50.85, 4.35),
    "rome": ("IT", 41.9, 12.5),
    "madrid": ("ES", 40.42, -3.7),
    "ankara": ("TR", 39.93, 32.85),
    "istanbul": ("TR", 41.01, 28.98),
    "warsaw": ("PL", 52.23, 21.01),
    "bucharest": ("RO", 44.43, 26.1),
    "vienna": ("AT", 48.21, 16.37),
    # Asia
    "beijing": ("CN", 39.9, 116.4),
    "shanghai": ("CN", 31.23, 121.47),
    "tokyo": ("JP", 35.68, 139.69),
    "new delhi": ("IN", 28.61, 77.21),
    "delhi": ("IN", 28.61, 77.21),
    "mumbai": ("IN", 19.08, 72.88),
    "islamabad": ("PK", 33.69, 73.04),
    "kabul": ("AF", 34.53, 69.17),
    "seoul": ("KR", 37.57, 126.98),
    "pyongyang": ("KP", 39.04, 125.76),
    "taipei": ("TW", 25.03, 121.57),
    "bangkok": ("TH", 13.76, 100.5),
    "jakarta": ("ID", -6.2, 106.85),
    # Americas
    "washington": ("US", 38.91, -77.04),
    "new york": ("US", 40.71, -74.01),
    "los angeles": ("US", 34.05, -118.24),
    "mexico city": ("MX", 19.43, -99.13),
    "bogota": ("CO", 4.71, -74.07),
    "buenos aires": ("AR", -34.6, -58.38),
    "brasilia": ("BR", -15.79, -47.88),
    "sao paulo": ("BR", -23.55, -46.63),
    "havana": ("CU", 23.11, -82.37),
    "caracas": ("VE", 10.49, -66.88),
    # Africa
    "nairobi": ("KE", -1.29, 36.82),
    "lagos": ("NG", 6.52, 3.38),
    "abuja": ("NG", 9.06, 7.49),
    "addis ababa": ("ET", 9.02, 38.75),
    "johannesburg": ("ZA", -26.2, 28.04),
    "mogadishu": ("SO", 2.05, 45.32),
    "kinshasa": ("CD", -4.32, 15.31),
    # Countries (centroid approximations)
    "ukraine": ("UA", 48.38, 31.17),
    "russia": ("RU", 61.52, 105.32),
    "syria": ("SY", 34.8, 38.99),
    "iraq": ("IQ", 33.22, 43.68),
    "iran": ("IR", 32.43, 53.69),
    "yemen": ("YE", 15.55, 48.52),
    "lebanon": ("LB", 33.85, 35.86),
    "israel": ("IL", 31.05, 34.85),
    "palestine": ("PS", 31.95, 35.23),
    "egypt": ("EG", 26.82, 30.8),
    "libya": ("LY", 26.34, 17.23),
    "sudan": ("SD", 12.86, 30.22),
    "afghanistan": ("AF", 33.94, 67.71),
    "pakistan": ("PK", 30.38, 69.35),
    "china": ("CN", 35.86, 104.2),
    "taiwan": ("TW", 23.7, 120.96),
    "north korea": ("KP", 40.34, 127.51),
    "south korea": ("KR", 35.91, 127.77),
    "united states": ("US", 39.83, -98.58),
    "united kingdom": ("GB", 55.38, -3.44),
    "saudi arabia": ("SA", 23.89, 45.08),
    "turkey": ("TR", 38.96, 35.24),
    "india": ("IN", 20.59, 78.96),
    "japan": ("JP", 36.2, 138.25),
    "germany": ("DE", 51.17, 10.45),
    "france": ("FR", 46.23, 2.21),
    "italy": ("IT", 41.87, 12.57),
    "spain": ("ES", 40.46, -3.75),
    "nigeria": ("NG", 9.08, 8.68),
    "ethiopia": ("ET", 9.15, 40.49),
    "somalia": ("SO", 5.15, 46.2),
    "myanmar": ("MM", 21.91, 95.96),
    "jordan": ("JO", 30.59, 36.24),
    # ── Arabic names ─────────────────────────────────────────────
    # Middle East
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
    "البصرة": ("IQ", 30.51, 47.81),
    "الموصل": ("IQ", 36.34, 43.14),
    "أربيل": ("IQ", 36.19, 44.01),
    "طهران": ("IR", 35.69, 51.39),
    "الرياض": ("SA", 24.71, 46.67),
    "جدة": ("SA", 21.49, 39.19),
    "مكة": ("SA", 21.39, 39.86),
    "المدينة": ("SA", 24.47, 39.61),
    "القاهرة": ("EG", 30.04, 31.24),
    "عمان": ("JO", 31.95, 35.93),
    "صنعاء": ("YE", 15.37, 44.19),
    "عدن": ("YE", 12.78, 45.03),
    "الدوحة": ("QA", 25.29, 51.53),
    "دبي": ("AE", 25.2, 55.27),
    "أبو ظبي": ("AE", 24.45, 54.65),
    "الكويت": ("KW", 29.37, 47.98),
    # North Africa
    "طرابلس": ("LY", 32.9, 13.18),
    "بنغازي": ("LY", 32.12, 20.09),
    "تونس": ("TN", 36.81, 10.18),
    "الجزائر": ("DZ", 36.75, 3.04),
    "الرباط": ("MA", 34.01, -6.84),
    "الدار البيضاء": ("MA", 33.57, -7.59),
    "الخرطوم": ("SD", 15.59, 32.53),
    # Countries (Arabic)
    "أوكرانيا": ("UA", 48.38, 31.17),
    "روسيا": ("RU", 61.52, 105.32),
    "سوريا": ("SY", 34.8, 38.99),
    "العراق": ("IQ", 33.22, 43.68),
    "إيران": ("IR", 32.43, 53.69),
    "اليمن": ("YE", 15.55, 48.52),
    "لبنان": ("LB", 33.85, 35.86),
    "فلسطين": ("PS", 31.95, 35.23),
    "مصر": ("EG", 26.82, 30.8),
    "ليبيا": ("LY", 26.34, 17.23),
    "السودان": ("SD", 12.86, 30.22),
    "أفغانستان": ("AF", 33.94, 67.71),
    "باكستان": ("PK", 30.38, 69.35),
    "الصين": ("CN", 35.86, 104.2),
    "السعودية": ("SA", 24.71, 46.67),
    "الأردن": ("JO", 31.95, 35.93),
    "الإمارات": ("AE", 24.45, 54.65),
}

# ── Country text patterns → ISO code ─────────────────────────────────────────
# Matches country names, demonyms, and key city names to country codes.
# Used as a high-recall fallback after gazetteer lookup.

_COUNTRY_TEXT_PATTERNS: dict[str, list[str]] = {
    "US": ["united states", "u.s.", "usa", "america", "american"],
    "GB": ["united kingdom", "u.k.", "britain", "british", "england", "scotland", "wales"],
    "IL": ["israel", "israeli"],
    "PS": ["palestine", "palestinian", "gaza", "west bank", "فلسطيني"],
    "UA": ["ukraine", "ukrainian", "kyiv", "kiev", "أوكراني"],
    "RU": ["russia", "russian", "moscow", "kremlin", "روسي"],
    "CN": ["china", "chinese", "beijing", "صيني"],
    "IR": ["iran", "iranian", "tehran", "إيراني"],
    "IQ": ["iraq", "iraqi", "baghdad", "عراقي"],
    "SY": ["syria", "syrian", "damascus", "سوري"],
    "LB": ["lebanon", "lebanese", "beirut", "لبناني"],
    "SA": ["saudi arabia", "saudi", "riyadh", "سعودي"],
    "AE": ["emirates", "uae", "emirati", "dubai", "abu dhabi", "إماراتي"],
    "EG": ["egypt", "egyptian", "cairo", "مصري"],
    "TR": ["turkey", "turkish", "ankara", "istanbul", "تركي"],
    "YE": ["yemen", "yemeni", "sanaa", "يمني"],
    "AF": ["afghanistan", "afghan", "kabul", "أفغاني"],
    "PK": ["pakistan", "pakistani", "islamabad", "باكستاني"],
    "IN": ["india", "indian", "delhi", "mumbai", "هندي"],
    "JP": ["japan", "japanese", "tokyo", "ياباني"],
    "KR": ["south korea", "korean", "seoul", "كوري"],
    "KP": ["north korea", "pyongyang"],
    "DE": ["germany", "german", "berlin", "ألماني"],
    "FR": ["france", "french", "paris", "فرنسي"],
    "IT": ["italy", "italian", "rome", "إيطالي"],
    "ES": ["spain", "spanish", "madrid", "إسباني"],
    "LY": ["libya", "libyan", "tripoli", "ليبي"],
    "SD": ["sudan", "sudanese", "khartoum", "سوداني"],
    "SO": ["somalia", "somali", "mogadishu", "صومالي"],
    "NG": ["nigeria", "nigerian", "abuja", "lagos", "نيجيري"],
    "ET": ["ethiopia", "ethiopian", "addis ababa", "إثيوبي"],
    "MM": ["myanmar", "burmese", "burma"],
    "TW": ["taiwan", "taiwanese", "taipei"],
    "JO": ["jordan", "jordanian", "amman", "أردني"],
    "QA": ["qatar", "qatari", "doha", "قطري"],
    "KW": ["kuwait", "kuwaiti", "كويتي"],
    "BH": ["bahrain", "bahraini", "بحريني"],
    "OM": ["oman", "omani", "عماني"],
    "MA": ["morocco", "moroccan", "rabat", "مغربي"],
    "TN": ["tunisia", "tunisian", "تونسي"],
    "DZ": ["algeria", "algerian", "جزائري"],
}

# Pre-compile country text patterns for fast matching
_COMPILED_COUNTRY_PATTERNS: list[tuple[str, re.Pattern]] = []
for _code, _patterns in _COUNTRY_TEXT_PATTERNS.items():
    for _pat in sorted(_patterns, key=len, reverse=True):
        _COMPILED_COUNTRY_PATTERNS.append(
            (_code, re.compile(r"\b" + re.escape(_pat) + r"\b", re.IGNORECASE))
        )

# Pattern for "in <Location>" or "near <Location>"
_IN_LOCATION_RE = re.compile(
    r"\b(?:in|near|from|at|across)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
)
# Arabic preposition + location pattern (في بغداد، قرب دمشق، من القاهرة)
_IN_LOCATION_AR_RE = re.compile(
    r"(?:في|قرب|من|إلى|نحو|على)\s+([\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+){0,2})"
)


class GeoExtractionService:
    """Extract and normalise geographic information from article content."""

    def extract_geo(self, article: Article) -> dict:
        """Return dict with location_name, country, lat, lon (or empty values)."""
        text = f"{article.title} {article.content}"
        title_lower = article.title.lower() if article.title else ""
        text_lower = text.lower()

        # 1. NER entity lookup — most precise, from already-extracted LOC entities
        best = self._entity_lookup(article)
        if best and best.get("location_country"):
            return best

        # 2. Gazetteer lookup against known locations (prefer title matches)
        best = self._gazetteer_lookup(title_lower)
        if best:
            return best
        best = self._gazetteer_lookup(text_lower)
        if best:
            return best

        # 3. Country text pattern matching (demonyms + country names)
        best = self._country_pattern_lookup(title_lower, text_lower)
        if best:
            return best

        # 4. "in <Location>" regex pattern
        best = self._pattern_lookup(text)
        if best:
            return best

        return {
            "location_name": "",
            "location_country": "",
            "location_lat": None,
            "location_lon": None,
        }

    def _entity_lookup(self, article: Article) -> dict | None:
        """Use NER location entities already extracted from the article."""
        from sources.models import ArticleEntity, Entity

        loc_entities = list(
            ArticleEntity.objects.filter(
                article=article,
                entity__entity_type=Entity.EntityType.LOCATION,
            )
            .select_related("entity")
            .order_by("-relevance_score")[:5]
        )
        if not loc_entities:
            return None

        # Try each LOC entity against the gazetteer
        for ae in loc_entities:
            entity = ae.entity
            key = entity.normalized_name
            if key in _GEO_GAZETTEER:
                country, lat, lon = _GEO_GAZETTEER[key]
                return {
                    "location_name": entity.name,
                    "location_country": country,
                    "location_lat": Decimal(str(lat)),
                    "location_lon": Decimal(str(lon)),
                }

        # Try country text patterns on entity names
        for ae in loc_entities:
            name_lower = ae.entity.normalized_name
            for code, compiled in _COMPILED_COUNTRY_PATTERNS:
                if compiled.search(name_lower):
                    return {
                        "location_name": ae.entity.name,
                        "location_country": code,
                        "location_lat": None,
                        "location_lon": None,
                    }

        # Fallback: return first entity even without country
        entity = loc_entities[0].entity
        return {
            "location_name": entity.name,
            "location_country": entity.country or "",
            "location_lat": entity.latitude,
            "location_lon": entity.longitude,
        }

    def _gazetteer_lookup(self, text_lower: str) -> dict | None:
        # Prefer longer names first (e.g. "gaza strip" over "gaza")
        sorted_entries = sorted(
            _GEO_GAZETTEER.items(), key=lambda x: len(x[0]), reverse=True
        )
        for name, (country, lat, lon) in sorted_entries:
            # Word-boundary match to avoid partial matches
            pattern = r"\b" + re.escape(name) + r"\b"
            if re.search(pattern, text_lower):
                return {
                    "location_name": name.title(),
                    "location_country": country,
                    "location_lat": Decimal(str(lat)),
                    "location_lon": Decimal(str(lon)),
                }
        return None

    def _country_pattern_lookup(
        self, title_lower: str, text_lower: str
    ) -> dict | None:
        """Match country names, demonyms, and city names to country codes.

        Counts all mentions across the text and returns the most-mentioned
        country, with a 2x weight for title mentions.
        """
        hits: Counter[str] = Counter()
        for code, compiled in _COMPILED_COUNTRY_PATTERNS:
            title_matches = len(compiled.findall(title_lower))
            body_matches = len(compiled.findall(text_lower))
            if title_matches or body_matches:
                # Title mentions are weighted 2x
                hits[code] += title_matches * 2 + body_matches

        if not hits:
            return None

        top_code = hits.most_common(1)[0][0]
        # Try to find coords from gazetteer for the top country
        for name, (country, lat, lon) in _GEO_GAZETTEER.items():
            if country == top_code:
                return {
                    "location_name": name.title(),
                    "location_country": top_code,
                    "location_lat": Decimal(str(lat)),
                    "location_lon": Decimal(str(lon)),
                }
        return {
            "location_name": top_code,
            "location_country": top_code,
            "location_lat": None,
            "location_lon": None,
        }

    def _pattern_lookup(self, text: str) -> dict | None:
        # Try English patterns
        matches = _IN_LOCATION_RE.findall(text)
        # Try Arabic patterns
        matches += _IN_LOCATION_AR_RE.findall(text)

        for location_name in matches:
            key = location_name.strip().lower()
            if key in _GEO_GAZETTEER:
                country, lat, lon = _GEO_GAZETTEER[key]
                return {
                    "location_name": location_name.strip(),
                    "location_country": country,
                    "location_lat": Decimal(str(lat)),
                    "location_lon": Decimal(str(lon)),
                }
        # Return first extracted location even without coords
        if matches:
            return {
                "location_name": matches[0].strip(),
                "location_country": "",
                "location_lat": None,
                "location_lon": None,
            }
        return None
