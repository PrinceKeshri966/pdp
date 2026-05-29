"""
Deterministic DOM / meta / embedded JSON extraction.
"""
from __future__ import annotations

import json
import re
from html import unescape
from app.core.extraction.shopify_theme import extract_visible_sale_price
from app.core.extraction.platform_parity import (
    detect_review_provider,
    extract_visible_review_count,
    reconcile_review_count,
)


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
_COMPARE_AT_RE = re.compile(
    r"(?:M\.?R\.?P\.?|Was|Compare at|Original)[^₹\d]{0,20}"
    r"(?:₹|rs\.?\s*|inr\s*)?\s*([\d,]+(?:\.\d{1,2})?)",
    re.I,
)
_DISCOUNT_RE = re.compile(r"(\d{1,2})\s*%\s*off", re.I)
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
_STAMPED_RE = re.compile(
    r"stamped-(?:badge|reviews-badge|main-badge)[^>]*data-rating=[\"']([\d.]+)[\"']|"
    r"data-reviews-count=[\"'](\d+)[\"']|"
    r"data-rating=[\"']([\d.]+)[\"'][^>]*data-count=[\"'](\d+)[\"']|"
    r"stamped-badge[^>]*data-count=[\"'](\d+)[\"']",
    re.I,
)
_OKENDO_RE = re.compile(
    r"data-oke-reviews[^>]*data-oke-rendered-product-id|"
    r"okeReviews[^>]*data-oke-aggregate-rating=[\"']([\d.]+)[\"']|"
    r"data-oke-aggregate-rating=[\"']([\d.]+)[\"']|"
    r"data-oke-review-count=[\"'](\d+)[\"']|"
    r"oke-w-ratingAverageValue=[\"']([\d.]+)[\"']|"
    r"oke-w-ratingCount=[\"'](\d+)[\"']",
    re.I,
)
_UGC_IMAGE_RE = re.compile(
    r"(?:stamped|okendo|yotpo|loox|judge)[^>]*(?:ugc|photo|image|media)|"
    r"class=[\"'][^\"']*(?:review-photo|review-image|ugc-image|photo-review)",
    re.I,
)
_NETWORK_PRODUCT_URL_HINTS = (
    "product", "graphql", "catalog", "item", "sku", "variant", "api",
    "yotpo", "judge.me", "loox", "stamped", "okendo", "oke-reviews", "reviews", "rating",
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
    cm = _COMPARE_AT_RE.search(text)
    if cm:
        out["compare_at_price"] = cm.group(1).replace(",", "")
    dm = _DISCOUNT_RE.search(text)
    if dm:
        out["discount_pct"] = int(dm.group(1))
    picker = len(re.findall(
        r'select[^>]*name=["\'][^"\']*option|class=["\'][^"\']*swatch|data-variant-id|'
        r'product-form__input[^>]*type=["\']radio["\']',
        html,
        re.I,
    ))
    if picker:
        out["variant_picker_count"] = picker
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
    vp = extract_visible_sale_price(html)
    if vp and vp.get("price"):
        out["price"] = vp["price"]
        out["_visible_price_source"] = vp.get("source")
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
    """Parse Yotpo, Judge.me, Loox, Stamped, Okendo and common review widget DOM markers."""
    out: dict[str, Any] = {}
    blob = f"{html}\n{visible_text or ''}"
    for pattern in (_JUDGE_ME_RE, _YOTPO_RE, _LOOX_RE, _STAMPED_RE, _OKENDO_RE):
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

    # UGC image count from review widget DOM
    ugc_matches = _UGC_IMAGE_RE.findall(blob)
    if ugc_matches:
        out["ugc_image_count"] = len(ugc_matches)
        out["has_ugc_images"] = True

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

    visible_count = extract_visible_review_count(html, visible_text)
    if visible_count is not None:
        out["review_count"] = reconcile_review_count(out.get("review_count"), visible_count) or visible_count
        out["has_reviews"] = True

    provider = detect_review_provider(html)
    if provider:
        out["review_provider"] = provider

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
        if any(p in url for p in ("judge.me", "yotpo", "loox", "stamped", "okendo", "oke-reviews")):
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
        if "stamped" in url:
            widget = body.get("widget") if isinstance(body.get("widget"), dict) else body
            rc = (
                widget.get("count")
                or widget.get("reviews_count")
                or widget.get("total_reviews")
                or body.get("count")
                or body.get("total")
            )
            avg = widget.get("rating") or widget.get("average_rating") or body.get("rating")
            if isinstance(body, list) and body:
                rc = rc or len(body)
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
            # UGC photos in Stamped reviews array
            reviews = body.get("reviews") or body.get("data") or (body if isinstance(body, list) else [])
            if isinstance(reviews, list):
                ugc = sum(
                    1 for r in reviews
                    if isinstance(r, dict) and (r.get("reviewUserPhotos") or r.get("photos") or r.get("images"))
                )
                if ugc:
                    out["ugc_image_count"] = ugc
                    out["has_ugc_images"] = True
        if "okendo" in url or "oke-reviews" in url:
            data = body.get("reviewAggregate") or body.get("aggregate") or body
            if isinstance(data, dict):
                rc = data.get("reviewCount") or data.get("review_count") or data.get("count")
                avg = data.get("ratingAndReviewCountByLevel") or data.get("rating")
                if isinstance(avg, dict):
                    avg = avg.get("average") or avg.get("rating")
                if not avg:
                    avg = data.get("averageRating") or data.get("average_rating")
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
            reviews = body.get("reviews") or []
            if isinstance(reviews, list):
                ugc = sum(
                    1 for r in reviews
                    if isinstance(r, dict) and (r.get("media") or r.get("images") or r.get("photos"))
                )
                if ugc:
                    out["ugc_image_count"] = max(out.get("ugc_image_count") or 0, ugc)
                    out["has_ugc_images"] = True
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
