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
from urllib.parse import (
    parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse,
)
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

    # -- pagination -------------------------------------------------------
    def _page_number(self, url: str, param: str) -> int | None:
        for k, v in parse_qsl(urlparse(url).query):
            if k == param:
                try:
                    return int(v)
                except ValueError:
                    return None
        return None

    def _expand_pagination(self, url: str, links: list[str]) -> list[str]:
        """For a listing page, synthesise links to every page 1..last.

        A site's pager usually only links to a few nearby pages plus the last
        one, so plain link-following skips the middle. We read the highest page
        number visible (including the last-page link) and generate them all.
        """
        crawl = self.config.crawl
        if not crawl.auto_paginate:
            return []
        # Only expand on the listing pages themselves.
        if crawl.follow_link_patterns and not any(
            p in url for p in crawl.follow_link_patterns
        ):
            return []
        param = crawl.page_param

        # Highest page number among sibling listing links (and this page).
        candidates = [self._page_number(url, param) or 1]
        for link in links:
            if not self._should_follow(link):
                continue
            n = self._page_number(link, param)
            if n:
                candidates.append(n)
        last = max(candidates)
        if last <= 1:
            return []

        # Rebuild this URL with page=1..last.
        parsed = urlparse(url)
        base_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k != param]
        out = []
        for p in range(1, last + 1):
            query = urlencode(base_pairs + [(param, str(p))])
            out.append(normalize_url(urlunparse(parsed._replace(query=query))))
        return out

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
            page_links = self._extract_links(result.url, result.html)
            # Make sure every listing page (1..last) gets queued, not just the
            # few a pager happens to link to.
            page_links += self._expand_pagination(result.url, page_links)
            for link in page_links:
                if link in self.seen or not self._should_follow(link):
                    continue
                # Priority links (e.g. product pages) jump to the front so we
                # scrape real products before exhausting search pagination.
                if priority and any(p in link for p in priority):
                    frontier.appendleft(link)
                else:
                    frontier.append(link)
