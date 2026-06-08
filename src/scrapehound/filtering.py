"""Generic, declarative selection — no domain knowledge.

A Filter is a list of Rules (implicit AND). Each rule targets a top-level
`field` (title, price, in_stock, ...) or an `attr` (a derived attribute) and
applies an `op`. Empty filter matches everything.

    - {attr: brand, op: eq, value: New Balance}
    - {field: title, op: not_contains, value: [work boot, women]}
    - {attr: width, op: in, value: ["4E"]}
    - {attr: sizes_in_stock, op: intersects, value: [10, 10.5]}
    - {field: price, op: lte, value: 300}
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, model_validator

from .models import Product, as_number

KNOWN_OPS = {
    "eq", "ne", "in", "contains_any", "contains_all", "not_contains",
    "intersects", "gte", "lte", "gt", "lt", "regex", "exists",
}


def _norm_set(values) -> set:
    out = set()
    for v in values or []:
        n = as_number(v)
        out.add(n if n is not None else str(v).lower())
    return out


class Rule(BaseModel):
    field: Optional[str] = None
    attr: Optional[str] = None
    op: str
    value: Any = None

    @model_validator(mode="after")
    def _validate(self):
        if self.op not in KNOWN_OPS:
            raise ValueError(f"unknown filter op {self.op!r}; known: {sorted(KNOWN_OPS)}")
        if bool(self.field) == bool(self.attr):
            raise ValueError(f"rule needs exactly one of field/attr (got field={self.field!r}, attr={self.attr!r})")
        return self

    def _target(self, p: Product):
        return getattr(p, self.field, None) if self.field else p.attrs.get(self.attr)

    def matches(self, p: Product) -> bool:
        t, v, op = self._target(p), self.value, self.op
        if op == "exists":
            return t is not None
        if op in ("eq", "ne"):
            equal = t is not None and str(t).lower() == str(v).lower()
            return equal if op == "eq" else not equal
        if op == "in":
            return t is not None and str(t).lower() in [str(x).lower() for x in (v or [])]
        if op in ("contains_any", "contains_all", "not_contains"):
            s = str(t or "").lower()
            vals = [str(x).lower() for x in (v if isinstance(v, list) else [v])]
            if op == "contains_all":
                return all(x in s for x in vals)
            hit = any(x in s for x in vals)
            return hit if op == "contains_any" else not hit
        if op == "intersects":
            return bool(_norm_set(t if isinstance(t, list) else [t]) & _norm_set(v))
        if op in ("gte", "lte", "gt", "lt"):
            tn, vn = as_number(t), as_number(v)
            if tn is None or vn is None:
                return False
            return {"gte": tn >= vn, "lte": tn <= vn, "gt": tn > vn, "lt": tn < vn}[op]
        if op == "regex":
            return bool(re.search(str(v), str(t or ""), re.I))
        raise ValueError(f"unknown filter op: {op}")


class Filter(BaseModel):
    rules: list[Rule] = []

    def matches(self, p: Product) -> bool:
        return all(r.matches(p) for r in self.rules)
