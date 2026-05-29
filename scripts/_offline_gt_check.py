"""Offline extractor vs known GT (no Playwright GT)."""
import sys
sys.path.insert(0, ".")
import httpx
from app.core.html_metadata import BROWSER_UA
from app.core.extraction.shopify_theme import extract_shopify_fields, extract_visible_sale_price, count_variant_pickers_gt, count_faq_gt, extract_policy_visible, extract_review_widget_trust
from app.core.extraction.pdp_signals import extract_faq, extract_trust_badges, extract_shipping_visible, extract_return_policy_visible, extract_variants

BOAT = "https://www.boat-lifestyle.com/products/airdopes-181-pro-bluetooth-earbuds"
BOAT_GT = {"price": "1099", "variant_count": 16, "faq_count": 1, "trust": "Verified Reviews:", "shipping": True, "returns": True}

h = httpx.get(BOAT, headers={"User-Agent": BROWSER_UA}, follow_redirects=True, timeout=25).text
sf = extract_shopify_fields(h)
price = extract_visible_sale_price(h)
vc = count_variant_pickers_gt(h)
faq = count_faq_gt(h)
ship, ret = extract_policy_visible(h)
trust = extract_review_widget_trust(h)
print("BOAT offline vs GT:")
print("price", price, "GT", BOAT_GT["price"])
print("variants", vc, "GT", BOAT_GT["variant_count"])
print("faq", faq, "GT", BOAT_GT["faq_count"])
print("shipping", ship, "GT", BOAT_GT["shipping"])
print("returns", ret, "GT", BOAT_GT["returns"])
print("trust", trust[:3], "GT", BOAT_GT["trust"])
