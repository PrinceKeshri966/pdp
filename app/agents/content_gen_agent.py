"""
app/agents/content_gen_agent.py

ContentGenAgent  (Mode 1 – Phase 4, Parallel)   Model: Claude Sonnet
──────────────────────────────────────────────────────────────────────
Generates production-ready optimized content based on all analysis reports.
Produces: AI-optimized descriptions, FAQs, metadata, schema markup,
and social captions — all ready to copy-paste.
"""
from __future__ import annotations

import json
import time

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.agents.state import AgentState, state_dict
from app.core.logging import get_logger

logger = get_logger(__name__)

_MODEL = get_model("autofix")  # Sonnet — creative generation

_SYSTEM_PROMPT = """
You are a world-class e-commerce content strategist, SEO copywriter, and GEO specialist.
GEO = Generative Engine Optimization: content optimized to be cited by AI answer engines.
Generate production-ready content following Google E-E-A-T guidelines and
Jasper/Shopify Magic content standards.

Return ONLY a valid JSON object — no prose, no markdown fences.

Required JSON schema:
{
  "product_description": string,
  "ai_optimized_description": string,
  "brand_story_snippet": string,
  "faqs": [
    {"question": string, "answer": string}
  ],
  "meta_title": string,
  "meta_description": string,
  "open_graph_title": string,
  "open_graph_description": string,
  "schema_markup": string,
  "faq_schema": string,
  "social_captions": {
    "instagram": string,
    "whatsapp": string,
    "twitter": string,
    "linkedin": string
  },
  "email_marketing": {
    "subject_lines": [string],
    "preview_text": string,
    "hero_copy": string
  },
  "push_notification_copy": {
    "title": string,
    "body": string
  },
  "suggested_h2s": [string],
  "bullet_points": [string],
  "size_guide_copy": string | null,
  "keyword_strategy": {
    "primary": string,
    "secondary": [string],
    "lsi_keywords": [string],
    "ai_query_targets": [string]
  },
  "ab_test_variants": {
    "title_variant_b": string,
    "cta_variant_a": string,
    "cta_variant_b": string,
    "description_variant_b": string
  }
}
""".strip()


async def content_gen_agent(state: AgentState) -> AgentState:
    """Generate optimized content based on all analysis reports."""
    structured = state_dict(state, "json_structured_data")
    seo = state_dict(state, "seo_report")
    aeo = state_dict(state, "aeo_report")
    diagnosis = state_dict(state, "final_diagnosis")

    if not structured:
        return {"errors": ["content_gen_agent: no json_structured_data"]}

    logger.info("content_gen_agent.start", model=_MODEL)
    t0 = time.monotonic()

    user_message = f"""
Generate optimized content for this product:

Product Data:
{json.dumps(structured, indent=2)}

SEO Gaps to fix:
{json.dumps(seo.get("top_issues", []), indent=2)}

AEO Gaps to fix:
{json.dumps(aeo.get("gaps", []), indent=2)}

Priority Actions:
{json.dumps(diagnosis.get("quick_wins", []), indent=2)}

Generate content that fixes all identified gaps.
FAQs must be conversational and AI-engine-friendly.
Schema markup must be valid JSON-LD Product schema.
""".strip()

    response = await claude.messages.create(
        model=_MODEL,
        max_tokens=6000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    duration_ms = int((time.monotonic() - t0) * 1000)
    generated_content, parse_err = safe_json_parse_report(raw, "content_gen_agent")
    if parse_err:
        return {"errors": [parse_err]}

    logger.info(
        "content_gen_agent.done",
        faqs=len(generated_content.get("faqs", [])),
        duration_ms=duration_ms,
    )

    return {
        "generated_content": generated_content,
        "status": "completed",
        "agent_reports": [
            {
                "agent": "content_gen_agent",
                "model": _MODEL,
                "output": generated_content,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        ],
    }
