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

    def exists(self) -> bool:
        """True once this source has been scraped at least once (state file
        written). Distinguishes a real first run from a previously-empty baseline,
        so a source that was empty (e.g. all items filtered out) still alerts when
        its first real item appears."""
        return self.state_path.exists()

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
        """Write the snapshot and append history, recording only real changes.

        Each snapshot item carries `first_seen` (full timestamp, set once and
        never changed) and `last_seen` (date — "still listed as of"). last_seen
        is date-granular so the file only changes once a day, not every scrape;
        otherwise it's byte-stable until a price/field actually moves. History
        appends one row per *price change*. All keep all-time-low intact.
        """
        self.dir.mkdir(parents=True, exist_ok=True)
        previous = self.load()
        _MISSING = object()
        day = scraped_at[:10]                       # YYYY-MM-DD
        latest: dict = {}
        changed: list[Product] = []
        for p in products:
            d = p.model_dump(mode="json")
            d.pop("scraped_at", None)               # volatile per-run ts -> not stored
            prev = previous.get(p.key)
            d["first_seen"] = (prev or {}).get("first_seen") or scraped_at
            d["last_seen"] = day
            latest[p.key] = d
            prev_price = prev.get("price") if prev else _MISSING
            if prev_price != d.get("price"):        # new listing or price moved
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
