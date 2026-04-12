from __future__ import annotations

import hashlib
import unicodedata

from services.integrations.common import clean_text, normalize_canonical_url, parse_datetime_value
from sources.models import ParsedArticleCandidate, RawItem


class NormalizationService:
    def normalize_text(self, value: str, *, lowercase: bool = False) -> str:
        normalized = unicodedata.normalize("NFKC", clean_text(value))
        return normalized.lower() if lowercase else normalized

    def content_hash(self, title: str, content: str) -> str:
        basis = clean_text(title).lower() + "||" + clean_text(content).lower()
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def normalize(self, raw_item: RawItem, parsed_candidate: ParsedArticleCandidate) -> dict:
        title = self.normalize_text(parsed_candidate.title or raw_item.title_raw)
        content = self.normalize_text(parsed_candidate.content or raw_item.content_raw)
        normalized_title = self.normalize_text(title, lowercase=True)
        normalized_content = self.normalize_text(content, lowercase=True)
        canonical_url = normalize_canonical_url(raw_item.url)
        published_at = parsed_candidate.published_at or parse_datetime_value(
            raw_item.metadata.get("published_at")
        )

        return {
            "title": title,
            "normalized_title": normalized_title,
            "content": content,
            "normalized_content": normalized_content,
            "canonical_url": canonical_url,
            "published_at": published_at,
            "author": parsed_candidate.author or "",
            "image_url": parsed_candidate.image_url or "",
            "content_hash": self.content_hash(title, content),
            "metadata": {
                **raw_item.metadata,
                "canonical_url": canonical_url,
            },
        }
