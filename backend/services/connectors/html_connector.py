from __future__ import annotations

from typing import Iterable

import requests
from bs4 import BeautifulSoup

from services.integrations.common import (
    IntegrationError,
    RawFetchResult,
    absolutize_url,
    clean_text,
    parse_datetime_value,
)


class HTMLConnector:
    default_selectors = ("article", "main", "[role='main']", "body")

    def fetch(self, source) -> list[RawFetchResult]:
        mode = source.parser_config.get("mode", "auto")
        limit = int(source.parser_config.get("max_urls", 10))
        seed_urls = source.parser_config.get("seed_urls") or []
        base_url = source.fetch_url

        if seed_urls:
            candidate_urls = [absolutize_url(base_url, url) for url in seed_urls]
        elif mode == "article":
            candidate_urls = [base_url]
        else:
            listing_html = self._download(base_url, source.request_timeout_seconds)
            discovered = self._discover_article_urls(base_url, listing_html, source, limit)
            candidate_urls = discovered or [base_url]

        results: list[RawFetchResult] = []
        seen_urls: set[str] = set()
        for url in candidate_urls[:limit]:
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(self.fetch_article(url, source))

        if not results:
            raise IntegrationError(f"No HTML articles could be extracted for source '{source.name}'.")
        return results

    def fetch_article(self, url: str, source) -> RawFetchResult:
        html = self._download(url, source.request_timeout_seconds)
        return self.extract_raw_result(url, html, source=source)

    def extract_raw_result(self, url: str, html: str, *, source=None) -> RawFetchResult:
        soup = BeautifulSoup(html, "lxml")
        for node in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer"]):
            node.decompose()

        title = self._extract_title(soup)
        published_at = self._extract_published_at(soup)
        author = self._extract_author(soup)
        image_url = absolutize_url(url, self._extract_image_url(soup))
        content = self._extract_content(soup, source)

        return RawFetchResult(
            url=url,
            title_raw=title,
            content_raw=content,
            html_raw=html,
            published_at=published_at,
            author=author,
            image_url=image_url,
            metadata={
                "connector": "html",
                "published_at": published_at.isoformat() if published_at else "",
                "author": author,
                "image_url": image_url,
            },
        )

    def _download(self, url: str, timeout_seconds: int) -> str:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "NewsIntelBot/1.0"},
        )
        response.raise_for_status()
        return response.text

    def _discover_article_urls(self, base_url: str, html: str, source, limit: int) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        link_selector = source.parser_config.get("link_selector")
        if link_selector:
            links = [tag.get("href") for tag in soup.select(link_selector)]
        else:
            links = [tag.get("href") for tag in soup.select("article a[href], main a[href], body a[href]")]

        same_domain = []
        for href in links:
            resolved = absolutize_url(base_url, href)
            if not resolved.startswith("http"):
                continue
            if url_is_probably_article(resolved, base_url):
                same_domain.append(resolved)
            if len(same_domain) >= limit:
                break
        return same_domain

    def _extract_title(self, soup: BeautifulSoup) -> str:
        selectors = [
            "meta[property='og:title']",
            "meta[name='twitter:title']",
            "title",
            "h1",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            value = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
            if value:
                return clean_text(value)
        return ""

    def _extract_published_at(self, soup: BeautifulSoup):
        values: list[str] = []
        meta_candidates = [
            ("meta", "property", "article:published_time"),
            ("meta", "name", "pubdate"),
            ("meta", "name", "publishdate"),
            ("meta", "name", "date"),
            ("meta", "itemprop", "datePublished"),
        ]
        for tag_name, attr_name, attr_value in meta_candidates:
            node = soup.find(tag_name, attrs={attr_name: attr_value})
            if node:
                values.append(node.get("content") or node.get_text(" ", strip=True))

        time_node = soup.find("time")
        if time_node:
            values.append(time_node.get("datetime") or time_node.get_text(" ", strip=True))

        for value in values:
            parsed = parse_datetime_value(value)
            if parsed:
                return parsed
        return None

    def _extract_author(self, soup: BeautifulSoup) -> str:
        selectors = [
            "meta[name='author']",
            "meta[property='article:author']",
            "[rel='author']",
            ".author",
            "[itemprop='author']",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            value = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
            if value:
                return clean_text(value)
        return ""

    def _extract_image_url(self, soup: BeautifulSoup) -> str:
        selectors = [
            "meta[property='og:image']",
            "meta[name='twitter:image']",
            "article img",
            "main img",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            value = node.get("content") if node.name == "meta" else node.get("src")
            if value:
                return value
        return ""

    def _extract_content(self, soup: BeautifulSoup, source) -> str:
        selectors: Iterable[str] = source.parser_config.get("content_selectors") or self.default_selectors
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                text = clean_text(node.get_text(" ", strip=True))
                if text:
                    return text
        return clean_text(soup.get_text(" ", strip=True))


def url_is_probably_article(url: str, base_url: str) -> bool:
    if "#" in url:
        return False
    blocked_suffixes = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".xml")
    if url.lower().endswith(blocked_suffixes):
        return False
    return url.split("/")[2] == base_url.split("/")[2]
