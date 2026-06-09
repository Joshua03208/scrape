"""A configurable web scraper for collecting part numbers and prices.

The package is organised as a small pipeline:

    config   -> load per-site YAML settings
    fetcher  -> download a page (requests or a real Playwright browser)
    crawler  -> walk every in-domain link, politely and deduplicated
    extractor-> pull part numbers + prices out of each page
    storage  -> persist results to SQLite and export CSV
    pipeline -> wire the above together for one site

Run it via ``python -m scraper.cli --help``.
"""

__version__ = "0.1.0"
