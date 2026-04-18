"""Entity Relationship Service — v2 (quality-tuned).

Builds and maintains the entity co-occurrence graph stored in
``EntityRelationship`` and ``EntitySignal``.

Pipeline
────────
  EntityRelationshipService.rebuild_relationships(lookback_days)
    ├── Scans all articles published in the lookback window
    ├── Filters out blocked entities (news sources, garbage names)
    ├── For every pair with co_occurrence ≥ MIN_CO_OCCURRENCE:
    │     compute_pair_score() → strength, confidence, recency, diversity
    │     classify_relationship_type() → political/military/economic/…
    │     upsert EntityRelationship row
    └── Prune stale or weak relationships

  EntityRelationshipService.incremental_update(article)
    └── Fast per-article update called from the ingestion pipeline

Relationship Strength Formula (v2)
──────────────────────────────────
  raw_co_occ   = log1p(co_occurrence_count) / log1p(MAX_EXPECTED_CO_OCC)  [0-1]
  recency      = exp(-decay_days / HALF_LIFE_DAYS)                        [0-1]
  diversity    = distinct_sources / total_unique_sources                   [0-1]
  stability    = 1 - (1 / co_occurrence_count)  (approaches 1 for stable) [0-1]

  strength = 0.40×raw_co_occ + 0.20×recency + 0.25×diversity + 0.15×stability

Confidence (v2)
───────────────
  base = min(1.0, co_occurrence_count / MIN_FOR_FULL_CONFIDENCE)
  diversity_bonus = 0.15 × diversity
  confidence = min(1.0, base + diversity_bonus)
"""
from __future__ import annotations

import logging
import math
import re
from datetime import timedelta
from decimal import Decimal
from itertools import combinations
from typing import Optional

from django.db import transaction
from django.db.models import Count, Max, Min, Q
from django.utils import timezone

from sources.models import (
    Article,
    ArticleEntity,
    Entity,
    EntityRelationship,
    EntitySignal,
    Source,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Tunable constants
# ══════════════════════════════════════════════════════════════════════════════
_LOOKBACK_DAYS          = 90    # default rebuild window (days)
_HALF_LIFE_DAYS         = 30    # recency decay half-life
_MAX_EXPECTED_CO_OCC    = 100   # denominator for log-normalised raw_strength (was 500)
_MIN_FOR_FULL_CONF      = 8     # articles needed for confidence = 1.0
_PRUNE_AFTER_DAYS       = 90    # remove relationships with no evidence this old
_MAX_EVIDENCE_ARTICLES  = 20    # max article IDs stored per relationship

# ── Minimum thresholds (P0 noise elimination) ─────────────────────────────
_MIN_CO_OCCURRENCE      = 2     # skip pairs appearing together < 2 times
_MIN_CO_OCC_STRONG      = 3     # "strong" relationship threshold
_MIN_STRENGTH_SIGNAL    = 0.35  # minimum strength to emit NEW_RELATIONSHIP signal
_SPIKE_RATIO_THRESHOLD  = 2.0   # fire UNUSUAL_PAIR signal when growth_rate ≥ this
_MIN_STRENGTH_GRAPH     = 0.10  # minimum strength for graph inclusion

# ── Entity name blocklist (P1: news sources & garbage) ────────────────────
_BLOCKED_ENTITY_NAMES: set[str] = {
    # News sources (English)
    "reuters", "bbc", "cnn", "axios", "associated press", "ap",
    "al jazeera", "bloomberg", "nbc", "abc", "cbs", "fox news",
    "the guardian", "new york times", "washington post", "politico",
    "crypto briefing", "coindesk", "the hill", "truth social",
    # News sources (Arabic)
    "رويترز", "اكسيوس", "الحدث.نت", "الجزيرة", "بلومبرغ",
    "فرانس برس", "فرانس 24", "سكاي نيوز",
    # Garbage / NER errors
    "pop", "ran", "house", "الل", "ال", "من", "في", "على",
    "هو", "هي", "لا", "ما", "the", "a", "an", "is", "was",
    "are", "were", "has", "have", "had", "will", "can",
}

# Minimum entity name length (characters) to be included
_MIN_ENTITY_NAME_LEN = 3

# ── Arabic/English duplicate aliases (P1) ─────────────────────────────────
# Maps Arabic variant → preferred English canonical name.
# During rebuild, these are treated as the SAME entity.
_ENTITY_ALIASES: dict[str, str] = {
    "سراايل": "Israel",
    "اسرائيل": "Israel",
    "طهران": "Tehran",
    "ايران": "Iran",
    "باريس": "Paris",
    "فرنسا": "France",
    "اسلام اباد": "Islamabad",
    "باكستان": "Pakistan",
    "هرمز": "Strait of Hormuz",
    "الولايات المتحد": "United States",
    "الولايات المتحدة": "United States",
    "مصر": "Egypt",
    "سعودي": "Saudi Arabia",
    "السعودية": "Saudi Arabia",
    "بريطانيا": "United Kingdom",
    "المانيا": "Germany",
    "اوكرانيا": "Ukraine",
    "روسيا": "Russia",
    "موسكو": "Moscow",
    "كييف": "Kyiv",
    "بيروت": "Beirut",
    "لبنان": "Lebanon",
    "بكين": "Beijing",
    "الصين": "China",
    "تركيا": "Turkey",
    "الهند": "India",
    "العراق": "Iraq",
    "الجزائر": "Algeria",
}

# Build a reverse lookup: canonical_entity_id cache (populated at runtime)
_alias_entity_id_cache: dict[str, int] = {}

# ── Keyword sets for relationship-type classification ─────────────────────
# Ordered by specificity (most specific first for tie-breaking)
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "military":   ["military operation", "defense minister", "army chief",
                   "troops deployed", "naval exercise", "air force",
                   "defense", "army", "navy", "forces", "nato",
                   "deployment", "tank", "دفاع", "جيش", "قوات"],
    "conflict":   ["war", "airstrike", "bombing", "missile strike", "killed in",
                   "casualties", "battle", "shelling", "ceasefire violation",
                   "hostage", "invaded", "شن هجوم", "قصف", "معركة", "صواريخ",
                   "ضحايا", "قتل"],
    "economic":   ["trade deal", "sanction", "oil price", "gas export",
                   "investment", "billion dollar", "gdp", "economy",
                   "tariff", "trade war", "اقتصاد", "نفط", "تجارة", "عقوبات",
                   "استثمار"],
    "diplomatic": ["talks", "agreement signed", "summit", "state visit",
                   "ambassador", "treaty", "diplomacy", "bilateral",
                   "مفاوضات", "اتفاقية", "دبلوماسي", "قمة", "سفير"],
    "political":  ["election", "vote", "ruling party", "prime minister",
                   "parliament", "government policy", "cabinet",
                   "انتخابات", "حكومة", "رئيس", "برلمان", "تصويت"],
}


class EntityRelationshipService:
    """Builds and maintains the entity co-occurrence graph."""

    # ═════════════════════════════════════════════════════════════════════════
    # Public API
    # ═════════════════════════════════════════════════════════════════════════

    def rebuild_relationships(
        self,
        *,
        lookback_days: int = _LOOKBACK_DAYS,
        dry_run: bool = False,
    ) -> dict:
        """Full rebuild of relationships from the last ``lookback_days`` days.

        Returns a stats dict.
        """
        stats = {
            "examined": 0, "pairs_raw": 0, "pairs_filtered": 0,
            "created": 0, "updated": 0, "pruned": 0, "signals": 0,
            "blocked_entities": 0, "alias_merged": 0,
        }

        cutoff = timezone.now() - timedelta(days=lookback_days)

        # Load articles with their entity sets
        article_ids = list(
            Article.objects
            .filter(published_at__gte=cutoff, is_duplicate=False)
            .values_list("id", flat=True)
        )
        if not article_ids:
            logger.info("rebuild_relationships: no articles in window")
            return stats

        # ── Build entity blocklist ────────────────────────────────────────
        blocked_entity_ids = self._build_blocked_entity_ids()
        stats["blocked_entities"] = len(blocked_entity_ids)

        # ── Build alias map: entity_id → canonical_entity_id ─────────────
        alias_map = self._build_alias_map()
        stats["alias_merged"] = len(alias_map)

        # ── Total unique sources (for diversity normalization) ────────────
        total_sources = max(Source.objects.filter(is_active=True).count(), 1)

        # Group entity ids per article
        ae_pairs = list(
            ArticleEntity.objects
            .filter(article_id__in=article_ids)
            .values(
                "article_id",
                "entity_id",
                "article__published_at",
                "article__source_id",
            )
        )

        article_entities: dict[int, set[int]] = {}
        article_meta: dict[int, dict] = {}

        for row in ae_pairs:
            eid = row["entity_id"]

            # Skip blocked entities
            if eid in blocked_entity_ids:
                continue

            # Resolve aliases to canonical entity id
            eid = alias_map.get(eid, eid)

            aid = row["article_id"]
            article_entities.setdefault(aid, set()).add(eid)
            article_meta[aid] = {
                "published_at": row["article__published_at"],
                "source_id":    row["article__source_id"],
            }

        # Build pair accumulator: (a_id, b_id) → {article_ids, source_ids, dates}
        pair_data: dict[tuple[int, int], dict] = {}

        for aid, ent_ids in article_entities.items():
            stats["examined"] += 1
            ent_list = sorted(ent_ids)
            meta = article_meta[aid]

            for a_id, b_id in combinations(ent_list, 2):
                key = (min(a_id, b_id), max(a_id, b_id))
                if key not in pair_data:
                    pair_data[key] = {"articles": [], "sources": set(), "dates": []}
                pd = pair_data[key]
                pd["articles"].append(aid)
                if meta["source_id"]:
                    pd["sources"].add(meta["source_id"])
                if meta["published_at"]:
                    pd["dates"].append(meta["published_at"])

        stats["pairs_raw"] = len(pair_data)

        # ── P0: Filter out weak pairs (co_occurrence < MIN) ──────────────
        pair_data = {
            key: pd for key, pd in pair_data.items()
            if len(pd["articles"]) >= _MIN_CO_OCCURRENCE
        }
        stats["pairs_filtered"] = len(pair_data)

        # Filter pairs to only include entity IDs that still exist
        all_entity_ids = set()
        for a_id, b_id in pair_data:
            all_entity_ids.add(a_id)
            all_entity_ids.add(b_id)
        valid_entity_ids = set(
            Entity.objects.filter(id__in=all_entity_ids).values_list("id", flat=True)
        )
        pair_data = {
            (a_id, b_id): pd
            for (a_id, b_id), pd in pair_data.items()
            if a_id in valid_entity_ids and b_id in valid_entity_ids
        }

        logger.info(
            "rebuild_relationships: %d articles, %d raw pairs → %d after filtering (blocked %d entities, %d alias merges)",
            stats["examined"], stats["pairs_raw"], len(pair_data),
            stats["blocked_entities"], stats["alias_merged"],
        )

        if dry_run:
            return stats

        now = timezone.now()

        # ── Delete all old relationships and rebuild from scratch ─────────
        # This is cleaner than upsert for a full rebuild since we've changed
        # the filtering rules drastically.
        old_count = EntityRelationship.objects.count()

        # Track existing for growth-rate computation
        existing_counts: dict[tuple[int, int], int] = {}
        for row in EntityRelationship.objects.values("entity_a_id", "entity_b_id", "co_occurrence_count"):
            key = (row["entity_a_id"], row["entity_b_id"])
            existing_counts[key] = row["co_occurrence_count"]

        # Clear old relationships
        EntityRelationship.objects.all().delete()

        # Clear old relationship signals (they're now stale)
        EntitySignal.objects.filter(
            signal_type__in=[
                EntitySignal.SignalType.NEW_RELATIONSHIP,
                EntitySignal.SignalType.UNUSUAL_PAIR,
            ]
        ).delete()

        for (a_id, b_id), pd in pair_data.items():
            count      = len(pd["articles"])
            source_ids = sorted(pd["sources"])
            dates      = sorted(pd["dates"])
            last_seen  = dates[-1] if dates else now
            first_seen = dates[0] if dates else now

            strength, confidence, recency, diversity = self._compute_scores(
                count=count,
                last_seen=last_seen,
                distinct_sources=len(pd["sources"]),
                total_sources=total_sources,
                now=now,
            )

            # Get article context for type classification
            sample_text = self._get_sample_text(pd["articles"][:5])
            rel_type = self._classify_type(sample_text)

            # Growth rate vs previous rebuild
            lo, hi = (a_id, b_id) if a_id < b_id else (b_id, a_id)
            prev_count = existing_counts.get((lo, hi), 0)
            growth = (count - prev_count) / max(prev_count, 1) if prev_count > 0 else 0.0

            EntityRelationship.objects.create(
                entity_a_id=lo,
                entity_b_id=hi,
                co_occurrence_count=count,
                strength_score=Decimal(str(round(strength, 4))),
                confidence=Decimal(str(round(confidence, 4))),
                recency_score=Decimal(str(round(recency, 4))),
                source_diversity_score=Decimal(str(round(diversity, 4))),
                relationship_type=rel_type,
                last_seen_at=last_seen,
                first_seen_at=first_seen,
                supporting_article_ids=pd["articles"][-_MAX_EVIDENCE_ARTICLES:],
                supporting_source_ids=source_ids[:30],
                growth_rate=Decimal(str(round(growth, 4))),
                prev_co_occurrence_count=prev_count,
            )
            stats["created"] += 1

            # ── Signals: only meaningful ones ─────────────────────────────
            # NEW_RELATIONSHIP: only for strong new relationships
            if prev_count == 0 and count >= _MIN_CO_OCC_STRONG and strength >= _MIN_STRENGTH_SIGNAL:
                self._emit_signal(
                    entity_id=lo,
                    signal_type=EntitySignal.SignalType.NEW_RELATIONSHIP,
                    severity=EntitySignal.Severity.MEDIUM,
                    title=f"New relationship: {self._entity_name(lo)} ↔ {self._entity_name(hi)}",
                    description=f"Detected with {count} co-occurring articles, strength {strength:.2f}.",
                    metadata={"strength": strength, "entity_b_id": hi, "count": count},
                    related_entity_id=hi,
                )
                stats["signals"] += 1

            # UNUSUAL_PAIR: growth surge on an existing relationship
            if prev_count > 0 and growth >= _SPIKE_RATIO_THRESHOLD and count >= _MIN_CO_OCC_STRONG:
                self._emit_signal(
                    entity_id=lo,
                    signal_type=EntitySignal.SignalType.UNUSUAL_PAIR,
                    severity=EntitySignal.Severity.HIGH,
                    title=f"Relationship surge: {self._entity_name(lo)} ↔ {self._entity_name(hi)}",
                    description=f"Co-occurrence grew {growth*100:.0f}% (was {prev_count}, now {count}).",
                    metadata={"growth_rate": growth, "entity_b_id": hi, "count": count, "prev_count": prev_count},
                    related_entity_id=hi,
                )
                stats["signals"] += 1

        # Prune stale relationships
        prune_cutoff = now - timedelta(days=_PRUNE_AFTER_DAYS)
        pruned = EntityRelationship.objects.filter(
            last_seen_at__lt=prune_cutoff
        ).delete()[0]
        stats["pruned"] = pruned

        logger.info(
            "rebuild_relationships complete: %d→%d relationships, created=%d pruned=%d signals=%d",
            old_count, EntityRelationship.objects.count(),
            stats["created"], stats["pruned"], stats["signals"],
        )
        return stats

    def incremental_update(self, article: Article) -> None:
        """Fast per-article update — call from ingestion pipeline.

        Only updates pairs involving entities from *this* article.
        Skips blocked entities and resolves aliases.
        """
        try:
            ae_list = list(
                ArticleEntity.objects
                .filter(article=article)
                .select_related("entity")
            )
            if len(ae_list) < 2:
                return

            blocked = self._build_blocked_entity_ids()
            alias_map = self._build_alias_map()
            total_sources = max(Source.objects.filter(is_active=True).count(), 1)

            # Resolve and filter entity IDs
            resolved_ids = set()
            for ae in ae_list:
                eid = ae.entity_id
                if eid in blocked:
                    continue
                eid = alias_map.get(eid, eid)
                resolved_ids.add(eid)

            entity_ids = sorted(resolved_ids)
            if len(entity_ids) < 2:
                return

            now = timezone.now()

            for a_id, b_id in combinations(entity_ids, 2):
                lo, hi = (a_id, b_id) if a_id < b_id else (b_id, a_id)

                with transaction.atomic():
                    rel, created = EntityRelationship.objects.get_or_create(
                        entity_a_id=lo,
                        entity_b_id=hi,
                        defaults={
                            "co_occurrence_count": 1,
                            "last_seen_at": article.published_at or now,
                            "first_seen_at": article.published_at or now,
                            "supporting_article_ids": [article.id],
                            "supporting_source_ids":
                                [article.source_id] if article.source_id else [],
                        },
                    )

                    if not created:
                        art_ids = list(rel.supporting_article_ids or [])
                        if article.id not in art_ids:
                            art_ids.append(article.id)
                        src_ids = list(rel.supporting_source_ids or [])
                        if article.source_id and article.source_id not in src_ids:
                            src_ids.append(article.source_id)

                        rel.co_occurrence_count += 1
                        rel.supporting_article_ids = art_ids[-_MAX_EVIDENCE_ARTICLES:]
                        rel.supporting_source_ids = src_ids[:30]
                        if article.published_at and (
                            not rel.last_seen_at or article.published_at > rel.last_seen_at
                        ):
                            rel.last_seen_at = article.published_at

                        # Recompute scores
                        strength, confidence, recency, diversity = self._compute_scores(
                            count=rel.co_occurrence_count,
                            last_seen=rel.last_seen_at or now,
                            distinct_sources=len(src_ids),
                            total_sources=total_sources,
                            now=now,
                        )
                        rel.strength_score = Decimal(str(round(strength, 4)))
                        rel.confidence = Decimal(str(round(confidence, 4)))
                        rel.recency_score = Decimal(str(round(recency, 4)))
                        rel.source_diversity_score = Decimal(str(round(diversity, 4)))
                        rel.save()

        except Exception:
            logger.debug(
                "EntityRelationshipService.incremental_update failed for article %s",
                article.id,
                exc_info=True,
            )

    def get_entity_graph(
        self,
        *,
        entity_type: Optional[str] = None,
        relationship_type: Optional[str] = None,
        min_strength: float = _MIN_STRENGTH_GRAPH,
        since_days: Optional[int] = None,
        limit_nodes: int = 100,
    ) -> dict:
        """Return a graph payload (nodes + edges) for the frontend visualiser.

        Filters to meaningful relationships only (P0: min co_occurrence, min strength).
        """
        from sources.models import EntityInfluenceScore

        # P0: Only include relationships with sufficient evidence
        qs = EntityRelationship.objects.filter(
            strength_score__gte=Decimal(str(min_strength)),
            co_occurrence_count__gte=_MIN_CO_OCCURRENCE,
        ).select_related("entity_a", "entity_b")

        if relationship_type:
            qs = qs.filter(relationship_type=relationship_type)
        if since_days:
            cutoff = timezone.now() - timedelta(days=since_days)
            qs = qs.filter(last_seen_at__gte=cutoff)
        if entity_type:
            qs = qs.filter(
                Q(entity_a__entity_type=entity_type)
                | Q(entity_b__entity_type=entity_type)
            )

        # Limit edges to the most influential entities
        blocked = self._build_blocked_entity_ids()
        influence_qs = (
            EntityInfluenceScore.objects
            .exclude(entity_id__in=blocked)
        )
        if entity_type:
            influence_qs = influence_qs.filter(entity__entity_type=entity_type)
        top_entity_ids = set(
            influence_qs
            .order_by("influence_rank")
            .values_list("entity_id", flat=True)[:limit_nodes]
        )

        if top_entity_ids:
            qs = qs.filter(
                Q(entity_a_id__in=top_entity_ids)
                | Q(entity_b_id__in=top_entity_ids)
            )

        edges = list(qs.order_by("-strength_score")[:500])

        # Build node set from edges
        entity_ids = set()
        for e in edges:
            entity_ids.add(e.entity_a_id)
            entity_ids.add(e.entity_b_id)

        # Exclude blocked entities from nodes
        entity_ids -= blocked

        entities = {
            ent.id: ent
            for ent in Entity.objects.filter(id__in=entity_ids)
        }
        influence = {
            inf.entity_id: inf
            for inf in EntityInfluenceScore.objects.filter(entity_id__in=entity_ids)
        }

        nodes = []
        for eid, ent in entities.items():
            inf = influence.get(eid)
            nodes.append({
                "id":            eid,
                "label":         ent.canonical_name or ent.name,
                "type":          ent.entity_type,
                "country":       ent.country,
                "influence":     float(inf.influence_score) if inf else 0.0,
                "degree":        float(inf.degree_centrality) if inf else 0.0,
                "velocity":      float(inf.velocity_score) if inf else 0.0,
                "mentions_7d":   inf.mentions_last_7d if inf else 0,
                "growth_flag":   inf.growth_flag if inf else False,
            })

        edge_list = []
        for rel in edges:
            # Skip edges to blocked nodes
            if rel.entity_a_id not in entities or rel.entity_b_id not in entities:
                continue
            edge_list.append({
                "source":         rel.entity_a_id,
                "target":         rel.entity_b_id,
                "strength":       float(rel.strength_score),
                "confidence":     float(rel.confidence),
                "type":           rel.relationship_type,
                "co_occurrences": rel.co_occurrence_count,
                "last_seen_at":   rel.last_seen_at.isoformat() if rel.last_seen_at else None,
                "growth_rate":    float(rel.growth_rate),
            })

        return {"nodes": nodes, "edges": edge_list}

    # ═════════════════════════════════════════════════════════════════════════
    # Private helpers
    # ═════════════════════════════════════════════════════════════════════════

    def _build_blocked_entity_ids(self) -> set[int]:
        """Return set of entity IDs that should be excluded from graphs.

        Includes:
        - Entities whose names match the blocklist (news sources, garbage words)
        - Entities with very short names (< _MIN_ENTITY_NAME_LEN chars)
        """
        blocked = set()

        # Short names and blocklist matches
        for eid, name in Entity.objects.values_list("id", "name"):
            name_lower = name.strip().lower()
            if len(name_lower) < _MIN_ENTITY_NAME_LEN:
                blocked.add(eid)
            elif name_lower in _BLOCKED_ENTITY_NAMES:
                blocked.add(eid)

        return blocked

    def _build_alias_map(self) -> dict[int, int]:
        """Return a map of entity_id → canonical_entity_id for known duplicates.

        Uses _ENTITY_ALIASES to find Arabic entity IDs and map them to their
        English canonical counterparts.
        """
        alias_map: dict[int, int] = {}

        # For each Arabic variant, find its entity ID and the canonical entity ID
        for arabic_name, english_name in _ENTITY_ALIASES.items():
            arabic_ents = list(
                Entity.objects.filter(name__iexact=arabic_name).values_list("id", flat=True)
            )
            english_ents = list(
                Entity.objects.filter(name__iexact=english_name).values_list("id", flat=True)
            )

            if arabic_ents and english_ents:
                canonical_id = english_ents[0]
                for aid in arabic_ents:
                    if aid != canonical_id:
                        alias_map[aid] = canonical_id

        return alias_map

    def _compute_scores(
        self,
        *,
        count: int,
        last_seen,
        distinct_sources: int,
        total_sources: int,
        now,
    ) -> tuple[float, float, float, float]:
        """Return (strength, confidence, recency, source_diversity).

        v2 formula:
        - Co-occurrence weight: 40% (log-normalized, against realistic max)
        - Recency weight: 20% (exponential decay)
        - Source diversity weight: 25% (against actual unique source count)
        - Frequency stability weight: 15% (approaches 1 for frequent pairs)
        """
        # Raw co-occurrence: log-normalised against realistic max
        raw_co_occ = math.log1p(count) / math.log1p(_MAX_EXPECTED_CO_OCC)
        raw_co_occ = min(raw_co_occ, 1.0)

        # Recency: exponential decay from last_seen
        if last_seen:
            age_days = (now - last_seen).total_seconds() / 86400
        else:
            age_days = _HALF_LIFE_DAYS
        recency = math.exp(-age_days * math.log(2) / _HALF_LIFE_DAYS)

        # Source diversity: distinct sources / total unique sources in system
        diversity = min(distinct_sources / max(total_sources, 1), 1.0)

        # Frequency stability: approaches 1 for pairs with many co-occurrences
        stability = 1.0 - (1.0 / max(count, 1))

        # Combined strength (v2 weights)
        strength = (
            0.40 * raw_co_occ
            + 0.20 * recency
            + 0.25 * diversity
            + 0.15 * stability
        )

        # Confidence (v2): evidence count + diversity bonus
        base_conf = min(count / _MIN_FOR_FULL_CONF, 1.0)
        diversity_bonus = 0.15 * diversity
        confidence = min(1.0, base_conf + diversity_bonus)

        return strength, confidence, recency, diversity

    def _classify_type(self, text: str) -> str:
        """Improved keyword-based relationship type classification.

        v2 changes:
        - Requires minimum 2 keyword matches to assign a type
        - Uses more specific multi-word phrases to reduce false positives
        - Defaults to "unknown" when evidence is weak
        """
        if not text:
            return EntityRelationship.RelationshipType.UNKNOWN

        text_lower = text.lower()
        scores: dict[str, int] = {}

        for rel_type, keywords in _TYPE_KEYWORDS.items():
            scores[rel_type] = sum(1 for kw in keywords if kw in text_lower)

        best = max(scores, key=lambda k: scores[k])

        # P2: Require minimum 2 keyword hits to assign a non-unknown type
        if scores[best] < 2:
            return EntityRelationship.RelationshipType.UNKNOWN

        # If top two types are very close (within 1), default to unknown
        sorted_scores = sorted(scores.values(), reverse=True)
        if len(sorted_scores) >= 2 and sorted_scores[0] - sorted_scores[1] <= 1 and sorted_scores[0] <= 3:
            return EntityRelationship.RelationshipType.UNKNOWN

        return best

    def _get_sample_text(self, article_ids: list[int]) -> str:
        """Fetch title + snippet text from a list of article IDs."""
        rows = Article.objects.filter(id__in=article_ids).values("title", "content")
        return " ".join(
            f"{r['title']} {r.get('content', '')}" for r in rows
        )

    def _entity_name(self, entity_id: int) -> str:
        try:
            ent = Entity.objects.filter(pk=entity_id).values_list(
                "canonical_name", "name"
            ).first()
            if ent:
                return ent[0] or ent[1]
            return str(entity_id)
        except Exception:
            return str(entity_id)

    def _emit_signal(
        self,
        *,
        entity_id: int,
        signal_type: str,
        severity: str,
        title: str,
        description: str,
        metadata: dict,
        related_entity_id: Optional[int] = None,
    ) -> None:
        """Create an EntitySignal unless a recent identical one already exists."""
        recent_cutoff = timezone.now() - timedelta(hours=24)

        already_exists = EntitySignal.objects.filter(
            entity_id=entity_id,
            signal_type=signal_type,
            related_entity_id=related_entity_id,
            created_at__gte=recent_cutoff,
        ).exists()

        if not already_exists:
            EntitySignal.objects.create(
                entity_id=entity_id,
                signal_type=signal_type,
                severity=severity,
                title=title,
                description=description,
                metadata=metadata,
                related_entity_id=related_entity_id,
                expires_at=timezone.now() + timedelta(days=7),
            )
