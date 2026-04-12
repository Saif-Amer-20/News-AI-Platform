from __future__ import annotations

from xml.etree import ElementTree

import requests

from services.integrations.common import IntegrationError

from .html_connector import HTMLConnector


class SitemapConnector:
    def __init__(self):
        self.html_connector = HTMLConnector()

    def fetch(self, source):
        response = requests.get(
            source.fetch_url,
            timeout=source.request_timeout_seconds,
            headers={"User-Agent": "NewsIntelBot/1.0"},
        )
        response.raise_for_status()
        urls = self._extract_urls(response.text)
        if not urls:
            raise IntegrationError(f"Sitemap '{source.fetch_url}' returned no URLs.")

        max_urls = int(source.parser_config.get("max_urls", 10))
        return [self.html_connector.fetch_article(url, source) for url in urls[:max_urls]]

    def _extract_urls(self, xml_payload: str) -> list[str]:
        root = ElementTree.fromstring(xml_payload)
        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        return [
            node.text.strip()
            for node in root.findall(f".//{namespace}loc")
            if node.text and node.text.strip()
        ]
