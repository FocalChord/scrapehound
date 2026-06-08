"""Magento 2 GraphQL adapter (e.g. The Athlete's Foot).

Two-phase: a light list query finds candidates (pruned by the `prefilter` hint),
then a reliable per-sku query reads variants (the list query's nested variants
field is silently truncated under load). Emits generic Products + variants.
"""
from __future__ import annotations

from .base import Adapter, register
from ..models import Product, Variant, to_decimal
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
    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self.config.get("store"):
            h["Store"] = self.config["store"]
        return h

    def _post(self, client, query):
        r = client.post(self.config["graphql_url"], json={"query": query})
        r.raise_for_status()
        return r.json()

    def _list_items(self, client):
        search = self.config.get("search", "")
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

    def fetch_raw(self) -> dict:
        with http_client(self._headers) as client:
            return {"items": self._list_items(client)}

    def parse(self, raw: dict) -> list[Product]:
        base = self.config.get("base_url", "").rstrip("/")
        products = []
        for it in raw.get("items", []):
            mp = (it.get("price_range") or {}).get("minimum_price") or {}
            final = to_decimal((mp.get("final_price") or {}).get("value"))
            if final is None:
                continue
            regular = to_decimal((mp.get("regular_price") or {}).get("value"))
            url_key = it.get("url_key") or ""
            products.append(Product(
                id=it["sku"], title=it.get("name", "").title(),
                url=f"{base}/{url_key}.html" if url_key else base,
                price=final, was_price=regular if (regular and regular > final) else None,
                currency=(mp.get("final_price") or {}).get("currency") or "AUD",
                in_stock=it.get("stock_status") == "IN_STOCK",
                image=(it.get("small_image") or {}).get("url"),
            ))
        return products

    @staticmethod
    def _variants(raw: dict) -> list[Variant]:
        items = (raw.get("data", {}).get("products", {}) or {}).get("items") or []
        out = []
        for v in (items[0].get("variants") if items else []) or []:
            available = (v.get("product") or {}).get("stock_status") == "IN_STOCK"
            size = next((a.get("label") for a in v.get("attributes") or []
                         if a.get("code") == "size"), None)
            if size is not None:
                out.append(Variant(options={"Size": size}, available=available))
        return out

    def collect(self) -> list[Product]:
        with http_client(self._headers) as client:
            products = self.parse({"items": self._list_items(client)})
            seen, cands = set(), []
            for p in products:
                if p.id in seen or not self._prefilter_ok(p.title):
                    continue
                seen.add(p.id)
                cands.append(p)
            for p in cands:
                p.variants = self._variants(self._post(client, _VARIANT_QUERY % {"sku": p.id}))
        return cands
