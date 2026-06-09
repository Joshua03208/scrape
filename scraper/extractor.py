"""Pull part numbers and prices out of page HTML.

Two strategies, chosen per site in config:

* ``product_page`` -- the page is one product; emit at most one record with
  the page's part number and price.
* ``price_table``  -- the page holds a table/list of many parts; emit one
  record per row.

Each field is located by trying the configured CSS selectors first, then the
configured regexes, then (for prices) a generic currency fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .config import ExtractConfig, FieldRule

# Generic money matcher: $1,234.56 / $1234 / 1,234.56 USD-ish.
_PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
# A reasonable default part-number shape: letters+digits, dashes allowed.
_PART_RE = re.compile(r"\b([A-Z0-9]{2,}(?:-[A-Z0-9]+)+|[A-Z]{1,4}\d{3,}[A-Z0-9\-]*)\b")


@dataclass
class Record:
    url: str
    part_number: str
    price: float
    currency: str = "USD"
    raw_price: str = ""


def _clean_price(text: str) -> tuple[float, str] | None:
    """Parse a price string into (amount, raw_match) or None."""
    m = _PRICE_RE.search(text)
    if not m:
        return None
    amount = float(m.group(1).replace(",", ""))
    return amount, m.group(0).strip()


def _field_from_selectors(node: Tag, rule: FieldRule) -> str | None:
    for selector in rule.selectors:
        el = node.select_one(selector)
        if el is None:
            continue
        if rule.attribute:
            val = el.get(rule.attribute)
            if val:
                return val.strip()
        else:
            text = el.get_text(" ", strip=True)
            if text:
                return text
    return None


def _field_from_regex(text: str, rule: FieldRule) -> str | None:
    for pattern in rule.regex:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            # Prefer first capture group if the pattern defines one.
            return (m.group(1) if m.groups() else m.group(0)).strip()
    return None


def _find_part_number(node: Tag, page_text: str, rule: FieldRule) -> str | None:
    val = _field_from_selectors(node, rule)
    if val:
        return val
    val = _field_from_regex(page_text, rule)
    if val:
        return val
    # Last-ditch generic guess.
    m = _PART_RE.search(page_text)
    return m.group(1) if m else None


def _find_price(node: Tag, page_text: str, rule: FieldRule) -> tuple[float, str] | None:
    val = _field_from_selectors(node, rule)
    if val:
        parsed = _clean_price(val)
        if parsed:
            return parsed
    val = _field_from_regex(page_text, rule)
    if val:
        parsed = _clean_price(val)
        if parsed:
            return parsed
    return _clean_price(page_text)


class Extractor:
    def __init__(self, config: ExtractConfig) -> None:
        self.config = config

    def extract(self, url: str, html: str) -> list[Record]:
        soup = BeautifulSoup(html, "lxml")
        if self.config.strategy == "price_table":
            return self._extract_table(url, soup)
        return self._extract_product_page(url, soup)

    def _extract_product_page(self, url: str, soup: BeautifulSoup) -> list[Record]:
        page_text = soup.get_text(" ", strip=True)
        part = _find_part_number(soup, page_text, self.config.part_number)
        price = _find_price(soup, page_text, self.config.price)
        if not part or not price:
            return []
        amount, raw = price
        return [Record(url=url, part_number=part, price=amount, raw_price=raw)]

    def _extract_table(self, url: str, soup: BeautifulSoup) -> list[Record]:
        cfg = self.config
        if not (cfg.row_selector and cfg.part_number_cell and cfg.price_cell):
            raise ValueError(
                "price_table strategy requires row_selector, part_number_cell "
                "and price_cell in the site config."
            )
        records: list[Record] = []
        for row in soup.select(cfg.row_selector):
            part_el = row.select_one(cfg.part_number_cell)
            price_el = row.select_one(cfg.price_cell)
            if not part_el or not price_el:
                continue
            part = part_el.get_text(" ", strip=True)
            parsed = _clean_price(price_el.get_text(" ", strip=True))
            if not part or not parsed:
                continue
            amount, raw = parsed
            records.append(
                Record(url=url, part_number=part, price=amount, raw_price=raw)
            )
        return records
