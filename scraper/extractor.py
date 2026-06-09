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

# Generic money matcher: handles $ £ € (and GBP/USD/EUR words), e.g.
# £1,234.56 / $99 / €12.5 / 1,234.56 GBP.
_AMOUNT = r"(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
_PRICE_RE = re.compile(
    rf"(?:(?P<sym>[$£€])|(?P<code>\b(?:GBP|USD|EUR)\b))\s?{_AMOUNT}"
    rf"|{_AMOUNT}\s?(?P<code2>\b(?:GBP|USD|EUR)\b)"
)
_SYMBOL_TO_CCY = {"$": "USD", "£": "GBP", "€": "EUR"}
# A reasonable default part-number shape: letters+digits, dots/dashes allowed
# (covers OpenCart-style codes like 133.123 as well as AB-123-X).
_PART_RE = re.compile(
    r"\b([A-Z0-9]{2,}(?:[.\-][A-Z0-9]+)+|[A-Z]{1,4}\d{3,}[A-Z0-9.\-]*)\b"
)


@dataclass
class Record:
    url: str
    part_number: str
    price: float
    currency: str = "USD"
    raw_price: str = ""


def _clean_price(text: str, default_currency: str = "USD") -> tuple[float, str, str] | None:
    """Parse a price string into (amount, raw_match, currency) or None."""
    m = _PRICE_RE.search(text)
    if not m:
        return None
    # The amount is whichever numeric group matched.
    amount_str = next(g for g in m.groups()[:] if g and any(c.isdigit() for c in g))
    amount = float(amount_str.replace(",", ""))
    sym = m.groupdict().get("sym")
    code = m.groupdict().get("code") or m.groupdict().get("code2")
    currency = _SYMBOL_TO_CCY.get(sym) if sym else (code or default_currency)
    return amount, m.group(0).strip(), currency


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


def _find_price(node: Tag, page_text: str, rule: FieldRule) -> tuple[float, str, str] | None:
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
    # Last-ditch fallback: scan the whole page, but prefer the first NON-ZERO
    # amount. This skips things like an empty basket total ("£0.00") that many
    # shop themes show in the header.
    for m in _PRICE_RE.finditer(page_text):
        parsed = _clean_price(m.group(0))
        if parsed and parsed[0] > 0:
            return parsed
    return _clean_price(page_text)


class Extractor:
    def __init__(self, config: ExtractConfig) -> None:
        self.config = config

    def extract(self, url: str, html: str) -> list[Record]:
        # Skip pages we don't want to extract from (e.g. search listings) while
        # the crawler still uses them to discover product links.
        patterns = self.config.only_on_url_patterns
        if patterns and not any(p in url for p in patterns):
            return []
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
        amount, raw, currency = price
        return [Record(url=url, part_number=part, price=amount,
                       currency=currency, raw_price=raw)]

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
            amount, raw, currency = parsed
            records.append(
                Record(url=url, part_number=part, price=amount,
                       currency=currency, raw_price=raw)
            )
        return records
