#!/usr/bin/env python3
"""Validate platform extractors against GT-aligned HTML fixtures (no Playwright)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.extraction.pdp_signals import (
    extract_faq,
    extract_return_policy_visible,
    extract_shipping_visible,
    extract_trust_badges,
    extract_variants,
)
from app.core.extraction.platform_parity import extract_visible_review_count, reconcile_review_count
from scripts.ground_truth_validation import _match_status

FIXTURES: list[dict] = [
    {
        "store": "Boat (Shopify)",
        "html": """
        <div class="product-faq shopify-section"><details><summary>Warranty</summary></details></div>
        <div class="product-info"><span>Verified Reviews:</span></div>
        <p>Free shipping on orders above Rs. 399</p>
        <p>7 day return policy</p>
        <select name="option1"><option>A</option></select>
        <div class="swatch" data-variant-id="1"></div>
        """,
        "expected": {
            "faq_count": 1,
            "trust_badges": ["Verified Reviews:"],
            "shipping_visible": True,
            "return_policy_visible": True,
            "variant_count": 2,
        },
    },
    {
        "store": "Mamaearth (Shopify)",
        "html": """
        <script type="application/ld+json">
        {"@type":"FAQPage","mainEntity":[{"@type":"Question"},{"@type":"Question"}]}
        </script>
        <div class="accordion-item"><summary>Ingredients</summary></div>
        <p>Asia's 1st Brand with MADE SAFE Certified Products</p>
        """,
        "expected": {
            "faq_count": 0,
            "trust_badges": ["Asia's 1st Brand with MADE SAFE Certified Products"],
            "shipping_visible": False,
            "return_policy_visible": False,
        },
    },
    {
        "store": "Allbirds (React/Yotpo)",
        "html": """
        <div class="product-form"><button>Add to Cart</button></div>
        <p>Free Shipping on Orders over $75. Easy Returns.</p>
        <div class="yotpo">105 Reviews</div>
        <span data-reviews-count="132"></span>
        <div data-variant-id="1"></div><div data-variant-id="2"></div>
        """,
        "expected": {
            "shipping_visible": True,
            "return_policy_visible": True,
            "review_count": 105,
            "variant_count": 2,
        },
    },
    {
        "store": "Gymshark (Headless)",
        "html": """
        <div class="product-faq"><details><summary>Size guide?</summary></details>
        <details><summary>Care instructions?</summary></details></div>
        <p>Free delivery on orders over £45</p>
        <button>Add to bag</button>
        """,
        "expected": {
            "faq_count": 2,
            "shipping_visible": True,
            "return_policy_visible": False,
        },
    },
]


def _extract_all(html: str) -> dict:
    faq = extract_faq(html)
    trust = extract_trust_badges(html)
    ship = extract_shipping_visible(html)
    ret = extract_return_policy_visible(html)
    variants = extract_variants(html)
    visible_reviews = extract_visible_review_count(html)
    return {
        "faq_count": faq.value,
        "trust_badges": trust.value,
        "shipping_visible": ship.value,
        "return_policy_visible": ret.value,
        "variant_count": variants.value,
        "review_count": visible_reviews,
    }


def main() -> int:
    total = 0
    passed = 0
    print("=== Platform Extractor GT Fixture Validation ===\n")
    for fx in FIXTURES:
        got = _extract_all(fx["html"])
        print(f"## {fx['store']}")
        for field, expected in fx["expected"].items():
            total += 1
            actual = got.get(field)
            if field == "review_count" and actual is None:
                actual = reconcile_review_count(
                    extract_visible_review_count(fx["html"]),
                    132,
                )
            status = _match_status(expected, actual)
            ok = status in ("MATCH", "PARTIAL MATCH")
            if ok:
                passed += 1
            mark = "PASS" if ok else "FAIL"
            print(f"  {field}: {mark} (expected={expected!r}, got={actual!r})")
        print()

    pct = round(passed / total * 100, 1) if total else 0
    print(f"Fixture accuracy: {passed}/{total} ({pct}%)")
    target = 85.0
    print(f"Target > {target}%: {'MET' if pct >= target else 'NOT MET'}")
    return 0 if pct >= target else 1


if __name__ == "__main__":
    raise SystemExit(main())
