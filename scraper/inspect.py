"""Inspect a live page to discover selectors for a new site config.

Because every site puts part numbers and prices in different places, this
helper fetches one URL and reports:

  * the page <title> and any search form (action + input name),
  * elements that contain a price, with a usable CSS selector for each,
  * elements that look like a part number (sku/model attributes or matching
    a part-number pattern),

so you can copy the right selectors into a ``config/sites/*.yaml`` file. Run it
on a machine that can actually reach the site (this is the bit the cloud
sandbox can't do for blocked hosts).

Usage:
    python -m scraper.cli inspect "https://site/search?q=133." --playwright
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .config import SiteConfig
from .extractor import _PART_RE, _PRICE_RE
from .fetcher import RequestsFetcher, PlaywrightFetcher

# Attributes that strongly suggest a part/model number.
_PART_ATTRS = ("data-part-number", "data-sku", "data-product-sku", "data-mpn")


def _css_selector(el: Tag) -> str:
    """Build a short, human-readable CSS selector for an element."""
    sel = el.name
    el_id = el.get("id")
    if el_id:
        return f"{sel}#{el_id}"
    classes = [c for c in (el.get("class") or []) if c][:3]
    if classes:
        sel += "." + ".".join(classes)
    itemprop = el.get("itemprop")
    if itemprop:
        sel += f"[itemprop={itemprop}]"
    return sel


def _is_leafish(el: Tag) -> bool:
    """True if the element holds text directly rather than wrapping big blocks."""
    return len(el.find_all(True, recursive=False)) <= 2


@dataclass
class Candidate:
    selector: str
    text: str


def _price_candidates(soup: BeautifulSoup) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for el in soup.find_all(True):
        if not _is_leafish(el):
            continue
        text = el.get_text(" ", strip=True)
        if len(text) > 60 or not _PRICE_RE.search(text):
            continue
        sel = _css_selector(el)
        key = sel + "|" + text
        if key in seen:
            continue
        seen.add(key)
        out.append(Candidate(sel, text))
    return out[:25]


def _part_candidates(soup: BeautifulSoup) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()

    # 1) Elements carrying an explicit sku/part attribute.
    for el in soup.find_all(True):
        for attr in _PART_ATTRS + ("itemprop",):
            val = el.get(attr)
            if attr == "itemprop" and val != "sku":
                continue
            if val:
                sel = _css_selector(el)
                text = (el.get(attr) if attr != "itemprop"
                        else el.get_text(" ", strip=True)) or ""
                key = sel + "|" + str(text)
                if key not in seen:
                    seen.add(key)
                    out.append(Candidate(sel, str(text)))

    # 2) Leaf elements whose text matches a part-number shape.
    for el in soup.find_all(True):
        if not _is_leafish(el):
            continue
        text = el.get_text(" ", strip=True)
        if len(text) > 40 and _PART_RE.search(text) is None:
            continue
        m = _PART_RE.search(text)
        if not m:
            continue
        sel = _css_selector(el)
        key = sel + "|" + m.group(1)
        if key not in seen:
            seen.add(key)
            out.append(Candidate(sel, m.group(1)))
    return out[:25]


def _search_form(soup: BeautifulSoup) -> str:
    for form in soup.find_all("form"):
        inp = form.find("input", attrs={"type": "search"}) or form.find(
            "input", attrs={"name": lambda v: v and v.lower() in ("q", "query", "search", "keyword")}
        )
        if inp:
            action = form.get("action", "(same page)")
            method = (form.get("method") or "get").upper()
            name = inp.get("name", "?")
            return f"  action={action}  method={method}  input name={name!r}"
    return "  (no obvious search form found)"


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def inspect_url(url: str, use_playwright: bool = False) -> None:
    # Use a normal browser identity + a visible window so the inspector can get
    # past the same bot-walls the real crawl does.
    cfg = SiteConfig(
        name="inspect", start_urls=[url], allowed_domains=["_"],
        headless=False, user_agent=_BROWSER_UA,
    )
    fetcher = PlaywrightFetcher(cfg, headless=False) if use_playwright else RequestsFetcher(cfg)
    try:
        result = fetcher.fetch(url)
    finally:
        fetcher.close()

    if not result.html:
        print(f"Could not fetch {url} (status {result.status}).")
        if not use_playwright:
            print("Tip: try again with --playwright if the site needs JavaScript.")
        return

    soup = BeautifulSoup(result.html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else "(no title)"

    print(f"\n=== {url}")
    print(f"status: {result.status}   title: {title}\n")

    print("SEARCH FORM:")
    print(_search_form(soup), "\n")

    print("PRICE candidates (selector  ->  text):")
    for c in _price_candidates(soup):
        print(f"  {c.selector:<40}  {c.text}")
    print()

    print("PART NUMBER candidates (selector  ->  value):")
    for c in _part_candidates(soup):
        print(f"  {c.selector:<40}  {c.text}")
    print()

    print("Next: copy the best price + part selectors into a "
          "config/sites/<name>.yaml under extract:.")
