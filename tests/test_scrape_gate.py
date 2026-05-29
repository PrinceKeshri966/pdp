"""Hard-fail scrape gate — stop pipeline before extraction on invalid pages."""
from __future__ import annotations

import asyncio

import pytest

from app.agents.scrape_validator import scrape_quality_agent
from app.core.scrape_gate import evaluate_scrape_gate

_VALID_MARKDOWN = " ".join(["product"] * 60) + " Add to cart $29.99 free shipping returns policy"


def test_gate_passes_valid_product_page():
    assert evaluate_scrape_gate(markdown=_VALID_MARKDOWN, url="https://shop.example/p") is None


@pytest.mark.parametrize(
    "markdown,dom,expected_code",
    [
        ("", {}, "empty_content"),
        ("too short", {}, "empty_content"),
        ("Page Not Found " + "x " * 30, {}, "page_not_found"),
        ("Product not found " + "x " * 30, {}, "product_not_found"),
        ("Access Denied " + "x " * 30, {}, "access_denied"),
        ("Please complete the CAPTCHA " + "x " * 30, {}, "captcha_block"),
        ("Sign in to continue " + "x " * 30, {}, "login_required"),
        (_VALID_MARKDOWN, {"http_status": 404}, "page_not_found"),
        (_VALID_MARKDOWN, {"http_status": 403}, "access_denied"),
        (_VALID_MARKDOWN, {"http_status": 401}, "login_required"),
    ],
)
def test_gate_hard_fails_invalid_pages(markdown: str, dom: dict, expected_code: str):
    gate = evaluate_scrape_gate(
        markdown=markdown,
        scrape_html="",
        dom_technical_seo=dom,
        url="https://shop.example/p",
    )
    assert gate is not None
    assert gate["hard_fail"] is True
    assert gate["code"] == expected_code
    assert gate["message"]
    assert "extractor" in gate["agents_skipped"]
    assert "seo" in gate["agents_skipped"]
    assert "validator" in gate["agents_skipped"]
    assert "autofix" in gate["agents_skipped"]


def test_scrape_quality_agent_hard_fails_before_extraction():
    state = {
        "url": "https://shop.example/missing",
        "markdown_content": "404 Page Not Found " + "missing product page content " * 20,
        "scrape_html": "<title>404</title>",
        "dom_technical_seo": {},
        "scraper_method": "httpx",
        "capture_confidence": 0.9,
        "scrape_retry_count": 99,
        "scrape_retry_methods": [],
        "agent_reports": [],
        "errors": [],
        "status": "running",
    }
    result = asyncio.run(scrape_quality_agent(state))
    assert result["status"] == "failed"
    assert result["scrape_validation"]["hard_fail"]["code"] == "page_not_found"
    assert any(e.startswith("scrape_gate:") for e in result["errors"])
    assert result["agent_reports"][0]["agent"] == "scrape_gate"


def test_scrape_quality_agent_empty_markdown_hard_fails():
    state = {
        "url": "https://shop.example/empty",
        "markdown_content": "",
        "scrape_html": "",
        "dom_technical_seo": {},
        "agent_reports": [],
        "errors": [],
        "status": "running",
    }
    result = asyncio.run(scrape_quality_agent(state))
    assert result["status"] == "failed"
    assert result["scrape_validation"]["hard_fail"]["code"] == "empty_content"
