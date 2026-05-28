"""
app/api/routes/screenshot.py

POST /analyze/screenshot-annotate – capture page screenshot and annotate SEO/UX issues.
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

ISSUE_SELECTORS: dict[str, str] = {
    "missing_h1": "h1",
    "meta_too_short": "meta[name='description']",
    "img_no_alt": "img:not([alt]), img[alt='']",
    "title_missing": "title",
    "no_schema": "script[type='application/ld+json']",
    "no_canonical": "link[rel='canonical']",
    "no_og": "meta[property='og:title']",
    "no_cta": "button, a[href*='cart'], a[href*='buy'], .add-to-cart",
    "no_reviews": "[class*='review'], [class*='rating'], .star",
}

CRITICAL_COLOR = "#E24B4A"
WARNING_COLOR = "#F59E0B"
CRITICAL_WIDTH = 3
WARNING_WIDTH = 2


class ScreenshotIssue(BaseModel):
    id: str
    severity: Literal["critical", "warning"]
    label: str


class ScreenshotAnnotateRequest(BaseModel):
    url: str
    issues: list[ScreenshotIssue] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def must_be_http_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class BBox(BaseModel):
    x: float
    width: float
    y: float
    height: float


class AnnotatedElement(BaseModel):
    issue_id: str
    found: bool
    bbox: BBox | None = None


class ScreenshotAnnotateResponse(BaseModel):
    screenshot_base64: str
    annotated_elements: list[AnnotatedElement]


def _load_font(size: int = 12) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_label(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    x: float,
    y: float,
    label: str,
    fill_color: str,
) -> None:
    text = label[:80]
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = 4
    label_y = max(0, y - th - pad * 2)
    draw.rectangle(
        [x, label_y, x + tw + pad * 2, label_y + th + pad * 2],
        fill=fill_color,
    )
    draw.text((x + pad, label_y + pad), text, fill="white", font=font)


def _annotate_png(
    png_bytes: bytes,
    boxes: list[tuple[ScreenshotIssue, dict[str, float]]],
) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _load_font()

    for issue, box in boxes:
        x, y, w, h = box["x"], box["y"], box["width"], box["height"]
        color = CRITICAL_COLOR if issue.severity == "critical" else WARNING_COLOR
        width = CRITICAL_WIDTH if issue.severity == "critical" else WARNING_WIDTH
        draw.rectangle(
            [x, y, x + w, y + h],
            outline=color,
            width=width,
        )
        _draw_label(draw, font, x, y, issue.label, color)

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


async def _capture_and_locate(
    url: str,
    issues: list[ScreenshotIssue],
) -> tuple[bytes, list[AnnotatedElement], list[tuple[ScreenshotIssue, dict[str, float]]]]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from exc

    annotated: list[AnnotatedElement] = []
    drawable: list[tuple[ScreenshotIssue, dict[str, float]]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            screenshot_bytes = await page.screenshot(full_page=True, type="png")

            for issue in issues:
                selector = ISSUE_SELECTORS.get(issue.id)
                if not selector:
                    annotated.append(
                        AnnotatedElement(issue_id=issue.id, found=False, bbox=None)
                    )
                    continue

                element = await page.query_selector(selector)
                if element is None:
                    elements = await page.query_selector_all(selector)
                    element = elements[0] if elements else None

                if element is None:
                    annotated.append(
                        AnnotatedElement(issue_id=issue.id, found=False, bbox=None)
                    )
                    continue

                raw_box = await element.bounding_box()
                if not raw_box:
                    annotated.append(
                        AnnotatedElement(issue_id=issue.id, found=False, bbox=None)
                    )
                    continue

                box = {
                    "x": raw_box["x"],
                    "y": raw_box["y"],
                    "width": raw_box["width"],
                    "height": raw_box["height"],
                }
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
    summary="Screenshot a URL and annotate detected issue elements",
)
async def screenshot_annotate(
    body: ScreenshotAnnotateRequest,
) -> ScreenshotAnnotateResponse:
    if not playwright_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Annotated screenshots need Playwright (Chromium). "
                "On Vercel this is disabled (SKIP_PLAYWRIGHT=true). "
                "Test locally with SKIP_PLAYWRIGHT=false and `playwright install chromium`, "
                "or deploy the API on Render/Docker with Playwright enabled."
            ),
        )

    try:
        png_bytes, annotated_elements, drawable = await _capture_and_locate(
            body.url,
            body.issues,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to capture screenshot: {exc}",
        ) from exc

    if drawable:
        png_bytes = _annotate_png(png_bytes, drawable)

    return ScreenshotAnnotateResponse(
        screenshot_base64=base64.b64encode(png_bytes).decode("ascii"),
        annotated_elements=annotated_elements,
    )
