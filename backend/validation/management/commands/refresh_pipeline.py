"""Re-run improved pipeline components on existing data.

Usage:
    python manage.py refresh_pipeline [--geo] [--conflict] [--dedup] [--all]
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from sources.models import Article, Event


class Command(BaseCommand):
    help = "Re-process existing data through improved geo/conflict/dedup pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--geo", action="store_true", help="Re-run geo extraction on all events")
        parser.add_argument("--conflict", action="store_true", help="Re-run conflict detection on all events")
        parser.add_argument("--dedup", action="store_true", help="Re-run dedup on all non-duplicate articles")
        parser.add_argument("--all", action="store_true", help="Run all refreshes")

    def handle(self, **options):
        run_all = options["all"]
        t0 = time.time()

        if run_all or options["geo"]:
            self._refresh_geo()

        if run_all or options["conflict"]:
            self._refresh_conflict()

        if run_all or options["dedup"]:
            self._refresh_dedup()

        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(f"\nDone in {elapsed:.1f}s"))

    def _refresh_geo(self):
        from services.orchestration.geo_extraction_service import GeoExtractionService

        geo_svc = GeoExtractionService()
        events = Event.objects.all()
        total = events.count()
        updated = 0

        self.stdout.write(f"\n── Refreshing geo for {total} events ──")

        for event in events.iterator():
            # Get primary article for this event
            primary = (
                Article.objects.filter(
                    story__event=event,
                    is_duplicate=False,
                )
                .order_by("-importance_score", "-published_at")
                .first()
            )
            if not primary:
                continue

            geo = geo_svc.extract_geo(primary)
            new_country = geo.get("location_country", "")
            new_name = geo.get("location_name", "")

            if new_country != (event.location_country or "") or new_name != (event.location_name or ""):
                event.location_country = new_country
                event.location_name = new_name
                if geo.get("location_lat"):
                    event.location_lat = geo["location_lat"]
                if geo.get("location_lon"):
                    event.location_lon = geo["location_lon"]
                event.save(update_fields=[
                    "location_country", "location_name",
                    "location_lat", "location_lon", "updated_at",
                ])
                updated += 1

        self.stdout.write(f"  Updated {updated}/{total} events")

    def _refresh_conflict(self):
        from services.orchestration.narrative_conflict_service import NarrativeConflictService

        conflict_svc = NarrativeConflictService()
        events = Event.objects.all()
        total = events.count()
        flagged_before = events.filter(conflict_flag=True).count()

        self.stdout.write(f"\n── Refreshing conflict for {total} events ──")
        self.stdout.write(f"  Before: {flagged_before} flagged")

        for event in events.iterator():
            conflict_svc.detect(event)

        flagged_after = Event.objects.filter(conflict_flag=True).count()
        self.stdout.write(f"  After:  {flagged_after} flagged")

    def _refresh_dedup(self):
        from services.orchestration.dedup_service import DedupService

        dedup_svc = DedupService()
        # Re-check articles that are currently NOT marked as duplicates
        articles = Article.objects.filter(is_duplicate=False).order_by("published_at")
        total = articles.count()
        new_dups = 0

        self.stdout.write(f"\n── Refreshing dedup for {total} non-duplicate articles ──")

        for article in articles.iterator():
            result = dedup_svc.mark_duplicates(article)
            if result.is_duplicate:
                new_dups += 1

        self.stdout.write(f"  New duplicates found: {new_dups}")
