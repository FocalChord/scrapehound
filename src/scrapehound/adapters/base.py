"""Adapter interface + a self-registration decorator.

Add a source type = one Adapter subclass decorated with @register("type"). The
split between fetch_raw (network) and parse (pure) keeps parsing unit-testable
against saved fixtures.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import Product, Filter

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
    def fetch_raw(self, filt: Optional[Filter]):
        """Hit the live source, return its raw payload."""

    @abstractmethod
    def parse(self, raw, filt: Optional[Filter]) -> list[Product]:
        """Pure: raw payload -> normalized Products. No network."""

    def collect(self, filt: Optional[Filter]) -> list[Product]:
        products = self.parse(self.fetch_raw(filt), filt)
        return [p for p in products if filt is None or filt.matches(p)]
