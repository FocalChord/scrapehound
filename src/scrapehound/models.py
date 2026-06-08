"""Core domain models — fully generic, no product-category knowledge.

A `Product` is whatever an adapter extracts: common commerce fields, an open
`attrs` bag (filled by the declarative derive step, not by adapters), and generic
`variants` (e.g. size/colour options with availability). Domain semantics like
"width" or "size" live in config (derive + filter), never here.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


def to_decimal(value) -> Optional[Decimal]:
    """Parse a price from a number or a messy string like '$6,554.05'."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = re.sub(r"[^\d.]", "", value)
        if value in ("", "."):
            return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def as_number(x) -> Optional[float]:
    """Best-effort number out of anything (used by rules/derive)."""
    if isinstance(x, (int, float, Decimal)):
        return float(x)
    if x is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(x))
    return float(m.group()) if m else None


class Variant(BaseModel):
    options: dict[str, str] = Field(default_factory=dict)   # e.g. {"Size": "10.5"}
    available: bool = True
    price: Optional[Decimal] = None


class Product(BaseModel):
    source: str = ""                 # set by the pipeline to the source key
    id: str                          # stable id within the source
    title: str
    url: str
    price: Decimal
    was_price: Optional[Decimal] = None
    currency: str = "AUD"
    image: Optional[str] = None
    in_stock: bool = True
    attrs: dict[str, Any] = Field(default_factory=dict)     # filled by derive
    variants: list[Variant] = Field(default_factory=list)
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
