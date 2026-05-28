"""
app/agents/context_router.py

Strategic multi-page crawl (depth 1, same-domain), page classification,
compact structured summaries, and agent-specific context packages.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.agents.page_fetch import fetch_page_markdown
from app.agents.scraper_agent import _extract_dom_metadata
from app.agents.seo_preprocessor import extract_seo_facts
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_STRATEGIC_PAGES = 5
MAX_CRAWL_DEPTH = 1
_MAX_HTML_FOR_LINKS = 120_000
_MAX_HEADINGS = 12
_MAX_PARAS = 5
_MAX_PARA_CHARS = 280
_MAX_TRUST = 10
_MAX_CTAS = 8
_MAX_REVIEWS = 5
_HTTP_TIMEOUT = 25.0
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PAGE_ROLES = ("main", "faq", "about", "shipping", "returns", "reviews")

_ROLE_URL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("faq", re.compile(r"(?:/faq|frequently-asked|help/faq|/faqs|questions-answers)", re.I)),
    ("about", re.compile(r"(?:/about|our-story|who-we-are|/company|/team\b)", re.I)),
    ("shipping", re.compile(r"(?:/shipping|/delivery|dispatch|ship-to)", re.I)),
    ("returns", re.compile(r"(?:/return|/refund|exchange-policy|money-back)", re.I)),
    ("reviews", re.compile(r"(?:/review|testimonial|customer-stories|/ratings)", re.I)),
]

_ROLE_HEADING_KEYWORDS: dict[str, re.Pattern[str]] = {
    "faq": re.compile(r"\b(faq|frequently asked|questions)\b", re.I),
    "about": re.compile(r"\b(about us|our story|who we are|our mission)\b", re.I),
    "shipping": re.compile(r"\b(shipping|delivery|dispatch)\b", re.I),
    "returns": re.compile(r"\b(return|refund|exchange)\b", re.I),
    "reviews": re.compile(r"\b(reviews?|testimonials?|what customers say)\b", re.I),
}

_TRUST_PATTERNS = re.compile(
    r"(secure|ssl|verified|trusted|guarantee|money.?back|free shipping|"
    r"certified|award|iso|pci|norton|mcafee|\d+\+?\s*(reviews?|ratings?)|"
    r"\d\.\d\s*/\s*5|★|stars?)",
    re.I,
)
_CTA_PATTERNS = re.compile(
    r"\b(add to cart|buy now|shop now|get started|sign up|subscribe|"
    r"download|order now|try free|book now|join now|learn more)\b",
    re.I,
)
_BOILERPLATE_HTML = re.compile(
    r"<(nav|footer|header)[^>]*>[\s\S]*?</\1>",
    re.I,
)
_COOKIE_HTML = re.compile(
    r'<[^>]*(?:cookie|gdpr|consent|banner)[^>]*>[\s\S]{0,8000}?</[^>]+>',
    re.I,
)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


def _same_domain(base: str, link: str) -> bool:
    b = urlparse(base)
    l = urlparse(urljoin(base, link))
    if not l.netloc:
        return True
    return l.netloc.lower().replace("www.", "") == b.netloc.lower().replace("www.", "")


def _classify_url(url: str) -> str | None:
    path = urlparse(url).path.lower()
    full = (path + " " + urlparse(url).query.lower()).strip()
    for role, pat in _ROLE_URL_PATTERNS:
        if pat.search(full):
            return role
    return None


def _classify_by_headings(text: str) -> str | None:
    for h in re.finditer(r"^#{1,3}\s+(.+)$", text, re.M):
        line = h.group(1).strip()
        for role, pat in _ROLE_HEADING_KEYWORDS.items():
            if pat.search(line):
                return role
    for m in re.finditer(r"<h[1-3][^>]*>([\s\S]*?)</h[1-3]>", text, re.I):
        line = unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        for role, pat in _ROLE_HEADING_KEYWORDS.items():
            if pat.search(line):
                return role
    return None


def _extract_internal_links(base_url: str, html: str, markdown: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str) -> None:
        if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:")):
            return
        abs_url = urljoin(base_url, raw.split("#")[0].strip())
        if not _same_domain(base_url, abs_url):
            return
        norm = _normalize_url(abs_url)
        if norm in seen or norm == _normalize_url(base_url):
            return
        seen.add(norm)
        out.append(abs_url)

    if html:
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.I):
            add(m.group(1))
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", markdown or ""):
        add(m.group(2))
    return out


def _strip_boilerplate_html(html: str) -> str:
    text = _BOILERPLATE_HTML.sub(" ", html)
    text = _COOKIE_HTML.sub(" ", text)
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<noscript[^>]*>[\s\S]*?</noscript>", " ", text, flags=re.I)
    return text


def _html_to_clean_text(html: str) -> str:
    body = _strip_boilerplate_html(html)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", unescape(body)).strip()


def _extract_headings(html: str, text: str) -> list[dict[str, str]]:
    headings: list[dict[str, str]] = []
    for tag in ("h1", "h2", "h3"):
        for m in re.finditer(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", html or "", re.I):
            t = unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip()
            if t and len(t) < 200:
                headings.append({"level": tag, "text": t})
    for m in re.finditer(r"^(#{1,3})\s+(.+)$", text or "", re.M):
        level = f"h{len(m.group(1))}"
        headings.append({"level": level, "text": m.group(2).strip()[:200]})
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for h in headings:
        key = (h["level"], h["text"].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(h)
        if len(deduped) >= _MAX_HEADINGS:
            break
    return deduped


def _key_paragraphs(text: str) -> list[str]:
    chunks = re.split(r"\n{2,}|\.\s+", text)
    paras: list[str] = []
    for c in chunks:
        c = c.strip()
        if len(c) < 40:
            continue
        if _CTA_PATTERNS.search(c) and len(c) < 80:
            continue
        paras.append(c[:_MAX_PARA_CHARS])
        if len(paras) >= _MAX_PARAS:
            break
    return paras


def _trust_signals(text: str) -> list[str]:
    found: list[str] = []
    for m in _TRUST_PATTERNS.finditer(text):
        snippet = text[max(0, m.start() - 20) : m.end() + 40].strip()
        snippet = re.sub(r"\s+", " ", snippet)[:120]
        if snippet and snippet not in found:
            found.append(snippet)
        if len(found) >= _MAX_TRUST:
            break
    return found


def _cta_examples(text: str) -> list[str]:
    ctas: list[str] = []
    for m in _CTA_PATTERNS.finditer(text):
        ctas.append(m.group(0).strip().title())
        if len(ctas) >= _MAX_CTAS:
            break
    return list(dict.fromkeys(ctas))


def _review_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    for m in re.finditer(
        r'(?:review|rating|stars?|said|customer)[^.!?]{10,180}[.!?]',
        text,
        re.I,
    ):
        s = re.sub(r"\s+", " ", m.group(0)).strip()[:200]
        if s not in snippets:
            snippets.append(s)
        if len(snippets) >= _MAX_REVIEWS:
            break
    return snippets


def _schema_from_html(html: str) -> dict[str, Any]:
    types: list[str] = []
    for script in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
        html or "",
        re.I,
    ):
        block = script.group(1).lower()
        for t in ("product", "faqpage", "organization", "website", "review", "breadcrumb"):
            if f'"{t}"' in block or f"'{t}'" in block:
                label = t.title() if t != "faqpage" else "FAQPage"
                if label not in types:
                    types.append(label)
    return {"detected": bool(types), "types": types[:8]}


def _keyword_hints(title: str | None, headings: list[dict[str, str]], paras: list[str]) -> list[str]:
    blob = " ".join(
        [title or ""]
        + [h["text"] for h in headings[:5]]
        + paras[:2]
    ).lower()
    words = re.findall(r"[a-z]{4,}", blob)
    stop = {
        "that", "this", "with", "from", "your", "have", "will", "more", "about",
        "home", "page", "shop", "cart", "free", "best", "also", "they", "their",
    }
    freq: dict[str, int] = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:12]]


def build_page_summary(
    url: str,
    role: str,
    *,
    markdown: str | None = None,
    html: str | None = None,
    dom_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compact structured page summary (no raw markdown dump)."""
    text = ""
    if html:
        text = _html_to_clean_text(html)
    elif markdown:
        text = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", markdown)
        text = re.sub(r"#{1,6}\s+", "", text)
        text = re.sub(r"\s+", " ", text).strip()

    headings = _extract_headings(html or "", markdown or text)
    paras = _key_paragraphs(text)
    title = None
    if dom_meta and dom_meta.get("title_tag"):
        title = dom_meta["title_tag"]
    elif headings:
        h1s = [h["text"] for h in headings if h["level"] == "h1"]
        title = h1s[0] if h1s else headings[0]["text"]

    schema = _schema_from_html(html or "")
    if dom_meta:
        if dom_meta.get("product_schema_present") and "Product" not in schema["types"]:
            schema["types"].append("Product")
            schema["detected"] = True
        if dom_meta.get("faq_schema_present") and "FAQPage" not in schema["types"]:
            schema["types"].append("FAQPage")
            schema["detected"] = True

    meta_desc = (dom_meta or {}).get("meta_description")
    return {
        "url": url,
        "role": role,
        "title": title,
        "meta_description": meta_desc,
        "headings": headings,
        "key_paragraphs": paras,
        "trust_signals": _trust_signals(text),
        "cta_examples": _cta_examples(text),
        "schema": schema,
        "review_snippets": _review_snippets(text) if role in ("reviews", "main") else [],
        "word_count_estimate": len(text.split()) if text else 0,
        "keyword_hints": _keyword_hints(title, headings, paras),
        "technical": {
            "canonical_present": bool((dom_meta or {}).get("canonical_present")),
            "open_graph_present": bool((dom_meta or {}).get("open_graph_present")),
        },
    }


def select_strategic_urls(base_url: str, links: list[str]) -> list[tuple[str, str]]:
    """Pick up to MAX_STRATEGIC_PAGES non-main URLs, one preferred URL per role."""
    by_role: dict[str, str] = {}
    for link in links:
        role = _classify_url(link)
        if role and role not in by_role:
            by_role[role] = link

    priority = ("faq", "about", "shipping", "returns", "reviews")
    selected: list[tuple[str, str]] = []
    for role in priority:
        if role in by_role:
            selected.append((role, by_role[role]))
        if len(selected) >= MAX_STRATEGIC_PAGES:
            return selected

    for link in links:
        if len(selected) >= MAX_STRATEGIC_PAGES:
            break
        if any(link == u for _, u in selected):
            continue
        role = _classify_url(link) or "about"
        if role == "main":
            continue
        if role not in {r for r, _ in selected}:
            selected.append((role, link))
    return selected[:MAX_STRATEGIC_PAGES]


async def _fetch_html_light(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/html"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text[:_MAX_HTML_FOR_LINKS]
    except Exception:
        return None


async def _fetch_page_content(url: str) -> tuple[str | None, str | None]:
    """Return (markdown_or_text, html_if_any)."""
    html = await _fetch_html_light(url)
    if html and len(_html_to_clean_text(html)) >= 200:
        return _html_to_clean_text(html), html
    md = await fetch_page_markdown(url)
    return md, html


def build_agent_context_packages(
    page_contexts: dict[str, dict[str, Any]],
    dom_facts: dict[str, Any],
    *,
    url: str,
    competitor_urls: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    main = page_contexts.get("main") or {}

    def pick(*roles: str) -> dict[str, dict[str, Any]]:
        return {r: page_contexts[r] for r in roles if r in page_contexts}

    seo = {
        "page_type": "main_only",
        "url": url,
        "dom_technical_seo": dom_facts,
        "main": {
            "title": main.get("title"),
            "meta_description": main.get("meta_description"),
            "headings": main.get("headings"),
            "schema": main.get("schema"),
            "keyword_hints": main.get("keyword_hints"),
            "key_paragraphs": (main.get("key_paragraphs") or [])[:3],
            "technical": main.get("technical"),
            "word_count_estimate": main.get("word_count_estimate"),
        },
    }

    aeo = {
        "pages": pick("main", "faq", "about"),
        "focus": ["eeat", "faq_schema", "brand_clarity", "conversational_snippets"],
    }

    ux = {
        "pages": pick("main", "shipping", "returns"),
        "focus": ["cta", "trust_signals", "shipping_returns_visibility"],
    }

    psychology = {
        "pages": pick("main", "reviews"),
        "focus": ["social_proof", "scarcity", "pricing_psychology", "reviews"],
    }

    competitor = {
        "source": "competitor_agent_live_scrape",
        "your_url": url,
        "user_supplied_competitor_urls": list(competitor_urls or [])[:3],
        "note": "Competitor PDP/homepage metrics are fetched in competitor_agent, not from your site crawl.",
    }

    return {
        "seo": seo,
        "aeo": aeo,
        "ux": ux,
        "psychology": psychology,
        "competitor": competitor,
    }


def format_context_for_llm(package: dict[str, Any], max_chars: int = 4500) -> str:
    """Serialize agent package compactly for Claude prompts."""
    raw = json.dumps(package, ensure_ascii=False, separators=(",", ":"))
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + "...(truncated)"


async def context_router_agent(state: AgentState) -> AgentState:
    """
    Crawl strategic same-domain pages (depth 1), build page_contexts and
    agent_context_packages. Keeps markdown_content unchanged for extractor/autofix.
    """
    url = (state.get("url") or "").strip()
    markdown = state.get("markdown_content") or ""
    if not url or not markdown:
        return {"errors": ["context_router: missing url or markdown_content"]}

    dom_facts = state_dict(state, "dom_technical_seo")
    scrape_html = state.get("scrape_html") or ""

    t0 = time.monotonic()
    logger.info("context_router.start", url=url)

    if not scrape_html:
        scrape_html = await _fetch_html_light(url) or ""

    links = _extract_internal_links(url, scrape_html, markdown)
    strategic = select_strategic_urls(url, links)

    page_contexts: dict[str, dict[str, Any]] = {
        "main": build_page_summary(url, "main", markdown=markdown, html=scrape_html or None, dom_meta=dom_facts),
    }

    async def load_role(role: str, page_url: str) -> tuple[str, dict[str, Any]]:
        text, html = await _fetch_page_content(page_url)
        role_guess = _classify_url(page_url) or _classify_by_headings(text or "") or role
        dom = _extract_dom_metadata(html) if html else None
        summary = build_page_summary(
            page_url,
            role_guess,
            markdown=text,
            html=html,
            dom_meta=dom,
        )
        return role_guess, summary

    if strategic:
        results = await asyncio.gather(
            *[load_role(r, u) for r, u in strategic],
            return_exceptions=True,
        )
        for item in results:
            if isinstance(item, Exception):
                logger.warning("context_router.page_failed", error=str(item))
                continue
            role_key, summary = item
            if role_key not in page_contexts or role_key == "main":
                page_contexts[role_key] = summary

    packages = build_agent_context_packages(
        page_contexts,
        dom_facts,
        url=url,
        competitor_urls=state.get("competitor_urls"),
    )

    seo_preprocessor_facts = extract_seo_facts(
        url=url,
        markdown=markdown,
        scrape_html=scrape_html,
        dom_technical_seo=dom_facts,
        page_main_summary=page_contexts.get("main"),
    )

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "context_router.done",
        pages=list(page_contexts.keys()),
        strategic_fetched=len(strategic),
        duration_ms=duration_ms,
    )

    return {
        "page_contexts": page_contexts,
        "agent_context_packages": packages,
        "seo_preprocessor_facts": seo_preprocessor_facts,
        "agent_reports": [
            {
                "agent": "context_router",
                "model": "heuristic",
                "input": {"url": url, "links_found": len(links), "strategic_urls": [u for _, u in strategic]},
                "output": {
                    "roles": list(page_contexts.keys()),
                    "package_keys": list(packages.keys()),
                },
                "duration_ms": duration_ms,
            }
        ],
    }
