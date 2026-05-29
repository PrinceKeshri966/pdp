import re, httpx, sys
sys.path.insert(0, ".")
from app.core.html_metadata import BROWSER_UA
h = httpx.get("https://www.boat-lifestyle.com/products/airdopes-181-pro-bluetooth-earbuds", headers={"User-Agent": BROWSER_UA}, timeout=20).text
# GT variant count
vc = len(re.findall(r'select[^>]*name=["\'][^"\']*option', h, re.I))
vc += len(re.findall(r'class=["\'][^"\']*variant[^"\']*["\'][^>]*>\s*<button', h, re.I))
vc += len(re.findall(r'class=["\'][^"\']*swatch', h, re.I))
vc += len(re.findall(r"data-variant-id", h, re.I))
vc += len(re.findall(r'product-form__input[^>]*type=["\']radio', h, re.I))
print("variants", vc)
# FAQ GT style
faq1 = len(re.findall(r'class=["\'][^"\']*faq[^"\']*["\'][^>]*>[\s\S]*?<details', h, re.I))
faq2 = len(re.findall(r"<details\b", h, re.I))
faq3 = len(re.findall(r"<summary\b", h, re.I))
print("faq details", faq1, faq2, faq3)
# trust jdgm
m = re.search(r'jdgm-prev-badge[^>]*>([\s\S]{0,300})', h, re.I)
print("jdgm block", m.group(1)[:200] if m else "none")
# shipping in product area
footer = h.lower().find("<footer")
pre = h[:footer] if footer > 0 else h
print("shipping pre-footer", bool(re.search(r"free shipping|ships in|delivery in|dispatch|deliver", pre, re.I)))
print("return pre-footer", bool(re.search(r"return policy|easy returns|\d+\s*day[s]?\s*return|money.?back", pre, re.I)))
# first price GT
text = re.sub(r"<[^>]+>", " ", pre)
prices = re.findall(r"(?:₹|Rs\.?\s*|INR\s*)\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
print("first price", prices[0] if prices else None)
