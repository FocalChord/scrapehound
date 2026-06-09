"""Sold-price comps: accumulate eBay sold listings into a market-value history.

eBay only exposes ~90 days of sold/completed listings at a time, so a true
"last year" market value has to be *accumulated*: collect sold comps on a
schedule and append the new ones (deduped by item id) to a git-tracked store.
On day one you already get a trailing-90-day picture; it grows into a rolling
year as the collector runs.

  state/comps/<key>.jsonl   append-only sold-comp rows, deduped by item_id

A comp source is just a SourceConfig (type: ebay, query, site, filter, ...);
the collector forces sold/completed on, derives + filters like the pipeline,
then appends. `stats()` windows by sold_date and computes percentiles.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Optional

from . import adapters  # noqa: F401  (registers adapters)
from .adapters import base
from .config import SourceConfig
from .derive import derive_attrs

log = logging.getLogger("scrapehound")

_DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
                 "%b %d %Y", "%B %d %Y")


def parse_sold_date(s: str | None) -> Optional[dt.date]:
    """eBay sold dates come as 'Sold 9 Jun 2026' (AU/UK) or 'Jun 9, 2026' (US)."""
    if not s:
        return None
    s = s.replace("Sold", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def percentile(values: list[float], q: float) -> Optional[float]:
    """Linear-interpolation percentile (q in 0..1) over unsorted values."""
    if not values:
        return None
    v = sorted(values)
    if len(v) == 1:
        return round(v[0], 2)
    k = (len(v) - 1) * q
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return round(v[f] + (v[c] - v[f]) * (k - f), 2)


def summarize(prices: list[float]) -> dict:
    """Headline market-value stats over a list of sale prices."""
    if not prices:
        return {"n": 0}
    return {
        "n": len(prices),
        "min": round(min(prices), 2),
        "p25": percentile(prices, 0.25),
        "p50": percentile(prices, 0.50),
        "p75": percentile(prices, 0.75),
        "p90": percentile(prices, 0.90),
        "p95": percentile(prices, 0.95),
        "max": round(max(prices), 2),
        "mean": round(sum(prices) / len(prices), 2),
    }


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class CompStore:
    """Append-only sold-comp store, deduped by item id (first capture wins)."""

    def __init__(self, key: str, directory: Path | str = "state"):
        self.path = Path(directory) / "comps" / f"{key}.jsonl"

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def append_new(self, rows: list[dict]) -> int:
        """Append rows whose item_id isn't already stored. Returns count added."""
        seen = {r["item_id"] for r in self.load()}
        fresh = [r for r in rows if r["item_id"] not in seen]
        if not fresh:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            for r in fresh:
                f.write(json.dumps(r) + "\n")
        return len(fresh)


def collect(key: str, src: SourceConfig, state_dir: str = "state") -> tuple[int, int]:
    """Scrape sold listings for a comps source and append new ones to the store.

    Returns (added_this_run, total_in_store). Forces sold/completed on so the
    config only needs the query + filters.
    """
    cls = base.REGISTRY.get(src.type)
    if cls is None:
        raise ValueError(f"unknown adapter type {src.type!r} for comps '{key}'")
    opts = {**src.options(), "sold": True, "completed": True}
    products = cls(opts).collect()
    for p in products:
        derive_attrs(p, src.derive)
    products = [p for p in products if src.filter.matches(p)]

    captured = _now_iso()
    rows = []
    for p in products:
        sold = parse_sold_date(p.attrs.get("sold_date"))
        if p.price is None or sold is None:
            continue  # need a price and a sale date to be a usable comp
        rows.append({
            "item_id": p.id,
            "title": p.title,
            "price": float(p.price),
            "currency": p.currency,
            "condition": p.attrs.get("condition"),
            "sold_date": sold.isoformat(),
            "captured_at": captured,
        })
    store = CompStore(key, state_dir)
    added = store.append_new(rows)
    return added, len(store.load())


def _window_prices(rows: list[dict], days: int, currency: str,
                   condition: Optional[str], today: dt.date) -> list[float]:
    cutoff = today - dt.timedelta(days=days)
    out = []
    for r in rows:
        if r.get("currency") != currency:
            continue
        if condition and (r.get("condition") or "").lower() != condition.lower():
            continue
        d = dt.date.fromisoformat(r["sold_date"])
        if d >= cutoff:
            out.append(r["price"])
    return out


def stats(key: str, state_dir: str = "state", windows: tuple[int, ...] = (30, 90, 365),
          currency: Optional[str] = None, condition: Optional[str] = None,
          today: Optional[dt.date] = None) -> dict:
    """Market-value stats per window for a comps key.

    currency defaults to the most common in the store (sold listings can be a
    mix; stats only make sense within one currency).
    """
    rows = CompStore(key, state_dir).load()
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if not rows:
        return {"key": key, "total": 0, "currency": currency, "windows": {}}
    if currency is None:
        currency = Counter(r.get("currency") for r in rows).most_common(1)[0][0]
    dates = [dt.date.fromisoformat(r["sold_date"]) for r in rows
             if r.get("currency") == currency]
    out = {
        "key": key,
        "total": len(rows),
        "currency": currency,
        "condition": condition,
        "span": [min(dates).isoformat(), max(dates).isoformat()] if dates else None,
        "windows": {},
    }
    for w in windows:
        out["windows"][w] = summarize(
            _window_prices(rows, w, currency, condition, today))
    return out


def monthly_trend(key: str, state_dir: str = "state",
                  currency: Optional[str] = None) -> list[dict]:
    """Per-month median (p50) + count, oldest→newest, for charting a trend."""
    rows = CompStore(key, state_dir).load()
    if not rows:
        return []
    if currency is None:
        currency = Counter(r.get("currency") for r in rows).most_common(1)[0][0]
    buckets: dict[str, list[float]] = {}
    for r in rows:
        if r.get("currency") != currency:
            continue
        ym = r["sold_date"][:7]  # YYYY-MM
        buckets.setdefault(ym, []).append(r["price"])
    return [{"month": ym, "p50": percentile(p, 0.5), "n": len(p)}
            for ym, p in sorted(buckets.items())]
