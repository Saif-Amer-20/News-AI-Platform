"""Export a manual validation sample (50-100 articles) for human review.

Usage:
    python manage.py export_manual_sample
    python manage.py export_manual_sample --count 100
    python manage.py export_manual_sample --output /path/to/sample.json
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from django.core.management.base import BaseCommand

from validation.extractor import (
    IndependentGroundTruthBuilder,
    ValidationDatasetExtractor,
)


class Command(BaseCommand):
    help = "Export a diverse sample of 50-100 articles for manual validation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=50,
            help="Number of articles to sample (default: 50).",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="",
            help="Path to write JSON output.",
        )

    def handle(self, *args, **options):
        count = min(options["count"], 200)
        output_path = options["output"] or str(
            Path(__file__).resolve().parents[3] / "validation" / "manual_sample.json"
        )

        self.stdout.write(self.style.NOTICE(f"Building manual validation sample ({count} articles)..."))

        extractor = ValidationDatasetExtractor()
        dataset = extractor.extract(max_articles=count * 3)  # oversample then select

        if not dataset.records:
            self.stdout.write(self.style.WARNING("No eligible articles found."))
            return

        records = dataset.records

        # Build independent GT for context
        gt_builder = IndependentGroundTruthBuilder()
        gt = gt_builder.build_all(records)

        # Select diverse sample
        sample = self._select_diverse(records, gt, count)

        # Build review items
        cluster_for = {}
        for ck, aids in gt["clusters"].items():
            for aid in aids:
                cluster_for[aid] = ck

        indie_dup_of = {}
        for dup_id, orig_id in gt["dedup_pairs"]:
            indie_dup_of[dup_id] = orig_id

        review_items = []
        for r in sample:
            text_geo = gt["geo_truth"].get(r.article_id, {})
            indie_cluster = cluster_for.get(r.article_id)

            item = {
                "article_id": r.article_id,
                "title": r.title,
                "url": r.url,
                "source": r.source_name,
                "language": r.language,
                "content_preview": r.content_snippet[:500],
                "published_at": r.published_at,
                # System values (what pipeline produced)
                "system": {
                    "story_id": r.story_id,
                    "is_duplicate": r.is_duplicate,
                    "duplicate_of_id": r.duplicate_of_id,
                    "event_location_country": r.gt_location_country,
                    "conflict_flag": r.gt_has_conflict,
                    "entities": list(zip(r.entity_names, r.entity_types)),
                },
                # Independent analysis (text-based)
                "independent": {
                    "indie_cluster": indie_cluster,
                    "indie_is_duplicate": r.article_id in indie_dup_of,
                    "indie_dup_of": indie_dup_of.get(r.article_id),
                    "text_country": text_geo.get("country"),
                    "text_country_mentions": text_geo.get("all_countries", {}),
                    "indie_conflict_cluster": indie_cluster in set(gt["conflict_events"]) if indie_cluster else False,
                },
                # Human review fields (to be filled manually)
                "human_review": {
                    "correct_cluster": None,  # True/False
                    "correct_dedup": None,
                    "correct_geo": None,
                    "correct_conflict": None,
                    "correct_entities": None,
                    "notes": "",
                },
            }
            review_items.append(item)

        output = {
            "total_articles": len(review_items),
            "instructions": (
                "Review each article and fill in the 'human_review' section. "
                "Compare 'system' (pipeline output) vs 'independent' (text analysis). "
                "Mark True if system is correct, False if wrong, null if uncertain."
            ),
            "articles": review_items,
        }

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False, default=str)

        self.stdout.write(self.style.SUCCESS(f"\nManual sample saved to {output_path}"))
        self.stdout.write(f"  Articles: {len(review_items)}")

        # Summary of what's interesting in the sample
        has_story = sum(1 for r in sample if r.has_story)
        has_dup = sum(1 for r in sample if r.is_duplicate)
        has_event = sum(1 for r in sample if r.has_event)
        has_indie_cluster = sum(1 for r in sample if r.article_id in cluster_for)
        has_indie_dup = sum(1 for r in sample if r.article_id in indie_dup_of)

        self.stdout.write(f"  System: {has_story} with story, {has_dup} duplicates, {has_event} with event")
        self.stdout.write(f"  Independent: {has_indie_cluster} in clusters, {has_indie_dup} indie duplicates")

    def _select_diverse(self, records, gt, count):
        """Select a diverse sample covering different feature buckets."""
        # Categorize records
        buckets = {
            "with_event": [],
            "duplicate": [],
            "in_indie_cluster": [],
            "with_entities": [],
            "unclustered": [],
        }

        cluster_for = {}
        for ck, aids in gt["clusters"].items():
            for aid in aids:
                cluster_for[aid] = ck

        for r in records:
            if r.has_event:
                buckets["with_event"].append(r)
            if r.is_duplicate:
                buckets["duplicate"].append(r)
            if r.article_id in cluster_for:
                buckets["in_indie_cluster"].append(r)
            if r.entity_count > 0:
                buckets["with_entities"].append(r)
            if not r.has_story and r.article_id not in cluster_for:
                buckets["unclustered"].append(r)

        # Proportional sampling from each bucket
        selected = set()
        result = []
        per_bucket = max(count // len(buckets), 5)

        for bucket_name, bucket_records in buckets.items():
            random.shuffle(bucket_records)
            for r in bucket_records[:per_bucket]:
                if r.article_id not in selected:
                    selected.add(r.article_id)
                    result.append(r)

        # Fill remainder randomly
        remaining = [r for r in records if r.article_id not in selected]
        random.shuffle(remaining)
        for r in remaining:
            if len(result) >= count:
                break
            result.append(r)

        return result[:count]
