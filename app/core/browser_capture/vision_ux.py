"""
Screenshot-based visual UX analysis using Claude vision model.
"""
from __future__ import annotations

import json
from typing import Any

from app.agents.claude_client import claude
from app.agents.json_utils import safe_json_parse_report
from app.agents.model_router import get_model
from app.core.logging import get_logger

logger = get_logger(__name__)

_VISION_PROMPT = """Analyze this e-commerce page screenshot for conversion UX.
Return ONLY valid JSON:
{
  "above_fold_clarity": float (0-10),
  "cta_visibility": float (0-10),
  "trust_signals_visible": float (0-10),
  "visual_hierarchy": float (0-10),
  "mobile_readiness_estimate": float (0-10),
  "color_contrast_risk": "low|medium|high",
  "issues": [string],
  "quick_wins": [string],
  "overall_ux_score": float (0-10),
  "confidence": float (0-1)
}"""


async def analyze_screenshot_ux(
    screenshot_base64: str,
    url: str = "",
    page_type: str = "product",
) -> dict[str, Any]:
    """Run vision model analysis on a page screenshot."""
    if not screenshot_base64:
        return {"available": False, "confidence": 0.0, "warnings": ["No screenshot provided"]}

    try:
        image_data = screenshot_base64
        if not image_data.startswith("data:"):
            image_data = f"data:image/png;base64,{image_data}"

        response = await claude.messages.create(
            model=get_model("ux"),
            max_tokens=1024,
            system=_VISION_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_base64.replace("data:image/png;base64,", ""),
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Page URL: {url}\nPage type: {page_type}\nAnalyze conversion UX from this screenshot.",
                        },
                    ],
                }
            ],
        )

        raw = response.content[0].text.strip()
        parsed, err = safe_json_parse_report(raw, "vision_ux")
        if err or not parsed:
            return {"available": False, "confidence": 0.3, "warnings": [err or "Parse failed"]}

        parsed["available"] = True
        parsed["source"] = "claude_vision"
        parsed["confidence"] = float(parsed.get("confidence") or 0.8)
        return parsed
    except Exception as exc:
        logger.warning("vision_ux.failed", error=str(exc))
        return {"available": False, "confidence": 0.0, "warnings": [str(exc)]}
