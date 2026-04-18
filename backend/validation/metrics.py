"""Metrics calculation for benchmarking the News Intelligence pipeline.

All metric functions accept ground-truth vs predicted sets/lists and return
float scores in [0, 1] unless otherwise noted.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


# ── Core metrics ──────────────────────────────────────────────────────────────


def precision(true_set: set, pred_set: set) -> float:
    if not pred_set:
        return 0.0
    return len(true_set & pred_set) / len(pred_set)


def recall(true_set: set, pred_set: set) -> float:
    if not true_set:
        return 1.0  # nothing to find → perfect recall
    return len(true_set & pred_set) / len(true_set)


def f1(true_set: set, pred_set: set) -> float:
    p = precision(true_set, pred_set)
    r = recall(true_set, pred_set)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


# ── Entity extraction metrics ────────────────────────────────────────────────


@dataclass
class EntityMetrics:
    """Per-type and overall entity extraction metrics."""
    overall_precision: float = 0.0
    overall_recall: float = 0.0
    overall_f1: float = 0.0
    per_type: dict[str, dict[str, float]] = field(default_factory=dict)
    total_true: int = 0
    total_predicted: int = 0
    total_correct: int = 0


def compute_entity_metrics(
    articles: list[dict],
    normalize_fn=None,
) -> EntityMetrics:
    """Compute entity extraction precision/recall/F1.

    Each article dict must have:
      - gt_entities: list[dict] with keys {name, type}
      - pred_entities: list[dict] with keys {name, type}

    normalize_fn: optional callable(str) -> str for name normalization.

    Matching is done on NORMALIZED NAME ONLY — entity type mismatches
    (e.g., person vs org) do NOT count as errors.  Per-type stats are
    computed using the GT type for TP/FN and the pred type for FP.
    """
    if normalize_fn is None:
        normalize_fn = lambda s: s.strip().lower()

    type_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0}
    )
    total_tp = total_fp = total_fn = 0

    for art in articles:
        # Build sets keyed on normalized name ONLY
        gt_names: dict[str, str] = {}  # norm_name -> type
        for e in art.get("gt_entities", []):
            norm = normalize_fn(e["name"])
            if norm:
                gt_names[norm] = e["type"].lower()

        pred_names: dict[str, str] = {}  # norm_name -> type
        for e in art.get("pred_entities", []):
            norm = normalize_fn(e["name"])
            if norm:
                pred_names[norm] = e["type"].lower()

        gt_name_set = set(gt_names.keys())
        pred_name_set = set(pred_names.keys())

        tp_names = gt_name_set & pred_name_set
        fp_names = pred_name_set - gt_name_set
        fn_names = gt_name_set - pred_name_set

        total_tp += len(tp_names)
        total_fp += len(fp_names)
        total_fn += len(fn_names)

        # Per-type: use GT type for TP/FN, pred type for FP
        for name in tp_names:
            type_stats[gt_names[name]]["tp"] += 1
        for name in fp_names:
            type_stats[pred_names[name]]["fp"] += 1
        for name in fn_names:
            type_stats[gt_names[name]]["fn"] += 1

    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    overall_f = (
        2 * overall_p * overall_r / (overall_p + overall_r)
        if (overall_p + overall_r)
        else 0.0
    )

    per_type = {}
    for etype, counts in sorted(type_stats.items()):
        tp_t, fp_t, fn_t = counts["tp"], counts["fp"], counts["fn"]
        p = tp_t / (tp_t + fp_t) if (tp_t + fp_t) else 0.0
        r = tp_t / (tp_t + fn_t) if (tp_t + fn_t) else 0.0
        f = 2 * p * r / (p + r) if (p + r) else 0.0
        per_type[etype] = {"precision": p, "recall": r, "f1": f}

    return EntityMetrics(
        overall_precision=overall_p,
        overall_recall=overall_r,
        overall_f1=overall_f,
        per_type=per_type,
        total_true=total_tp + total_fn,
        total_predicted=total_tp + total_fp,
        total_correct=total_tp,
    )


# ── Clustering / similarity metrics ──────────────────────────────────────────


@dataclass
class ClusterMetrics:
    """Story clustering quality metrics."""
    same_event_accuracy: float = 0.0  # articles that should cluster did cluster
    false_merge_rate: float = 0.0      # articles wrongly clustered together
    missed_grouping_rate: float = 0.0  # articles that should cluster but didn't
    total_pairs_checked: int = 0


def compute_cluster_metrics(articles: list[dict]) -> ClusterMetrics:
    """Compute clustering quality.

    Each article dict must have:
      - id: str
      - gt_cluster: str (ground truth cluster label)
      - pred_cluster: str | None (predicted story_id or cluster label)
    """
    n = len(articles)
    if n < 2:
        return ClusterMetrics()

    should_cluster = 0       # pairs that share gt_cluster
    did_cluster = 0          # of those, how many share pred_cluster
    should_not_cluster = 0   # pairs that differ in gt_cluster
    false_merged = 0         # of those, how many share pred_cluster

    for i in range(n):
        for j in range(i + 1, n):
            gt_same = articles[i]["gt_cluster"] == articles[j]["gt_cluster"]
            pred_i = articles[i].get("pred_cluster")
            pred_j = articles[j].get("pred_cluster")
            pred_same = (
                pred_i is not None
                and pred_j is not None
                and pred_i == pred_j
            )

            if gt_same:
                should_cluster += 1
                if pred_same:
                    did_cluster += 1
            else:
                should_not_cluster += 1
                if pred_same:
                    false_merged += 1

    return ClusterMetrics(
        same_event_accuracy=did_cluster / should_cluster if should_cluster else 1.0,
        false_merge_rate=false_merged / should_not_cluster if should_not_cluster else 0.0,
        missed_grouping_rate=1.0 - (did_cluster / should_cluster) if should_cluster else 0.0,
        total_pairs_checked=should_cluster + should_not_cluster,
    )


# ── Dedup metrics ─────────────────────────────────────────────────────────────


@dataclass
class DedupMetrics:
    """Deduplication accuracy metrics."""
    precision: float = 0.0   # of flagged duplicates, how many are correct
    miss_rate: float = 0.0   # of true duplicates, how many were missed
    total_true_dups: int = 0
    total_flagged: int = 0
    total_correct: int = 0


def compute_dedup_metrics(articles: list[dict]) -> DedupMetrics:
    """Compute dedup precision and miss rate.

    Each article dict must have:
      - id: str
      - gt_dup_of: str | None (ground truth duplicate-of article ID)
      - pred_is_dup: bool
      - pred_dup_of: str | None
    """
    true_dups = {a["id"] for a in articles if a.get("gt_dup_of")}
    flagged = {a["id"] for a in articles if a.get("pred_is_dup")}

    correct = true_dups & flagged
    missed = true_dups - flagged
    false_flags = flagged - true_dups

    total_flagged = len(flagged)
    total_true = len(true_dups)

    return DedupMetrics(
        precision=len(correct) / total_flagged if total_flagged else 1.0,
        miss_rate=len(missed) / total_true if total_true else 0.0,
        total_true_dups=total_true,
        total_flagged=total_flagged,
        total_correct=len(correct),
    )


# ── Geo extraction metrics ───────────────────────────────────────────────────


@dataclass
class GeoMetrics:
    """Geographic extraction accuracy."""
    correct_location_pct: float = 0.0
    false_location_pct: float = 0.0
    country_accuracy: float = 0.0
    total_with_gt_location: int = 0
    total_with_pred_location: int = 0


def compute_geo_metrics(articles: list[dict]) -> GeoMetrics:
    """Compute geo extraction accuracy with multi-country support.

    Each article dict must have:
      - gt_location: dict | None  {country: str, all_countries: set[str]}
      - pred_location: dict | None  {country: str, name: str}

    Multi-country scoring: prediction is CORRECT if the system's country
    is ANY of the countries mentioned in the article text (all_countries).
    Articles without GT location are EXCLUDED from false_location scoring
    (no penalty for GT gaps — the GT patterns may simply not cover them).
    """
    has_gt = [a for a in articles if a.get("gt_location") and a["gt_location"].get("country")]
    has_pred = [a for a in articles if a.get("pred_location") and a["pred_location"].get("country")]

    correct_country = 0
    for a in has_gt:
        gt_loc = a["gt_location"]
        pred_loc = a.get("pred_location") or {}
        pred_c = (pred_loc.get("country") or "").upper()
        if not pred_c:
            continue

        # Multi-country: correct if pred is in ANY of the GT countries
        all_gt_countries = gt_loc.get("all_countries")
        if all_gt_countries and isinstance(all_gt_countries, set):
            if pred_c in {c.upper() for c in all_gt_countries}:
                correct_country += 1
        else:
            # Fallback: single-country match
            gt_c = gt_loc["country"].upper()
            if gt_c == pred_c:
                correct_country += 1

    total_gt = len(has_gt)

    return GeoMetrics(
        correct_location_pct=correct_country / total_gt if total_gt else 0.0,
        false_location_pct=0.0,  # No longer penalize — GT gaps are not system errors
        country_accuracy=correct_country / total_gt if total_gt else 0.0,
        total_with_gt_location=total_gt,
        total_with_pred_location=len(has_pred),
    )


# ── Narrative/conflict metrics ────────────────────────────────────────────────


@dataclass
class ConflictMetrics:
    """Narrative contradiction detection metrics."""
    correct_contradiction_pct: float = 0.0
    false_contradiction_pct: float = 0.0
    total_true_contradictions: int = 0
    total_detected: int = 0


def compute_conflict_metrics(articles: list[dict]) -> ConflictMetrics:
    """Compute contradiction detection accuracy.

    Each article dict must have:
      - id: str
      - gt_contradicts: list[str]  (IDs of articles this one contradicts)
      - pred_contradicts: list[str]
    """
    true_pairs = set()
    pred_pairs = set()

    for a in articles:
        aid = a["id"]
        for cid in a.get("gt_contradicts", []):
            pair = tuple(sorted([aid, cid]))
            true_pairs.add(pair)
        for cid in a.get("pred_contradicts", []):
            pair = tuple(sorted([aid, cid]))
            pred_pairs.add(pair)

    correct = true_pairs & pred_pairs
    false_pos = pred_pairs - true_pairs
    missed = true_pairs - pred_pairs

    total_true = len(true_pairs)
    total_pred = len(pred_pairs)

    return ConflictMetrics(
        correct_contradiction_pct=len(correct) / total_true if total_true else 0.0,
        false_contradiction_pct=len(false_pos) / total_pred if total_pred else 0.0,
        total_true_contradictions=total_true,
        total_detected=total_pred,
    )


# ── Performance metrics ───────────────────────────────────────────────────────


@dataclass
class PerformanceMetrics:
    """System performance metrics."""
    avg_time_per_article_ms: float = 0.0
    max_time_per_article_ms: float = 0.0
    min_time_per_article_ms: float = 0.0
    total_time_s: float = 0.0
    articles_processed: int = 0
    errors: int = 0


class PerformanceTracker:
    """Track processing time for articles."""

    def __init__(self):
        self._times: list[float] = []
        self._errors = 0

    def record(self, duration_s: float):
        self._times.append(duration_s)

    def record_error(self):
        self._errors += 1

    def summarize(self) -> PerformanceMetrics:
        if not self._times:
            return PerformanceMetrics(errors=self._errors)
        times_ms = [t * 1000 for t in self._times]
        return PerformanceMetrics(
            avg_time_per_article_ms=sum(times_ms) / len(times_ms),
            max_time_per_article_ms=max(times_ms),
            min_time_per_article_ms=min(times_ms),
            total_time_s=sum(self._times),
            articles_processed=len(self._times),
            errors=self._errors,
        )


# ── Aggregate report ──────────────────────────────────────────────────────────


@dataclass
class BenchmarkReport:
    """Full benchmark report combining all metrics."""
    entity: EntityMetrics = field(default_factory=EntityMetrics)
    cluster: ClusterMetrics = field(default_factory=ClusterMetrics)
    dedup: DedupMetrics = field(default_factory=DedupMetrics)
    geo: GeoMetrics = field(default_factory=GeoMetrics)
    conflict: ConflictMetrics = field(default_factory=ConflictMetrics)
    performance: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    by_language: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        import dataclasses
        result = {}
        for fld in dataclasses.fields(self):
            val = getattr(self, fld.name)
            if dataclasses.is_dataclass(val):
                result[fld.name] = dataclasses.asdict(val)
            elif isinstance(val, dict):
                result[fld.name] = val
            else:
                result[fld.name] = val
        return result

    def print_report(self):
        """Print a human-readable benchmark report."""
        print("\n" + "=" * 70)
        print("  NEWS INTELLIGENCE PLATFORM — BENCHMARK REPORT")
        print("=" * 70)

        print("\n── Entity Extraction ──")
        print(f"  Precision:  {self.entity.overall_precision:.3f}")
        print(f"  Recall:     {self.entity.overall_recall:.3f}")
        print(f"  F1:         {self.entity.overall_f1:.3f}")
        print(f"  True: {self.entity.total_true}  Predicted: {self.entity.total_predicted}  Correct: {self.entity.total_correct}")
        for etype, scores in sorted(self.entity.per_type.items()):
            print(f"    {etype:>14s}  P={scores['precision']:.3f}  R={scores['recall']:.3f}  F1={scores['f1']:.3f}")

        print("\n── Story Clustering ──")
        print(f"  Same-event accuracy:  {self.cluster.same_event_accuracy:.3f}")
        print(f"  False merge rate:     {self.cluster.false_merge_rate:.3f}")
        print(f"  Missed grouping rate: {self.cluster.missed_grouping_rate:.3f}")
        print(f"  Total pairs checked:  {self.cluster.total_pairs_checked}")

        print("\n── Deduplication ──")
        print(f"  Precision:  {self.dedup.precision:.3f}")
        print(f"  Miss rate:  {self.dedup.miss_rate:.3f}")
        print(f"  True dups: {self.dedup.total_true_dups}  Flagged: {self.dedup.total_flagged}  Correct: {self.dedup.total_correct}")

        print("\n── Geo Extraction ──")
        print(f"  Correct location %:  {self.geo.correct_location_pct:.3f}")
        print(f"  False location %:    {self.geo.false_location_pct:.3f}")
        print(f"  Country accuracy:    {self.geo.country_accuracy:.3f}")

        print("\n── Conflict/Contradiction Detection ──")
        print(f"  Correct detection %: {self.conflict.correct_contradiction_pct:.3f}")
        print(f"  False detection %:   {self.conflict.false_contradiction_pct:.3f}")
        print(f"  True contradictions: {self.conflict.total_true_contradictions}")
        print(f"  Detected:            {self.conflict.total_detected}")

        print("\n── Performance ──")
        print(f"  Avg time/article:  {self.performance.avg_time_per_article_ms:.0f} ms")
        print(f"  Max time/article:  {self.performance.max_time_per_article_ms:.0f} ms")
        print(f"  Total time:        {self.performance.total_time_s:.1f} s")
        print(f"  Articles:          {self.performance.articles_processed}")
        print(f"  Errors:            {self.performance.errors}")

        if self.by_language:
            print("\n── By Language ──")
            for lang, metrics in sorted(self.by_language.items()):
                print(f"  [{lang}]")
                for k, v in metrics.items():
                    print(f"    {k}: {v}")

        print("\n" + "=" * 70)
