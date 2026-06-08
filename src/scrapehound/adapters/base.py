"""Adapter interface + self-registration.

Adapters are pure platform extractors: site -> generic Product[] (with variants).
They hold no domain knowledge and no filtering — derivation and selection happen
in the pipeline from config. Add a type = one @register-decorated subclass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Product

REGISTRY: dict[str, type["Adapter"]] = {}


def register(type_name: str):
    def deco(cls):
        REGISTRY[type_name] = cls
        return cls
    return deco


class Adapter(ABC):
    def __init__(self, config: dict | None = None):
        self.config = config or {}

    @abstractmethod
    def fetch_raw(self):
        """Hit the live source, return its raw payload."""

    @abstractmethod
    def parse(self, raw) -> list[Product]:
        """Pure: raw payload -> generic Products. No network, no filtering."""

    def collect(self) -> list[Product]:
        return self.parse(self.fetch_raw())

    def _prefilter_ok(self, blob: str) -> bool:
        """Cheap fetch-time pruning hint: config `prefilter` is a list of token
        groups; the text must contain a token from every group (AND of ORs)."""
        groups = self.config.get("prefilter") or []
        low = blob.lower()
        return all(any(str(t).lower() in low for t in group) for group in groups)
