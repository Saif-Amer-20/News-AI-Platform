from django.core.management.base import BaseCommand, CommandError

from services.orchestration.ingest_orchestration import IngestOrchestrationService
from sources.models import Source


class Command(BaseCommand):
    help = "Fetches a source and optionally processes fetched raw items inline."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Source ID or slug")
        parser.add_argument(
            "--inline",
            action="store_true",
            help="Process raw items inline instead of queuing Celery follow-up tasks.",
        )

    def handle(self, *args, **options):
        source_lookup = options["source"]
        source = self._get_source(source_lookup)
        queue_follow_up = not options["inline"]

        run = IngestOrchestrationService().fetch_source(
            source_id=source.id,
            queue_follow_up=queue_follow_up,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Fetch run {run.id} completed with status={run.status} items_fetched={run.items_fetched}."
            )
        )

        if options["inline"]:
            articles_created = 0
            for raw_item in run.raw_items.order_by("id"):
                article = IngestOrchestrationService().process_raw_item(raw_item.id)
                if article:
                    articles_created += 1
            self.stdout.write(
                self.style.SUCCESS(f"Inline processing finished. Articles touched: {articles_created}.")
            )

    def _get_source(self, value: str) -> Source:
        if value.isdigit():
            return Source.objects.get(pk=int(value))

        try:
            return Source.objects.get(slug=value)
        except Source.DoesNotExist as exc:
            raise CommandError(f"Source '{value}' was not found.") from exc
