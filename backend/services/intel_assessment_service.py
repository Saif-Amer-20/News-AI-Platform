"""Intelligence assessment service for events.

Gathers all articles/stories for an event, performs cross-source claim
comparison, calls Groq LLM for analyst-level assessment, computes
credibility scores, and generates probabilistic forecasts.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from sources.models import Article, Event, EventIntelAssessment

logger = logging.getLogger(__name__)

ASSESSMENT_PROMPT = (
    "You are a senior intelligence analyst. You will receive ALL articles "
    "from multiple news sources covering the same event. Your job is to "
    "produce a professional intelligence assessment.\n\n"
    "For each task below, be **specific**, cite source names, and avoid vague "
    "statements.\n\n"
    "## TASKS\n\n"
    "### 1. Claims Extraction\n"
    "List every distinct factual claim made across all articles. For each "
    "claim state which source(s) reported it and whether other sources "
    "agree, contradict, or omit it.\n\n"
    "### 2. Contradiction Analysis\n"
    "Identify pairs of claims that directly contradict each other. Explain "
    "the contradiction and which sources are on each side.\n\n"
    "### 3. Summary\n"
    "Write a concise but comprehensive summary of what happened.\n\n"
    "### 4. Source Agreement\n"
    "How much do the sources agree? What is the dominant narrative and "
    "where do accounts diverge?\n\n"
    "### 5. Dominant Narrative\n"
    "Describe the dominant narrative across sources.\n\n"
    "### 6. Uncertain Elements\n"
    "List facts that only one source mentions or that are contested.\n\n"
    "### 7. Analyst Reasoning\n"
    "Provide your analytical reasoning about the event's veracity and "
    "significance. What does an experienced analyst notice?\n\n"
    "### 8. Credibility Assessment\n"
    "Rate overall credibility (0.0-1.0) and explain why.\n\n"
    "### 9. Predictions\n"
    "Provide probabilistic forecasts:\n"
    "- escalation_probability (0-1): Will the situation escalate?\n"
    "- continuation_probability (0-1): Will the event continue developing?\n"
    "- hidden_link_probability (0-1): Are there hidden connections?\n"
    "- monitoring_recommendation: What should analysts watch for?\n\n"
    "## OUTPUT FORMAT (JSON)\n"
    "Respond ONLY with valid JSON, no markdown code fences:\n"
    "{\n"
    '  "claims": [{"claim": "...", "sources": ["src1"], "status": "agreed|contradicted|unique"}],\n'
    '  "agreements": ["Sources X and Y agree that ..."],\n'
    '  "contradictions": [{"claim_a": "...", "source_a": "...", "claim_b": "...", "source_b": "..."}],\n'
    '  "missing_details": ["Only Source X mentions ..."],\n'
    '  "late_emerging_claims": ["Source Z later added ..."],\n'
    '  "summary": "...",\n'
    '  "source_agreement_summary": "...",\n'
    '  "dominant_narrative": "...",\n'
    '  "uncertain_elements": "...",\n'
    '  "analyst_reasoning": "...",\n'
    '  "credibility_score": 0.75,\n'
    '  "escalation_probability": 0.3,\n'
    '  "continuation_probability": 0.6,\n'
    '  "hidden_link_probability": 0.1,\n'
    '  "monitoring_recommendation": "..."\n'
    "}\n"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_intel_assessment(event: Event) -> EventIntelAssessment:
    """Generate or return an existing intelligence assessment for *event*."""

    existing = EventIntelAssessment.objects.filter(
        event=event,
        status=EventIntelAssessment.Status.COMPLETED,
    ).first()
    if existing:
        return existing

    obj, _created = EventIntelAssessment.objects.get_or_create(
        event=event,
        defaults={"status": EventIntelAssessment.Status.PENDING},
    )

    if obj.status == EventIntelAssessment.Status.COMPLETED:
        return obj

    # Reset if previously failed
    obj.status = EventIntelAssessment.Status.PENDING
    obj.error_message = ""
    obj.save(update_fields=["status", "error_message", "updated_at"])

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        obj.status = EventIntelAssessment.Status.FAILED
        obj.error_message = "GROQ_API_KEY not configured."
        obj.save(update_fields=["status", "error_message", "updated_at"])
        return obj

    try:
        # 1. Gather articles via stories
        articles = _gather_articles(event)
        if not articles:
            obj.status = EventIntelAssessment.Status.FAILED
            obj.error_message = "No articles found for this event."
            obj.save(update_fields=["status", "error_message", "updated_at"])
            return obj

        # 2. Build diffusion layer (coverage stats)
        _populate_diffusion(obj, event, articles)

        # 3. Build user prompt from articles
        user_msg = _build_user_prompt(event, articles)

        # 4. Call LLM
        parsed = _call_llm(api_key, user_msg)

        # 5. Populate cross-source comparison
        obj.claims = parsed.get("claims", [])
        obj.agreements = parsed.get("agreements", [])
        obj.contradictions = parsed.get("contradictions", [])
        obj.missing_details = parsed.get("missing_details", [])
        obj.late_emerging_claims = parsed.get("late_emerging_claims", [])

        # 6. Populate AI assessment text
        obj.summary = parsed.get("summary", "")
        obj.source_agreement_summary = parsed.get("source_agreement_summary", "")
        obj.dominant_narrative = parsed.get("dominant_narrative", "")
        obj.uncertain_elements = parsed.get("uncertain_elements", "")
        obj.analyst_reasoning = parsed.get("analyst_reasoning", "")

        # 7. Credibility & predictions
        obj.credibility_score = _safe_decimal(parsed.get("credibility_score", 0))
        obj.confidence_score = _compute_confidence(obj, articles)
        obj.verification_status = _derive_verification_status(obj.credibility_score)
        obj.credibility_factors = _build_credibility_factors(obj, articles)

        obj.escalation_probability = _safe_decimal(parsed.get("escalation_probability", 0))
        obj.continuation_probability = _safe_decimal(parsed.get("continuation_probability", 0))
        obj.hidden_link_probability = _safe_decimal(parsed.get("hidden_link_probability", 0))
        obj.monitoring_recommendation = parsed.get("monitoring_recommendation", "")
        obj.forecast_signals = {
            "escalation": float(obj.escalation_probability),
            "continuation": float(obj.continuation_probability),
            "hidden_links": float(obj.hidden_link_probability),
        }

        obj.model_used = "llama-3.3-70b-versatile"
        obj.status = EventIntelAssessment.Status.COMPLETED
        obj.generated_at = timezone.now()

        # 8. Arabic translation
        _translate_fields(obj)

        obj.save()
        logger.info("Intel assessment generated for event %d", event.id)

    except Exception as exc:
        obj.status = EventIntelAssessment.Status.FAILED
        obj.error_message = str(exc)[:500]
        obj.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("Intel assessment failed for event %d: %s", event.id, exc)

    return obj


def regenerate_intel_assessment(event: Event) -> EventIntelAssessment:
    """Force-regenerate the assessment by deleting any existing one."""
    EventIntelAssessment.objects.filter(event=event).delete()
    return generate_intel_assessment(event)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _gather_articles(event: Event) -> list[Article]:
    """Collect all articles linked to the event via its stories."""
    story_ids = event.stories.values_list("id", flat=True)
    return list(
        Article.objects.filter(story_id__in=story_ids)
        .select_related("source")
        .order_by("published_at")
    )


def _populate_diffusion(
    obj: EventIntelAssessment,
    event: Event,
    articles: list[Article],
) -> None:
    """Fill story-diffusion fields: coverage count, source spread, timeline."""
    obj.coverage_count = len(articles)

    sources_map: dict[int, dict] = {}
    timeline = []
    for art in articles:
        src = art.source
        if src and src.id not in sources_map:
            sources_map[src.id] = {
                "source_id": src.id,
                "name": src.name,
                "trust": float(src.trust_score or 0),
                "country": src.country or "",
                "articles": 0,
                "first": None,
                "last": None,
            }
        if src:
            entry = sources_map[src.id]
            entry["articles"] += 1
            pub = art.published_at.isoformat() if art.published_at else None
            if pub:
                if entry["first"] is None or pub < entry["first"]:
                    entry["first"] = pub
                if entry["last"] is None or pub > entry["last"]:
                    entry["last"] = pub

        timeline.append({
            "ts": art.published_at.isoformat() if art.published_at else "",
            "source": src.name if src else "Unknown",
            "article_id": art.id,
            "title": (art.title or "")[:120],
        })

    obj.distinct_source_count = len(sources_map)
    obj.source_list = list(sources_map.values())
    obj.publication_timeline = timeline

    # Article link list
    obj.article_links = [
        {
            "id": a.id,
            "title": (a.title or "")[:120],
            "url": a.url or "",
            "source": a.source.name if a.source else "Unknown",
            "published_at": a.published_at.isoformat() if a.published_at else "",
        }
        for a in articles
    ]

    timestamps = [a.published_at for a in articles if a.published_at]
    obj.first_seen = min(timestamps) if timestamps else None
    obj.last_seen = max(timestamps) if timestamps else None


def _build_user_prompt(event: Event, articles: list[Article]) -> str:
    """Format event info + all articles into a single user message."""
    parts = [
        f"EVENT: {event.title}",
        f"TYPE: {event.get_event_type_display() if hasattr(event, 'get_event_type_display') else event.event_type}",
        f"LOCATION: {event.location_name or 'N/A'}, {event.location_country or 'N/A'}",
        f"TOTAL ARTICLES: {len(articles)}",
        "",
        "=" * 60,
    ]

    # Limit total text length for the LLM context window
    char_budget = 12000
    chars_used = 0

    for i, art in enumerate(articles, 1):
        src_name = art.source.name if art.source else "Unknown"
        title = art.title or "No title"
        body = art.content or art.normalized_content or ""
        if len(body) > 2000:
            body = body[:2000] + "..."

        block = (
            f"\n--- ARTICLE {i} [{src_name}] ---\n"
            f"Title: {title}\n"
            f"Published: {art.published_at.isoformat() if art.published_at else 'N/A'}\n"
            f"Body:\n{body}\n"
        )

        if chars_used + len(block) > char_budget:
            parts.append(f"\n... ({len(articles) - i + 1} more articles omitted for brevity)")
            break
        parts.append(block)
        chars_used += len(block)

    return "\n".join(parts)


def _call_llm(api_key: str, user_msg: str) -> dict:
    """Call Groq API and parse the JSON response."""
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": ASSESSMENT_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4000,
        temperature=0.3,
    )

    raw = response.choices[0].message.content or "{}"

    # Strip possible markdown code fences
    raw = raw.strip()
    if raw.startswith("```"):
        first_nl = raw.index("\n") if "\n" in raw else 3
        raw = raw[first_nl + 1 :]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON, attempting recovery.")
        # Try to find a JSON object in the response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass
        return {"summary": raw, "analyst_reasoning": "JSON parse failure — raw text preserved."}


def _safe_decimal(val, default="0.00") -> Decimal:
    """Convert a value to Decimal, clamping to [0, 1]."""
    try:
        d = Decimal(str(val))
        return max(Decimal("0.00"), min(Decimal("1.00"), d))
    except Exception:
        return Decimal(default)


def _compute_confidence(obj: EventIntelAssessment, articles: list[Article]) -> Decimal:
    """Algorithmic confidence in our credibility score."""
    factors = []
    # More sources → higher confidence
    src_count = obj.distinct_source_count
    if src_count >= 5:
        factors.append(Decimal("0.30"))
    elif src_count >= 3:
        factors.append(Decimal("0.20"))
    elif src_count >= 2:
        factors.append(Decimal("0.10"))

    # More articles → higher confidence
    if obj.coverage_count >= 10:
        factors.append(Decimal("0.25"))
    elif obj.coverage_count >= 5:
        factors.append(Decimal("0.15"))
    elif obj.coverage_count >= 2:
        factors.append(Decimal("0.07"))

    # Few contradictions → higher confidence
    contradiction_count = len(obj.contradictions) if isinstance(obj.contradictions, list) else 0
    if contradiction_count == 0:
        factors.append(Decimal("0.25"))
    elif contradiction_count <= 2:
        factors.append(Decimal("0.10"))

    # Time span — longer coverage → more data
    if obj.first_seen and obj.last_seen:
        span = (obj.last_seen - obj.first_seen).total_seconds()
        if span >= 86400:  # 24 h
            factors.append(Decimal("0.20"))
        elif span >= 3600:
            factors.append(Decimal("0.10"))

    return min(sum(factors), Decimal("1.00"))


def _derive_verification_status(credibility: Decimal) -> str:
    """Map credibility score to a verification status label."""
    if credibility >= Decimal("0.85"):
        return EventIntelAssessment.VerificationStatus.VERIFIED
    if credibility >= Decimal("0.65"):
        return EventIntelAssessment.VerificationStatus.LIKELY_TRUE
    if credibility >= Decimal("0.45"):
        return EventIntelAssessment.VerificationStatus.MIXED
    if credibility >= Decimal("0.25"):
        return EventIntelAssessment.VerificationStatus.UNVERIFIED
    return EventIntelAssessment.VerificationStatus.LIKELY_MISLEADING


def _build_credibility_factors(obj: EventIntelAssessment, articles: list[Article]) -> dict:
    """Break down how the credibility score is composed."""
    return {
        "source_diversity": obj.distinct_source_count,
        "coverage_volume": obj.coverage_count,
        "contradiction_count": len(obj.contradictions) if isinstance(obj.contradictions, list) else 0,
        "agreement_count": len(obj.agreements) if isinstance(obj.agreements, list) else 0,
        "time_span_hours": (
            round((obj.last_seen - obj.first_seen).total_seconds() / 3600, 1)
            if obj.first_seen and obj.last_seen
            else 0
        ),
    }


def _translate_fields(obj: EventIntelAssessment) -> None:
    """Translate assessment text fields to Arabic."""
    try:
        from deep_translator import GoogleTranslator

        translator = GoogleTranslator(source="auto", target="ar")

        fields = [
            ("summary", "summary_ar"),
            ("source_agreement_summary", "source_agreement_summary_ar"),
            ("dominant_narrative", "dominant_narrative_ar"),
            ("uncertain_elements", "uncertain_elements_ar"),
            ("analyst_reasoning", "analyst_reasoning_ar"),
            ("contradiction_summary", "contradiction_summary_ar"),
        ]

        for src_field, dst_field in fields:
            text = getattr(obj, src_field, "") or ""
            if text:
                chunks = _chunk_text(text, 4500)
                parts = [translator.translate(c) or "" for c in chunks]
                setattr(obj, dst_field, "\n\n".join(p for p in parts if p))
    except Exception as exc:
        logger.warning("Arabic translation of intel assessment failed: %s", exc)


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
                chunks.append(paragraph[i : i + max_len])
    return chunks
