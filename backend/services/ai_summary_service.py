"""AI-powered article summary and predictions service.

Uses Groq (OpenAI-compatible API) to generate comprehensive article
summaries with forward-looking predictions.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from sources.models import Article, ArticleAISummary

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert intelligence analyst and geopolitical forecaster. "
    "Given a news article, provide:\n\n"
    "1. **Comprehensive Summary**: A detailed, well-structured summary covering "
    "the key facts, actors involved, context, background, and significance of "
    "the news. Include who, what, where, when, why, and how.\n\n"
    "2. **Predictions & Forecast**: This is CRITICAL. Based on the information, "
    "provide detailed analytical predictions:\n"
    "   - What will likely happen next in the short term (days/weeks)?\n"
    "   - What are the medium-term consequences (months)?\n"
    "   - What are the potential long-term implications?\n"
    "   - Who will be most affected and how?\n"
    "   - What are the possible scenarios (best case, worst case, most likely)?\n"
    "   - What indicators should analysts watch for?\n"
    "   Be specific, analytical, and actionable. Do NOT be vague.\n\n"
    "Format your response EXACTLY as:\n"
    "## Summary\n<your summary here>\n\n"
    "## Predictions\n<your predictions here>\n\n"
    "Write in the same language as the article. Be thorough."
)


def generate_ai_summary(article: Article) -> ArticleAISummary:
    """Return an existing or newly-generated AI summary for *article*.

    If a completed summary already exists it is returned immediately.
    Otherwise a new one is created via the Groq API.
    """
    existing = ArticleAISummary.objects.filter(
        article=article,
        status=ArticleAISummary.Status.COMPLETED,
    ).first()
    if existing:
        return existing

    summary_obj, _created = ArticleAISummary.objects.get_or_create(
        article=article,
        defaults={"status": ArticleAISummary.Status.PENDING},
    )

    if summary_obj.status == ArticleAISummary.Status.COMPLETED:
        return summary_obj

    # Reset if previously failed
    summary_obj.status = ArticleAISummary.Status.PENDING
    summary_obj.error_message = ""
    summary_obj.save(update_fields=["status", "error_message", "updated_at"])

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        summary_obj.status = ArticleAISummary.Status.FAILED
        summary_obj.error_message = "GROQ_API_KEY not configured."
        summary_obj.save(update_fields=["status", "error_message", "updated_at"])
        return summary_obj

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )

        # Build article text for the prompt
        title = article.title or ""
        content = article.content or article.normalized_content or ""
        # Truncate to ~6000 chars to stay within token limits
        if len(content) > 6000:
            content = content[:6000] + "..."

        user_message = f"**Title:** {title}\n\n**Content:**\n{content}"

        model_name = "llama-3.3-70b-versatile"
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=2000,
            temperature=0.4,
        )

        result_text = response.choices[0].message.content or ""

        # Parse the structured response
        summary_text, predictions_text = _parse_response(result_text)

        summary_obj.summary = summary_text
        summary_obj.predictions = predictions_text
        summary_obj.model_used = model_name
        summary_obj.status = ArticleAISummary.Status.COMPLETED
        summary_obj.generated_at = timezone.now()

        # Auto-translate to Arabic
        summary_ar, predictions_ar = _translate_to_arabic(summary_text, predictions_text)
        summary_obj.summary_ar = summary_ar
        summary_obj.predictions_ar = predictions_ar

        summary_obj.save(update_fields=[
            "summary", "predictions", "summary_ar", "predictions_ar",
            "model_used", "status", "generated_at", "updated_at",
        ])
        logger.info("Generated AI summary for article %d", article.id)

    except Exception as exc:
        summary_obj.status = ArticleAISummary.Status.FAILED
        summary_obj.error_message = str(exc)[:500]
        summary_obj.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("AI summary failed for article %d: %s", article.id, exc)

    return summary_obj


def _parse_response(text: str) -> tuple[str, str]:
    """Split the LLM response into (summary, predictions) sections."""
    summary = ""
    predictions = ""

    lower = text.lower()
    sum_idx = lower.find("## summary")
    pred_idx = lower.find("## predictions")

    if sum_idx != -1 and pred_idx != -1:
        # Both sections found
        summary_start = text.index("\n", sum_idx) + 1
        summary = text[summary_start:pred_idx].strip()
        predictions_start = text.index("\n", pred_idx) + 1
        predictions = text[predictions_start:].strip()
    elif sum_idx != -1:
        summary_start = text.index("\n", sum_idx) + 1
        summary = text[summary_start:].strip()
    elif pred_idx != -1:
        predictions_start = text.index("\n", pred_idx) + 1
        predictions = text[predictions_start:].strip()
        summary = text[:pred_idx].strip()
    else:
        # No headers found — treat entire text as summary
        summary = text.strip()

    return summary, predictions


def _translate_to_arabic(summary: str, predictions: str) -> tuple[str, str]:
    """Translate summary and predictions to Arabic using Google Translate."""
    try:
        from deep_translator import GoogleTranslator

        translator = GoogleTranslator(source="auto", target="ar")

        summary_ar = ""
        if summary:
            chunks = _chunk_text(summary, 4500)
            parts = [translator.translate(c) or "" for c in chunks]
            summary_ar = "\n\n".join(p for p in parts if p)

        predictions_ar = ""
        if predictions:
            chunks = _chunk_text(predictions, 4500)
            parts = [translator.translate(c) or "" for c in chunks]
            predictions_ar = "\n\n".join(p for p in parts if p)

        return summary_ar, predictions_ar
    except Exception as exc:
        logger.warning("Arabic translation of AI summary failed: %s", exc)
        return "", ""


def _chunk_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks, preferring paragraph boundaries."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue
        if len(paragraph) <= max_len:
            chunks.append(paragraph)
        else:
            for i in range(0, len(paragraph), max_len):
                chunks.append(paragraph[i:i + max_len])
    return chunks
