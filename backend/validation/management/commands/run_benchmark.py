"""Management command: run the full data-driven benchmark.

Usage:
    python manage.py run_benchmark
    python manage.py run_benchmark --max-articles 500
    python manage.py run_benchmark --output /path/to/report.json
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand

from validation.benchmark import BenchmarkRunner
from validation.models import ValidationRun


class Command(BaseCommand):
    help = "Run the full data-driven benchmark against existing platform data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-articles",
            type=int,
            default=0,
            help="Maximum articles to evaluate (0 = all eligible).",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="",
            help="Path to write JSON report. Default: validation/benchmark_report.json",
        )

    def handle(self, *args, **options):
        max_articles = options["max_articles"]
        output_path = options["output"] or str(
            Path(__file__).resolve().parents[3] / "validation" / "benchmark_report.json"
        )

        self.stdout.write(self.style.NOTICE("Running data-driven benchmark..."))

        # Create a run record
        run = ValidationRun.objects.create(
            articles_sampled=0,
            notes=f"max_articles={max_articles}",
        )

        try:
            runner = BenchmarkRunner()
            report = runner.run(max_articles=max_articles)

            # Update run record
            run.status = ValidationRun.Status.COMPLETED
            run.articles_sampled = report.dataset_stats.get("sampled", 0)
            run.report_json = report.to_dict()
            run.elapsed_seconds = Decimal(str(round(report.elapsed_seconds, 2)))
            run.save()

            # Print human-readable report
            self.stdout.write(report.print_report())

            # Save JSON
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False, default=str)

            self.stdout.write(self.style.SUCCESS(f"\nJSON report saved to {output_path}"))
            self.stdout.write(self.style.SUCCESS(f"Run ID: {run.id}"))

        except Exception as exc:
            run.status = ValidationRun.Status.FAILED
            run.notes += f"\nError: {exc}"
            run.save()
            raise
