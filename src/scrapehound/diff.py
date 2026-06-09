"""Change detection over a configurable set of watched fields.

By default a source watches `price`, but it can watch any field or attr (e.g.
Apple availability watches `ships` and `pickup`). Computes new / removed / changed
once; the notifier decides what to send per mode. all-time-low is flagged for
numeric price drops.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from .models import Product, as_number


def _canon(v) -> Any:
    """Canonical form for equality: numbers compare numerically, text as text."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return float(s)
    return s.lower()


def _record_value(rec: dict, field: str):
    return rec[field] if field in rec else (rec.get("attrs") or {}).get(field)


class Change(BaseModel):
    product: Product
    field: str
    old: Any = None
    new: Any = None
    all_time_low: bool = False
    low_price: Any = None        # all-time-low price for this model
    low_date: Any = None         # ISO date that low was first reached

    @property
    def dropped(self) -> bool:
        o, n = as_number(self.old), as_number(self.new)
        return o is not None and n is not None and n < o


class Changes(BaseModel):
    new: list[Product] = []
    removed: list[Product] = []
    changes: list[Change] = []

    def any(self) -> bool:
        return bool(self.new or self.removed or self.changes)

    def summary(self) -> str:
        bits = []
        if self.new:
            bits.append(f"{len(self.new)} new")
        if self.removed:
            bits.append(f"{len(self.removed)} removed")
        if self.changes:
            bits.append(f"{len(self.changes)} change(s)")
        return ", ".join(bits) or "no changes"


def diff(previous: dict, current: list[Product], store, watch=("price",)) -> Changes:
    curr = {p.key: p for p in current}
    prev_keys, curr_keys = set(previous), set(curr)

    new = [curr[k] for k in curr_keys - prev_keys]
    removed = [Product(**previous[k]) for k in prev_keys - curr_keys]

    changes = []
    for k in curr_keys & prev_keys:
        p = curr[k]
        for field in watch:
            old, new_v = _record_value(previous[k], field), p.value(field)
            if _canon(old) == _canon(new_v):
                continue
            atl, low_price, low_date = False, None, None
            if field == "price":
                point = store.low_point(k)
                n = as_number(new_v)
                atl = n is not None and (point is None or n <= float(point[0]))
                if atl and n is not None:
                    low_price, low_date = new_v, p.scraped_at   # current run set a new low
                elif point is not None:
                    low_price, low_date = str(point[0]), point[1]
            changes.append(Change(product=p, field=field, old=old, new=new_v,
                                  all_time_low=atl, low_price=low_price, low_date=low_date))
    return Changes(new=new, removed=removed, changes=changes)
