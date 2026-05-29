"""
app/agents/competitor_discovery.py

Discover real market category competitor URLs via context-aware Jina search execution lines.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlparse

import httpx

from app.core.config import get_settings

_LINK_RE = re.compile(r"https?://[^\s\)\]\"'<>]+", re.I)
_SOURCE_RE = re.compile(r"URL Source:\s*(https?://\S+)", re.I)
_SKIP_DOMAINS = {
    "google.com",
    "google.co.in",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "pinterest.com",
    "linkedin.com",
    "amazon.com",
    "amazon.in",
    "flipkart.com",
    "wikipedia.org",
}
# Marketplaces / aggregators — not direct D2C competitors
_MARKETPLACE_DOMAINS = frozenset({
    "amazon.in", "amazon.com", "flipkart.com", "myntra.com", "ajio.com",
    "nykaa.com", "snapdeal.com", "paytmmall.com", "meesho.com",
    "lifestylestores.com", "shoppersstop.com", "reliancedigital.in",
    "croma.com", "tatacliq.com", "jiomart.com",
})
# Unrelated mega-brands when comparing D2C / retail / electronics homepages
_UNRELATED_RETAIL_COMPETITORS = frozenset({
    "meta.com",
    "about.meta.com",
    "meta.ai",
    "facebook.com",
    "instagram.com",
    "threads.com",
    "threads.net",
    "microsoft.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "google.com",
    "wikipedia.org",
})
_PRODUCT_PATH_MARKERS = ("/product", "/products/", "/p/", "/dp/", "/item/", "/buy", "/shop/")


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def resolve_homepage_mode(user_url: str, compare_as: str | None = None) -> bool:
    """Evaluate layout configuration routing matrices to determine verification level."""
    mode = (compare_as or "auto").lower().strip()
    if mode == "homepage":
        return True
    if mode == "product":
        return False
    return is_homepage_url(user_url)


def is_homepage_url(url: str) -> bool:
    """Validate resource depth strings to ensure location context boundaries match root hierarchies."""
    try:
        raw = url if url.startswith("http") else f"https://{url}"
        u = urlparse(raw)
        path = (u.path or "/").strip().rstrip("/") or "/"
        if path == "/":
            return True
        low = path.lower()
        if any(marker in low for marker in _PRODUCT_PATH_MARKERS):
            return False
        segments = [s for s in path.split("/") if s]
        return len(segments) <= 1
    except Exception:
        return False


def to_site_root(url: str) -> str:
    """Truncate complex address paths down to top-level secure domains safely."""
    u = urlparse(url if url.startswith("http") else f"https://{url}")
    scheme = u.scheme or "https"
    netloc = u.netloc
    return f"{scheme}://{netloc}/"


def _is_main_brand_site(url: str, *, homepage_mode: bool) -> bool:
    """Skip blog/store subdomains when comparing homepage competitors."""
    if not homepage_mode:
        return True
    u = urlparse(url if url.startswith("http") else f"https://{url}")
    dom = u.netloc.lower().replace("www.", "")
    path = (u.path or "/").strip().rstrip("/") or "/"
    if path != "/":
        return False
    if dom.startswith(("blog.", "shop.", "store.", "m.", "app.", "news.")):
        return False
    if any(x in dom for x in (".blog.", ".shop.")):
        return False
    return True


def _is_productish(url: str) -> bool:
    """Confirm location extensions describe conversion endpoints vs asset files."""
    low = url.lower()
    if any(ext in low for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")):
        return False
    if "/media/" in low or "/catalog/" in low:
        return False
    path = urlparse(url).path.lower()
    if path in ("", "/"):
        return False
    if any(x in path for x in _PRODUCT_PATH_MARKERS):
        return True
    return path.count("/") >= 2 and len(path) > 10


def _url_score(url: str, *, homepage_mode: bool) -> int:
    """Calculate contextual weights to optimize engine placement hierarchies."""
    path = urlparse(url).path.lower()
    if homepage_mode:
        if path in ("", "/"):
            return 20
        return -10
    score = 0
    if "/products/" in path or "/product/" in path:
        score += 20
    if "/dp/" in path or "/p/" in path:
        score += 15
    if "/collections/" in path or "/search" in path or "/cart" in path:
        score -= 10
    return score


def _extract_urls(text: str) -> list[str]:
    """Isolate clean web nodes from textual target outputs completely."""
    ordered: list[str] = []
    seen: set[str] = set()
    for pattern in (_SOURCE_RE, _LINK_RE):
        for match in pattern.finditer(text):
            url = match.group(1 if pattern is _SOURCE_RE else 0).rstrip(".,;)")
            if url not in seen:
                seen.add(url)
                ordered.append(url)
    return ordered


def _brand_from_domain(user_domain: str) -> str:
    """e.g. boat-lifestyle.com → boat lifestyle (avoid ambiguous single token 'boat')."""
    base = (user_domain or "").split(".")[0].replace("www.", "")
    return base.replace("-", " ").strip()


def _detect_vertical(
    *,
    categories: list[str],
    user_domain: str,
    product_name: str,
) -> str:
    blob = " ".join(categories + [_brand_from_domain(user_domain), product_name or "", user_domain]).lower()
    if any(
        m in blob
        for m in ("fitness", "gym", "workout", "fitpass", "nutrition", "yoga", "cult.fit")
    ):
        return "fitness"
    if any(
        m in blob
        for m in (
            "audio",
            "earbud",
            "earphone",
            "speaker",
            "watch",
            "wearable",
            "electronics",
            "lifestyle",
            "boat",
            "noise",
            "fire-boltt",
            "boltt",
            "smartwatch",
        )
    ):
        return "electronics"
    if any(m in blob for m in ("fashion", "apparel", "clothing", "beauty", "skincare", "cosmetic", "jeans", "denim")):
        return "fashion"
    return "general"


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 2}


def _semantic_similarity(product_name: str, categories: list[str], candidate_url: str) -> float:
    """Simple token overlap between product context and candidate URL/domain."""
    ctx_tokens = _tokenize(" ".join(categories + [product_name or ""]))
    cand_tokens = _tokenize(candidate_url)
    if not ctx_tokens or not cand_tokens:
        return 0.0
    overlap = len(ctx_tokens & cand_tokens)
    return overlap / max(len(ctx_tokens), 1)


def _is_irrelevant_competitor(
    user_domain: str,
    candidate_domain: str,
    vertical: str,
    *,
    product_name: str = "",
    categories: list[str] | None = None,
    candidate_url: str = "",
) -> bool:
    if not candidate_domain or candidate_domain == user_domain:
        return True
    if candidate_domain in _SKIP_DOMAINS:
        return True
    if candidate_domain in _MARKETPLACE_DOMAINS:
        return True
    if vertical in ("electronics", "fashion", "fitness", "general"):
        if candidate_domain in _UNRELATED_RETAIL_COMPETITORS:
            return True
        if "meta" in candidate_domain and "meta" not in user_domain:
            return True
        if candidate_domain.startswith(("about.", "blog.", "shop.")) and vertical == "electronics":
            return True
    # Reject semantically unrelated candidates for PDP mode
    if product_name and candidate_url:
        sim = _semantic_similarity(product_name, categories or [], candidate_url)
        ctx = _tokenize(product_name)
        cand = _tokenize(candidate_domain)
        if ctx and cand and not (ctx & cand) and sim < 0.05:
            unrelated_verticals = {
                "electronics": {"fashion", "beauty", "skincare", "gym", "fitness"},
                "fashion": {"audio", "earbud", "speaker", "smartwatch", "electronics"},
                "fitness": {"earbud", "skincare", "cosmetic", "jeans", "fashion"},
            }
            prod_vertical_tokens = unrelated_verticals.get(vertical, set())
            if prod_vertical_tokens & cand:
                return True
    return False


def _search_queries(
    *,
    homepage_mode: bool,
    product_name: str,
    categories: list[str],
    user_domain: str,
) -> list[str]:
    """Build highly distinct contextual queries dynamically using processed semantic attributes."""
    # Clean out platform-generic navigation values dynamically
    sanitized_categories = [
        c.strip() for c in categories 
        if c.lower() not in ("home", "product", "products", "all", "services", "app", "mobile app")
    ]
    
    # Resolve product business focus category directly
    if sanitized_categories:
        cat_context = sanitized_categories[-1]
    elif product_name:
        cat_context = product_name.split("-")[0].split("|")[0].strip()
    else:
        cat_context = "e-commerce marketplace"

    name_clean = (product_name or cat_context).split("-")[0].split("|")[0].strip()[:50]
    brand_context = _brand_from_domain(user_domain)
    vertical = _detect_vertical(
        categories=categories,
        user_domain=user_domain,
        product_name=product_name,
    )

    if homepage_mode:
        if vertical == "fitness":
            return [
                "cult.fit official website india gym membership",
                "fittr.com fitness coaching app india",
                "healthifyme.com official website india",
                f"gym membership app india alternatives to {brand_context or 'fitpass'}",
            ]
        if vertical == "electronics":
            b = brand_context or name_clean or "audio brand"
            return [
                f"noise.com official website india earbuds",
                f"fire-boltt.com india smartwatch audio official",
                f"best {b} competitors india consumer electronics brand website",
                f"india D2C audio wearable brands like {b} official homepage",
            ]
        if vertical == "fashion":
            b = brand_context or name_clean
            return [
                f"nykaa fashion brand india official website competitors",
                f"mamaearth official website india beauty brand",
                f"best {b} alternatives india D2C fashion brand homepage",
            ]
        queries = [
            f"top alternative brands to {brand_context or name_clean} india official website",
            f"best {cat_context} brands india D2C official homepage",
        ]
        if brand_context:
            queries.append(f"direct competitors of {brand_context} india same industry official site")
        return queries

    if vertical == "electronics":
        return [
            f"buy {name_clean} earbuds alternatives india product page",
            f"competing {cat_context} audio product PDP india",
        ]
    return [
        f"buy {name_clean} alternatives online india",
        f"top competing {cat_context} product pages in india",
    ]


async def discover_competitor_urls(
    user_url: str,
    product_name: str,
    categories: list[str],
    *,
    existing: list[str] | None = None,
    limit: int = 3,
    homepage_mode: bool | None = None,
) -> list[str]:
    """Execute live external crawling strategies to retrieve localized competing assets accurately."""
    settings = get_settings()
    user_domain = _domain(user_url)
    if homepage_mode is None:
        homepage_mode = is_homepage_url(user_url)

    found: list[str] = []
    seen_domains: set[str] = {user_domain}

    for u in existing or []:
        norm = to_site_root(u) if homepage_mode else u.split("#")[0]
        d = _domain(norm)
        if d and d not in seen_domains:
            found.append(norm)
            seen_domains.add(d)
        if len(found) >= limit:
            return found[:limit]

    headers: dict[str, str] = {"Accept": "text/plain", "User-Agent": "OptiPDP/1.0"}
    if settings.jina_api_key.strip():
        headers["Authorization"] = f"Bearer {settings.jina_api_key.strip()}"

    vertical = _detect_vertical(
        categories=categories,
        user_domain=user_domain,
        product_name=product_name,
    )
    queries = _search_queries(
        homepage_mode=homepage_mode,
        product_name=product_name,
        categories=categories,
        user_domain=user_domain,
    )

    try:
        async with httpx.AsyncClient(timeout=55.0, follow_redirects=True) as client:
            for query in queries:
                if len(found) >= limit:
                    break
                resp = await client.get(f"https://s.jina.ai/{quote(query)}", headers=headers)
                resp.raise_for_status()
                candidates = sorted(
                    _extract_urls(resp.text),
                    key=lambda u: _url_score(u, homepage_mode=homepage_mode),
                    reverse=True,
                )
                for url in candidates:
                    dom = _domain(url)
                    if not dom or dom in seen_domains or dom == user_domain:
                        continue
                    if _is_irrelevant_competitor(
                        user_domain, dom, vertical,
                        product_name=product_name,
                        categories=categories,
                        candidate_url=url,
                    ):
                        continue
                    if any(dom == s or dom.endswith("." + s) for s in _SKIP_DOMAINS):
                        continue
                    if homepage_mode:
                        norm = to_site_root(url)
                        if not _is_main_brand_site(norm, homepage_mode=True):
                            continue
                    else:
                        if not _is_productish(url):
                            continue
                        norm = url.split("#")[0]
                    found.append(norm)
                    seen_domains.add(dom)
                    if len(found) >= limit:
                        break
    except Exception:
        pass

    return found[:limit]