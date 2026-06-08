"""Generic Shopify adapter: point at any store via base_url.

Discovers candidates from /products.json, reads each /products/{handle}.js for
per-size stock, price, sale, and image. Cloudflare-walled stores set
`fetch: browser`. The product Filter drives both candidate pre-selection and the
final match.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import Adapter, register
from ..models import Product, Filter, parse_size, parse_brand, parse_width
from ..web import http_client, browser_page

_WIDTH_TOKENS = {
    "4E": ("4e", "x-wide", "x wide", "extra wide", "extra-wide"),
    "2E": ("2e",),
}


def _throttled(exc: Exception) -> bool:
    return (isinstance(exc, httpx.HTTPStatusError)
            and exc.response.status_code in (429, 500, 502, 503, 504))


def _width_tokens(widths) -> set[str]:
    out: set[str] = set()
    for w in widths or []:
        out |= set(_WIDTH_TOKENS.get(w.upper(), (w.lower(),)))
    return out


@register("shopify")
class ShopifyAdapter(Adapter):
    @property
    def base(self) -> str:
        return self.config["base_url"].rstrip("/")

    def _is_candidate(self, p: dict, filt: Optional[Filter]) -> bool:
        if filt is None:
            return True
        title = (p.get("title") or "")
        low = title.lower()
        tags = p.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        blob = low + " " + " ".join(tags).lower()
        if filt.brand and filt.brand.lower() not in (str(p.get("vendor", "")).lower() + " " + low):
            return False
        if filt.exclude_terms and any(t.lower() in low for t in filt.exclude_terms):
            return False
        tokens = _width_tokens(filt.widths)
        if tokens and not any(t in blob for t in tokens):
            return False
        return True

    def _candidate_handles(self, get_json, filt) -> list[str]:
        handles = []
        for page in range(1, int(self.config.get("max_pages", 10)) + 1):
            try:
                data = get_json(f"{self.base}/products.json?limit=250&page={page}")
            except Exception:
                break
            prods = (data or {}).get("products") or []
            if not prods:
                break
            handles += [p["handle"] for p in prods if self._is_candidate(p, filt)]
            if len(prods) < 250:
                break
            time.sleep(0.4)
        return handles

    def _products(self, get_json, filt) -> list[dict]:
        out = []
        for h in self._candidate_handles(get_json, filt):
            try:
                out.append(get_json(f"{self.base}/products/{h}.js"))
            except Exception:
                continue
        return out

    def fetch_raw(self, filt: Optional[Filter]) -> list[dict]:
        if self.config.get("fetch") == "browser":
            with browser_page() as page:
                page.goto(self.base + "/", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
                return self._products(
                    lambda u: page.evaluate("u => fetch(u).then(r => r.json())", u), filt)
        with http_client({"Accept": "application/json"}) as client:
            @retry(stop=stop_after_attempt(3),
                   wait=wait_exponential(multiplier=1, min=1, max=8),
                   retry=retry_if_exception(_throttled), reraise=True)
            def get_json(url):
                r = client.get(url)
                r.raise_for_status()
                return r.json()
            return self._products(get_json, filt)

    @staticmethod
    def _size_index(product: dict) -> Optional[int]:
        for o in product.get("options", []):
            name = (o.get("name") if isinstance(o, dict) else o) or ""
            if str(name).lower() == "size":
                return (o.get("position", 1) - 1) if isinstance(o, dict) else 0
        return None

    def parse(self, raw: list[dict], filt: Optional[Filter]) -> list[Product]:
        targets = filt.targets if filt else set()
        products: list[Product] = []
        for p in raw:
            if not p or not p.get("variants"):
                continue
            si = self._size_index(p)
            price = _cents(p.get("price"))
            if price is None:
                continue
            compare = _cents(p.get("compare_at_price"))
            sizes = []
            for v in p["variants"]:
                if not v.get("available") or si is None:
                    continue
                opts = v.get("options") or []
                if si < len(opts):
                    s = parse_size(opts[si])
                    if s is not None and (not targets or s in targets):
                        sizes.append(s)
            img = p.get("featured_image") or (p.get("images") or [None])[0]
            if isinstance(img, str) and img.startswith("//"):
                img = "https:" + img
            title = p["title"]
            products.append(Product(
                id=str(p.get("id") or p.get("handle")), title=title,
                url=f"{self.base}/products/{p['handle']}",
                price=price, was_price=compare if (compare and compare > price) else None,
                image=img, in_stock=any(v.get("available") for v in p["variants"]),
                attrs={"brand": parse_brand(title), "width": parse_width(title) or "4E",
                       "sizes_in_stock": sorted(set(sizes))},
            ))
        return products


def _cents(v) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    return (Decimal(int(v)) / 100).quantize(Decimal("0.01"))
