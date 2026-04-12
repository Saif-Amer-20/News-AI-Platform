"""Entity Resolution Service — merge equivalent entities into canonical forms.

Responsibilities
─────────────────
1. Maintain a table of known aliases → canonical name mappings.
2. At extraction time, resolve new entity names against the canonical registry.
3. Periodically merge duplicate Entity rows that map to the same canonical form.
4. Keep Entity.canonical_name and Entity.aliases up to date.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Q

from sources.models import ArticleEntity, Entity

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Static alias registry — covers the most common geo-political synonyms.
# Format: canonical_name → {alias_1, alias_2, …}
# All comparisons are done on lowered+stripped text.
# ──────────────────────────────────────────────────────────────────────────────

_ALIAS_REGISTRY: dict[str, set[str]] = {
    # Countries
    "united states": {"usa", "us", "u.s.", "u.s.a.", "america", "united states of america"},
    "united kingdom": {"uk", "u.k.", "britain", "great britain"},
    "russia": {"russian federation", "ussr", "soviet union"},
    "china": {"people's republic of china", "prc", "mainland china"},
    "south korea": {"republic of korea", "rok"},
    "north korea": {"dprk", "democratic people's republic of korea"},
    "iran": {"islamic republic of iran"},
    "syria": {"syrian arab republic"},
    "türkiye": {"turkey", "turkiye"},
    "uae": {"united arab emirates"},
    "eu": {"european union"},
    # Organisations
    "united nations": {"un", "u.n."},
    "nato": {"north atlantic treaty organization", "north atlantic treaty organisation"},
    "world health organization": {"who", "w.h.o."},
    "international monetary fund": {"imf", "i.m.f."},
    "european central bank": {"ecb"},
    "federal bureau of investigation": {"fbi", "f.b.i."},
    "central intelligence agency": {"cia", "c.i.a."},
    "hamas": {"islamic resistance movement"},
    "hezbollah": {"hizbollah", "hizballah"},
    "isis": {"isil", "islamic state", "daesh"},
    "taliban": {"islamic emirate of afghanistan"},
}

# Build a fast reverse-lookup: lowered alias → canonical name
_REVERSE_ALIAS: dict[str, str] = {}
for _canonical, _aliases in _ALIAS_REGISTRY.items():
    _canonical_low = _canonical.lower()
    _REVERSE_ALIAS[_canonical_low] = _canonical_low  # self-mapping
    for _alias in _aliases:
        _REVERSE_ALIAS[_alias.lower()] = _canonical_low


class EntityResolutionService:
    """Resolve, normalise, and merge entities to canonical forms."""

    # ── Public API ────────────────────────────────────────────────

    def resolve_name(self, raw_name: str) -> str:
        """Return the canonical form for *raw_name*, or the normalised name itself."""
        norm = self._normalize(raw_name)
        return _REVERSE_ALIAS.get(norm, norm)

    def resolve_entity(self, entity: Entity) -> Entity:
        """
        Fill in ``canonical_name`` and ``aliases`` on a single Entity if it
        matches the alias registry.  Returns the (possibly updated) entity.
        """
        canonical = self.resolve_name(entity.name)
        changed = False

        if canonical != entity.canonical_name:
            entity.canonical_name = canonical
            changed = True

        # Populate aliases list from registry if available
        registry_aliases = _ALIAS_REGISTRY.get(canonical, set())
        existing_aliases = set(a.lower() for a in entity.aliases) if entity.aliases else set()
        new_aliases = registry_aliases - existing_aliases - {canonical}
        if new_aliases:
            entity.aliases = list(set(entity.aliases or []) | new_aliases)
            changed = True

        if changed:
            entity.save(update_fields=["canonical_name", "aliases", "updated_at"])

        return entity

    def merge_duplicates(self, *, batch_size: int = 500) -> int:
        """
        Find Entity rows that share the same (canonical_name, entity_type)
        and merge them into a single row.  Re-links all ArticleEntity rows.

        Returns the number of duplicate Entity rows deleted.
        """
        # First pass: ensure every entity has a canonical_name
        entities_without_canonical = Entity.objects.filter(
            Q(canonical_name="") | Q(canonical_name__isnull=True)
        )[:batch_size]

        for entity in entities_without_canonical:
            self.resolve_entity(entity)

        # Second pass: group by (canonical_name, entity_type) with count > 1
        dupes = (
            Entity.objects.values("canonical_name", "entity_type")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .order_by("-cnt")[:batch_size]
        )

        merged_count = 0
        for group in dupes:
            canonical = group["canonical_name"]
            etype = group["entity_type"]
            if not canonical:
                continue
            merged_count += self._merge_group(canonical, etype)

        if merged_count:
            logger.info("Entity resolution: merged %d duplicate entities", merged_count)
        return merged_count

    # ── Internals ─────────────────────────────────────────────────

    def _merge_group(self, canonical_name: str, entity_type: str) -> int:
        """Merge all entities with the same canonical_name+entity_type into one."""
        entities = list(
            Entity.objects.filter(
                canonical_name=canonical_name,
                entity_type=entity_type,
            ).order_by("created_at")
        )
        if len(entities) < 2:
            return 0

        primary = entities[0]
        duplicates = entities[1:]

        # Gather aliases from all duplicates
        all_aliases: set[str] = set(primary.aliases or [])
        for dup in duplicates:
            all_aliases.add(dup.name.lower())
            all_aliases.add(dup.normalized_name)
            if dup.aliases:
                all_aliases.update(a.lower() for a in dup.aliases)
        all_aliases.discard(primary.canonical_name)
        all_aliases.discard(primary.normalized_name)

        with transaction.atomic():
            # Update primary's alias list
            primary.aliases = sorted(all_aliases)
            primary.save(update_fields=["aliases", "updated_at"])

            # Re-link ArticleEntity rows
            dup_ids = [d.id for d in duplicates]
            for ae in ArticleEntity.objects.filter(entity_id__in=dup_ids):
                # If the primary already has a link to this article, aggregate
                existing = ArticleEntity.objects.filter(
                    article_id=ae.article_id, entity_id=primary.id
                ).first()
                if existing:
                    existing.mention_count += ae.mention_count
                    if float(ae.relevance_score) > float(existing.relevance_score):
                        existing.relevance_score = ae.relevance_score
                    existing.save(update_fields=["mention_count", "relevance_score", "updated_at"])
                    ae.delete()
                else:
                    ae.entity = primary
                    ae.save(update_fields=["entity", "updated_at"])

            # Delete duplicate entities
            Entity.objects.filter(id__in=dup_ids).delete()

        return len(duplicates)

    @staticmethod
    def _normalize(name: str) -> str:
        norm = unicodedata.normalize("NFKC", name)
        norm = re.sub(r"\s+", " ", norm).strip().lower()
        return norm
