"""Offline tests for the extractor -- no network needed."""

from scraper.config import ExtractConfig, FieldRule
from scraper.extractor import Extractor, _clean_price


def test_clean_price_variants():
    assert _clean_price("$1,234.56")[0] == 1234.56
    assert _clean_price("Now only $99")[0] == 99.0
    assert _clean_price("$12.5")[0] == 12.5
    assert _clean_price("no price here") is None


def test_product_page_selectors():
    html = """
    <html><body>
      <span itemprop="sku">SH-4521-CR</span>
      <span itemprop="price">$148.99</span>
    </body></html>
    """
    cfg = ExtractConfig(
        strategy="product_page",
        part_number=FieldRule(selectors=["[itemprop=sku]"]),
        price=FieldRule(selectors=["[itemprop=price]"]),
    )
    records = Extractor(cfg).extract("http://x/p/1", html)
    assert len(records) == 1
    assert records[0].part_number == "SH-4521-CR"
    assert records[0].price == 148.99


def test_product_page_regex_fallback():
    html = "<html><body><p>Model # AB123-X Price: $59.00</p></body></html>"
    cfg = ExtractConfig(
        strategy="product_page",
        part_number=FieldRule(regex=[r"Model\s*#?\s*([A-Z0-9\-]+)"]),
        price=FieldRule(regex=[r"\$([0-9.]+)"]),
    )
    records = Extractor(cfg).extract("http://x/p/2", html)
    assert records[0].part_number == "AB123-X"
    assert records[0].price == 59.0


def test_price_table_strategy():
    html = """
    <table class="pricing">
      <tr><td>VLV-100</td><td>$25.00</td></tr>
      <tr><td>VLV-200</td><td>$31.50</td></tr>
      <tr><td>header</td><td>no price</td></tr>
    </table>
    """
    cfg = ExtractConfig(
        strategy="price_table",
        row_selector="table.pricing tr",
        part_number_cell="td:nth-child(1)",
        price_cell="td:nth-child(2)",
    )
    records = Extractor(cfg).extract("http://x/list", html)
    assert [r.part_number for r in records] == ["VLV-100", "VLV-200"]
    assert [r.price for r in records] == [25.0, 31.5]
