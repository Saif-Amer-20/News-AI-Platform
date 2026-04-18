"""Article translation service.

Translates article title and body into a target language, persisting the
result in ArticleTranslation.  Uses deep-translator (Google Translate)
as the default provider.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from sources.models import Article, ArticleTranslation

logger = logging.getLogger(__name__)


def translate_article(article: Article, target_language: str = "ar") -> ArticleTranslation:
    """Return an existing or newly-created translation for *article*.

    If a completed translation already exists it is returned immediately.
    If the article is already in the target language, skip translation
    and copy the content directly.
    Otherwise a new one is created, the translation is performed, and the
    result is persisted.
    """
    # Skip translation if article is already in the target language
    article_lang = getattr(article, "language", "") or ""
    if article_lang and article_lang.startswith(target_language):
        translation, _ = ArticleTranslation.objects.get_or_create(
            article=article,
            language_code=target_language,
            defaults={
                "translated_title": article.title or "",
                "translated_body": article.content or article.normalized_content or "",
                "translation_status": ArticleTranslation.TranslationStatus.COMPLETED,
                "translated_at": timezone.now(),
                "provider": "skip-same-language",
            },
        )
        if translation.translation_status == ArticleTranslation.TranslationStatus.COMPLETED:
            return translation

    existing = ArticleTranslation.objects.filter(
        article=article,
        language_code=target_language,
        translation_status=ArticleTranslation.TranslationStatus.COMPLETED,
    ).first()
    if existing:
        return existing

    translation, _created = ArticleTranslation.objects.get_or_create(
        article=article,
        language_code=target_language,
        defaults={"translation_status": ArticleTranslation.TranslationStatus.PENDING},
    )

    if translation.translation_status == ArticleTranslation.TranslationStatus.COMPLETED:
        return translation

    # Reset if previously failed
    translation.translation_status = ArticleTranslation.TranslationStatus.PENDING
    translation.error_message = ""
    translation.save(update_fields=["translation_status", "error_message", "updated_at"])

    try:
        from deep_translator import GoogleTranslator

        translator = GoogleTranslator(source="auto", target=target_language)

        translated_title = ""
        if article.title:
            translated_title = translator.translate(article.title[:4500]) or ""

        body_source = article.content or article.normalized_content or ""
        translated_body = ""
        if body_source:
            # Google Translate has a 5000 char limit per request; chunk if needed
            chunks = _chunk_text(body_source, 4500)
            parts = []
            for chunk in chunks:
                part = translator.translate(chunk)
                if part:
                    parts.append(part)
            translated_body = "\n\n".join(parts)

        translation.translated_title = translated_title
        translation.translated_body = translated_body
        translation.translation_status = ArticleTranslation.TranslationStatus.COMPLETED
        translation.translated_at = timezone.now()
        translation.provider = "google"
        translation.save(update_fields=[
            "translated_title", "translated_body", "translation_status",
            "translated_at", "provider", "updated_at",
        ])
        logger.info("Translated article %d to %s", article.id, target_language)

    except Exception as exc:
        translation.translation_status = ArticleTranslation.TranslationStatus.FAILED
        translation.error_message = str(exc)[:2000]
        translation.save(update_fields=["translation_status", "error_message", "updated_at"])
        logger.exception("Translation failed for article %d to %s", article.id, target_language)

    return translation


def _chunk_text(text: str, max_len: int) -> list[str]:
    """Split *text* into chunks of at most *max_len* characters,
    preferring to split on paragraph boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue
        if len(paragraph) <= max_len:
            chunks.append(paragraph)
        else:
            # Force-split long paragraphs on sentence-ish boundaries
            while len(paragraph) > max_len:
                split_at = paragraph.rfind(". ", 0, max_len)
                if split_at == -1:
                    split_at = max_len
                else:
                    split_at += 2  # include the ". "
                chunks.append(paragraph[:split_at])
                paragraph = paragraph[split_at:]
            if paragraph.strip():
                chunks.append(paragraph)
    return chunks
