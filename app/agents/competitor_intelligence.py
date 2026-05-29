"""
Synthesize legacy competitor intelligence fields from live scrape data.

The frontend benchmark panel expects market_positioning, benchmark_scores,
share_of_voice, traffic_estimate, and backlink_gap. The live competitor_agent
produces feature_comparison and live_compare — this module bridges the gap
with deterministic heuristics (no LLM hallucination).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def _parse_price(val: Any) -> float | None:
    if val is None:
        return None
    s = re.sub(r"[^\d.]", "", str(val).replace(",", ""))
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _feature_proxy_scores(feat: dict[str, Any]) -> dict[str, float]:
    """Estimate 0–10 category scores from scraped page features."""
    wc = int(feat.get("page_word_count") or 0)
    imgs = int(feat.get("images_count") or 0)
    has_reviews = bool(feat.get("has_reviews"))
    has_video = bool(feat.get("has_video"))
    has_size = bool(feat.get("has_size_guide"))
    has_return = bool(feat.get("has_return_policy"))
    rating = feat.get("avg_rating")
    review_count = int(feat.get("review_count") or 0)

    content = 4.0
    if wc >= 2000:
        content += 3.0
    elif wc >= 1000:
        content += 2.0
    elif wc >= 500:
        content += 1.0
    elif wc < 200:
        content -= 1.5

    seo = 4.5
    if imgs >= 8:
        seo += 1.5
    elif imgs >= 4:
        seo += 0.8
    if has_reviews:
        seo += 1.2
    if has_return:
        seo += 0.5
    if wc >= 800:
        seo += 0.8

    conversion = 4.0
    if has_reviews:
        conversion += 2.0
    if has_video:
        conversion += 1.0
    if has_size:
        conversion += 0.8
    if rating and float(rating) >= 4.0:
        conversion += 1.0
    if review_count >= 100:
        conversion += 0.5

    ai_vis = 3.5
    if wc >= 1500:
        ai_vis += 2.5
    elif wc >= 800:
        ai_vis += 1.5
    if has_reviews and review_count >= 50:
        ai_vis += 1.0
    if has_video:
        ai_vis += 0.8

    def _clamp(v: float) -> float:
        return round(min(10.0, max(2.0, v)), 1)

    return {
        "avg_seo_score": _clamp(seo),
        "avg_ai_visibility_score": _clamp(ai_vis),
        "avg_conversion_score": _clamp(conversion),
        "avg_content_depth_score": _clamp(content),
    }


def _avg_scores(scores: list[dict[str, float]]) -> dict[str, float]:
    if not scores:
        return {}
    keys = ["avg_seo_score", "avg_ai_visibility_score", "avg_conversion_score", "avg_content_depth_score"]
    out: dict[str, float] = {}
    for k in keys:
        vals = [s[k] for s in scores if k in s]
        out[k] = round(sum(vals) / len(vals), 1) if vals else 5.0
    return out


def _price_tier(your_price: float | None, comp_prices: list[float]) -> str:
    if your_price is None or not comp_prices:
        return "mid-range"
    avg = sum(comp_prices) / len(comp_prices)
    if avg <= 0:
        return "mid-range"
    ratio = your_price / avg
    if ratio < 0.85:
        return "budget"
    if ratio > 1.15:
        return "premium"
    return "mid-range"


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Z0-9]{3,}", text or "")}


def _traffic_tier(review_count: int | None, word_count: int | None) -> str:
    rc = review_count or 0
    wc = word_count or 0
    if rc >= 500 or wc >= 2500:
        return "high"
    if rc >= 50 or wc >= 1000:
        return "medium"
    return "low"


def _authority_tier(review_count: int | None, word_count: int | None, has_reviews: bool) -> str:
    rc = review_count or 0
    wc = word_count or 0
    if rc >= 200 and wc >= 1200 and has_reviews:
        return "high"
    if rc >= 30 or wc >= 600:
        return "medium"
    return "low"


def synthesize_competitor_intelligence(
    *,
    sites: list[dict[str, Any]],
    structured: dict[str, Any],
    gaps: list[str],
    wins: list[str],
    feature_comparison: dict[str, Any],
    benchmark_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build frontend-expected intelligence fields from live scrape artifacts."""
    you_site = next((s for s in sites if s.get("role") == "you"), None)
    comp_sites = [s for s in sites if s.get("role") == "competitor" and s.get("scrape_ok")]
    you_feat = (you_site or {}).get("features") or {}
    comp_feats = [s.get("features") or {} for s in comp_sites]

    if not comp_feats:
        return {}

    comp_scores = [_feature_proxy_scores(f) for f in comp_feats]
    benchmark_scores = _avg_scores(comp_scores)

    your_price = _parse_price(you_feat.get("price") or structured.get("price"))
    comp_prices = [p for p in (_parse_price(f.get("price")) for f in comp_feats) if p is not None]
    price_tier = _price_tier(your_price, comp_prices)
    price_index = round(your_price / (sum(comp_prices) / len(comp_prices)), 2) if your_price and comp_prices else 1.0

    product_name = structured.get("product_name") or you_feat.get("product_name") or ""
    categories = structured.get("categories") or []
    cat_text = " ".join(categories) if isinstance(categories, list) else str(categories)
    your_tokens = _tokenize(f"{product_name} {cat_text}")

    shared_kw: set[str] = set()
    unique_kw: set[str] = set(your_tokens)
    for cf in comp_feats:
        comp_tokens = _tokenize(cf.get("product_name") or "")
        overlap = your_tokens & comp_tokens
        shared_kw |= overlap
        unique_kw -= comp_tokens

    overlap_pct = round(100 * len(shared_kw) / max(len(your_tokens), 1), 0) if your_tokens else 0
    top_shared = sorted(shared_kw, key=len, reverse=True)[:10]
    if not top_shared and categories:
        top_shared = [str(c) for c in (categories[:6] if isinstance(categories, list) else [categories])]

    your_rc = int(you_feat.get("review_count") or structured.get("review_count") or 0)
    your_wc = int(you_feat.get("page_word_count") or structured.get("page_word_count") or 0)
    comp_rc_avg = feature_comparison.get("avg_review_count") or 0
    comp_wc_avg = feature_comparison.get("description_word_count_avg") or 0

    your_traffic = _traffic_tier(your_rc, your_wc)
    comp_traffic_vals = [_traffic_tier(int(f.get("review_count") or 0), int(f.get("page_word_count") or 0)) for f in comp_feats]
    tier_rank = {"low": 1, "medium": 2, "high": 3}
    comp_avg_rank = sum(tier_rank.get(t, 2) for t in comp_traffic_vals) / max(len(comp_traffic_vals), 1)
    comp_avg_tier = "high" if comp_avg_rank >= 2.5 else ("medium" if comp_avg_rank >= 1.5 else "low")

    if tier_rank.get(your_traffic, 2) > comp_avg_rank:
        traffic_gap = "Your page signals suggest stronger organic/traffic potential than scraped competitors on this PDP."
    elif tier_rank.get(your_traffic, 2) < comp_avg_rank:
        traffic_gap = "Competitors show stronger social proof or content depth signals — invest in reviews and PDP copy."
    else:
        traffic_gap = "Traffic tier is comparable to scraped competitors on comparable PDP URLs."

    your_auth = _authority_tier(your_rc, your_wc, bool(you_feat.get("has_reviews")))
    comp_auth_vals = [
        _authority_tier(int(f.get("review_count") or 0), int(f.get("page_word_count") or 0), bool(f.get("has_reviews")))
        for f in comp_feats
    ]
    auth_rank = {"low": 1, "medium": 2, "high": 3}
    comp_auth_avg = sum(auth_rank.get(a, 2) for a in comp_auth_vals) / max(len(comp_auth_vals), 1)
    comp_auth_tier = "high" if comp_auth_avg >= 2.5 else ("medium" if comp_auth_avg >= 1.5 else "low")

    if auth_rank.get(your_auth, 2) >= comp_auth_avg:
        backlink_rec = "Maintain authority edge with structured data, review volume, and linkable product guides."
    else:
        backlink_rec = "Close authority gap with PR, expert reviews, and comparison content targeting category keywords."

    differentiation = wins[0] if wins else (gaps[0] if gaps else None)
    target_segment = cat_text.strip() or product_name or "Category shoppers comparing similar PDPs"

    bm = benchmark_metrics or {}
    confidence = float(bm.get("confidence") or 0.65)

    return {
        "benchmark_scores": benchmark_scores,
        "market_positioning": {
            "price_tier": price_tier,
            "price_positioning_index": price_index,
            "target_segment": target_segment[:200],
            "differentiation": (differentiation or "—")[:300],
            "market_maturity": "growing",
        },
        "share_of_voice": {
            "estimated_keyword_overlap_pct": int(overlap_pct),
            "top_shared_keywords": top_shared or ["category keywords"],
            "your_unique_keywords": sorted(unique_kw, key=len, reverse=True)[:8],
            "_confidence": confidence,
        },
        "traffic_estimate": {
            "your_tier": your_traffic,
            "competitor_avg_tier": comp_avg_tier,
            "gap_assessment": traffic_gap,
            "_signals": {"your_review_count": your_rc, "comp_avg_reviews": comp_rc_avg, "your_word_count": your_wc},
        },
        "backlink_gap": {
            "your_authority_estimate": your_auth,
            "competitor_avg_authority": comp_auth_tier,
            "recommendation": backlink_rec,
        },
        "first_mover_opportunities": _first_mover_opportunities(you_feat, comp_feats, gaps),
        "category_best_practices": _category_best_practices(comp_feats, feature_comparison),
    }


def _first_mover_opportunities(you: dict, comps: list[dict], gaps: list[str]) -> list[str]:
    opps: list[str] = []
    comp_has_video_pct = sum(1 for c in comps if c.get("has_video")) / max(len(comps), 1)
    if not you.get("has_video") and comp_has_video_pct < 0.34:
        opps.append("Add product video — fewer than one-third of scraped competitors have video on comparable PDPs.")
    if not you.get("has_size_guide") and sum(1 for c in comps if c.get("has_size_guide")) / max(len(comps), 1) < 0.5:
        opps.append("Publish a size/fit guide — most competitors in this scrape set lack one.")
    if not you.get("has_reviews"):
        opps.append("Launch verified reviews — social proof is a category baseline for conversion.")
    for g in gaps[:3]:
        if g not in opps:
            opps.append(g)
    return opps[:6]


def _category_best_practices(comps: list[dict], fc: dict[str, Any]) -> list[str]:
    practices: list[str] = []
    if (fc.get("has_reviews_pct") or 0) >= 50:
        practices.append(f"{int(fc.get('has_reviews_pct') or 0)}% of scraped competitors display customer reviews on the PDP.")
    avg_imgs = fc.get("product_images_avg")
    if avg_imgs:
        practices.append(f"Category average: {avg_imgs} product images per PDP — use multi-angle galleries.")
    avg_wc = fc.get("description_word_count_avg")
    if avg_wc:
        practices.append(f"Competitors average {int(avg_wc)} words of PDP copy — depth supports SEO and AI visibility.")
    if (fc.get("has_video_pct") or 0) >= 30:
        practices.append(f"{int(fc.get('has_video_pct') or 0)}% of competitors include product video — consider demo content.")
    if not practices:
        practices.append("Run live competitor compare with 2+ scraped PDPs for category-specific best practices.")
    return practices[:5]
