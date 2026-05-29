"""
app/agents/extractor_agent.py

ExtractorAgent  (Mode 1 – Node 5)
Multi-strategy extraction for PDPs; LLM gap-fill only when needed.
"""
from __future__ import annotations

import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.extraction_confidence import score_extraction_confidence
from app.agents.state import AgentState, state_dict
from app.core.extraction.pipeline import run_extraction_pipeline
from app.core.extraction.playwright_pdp import url_looks_like_pdp
from app.core.extraction.domain_memory import record_domain_success
from app.core.page_type_router import is_pdp
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("scraper_parser")

_SYSTEM_PROMPT = """
You are an expert e-commerce data extractor trained on Google's Product structured data spec (schema.org).
Given raw scraped text from a product page, extract only the core product information.
Ignore navigation menus, footers, cookie banners, ads, and unrelated content.

Return ONLY a valid JSON object — no prose, no markdown fences.

Required JSON schema (aligned with schema.org Product + Google Merchant Center fields):
{
  "product_name": string,
  "brand": string,
  "seller_name": string | null,
  "product_url": string | null,
  "language": string | null,
  "sku": string | null,
  "gtin": string | null,
  "mpn": string | null,
  "price": string,
  "original_price": string | null,
  "discount_pct": float | null,
  "currency": string,
  "price_valid_until": string | null,
  "availability": "InStock|OutOfStock|PreOrder|LimitedAvailability",
  "condition": "NewCondition|UsedCondition|RefurbishedCondition",
  "description": string,
  "features": [string],
  "categories": [string],
  "breadcrumb": [string],
  "image_urls": [string],
  "video_urls": [string],
  "images_count": int,
  "has_video": boolean,
  "has_size_guide": boolean,
  "has_reviews": boolean,
  "review_count": int | null,
  "avg_rating": float | null,
  "rating_max": float,
  "shipping_info": string | null,
  "return_policy": string | null,
  "warranty": string | null,
  "color_variants": [string],
  "size_variants": [string],
  "related_products_count": int,
  "page_word_count": int,
  "above_fold_cta": string | null,
  "trust_badges": [string]
}
""".strip()


def _page_type_from_state(state: AgentState) -> str:
    pti = state_dict(state, "page_type_info")
    sv = state_dict(state, "scrape_validation")
    return (pti.get("page_type") or sv.get("page_type") or "").lower()


def _use_pdp_pipeline(state: AgentState) -> bool:
    url = (state.get("url") or "").strip()
    pt = _page_type_from_state(state)
    return is_pdp(pt) or url_looks_like_pdp(url)


async def _legacy_llm_extract(state: AgentState, markdown: str) -> dict:
    source_url = state.get("url", "")
    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=2000,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Source URL: {source_url}\n\n"
                    f"Extract product data from this scraped page content:\n\n"
                    f"{markdown[:10000]}"
                ),
            }
        ],
    )
    raw = response.content[0].text.strip()
    structured_data, parse_err = safe_json_parse_report(raw, "extractor_agent")
    if parse_err:
        return {"errors": [parse_err]}
    extraction_confidence = score_extraction_confidence(
        structured_data,
        scrape_validation=state_dict(state, "scrape_validation"),
    )
    structured_data["_extraction_confidence"] = extraction_confidence
    return {
        "json_structured_data": structured_data,
        "extraction_confidence": extraction_confidence,
        "llm_response": response,
    }


async def extractor_agent(state: AgentState) -> AgentState:
    """Extract structured product data — multi-strategy for PDPs."""
    markdown = state.get("markdown_content", "")
    if not markdown:
        return {"errors": ["extractor_agent: no markdown_content"]}

    logger.info("extractor_agent.start", pdp_pipeline=_use_pdp_pipeline(state), chars=len(markdown))
    t0 = time.monotonic()
    source_url = state.get("url", "")

    if _use_pdp_pipeline(state):
        result = await run_extraction_pipeline(
            url=source_url,
            markdown=markdown,
            scrape_html=state.get("scrape_html") or "",
            network_payloads=state.get("network_payloads") or [],
            platform_info=state.get("platform_info"),
            scrape_validation=state_dict(state, "scrape_validation"),
        )
        structured_data = result["json_structured_data"]
        extraction_confidence = result["extraction_confidence"]
        extraction_meta = result.get("extraction_meta") or {}

        record_domain_success(
            source_url,
            scraper_method=state.get("scraper_method") or "unknown",
            overall_confidence=extraction_confidence.get("overall_extraction_confidence") or 0,
            platform=(state.get("platform_info") or {}).get("platform"),
            used_network=bool(state.get("network_payloads")),
        )

        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "extractor_agent.done",
            mode="pdp_pipeline",
            product=structured_data.get("product_name"),
            confidence=extraction_confidence.get("overall_extraction_confidence"),
            duration_ms=duration_ms,
        )
        return {
            "json_structured_data": structured_data,
            "extraction_confidence": extraction_confidence,
            "extraction_meta": extraction_meta,
            "agent_reports": [
                {
                    "agent": "extractor_agent",
                    "model": "multi_strategy",
                    "input": {
                        "markdown_chars": len(markdown),
                        "scraper_method": state.get("scraper_method", "unknown"),
                        "strategies": structured_data.get("_extraction_strategies"),
                    },
                    "output": structured_data,
                    "duration_ms": duration_ms,
                }
            ],
        }

    legacy = await _legacy_llm_extract(state, markdown)
    if legacy.get("errors"):
        return legacy
    duration_ms = int((time.monotonic() - t0) * 1000)
    response = legacy.pop("llm_response", None)
    report = {
        "agent": "extractor_agent",
        "model": _MODEL,
        "input": {
            "markdown_chars": len(markdown),
            "scraper_method": state.get("scraper_method", "unknown"),
        },
        "output": legacy["json_structured_data"],
        "duration_ms": duration_ms,
    }
    if response:
        report["input_tokens"] = response.usage.input_tokens
        report["output_tokens"] = response.usage.output_tokens
    return {
        **legacy,
        "agent_reports": [report],
    }
