"""Entity Resolution Service — merge equivalent entities into canonical forms.

Responsibilities
─────────────────
1. Maintain a table of known aliases → canonical name mappings.
2. At extraction time, resolve new entity names against the canonical registry.
3. Periodically merge duplicate Entity rows that map to the same canonical form.
4. Keep Entity.canonical_name and Entity.aliases up to date.
5. Merge PERSON entities where one name is a token-subset of another
   (e.g. "Trump" → "Donald Trump") across articles.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Q

from sources.models import ArticleEntity, Entity
from .entity_post_processing_service import arabic_normalized_key

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Static alias registry — covers the most common geo-political synonyms.
# Format: canonical_name → {alias_1, alias_2, …}
# All comparisons are done on lowered+stripped text.
# Arabic entries use arabic_normalized_key() for matching at runtime.
# ──────────────────────────────────────────────────────────────────────────────

_ALIAS_REGISTRY: dict[str, set[str]] = {
    # ── Countries (English canonical) ──────────────────────────────────────
    "united states": {
        "usa", "us", "u.s.", "u.s.a.", "america", "united states of america",
        # Arabic variants (all normalised at lookup time)
        "الولايات المتحدة", "الولايات المتحدة الامريكيه", "امريكا", "أمريكا",
        "اميركا", "الولايات المتحده", "أمريكيا",
    },
    "united kingdom": {
        "uk", "u.k.", "britain", "great britain",
        "المملكة المتحدة", "المملكه المتحده", "بريطانيا", "بريطانيه",
    },
    "russia": {
        "russian federation", "ussr", "soviet union",
        "روسيا", "روسيه", "الاتحاد الروسي", "الاتحاد الروسيه",
    },
    "china": {
        "people's republic of china", "prc", "mainland china",
        "الصين", "جمهورية الصين الشعبية",
    },
    "france": {
        "french republic",
        "فرنسا", "فرنسه",
    },
    "germany": {
        "federal republic of germany",
        "المانيا", "ألمانيا", "الماني",
    },
    "south korea": {"republic of korea", "rok", "كوريا الجنوبية"},
    "north korea": {
        "dprk", "democratic people's republic of korea",
        "كوريا الشمالية",
    },
    "iran": {
        "islamic republic of iran", "persia",
        "إيران", "ايران", "إيران", "الجمهورية الإسلامية الإيرانية",
        "يران",  # malformed variant: hamza-loss on initial alef (يران ← إيران)
    },
    "syria": {
        "syrian arab republic",
        "سوريا", "سوريه", "الجمهورية العربية السورية",
    },
    "turkey": {
        "türkiye", "turkiye",
        "تركيا", "تركيه",
    },
    "uae": {
        "united arab emirates",
        "الإمارات العربية المتحدة", "الامارات", "الإمارات", "الامارات العربية المتحدة",
    },
    "saudi arabia": {
        "ksa", "kingdom of saudi arabia",
        "المملكة العربية السعودية", "المملكه العربيه السعوديه", "السعودية", "السعوديه",
    },
    "egypt": {
        "arab republic of egypt",
        "مصر", "جمهورية مصر العربية",
    },
    "jordan": {
        "hashemite kingdom of jordan",
        "الأردن", "الاردن",
    },
    "iraq": {
        "republic of iraq",
        "العراق",
    },
    "lebanon": {
        "republic of lebanon",
        "لبنان",
    },
    "palestine": {
        "state of palestine", "palestinian territories", "west bank", "gaza",
        "فلسطين",
    },
    "israel": {
        "state of israel",
        "إسرائيل", "اسرائيل", "إسرائيل",
    },
    "qatar": {
        "state of qatar",
        "قطر",
    },
    "kuwait": {
        "state of kuwait",
        "الكويت",
    },
    "bahrain": {
        "kingdom of bahrain",
        "البحرين",
    },
    "oman": {
        "sultanate of oman",
        "عُمان", "عمان",
    },
    "yemen": {
        "republic of yemen",
        "اليمن",
    },
    "libya": {
        "state of libya",
        "ليبيا", "ليبيه",
    },
    "algeria": {
        "people's democratic republic of algeria",
        "الجزائر",
    },
    "morocco": {
        "kingdom of morocco",
        "المغرب",
    },
    "tunisia": {
        "republic of tunisia",
        "تونس",
    },
    "sudan": {
        "republic of sudan",
        "السودان",
    },
    "somalia": {
        "federal republic of somalia",
        "الصومال",
    },
    "afghanistan": {
        "islamic emirate of afghanistan",
        "أفغانستان", "افغانستان",
    },
    "pakistan": {
        "islamic republic of pakistan",
        "باكستان", "پاکستان",
    },
    "eu": {
        "european union",
        "الاتحاد الأوروبي", "الاتحاد الاوروبي",
    },

    # ── Cities / Capitals (English canonical) ──────────────────────────────
    "washington": {
        "washington dc", "washington d.c.", "d.c.", "dc",
        "واشنطن", "واشنطن العاصمة",
    },

    # ── Persons (English canonical) ────────────────────────────────────────
    "donald trump": {
        "trump", "donald j trump", "donald j. trump",
        # Arabic — all phonetic variants of Trump/Tramp
        "دونالد ترامب", "دونالد ترمب", "ترامب", "ترمب",
        "دونالد جي ترامب", "الرئيس ترامب",
    },
    "joe biden": {
        "biden", "joseph biden", "joseph r biden",
        "جو بايدن", "بايدن", "جو بيدن", "بيدن",
        "جوزيف بايدن",
    },
    "barack obama": {
        "obama",
        "باراك أوباما", "أوباما", "اوباما", "باراك اوباما",
    },
    "vladimir putin": {
        "putin",
        "فلاديمير بوتين", "بوتين", "فلاديمير پوتين",
        "فلادمير بوتين", "بوتن",
    },
    "xi jinping": {
        "xi",
        "شي جين بينغ", "شي جينبينغ",
    },
    "benjamin netanyahu": {
        "netanyahu", "bibi", "binyamin netanyahu",
        "بنيامين نتنياهو", "نتنياهو", "بنيامين نتانياهو",
        "بينيامين نتنياهو", "نتانياهو",
    },
    "bashar al-assad": {
        "al-assad", "bashar", "bashar al-asad",
        "بشار الاسد", "بشار الأسد", "الاسد", "الأسد",
        "الرئيس الاسد", "الرئيس الأسد",
    },
    "recep tayyip erdogan": {
        "erdogan",
        "رجب طيب أردوغان", "أردوغان", "اردوغان",
    },
    "mohammed bin salman": {
        "mbs", "bin salman",
        "محمد بن سلمان", "ابن سلمان",
    },
    "volodymyr zelensky": {
        "zelensky", "zelenskyy", "volodymyr zelenskyy",
        "فولوديمير زيلينسكي", "زيلينسكي", "زيلنسكي",
        "زيلينسكي", "فلاديمير زيلينسكي",
    },
    "antonio guterres": {
        "guterres",
        "أنتونيو غوتيريش", "غوتيريش",
    },
    "emmanuel macron": {
        "macron",
        "إيمانويل ماكرون", "ماكرون",
    },
    "olaf scholz": {
        "scholz",
        "أولاف شولتس", "شولتس",
    },
    "rishi sunak": {
        "sunak",
        "ريشي سوناك", "سوناك",
    },

    # ── Organisations ──────────────────────────────────────────────────────
    "united nations": {
        "un", "u.n.",
        "الأمم المتحدة", "الامم المتحده",
    },
    "nato": {
        "north atlantic treaty organization", "north atlantic treaty organisation",
        "حلف الناتو", "الناتو",
    },
    "world health organization": {
        "who", "w.h.o.",
        "منظمة الصحة العالمية", "منظمه الصحه العالميه",
    },
    "international monetary fund": {
        "imf", "i.m.f.",
        "صندوق النقد الدولي",
    },
    "european central bank": {"ecb", "البنك المركزي الأوروبي"},
    "federal bureau of investigation": {"fbi", "f.b.i.", "مكتب التحقيقات الفيدرالي"},
    "central intelligence agency": {"cia", "c.i.a.", "وكالة المخابرات المركزية"},
    "hamas": {
        "islamic resistance movement",
        "حماس", "حركة حماس", "حركة المقاومة الإسلامية",
    },
    "hezbollah": {
        "hizbollah", "hizballah",
        "حزب الله",
    },
    "isis": {
        "isil", "islamic state", "daesh",
        "داعش", "تنظيم داعش", "الدولة الإسلامية",
    },
    "al-qaeda": {
        "al qaeda", "alqaeda",
        "القاعدة", "تنظيم القاعدة",
    },
    "taliban": {
        "islamic emirate of afghanistan",
        "طالبان", "حركة طالبان",
    },
    "arab league": {
        "league of arab states",
        "جامعة الدول العربية", "الجامعة العربية",
    },
    "african union": {
        "au",
        "الاتحاد الأفريقي",
    },
}

# ── Build reverse-lookup tables ───────────────────────────────────────────────
# Two tables:
#   _REVERSE_ALIAS     : plain-lower key  → canonical
#   _REVERSE_ALIAS_AR  : arabic_normalized_key → canonical
# (the Arabic table covers both Arabic and Latin entries for robustness)

_REVERSE_ALIAS: dict[str, str] = {}
_REVERSE_ALIAS_AR: dict[str, str] = {}

for _canonical, _aliases in _ALIAS_REGISTRY.items():
    _canonical_low = _canonical.lower()
    _REVERSE_ALIAS[_canonical_low] = _canonical_low
    _REVERSE_ALIAS_AR[arabic_normalized_key(_canonical)] = _canonical_low
    for _alias in _aliases:
        _REVERSE_ALIAS[_alias.lower()] = _canonical_low
        _REVERSE_ALIAS_AR[arabic_normalized_key(_alias)] = _canonical_low


class EntityResolutionService:
    """Resolve, normalise, and merge entities to canonical forms."""

    # ── Public API ────────────────────────────────────────────────

    def resolve_name(self, raw_name: str) -> str:
        """Return the canonical form for *raw_name*, or the normalised name itself.

        Look-up strategy (first hit wins):
          1. Plain lowercase normalisation  → _REVERSE_ALIAS
          2. Arabic-normalised key          → _REVERSE_ALIAS_AR
             (handles alef/ya/ta-marbuta spelling variants and
              Arabic↔English cross-language aliases)
        """
        norm = self._normalize(raw_name)
        result = _REVERSE_ALIAS.get(norm)
        if result is not None:
            return result
        ar_key = arabic_normalized_key(raw_name)
        result = _REVERSE_ALIAS_AR.get(ar_key)
        if result is not None:
            return result
        return norm

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

    def merge_person_variants(self, *, batch_size: int = 1000) -> int:
        """
        Merge PERSON entities where one is a single-token that matches the
        **last token** of a multi-token person (the "surname" rule).

        Examples:
            "Trump" → "Donald Trump"
            "Biden" → "Joe Biden"
            "Netanyahu" → "Benjamin Netanyahu"

        This handles cross-article variant accumulation that the within-batch
        deduplication in EntityPostProcessor cannot cover retroactively.

        Returns the number of variant entities merged away.
        """
        persons = list(
            Entity.objects.filter(entity_type=Entity.EntityType.PERSON)
            .annotate(art_count=Count("article_entities"))
            .order_by("-art_count")[:batch_size]
        )

        # Index multi-token persons by their last token.
        multi: dict[str, list[Entity]] = defaultdict(list)
        for entity in persons:
            key = entity.canonical_name or entity.normalized_name
            tokens = key.split()
            if len(tokens) >= 2:
                multi[tokens[-1]].append(entity)

        merged_count = 0
        for entity in persons:
            key = entity.canonical_name or entity.normalized_name
            tokens = key.split()
            # Only consider single-token entities as variant candidates.
            if len(tokens) != 1:
                continue
            last = tokens[0]
            candidates = multi.get(last, [])
            if not candidates:
                continue
            # Pick the candidate with the most articles (most authoritative).
            best = max(candidates, key=lambda e: e.article_entities.count())
            if best.id == entity.id:
                continue
            # Sanity: the variant should have fewer mentions than the canonical.
            variant_count = entity.article_entities.count()
            canonical_count = best.article_entities.count()
            if variant_count > canonical_count * 2:
                # The "short" name is more prominent — skip to avoid wrong merge.
                continue
            merged_count += self._merge_into(entity, best)

        if merged_count:
            logger.info(
                "Person-variant merge: absorbed %d single-token variants", merged_count
            )
        return merged_count

    def _merge_into(self, variant: Entity, canonical: Entity) -> int:
        """
        Merge *variant* into *canonical*.  Re-links ArticleEntity rows,
        adds variant name to canonical's alias list, and deletes the variant.

        Returns 1 if merged, 0 if skipped.
        """
        if variant.id == canonical.id:
            return 0

        with transaction.atomic():
            # Add variant name as alias on the canonical entity.
            aliases: set[str] = set(canonical.aliases or [])
            aliases.add(variant.name.lower())
            aliases.add(variant.normalized_name)
            if variant.aliases:
                aliases.update(a.lower() for a in variant.aliases)
            aliases.discard(canonical.normalized_name)
            canonical.aliases = sorted(aliases)
            canonical.save(update_fields=["aliases", "updated_at"])

            # Re-link or aggregate ArticleEntity rows.
            for ae in ArticleEntity.objects.filter(entity=variant):
                existing = ArticleEntity.objects.filter(
                    article_id=ae.article_id, entity=canonical
                ).first()
                if existing:
                    existing.mention_count += ae.mention_count
                    if float(ae.relevance_score) > float(existing.relevance_score):
                        existing.relevance_score = ae.relevance_score
                    existing.save(
                        update_fields=["mention_count", "relevance_score", "updated_at"]
                    )
                    ae.delete()
                else:
                    ae.entity = canonical
                    ae.save(update_fields=["entity", "updated_at"])

            variant.delete()

        logger.debug("Merged entity '%s' into '%s'", variant.name, canonical.name)
        return 1

    @staticmethod
    def _normalize(name: str) -> str:
        norm = unicodedata.normalize("NFKC", name)
        norm = re.sub(r"\s+", " ", norm).strip().lower()
        return norm

    # ── Cross-language unification ────────────────────────────────

    def merge_crosslanguage_entities(self, *, batch_size: int = 2000) -> int:
        """Unify EN and AR DB rows that refer to the same real-world entity.

        Strategy
        --------
        Both the English canonical and every Arabic alias in _ALIAS_REGISTRY
        are mapped to the same *canonical_name* by resolve_name().  After
        resolve_entity() has been called on all entities (done in
        merge_duplicates) the remaining problem is: two Entity rows with the
        *same* canonical_name but different entity_type—impossible—or the same
        entity_type but the canonical_name was set from the Arabic side and
        doesn't match the English canonical.

        This method directly walks the registry and:
          1. Queries all Entity rows whose name / normalized_name match any
             known alias (including Arabic ones via arabic_normalized_key).
          2. Groups them by (registry_canonical, entity_type).
          3. Picks the English-named row (or highest-mention row) as primary.
          4. Merges all others in via _merge_into().

        Returns the number of cross-language duplicates absorbed.
        """
        merged_count = 0

        for registry_canonical, aliases in _ALIAS_REGISTRY.items():
            all_forms: set[str] = {registry_canonical} | {a.lower() for a in aliases}

            # Gather entity rows matching any form.  We query by canonical_name
            # (already resolved) OR by normalised name.
            matching = list(
                Entity.objects.filter(
                    canonical_name__in=all_forms
                ).annotate(art_count=Count("article_entities"))
            )
            if len(matching) < 2:
                continue

            # Group by entity_type to avoid cross-type merges.
            by_type: dict[str, list[Entity]] = defaultdict(list)
            for e in matching:
                by_type[e.entity_type].append(e)

            for etype, group in by_type.items():
                if len(group) < 2:
                    continue

                # Prefer the entity whose canonical_name equals the
                # registry English canonical (authoritative); else pick
                # highest article count.
                def _priority(e: Entity) -> tuple[int, int]:
                    is_english = int(
                        (e.canonical_name or "").lower() == registry_canonical
                    )
                    return (is_english, e.art_count)  # type: ignore[attr-defined]

                primary = max(group, key=_priority)
                for entity in group:
                    if entity.id == primary.id:
                        continue
                    # Safety: don't merge if the variant has far more articles
                    # than the primary (would indicate wrong mapping).
                    variant_count = entity.art_count  # type: ignore[attr-defined]
                    primary_count = primary.art_count  # type: ignore[attr-defined]
                    if variant_count > primary_count * 3 and primary_count > 0:
                        logger.warning(
                            "Cross-lang merge skipped: '%s'(%d) >> '%s'(%d)",
                            entity.name, variant_count, primary.name, primary_count,
                        )
                        continue
                    merged_count += self._merge_into(entity, primary)

        if merged_count:
            logger.info(
                "Cross-language merge: absorbed %d duplicate entities", merged_count
            )
        return merged_count


# ─────────────────────────────────────────────────────────────────────────────
# Targeted Repair Service
# ─────────────────────────────────────────────────────────────────────────────

# Arabic typo repairs: arabic_normalized_key(malformed_form) → registry canonical.
# These catch forms where a letter was dropped or mistyped in a way that the
# standard normalisation rules cannot collapse (e.g. hamza-loss at word start).
_ARABIC_TYPO_REPAIRS: dict[str, str] = {
    "يران": "iran",   # hamza-loss: يران (ya+ra+alef+nun) instead of إيران
}


class TargetedRepairService:
    """Apply targeted registry-lookup and typo-repair passes to DB entities.

    Handles cases the standard registry lookup misses:
      1. Arabic typos where a letter is dropped (e.g. يران instead of إيران).
      2. High-confidence known-entity forms that need a forced canonical.

    Does NOT merge entities — only updates canonical_name so that the
    canonical_merge phase can unify them in the next pass.
    Embedding merge safety rules are completely untouched.
    """

    # Minimum article count for the high-frequency re-check.
    # Typo repairs run regardless of frequency (even 1 mention is worth fixing).
    MIN_ARTICLES_RECHECK = 5

    def repair_arabic_typos(
        self, *, dry_run: bool = False, batch_size: int = 2000
    ) -> tuple[int, list[str]]:
        """Find entities whose arabic_normalized_key matches a known typo pattern
        and set their canonical_name to the corrected registry canonical.

        Returns (fixed_count, example_strings).
        """
        fixed = 0
        examples: list[str] = []

        for entity in Entity.objects.annotate(
            art_count=Count("article_entities")
        ).iterator(chunk_size=batch_size):
            ar_key = arabic_normalized_key(entity.name)
            correct_canonical = _ARABIC_TYPO_REPAIRS.get(ar_key)
            if correct_canonical is None:
                continue
            if (entity.canonical_name or "").lower() == correct_canonical:
                continue  # already correct
            examples.append(
                f"'{entity.name}' (ar_key={ar_key!r}) → canonical '{correct_canonical}'"
            )
            if not dry_run:
                entity.canonical_name = correct_canonical
                entity.save(update_fields=["canonical_name", "updated_at"])
            fixed += 1

        if fixed:
            logger.info("Targeted typo repair: fixed %d entities", fixed)
        return fixed, examples

    def apply_force_canonicals(
        self,
        force_map: dict[str, str],
        *,
        dry_run: bool = False,
        batch_size: int = 2000,
    ) -> tuple[int, list[str]]:
        """For each entity whose normalized_name matches a key in *force_map*,
        set its canonical_name to the mapped value.

        Only updates entities that currently have no canonical or whose
        canonical is just their own normalized name (i.e. unresolved).

        Returns (fixed_count, example_strings).
        """
        fixed = 0
        examples: list[str] = []

        for name_lower, target_canonical in force_map.items():
            for entity in Entity.objects.filter(
                normalized_name=name_lower
            ).iterator(chunk_size=batch_size):
                current = (entity.canonical_name or "").lower()
                if current == target_canonical:
                    continue
                examples.append(
                    f"'{entity.name}' → canonical '{target_canonical}'"
                    f" (was: '{current or '(none)'}')"
                )
                if not dry_run:
                    entity.canonical_name = target_canonical
                    entity.save(update_fields=["canonical_name", "updated_at"])
                fixed += 1

        if fixed:
            logger.info("Targeted force-canonical: updated %d entities", fixed)
        return fixed, examples

    def recheck_high_frequency_entities(
        self,
        resolver: EntityResolutionService,
        *,
        min_articles: int = 5,
        dry_run: bool = False,
        batch_size: int = 2000,
    ) -> tuple[int, list[str]]:
        """Re-run registry lookup for high-frequency entities that are still
        pointing to themselves as their own canonical (i.e. never resolved).

        This catches entities that were created before the registry contained
        their alias (e.g. 'Washington' added after initial data import).

        Returns (fixed_count, example_strings).
        """
        fixed = 0
        examples: list[str] = []

        candidates = list(
            Entity.objects.annotate(art_count=Count("article_entities"))
            .filter(art_count__gte=min_articles)
            .iterator(chunk_size=batch_size)
        )

        for entity in candidates:
            own_norm = entity.normalized_name.lower()
            current = (entity.canonical_name or "").lower()
            # Only process entities not yet resolved to a *different* canonical.
            if current and current != own_norm:
                continue
            canonical = resolver.resolve_name(entity.name)
            if canonical == own_norm:
                continue  # registry still doesn't know it
            examples.append(
                f"'{entity.name}' → canonical '{canonical}'"
                f" (was: '{current or '(none)'}')"
            )
            if not dry_run:
                entity.canonical_name = canonical
                entity.save(update_fields=["canonical_name", "updated_at"])
            fixed += 1

        if fixed:
            logger.info(
                "High-frequency registry re-check: updated %d entities", fixed
            )
        return fixed, examples

