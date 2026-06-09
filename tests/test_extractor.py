"""Offline tests for the extractor -- no network needed."""

from scraper.config import ExtractConfig, FieldRule
from scraper.extractor import Extractor, _clean_price


def test_clean_price_variants():
    amount, _raw, ccy = _clean_price("$1,234.56")
    assert (amount, ccy) == (1234.56, "USD")
    assert _clean_price("Now only $99")[0] == 99.0
    assert _clean_price("$12.5")[0] == 12.5
    # UK / EUR symbols are recognised with the right currency code.
    assert _clean_price("£45.00")[0] == 45.0
    assert _clean_price("£45.00")[2] == "GBP"
    assert _clean_price("€10")[2] == "EUR"
    assert _clean_price("no price here") is None


def test_fallback_skips_empty_basket_total():
    # The header shows an empty basket "£0.00" before the real price. The
    # fallback should skip the zero and pick the genuine product price.
    html = """
    <html><body>
      <div id="cart"><span id="cart-total">0 item(s) - &pound;0.00</span></div>
      <h1>Shower Hose</h1>
      <p>Product Code: 150.221</p>
      <div class="product-price">&pound;14.99</div>
    </body></html>
    """
    cfg = ExtractConfig(
        strategy="product_page",
        part_number=FieldRule(regex=[r"Product Code:\s*([A-Za-z0-9.\-/]+)"]),
        price=FieldRule(),  # no selector -> exercises the fallback
    )
    rec = Extractor(cfg).extract("http://x/p", html)[0]
    assert rec.part_number == "150.221"
    assert rec.price == 14.99


def test_only_on_url_patterns_skips_listing_pages():
    html = "<html><body>Product Code: 133.1 &pound;9.99</body></html>"
    cfg = ExtractConfig(
        strategy="product_page",
        only_on_url_patterns=["route=product/product"],
        part_number=FieldRule(regex=[r"Product Code:\s*([A-Za-z0-9.\-/]+)"]),
    )
    ex = Extractor(cfg)
    # A search-listing URL is skipped...
    assert ex.extract("http://x/index.php?route=product/search&page=3", html) == []
    # ...but a real product page is scraped.
    assert ex.extract("http://x/index.php?route=product/product&product_id=5", html)


def test_opencart_style_product_page():
    # Mimics OpenCart default markup: Product Code line + GBP price.
    html = """
    <html><body>
      <h1>Triton Heater Tank</h1>
      <ul class="list-unstyled">
        <li>Brand: Triton</li>
        <li>Product Code: 133.456</li>
        <li>Availability: In Stock</li>
      </ul>
      <div class="product-info">
        <ul class="list-unstyled"><li class="price">&pound;28.75</li></ul>
      </div>
    </body></html>
    """
    cfg = ExtractConfig(
        strategy="product_page",
        part_number=FieldRule(regex=[r"Product Code:\s*([A-Za-z0-9.\-/]+)"]),
        price=FieldRule(selectors=[".product-info .price"]),
    )
    rec = Extractor(cfg).extract("http://x/p", html)[0]
    assert rec.part_number == "133.456"
    assert rec.price == 28.75
    assert rec.currency == "GBP"


def test_description_is_extracted():
    html = """
    <html><body>
      <p>Product Code: 133.999</p>
      <div class="product-info"><span class="price">&pound;5.00</span></div>
      <div id="tab-description">Genuine Triton solenoid valve, 230V.</div>
    </body></html>
    """
    cfg = ExtractConfig(
        strategy="product_page",
        part_number=FieldRule(regex=[r"Product Code:\s*([A-Za-z0-9.\-/]+)"]),
        price=FieldRule(selectors=[".product-info .price"]),
        description=FieldRule(selectors=["#tab-description"]),
    )
    rec = Extractor(cfg).extract("http://x/p", html)[0]
    assert rec.description == "Genuine Triton solenoid valve, 230V."


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
