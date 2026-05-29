"""Tests for platform-agnostic GT parity extractors."""
from __future__ import annotations

from app.core.extraction.platform_parity import (
    count_faq_dom_gt,
    detect_review_provider,
    extract_policy_visibility_gt,
    extract_trust_badges_gt,
    extract_visible_review_count,
    reconcile_review_count,
    resolve_variant_count,
)
from app.core.extraction.pdp_signals import extract_faq, extract_trust_badges


FAQ_BOAT_HTML = """
<div class="shopify-section product-faq">
  <details><summary>Warranty info</summary><p>1 year</p></details>
</div>
<footer>Return policy</footer>
"""

FAQ_SCHEMA_ONLY = """
<script type="application/ld+json">
{"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Q1"},{"@type":"Question","name":"Q2"}]}
</script>
<div class="accordion-item"><summary>Ingredients</summary></div>
"""

TRUST_MADE_SAFE = """
<div class="product-info">
  <p>Asia's 1st Brand with MADE SAFE Certified Products</p>
</div>
<div class="jdgm-widget">90 reviews</div>
"""

TRUST_VERIFIED = """
<div class="product-info"><span>Verified Reviews:</span></div>
"""

SHIPPING_ALLBIRDS = """
<div class="product-form"><button>Add to Cart</button></div>
<p>Free Shipping on Orders over $75. Easy Returns.</p>
<footer><a href="/policies/shipping">Shipping</a></footer>
"""

VARIANT_REACT = """
<div data-variant-id="101"></div>
<div data-variant-id="102"></div>
<div data-variant-id="103"></div>
"""


def test_faq_dom_boat_style():
    assert count_faq_dom_gt(FAQ_BOAT_HTML) == 1


def test_faq_dom_gymshark_two_questions():
    html = """
    <div class="product-faq"><details><summary>Size guide?</summary></details>
    <details><summary>Care instructions?</summary></details></div>
    """
    assert count_faq_dom_gt(html) == 2


def test_variant_boat_select_plus_swatch():
    html = """
    <select name="option1"><option>A</option></select>
    <div class="swatch" data-variant-id="1"></div>
    """
    assert resolve_variant_count(html) == 2


def test_faq_schema_only_not_counted():
    result = extract_faq(FAQ_SCHEMA_ONLY)
    assert result.value == 0


def test_trust_made_safe_not_reviews():
    hits = extract_trust_badges_gt(TRUST_MADE_SAFE)
    assert any("made safe" in h.lower() for h in hits)
    assert not any("90 reviews" in h.lower() for h in hits)


def test_trust_verified_reviews_label():
    hits = extract_trust_badges(TRUST_VERIFIED).value
    assert any("verified review" in h.lower() for h in hits)
    assert not any("jdgm" in h.lower() for h in hits)


def test_shipping_returns_body_text():
    ship, ret = extract_policy_visibility_gt(SHIPPING_ALLBIRDS)
    assert ship is True
    assert ret is True


def test_variant_unique_data_ids():
    assert resolve_variant_count(VARIANT_REACT) == 3


def test_review_count_reconcile_prefers_visible():
    assert reconcile_review_count(132, 105) == 105
    assert reconcile_review_count(90, 92) == 92


def test_visible_review_count_yotpo():
    html = '<div class="yotpo">105 Reviews</div><span data-reviews-count="132"></span>'
    assert extract_visible_review_count(html) == 105


def test_review_provider_yotpo():
    assert detect_review_provider('<div class="yotpo-main-widget">') == "yotpo"


def test_huel_gbp_shipping_returns():
    html = """
    <div class="product-form"><button>Add to basket</button></div>
    <p>Free delivery on orders over £45</p>
    <p>60-day money back guarantee</p>
    """
    ship, ret = extract_policy_visibility_gt(html)
    assert ship and ret


def test_page_type_pdp_url():
    from app.core.page_type_router import detect_page_type
    r = detect_page_type(url="https://huel.com/products/black-edition", scrape_html="<button>add to cart</button>")
    assert r["page_type"] == "pdp"
