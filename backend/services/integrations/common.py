"""Common types and helpers for integration adapters."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)


class IntegrationError(Exception):
    """Raised when an external integration call fails."""


class BaseAdapter:
    """Base class for stateless external-system adapters."""

    service_name: str = "unknown"

    def _log_call(self, method: str, **kwargs):
        logger.debug("[%s] %s called with %s", self.service_name, method, kwargs)


@dataclass(slots=True)
class RawFetchResult:
    url: str
    title_raw: str = ""
    content_raw: str = ""
    html_raw: str = ""
    published_at: datetime | None = None
    author: str = ""
    image_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript", "svg", "iframe"]):
        node.decompose()
    return clean_text(soup.get_text(" ", strip=True))


def parse_datetime_value(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, struct_time):
        return datetime(*value[:6])
    if isinstance(value, str):
        try:
            return date_parser.parse(value)
        except (ValueError, TypeError, OverflowError):
            try:
                return parsedate_to_datetime(value)
            except (TypeError, ValueError, IndexError):
                return None
    return None


def normalize_canonical_url(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower()
        not in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
    ]
    path = parsed.path.rstrip("/") or parsed.path or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def build_raw_content_hash(url: str, title: str, content: str, html: str) -> str:
    basis = "||".join(
        [
            normalize_canonical_url(url),
            clean_text(title),
            clean_text(content),
            clean_text(html_to_text(html)),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def absolutize_url(base_url: str, maybe_relative_url: str | None) -> str:
    if not maybe_relative_url:
        return ""
    return urljoin(base_url, maybe_relative_url)
