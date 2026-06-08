"""Declarative attribute derivation — domain knowledge as data, not code.

A source's `derive:` maps an attr name to a spec. Supported specs:

    brand:          {from: title, match: [New Balance, Asics, ...]}
    width:          {from: title, regex: '\\b([2468]E)\\b', upper: true,
                     fallbacks: {x-wide: "4E", extra wide: "4E"}}
    sizes_in_stock: {from_variants: Size}        # available values of that option
    width:          {const: "4E"}                # a fixed value

This is where "shoes have widths and sizes" lives — as config, so the adapters
and core stay domain-agnostic.
"""
from __future__ import annotations

import re
from typing import Any

from .models import Product, as_number


def derive_attrs(p: Product, specs: dict) -> None:
    for name, spec in (specs or {}).items():
        p.attrs[name] = _derive_one(p, spec)


def _derive_one(p: Product, spec: dict) -> Any:
    if "const" in spec:
        return spec["const"]

    if "from_variants" in spec:
        opt = spec["from_variants"]
        numeric = spec.get("numeric", True)
        out = set()
        for v in p.variants:
            if v.available and opt in v.options:
                raw = v.options[opt]
                n = as_number(raw) if numeric else None
                out.add(n if n is not None else raw)
        return sorted(out, key=lambda z: (isinstance(z, str), z))

    src = str(getattr(p, spec.get("from", "title"), "") or "")
    low = src.lower()

    if "match" in spec:                       # first listed value present in src
        for val in spec["match"]:
            if str(val).lower() in low:
                return val
        return spec.get("default")

    if "regex" in spec:
        m = re.search(spec["regex"], src, re.I)
        if m:
            return m.group(1).upper() if spec.get("upper") else m.group(1)
        for kw, val in (spec.get("fallbacks") or {}).items():
            if kw.lower() in low:
                return val
        return spec.get("default")

    return spec.get("default")
