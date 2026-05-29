import re, httpx, sys
sys.path.insert(0, ".")
from app.core.html_metadata import BROWSER_UA
url = "https://www.boat-lifestyle.com/products/airdopes-181-pro-bluetooth-earbuds"
h = httpx.get(url, headers={"User-Agent": BROWSER_UA}, follow_redirects=True, timeout=20).text
m = re.search(r"Shopify\.theme\s*=\s*\{[^}]*\"name\"\s*:\s*\"([^\"]+)\"", h)
print("theme:", m.group(1) if m else "?")
for pat in ["price-item--sale", "product__price", "jdgm", "verified review", "faq", "accordion-item", "shipping", "return", "product-form__input"]:
    print(pat, h.lower().count(pat.lower()))
vc = len(re.findall(r'select[^>]*name=["\'][^"\']*option', h, re.I))
vc += len(re.findall(r'class=["\'][^"\']*swatch', h, re.I))
vc += len(re.findall(r"data-variant-id", h, re.I))
vc += len(re.findall(r'product-form__input[^>]*type=["\']radio', h, re.I))
print("variant_pickers", vc)
prices = re.findall(r"(?:₹|Rs\.?\s*)\s*([\d,]+)", h[:80000])
print("prices_sample", prices[:8])
