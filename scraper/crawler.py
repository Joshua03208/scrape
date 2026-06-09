"""Breadth-first, polite, in-domain crawler.

Responsibilities:
* keep a frontier of URLs to visit and a set of already-seen URLs;
* discover new links from each page's HTML;
* stay within the configured domains and link patterns;
* honour robots.txt and a per-request delay.

The crawler yields ``(url, html)`` pairs; extraction happens elsewhere.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Iterator
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from .config import SiteConfig
from .fetcher import Fetcher


def normalize_url(url: str) -> str:
    """Drop the fragment and trailing slash noise so we dedupe reliably."""
    url, _frag = urldefrag(url)
    if url.endswith("/") and url.count("/") > 3:
        url = url.rstrip("/")
    return url


class Crawler:
    def __init__(self, config: SiteConfig, fetcher: Fetcher) -> None:
        self.config = config
        self.fetcher = fetcher
        self.seen: set[str] = set()
        self._robots: dict[str, RobotFileParser] = {}

    # -- robots.txt -------------------------------------------------------
    def _robots_for(self, url: str) -> RobotFileParser | None:
        if not self.config.respect_robots:
            return None
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            rp.set_url(urljoin(base, "/robots.txt"))
            try:
                rp.read()
            except Exception:
                # If robots.txt is unreachable, default to permissive but quiet.
                rp = RobotFileParser()
                rp.parse([])
            self._robots[base] = rp
        return self._robots[base]

    def _allowed_by_robots(self, url: str) -> bool:
        rp = self._robots_for(url)
        if rp is None:
            return True
        return rp.can_fetch(self.config.user_agent, url)

    # -- link filtering ---------------------------------------------------
    def _in_domain(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return any(
            host == d.lower() or host.endswith("." + d.lower())
            for d in self.config.allowed_domains
        )

    def _should_follow(self, url: str) -> bool:
        if urlparse(url).scheme not in ("http", "https"):
            return False
        if not self._in_domain(url):
            return False
        path = urlparse(url).path
        crawl = self.config.crawl
        if any(pat in url or pat in path for pat in crawl.ignore_link_patterns):
            return False
        if crawl.follow_link_patterns:
            return any(pat in url or pat in path for pat in crawl.follow_link_patterns)
        return True

    def _extract_links(self, base_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            absolute = normalize_url(urljoin(base_url, a["href"]))
            links.append(absolute)
        return links

    # -- main loop --------------------------------------------------------
    def crawl(self) -> Iterator[tuple[str, str]]:
        """Yield ``(url, html)`` for every successfully fetched page."""
        frontier: deque[str] = deque(
            normalize_url(u) for u in self.config.start_urls
        )
        pages_fetched = 0

        while frontier and pages_fetched < self.config.max_pages:
            url = frontier.popleft()
            if url in self.seen:
                continue
            self.seen.add(url)

            if not self._allowed_by_robots(url):
                continue

            result = self.fetcher.fetch(url)
            if self.config.delay_seconds:
                time.sleep(self.config.delay_seconds)
            if not result.ok or not result.html:
                continue

            pages_fetched += 1
            yield result.url, result.html

            priority = self.config.crawl.priority_link_patterns
            for link in self._extract_links(result.url, result.html):
                if link in self.seen or not self._should_follow(link):
                    continue
                # Priority links (e.g. product pages) jump to the front so we
                # scrape real products before exhausting search pagination.
                if priority and any(p in link for p in priority):
                    frontier.appendleft(link)
                else:
                    frontier.append(link)
