"""Management command to recreate OpenSearch indices and reindex all articles/events."""

from django.core.management.base import BaseCommand

from services.orchestration.opensearch_service import (
    ARTICLE_INDEX,
    EVENT_INDEX,
    OpenSearchService,
)
from sources.models import Article, Event


class Command(BaseCommand):
    help = "Recreate OpenSearch indices with updated mappings and reindex all data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--articles-only",
            action="store_true",
            help="Only reindex articles (skip events).",
        )
        parser.add_argument(
            "--events-only",
            action="store_true",
            help="Only reindex events (skip articles).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Batch size for bulk indexing (default: 500).",
        )
        parser.add_argument(
            "--no-recreate",
            action="store_true",
            help="Skip index recreation (just reindex into existing indices).",
        )

    def handle(self, *args, **options):
        svc = OpenSearchService()
        batch_size = options["batch_size"]
        articles_only = options["articles_only"]
        events_only = options["events_only"]
        no_recreate = options["no_recreate"]

        if not no_recreate:
            self.stdout.write("Recreating indices with updated mappings...")
            adapter = svc._adapter
            if not events_only:
                adapter.delete_index(ARTICLE_INDEX)
            if not articles_only:
                adapter.delete_index(EVENT_INDEX)
            svc.ensure_indices()
            self.stdout.write(self.style.SUCCESS("Indices recreated."))

        if not events_only:
            self._reindex_articles(svc, batch_size)

        if not articles_only:
            self._reindex_events(svc, batch_size)

        self.stdout.write(self.style.SUCCESS("Reindex complete."))

    def _reindex_articles(self, svc: OpenSearchService, batch_size: int):
        qs = (
            Article.objects.select_related("source", "story", "story__event")
            .prefetch_related("article_entities__entity", "matched_topics")
            .order_by("id")
        )
        total = qs.count()
        self.stdout.write(f"Reindexing {total} articles...")

        indexed = 0
        batch = []
        for article in qs.iterator(chunk_size=batch_size):
            batch.append(article)
            if len(batch) >= batch_size:
                result = svc.bulk_index_articles(batch)
                indexed += len(batch)
                self.stdout.write(f"  {indexed}/{total} articles indexed")
                batch = []

        if batch:
            svc.bulk_index_articles(batch)
            indexed += len(batch)

        self.stdout.write(self.style.SUCCESS(f"  {indexed} articles indexed."))

    def _reindex_events(self, svc: OpenSearchService, batch_size: int):
        qs = Event.objects.order_by("id")
        total = qs.count()
        self.stdout.write(f"Reindexing {total} events...")

        indexed = 0
        for event in qs.iterator(chunk_size=batch_size):
            svc.index_event(event)
            indexed += 1
            if indexed % batch_size == 0:
                self.stdout.write(f"  {indexed}/{total} events indexed")

        self.stdout.write(self.style.SUCCESS(f"  {indexed} events indexed."))
