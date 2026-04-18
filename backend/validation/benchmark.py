"""Benchmark runner — measures pipeline quality using real data.

Queries existing articles, builds INDEPENDENT ground-truth from text
analysis (title similarity, content hashing, NLP patterns), then
compares against what the pipeline actually produced.

This measures:
  - Entity extraction consistency (cross-article consensus in independent clusters)
  - Clustering accuracy (title similarity vs system's story_id)
  - Dedup accuracy (content similarity vs system's is_duplicate)
  - Geo extraction accuracy (text-extracted countries vs event location)
  - Conflict detection accuracy (keyword analysis vs conflict_flag)
  - Source quality analysis
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from validation.extractor import (
    IndependentGroundTruthBuilder,
    PseudoGroundTruthBuilder,
    SourceQualityExtractor,
    ValidationDatasetExtractor,
    is_noisy_entity,
    normalize_entity_name,
)
from validation.metrics import (
    BenchmarkReport,
    ClusterMetrics,
    ConflictMetrics,
    DedupMetrics,
    EntityMetrics,
    GeoMetrics,
    compute_cluster_metrics,
    compute_conflict_metrics,
    compute_dedup_metrics,
    compute_entity_metrics,
    compute_geo_metrics,
)

logger = logging.getLogger(__name__)


@dataclass
class DataDrivenBenchmarkReport:
    """Full benchmark results from real data evaluation."""
    dataset_stats: dict[str, Any] = field(default_factory=dict)
    ground_truth_stats: dict[str, Any] = field(default_factory=dict)
    entity_metrics: dict[str, Any] = field(default_factory=dict)
    cluster_metrics: dict[str, Any] = field(default_factory=dict)
    dedup_metrics: dict[str, Any] = field(default_factory=dict)
    geo_metrics: dict[str, Any] = field(default_factory=dict)
    conflict_metrics: dict[str, Any] = field(default_factory=dict)
    source_quality: list[dict] = field(default_factory=list)
    coverage_report: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def print_report(self) -> str:
        """Format a human-readable report."""
        lines = [
            "",
            "=" * 72,
            "  NEWS INTELLIGENCE PLATFORM — DATA-DRIVEN BENCHMARK REPORT",
            "=" * 72,
            "",
        ]

        # Dataset overview
        stats = self.dataset_stats
        lines.append("── DATASET ─────────────────────────────────────────────")
        lines.append(f"  Total eligible articles: {stats.get('total_eligible', '?')}")
        lines.append(f"  Sampled for evaluation:  {stats.get('sampled', '?')}")
        lines.append(f"  Languages: {stats.get('languages', {})}")
        lines.append(f"  Sources:   {stats.get('unique_sources', '?')}")
        lines.append(f"  With story:   {stats.get('with_story', 0)}")
        lines.append(f"  With event:   {stats.get('with_event', 0)}")
        lines.append(f"  With entities:{stats.get('with_entities', 0)}")
        lines.append(f"  Duplicates:   {stats.get('duplicates', 0)}")
        lines.append(f"  Conflict flag:{stats.get('with_conflict', 0)}")
        lines.append(f"  With location:{stats.get('with_location', 0)}")
        lines.append("")

        # Ground truth summary
        gt = self.ground_truth_stats
        lines.append("── GROUND TRUTH ────────────────────────────────────────")
        lines.append(f"  Clusters (2+ articles):    {gt.get('clusters_count', 0)}")
        lines.append(f"  Duplicate pairs:           {gt.get('dedup_pairs_count', 0)}")
        lines.append(f"  Entity consensus clusters: {gt.get('entity_consensus_count', 0)}")
        lines.append(f"  Conflict events:           {gt.get('conflict_events_count', 0)}")
        lines.append(f"  Geo-tagged articles:       {gt.get('geo_truth_count', 0)}")
        lines.append("")

        # Metrics sections
        if self.entity_metrics:
            lines.append("── ENTITY EXTRACTION ───────────────────────────────────")
            lines.append(f"  Overall P/R/F1: {self.entity_metrics.get('overall_precision', 0):.3f} / "
                         f"{self.entity_metrics.get('overall_recall', 0):.3f} / "
                         f"{self.entity_metrics.get('overall_f1', 0):.3f}")
            for etype, vals in self.entity_metrics.get("per_type", {}).items():
                lines.append(f"    {etype:15s}: P={vals['precision']:.3f}  R={vals['recall']:.3f}  F1={vals['f1']:.3f}")
            lines.append("")

        if self.cluster_metrics:
            lines.append("── CLUSTERING ──────────────────────────────────────────")
            lines.append(f"  Same-event accuracy:  {self.cluster_metrics.get('same_event_accuracy', 0):.3f}")
            lines.append(f"  False merge rate:     {self.cluster_metrics.get('false_merge_rate', 0):.3f}")
            lines.append(f"  Missed grouping rate: {self.cluster_metrics.get('missed_grouping_rate', 0):.3f}")
            lines.append(f"  Pairs evaluated:      {self.cluster_metrics.get('total_pairs_checked', 0)}")
            lines.append("")

        if self.dedup_metrics:
            lines.append("── DEDUP ───────────────────────────────────────────────")
            lines.append(f"  Precision:    {self.dedup_metrics.get('precision', 0):.3f}")
            lines.append(f"  Miss rate:    {self.dedup_metrics.get('miss_rate', 0):.3f}")
            lines.append(f"  True dups:    {self.dedup_metrics.get('total_true_dups', 0)}")
            lines.append(f"  Flagged:      {self.dedup_metrics.get('total_flagged', 0)}")
            lines.append("")

        if self.geo_metrics:
            lines.append("── GEO EXTRACTION ──────────────────────────────────────")
            lines.append(f"  Country accuracy:    {self.geo_metrics.get('country_accuracy', 0):.3f}")
            lines.append(f"  False location rate: {self.geo_metrics.get('false_location_pct', 0):.3f}")
            lines.append("")

        if self.conflict_metrics:
            lines.append("── CONFLICT DETECTION ──────────────────────────────────")
            lines.append(f"  Correct contradiction %: {self.conflict_metrics.get('correct_contradiction_pct', 0):.3f}")
            lines.append(f"  False contradiction %:   {self.conflict_metrics.get('false_contradiction_pct', 0):.3f}")
            lines.append("")

        # Coverage
        cov = self.coverage_report
        if cov:
            lines.append("── COVERAGE ────────────────────────────────────────────")
            lines.append(f"  Entity evaluation possible: {cov.get('entity_eval_possible', False)}")
            lines.append(f"  Cluster evaluation possible: {cov.get('cluster_eval_possible', False)}")
            lines.append(f"  Dedup evaluation possible:  {cov.get('dedup_eval_possible', False)}")
            lines.append(f"  Geo evaluation possible:    {cov.get('geo_eval_possible', False)}")
            lines.append(f"  Conflict evaluation possible:{cov.get('conflict_eval_possible', False)}")
            lines.append("")

        # Source quality top 5
        if self.source_quality:
            lines.append("── SOURCE QUALITY (TOP 10) ─────────────────────────────")
            lines.append(f"  {'Source':<30s} {'Articles':>8s} {'Quality':>8s} {'Dups':>6s} {'Class':>6s}")
            lines.append(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*6} {'-'*6}")
            for sq in self.source_quality[:10]:
                lines.append(
                    f"  {sq['source_name'][:30]:<30s} "
                    f"{sq['total_articles']:>8d} "
                    f"{sq['avg_quality_score']:>8.3f} "
                    f"{sq['duplication_rate']:>6.1%} "
                    f"{sq['quality_class']:>6s}"
                )
            lines.append("")

        lines.append(f"  Elapsed: {self.elapsed_seconds:.1f}s")
        lines.append("=" * 72)

        return "\n".join(lines)


class BenchmarkRunner:
    """Run the full data-driven benchmark."""

    def run(self, max_articles: int = 0) -> DataDrivenBenchmarkReport:
        t0 = time.time()
        report = DataDrivenBenchmarkReport()

        # ── 1. Extract validation dataset ──
        extractor = ValidationDatasetExtractor()
        dataset = extractor.extract(max_articles=max_articles)
        report.dataset_stats = dataset.stats
        records = dataset.records

        if not records:
            logger.warning("No records to benchmark. Ensure articles exist in database.")
            report.elapsed_seconds = time.time() - t0
            return report

        # ── 2. Build INDEPENDENT ground-truth (text-based, no DB fields) ──
        gt_builder = IndependentGroundTruthBuilder()
        gt = gt_builder.build_all(records)

        report.ground_truth_stats = {
            "clusters_count": len(gt["clusters"]),
            "dedup_pairs_count": len(gt["dedup_pairs"]),
            "entity_consensus_count": len(gt["entity_consensus"]),
            "conflict_events_count": len(gt["conflict_events"]),
            "geo_truth_count": len(gt["geo_truth"]),
        }

        # Coverage check — which metrics can we evaluate
        coverage = {
            "entity_eval_possible": len(gt["entity_consensus"]) > 0,
            "cluster_eval_possible": len(gt["clusters"]) > 0,
            "dedup_eval_possible": len(gt["dedup_pairs"]) > 0,
            "geo_eval_possible": len(gt["geo_truth"]) > 0,
            "conflict_eval_possible": len(gt["conflict_events"]) > 0,
        }
        report.coverage_report = coverage

        # ── 3. Entity metrics ──
        if coverage["entity_eval_possible"]:
            report.entity_metrics = self._eval_entities(records, gt["entity_consensus"])

        # ── 4. Cluster metrics ──
        if coverage["cluster_eval_possible"]:
            report.cluster_metrics = self._eval_clusters(records, gt["clusters"])

        # ── 5. Dedup metrics ──
        if coverage["dedup_eval_possible"]:
            report.dedup_metrics = self._eval_dedup(records, gt["dedup_pairs"])

        # ── 6. Geo metrics ──
        if coverage["geo_eval_possible"]:
            report.geo_metrics = self._eval_geo(records, gt["geo_truth"])

        # ── 7. Conflict metrics ──
        if coverage["conflict_eval_possible"]:
            report.conflict_metrics = self._eval_conflict(records, gt["conflict_events"])

        # ── 8. Source quality ──
        sq_extractor = SourceQualityExtractor()
        sq_records = sq_extractor.extract_all()
        report.source_quality = [r.to_dict() for r in sq_records]

        report.elapsed_seconds = time.time() - t0
        return report

    # ── Entity evaluation ─────────────────────────────────────────────────────

    def _eval_entities(
        self,
        records: list,
        entity_consensus: dict[str, list[dict]],
    ) -> dict:
        """Compare each article's entities against independent cluster consensus."""
        # Build reverse map: article_id → indie_cluster_key
        gt_builder = IndependentGroundTruthBuilder()
        indie_clusters = gt_builder.build_cluster_ground_truth(records)
        cluster_for = {}
        for ck, aids in indie_clusters.items():
            for aid in aids:
                cluster_for[aid] = ck

        metric_input = []
        for cluster_key, consensus in entity_consensus.items():
            cluster_articles = [
                r for r in records if cluster_for.get(r.article_id) == cluster_key
            ]
            for r in cluster_articles:
                # Filter noisy pred entities before scoring
                pred_entities = []
                for n, t in zip(r.entity_names, r.entity_types):
                    if not is_noisy_entity(n):
                        pred_entities.append({"name": n, "type": t})
                metric_input.append({
                    "gt_entities": consensus,
                    "pred_entities": pred_entities,
                })

        if not metric_input:
            return {}

        result = compute_entity_metrics(metric_input, normalize_fn=normalize_entity_name)
        return asdict(result)

    # ── Cluster evaluation ────────────────────────────────────────────────────

    def _eval_clusters(
        self,
        records: list,
        clusters: dict[str, list[int]],
    ) -> dict:
        """Evaluate clustering: independent title-based clusters (GT) vs system story_id (pred)."""
        # Build reverse mapping: article_id → indie_cluster_key
        indie_cluster_for = {}
        for cluster_key, article_ids in clusters.items():
            for aid in article_ids:
                indie_cluster_for[aid] = cluster_key

        metric_input = []
        for r in records:
            # GT = independent cluster (title similarity + time proximity)
            gt_cluster = indie_cluster_for.get(r.article_id, f"unclustered_{r.article_id}")
            # Pred = system's story_id assignment
            pred_cluster = f"story_{r.story_id}" if r.story_id else None

            metric_input.append({
                "id": str(r.article_id),
                "gt_cluster": gt_cluster,
                "pred_cluster": pred_cluster,
            })

        if len(metric_input) < 2:
            return {}

        result = compute_cluster_metrics(metric_input)
        return asdict(result)

    # ── Dedup evaluation ──────────────────────────────────────────────────────

    def _eval_dedup(
        self,
        records: list,
        dedup_pairs: list[tuple[int, int]],
    ) -> dict:
        """Evaluate dedup: independent content-similarity pairs (GT) vs system is_duplicate (pred)."""
        # True duplicates from independent analysis
        indie_dup_ids = {pair[0] for pair in dedup_pairs}
        indie_dup_of = {}
        for dup_id, orig_id in dedup_pairs:
            indie_dup_of[dup_id] = orig_id

        metric_input = []
        for r in records:
            gt_dup_of = str(indie_dup_of[r.article_id]) if r.article_id in indie_dup_of else None

            metric_input.append({
                "id": str(r.article_id),
                "gt_dup_of": gt_dup_of,
                "pred_is_dup": r.is_duplicate,
                "pred_dup_of": str(r.duplicate_of_id) if r.duplicate_of_id else None,
            })

        result = compute_dedup_metrics(metric_input)
        return asdict(result)

    # ── Geo evaluation ────────────────────────────────────────────────────────

    def _eval_geo(
        self,
        records: list,
        geo_truth: dict[int, dict],
    ) -> dict:
        """Evaluate geo: text-extracted countries (GT) vs system event.location_country (pred)."""
        metric_input = []
        for r in records:
            # GT = country extracted from article text by independent analysis
            gt_loc = geo_truth.get(r.article_id)

            # Pred = system's stored event location
            pred_loc = None
            if r.has_event and r.gt_location_country:
                pred_loc = {
                    "country": r.gt_location_country,
                    "name": r.gt_location_name,
                }

            metric_input.append({
                "gt_location": gt_loc,
                "pred_location": pred_loc,
            })

        result = compute_geo_metrics(metric_input)
        return asdict(result)

    # ── Conflict evaluation ───────────────────────────────────────────────────

    def _eval_conflict(
        self,
        records: list,
        conflict_events: list[str],
    ) -> dict:
        """Evaluate conflict: text-based keyword analysis (GT) vs system conflict_flag (pred)."""
        indie_conflict_set = set(conflict_events)

        # Build independent clusters to group articles
        gt_builder = IndependentGroundTruthBuilder()
        indie_clusters = gt_builder.build_cluster_ground_truth(records)

        # Reverse map: article_id → indie_cluster_key
        cluster_for = {}
        for ck, aids in indie_clusters.items():
            for aid in aids:
                cluster_for[aid] = ck

        # Group articles by indie cluster
        cluster_articles: dict[str, list] = {}
        for r in records:
            ck = cluster_for.get(r.article_id)
            if ck:
                cluster_articles.setdefault(ck, []).append(r)

        metric_input = []
        for r in records:
            gt_contradicts = []
            pred_contradicts = []
            ck = cluster_for.get(r.article_id)

            # GT: from independent text analysis
            if ck and ck in indie_conflict_set:
                siblings = cluster_articles.get(ck, [])
                gt_contradicts = [
                    str(s.article_id) for s in siblings if s.article_id != r.article_id
                ]

            # Pred: system's conflict_flag on event
            if r.gt_has_conflict and r.gt_event_group != "no_event":
                # Find all articles in same system event group
                pred_contradicts = [
                    str(s.article_id)
                    for s in records
                    if s.gt_event_group == r.gt_event_group
                    and s.article_id != r.article_id
                    and s.gt_has_conflict
                ]

            metric_input.append({
                "id": str(r.article_id),
                "gt_contradicts": gt_contradicts,
                "pred_contradicts": pred_contradicts,
            })

        result = compute_conflict_metrics(metric_input)
        return asdict(result)
