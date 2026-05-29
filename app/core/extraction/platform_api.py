"""
Platform-native product APIs (highest confidence when available).
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.html_metadata import BROWSER_UA


def _shopify_handle(url: str) -> str | None:
    m = re.search(r"/products/([^/?#]+)", url, re.I)
    return m.group(1) if m else None


def _woo_slug(url: str) -> str | None:
    m = re.search(r"/product(?:s)?/([^/?#]+)", url, re.I)
    return m.group(1) if m else None


def _base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_shopify_price(raw_price: Any, *, in_cents: bool = True) -> str | None:
    if raw_price is None:
        return None
    try:
        pval = float(str(raw_price).replace(",", ""))
        if in_cents and pval >= 1000 and pval == int(pval):
            return str(int(pval / 100))
        return str(int(pval) if pval == int(pval) else round(pval, 2))
    except (TypeError, ValueError):
        return str(raw_price)


def _parse_visible_discount_pct(text: str) -> int | None:
    m = re.search(r"(\d{1,2})\s*%\s*off", text or "", re.I)
    return int(m.group(1)) if m else None


def _variant_picker_count(html: str) -> int | None:
    """Count visible variant picker controls (ground-truth parity)."""
    if not html:
        return None
    selectors = len(re.findall(
        r'select[^>]*name=["\'][^"\']*option|class=["\'][^"\']*swatch|data-variant-id|'
        r'class=["\'][^"\']*variant[^"\']*["\'][^>]*(?:button|input)',
        html,
        re.I,
    ))
    if selectors:
        return selectors
    opts = len(re.findall(r'class=["\'][^"\']*variant[^"\']*["\'][^>]*>.*?<option', html, re.I))
    return opts or None


def _map_shopify_variant(v: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single Shopify variant to structured output."""
    out: dict[str, Any] = {}
    if v.get("id") is not None:
        out["id"] = v["id"]
    if v.get("title"):
        out["title"] = str(v["title"]).strip()
    if v.get("sku"):
        out["sku"] = str(v["sku"]).strip()
    raw_price = v.get("price")
    norm = _normalize_shopify_price(raw_price)
    if norm:
        out["price"] = norm
    cap = v.get("compare_at_price")
    if cap is not None and str(cap) not in ("", "0", "0.0"):
        norm_cap = _normalize_shopify_price(cap)
        if norm_cap:
            out["compare_at_price"] = norm_cap
    inv = v.get("inventory_quantity")
    if inv is not None:
        try:
            out["inventory_quantity"] = int(inv)
        except (TypeError, ValueError):
            pass
    if "available" in v:
        out["available"] = bool(v.get("available"))
    for opt_key in ("option1", "option2", "option3"):
        if v.get(opt_key):
            out[opt_key] = str(v[opt_key]).strip()
    return out


def _shopify_collections(data: dict[str, Any]) -> list[str]:
    """Derive collection labels from Shopify product payload."""
    collections: list[str] = []
    seen: set[str] = set()

    def _add(val: str | None) -> None:
        if not val:
            return
        label = str(val).strip()
        if label and label.lower() not in seen:
            seen.add(label.lower())
            collections.append(label)

    for coll in data.get("collections") or []:
        if isinstance(coll, dict):
            _add(coll.get("title") or coll.get("handle"))
        elif isinstance(coll, str):
            _add(coll)

    _add(data.get("product_type") or data.get("type"))

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    for tag in tags:
        if isinstance(tag, str) and tag.strip():
            _add(tag.strip())

    return collections[:20]


def _map_shopify_product(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if data.get("title"):
        out["product_name"] = str(data["title"]).strip()
    if data.get("vendor"):
        vendor = str(data["vendor"]).strip()
        out["vendor"] = vendor
        out["brand"] = vendor

    variants_raw = data.get("variants") or []
    variants: list[dict[str, Any]] = []
    total_inventory = 0
    has_inventory = False
    compare_prices: list[str] = []

    for v in variants_raw:
        if not isinstance(v, dict):
            continue
        mapped = _map_shopify_variant(v)
        if mapped:
            variants.append(mapped)
        inv = mapped.get("inventory_quantity")
        if inv is not None:
            has_inventory = True
            total_inventory += int(inv)
        cap = mapped.get("compare_at_price")
        if cap:
            compare_prices.append(str(cap))

    if variants:
        out["variants"] = variants
        prices = [v["price"] for v in variants if v.get("price")]
        if prices:
            try:
                out["price"] = str(min(int(float(p)) for p in prices))
            except (TypeError, ValueError):
                out["price"] = variants[0].get("price")
        compare_vals: list[float] = []
        for v in variants:
            cap = v.get("compare_at_price")
            if cap:
                try:
                    compare_vals.append(float(str(cap).replace(",", "")))
                except ValueError:
                    pass
        sale = None
        try:
            sale = float(str(out.get("price", "")).replace(",", ""))
        except (TypeError, ValueError):
            pass
        max_compare = max(compare_vals) if compare_vals else None
        if max_compare and sale and max_compare > sale * 1.02:
            out["compare_at_price"] = str(int(max_compare) if max_compare == int(max_compare) else round(max_compare, 2))
            out["original_price"] = out["compare_at_price"]
            out["discount_pct"] = round((1 - sale / max_compare) * 100)
        if has_inventory:
            out["inventory_quantity"] = total_inventory
        out["availability"] = "OutOfStock" if not any(v.get("available", True) for v in variants) else "InStock"
        out["currency"] = "INR"

    collections = _shopify_collections(data)
    if collections:
        out["collections"] = collections
        out["categories"] = collections

    desc = data.get("description") or data.get("body_html")
    if desc:
        out["description"] = re.sub(r"<[^>]+>", " ", str(desc))[:3000]
    images = data.get("images") or []
    if images:
        urls = []
        for img in images:
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict) and img.get("src"):
                urls.append(str(img["src"]))
        if urls:
            out["image_urls"] = urls[:12]
            out["images_count"] = len(urls)

    # Structured Shopify summary for downstream ecommerce analysis
    out["shopify_product"] = {
        "product_name": out.get("product_name"),
        "vendor": out.get("vendor"),
        "collections": out.get("collections") or [],
        "variants": out.get("variants") or [],
        "inventory_quantity": out.get("inventory_quantity"),
        "price": out.get("price"),
        "compare_at_price": out.get("compare_at_price"),
    }
    return out


async def fetch_shopify_product_json(url: str) -> dict[str, Any]:
    handle = _shopify_handle(url)
    if not handle:
        return {}
    base = _base_url(url)
    # Try .js (Ajax API) then .json (Storefront JSON) for richer payload
    for suffix in (".js", ".json"):
        api_url = urljoin(base + "/", f"products/{handle}{suffix}")
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(api_url, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"})
                if not resp.is_success:
                    continue
                data = resp.json()
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        # .json wraps product under "product" key
        product = data.get("product") if isinstance(data.get("product"), dict) else data
        if isinstance(product, dict) and product.get("title"):
            out = _map_shopify_product(product)
            if out:
                return out
    return {}


async def fetch_shopify_products_json(url: str) -> dict[str, Any]:
    """Fallback: products.json?limit=250 and match handle."""
    handle = _shopify_handle(url)
    if not handle:
        return {}
    base = _base_url(url)
    api_url = urljoin(base + "/", "products.json?limit=250")
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(api_url, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"})
            if not resp.is_success:
                return {}
            data = resp.json()
    except Exception:
        return {}
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        return {}
    for prod in products:
        if isinstance(prod, dict) and prod.get("handle") == handle:
            return _map_shopify_product(prod)
    return {}


async def fetch_woocommerce_product(url: str) -> dict[str, Any]:
    slug = _woo_slug(url)
    if not slug:
        return {}
    base = _base_url(url)
    endpoints = [
        f"{base}/wp-json/wc/store/v1/products?slug={slug}",
        f"{base}/wp-json/wc/v3/products?slug={slug}",
        f"{base}/wp-json/wp/v2/product?slug={slug}",
    ]
    headers = {"User-Agent": BROWSER_UA, "Accept": "application/json", "Accept-Language": "en-IN,en;q=0.9"}
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for api_url in endpoints:
            try:
                resp = await client.get(api_url, headers=headers)
                if not resp.is_success:
                    continue
                data = resp.json()
            except Exception:
                continue
            if isinstance(data, list) and data:
                data = data[0]
            if not isinstance(data, dict):
                continue
            if "fraud" in resp.text.lower() or "click here" in resp.text.lower():
                continue
            out: dict[str, Any] = {}
            name = data.get("name") or data.get("title")
            if name:
                out["product_name"] = str(name).strip()
            prices = data.get("prices") if isinstance(data.get("prices"), dict) else {}
            price = (
                data.get("price")
                or data.get("regular_price")
                or prices.get("price")
                or prices.get("regular_price")
            )
            if price is not None:
                try:
                    pval = float(str(price).replace(",", ""))
                    out["price"] = str(int(pval / 100)) if pval >= 10000 and pval == int(pval) else str(int(pval) if pval == int(pval) else pval)
                except (TypeError, ValueError):
                    out["price"] = str(price)
            if data.get("description"):
                out["description"] = re.sub(r"<[^>]+>", " ", str(data["description"]))[:3000]
            if data.get("average_rating"):
                try:
                    out["avg_rating"] = float(data["average_rating"])
                    out["has_reviews"] = True
                except (TypeError, ValueError):
                    pass
            if data.get("rating_count") or data.get("review_count"):
                try:
                    out["review_count"] = int(data.get("rating_count") or data.get("review_count"))
                    out["has_reviews"] = True
                except (TypeError, ValueError):
                    pass
            if out.get("product_name") or out.get("price"):
                return out
    return {}


async def fetch_custom_product_api(url: str) -> dict[str, Any]:
    """Common D2C patterns: /api/product/{slug}, Mamaearth-style."""
    slug = _woo_slug(url) or _shopify_handle(url)
    if not slug:
        return {}
    base = _base_url(url)
    candidates = [
        f"{base}/api/product/{slug}",
        f"{base}/api/products/{slug}",
        f"{base}/api/v1/product/{slug}",
        f"{base}/api/v1/products/{slug}",
    ]
    headers = {"User-Agent": BROWSER_UA, "Accept": "application/json", "Accept-Language": "en-IN,en;q=0.9"}
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for api_url in candidates:
            try:
                resp = await client.get(api_url, headers=headers)
                if not resp.is_success:
                    continue
                if "fraud" in resp.text.lower() or resp.text.strip().startswith("May be"):
                    continue
                data = resp.json()
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            from app.core.extraction.dom_extractors import _walk_product_like

            parsed = _walk_product_like(data, depth=0)
            if parsed.get("product_name") or parsed.get("price"):
                return parsed
    return {}


def extract_magento_from_network(network_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse Magento GraphQL product responses from captured XHR."""
    from app.core.extraction.dom_extractors import _walk_product_like

    best: dict[str, Any] = {}
    best_score = 0
    for item in network_payloads or []:
        url = (item.get("url") or "").lower()
        body = item.get("body")
        if not isinstance(body, dict):
            continue
        if "graphql" not in url and "magento" not in url:
            data_str = json.dumps(body).lower()
            if "productdetail" not in data_str and "products(" not in data_str:
                continue
        parsed = _walk_product_like(body, depth=0)
        # Magento often nests under data.products.items
        items = (
            (body.get("data") or {}).get("products", {}).get("items")
            if isinstance(body.get("data"), dict)
            else None
        )
        if isinstance(items, list) and items:
            nested = _walk_product_like(items[0], depth=0)
            for k, v in nested.items():
                if v not in (None, "", []) and k not in parsed:
                    parsed[k] = v
        score = sum(1 for k in ("product_name", "price", "review_count") if parsed.get(k))
        if score > best_score:
            best_score = score
            best = parsed
    return best


async def fetch_platform_api_product(
    url: str,
    platform: str,
    *,
    network_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Try platform-specific JSON endpoints in priority order."""
    plat = (platform or "").lower()
    payloads = network_payloads or []

    if plat == "shopify" or _shopify_handle(url):
        for fetcher, source in (
            (fetch_shopify_product_json, "shopify_api"),
            (fetch_shopify_products_json, "shopify_products_json"),
        ):
            data = await fetcher(url)
            if data:
                data["_extraction_source"] = source
                return data

    if plat in ("woocommerce", "custom_react") or _woo_slug(url):
        data = await fetch_woocommerce_product(url)
        if data:
            data["_extraction_source"] = "woocommerce_api"
            return data
        data = await fetch_custom_product_api(url)
        if data:
            data["_extraction_source"] = "custom_product_api"
            return data

    if plat == "magento" or any("graphql" in (p.get("url") or "").lower() for p in payloads):
        data = extract_magento_from_network(payloads)
        if data:
            data["_extraction_source"] = "magento_graphql"
            return data

    # Generic custom API attempt for unknown platforms on PDP URLs
    if _woo_slug(url) or _shopify_handle(url):
        data = await fetch_custom_product_api(url)
        if data:
            data["_extraction_source"] = "custom_product_api"
            return data

    return {}
