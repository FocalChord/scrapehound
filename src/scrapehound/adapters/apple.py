"""Apple store availability adapter.

Watches Apple's per-part pickup + delivery for a set of part numbers:
  - /shop/retail/pickup-message  -> in-store pickup availability at a store
  - /shop/delivery-message       -> ship / delivery lead time

Emits one (price-less) Product per part with attrs `pickup` (available/ineligible)
and `ships` (e.g. "16-18 weeks"). Pair with `watch: [pickup, ships]` to alert when
a config's lead time moves or pickup opens up.

    apple_mac_studio:
      type: apple
      region: au          # url path segment
      store: R504         # Apple Highpoint (for pickup); omit to skip pickup
      location: "3032"    # postcode (for delivery); omit to skip delivery
      parts: ["MU963X/A", "MU973X/A"]
      watch: [pickup, ships]
"""
from __future__ import annotations

import json

from .base import Adapter, register
from ..models import Product, to_decimal
from ..web import http_client


def _extract_array(html: str, key: str):
    """Pull a balanced JSON array embedded as \"key\":[ ... ] from page HTML."""
    i = html.find(f'"{key}":[')
    if i < 0:
        return []
    start = html.index("[", i)
    depth = 0
    for j in range(start, len(html)):
        if html[j] == "[":
            depth += 1
        elif html[j] == "]":
            depth -= 1
            if depth == 0:
                return json.loads(html[start:j + 1])
    return []


@register("apple")
class AppleAdapter(Adapter):
    required = ["parts"]

    @property
    def region(self) -> str:
        return self.config.get("region", "au")

    @property
    def parts(self) -> list[str]:
        return self.config["parts"]

    def fetch_raw(self) -> dict:
        base = f"https://www.apple.com/{self.region}/shop"
        ref = f"{base}/buy-mac/mac-studio"
        parts_qs = "&".join(f"parts.{i}={p}" for i, p in enumerate(self.parts))
        out: dict = {"pickup": {}, "delivery": {}, "store": ""}
        with http_client({"Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                          "Referer": ref}) as c:
            c.get(ref)  # establish session cookies
            if self.config.get("store"):
                try:
                    body = c.get(f"{base}/retail/pickup-message?pl=true&mts.0=regular"
                                 f"&store={self.config['store']}&{parts_qs}").json()["body"]
                    stores = body.get("stores") or []
                    if stores:
                        out["pickup"] = stores[0].get("partsAvailability", {})
                        out["store"] = stores[0].get("storeName", "")
                except Exception:
                    pass
            if self.config.get("location"):
                try:
                    out["delivery"] = (c.get(f"{base}/delivery-message?mts.0=regular"
                                             f"&location={self.config['location']}&{parts_qs}")
                                       .json()["body"]["content"]["deliveryMessage"])
                except Exception:
                    pass
        return out

    def parse(self, raw: dict) -> list[Product]:
        pickup, delivery = raw.get("pickup", {}), raw.get("delivery", {})
        products = []
        for part in self.parts:
            pinfo = pickup.get(part, {})
            regular = pinfo.get("messageTypes", {}).get("regular", {})
            ships = ((delivery.get(part, {}).get("regular", {})
                      .get("deliveryOptionMessages") or [{}])[0].get("displayName"))
            attrs = {}
            if pinfo.get("pickupDisplay"):
                attrs["pickup"] = pinfo["pickupDisplay"]
            if ships:
                attrs["ships"] = ships
            products.append(Product(
                id=part, title=regular.get("storePickupProductTitle") or part,
                url=f"https://www.apple.com/{self.region}/shop/buy", attrs=attrs,
            ))
        return products


@register("apple_refurb")
class AppleRefurbAdapter(Adapter):
    """Apple Certified Refurbished store (e.g. /au/shop/refurbished/mac).

    Plain HTTP — the page embeds a `tiles` JSON of every refurb product with part
    number, title, price and image. Great for "alert me when a refurb config I
    want comes into stock / drops in price" (new/removed/price via `changes`).
    """
    required = ["category"]

    @property
    def region(self) -> str:
        return self.config.get("region", "au")

    def fetch_raw(self) -> str:
        url = f"https://www.apple.com/{self.region}/shop/refurbished/{self.config['category']}"
        with http_client() as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text

    def parse(self, raw: str) -> list[Product]:
        products = []
        for t in _extract_array(raw, "tiles"):
            part = t.get("partNumber")
            price = to_decimal((t.get("price", {}).get("currentPrice") or {}).get("raw_amount"))
            if not part or price is None:
                continue
            url = (t.get("productDetailsUrl") or "").split("?")[0]
            if url.startswith("/"):
                url = "https://www.apple.com" + url
            srcs = (t.get("image") or {}).get("sources") or []
            image = (srcs[0].get("srcSet", "").split() or [None])[0] if srcs else None
            products.append(Product(id=part, title=t.get("title", part), url=url,
                                    price=price, image=image))
        return products
