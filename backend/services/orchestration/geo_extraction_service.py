from __future__ import annotations

import logging
import re
from decimal import Decimal

from sources.models import Article, Entity

logger = logging.getLogger(__name__)

# ── Geo gazetteer ─────────────────────────────────────────────────────────────
# Compact lookup for common geopolitical locations → (country_code, lat, lon).
# A production system would use a full gazetteer (GeoNames) or geocoding API.
# This gives immediate value without external dependencies.

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
    "tehran": ("IR", 35.69, 51.39),
    "riyadh": ("SA", 24.71, 46.67),
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
}

# Pattern for "in <Location>" or "near <Location>"
_IN_LOCATION_RE = re.compile(
    r"\b(?:in|near|from|at|across)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
)


class GeoExtractionService:
    """Extract and normalise geographic information from article content."""

    def extract_geo(self, article: Article) -> dict:
        """Return dict with location_name, country, lat, lon (or empty values)."""
        text = f"{article.title} {article.content}"
        text_lower = text.lower()

        # 1. Try gazetteer lookup against known locations in text
        best = self._gazetteer_lookup(text_lower)
        if best:
            return best

        # 2. Try "in <Location>" pattern
        best = self._pattern_lookup(text)
        if best:
            return best

        # 3. Try location entities already extracted for this article
        best = self._entity_lookup(article)
        if best:
            return best

        return {
            "location_name": "",
            "location_country": "",
            "location_lat": None,
            "location_lon": None,
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

    def _pattern_lookup(self, text: str) -> dict | None:
        matches = _IN_LOCATION_RE.findall(text)
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

    def _entity_lookup(self, article: Article) -> dict | None:
        """Use location entities already extracted from the article."""
        from sources.models import ArticleEntity, Entity

        location_entity = (
            ArticleEntity.objects.filter(
                article=article,
                entity__entity_type=Entity.EntityType.LOCATION,
            )
            .select_related("entity")
            .order_by("-relevance_score")
            .first()
        )
        if not location_entity:
            return None

        entity = location_entity.entity
        key = entity.normalized_name
        if key in _GEO_GAZETTEER:
            country, lat, lon = _GEO_GAZETTEER[key]
            return {
                "location_name": entity.name,
                "location_country": country,
                "location_lat": Decimal(str(lat)),
                "location_lon": Decimal(str(lon)),
            }
        return {
            "location_name": entity.name,
            "location_country": entity.country,
            "location_lat": entity.latitude,
            "location_lon": entity.longitude,
        }
