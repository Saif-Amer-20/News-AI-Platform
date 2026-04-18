"""Management command: consolidate_entities

Full DB-level entity consolidation pass.  Runs in phases:

  Phase 1  reclassify       – Fix mis-typed entities (White House → org, etc.)
  Phase 1b targeted         – Arabic typo repair (يران→iran), forced canonicals
                              for title-form variants (President Trump→trump),
                              high-frequency registry re-check (≥5 articles)
  Phase 2  assign_canonical – Fill canonical_name via alias registry +
                              title-strip logic for all entities
  Phase 3  arabic_variants  – Merge Arabic spelling variants (alef/ya/ta-marbuta)
                              that are NOT in the alias registry
  Phase 4  canonical_merge  – Merge all rows sharing (canonical_name, entity_type)
                              into one authoritative row (English-first primary)
  Phase 5  embedding        – AI-assisted semantic merge using multilingual embeddings
                              (paraphrase-multilingual-MiniLM-L12-v2)
  Phase 6  crosslang        – merge_crosslanguage_entities (safety net)
  Phase 7  surname          – merge_person_variants (Trump → Donald Trump)
  Phase 8  noise_strip      – Strip fragment prefixes, delete zero-article noise
  Phase 9  final_dedup      – Last merge_duplicates pass

Usage
-----
    python manage.py consolidate_entities
    python manage.py consolidate_entities --dry-run
    python manage.py consolidate_entities --phases reclassify assign_canonical canonical_merge
    python manage.py consolidate_entities --phases embedding
    python manage.py consolidate_entities --embedding-threshold 0.88
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import NamedTuple

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from sources.models import ArticleEntity, Entity
from services.orchestration.entity_post_processing_service import (
    EntityPostProcessor,
    arabic_normalized_key,
)
from services.orchestration.entity_resolution_service import (
    EntityResolutionService,
    TargetedRepairService,
    _ARABIC_TYPO_REPAIRS,
)
from services.orchestration.embedding_canonicalization_service import (
    EmbeddingCanonicalizationService,
)

# ─────────────────────────────────────────────────────────────────────────────
# Reclassification rules  name_lower → correct EntityType
# These correct systematic misclassifications produced by the NER model.
# ─────────────────────────────────────────────────────────────────────────────
_RECLASSIFY: dict[str, str] = {
    # ── Mis-classified as PERSON ──────────────────────────────────────────
    "white house": Entity.EntityType.ORGANIZATION,
    "the white house": Entity.EntityType.ORGANIZATION,
    "congress": Entity.EntityType.ORGANIZATION,
    "the congress": Entity.EntityType.ORGANIZATION,
    "senate": Entity.EntityType.ORGANIZATION,
    "house of representatives": Entity.EntityType.ORGANIZATION,
    "supreme court": Entity.EntityType.ORGANIZATION,
    "pentagon": Entity.EntityType.ORGANIZATION,
    "the pentagon": Entity.EntityType.ORGANIZATION,
    "kremlin": Entity.EntityType.ORGANIZATION,
    "the kremlin": Entity.EntityType.ORGANIZATION,
    "truth social": Entity.EntityType.ORGANIZATION,
    "un security council": Entity.EntityType.ORGANIZATION,
    "security council": Entity.EntityType.ORGANIZATION,
    "european parliament": Entity.EntityType.ORGANIZATION,
    "court of justice": Entity.EntityType.ORGANIZATION,
    "international court of justice": Entity.EntityType.ORGANIZATION,
    "international criminal court": Entity.EntityType.ORGANIZATION,
    # Arabic
    "البيت الابيض": Entity.EntityType.ORGANIZATION,
    "البيت الأبيض": Entity.EntityType.ORGANIZATION,
    "مجلس الامن": Entity.EntityType.ORGANIZATION,
    "مجلس الأمن": Entity.EntityType.ORGANIZATION,
    # ── Mis-classified as PERSON (should be LOCATION) ────────────────────
    "middle east": Entity.EntityType.LOCATION,
    "the middle east": Entity.EntityType.LOCATION,
    "strait of hormuz": Entity.EntityType.LOCATION,
    "red sea": Entity.EntityType.LOCATION,
    "black sea": Entity.EntityType.LOCATION,
    "persian gulf": Entity.EntityType.LOCATION,
    "arabian sea": Entity.EntityType.LOCATION,
    "mediterranean": Entity.EntityType.LOCATION,
    "mediterranean sea": Entity.EntityType.LOCATION,
    "dead sea": Entity.EntityType.LOCATION,
    "jordan river": Entity.EntityType.LOCATION,
    "nile": Entity.EntityType.LOCATION,
    "euphrates": Entity.EntityType.LOCATION,
    "tigris": Entity.EntityType.LOCATION,
    "gaza strip": Entity.EntityType.LOCATION,
    "west bank": Entity.EntityType.LOCATION,
    "golan heights": Entity.EntityType.LOCATION,
    "sinai": Entity.EntityType.LOCATION,
    "sinai peninsula": Entity.EntityType.LOCATION,
    "horn of africa": Entity.EntityType.LOCATION,
    # Arabic locations
    "الشرق الاوسط": Entity.EntityType.LOCATION,
    "الشرق الأوسط": Entity.EntityType.LOCATION,
    "قطاع غزه": Entity.EntityType.LOCATION,
    "قطاع غزة": Entity.EntityType.LOCATION,
    # ── Mis-classified (should stay PERSON) ──────────────────────────────
    "the pope": Entity.EntityType.PERSON,
    "pope leo": Entity.EntityType.PERSON,
    "pope francis": Entity.EntityType.PERSON,
    "pope": Entity.EntityType.PERSON,
    # ── Washington (city) — often mis-tagged as PERSON or ORGANIZATION ────
    "washington": Entity.EntityType.LOCATION,
    "washington dc": Entity.EntityType.LOCATION,
    "washington d.c.": Entity.EntityType.LOCATION,
    "واشنطن": Entity.EntityType.LOCATION,
    "واشنطن العاصمة": Entity.EntityType.LOCATION,
    # ── Person title variants — keep as PERSON (canonical = donald trump) ─
    "president donald trump": Entity.EntityType.PERSON,
    "president trump": Entity.EntityType.PERSON,
    "mr trump": Entity.EntityType.PERSON,
    "mr. trump": Entity.EntityType.PERSON,    # ── Explicit type fixes for high-frequency known entities ─────────────
    # NER sometimes tags country/person names with wrong type in Arabic articles
    "donald trump": Entity.EntityType.PERSON,
    "iran": Entity.EntityType.LOCATION,
    "إيران": Entity.EntityType.LOCATION,
    "ايران": Entity.EntityType.LOCATION,
    "يران": Entity.EntityType.LOCATION,}

# ─────────────────────────────────────────────────────────────────────────────
# Force-canonical map: normalized entity name → registry canonical_name.
# Used by the 'targeted' phase to assign canonical_name for forms that the
# standard registry lookup misses (e.g. title-prefixed forms stored in the DB).
# ─────────────────────────────────────────────────────────────────────────────
_FORCE_CANONICAL: dict[str, str] = {
    "president donald trump": "donald trump",
    "president trump":        "donald trump",
    "mr trump":               "donald trump",
    "mr. trump":              "donald trump",
    "washington dc":          "washington",
    "washington d.c.":        "washington",
    "واشنطن العاصمة":         "washington",
}

# Ordered list of all phases
_ALL_PHASES = [
    "reclassify",
    "targeted",
    "assign_canonical",
    "arabic_variants",
    "canonical_merge",
    "embedding",
    "crosslang",
    "surname",
    "noise_strip",
    "final_dedup",
]


class PhaseStats(NamedTuple):
    phase: str
    changed: int
    detail: str = ""


def _is_arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06FF" for c in text)


def _norm(text: str) -> str:
    """Plain lowercase + NFKC normalise."""
    return unicodedata.normalize("NFKC", text).strip().lower()


# ─────────────────────────────────────────────────────────────────────────────
# Command
# ─────────────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Full entity consolidation: reclassify, deduplicate, cross-language unification."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the DB.",
        )
        parser.add_argument(
            "--phases",
            nargs="+",
            choices=_ALL_PHASES,
            default=None,
            metavar="PHASE",
            help=f"Run only these phases (default: all). Choices: {', '.join(_ALL_PHASES)}",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=2000,
            help="Batch size for bulk operations (default: 2000).",
        )
        parser.add_argument(
            "--embedding-threshold",
            type=float,
            default=0.85,
            dest="embedding_threshold",
            help="Cosine similarity threshold for embedding-based merges (default: 0.85).",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        phases: list[str] = options["phases"] or _ALL_PHASES
        batch: int = options["batch"]
        embedding_threshold: float = options["embedding_threshold"]

        resolver = EntityResolutionService()
        processor = EntityPostProcessor()
        embedder = EmbeddingCanonicalizationService(threshold=embedding_threshold)

        before = Entity.objects.count()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'═' * 72}\n  Entity Consolidation Pass"
            f"{'  [DRY RUN]' if dry_run else ''}\n{'═' * 72}"
        ))
        self.stdout.write(f"  Entities before: {before:,}")
        self.stdout.write(f"  Phases: {', '.join(phases)}\n")

        results: list[PhaseStats] = []

        for phase in _ALL_PHASES:
            if phase not in phases:
                continue
            self.stdout.write(self.style.HTTP_INFO(f"\n── Phase: {phase} ──"))
            if phase == "embedding":
                stats = self._phase_embedding(resolver, embedder, dry_run, embedding_threshold)
            else:
                method = getattr(self, f"_phase_{phase}")
                stats = method(resolver, processor, dry_run, batch)
            results.append(stats)
            self.stdout.write(f"   changed: {stats.changed:,}  {stats.detail}")

        after = Entity.objects.count()
        removed = before - after
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'═' * 72}\n  SUMMARY\n{'═' * 72}"
        ))
        self.stdout.write(f"  Entities before  : {before:,}")
        self.stdout.write(f"  Entities after   : {after:,}")
        self.stdout.write(
            f"  Entities removed : {removed:,}"
            + ("  (dry-run — no actual writes)" if dry_run else "")
        )
        self.stdout.write("")
        for s in results:
            self.stdout.write(f"  {s.phase:<20} {s.changed:>6,}  {s.detail}")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1 — Reclassification
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_reclassify(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Fix entity types using the hard-coded rule table."""
        changed = 0
        merged = 0
        examples: list[str] = []

        for name_lower, correct_type in _RECLASSIFY.items():
            wrong_qs = Entity.objects.filter(normalized_name=name_lower).exclude(
                entity_type=correct_type
            )
            for entity in wrong_qs:
                examples.append(
                    f"{entity.name}({entity.entity_type}→{correct_type})"
                )
                # Check if a correct-type entity already exists (would violate unique)
                conflict = Entity.objects.filter(
                    normalized_name=entity.normalized_name,
                    entity_type=correct_type,
                ).first()
                if conflict:
                    # Merge the mis-classified entity into the correctly-typed one
                    if not dry_run:
                        resolver._merge_into(entity, conflict)
                    merged += 1
                else:
                    if not dry_run:
                        entity.entity_type = correct_type
                        entity.save(update_fields=["entity_type", "updated_at"])
                changed += 1

        detail = f"reclassified={changed - merged}, merged={merged}"
        if examples:
            detail += "  e.g. " + "; ".join(examples[:4])
        return PhaseStats("reclassify", changed, detail)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1b — Targeted typo repair + forced canonicals
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_targeted(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Three targeted sub-passes (all safe, non-destructive):

        1. Arabic typo repair — find entities whose arabic_normalized_key
           matches a known malformed pattern (e.g. يران → إيران) and set
           their canonical_name to the corrected registry canonical.
           Applied to ALL entities regardless of frequency.

        2. Force-canonical — find entities by exact normalized_name match
           against _FORCE_CANONICAL (e.g. 'president donald trump' →
           'donald trump') and update canonical_name.  Handles title-
           prefixed DB rows that were stored before title-stripping ran.

        3. High-frequency registry re-check — for entities with ≥5 articles
           that still resolve to themselves, retry resolve_name() in case
           their alias was added to the registry after initial ingestion
           (e.g. 'washington' added later).

        Embedding merge safety rules are untouched.
        canonical_merge (Phase 4) will unify the groups created here.
        """
        repairer = TargetedRepairService()
        total_fixed = 0
        all_examples: list[str] = []

        # Sub-pass 1: Arabic typo repairs
        n1, ex1 = repairer.repair_arabic_typos(dry_run=dry_run, batch_size=batch)
        total_fixed += n1
        all_examples.extend(ex1)

        # Sub-pass 2: Force canonicals for known title-form variants
        n2, ex2 = repairer.apply_force_canonicals(
            _FORCE_CANONICAL, dry_run=dry_run, batch_size=batch
        )
        total_fixed += n2
        all_examples.extend(ex2)

        # Sub-pass 3: High-frequency registry re-check (≥5 articles)
        n3, ex3 = repairer.recheck_high_frequency_entities(
            resolver,
            min_articles=5,
            dry_run=dry_run,
            batch_size=batch,
        )
        total_fixed += n3
        all_examples.extend(ex3)

        detail = (
            f"typo_repairs={n1}, force_canonical={n2}, hf_recheck={n3}"
        )
        if all_examples:
            detail += "  e.g. " + "; ".join(all_examples[:4])
        return PhaseStats("targeted", total_fixed, detail)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — Assign canonical_name (registry + title-strip)
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_assign_canonical(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Fill canonical_name for every entity using two strategies:
        1. Alias registry lookup (resolve_name).
        2. Title-strip → re-resolve the clean form.
        """
        registry_hits = 0
        title_strip_hits = 0
        to_update: list[tuple[int, str]] = []  # (pk, new_canonical)

        for entity in Entity.objects.iterator(chunk_size=1000):
            # Strategy 1: direct registry lookup
            canonical = resolver.resolve_name(entity.name)

            if canonical == _norm(entity.name):
                # Registry didn't help — try title-strip
                clean = processor.normalize_name(entity.name, entity.entity_type)
                if clean and _norm(clean) != _norm(entity.name):
                    # Title was stripped; re-resolve the cleaner form
                    canonical = resolver.resolve_name(clean)
                    if canonical != _norm(entity.name):
                        title_strip_hits += 1
                elif clean is None:
                    # normalize_name rejects this entirely — leave canonical as-is
                    canonical = entity.canonical_name or _norm(entity.name)

            current_canonical = entity.canonical_name or ""
            if canonical != current_canonical:
                to_update.append((entity.pk, canonical))
                if not _is_arabic(entity.name):
                    registry_hits += 1

        if not dry_run:
            # Bulk update in batches
            for i in range(0, len(to_update), batch):
                chunk = to_update[i : i + batch]
                with transaction.atomic():
                    for pk, canonical in chunk:
                        Entity.objects.filter(pk=pk).update(canonical_name=canonical)

        total = len(to_update)
        detail = f"registry={registry_hits}, title_strip={title_strip_hits}"
        return PhaseStats("assign_canonical", total, detail)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3 — Arabic spelling-variant merge
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_arabic_variants(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Merge Arabic entities that differ only in orthographic variants
        (alef forms, ya, ta marbuta) and are NOT already resolved by the
        alias registry.

        Grouping key: (arabic_normalized_key(name), entity_type)
        Primary: entity with most ArticleEntity links (prefer non-registry
                 canonical if tied).
        """
        # Load all entities that still point to themselves as canonical
        # (i.e. not yet resolved to a different canonical by the registry).
        arabic_entities = [
            e
            for e in Entity.objects.annotate(
                art_count=Count("article_entities")
            ).iterator(chunk_size=2000)
            if _is_arabic(e.name)
        ]

        groups: dict[tuple[str, str], list[Entity]] = defaultdict(list)
        for entity in arabic_entities:
            ar_key = arabic_normalized_key(entity.name)
            groups[(ar_key, entity.entity_type)].append(entity)

        merged = 0
        examples: list[str] = []

        for (ar_key, etype), group in groups.items():
            if len(group) < 2:
                continue
            primary = self._pick_primary(group)
            for entity in group:
                if entity.id == primary.id:
                    continue
                examples.append(f"{entity.name}→{primary.name}")
                if not dry_run:
                    resolver._merge_into(entity, primary)
                    Entity.objects.filter(pk=primary.pk).update(
                        merge_method=Entity.MergeMethod.RULE,
                        merge_confidence=1.00,
                    )
                merged += 1

        detail = ""
        if examples:
            detail = "e.g. " + "; ".join(examples[:4])
        return PhaseStats("arabic_variants", merged, detail)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 4 — Canonical group merge
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_canonical_merge(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Merge all Entity rows that share the same (canonical_name, entity_type)
        into a single authoritative row.

        Uses smart primary selection:
          1. Prefer entity whose normalized_name == canonical_name (exact English match).
          2. Prefer English over Arabic.
          3. Prefer most-mentioned.
        """
        merged = 0
        examples: list[str] = []

        # Iterate until stable (merges can reveal new duplicates)
        for _pass in range(10):
            dupes = list(
                Entity.objects.values("canonical_name", "entity_type")
                .annotate(cnt=Count("id"))
                .filter(cnt__gt=1, canonical_name__gt="")
                .order_by("-cnt")[:batch]
            )
            if not dupes:
                break

            pass_merged = 0
            for group_info in dupes:
                canonical = group_info["canonical_name"]
                etype = group_info["entity_type"]
                group = list(
                    Entity.objects.filter(
                        canonical_name=canonical, entity_type=etype
                    ).annotate(art_count=Count("article_entities"))
                )
                if len(group) < 2:
                    continue

                primary = self._pick_primary(group, preferred_name=canonical)
                for entity in group:
                    if entity.id == primary.id:
                        continue
                    examples.append(f"'{entity.name}'→'{primary.name}'")
                    if not dry_run:
                        resolver._merge_into(entity, primary)
                        # Record provenance on the surviving entity
                        Entity.objects.filter(pk=primary.pk).update(
                            merge_method=Entity.MergeMethod.RULE,
                            merge_confidence=1.00,
                        )
                    merged += 1
                    pass_merged += 1

            if pass_merged == 0:
                break

        detail = ""
        if examples:
            detail = "e.g. " + "; ".join(examples[:5])
        return PhaseStats("canonical_merge", merged, detail)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 5 — Embedding-based AI merge
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_embedding(
        self,
        resolver: EntityResolutionService,
        embedder: EmbeddingCanonicalizationService,
        dry_run: bool,
        threshold: float,
    ) -> PhaseStats:
        """Use multilingual sentence embeddings to merge semantically equivalent entities.

        Processes PERSON, LOCATION, and ORGANIZATION in turn.
        Reports per-type counts and example merges.
        """
        total = 0
        examples: list[str] = []

        for etype in [
            Entity.EntityType.PERSON,
            Entity.EntityType.LOCATION,
            Entity.EntityType.ORGANIZATION,
        ]:
            count, candidates = embedder.merge_with_embeddings(
                etype,
                resolver,
                threshold=threshold,
                dry_run=dry_run,
            )
            total += count
            for c in candidates:
                if not c.blocked and len(examples) < 5:
                    arrow = "→" if not dry_run else "~>"
                    examples.append(
                        f"[{etype}] '{c.variant_name}' {arrow} '{c.canonical_name}' "
                        f"({c.score:.3f})"
                    )

        detail = ""
        if examples:
            detail = ("(dry-run) " if dry_run else "") + "e.g. " + "; ".join(examples)
        return PhaseStats("embedding", total, detail)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 7 — Cross-language merge (safety net)
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_crosslang(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Run EntityResolutionService.merge_crosslanguage_entities().
        After Phase 4 this mostly handles edge cases not covered by the registry.
        """
        if dry_run:
            return PhaseStats("crosslang", 0, "(skipped in dry-run)")
        n = resolver.merge_crosslanguage_entities(batch_size=batch)
        return PhaseStats("crosslang", n, "")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 7 — Surname-rule person merge
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_surname(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Merge single-token person surnames into full-name equivalents.
        e.g. 'Trump' → 'Donald Trump', 'Netanyahu' → 'Benjamin Netanyahu'.
        """
        if dry_run:
            return PhaseStats("surname", 0, "(skipped in dry-run)")
        n = resolver.merge_person_variants(batch_size=batch)
        return PhaseStats("surname", n, "")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 8 — Noise strip
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_noise_strip(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Handle two categories of noise:

        A. Fragment-prefixed entities (e.g. "But Pope Leo", "Just War Theory"):
           Strip the prefix, look for a clean entity in the DB, and merge.
           If no clean target found, rename the entity to its clean form.

        B. Zero-article entities whose normalize_name() returns None (pure noise):
           Delete them — they have no article links and are orphaned DB rows.
        """
        merged = 0
        deleted = 0
        renamed = 0
        examples: list[str] = []

        for entity in Entity.objects.annotate(
            art_count=Count("article_entities")
        ).iterator(chunk_size=1000):
            clean = processor.normalize_name(entity.name, entity.entity_type)

            if clean is None:
                # Completely invalid name
                if entity.art_count == 0:  # type: ignore[attr-defined]
                    if not dry_run:
                        entity.delete()
                    deleted += 1
                # If it has articles: leave it (don't destroy data, just skip)
                continue

            clean_norm = _norm(clean)
            current_norm = _norm(entity.name)

            if clean_norm == current_norm:
                continue  # already clean

            # Entity has a dirty name — look for a clean target
            try:
                target = Entity.objects.get(
                    normalized_name=clean_norm,
                    entity_type=entity.entity_type,
                )
                if target.id != entity.id:
                    examples.append(f"'{entity.name}'→'{target.name}'")
                    if not dry_run:
                        resolver._merge_into(entity, target)
                    merged += 1
            except Entity.DoesNotExist:
                # Rename entity to its clean form
                examples.append(f"'{entity.name}'→renamed→'{clean}'")
                if not dry_run:
                    try:
                        with transaction.atomic():
                            entity.name = clean
                            entity.normalized_name = clean_norm
                            canonical = resolver.resolve_name(clean)
                            entity.canonical_name = canonical
                            entity.save(
                                update_fields=[
                                    "name",
                                    "normalized_name",
                                    "canonical_name",
                                    "updated_at",
                                ]
                            )
                    except Exception:
                        pass  # constraint violation — skip
                renamed += 1
            except Entity.MultipleObjectsReturned:
                target = (
                    Entity.objects.filter(
                        normalized_name=clean_norm,
                        entity_type=entity.entity_type,
                    )
                    .annotate(art_count=Count("article_entities"))
                    .order_by("-art_count")
                    .first()
                )
                if target and target.id != entity.id:
                    if not dry_run:
                        resolver._merge_into(entity, target)
                    merged += 1

        total = merged + deleted + renamed
        detail = f"merged={merged}, deleted={deleted}, renamed={renamed}"
        if examples:
            detail += "  e.g. " + "; ".join(examples[:4])
        return PhaseStats("noise_strip", total, detail)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 9 — Final deduplication
    # ─────────────────────────────────────────────────────────────────────────

    def _phase_final_dedup(
        self,
        resolver: EntityResolutionService,
        processor: EntityPostProcessor,
        dry_run: bool,
        batch: int,
    ) -> PhaseStats:
        """Run merge_duplicates one final time to catch anything missed."""
        if dry_run:
            return PhaseStats("final_dedup", 0, "(skipped in dry-run)")
        n = resolver.merge_duplicates(batch_size=batch)
        return PhaseStats("final_dedup", n, "")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _pick_primary(
        group: list[Entity],
        preferred_name: str = "",
    ) -> Entity:
        """Pick the authoritative entity from a group of equivalents.

        Priority:
          1. Entity whose normalized_name matches the preferred_name
             (i.e. the registry canonical — usually the English form).
          2. English-script entity with most article links.
          3. Any entity with most article links.
        """
        preferred_name = preferred_name.lower()

        # P1: exact name match to preferred canonical
        if preferred_name:
            for e in group:
                if e.normalized_name == preferred_name:
                    return e

        # P2: English-script entity
        english = [e for e in group if not _is_arabic(e.name)]
        if english:
            return max(english, key=lambda e: getattr(e, "art_count", 0))

        # P3: most-mentioned regardless of script
        return max(group, key=lambda e: getattr(e, "art_count", 0))
