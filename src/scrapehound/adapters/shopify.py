"""Generic Shopify adapter: any store via base_url.

Discovers candidates from /products.json (pruned by the `prefilter` hint), reads
each /products/{handle}.js, and emits generic Products with variants (option
name -> value, availability, price). Cloudflare-walled stores set fetch: browser.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import Adapter, register
from ..models import Product, Variant
from ..web import http_client, browser_page


def _throttled(exc: Exception) -> bool:
    return (isinstance(exc, httpx.HTTPStatusError)
            and exc.response.status_code in (429, 500, 502, 503, 504))


@register("shopify")
class ShopifyAdapter(Adapter):
    required = ["base_url"]
    @property
    def base(self) -> str:
        return self.config["base_url"].rstrip("/")

    def _is_candidate(self, p: dict) -> bool:
        tags = p.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        blob = (p.get("title") or "") + " " + str(p.get("vendor", "")) + " " + " ".join(tags)
        return self._prefilter_ok(blob)

    def _candidate_handles(self, get_json) -> list[str]:
        handles = []
        for page in range(1, int(self.config.get("max_pages", 10)) + 1):
            try:
                data = get_json(f"{self.base}/products.json?limit=250&page={page}")
            except Exception:
                break
            prods = (data or {}).get("products") or []
            if not prods:
                break
            handles += [p["handle"] for p in prods if self._is_candidate(p)]
            if len(prods) < 250:
                break
            time.sleep(0.4)
        return handles

    def _products(self, get_json) -> list[dict]:
        out = []
        for h in self._candidate_handles(get_json):
            try:
                out.append(get_json(f"{self.base}/products/{h}.js"))
            except Exception:
                continue
        return out

    def fetch_raw(self) -> list[dict]:
        if self.config.get("fetch") == "browser":
            with browser_page() as page:
                page.goto(self.base + "/", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
                return self._products(
                    lambda u: page.evaluate("u => fetch(u).then(r => r.json())", u))
        with http_client({"Accept": "application/json"}) as client:
            @retry(stop=stop_after_attempt(3),
                   wait=wait_exponential(multiplier=1, min=1, max=8),
                   retry=retry_if_exception(_throttled), reraise=True)
            def get_json(url):
                r = client.get(url)
                r.raise_for_status()
                return r.json()
            return self._products(get_json)

    def parse(self, raw: list[dict]) -> list[Product]:
        products: list[Product] = []
        for p in raw:
            if not p or not p.get("variants"):
                continue
            price = _cents(p.get("price"))
            if price is None:
                continue
            opt_names = [o.get("name", str(i)) for i, o in enumerate(p.get("options", []))]
            variants = []
            for v in p["variants"]:
                vals = v.get("options") or []
                options = {opt_names[i]: vals[i] for i in range(min(len(opt_names), len(vals)))}
                variants.append(Variant(options=options, available=bool(v.get("available")),
                                        price=_cents(v.get("price"))))
            compare = _cents(p.get("compare_at_price"))
            img = p.get("featured_image") or (p.get("images") or [None])[0]
            if isinstance(img, str) and img.startswith("//"):
                img = "https:" + img
            products.append(Product(
                id=str(p.get("id") or p.get("handle")), title=p["title"],
                url=f"{self.base}/products/{p['handle']}",
                price=price, was_price=compare if (compare and compare > price) else None,
                image=img, in_stock=any(v.available for v in variants), variants=variants,
            ))
        return products


def _cents(v) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    return (Decimal(int(v)) / 100).quantize(Decimal("0.01"))
