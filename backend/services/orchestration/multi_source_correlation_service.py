"""Multi-Source Correlation Service — analyse source diversity for events.

Responsibilities
─────────────────
1. Group event articles by source.
2. Determine if multiple *independent* sources confirm the event.
3. Produce a correlation report stored in Event.metadata["source_correlation"].

Independence heuristic: two sources are considered independent when they have
different ``base_url`` *and* different ``country``.  Same-outlet syndication
(same base_url) counts as a single source.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from sources.models import Article, Event, Source

logger = logging.getLogger(__name__)


class MultiSourceCorrelationService:
    """Correlate articles across diverse, independent sources."""

    def correlate(self, event: Event) -> dict:
        """
        Analyse source diversity for *event* and persist a summary
        in ``event.metadata["source_correlation"]``.

        Returns the correlation report dict.
        """
        articles = list(
            Article.objects.filter(
                story__event=event,
                is_duplicate=False,
            ).select_related("source")[:300]
        )

        if not articles:
            report = self._empty_report()
            self._persist(event, report)
            return report

        # Group articles by source
        by_source: dict[int, list[Article]] = defaultdict(list)
        sources_map: dict[int, Source] = {}
        for a in articles:
            by_source[a.source_id].append(a)
            sources_map[a.source_id] = a.source

        # Build independence clusters (group sources sharing base_url + country)
        independence_clusters = self._build_independence_clusters(sources_map)

        # Source breakdown
        source_breakdown: list[dict] = []
        for source_id, arts in by_source.items():
            src = sources_map[source_id]
            source_breakdown.append({
                "source_id": source_id,
                "source_name": src.name,
                "source_type": src.source_type,
                "country": src.country,
                "trust_score": str(src.trust_score),
                "article_count": len(arts),
            })

        total_sources = len(by_source)
        independent_count = len(independence_clusters)
        is_multi_source = independent_count >= 2

        report = {
            "total_articles": len(articles),
            "total_sources": total_sources,
            "independent_source_clusters": independent_count,
            "is_multi_source_confirmed": is_multi_source,
            "source_breakdown": source_breakdown,
        }

        self._persist(event, report)

        # Also update source_count on the event
        event.source_count = total_sources
        event.save(update_fields=["source_count", "updated_at"])

        logger.info(
            "Event %s multi-source correlation: %d sources, %d independent, confirmed=%s",
            event.id,
            total_sources,
            independent_count,
            is_multi_source,
        )
        return report

    # ── Internals ─────────────────────────────────────────────────

    def _build_independence_clusters(
        self, sources_map: dict[int, Source]
    ) -> list[set[int]]:
        """
        Group source IDs into clusters.  Sources sharing the same
        (base_url_domain, country) are in the same cluster.
        """
        cluster_key_map: dict[str, set[int]] = defaultdict(set)
        for sid, src in sources_map.items():
            domain = self._extract_domain(src.base_url or src.endpoint_url or "")
            key = f"{domain}|{src.country}".lower()
            cluster_key_map[key].add(sid)
        return list(cluster_key_map.values())

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Crude domain extraction without urllib."""
        url = url.lower().replace("https://", "").replace("http://", "")
        return url.split("/")[0].split("?")[0] if url else ""

    def _persist(self, event: Event, report: dict) -> None:
        meta = dict(event.metadata or {})
        meta["source_correlation"] = report
        event.metadata = meta
        event.save(update_fields=["metadata", "updated_at"])

    @staticmethod
    def _empty_report() -> dict:
        return {
            "total_articles": 0,
            "total_sources": 0,
            "independent_source_clusters": 0,
            "is_multi_source_confirmed": False,
            "source_breakdown": [],
        }
