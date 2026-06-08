"""Generic schema.org JSON-LD adapter — works on any site with Product markup.

schema.org Product is the de-facto SEO standard, so most e-commerce PDPs carry it
(verified across Shopify, SFCC, and custom stacks like JB Hi-Fi). Give it either
an explicit `product_urls` list, or a `search`/`link_regex` to discover PDPs; it
reads price (offer price or priceSpecification) and any in-stock sizes from a
ProductGroup. Replaces the old SFCC-specific adapter (registered as both names).

    type: jsonld
    base_url: "https://www.rebelsport.com.au"
    search: "new balance 4e"
    link_regex: "/p/(new-balance-[a-z0-9-]*4e[a-z0-9-]*-[A-Z0-9]+)\\\\.html"
    # or simply:  product_urls: ["https://store/p/thing", ...]
"""
from __future__ import annotations

import re

import extruct

from .base import Adapter, register
from ..models import Product, Variant, to_decimal
from .. import web

_SIZE_RE = re.compile(r"US\s*(\d+(?:\.\d+)?)", re.I)


@register("jsonld")
@register("sfcc_jsonld")   # backwards-compatible alias
class JsonLdAdapter(Adapter):
    def _pdp_urls(self, client) -> list[str]:
        if self.config.get("product_urls"):
            return list(self.config["product_urls"])
        base = self.config["base_url"].rstrip("/")
        link_re = re.compile(self.config["link_regex"])
        tmpl = self.config.get("product_url_template", "{base}/p/{handle}.html")
        r = web.get(client, f"{base}{self.config.get('search_path', '/search')}",
                    params={self.config.get("search_param", "q"): self.config.get("search", "")})
        return [tmpl.format(base=base, handle=h) for h in sorted(set(link_re.findall(r.text)))]

    def fetch_raw(self) -> list[str]:
        with web.http_client() as client:
            pages = []
            for u in self._pdp_urls(client):
                try:
                    pages.append(web.get(client, u).text)
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
            product = next((o for o in blocks if "Product" in str(o.get("@type", ""))
                            and o.get("@type") != "ProductGroup"), None)
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
            url = offers.get("url") or product.get("url") or self.config.get("base_url", "")
            img = product.get("image")
            products.append(Product(
                id=str(product.get("sku") or url), title=name, url=url, price=price,
                was_price=was if (was and was > price) else None,
                image=img if isinstance(img, str) else (img[0] if isinstance(img, list) and img else None),
                in_stock=bool(variants) or "InStock" in str(offers.get("availability")),
                variants=variants,
            ))
        return products
