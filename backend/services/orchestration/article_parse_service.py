"""Article parse service — extracts structured content from a RawItem."""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup
from django.db import transaction

from services.integrations.common import clean_text, html_to_text, parse_datetime_value
from sources.models import ParsedArticleCandidate, RawItem

logger = logging.getLogger(__name__)


class ArticleParseService:
    """Parses a single RawItem into a ParsedArticleCandidate.

    Idempotent: re-running on an already-parsed item returns the existing candidate.
    """

    @transaction.atomic
    def parse(self, raw_item: RawItem) -> ParsedArticleCandidate:
        # Idempotency: return existing non-failed candidate
        existing = ParsedArticleCandidate.objects.filter(raw_item=raw_item).first()
        if existing and existing.status != ParsedArticleCandidate.Status.FAILED:
            return existing

        try:
            if raw_item.html_raw:
                title, content, published_at, author, image_url = self._parse_html(raw_item)
            else:
                title, content, published_at, author, image_url = self._parse_text(raw_item)

            candidate, _ = ParsedArticleCandidate.objects.update_or_create(
                raw_item=raw_item,
                defaults={
                    "title": title[:500] if title else "",
                    "content": content,
                    "published_at": published_at,
                    "author": (author or "")[:255],
                    "image_url": image_url or "",
                    "status": ParsedArticleCandidate.Status.PARSED,
                    "error_message": "",
                    "metadata": raw_item.metadata,
                },
            )

            raw_item.status = RawItem.Status.PARSED
            raw_item.error_message = ""
            raw_item.save(update_fields=["status", "error_message", "updated_at"])
            logger.info("Parsed raw_item %s → candidate %s", raw_item.id, candidate.id)
            return candidate

        except Exception as exc:
            ParsedArticleCandidate.objects.update_or_create(
                raw_item=raw_item,
                defaults={
                    "status": ParsedArticleCandidate.Status.FAILED,
                    "error_message": str(exc)[:1000],
                },
            )
            raw_item.status = RawItem.Status.FAILED
            raw_item.error_message = str(exc)[:1000]
            raw_item.save(update_fields=["status", "error_message", "updated_at"])
            logger.exception("Parse failed for raw_item %s", raw_item.id)
            raise

    # ── HTML-based extraction ─────────────────────────────────────────

    def _parse_html(self, raw_item: RawItem):
        soup = BeautifulSoup(raw_item.html_raw, "lxml")

        title = self._extract_title_from_soup(soup) or clean_text(raw_item.title_raw)
        content = self._extract_content_from_soup(soup) or clean_text(raw_item.content_raw) or html_to_text(raw_item.html_raw)
        published_at = self._extract_published_from_soup(soup) or parse_datetime_value(raw_item.metadata.get("published_at"))
        author = self._extract_author_from_soup(soup) or clean_text(raw_item.metadata.get("author"))
        image_url = self._extract_image_from_soup(soup) or raw_item.metadata.get("image_url", "")

        return title, content, published_at, author, image_url

    def _parse_text(self, raw_item: RawItem):
        title = clean_text(raw_item.title_raw)
        content = clean_text(raw_item.content_raw)
        published_at = parse_datetime_value(raw_item.metadata.get("published_at"))
        author = clean_text(raw_item.metadata.get("author"))
        image_url = raw_item.metadata.get("image_url", "")

        return title, content, published_at, author, image_url

    # ── Soup extraction helpers ───────────────────────────────────────

    @staticmethod
    def _extract_title_from_soup(soup: BeautifulSoup) -> str:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        return ""

    @staticmethod
    def _extract_content_from_soup(soup: BeautifulSoup) -> str:
        for tag in soup.find_all(["script", "style", "nav", "aside", "footer", "header", "form"]):
            tag.decompose()
        article = soup.find("article")
        container = article if article else soup.find("body")
        if container:
            paragraphs = container.find_all("p")
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            if text:
                return text
        return ""

    @staticmethod
    def _extract_published_from_soup(soup: BeautifulSoup):
        meta = soup.find("meta", property="article:published_time")
        if meta and meta.get("content"):
            return parse_datetime_value(meta["content"])
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag:
            return parse_datetime_value(time_tag["datetime"])
        return None

    @staticmethod
    def _extract_author_from_soup(soup: BeautifulSoup) -> str:
        meta = soup.find("meta", attrs={"name": "author"})
        if meta and meta.get("content"):
            return meta["content"].strip()
        author_tag = soup.find(attrs={"class": re.compile(r"author", re.I)})
        if author_tag:
            return author_tag.get_text(strip=True)
        return ""

    @staticmethod
    def _extract_image_from_soup(soup: BeautifulSoup) -> str:
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"].strip()
        return ""
