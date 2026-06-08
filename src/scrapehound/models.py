"""Generic domain models shared by every adapter.

`Product` is source-agnostic: common commerce fields plus an open `attrs` bag for
source-specific data (brand, width, sizes, discount, ...). `Filter` decides
whether a product qualifies; an empty filter matches everything.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field

_WIDTH_RE = re.compile(r"\b([2468]E)\b")
_KNOWN_BRANDS = [
    "New Balance", "Asics", "Brooks", "Saucony", "Hoka",
    "Mizuno", "Adidas", "Nike", "Salomon", "Skechers", "Leica",
]


def to_decimal(value) -> Optional[Decimal]:
    """Parse a price from a number or a messy string like '$6,554.05'."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = re.sub(r"[^\d.]", "", value)
        if value in ("", "."):
            return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def parse_size(label) -> Optional[float]:
    if label is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(label))
    return float(m.group()) if m else None


def parse_width(name: str) -> Optional[str]:
    if not name:
        return None
    u = name.upper()
    m = _WIDTH_RE.search(u)
    if m:
        return m.group(1)
    if "X-WIDE" in u or "X WIDE" in u or "EXTRA WIDE" in u:
        return "4E"
    if "WIDE" in u:
        return "2E"
    return None


def parse_brand(name: str) -> str:
    low = (name or "").lower()
    for b in _KNOWN_BRANDS:
        if b.lower() in low:
            return b
    return name.split()[0] if name else ""


class Product(BaseModel):
    source: str = ""                 # set by the pipeline to the source key
    id: str                          # stable id within the source (sku)
    title: str
    url: str
    price: Decimal
    was_price: Optional[Decimal] = None
    currency: str = "AUD"
    image: Optional[str] = None
    in_stock: bool = True
    attrs: dict[str, Any] = Field(default_factory=dict)
    scraped_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def on_sale(self) -> bool:
        return self.was_price is not None and self.was_price > self.price

    @property
    def percent_off(self) -> Optional[int]:
        if not self.on_sale:
            return None
        return int(round((1 - (self.price / self.was_price)) * 100))


class Filter(BaseModel):
    """Generic product filter. All criteria are optional; empty matches all."""

    brand: Optional[str] = None
    widths: list[str] = []
    sizes: list[float] = []
    require_size_in_stock: bool = False
    include_terms: list[str] = []
    exclude_terms: list[str] = []
    search: str = ""                 # seed search string for adapters that use it
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None

    @property
    def targets(self) -> set[float]:
        return set(self.sizes)

    def matches(self, p: Product) -> bool:
        title = p.title.lower()
        if self.brand:
            brand = str(p.attrs.get("brand") or "").lower()
            if self.brand.lower() != brand and self.brand.lower() not in title:
                return False
        if self.exclude_terms and any(t.lower() in title for t in self.exclude_terms):
            return False
        if self.include_terms and not any(t.lower() in title for t in self.include_terms):
            return False
        if self.widths:
            w = str(p.attrs.get("width") or "").upper()
            if w not in [x.upper() for x in self.widths]:
                return False
        if self.require_size_in_stock and self.targets:
            if not (self.targets & set(p.attrs.get("sizes_in_stock") or [])):
                return False
        if self.min_price is not None and p.price < self.min_price:
            return False
        if self.max_price is not None and p.price > self.max_price:
            return False
        return True
