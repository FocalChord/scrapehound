"""Apple store availability adapter (a genuinely bespoke private API).

Most sites don't need their own adapter — Apple's *refurb* store, for instance,
is now just an `embedded_json` config. But Apple's pickup/delivery is a private,
non-standard API with no schema.org markup, so it stays a thin custom client:

  - /shop/retail/pickup-message  -> in-store pickup availability at a store
  - /shop/delivery-message       -> ship / delivery lead time

Emits one price-less Product per part with attrs `pickup` and `ships`. Pair with
`watch: [pickup, ships]` to alert when a config's lead time moves or pickup opens.
"""
from __future__ import annotations

from .base import Adapter, register
from ..models import Product
from .. import web


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
        with web.http_client({"Accept": "application/json",
                              "X-Requested-With": "XMLHttpRequest", "Referer": ref}) as c:
            web.get(c, ref)  # establish session cookies (retrying)
            if self.config.get("store"):
                try:
                    body = web.get_json(c, f"{base}/retail/pickup-message?pl=true&mts.0=regular"
                                        f"&store={self.config['store']}&{parts_qs}")["body"]
                    stores = body.get("stores") or []
                    if stores:
                        out["pickup"] = stores[0].get("partsAvailability", {})
                        out["store"] = stores[0].get("storeName", "")
                except Exception:
                    pass
            if self.config.get("location"):
                try:
                    out["delivery"] = (web.get_json(c, f"{base}/delivery-message?mts.0=regular"
                                       f"&location={self.config['location']}&{parts_qs}")
                                       ["body"]["content"]["deliveryMessage"])
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
