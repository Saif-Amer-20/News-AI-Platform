"""Scrapy item ingestion adapter."""

from __future__ import annotations

from .common import RawFetchResult, parse_datetime_value


class ScrapyIngestionAdapter:
    def transform_item(self, payload: dict) -> RawFetchResult:
        return RawFetchResult(
            url=payload.get("url", ""),
            title_raw=payload.get("title_raw") or payload.get("title", ""),
            content_raw=payload.get("content_raw") or payload.get("content", ""),
            html_raw=payload.get("html_raw") or payload.get("html", ""),
            published_at=parse_datetime_value(payload.get("published_at")),
            author=payload.get("author", ""),
            image_url=payload.get("image_url", ""),
            metadata={
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "url",
                    "title_raw",
                    "title",
                    "content_raw",
                    "content",
                    "html_raw",
                    "html",
                    "published_at",
                    "author",
                    "image_url",
                }
            },
        )
