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
        self.dir.mkdir(parents=True, exist_ok=True)
        latest = {p.key: p.model_dump(mode="json") for p in products}
        self.state_path.write_text(json.dumps(latest, indent=2, sort_keys=True))
        with self.history_path.open("a") as f:
            for p in products:
                f.write(json.dumps({"key": p.key, "price": str(p.price),
                                    "scraped_at": scraped_at}) + "\n")
