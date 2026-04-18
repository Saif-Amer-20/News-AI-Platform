from __future__ import annotations

import hashlib
import logging

from django.db import transaction
from django.conf import settings

from services.integrations.common import (
    RawFetchResult,
    build_raw_content_hash,
    clean_text,
    json_safe,
)
from services.integrations.minio_adapter import MinIOAdapter
from sources.models import Article, ParsedArticleCandidate, RawItem, Source, SourceFetchRun

logger = logging.getLogger(__name__)


class RawItemService:
    @transaction.atomic
    def persist_fetch_results(
        self,
        *,
        source: Source,
        fetch_run: SourceFetchRun,
        raw_results: list[RawFetchResult],
    ) -> list[RawItem]:
        persisted_items: list[RawItem] = []
        for result in raw_results:
            if not result.url:
                logger.warning("Skipping raw result without URL for source=%s", source.id)
                continue

            content_hash = build_raw_content_hash(
                result.url,
                result.title_raw,
                result.content_raw,
                result.html_raw,
            )
            raw_storage_key = self._store_html_snapshot(source_id=source.id, content_hash=content_hash, html=result.html_raw)
            raw_item, created = RawItem.objects.update_or_create(
                source=source,
                url=result.url,
                content_hash=content_hash,
                defaults={
                    "fetch_run": fetch_run,
                    "title_raw": result.title_raw,
                    "content_raw": result.content_raw,
                    "html_raw": result.html_raw,
                    "status": RawItem.Status.FETCHED,
                    "error_message": "",
                    "raw_storage_key": raw_storage_key,
                    "metadata": json_safe(
                        {
                            **result.metadata,
                            "published_at": result.published_at,
                            "author": result.author,
                            "image_url": result.image_url,
                        }
                    ),
                },
            )
            persisted_items.append(raw_item)
            logger.info(
                "Persisted raw item source_id=%s raw_item_id=%s created=%s",
                source.id,
                raw_item.id,
                created,
            )
        return persisted_items

    @transaction.atomic
    def create_or_update_article(
        self,
        *,
        raw_item: RawItem,
        parsed_candidate: ParsedArticleCandidate,
        normalized: dict,
    ) -> Article:
        article, _ = Article.objects.update_or_create(
            raw_item=raw_item,
            defaults={
                "source": raw_item.source,
                "parsed_candidate": parsed_candidate,
                "url": raw_item.url,
                "canonical_url": normalized["canonical_url"],
                "title": normalized["title"],
                "normalized_title": normalized["normalized_title"],
                "content": normalized["content"],
                "normalized_content": normalized["normalized_content"],
                "published_at": normalized["published_at"],
                "author": normalized["author"],
                "image_url": normalized["image_url"],
                "content_hash": normalized["content_hash"],
                "quality_score": normalized.get("quality_score", 0),
                "language": normalized.get("language", ""),
                "metadata": normalized["metadata"],
            },
        )
        raw_item.status = RawItem.Status.NORMALIZED
        raw_item.error_message = ""
        raw_item.save(update_fields=["status", "error_message", "updated_at"])

        parsed_candidate.status = ParsedArticleCandidate.Status.NORMALIZED
        parsed_candidate.error_message = ""
        parsed_candidate.save(update_fields=["status", "error_message", "updated_at"])
        return article

    def content_hash_for_article(self, title: str, content: str) -> str:
        basis = clean_text(title).lower() + "||" + clean_text(content).lower()
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def _store_html_snapshot(self, *, source_id: int, content_hash: str, html: str) -> str:
        if not html:
            return ""

        try:
            adapter = MinIOAdapter()
            object_name = f"sources/{source_id}/raw/{content_hash}.html"
            return adapter.store_raw(object_name, html, content_type="text/html")
        except Exception as exc:
            logger.warning("Failed to store raw HTML snapshot in MinIO: %s", exc)
            return ""
