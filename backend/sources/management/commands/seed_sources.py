"""Management command to seed example news sources for testing."""

from django.core.management.base import BaseCommand

from sources.models import Source


EXAMPLE_SOURCES = [
    {
        "name": "Al Jazeera RSS",
        "source_type": Source.SourceType.RSS,
        "parser_type": Source.ParserType.RSS,
        "base_url": "https://www.aljazeera.com/xml/rss/all.xml",
        "language": "en",
        "country": "QA",
        "fetch_interval_minutes": 15,
        "parser_config": {"fetch_full_article": False, "max_items": 20},
    },
    {
        "name": "Reuters World RSS",
        "source_type": Source.SourceType.RSS,
        "parser_type": Source.ParserType.RSS,
        "base_url": "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best",
        "language": "en",
        "country": "US",
        "fetch_interval_minutes": 15,
        "parser_config": {"fetch_full_article": False, "max_items": 20},
    },
    {
        "name": "BBC News RSS",
        "source_type": Source.SourceType.RSS,
        "parser_type": Source.ParserType.RSS,
        "base_url": "https://feeds.bbci.co.uk/news/rss.xml",
        "language": "en",
        "country": "GB",
        "fetch_interval_minutes": 15,
        "parser_config": {"fetch_full_article": False, "max_items": 20},
    },
    {
        "name": "GDELT Global News",
        "source_type": Source.SourceType.API,
        "parser_type": Source.ParserType.GDELT,
        "base_url": "https://api.gdeltproject.org/api/v2/doc/doc",
        "language": "en",
        "fetch_interval_minutes": 30,
        "parser_config": {"query": "global news", "max_records": 10, "sort": "DateDesc"},
    },
    {
        "name": "TechCrunch HTML",
        "source_type": Source.SourceType.HTML,
        "parser_type": Source.ParserType.HTML,
        "base_url": "https://techcrunch.com/",
        "language": "en",
        "country": "US",
        "fetch_interval_minutes": 60,
        "parser_config": {"mode": "auto", "max_urls": 5},
    },
]


class Command(BaseCommand):
    help = "Seeds example news sources for testing the ingestion pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing sources before seeding.",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            count, _ = Source.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {count} existing source records."))

        created = 0
        for src_data in EXAMPLE_SOURCES:
            name = src_data["name"]
            _, was_created = Source.objects.get_or_create(
                name=name,
                defaults=src_data,
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  Created: {name}"))
            else:
                self.stdout.write(f"  Exists:  {name}")

        self.stdout.write(self.style.SUCCESS(f"\nDone. {created} new sources created."))
