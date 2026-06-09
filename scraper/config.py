"""Load and validate per-site scraper configuration from YAML.

Each manufacturer site gets its own file under ``config/sites/``. Adding a
new site should never require touching Python code -- only a new YAML file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LoginStep:
    """A single action performed during a login flow (Playwright only)."""

    selector: str
    # Exactly one of `value`, `value_env`, or `action` is used.
    value: str | None = None          # literal text to type
    value_env: str | None = None      # env var name to read the value from
    action: str = "fill"              # "fill" | "click" | "wait"

    def resolved_value(self) -> str | None:
        """Return the literal value, reading from the environment if needed."""
        if self.value_env:
            val = os.environ.get(self.value_env)
            if val is None:
                raise RuntimeError(
                    f"Login step references env var {self.value_env!r} "
                    "but it is not set. Add it to your .env / environment."
                )
            return val
        return self.value


@dataclass
class LoginConfig:
    enabled: bool = False
    url: str | None = None
    steps: list[LoginStep] = field(default_factory=list)
    # A CSS selector that only appears once login succeeded; used to verify.
    success_selector: str | None = None


@dataclass
class CrawlConfig:
    # Only follow links whose path matches one of these substrings/patterns.
    # Empty means "follow everything in-domain".
    follow_link_patterns: list[str] = field(default_factory=list)
    # Never follow links matching these (cart, logout, etc.).
    ignore_link_patterns: list[str] = field(default_factory=list)


@dataclass
class FieldRule:
    """How to find one field (part number or price) on a page."""

    selectors: list[str] = field(default_factory=list)  # CSS selectors, tried in order
    regex: list[str] = field(default_factory=list)      # regexes, tried in order
    attribute: str | None = None  # pull this attribute instead of text (e.g. "content")


@dataclass
class ExtractConfig:
    # "product_page" -> one part/price per page.
    # "price_table"  -> many rows, each a part/price pair.
    strategy: str = "product_page"
    part_number: FieldRule = field(default_factory=FieldRule)
    price: FieldRule = field(default_factory=FieldRule)
    # price_table strategy only:
    row_selector: str | None = None
    part_number_cell: str | None = None
    price_cell: str | None = None
    # If set, only extract from pages whose URL contains one of these strings.
    # (e.g. only real product pages, not search/category listings.)
    only_on_url_patterns: list[str] = field(default_factory=list)


@dataclass
class SiteConfig:
    name: str
    start_urls: list[str]
    allowed_domains: list[str]
    fetcher: str = "requests"            # "requests" | "playwright"
    headless: bool = True                # playwright only: run with no visible window
    max_pages: int = 500
    delay_seconds: float = 1.0
    timeout_seconds: float = 30.0
    respect_robots: bool = True
    user_agent: str = (
        "PartPriceBot/0.1 (+https://example.com/bot; contact: you@example.com)"
    )
    login: LoginConfig = field(default_factory=LoginConfig)
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    extract: ExtractConfig = field(default_factory=ExtractConfig)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "SiteConfig":
        required = ("name", "start_urls", "allowed_domains")
        for key in required:
            if not data.get(key):
                raise ValueError(f"Site config missing required field: {key!r}")

        login_raw = data.get("login", {}) or {}
        steps = [LoginStep(**s) for s in login_raw.get("steps", [])]
        login = LoginConfig(
            enabled=login_raw.get("enabled", False),
            url=login_raw.get("url"),
            steps=steps,
            success_selector=login_raw.get("success_selector"),
        )

        crawl_raw = data.get("crawl", {}) or {}
        crawl = CrawlConfig(
            follow_link_patterns=crawl_raw.get("follow_link_patterns", []),
            ignore_link_patterns=crawl_raw.get("ignore_link_patterns", []),
        )

        extract_raw = data.get("extract", {}) or {}
        extract = ExtractConfig(
            strategy=extract_raw.get("strategy", "product_page"),
            part_number=FieldRule(**(extract_raw.get("part_number", {}) or {})),
            price=FieldRule(**(extract_raw.get("price", {}) or {})),
            row_selector=extract_raw.get("row_selector"),
            part_number_cell=extract_raw.get("part_number_cell"),
            price_cell=extract_raw.get("price_cell"),
            only_on_url_patterns=extract_raw.get("only_on_url_patterns", []),
        )

        known = {
            "name", "start_urls", "allowed_domains", "fetcher", "headless",
            "max_pages", "delay_seconds", "timeout_seconds", "respect_robots",
            "user_agent", "login", "crawl", "extract",
        }
        scalars = {k: v for k, v in data.items() if k in known and k not in
                   ("login", "crawl", "extract")}

        return SiteConfig(login=login, crawl=crawl, extract=extract, **scalars)


def load_site_config(path: str | Path) -> SiteConfig:
    """Load and validate a single site YAML file."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level.")
    return SiteConfig.from_dict(data)
