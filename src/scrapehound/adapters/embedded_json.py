"""Generic adapter for sites that embed their product data as JSON in the page.

A huge swathe of modern sites ship a JSON blob in the HTML (Apple's refurb
`tiles`, Next.js `__NEXT_DATA__`, bespoke stores). Point this at the array `key`
and map fields by dotted path — no bespoke code:

    type: embedded_json
    url: "https://www.apple.com/au/shop/refurbished/mac"
    base_url: "https://www.apple.com"
    key: tiles
    map:
      id: partNumber
      title: title
      price: price.currentPrice.raw_amount
      url: productDetailsUrl
      image: image.sources.0.srcSet
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .base import Adapter, register
from ..models import Product, to_decimal
from .. import web


@register("embedded_json")
class EmbeddedJsonAdapter(Adapter):
    required = ["url", "key", "map"]

    def fetch_raw(self) -> str:
        with web.http_client() as c:
            return web.get(c, self.config["url"]).text

    def parse(self, html: str) -> list[Product]:
        m = self.config["map"]
        s = urlsplit(self.config["url"])
        base = self.config.get("base_url") or f"{s.scheme}://{s.netloc}"
        products = []
        for item in web.extract_json_array(html, self.config["key"]):
            ident = web.dig(item, m["id"])
            if ident in (None, ""):
                continue
            price = to_decimal(web.dig(item, m["price"])) if "price" in m else None
            url = str(web.dig(item, m.get("url", "")) or "").split("?")[0]
            if url.startswith("/"):
                url = base + url
            products.append(Product(
                id=str(ident),
                title=str(web.dig(item, m.get("title", "")) or ident),
                url=url, price=price,
                image=web.first_url(web.dig(item, m["image"])) if "image" in m else None,
            ))
        return products
