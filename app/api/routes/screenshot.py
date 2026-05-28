"""
app/api/routes/screenshot.py
Playwright screenshot + PIL annotations. Render only (SKIP_PLAYWRIGHT=false).
"""
from __future__ import annotations

import base64
import io
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field, field_validator

from app.core.playwright_env import playwright_enabled

router = APIRouter(prefix="/analyze", tags=["Screenshot"])

# ── CSS selectors for each issue type ────────────────────────────────────────
ISSUE_SELECTORS: dict[str, list[str]] = {
    # SEO
    "h1_weak": ["h1"],
    "h1_missing": ["h1"],
    "missing_h1": ["h1"],
    "meta_too_long": ["meta[name='description']"],
    "meta_too_short": ["meta[name='description']"],
    "title_missing": ["title"],
    "img_no_alt": ["img:not([alt])", "img[alt='']"],
    "no_schema": ["script[type='application/ld+json']"],
    "no_canonical": ["link[rel='canonical']"],
    "no_og": ["meta[property='og:title']"],
    # UX
    "no_cta": [
        "button.add-to-cart",
        "a[href*='cart']",
        "a[href*='buy']",
        ".cta",
        "[class*='add-to-cart']",
        "[class*='btn-primary']",
    ],
    "no_reviews": [
        "[class*='review']",
        "[class*='rating']",
        ".star-rating",
        "[itemprop='ratingValue']",
    ],
    "no_faq": ["[class*='faq']", "details", "[itemtype*='FAQPage']"],
    "no_trust_badges": ["[class*='trust']", "[class*='badge']", "[class*='secure']"],
    "sticky_cta": ["[class*='sticky']", "[class*='floating']", ".sticky-bar"],
}

SEVERITY_COLORS = {
    "critical": ("#E53935", "#FFEBEE"),
    "warning": ("#F57C00", "#FFF3E0"),
    "info": ("#1565C0", "#E3F2FD"),
}


class ScreenshotIssue(BaseModel):
    id: str
    severity: Literal["critical", "warning", "info"] = "warning"
    label: str
    fix: str | None = None


class ScreenshotAnnotateRequest(BaseModel):
    url: str
    issues: list[ScreenshotIssue] = Field(default_factory=list)
    viewport_width: int = 1280
    viewport_height: int = 900

    @field_validator("url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class BBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class AnnotatedElement(BaseModel):
    issue_id: str
    found: bool
    bbox: BBox | None = None


class ScreenshotAnnotateResponse(BaseModel):
    screenshot_base64: str
    annotated_elements: list[AnnotatedElement]
    viewport_width: int
    viewport_height: int
    issues_found: int
    issues_total: int


def _load_font(size: int = 11) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hex_to_rgb(hx: str) -> tuple[int, int, int]:
    hx = hx.lstrip("#")
    return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)


def _annotate_png(
    png_bytes: bytes,
    boxes: list[tuple[ScreenshotIssue, dict[str, float]]],
    viewport_width: int,
) -> bytes:
    del viewport_width  # reserved for future viewport-aware layout
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw = ImageDraw.Draw(img)
    font = _load_font(11)
    font_small = _load_font(9)

    for issue, box in boxes:
        x, y, w, h = box["x"], box["y"], box["width"], box["height"]
        border_color_hex, bg_color_hex = SEVERITY_COLORS.get(
            issue.severity, SEVERITY_COLORS["warning"]
        )
        border_rgb = _hex_to_rgb(border_color_hex)
        bg_rgb = _hex_to_rgb(bg_color_hex)
        bg_rgba = (*bg_rgb, 60)

        draw_overlay.rectangle([x, y, x + w, y + h], fill=bg_rgba)

        border_w = 3 if issue.severity == "critical" else 2
        for i in range(border_w):
            draw.rectangle(
                [x - i, y - i, x + w + i, y + h + i],
                outline=border_rgb,
            )

        label_text = issue.label[:55]
        fix_text = f"Fix: {issue.fix[:45]}" if issue.fix else None

        bbox_txt = draw.textbbox((0, 0), label_text, font=font)
        tw = bbox_txt[2] - bbox_txt[0]
        th = bbox_txt[3] - bbox_txt[1]
        pad = 5

        label_y = y - th - pad * 2 - 4
        if label_y < 0:
            label_y = y + h + 4

        label_x = min(x, img.width - tw - pad * 2 - 4)

        draw.rounded_rectangle(
            [label_x, label_y, label_x + tw + pad * 2, label_y + th + pad * 2],
            radius=4,
            fill=border_rgb,
        )
        draw.text((label_x + pad, label_y + pad), label_text, fill="white", font=font)

        if fix_text:
            fix_bbox = draw.textbbox((0, 0), fix_text, font=font_small)
            fw = fix_bbox[2] - fix_bbox[0]
            fy = label_y + th + pad * 2 + 2
            draw.rounded_rectangle(
                [label_x, fy, label_x + fw + pad * 2, fy + 16],
                radius=3,
                fill=(255, 255, 255, 230),
                outline=border_rgb,
            )
            draw.text((label_x + pad, fy + 2), fix_text, fill=border_rgb, font=font_small)

    img = Image.alpha_composite(img, overlay).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


async def _capture_and_locate(
    url: str,
    issues: list[ScreenshotIssue],
    viewport_width: int,
    viewport_height: int,
) -> tuple[bytes, list[AnnotatedElement], list[tuple[ScreenshotIssue, dict[str, float]]]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        ) from exc

    annotated: list[AnnotatedElement] = []
    drawable: list[tuple[ScreenshotIssue, dict[str, float]]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = await browser.new_page(
                viewport={"width": viewport_width, "height": viewport_height},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            try:
                await page.wait_for_selector("main, article, body", timeout=5000)
            except Exception:
                pass

            screenshot_bytes = await page.screenshot(full_page=True, type="png")

            for issue in issues:
                selectors = ISSUE_SELECTORS.get(issue.id, [])
                element = None

                for selector in selectors:
                    try:
                        el = await page.query_selector(selector)
                        if el:
                            element = el
                            break
                    except Exception:
                        continue

                if element is None:
                    annotated.append(AnnotatedElement(issue_id=issue.id, found=False))
                    continue

                raw_box = await element.bounding_box()
                if not raw_box or raw_box["width"] == 0:
                    annotated.append(AnnotatedElement(issue_id=issue.id, found=False))
                    continue

                box = {k: raw_box[k] for k in ("x", "y", "width", "height")}
                annotated.append(
                    AnnotatedElement(
                        issue_id=issue.id,
                        found=True,
                        bbox=BBox(**box),
                    )
                )
                drawable.append((issue, box))

        finally:
            await browser.close()

    return screenshot_bytes, annotated, drawable


@router.post(
    "/screenshot-annotate",
    response_model=ScreenshotAnnotateResponse,
    status_code=status.HTTP_200_OK,
    summary="Playwright screenshot with issue annotations (Render only)",
)
async def screenshot_annotate(body: ScreenshotAnnotateRequest) -> ScreenshotAnnotateResponse:
    if not playwright_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Playwright disabled (SKIP_PLAYWRIGHT=true). "
                "This endpoint runs on Render. Set SKIP_PLAYWRIGHT=false there."
            ),
        )

    try:
        png_bytes, annotated_elements, drawable = await _capture_and_locate(
            body.url,
            body.issues,
            body.viewport_width,
            body.viewport_height,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Screenshot failed: {exc}",
        ) from exc

    if drawable:
        png_bytes = _annotate_png(png_bytes, drawable, body.viewport_width)

    found_count = sum(1 for a in annotated_elements if a.found)

    return ScreenshotAnnotateResponse(
        screenshot_base64=base64.b64encode(png_bytes).decode("ascii"),
        annotated_elements=annotated_elements,
        viewport_width=body.viewport_width,
        viewport_height=body.viewport_height,
        issues_found=found_count,
        issues_total=len(body.issues),
    )
