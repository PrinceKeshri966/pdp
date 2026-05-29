"""Unit tests for enterprise PDP signal extraction."""
from __future__ import annotations

from app.core.extraction.pdp_signals import (
    extract_faq,
    extract_inventory,
    extract_return_policy_visible,
    extract_shipping_visible,
    extract_trust_badges,
    extract_variants,
)
from app.core.extraction.schema_graph import parse_schema_graph


FAQ_SCHEMA_HTML = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
  {"@type":"Question","name":"How to use?","acceptedAnswer":{"@type":"Answer","text":"Apply daily."}},
  {"@type":"Question","name":"Is it safe?","acceptedAnswer":{"@type":"Answer","text":"Yes."}}
]}
</script>
<div class="product-faq" itemtype="https://schema.org/FAQPage"><h2>FAQ</h2></div>
"""

FAQ_ACCORDION_HTML = """
<div class="shopify-section product-faq">
  <h2>FAQs</h2>
  <details><summary>What is this?</summary><p>Hair oil.</p></details>
</div>
<footer>Free shipping on all orders</footer>
"""

GENERIC_ACCORDION_HTML = """
<div class="product-description accordion">
  <details><summary>Ingredients</summary><p>Onion extract</p></details>
</div>
"""

TRUST_HTML = """
<div class="product-info">
  <img alt="MADE SAFE Certified" src="/badge.png"/>
  <p>Asia's 1st Brand with MADE SAFE Certified Products</p>
</div>
<footer>888 reviews on other products</footer>
"""

SHIPPING_PDP_HTML = """
<div class="product-form">
  <p>Free shipping on orders above Rs. 399</p>
</div>
<footer><a href="/policies/shipping">Shipping Policy</a></footer>
"""

SHIPPING_FOOTER_ONLY = """
<div class="product-form"><button>Add to Cart</button></div>
<footer>Free shipping | Return policy | 7 day return</footer>
"""

OUT_OF_STOCK_HTML = """
<div class="product-info"><span class="stock">Out of stock</span></div>
<script type="application/ld+json">
{"@type":"Product","offers":{"@type":"Offer","availability":"https://schema.org/OutOfStock","price":"499"}}
</script>
"""


def test_faq_schema_priority():
    graph = parse_schema_graph(FAQ_SCHEMA_HTML)
    result = extract_faq(FAQ_SCHEMA_HTML, schema_graph=graph)
    assert result.value == 2
    assert "FAQPage.schema" in result.source
    assert result.confidence >= 0.95


def test_faq_accordion_in_section():
    result = extract_faq(FAQ_ACCORDION_HTML)
    assert result.value >= 1
    assert "faq" in result.source.lower()


def test_faq_no_generic_accordion():
    result = extract_faq(GENERIC_ACCORDION_HTML)
    assert result.value == 0


def test_trust_badges_ontology():
    result = extract_trust_badges(TRUST_HTML)
    assert result.value
    assert any("made safe" in b.lower() for b in result.value)
    assert not any("888 reviews" in b for b in result.value)


def test_shipping_visible_on_pdp():
    result = extract_shipping_visible(SHIPPING_PDP_HTML)
    assert result.value is True


def test_shipping_not_from_footer_only():
    result = extract_shipping_visible(SHIPPING_FOOTER_ONLY)
    assert result.value is False


def test_returns_not_from_footer_only():
    result = extract_return_policy_visible(SHIPPING_FOOTER_ONLY)
    assert result.value is False


def test_inventory_out_of_stock_schema():
    graph = parse_schema_graph(OUT_OF_STOCK_HTML)
    result = extract_inventory(OUT_OF_STOCK_HTML, schema_graph=graph)
    assert result.value == "Out of stock"
    assert result.confidence >= 0.90


def test_variants_merge_dom_and_api():
    html = '<div class="swatch" data-variant-id="1"></div><div class="swatch" data-variant-id="2"></div>'
    api_variants = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    result = extract_variants(html, platform_variants=api_variants)
    assert result.value >= 2


def test_schema_graph_product():
    html = """
    <script type="application/ld+json">
    {"@graph":[
      {"@type":"Product","name":"Test Product","offers":{"@type":"Offer","price":"999","priceCurrency":"INR"}},
      {"@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":1,"name":"Home"}]}
    ]}
    </script>
    """
    graph = parse_schema_graph(html)
    assert graph["has_product_schema"]
    assert graph["has_breadcrumb_schema"]
    assert "Product" in graph["detected_types"]
