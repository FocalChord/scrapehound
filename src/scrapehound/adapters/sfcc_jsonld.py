"""Salesforce Commerce Cloud via JSON-LD (e.g. Rebel Sport).

Discovers product links from a search page (config `link_regex`), then reads each
PDP's JSON-LD with extruct: price from the Product offer's priceSpecification,
available sizes from the ProductGroup variants -> generic Product + variants.
"""
from __future__ import annotations

import re

import extruct

from .base import Adapter, register
from ..models import Product, Variant, to_decimal
from ..web import http_client

_SIZE_RE = re.compile(r"US\s*(\d+(?:\.\d+)?)", re.I)


@register("sfcc_jsonld")
class SfccJsonLdAdapter(Adapter):
    required = ["base_url", "link_regex"]
    @property
    def base(self) -> str:
        return self.config["base_url"].rstrip("/")

    def fetch_raw(self) -> list[str]:
        link_re = re.compile(self.config["link_regex"])
        template = self.config.get("product_url_template", "{base}/p/{handle}.html")
        with http_client() as client:
            r = client.get(f"{self.base}{self.config.get('search_path', '/search')}",
                           params={self.config.get("search_param", "q"): self.config.get("search", "")})
            r.raise_for_status()
            pages = []
            for handle in sorted(set(link_re.findall(r.text))):
                try:
                    resp = client.get(template.format(base=self.base, handle=handle))
                    resp.raise_for_status()
                    pages.append(resp.text)
                except Exception:
                    continue
            return pages

    @staticmethod
    def _price(offers: dict):
        current, strike = None, None
        for s in offers.get("priceSpecification") or []:
            val = to_decimal(s.get("price"))
            if "Strikethrough" in (s.get("priceType") or ""):
                strike = val
            elif val is not None:
                current = val
        return (current if current is not None else to_decimal(offers.get("price"))), strike

    def parse(self, raw: list[str]) -> list[Product]:
        products = []
        for page in raw:
            blocks = extruct.extract(page, syntaxes=["json-ld"]).get("json-ld", [])
            product = next((o for o in blocks if o.get("@type") == "Product"), None)
            group = next((o for o in blocks if o.get("@type") == "ProductGroup"), None)
            if not product:
                continue
            offers = product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price, was = self._price(offers)
            if price is None:
                continue
            variants = []
            for v in (group or {}).get("hasVariant", []):
                m = _SIZE_RE.search(v.get("name", ""))
                if m:
                    variants.append(Variant(options={"Size": m.group(1)}, available=True))
            name = product.get("name", "")
            url = offers.get("url") or product.get("url") or self.base
            products.append(Product(
                id=str(product.get("sku") or url), title=name, url=url, price=price,
                was_price=was if (was and was > price) else None,
                image=product.get("image") if isinstance(product.get("image"), str) else None,
                in_stock=bool(variants) or "InStock" in str(offers.get("availability")),
                variants=variants,
            ))
        return products
