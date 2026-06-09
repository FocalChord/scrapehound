"""Facebook Marketplace adapter: a query -> generic Products.

fetch_raw drives a browser to capture cards + GraphQL JSON; parse is pure
(walk JSON / map cards -> Listing -> Product). Logged-out, no credentials.
Platform extras (location, seller, description) go into `attrs`.
"""
from __future__ import annotations

import logging

from ..base import Adapter, register
from ...models import Product, to_decimal
from .parser import parse_result
from .scraper import scrape_marketplace

log = logging.getLogger("scrapehound")


@register("facebook")
class FacebookAdapter(Adapter):
    required = ["query"]

    def fetch_raw(self):
        c = self.config
        return scrape_marketplace(
            city=c.get("city", "losangeles"),
            query=c["query"],
            max_price=c.get("max_price", 100000),
            limit=c.get("limit", 50),
            headless=c.get("headless", True),
            proxy_env=c.get("proxy_env"),
        )

    def parse(self, result) -> list[Product]:
        default_currency = self.config.get("currency", "USD")
        products: list[Product] = []
        for l in parse_result(result.cards, result.payloads):
            products.append(Product(
                id=l.id,
                title=l.title or "(untitled)",
                url=l.url or "",
                price=to_decimal(l.price),
                currency=l.currency or default_currency,
                image=l.image_url,
                attrs={
                    "location": l.location,
                    "seller": l.seller_name,
                    "sold": l.sold,
                    "description": l.description,
                    "category_id": l.category_id,
                },
            ))
        return products
