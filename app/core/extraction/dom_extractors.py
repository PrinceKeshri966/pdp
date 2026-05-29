"""
Deterministic DOM / meta / embedded JSON extraction.
"""
from __future__ import annotations

import json
import re
from html import unescape
from typing import Any


_PRICE_RE = re.compile(
    r"(?:₹|rs\.?\s*|inr\s*|usd\s*|\$|€|£)\s*([\d,]+(?:\.\d{1,2})?)|"
    r"([\d,]+(?:\.\d{1,2})?)\s*(?:₹|rs\.?|inr|usd)",
    re.I,
)
_REVIEW_RE = re.compile(
    r"(\d[\d,]*)\s*(?:reviews?|ratings?)|"
    r"(\d(?:\.\d)?)\s*(?:/|out of)\s*5|"
    r"data-number-of-reviews=[\"'](\d+)[\"']|"
    r"data-average-rating=[\"']([\d.]+)[\"']",
    re.I,
)
_JUDGE_ME_RE = re.compile(
    r"jdgm-prev-badge[^>]*data-number-of-reviews=[\"'](\d+)[\"']|"
    r"data-average-rating=[\"']([\d.]+)[\"']",
    re.I,
)
_YOTPO_RE = re.compile(
    r"yotpo[^>]*data-reviews-count=[\"'](\d+)[\"']|"
    r"data-score=[\"']([\d.]+)[\"']|"
    r"(\d[\d,]*)\s*Reviews",
    re.I,
)
_LOOX_RE = re.compile(
    r"loox-rating[^>]*data-rating=[\"']([\d.]+)[\"']|"
    r"data-raters=[\"'](\d+)[\"']",
    re.I,
)
_NETWORK_PRODUCT_URL_HINTS = (
    "product", "graphql", "catalog", "item", "sku", "variant", "api",
    "yotpo", "judge.me", "loox", "stamped", "reviews", "rating",
    "wc/store", "wp-json", "magento", "shopify",
)


def extract_open_graph(html: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not html:
        return out
    for prop, key in (
        ("og:title", "product_name"),
        ("og:description", "description"),
        ("product:price:amount", "price"),
        ("product:price:currency", "currency"),
    ):
        m = re.search(
            rf'<meta[^>]*property=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)["\']',
            html,
            re.I,
        )
        if not m:
            m = re.search(
                rf'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']{re.escape(prop)}["\']',
                html,
                re.I,
            )
        if m:
            out[key] = unescape(m.group(1)).strip()
    return out


def extract_dom_selectors(html: str) -> dict[str, Any]:
    """Lightweight regex/DOM hints — not a full parser."""
    out: dict[str, Any] = {}
    text = _html_to_visible_text(html)
    h1 = re.search(r"<h1[^>]*>([\s\S]{2,200}?)</h1>", html, re.I)
    if h1:
        name = unescape(re.sub(r"<[^>]+>", " ", h1.group(1))).strip()
        if name and len(name) > 2:
            out["product_name"] = name
    if not out.get("product_name"):
        m = re.search(r'itemprop=["\']name["\'][^>]*>([^<]{2,200})<', html, re.I)
        if m:
            out["product_name"] = unescape(m.group(1)).strip()
    pm = _PRICE_RE.search(text)
    if pm:
        out["price"] = (pm.group(1) or pm.group(2) or "").replace(",", "")
    reviews = extract_review_widgets(html, text)
    if reviews:
        out.update(reviews)
    else:
        rm = _REVIEW_RE.search(text)
        if rm:
            for grp in rm.groups():
                if not grp:
                    continue
                try:
                    if "." in grp:
                        out["avg_rating"] = float(grp)
                    else:
                        out["review_count"] = int(grp.replace(",", ""))
                    out["has_reviews"] = True
                except ValueError:
                    pass
    if re.search(r"\badd to cart\b|\badd to bag\b|\bbuy now\b", text, re.I):
        out["above_fold_cta"] = "add to cart"
    return out


def extract_next_data(html: str) -> dict[str, Any]:
    m = re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>', html, re.I)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    return _walk_product_like(data, depth=0)


def extract_review_widgets(html: str, visible_text: str | None = None) -> dict[str, Any]:
    """Parse Yotpo, Judge.me, Loox and common review widget DOM markers."""
    out: dict[str, Any] = {}
    blob = f"{html}\n{visible_text or ''}"
    for pattern in (_JUDGE_ME_RE, _YOTPO_RE, _LOOX_RE):
        m = pattern.search(blob)
        if not m:
            continue
        for grp in m.groups():
            if not grp:
                continue
            try:
                if "." in grp:
                    val = float(grp)
                    if 0 < val <= 5:
                        out["avg_rating"] = val
                else:
                    out["review_count"] = int(grp.replace(",", ""))
                out["has_reviews"] = True
            except ValueError:
                pass
    if not out.get("review_count"):
        rm = re.search(r"(\d[\d,]*)\s*(?:reviews?|ratings?)\b", blob, re.I)
        if rm:
            try:
                count = int(rm.group(1).replace(",", ""))
                if 0 < count < 500_000:
                    out["review_count"] = count
                    out["has_reviews"] = True
            except ValueError:
                pass
    return out


def extract_review_from_network(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Provider-specific review extraction from captured network JSON."""
    best: dict[str, Any] = {}
    for item in payloads or []:
        url = (item.get("url") or "").lower()
        body = item.get("body")
        if not isinstance(body, (dict, list)):
            continue
        parsed: dict[str, Any] = {}
        if "judge.me" in url or "yotpo" in url or "loox" in url:
            parsed = _parse_review_provider_body(body, url)
        if not parsed:
            parsed = _walk_product_like(body, depth=0)
            if not (parsed.get("review_count") or parsed.get("avg_rating")):
                continue
        if (parsed.get("review_count") or 0) > (best.get("review_count") or 0):
            best.update(parsed)
            best["has_reviews"] = True
    return best


def _parse_review_provider_body(body: Any, url: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(body, dict):
        if "judge.me" in url:
            widget = body.get("widget") if isinstance(body.get("widget"), dict) else body
            rc = widget.get("review_number") or widget.get("reviews_count") or body.get("reviews_count")
            avg = widget.get("average_rating") or body.get("average_rating")
            if rc:
                try:
                    out["review_count"] = int(rc)
                except (TypeError, ValueError):
                    pass
            if avg:
                try:
                    out["avg_rating"] = float(avg)
                except (TypeError, ValueError):
                    pass
        if "yotpo" in url:
            bottom = body.get("bottomline") if isinstance(body.get("bottomline"), dict) else body
            rc = bottom.get("total_review") or bottom.get("total_reviews")
            avg = bottom.get("average_score") or bottom.get("average_rating")
            if rc:
                try:
                    out["review_count"] = int(rc)
                except (TypeError, ValueError):
                    pass
            if avg:
                try:
                    out["avg_rating"] = float(avg)
                except (TypeError, ValueError):
                    pass
        if "loox" in url:
            rc = body.get("raters") or body.get("reviewCount")
            avg = body.get("rating") or body.get("avgRating")
            if rc:
                try:
                    out["review_count"] = int(rc)
                except (TypeError, ValueError):
                    pass
            if avg:
                try:
                    out["avg_rating"] = float(avg)
                except (TypeError, ValueError):
                    pass
    if out:
        out["has_reviews"] = True
    return out


def extract_network_product_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge best product-like fields from captured XHR/fetch JSON (primary truth source)."""
    best: dict[str, Any] = {}
    best_score = 0
    for item in payloads:
        url = (item.get("url") or "").lower()
        body = item.get("body")
        if not isinstance(body, (dict, list)):
            continue
        if not any(h in url for h in _NETWORK_PRODUCT_URL_HINTS) and not url.endswith(".json"):
            if not isinstance(body, dict):
                continue
        parsed = _walk_product_like(body, depth=0)
        provider_reviews = _parse_review_provider_body(body, url)
        for k, v in provider_reviews.items():
            if v not in (None, "", []) and k not in parsed:
                parsed[k] = v
        score = _score_partial(parsed)
        if score > best_score:
            best_score = score
            best = parsed
    review_only = extract_review_from_network(payloads)
    for k, v in review_only.items():
        if v not in (None, "", []) and k not in best:
            best[k] = v
    return best


def _walk_product_like(obj: Any, depth: int) -> dict[str, Any]:
    if depth > 8:
        return {}
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        keys = {k.lower() for k in obj}
        if keys & {"product_name", "title", "name"} and keys & {"price", "offers", "variants"}:
            pass
        name = (
            obj.get("product_name") or obj.get("productName") or obj.get("title")
            or obj.get("name")
        )
        if isinstance(name, str) and len(name) > 2:
            n = name.strip()
            if n.lower() not in ("mamaearth", "boat", "home", "product", "product_recommendations", "recommendations"):
                out["product_name"] = n
            elif len(n) > 15:
                out["product_name"] = n
        price = (
            obj.get("price") or obj.get("sale_price") or obj.get("salePrice")
            or obj.get("current_price") or obj.get("mrp") or obj.get("special_price")
        )
        if price is not None:
            if isinstance(price, dict):
                amt = price.get("amount") or price.get("value") or price.get("regular_price")
                if amt is not None:
                    out["price"] = str(amt).replace(",", "")
                out["currency"] = price.get("currency") or price.get("currency_code")
            else:
                pstr = str(price).replace(",", "")
                try:
                    pval = float(pstr)
                    if pval >= 10000 and pval == int(pval):
                        pstr = str(int(pval / 100))
                except ValueError:
                    pass
                out["price"] = pstr
        brand = obj.get("brand")
        if isinstance(brand, dict):
            out["brand"] = brand.get("name")
        elif isinstance(brand, str):
            out["brand"] = brand
        reviews = (
            obj.get("reviews") or obj.get("review_count") or obj.get("total_reviews")
            or obj.get("rating_count") or obj.get("reviewCount") or obj.get("number_of_reviews")
        )
        if reviews is not None:
            try:
                rc = int(reviews) if not isinstance(reviews, list) else len(reviews)
                if 0 < rc < 500_000:
                    out["review_count"] = rc
                    out["has_reviews"] = True
            except (TypeError, ValueError):
                pass
        rating = (
            obj.get("rating") or obj.get("average_rating") or obj.get("avg_rating")
            or obj.get("averageRating") or obj.get("ratingValue")
        )
        if rating is not None:
            try:
                out["avg_rating"] = float(rating)
                out["has_reviews"] = True
            except (TypeError, ValueError):
                pass
        for v in obj.values():
            if isinstance(v, (dict, list)):
                nested = _walk_product_like(v, depth + 1)
                for k, val in nested.items():
                    if k not in out and val not in (None, "", []):
                        out[k] = val
    elif isinstance(obj, list):
        for item in obj[:20]:
            nested = _walk_product_like(item, depth + 1)
            for k, val in nested.items():
                if k not in out and val not in (None, "", []):
                    out[k] = val
    return out


def _score_partial(d: dict[str, Any]) -> int:
    s = 0
    if d.get("product_name"):
        s += 2
    if d.get("price"):
        s += 3
    if d.get("has_reviews") or d.get("review_count"):
        s += 2
    if d.get("brand"):
        s += 1
    return s


def _html_to_visible_text(html: str) -> str:
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
    return unescape(re.sub(r"<[^>]+>", " ", html))
