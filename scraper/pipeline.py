"""Wire fetcher + crawler + extractor + storage into one run per site."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import SiteConfig
from .crawler import Crawler
from .extractor import Extractor
from .fetcher import build_fetcher
from .storage import Storage

log = logging.getLogger(__name__)


def run_site(config: SiteConfig, storage: Storage) -> int:
    """Crawl one site end to end. Returns the number of records saved."""
    extractor = Extractor(config.extract)
    total_saved = 0
    pages = 0

    log.info("Starting %s (fetcher=%s, max_pages=%d)",
             config.name, config.fetcher, config.max_pages)

    with build_fetcher(config) as fetcher:
        crawler = Crawler(config, fetcher)
        for url, html in crawler.crawl():
            pages += 1
            records = extractor.extract(url, html)
            if records:
                saved = storage.save(config.name, records)
                total_saved += saved
                log.info("  [%d] %s -> %d record(s)", pages, url, len(records))
            else:
                log.debug("  [%d] %s -> no part/price", pages, url)

    log.info("Finished %s: %d pages crawled, %d records saved",
             config.name, pages, total_saved)
    return total_saved
