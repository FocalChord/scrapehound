"""eBay search adapter: a query -> generic Products via the vendored core.

fetch_raw drives the anti-bot `Session` over N result pages; parse is pure
(regex over the captured HTML). Platform-native extras (condition, location,
seller, sold) go into `attrs` — consistent with the apple adapter.
"""
from __future__ import annotations

import logging

from ..base import Adapter, register
from ...models import Product, to_decimal
from . import core

log = logging.getLogger("scrapehound")


@register("ebay")
class EbayAdapter(Adapter):
    required = ["query"]

    def fetch_raw(self) -> list[str]:
        c = self.config
        site = c.get("site", "us")
        proxies = c.get("proxy") or []
        if isinstance(proxies, str):
            proxies = [proxies]
        sess = core.Session(
            site,
            delay=c.get("delay", 2.0),
            retries=c.get("retries", 4),
            backend=c.get("backend", "auto"),
            adaptive=c.get("adaptive", True),
            max_delay=c.get("max_delay", 30.0),
            proxies=proxies,
            verbose=c.get("verbose", False),
        )
        bodies: list[str] = []
        referer = "https://%s/" % core.SITES[site]["domain"]
        try:
            for page in range(1, int(c.get("pages", 1)) + 1):
                url = core.search_url(
                    site, c["query"], page,
                    ipg=c.get("ipg", 60),
                    category=c.get("category"),
                    min_price=c.get("min_price"),
                    max_price=c.get("max_price"),
                    condition=c.get("condition"),
                    buy_it_now=c.get("buy_it_now", False),
                    auction=c.get("auction", False),
                    located_in_country=c.get("located_in_country", False),
                    sold=c.get("sold", False),
                    completed=c.get("completed", False),
                    sort=c.get("sort"),
                )
                body = sess.get(url, referer=referer)
                referer = url
                # "located in country" => drop eBay's appended international section
                if c.get("located_in_country"):
                    body = core.local_segment(body)
                if not core.parse_search(body, site):
                    break  # empty page (or no local results left) -> stop
                bodies.append(body)
        finally:
            sess.close()
        return bodies

    def parse(self, bodies: list[str]) -> list[Product]:
        site = self.config.get("site", "us")
        default_currency = core.SITE_CURRENCY.get(site, "USD")
        products: list[Product] = []
        seen: set[str] = set()
        for body in bodies:
            for d in core.parse_search(body, site):
                if d["item_id"] in seen:
                    continue
                seen.add(d["item_id"])
                products.append(Product(
                    id=d["item_id"],
                    title=d["title"],
                    url=d["url"],
                    price=to_decimal(d["price"]),
                    currency=d["currency"] or default_currency,
                    image=d["image_url"],
                    attrs={
                        "condition": d["condition"],
                        "location": d["item_location"],
                        "seller": d["seller_name"],
                        "seller_pct": d["seller_feedback_pct"],
                        "buying_format": d["buying_format"],
                        "best_offer": d["best_offer"],
                        "bids": d["bids"],
                        "shipping": d["shipping"],
                        "free_shipping": d["free_shipping"],
                        "sold": d["is_sold"],
                        "sold_date": d["sold_date"],
                    },
                ))
        return products
