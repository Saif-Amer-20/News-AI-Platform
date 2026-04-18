"""Management command: build validation set from existing platform data.

Usage:
    python manage.py build_validation_set
    python manage.py build_validation_set --max-articles 500
    python manage.py build_validation_set --output /path/to/output.json
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from validation.extractor import IndependentGroundTruthBuilder, PseudoGroundTruthBuilder, ValidationDatasetExtractor


class Command(BaseCommand):
    help = "Build a validation dataset from existing articles, stories, events, and entities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-articles",
            type=int,
            default=0,
            help="Maximum articles to sample (0 = all eligible).",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="",
            help="Path to write JSON output. Default: validation/validation_set.json",
        )

    def handle(self, *args, **options):
        max_articles = options["max_articles"]
        output_path = options["output"] or str(
            Path(__file__).resolve().parents[3] / "validation" / "validation_set.json"
        )

        self.stdout.write(self.style.NOTICE("Building validation dataset from existing data..."))

        # Extract
        extractor = ValidationDatasetExtractor()
        dataset = extractor.extract(max_articles=max_articles)

        if not dataset.records:
            self.stdout.write(self.style.WARNING("No eligible articles found."))
            return

        # Build pseudo-ground-truth
        gt_builder = PseudoGroundTruthBuilder()
        gt = gt_builder.build_all(dataset.records)

        # Output
        output = {
            "stats": dataset.stats,
            "ground_truth": {
                "clusters": gt["clusters"],
                "dedup_pairs": [[a, b] for a, b in gt["dedup_pairs"]],
                "entity_consensus": gt["entity_consensus"],
                "conflict_events": gt["conflict_events"],
                "geo_truth": {str(k): v for k, v in gt["geo_truth"].items()},
            },
            "records": [r.to_dict() for r in dataset.records],
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        self.stdout.write(self.style.SUCCESS(
            f"\nValidation set saved to {output_path}"
        ))

        # Print summary
        self.stdout.write(f"\n  Articles sampled:     {dataset.stats.get('sampled', 0)}")
        self.stdout.write(f"  Languages:            {dataset.stats.get('languages', {})}")
        self.stdout.write(f"  Unique sources:       {dataset.stats.get('unique_sources', 0)}")
        self.stdout.write(f"  With story:           {dataset.stats.get('with_story', 0)}")
        self.stdout.write(f"  With event:           {dataset.stats.get('with_event', 0)}")
        self.stdout.write(f"  With entities:        {dataset.stats.get('with_entities', 0)}")
        self.stdout.write(f"  Duplicates:           {dataset.stats.get('duplicates', 0)}")
        self.stdout.write(f"  Unique clusters:      {dataset.stats.get('unique_clusters', 0)}")
        self.stdout.write(f"  Conflict events:      {len(gt['conflict_events'])}")
        self.stdout.write(f"  Geo-tagged articles:  {len(gt['geo_truth'])}")
