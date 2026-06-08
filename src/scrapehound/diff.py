"""Unified change detection.

Computes every change type (new / removed / price change) once; the notifier
decides which ones to send based on the source's notify mode. all-time-low is
flagged for price changes that hit a record low.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from .models import Product, to_decimal


class PriceChange(BaseModel):
    product: Product
    old_price: Decimal
    new_price: Decimal
    all_time_low: bool = False

    @property
    def dropped(self) -> bool:
        return self.new_price < self.old_price


class Changes(BaseModel):
    new: list[Product] = []
    removed: list[Product] = []
    price_changes: list[PriceChange] = []

    def any(self) -> bool:
        return bool(self.new or self.removed or self.price_changes)

    def summary(self) -> str:
        bits = []
        if self.new:
            bits.append(f"{len(self.new)} new")
        if self.removed:
            bits.append(f"{len(self.removed)} removed")
        if self.price_changes:
            bits.append(f"{len(self.price_changes)} price change(s)")
        return ", ".join(bits) or "no changes"


def diff(previous: dict, current: list[Product], store) -> Changes:
    curr = {p.key: p for p in current}
    prev_keys, curr_keys = set(previous), set(curr)

    new = [curr[k] for k in curr_keys - prev_keys]
    removed = [Product(**previous[k]) for k in prev_keys - curr_keys]

    price_changes = []
    for k in curr_keys & prev_keys:
        old = to_decimal(previous[k].get("price"))
        new_price = curr[k].price
        if old is not None and old != new_price:
            low = store.all_time_low(k)
            price_changes.append(PriceChange(
                product=curr[k], old_price=old, new_price=new_price,
                all_time_low=(low is None or new_price <= low),
            ))
    return Changes(new=new, removed=removed, price_changes=price_changes)
