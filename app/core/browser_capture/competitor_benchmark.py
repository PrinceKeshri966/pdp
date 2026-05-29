"""
Competitor benchmarking metrics for side-by-side comparison.
"""
from __future__ import annotations

from typing import Any


def build_benchmark_metrics(
    your_features: dict[str, Any],
    competitor_features: list[dict[str, Any]],
    *,
    your_lighthouse: dict[str, Any] | None = None,
    your_schema: dict[str, Any] | None = None,
    competitor_lighthouse: list[dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Build SEMrush-style benchmark comparison matrix."""
    if not competitor_features:
        return {"available": False, "confidence": 0.0}

    def _avg_comp(key: str, default=0):
        vals = [c.get(key) for c in competitor_features if c.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else default

    your_wc = your_features.get("page_word_count") or 0
    your_imgs = your_features.get("images_count") or 0
    your_reviews = your_features.get("has_reviews") or False
    your_rating = your_features.get("avg_rating")
    your_video = your_features.get("has_video") or False

    comp_wc_avg = _avg_comp("page_word_count")
    comp_imgs_avg = _avg_comp("images_count")
    comp_reviews_pct = round(
        sum(1 for c in competitor_features if c.get("has_reviews")) / len(competitor_features) * 100, 0
    )
    comp_ratings = [c.get("avg_rating") for c in competitor_features if c.get("avg_rating")]
    comp_rating_avg = round(sum(comp_ratings) / len(comp_ratings), 1) if comp_ratings else None
    comp_video_pct = round(
        sum(1 for c in competitor_features if c.get("has_video")) / len(competitor_features) * 100, 0
    )

    metrics: list[dict[str, Any]] = [
        {
            "metric": "word_count",
            "yours": your_wc,
            "competitor_avg": comp_wc_avg,
            "delta": your_wc - comp_wc_avg,
            "verdict": "ahead" if your_wc > comp_wc_avg * 1.1 else ("behind" if your_wc < comp_wc_avg * 0.9 else "parity"),
        },
        {
            "metric": "images_count",
            "yours": your_imgs,
            "competitor_avg": comp_imgs_avg,
            "delta": your_imgs - comp_imgs_avg,
            "verdict": "ahead" if your_imgs > comp_imgs_avg else "behind" if your_imgs < comp_imgs_avg * 0.8 else "parity",
        },
        {
            "metric": "reviews_present",
            "yours": your_reviews,
            "competitor_pct": comp_reviews_pct,
            "verdict": "ahead" if your_reviews and comp_reviews_pct < 80 else ("behind" if not your_reviews and comp_reviews_pct > 50 else "parity"),
        },
        {
            "metric": "avg_rating",
            "yours": your_rating,
            "competitor_avg": comp_rating_avg,
            "verdict": "ahead" if your_rating and comp_rating_avg and your_rating > comp_rating_avg else "parity",
        },
        {
            "metric": "video_present",
            "yours": your_video,
            "competitor_pct": comp_video_pct,
            "verdict": "ahead" if your_video and comp_video_pct < 50 else ("behind" if not your_video and comp_video_pct > 30 else "parity"),
        },
    ]

    if your_lighthouse and your_lighthouse.get("available"):
        your_perf = (your_lighthouse.get("categories") or {}).get("performance", 0)
        comp_perfs = [
            (lh or {}).get("categories", {}).get("performance", 0)
            for lh in (competitor_lighthouse or [])
            if lh and lh.get("available")
        ]
        if comp_perfs:
            comp_perf_avg = round(sum(comp_perfs) / len(comp_perfs), 0)
            metrics.append({
                "metric": "performance_score",
                "yours": your_perf,
                "competitor_avg": comp_perf_avg,
                "delta": your_perf - comp_perf_avg,
                "verdict": "ahead" if your_perf > comp_perf_avg + 5 else ("behind" if your_perf < comp_perf_avg - 5 else "parity"),
            })

    if your_schema and your_schema.get("detected_types"):
        metrics.append({
            "metric": "schema_types",
            "yours": your_schema.get("detected_types", []),
            "verdict": "ahead" if len(your_schema.get("detected_types", [])) >= 2 else "parity",
        })

    ahead = sum(1 for m in metrics if m.get("verdict") == "ahead")
    behind = sum(1 for m in metrics if m.get("verdict") == "behind")
    overall = round(ahead / max(len(metrics), 1) * 10, 1)

    return {
        "available": True,
        "metrics": metrics,
        "ahead_count": ahead,
        "behind_count": behind,
        "parity_count": len(metrics) - ahead - behind,
        "competitive_score": overall,
        "confidence": 0.8 if len(competitor_features) >= 2 else 0.65,
    }
