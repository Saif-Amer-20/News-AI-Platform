from __future__ import annotations

import hashlib
import re
import unicodedata

from langdetect import detect as detect_lang

from services.integrations.common import clean_text, normalize_canonical_url, parse_datetime_value
from sources.models import ParsedArticleCandidate, RawItem

# Unicode range for Arabic tashkeel (diacritics) — stripped during normalization
_TASHKEEL_RE = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670"
    r"\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]"
)


class NormalizationService:
    def normalize_text(self, value: str, *, lowercase: bool = False) -> str:
        normalized = unicodedata.normalize("NFKC", clean_text(value))
        if self._looks_arabic(normalized):
            normalized = self._normalize_arabic(normalized)
        return normalized.lower() if lowercase else normalized

    def content_hash(self, title: str, content: str) -> str:
        basis = clean_text(title).lower() + "||" + clean_text(content).lower()
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def normalize(self, raw_item: RawItem, parsed_candidate: ParsedArticleCandidate) -> dict:
        title = self.normalize_text(parsed_candidate.title or raw_item.title_raw)
        content = self.normalize_text(parsed_candidate.content or raw_item.content_raw)
        language = self._detect_language(content)
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
            "language": language,
            "metadata": {
                **raw_item.metadata,
                "canonical_url": canonical_url,
            },
        }

    # ── Arabic helpers ────────────────────────────────────────

    @staticmethod
    def _looks_arabic(text: str) -> bool:
        if not text:
            return False
        arabic_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
        return arabic_chars > len(text) * 0.3

    @staticmethod
    def _normalize_arabic(text: str) -> str:
        # Alef variants → bare Alef
        text = text.replace("\u0623", "\u0627")  # أ → ا
        text = text.replace("\u0625", "\u0627")  # إ → ا
        text = text.replace("\u0622", "\u0627")  # آ → ا
        # Ta marbuta → Ha
        text = text.replace("\u0629", "\u0647")  # ة → ه
        # Alef maqsura → Ya
        text = text.replace("\u0649", "\u064A")  # ى → ي
        # Strip tashkeel (diacritics)
        text = _TASHKEEL_RE.sub("", text)
        return text

    @staticmethod
    def _detect_language(text: str) -> str:
        try:
            return detect_lang(text[:1000]) if len(text) >= 20 else ""
        except Exception:
            return ""
