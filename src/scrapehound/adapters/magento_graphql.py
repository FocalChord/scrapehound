"""Magento 2 GraphQL adapter (e.g. The Athlete's Foot).

Two-phase: a light list query (no variants) finds candidates, then a reliable
per-sku query reads true per-size stock (the list query's nested variants field
is silently truncated under load).
"""
from __future__ import annotations

from typing import Optional

import httpx

from .base import Adapter, register
from ..models import Product, Filter, parse_size, parse_brand, parse_width, to_decimal
from ..web import http_client

_LIST_QUERY = """
{ products(search: "%(search)s", pageSize: %(ps)d, currentPage: %(page)d) {
  items { sku name url_key stock_status small_image { url }
    price_range { minimum_price {
      final_price { value currency } regular_price { value } } } } } }
"""
_VARIANT_QUERY = """
{ products(filter: { sku: { eq: "%(sku)s" } }) {
  items { ... on ConfigurableProduct {
    variants { product { stock_status } attributes { code label } } } } } }
"""


@register("magento_graphql")
class MagentoGraphQLAdapter(Adapter):
    LIST_PAGE_SIZE = 50

    @property
    def _url(self) -> str:
        return self.config["graphql_url"]

    @property
    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self.config.get("store"):
            h["Store"] = self.config["store"]
        return h

    def _post(self, client, query):
        r = client.post(self._url, json={"query": query})
        r.raise_for_status()
        return r.json()

    def _list_items(self, client, filt):
        search = filt.search if filt and filt.search else "shoes"
        items = []
        for page in range(1, int(self.config.get("max_pages", 3)) + 1):
            q = _LIST_QUERY % {"search": search, "ps": self.LIST_PAGE_SIZE, "page": page}
            page_items = (((self._post(client, q).get("data") or {}).get("products") or {})
                          .get("items") or [])
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < self.LIST_PAGE_SIZE:
                break
        return items

    def fetch_raw(self, filt: Optional[Filter]) -> dict:
        with http_client(self._headers) as client:
            return {"items": self._list_items(client, filt)}

    def parse(self, raw: dict, filt: Optional[Filter]) -> list[Product]:
        base = self.config.get("base_url", "").rstrip("/")
        products = []
        for it in raw.get("items", []):
            mp = (it.get("price_range") or {}).get("minimum_price") or {}
            final = to_decimal((mp.get("final_price") or {}).get("value"))
            if final is None:
                continue
            regular = to_decimal((mp.get("regular_price") or {}).get("value"))
            name = it.get("name", "").title()
            url_key = it.get("url_key") or ""
            products.append(Product(
                id=it["sku"], title=name,
                url=f"{base}/{url_key}.html" if url_key else base,
                price=final, was_price=regular if (regular and regular > final) else None,
                currency=(mp.get("final_price") or {}).get("currency") or "AUD",
                in_stock=it.get("stock_status") == "IN_STOCK",
                image=(it.get("small_image") or {}).get("url"),
                attrs={"brand": parse_brand(it.get("name", "")),
                       "width": parse_width(it.get("name", ""))},
            ))
        return products

    @staticmethod
    def variant_sizes(raw: dict, targets: set) -> list[float]:
        items = (raw.get("data", {}).get("products", {}) or {}).get("items") or []
        if not items:
            return []
        out = []
        for v in items[0].get("variants") or []:
            if (v.get("product") or {}).get("stock_status") != "IN_STOCK":
                continue
            for a in v.get("attributes") or []:
                if a.get("code") == "size":
                    s = parse_size(a.get("label"))
                    if s is not None and (not targets or s in targets):
                        out.append(s)
        return sorted(set(out))

    def collect(self, filt: Optional[Filter]) -> list[Product]:
        targets = filt.targets if filt else set()
        bw = filt.model_copy(update={"require_size_in_stock": False}) if filt else None
        with http_client(self._headers) as client:
            products = self.parse({"items": self._list_items(client, filt)}, filt)
            seen, cands = set(), []
            for p in products:
                if p.id in seen or (bw and not bw.matches(p)):
                    continue
                seen.add(p.id)
                cands.append(p)
            for p in cands:
                raw = self._post(client, _VARIANT_QUERY % {"sku": p.id})
                p.attrs["sizes_in_stock"] = self.variant_sizes(raw, targets)
        if filt and filt.require_size_in_stock and targets:
            cands = [p for p in cands if set(p.attrs.get("sizes_in_stock") or []) & targets]
        return cands
