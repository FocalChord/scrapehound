"""Per-source state persistence (committed back by CI so history survives).

  state/{source}.json          last-seen snapshot {key: product}; drives the diff
  state/{source}.history.jsonl append-only log; powers all-time-low
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .models import Product


class Store:
    def __init__(self, source: str, directory: Path | str = "state"):
        self.dir = Path(directory)
        self.state_path = self.dir / f"{source}.json"
        self.history_path = self.dir / f"{source}.history.jsonl"

    def load(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text() or "{}")
        return {}

    def all_time_low(self, key: str) -> Optional[Decimal]:
        if not self.history_path.exists():
            return None
        low: Optional[Decimal] = None
        for line in self.history_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("key") != key:
                continue
            p = Decimal(str(row["price"]))
            low = p if low is None or p < low else low
        return low

    def low_point(self, key: str) -> Optional[tuple[Decimal, str]]:
        """All-time-low price and the date it was first reached, from history."""
        if not self.history_path.exists():
            return None
        low: Optional[Decimal] = None
        when: Optional[str] = None
        for line in self.history_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("key") != key:
                continue
            try:
                p = Decimal(str(row["price"]))
            except (ArithmeticError, ValueError, TypeError):
                continue
            if low is None or p < low:
                low, when = p, row.get("scraped_at")
        return (low, when) if low is not None else None

    def save(self, products: list[Product], scraped_at: str) -> None:
        """Write the snapshot and append history — but only record real changes.

        The snapshot stays byte-identical across no-op scrapes (unchanged items
        keep their prior scraped_at, so git sees no diff), and history gets one
        row per *price change*, not one per scrape. Both keep all-time-low intact.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        previous = self.load()
        _MISSING = object()
        latest: dict = {}
        changed: list[Product] = []
        for p in products:
            d = p.model_dump(mode="json")
            prev = previous.get(p.key)
            if prev is not None and _without_ts(d) == _without_ts(prev):
                d["scraped_at"] = prev.get("scraped_at", d.get("scraped_at"))  # no churn
            latest[p.key] = d
            prev_price = prev.get("price") if prev else _MISSING
            if prev_price != d.get("price"):                                   # new or moved
                changed.append(p)
        self.state_path.write_text(json.dumps(latest, indent=2, sort_keys=True))
        if changed:
            with self.history_path.open("a") as f:
                for p in changed:
                    f.write(json.dumps({"key": p.key, "price": str(p.price),
                                        "scraped_at": scraped_at}) + "\n")

    def compact_history(self) -> int:
        """Collapse runs of identical price per key into one row each (keeping the
        first occurrence's date). Lossless for all-time-low; returns rows removed."""
        if not self.history_path.exists():
            return 0
        rows = [json.loads(l) for l in self.history_path.read_text().splitlines() if l.strip()]
        last: dict = {}
        kept = []
        for r in rows:
            k = r.get("key")
            if last.get(k) != r.get("price"):     # price differs from this key's previous row
                kept.append(r)
                last[k] = r.get("price")
        if len(kept) != len(rows):
            self.history_path.write_text("".join(json.dumps(r) + "\n" for r in kept))
        return len(rows) - len(kept)


def _without_ts(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "scraped_at"}
