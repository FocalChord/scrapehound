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


def row_kind(attrs: dict) -> str:
    """Classify a sale by how its price relates to the true clearing price:

      auction  – competitive final bid (truest market value)
      fixed    – Buy It Now at a real transacted price
      offer    – Best Offer accepted; eBay shows the ASKING price, not the
                 accepted amount, so these inflate comps and are excluded from
                 the headline 'realized' market value.
    """
    if attrs.get("best_offer"):
        return "offer"
    if attrs.get("bids") or attrs.get("buying_format") == "Auction":
        return "auction"
    return "fixed"


class CompStore:
    """Append-only sold-comp store, deduped by item id (first capture wins).

    `scope` separates collections of the same query: "" is the global market,
    "au" is the Australia-located market (eBay located_in_country, with the
    appended international section stripped). Each lands in its own file.
    """

    def __init__(self, key: str, directory: Path | str = "state", scope: str = ""):
        name = f"{key}.{scope}.jsonl" if scope else f"{key}.jsonl"
        self.path = Path(directory) / "comps" / name
        # ledger of every item id already classified (kept OR rejected), so the
        # LLM judges each listing exactly once across all future runs
        self.seen_path = self.path.with_suffix(".seen")

    def load_seen(self) -> set[str]:
        if not self.seen_path.exists():
            return set()
        return {ln.strip() for ln in self.seen_path.read_text().splitlines() if ln.strip()}

    def mark_seen(self, ids: list[str]) -> None:
        new = [i for i in ids if i]
        if not new:
            return
        existing = self.load_seen()
        new = [i for i in new if i not in existing]
        if not new:
            return
        self.seen_path.parent.mkdir(parents=True, exist_ok=True)
        with self.seen_path.open("a") as f:
            for i in new:
                f.write(i + "\n")

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


def _rows_from_products(products) -> list[dict]:
    captured = _now_iso()
    rows = []
    for p in products:
        sold = parse_sold_date(p.attrs.get("sold_date"))
        if p.price is None or sold is None:
            continue  # need a price and a sale date to be a usable comp
        a = p.attrs
        rows.append({
            "item_id": p.id,
            "title": p.title,
            "price": float(p.price),
            "currency": p.currency,
            "condition": a.get("condition"),
            "url": (p.url or "").split("?")[0],    # clean /itm/<id> link to the sold listing
            "sold_date": sold.isoformat(),
            "captured_at": captured,
            # sale type — distinguishes true clearing prices from asking prices
            "kind": row_kind(a),                  # auction | fixed | offer
            "buying_format": a.get("buying_format"),
            "best_offer": bool(a.get("best_offer")),
            "bids": a.get("bids"),
            # rich metadata resurfaced for the listings view
            "location": a.get("location"),
            "image": p.image,
            "seller": a.get("seller"),
            "seller_pct": a.get("seller_pct"),
            "shipping": a.get("shipping"),
            "free_shipping": bool(a.get("free_shipping")),
        })
    return rows


def _collect_pass(key: str, src: SourceConfig, state_dir: str, scope: str,
                  extra_opts: dict) -> tuple[int, int]:
    cls = base.REGISTRY.get(src.type)
    if cls is None:
        raise ValueError(f"unknown adapter type {src.type!r} for comps '{key}'")
    opts = {**src.options(), "sold": True, "completed": True, **extra_opts}
    products = cls(opts).collect()
    for p in products:
        derive_attrs(p, src.derive)
    products = [p for p in products if src.filter.matches(p)]
    # drop catalog-matched listings: their ended pages redirect to the eBay
    # product (ePID) page and their titles are genericized (low-quality comps)
    products = [p for p in products if not p.attrs.get("catalog")]
    store = CompStore(key, state_dir, scope)
    match_spec = src.options().get("match")
    # never re-classify: skip ids already stored (kept) or in the seen ledger (rejected)
    seen = {r["item_id"] for r in store.load()}
    if match_spec:
        seen |= store.load_seen()
    fresh = [p for p in products if p.id not in seen]
    keep = fresh
    if match_spec and fresh:
        from .classify import semantic_keep
        keep = semantic_keep(fresh, match_spec, key=lambda p: p.title)
        store.mark_seen([p.id for p in fresh])   # remember kept + rejected
    added = store.append_new(_rows_from_products(keep))
    return added, len(store.load())


def collect(key: str, src: SourceConfig, state_dir: str = "state") -> dict:
    """Scrape sold listings into two stores: the global market and the
    Australia-located market (eBay located_in_country, international section
    stripped). Forces sold/completed on. Returns
    {'global': (added, total), 'au': (added, total)}.
    """
    return {
        "global": _collect_pass(key, src, state_dir, "", {}),
        "au": _collect_pass(key, src, state_dir, "au", {"located_in_country": True}),
    }


def _window_rows(rows: list[dict], days: int, currency: str,
                 condition: Optional[str], today: dt.date) -> list[dict]:
    cutoff = today - dt.timedelta(days=days)
    out = []
    for r in rows:
        if r.get("currency") != currency:
            continue
        if condition and (r.get("condition") or "").lower() != condition.lower():
            continue
        if dt.date.fromisoformat(r["sold_date"]) >= cutoff:
            out.append(r)
    return out


def _window_prices(rows: list[dict], days: int, currency: str,
                   condition: Optional[str], today: dt.date) -> list[float]:
    return [r["price"] for r in _window_rows(rows, days, currency, condition, today)]


def _kind(r: dict) -> str:
    return r.get("kind") or row_kind(r)  # tolerate rows written before `kind`


def _segment(window_rows: list[dict]) -> dict:
    """Split a window's rows by sale type and summarize each.

    `realized` (auction + fixed) is the headline true market value; `offer`
    (Best Offer asking prices) is reported separately and excluded from it.
    """
    by = {"auction": [], "fixed": [], "offer": []}
    for r in window_rows:
        by[_kind(r)].append(r)
    realized = by["auction"] + by["fixed"]

    def _extreme(rows, pick):
        if not rows:
            return None
        r = pick(rows, key=lambda x: x["price"])
        return {"price": r["price"], "url": r.get("url"), "kind": _kind(r),
                "sold_date": r.get("sold_date"), "title": r.get("title"),
                "bids": r.get("bids")}

    prices = lambda rows: [r["price"] for r in rows]  # noqa: E731
    return {
        "realized": summarize(prices(realized)),
        "auction": summarize(prices(by["auction"])),
        "fixed": summarize(prices(by["fixed"])),
        "offer": summarize(prices(by["offer"])),
        "all": summarize(prices(window_rows)),
        "counts": {k: len(v) for k, v in by.items()},
        "lo": _extreme(realized, min),   # cheapest realized sale (with link + sale type)
        "hi": _extreme(realized, max),   # priciest realized sale
    }


def stats(key: str, state_dir: str = "state", windows: tuple[int, ...] = (30, 90, 365),
          currency: Optional[str] = None, condition: Optional[str] = None,
          today: Optional[dt.date] = None, scope: str = "") -> dict:
    """Sale-type-segmented market-value stats per window for a comps key.

    scope "" is the global market, "au" the Australia-located market. currency
    defaults to the most common in the store (sold listings can be a mix; stats
    only make sense within one currency).
    """
    rows = CompStore(key, state_dir, scope).load()
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
        out["windows"][w] = _segment(
            _window_rows(rows, w, currency, condition, today))
    return out


def monthly_trend(key: str, state_dir: str = "state",
                  currency: Optional[str] = None, scope: str = "") -> list[dict]:
    """Per-month realized median (p50) + count, oldest→newest, for the trend.

    Uses realized sales (auction + fixed) only, so the trend tracks true
    clearing prices rather than Best-Offer asking prices.
    """
    rows = CompStore(key, state_dir, scope).load()
    if not rows:
        return []
    if currency is None:
        currency = Counter(r.get("currency") for r in rows).most_common(1)[0][0]
    buckets: dict[str, list[float]] = {}
    for r in rows:
        if r.get("currency") != currency or _kind(r) == "offer":
            continue
        buckets.setdefault(r["sold_date"][:7], []).append(r["price"])  # YYYY-MM
    return [{"month": ym, "p50": percentile(p, 0.5), "n": len(p)}
            for ym, p in sorted(buckets.items())]
