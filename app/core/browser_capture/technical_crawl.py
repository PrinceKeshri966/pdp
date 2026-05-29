"""
Technical SEO crawling: robots.txt, sitemap.xml, redirects, canonicals, hreflang, OG, Twitter Cards.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.html_metadata import BROWSER_UA

_FETCH_TIMEOUT = 15.0


def _extract_link_rel(html: str, rel: str) -> list[str]:
    hrefs: list[str] = []
    pattern = re.compile(
        rf'<link[^>]*rel=["\']{rel}["\'][^>]*href=["\']([^"\']+)["\']',
        re.I,
    )
    hrefs.extend(m.group(1) for m in pattern.finditer(html))
    pattern2 = re.compile(
        rf'<link[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']{rel}["\']',
        re.I,
    )
    hrefs.extend(m.group(1) for m in pattern2.finditer(html))
    return hrefs


def _extract_hreflang(html: str) -> list[dict[str, str]]:
    tags: list[dict[str, str]] = []
    for m in re.finditer(
        r'<link[^>]*rel=["\']alternate["\'][^>]*hreflang=["\']([^"\']+)["\'][^>]*href=["\']([^"\']+)["\']',
        html,
        re.I,
    ):
        tags.append({"lang": m.group(1), "href": m.group(2)})
    for m in re.finditer(
        r'<link[^>]*hreflang=["\']([^"\']+)["\'][^>]*href=["\']([^"\']+)["\']',
        html,
        re.I,
    ):
        tags.append({"lang": m.group(1), "href": m.group(2)})
    return tags


def _extract_og_tags(html: str) -> dict[str, str]:
    og: dict[str, str] = {}
    for m in re.finditer(
        r'<meta[^>]*property=["\']og:([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']',
        html,
        re.I,
    ):
        og[m.group(1)] = unescape(m.group(2)).strip()
    for m in re.finditer(
        r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:([^"\']+)["\']',
        html,
        re.I,
    ):
        og[m.group(2)] = unescape(m.group(1)).strip()
    return og


def _extract_twitter_tags(html: str) -> dict[str, str]:
    tw: dict[str, str] = {}
    for m in re.finditer(
        r'<meta[^>]*name=["\']twitter:([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']',
        html,
        re.I,
    ):
        tw[m.group(1)] = unescape(m.group(2)).strip()
    for m in re.finditer(
        r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']twitter:([^"\']+)["\']',
        html,
        re.I,
    ):
        tw[m.group(2)] = unescape(m.group(1)).strip()
    return tw


async def _fetch_text(client: httpx.AsyncClient, url: str) -> tuple[str, int, str]:
    try:
        resp = await client.get(url, follow_redirects=True)
        return resp.text[:50_000], resp.status_code, str(resp.url)
    except Exception:
        return "", 0, url


async def crawl_technical_seo(
    url: str,
    html: str = "",
    *,
    redirect_chain: list[str] | None = None,
    final_url: str = "",
) -> dict[str, Any]:
    """Crawl robots.txt, sitemap, and parse on-page technical SEO signals."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = urljoin(base, "/robots.txt")
    sitemap_url = urljoin(base, "/sitemap.xml")

    robots_txt = ""
    robots_status = 0
    sitemap_found = False
    sitemap_urls: list[str] = []
    redirect_count = max(0, len(redirect_chain or []) - 1) if redirect_chain else 0

    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": BROWSER_UA},
    ) as client:
        robots_txt, robots_status, _ = await _fetch_text(client, robots_url)
        sitemap_body, sitemap_status, _ = await _fetch_text(client, sitemap_url)
        sitemap_found = sitemap_status == 200 and ("<urlset" in sitemap_body or "<sitemapindex" in sitemap_body)
        if sitemap_found:
            sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", sitemap_body)[:20]

        if not redirect_chain:
            try:
                resp = await client.get(url, follow_redirects=False)
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_count = 1
            except Exception:
                pass

    canonicals = _extract_link_rel(html, "canonical")
    hreflang = _extract_hreflang(html)
    og_tags = _extract_og_tags(html)
    twitter_tags = _extract_twitter_tags(html)

    canonical_match = False
    if canonicals and final_url:
        canon = canonicals[0].rstrip("/")
        final = final_url.rstrip("/")
        canonical_match = canon == final or canon in final or final in canon

    issues: list[str] = []
    if redirect_count > 2:
        issues.append(f"Long redirect chain ({redirect_count} hops)")
    if not canonicals:
        issues.append("Missing canonical tag")
    elif not canonical_match and final_url:
        issues.append("Canonical URL may not match final URL")
    if not og_tags.get("title"):
        issues.append("Missing og:title")
    if not og_tags.get("description"):
        issues.append("Missing og:description")
    if not twitter_tags.get("card"):
        issues.append("Missing twitter:card")
    if robots_status == 200:
        if "Disallow: /" in robots_txt and "Allow:" not in robots_txt:
            issues.append("robots.txt blocks all crawlers")
    if not sitemap_found:
        issues.append("sitemap.xml not found or invalid")

    score_items = [
        bool(canonicals),
        canonical_match or not final_url,
        bool(og_tags.get("title")),
        bool(og_tags.get("description")),
        bool(twitter_tags.get("card")),
        bool(hreflang) or True,  # hreflang optional
        sitemap_found,
        bool(robots_txt),
        redirect_count <= 2,
    ]
    score = round(sum(1 for x in score_items if x) / len(score_items) * 10, 1)

    return {
        "robots_txt": {
            "url": robots_url,
            "found": bool(robots_txt),
            "status": robots_status if robots_txt else 404,
            "preview": robots_txt[:500] if robots_txt else "",
        },
        "sitemap": {
            "url": sitemap_url,
            "found": sitemap_found,
            "url_count": len(sitemap_urls),
            "sample_urls": sitemap_urls[:5],
        },
        "redirects": {
            "chain": redirect_chain or [],
            "count": redirect_count,
            "final_url": final_url or url,
        },
        "canonical": {
            "present": bool(canonicals),
            "urls": canonicals,
            "matches_final": canonical_match,
        },
        "hreflang": {"present": bool(hreflang), "tags": hreflang[:10]},
        "open_graph": {"present": bool(og_tags), "tags": og_tags},
        "twitter_cards": {"present": bool(twitter_tags), "tags": twitter_tags},
        "issues": issues,
        "score": score,
        "confidence": round(min(1.0, score / 10), 2),
    }
