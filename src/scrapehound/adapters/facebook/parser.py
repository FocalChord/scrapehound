"""Recursively walk Facebook JSON payloads to extract Marketplace listings.

Facebook ships listing data as JSON (both in GraphQL responses and embedded in
``<script type="application/json">`` tags) rather than clean DOM. The stable
extraction strategy is to walk the JSON tree looking for nodes tagged with a
Marketplace ``__typename`` rather than relying on CSS selectors that change.
"""
from __future__ import annotations

import json
from typing import Any, Iterator, Optional

from .listing import Listing, listing_from_card, listing_from_node

LISTING_TYPENAMES = {"MarketplaceProductItem", "GroupCommerceProductItem"}


def walk(obj: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict node in a nested JSON structure that is a listing."""
    if isinstance(obj, dict):
        if obj.get("__typename") in LISTING_TYPENAMES:
            yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk(item)


def parse_payloads(payloads: list[Any]) -> list[Listing]:
    """Parse a mix of raw JSON strings / already-decoded objects into Listings.

    Deduplicates by listing id, preserving the first (most complete) occurrence.
    """
    listings: dict[str, Listing] = {}
    for payload in payloads:
        decoded = _coerce(payload)
        if decoded is None:
            continue
        for node in walk(decoded):
            listing = listing_from_node(node)
            if listing is None:
                continue
            existing = listings.get(listing.id)
            if existing is None:
                listings[listing.id] = listing
            else:
                # The same id can appear as several nodes (a sparse search node
                # plus a rich PDP node). Merge so each fills the other's gaps.
                _merge_into(existing, listing)
    return list(listings.values())


def _merge_into(target: Listing, other: Listing) -> None:
    """Fill any None field on `target` from `other` in place."""
    for key, value in other.to_dict().items():
        if value is not None and getattr(target, key) is None:
            setattr(target, key, value)


def cards_to_listings(cards: list[dict[str, Any]]) -> list[Listing]:
    """Map DOM-extracted cards into Listings, deduped by id (primary path)."""
    listings: dict[str, Listing] = {}
    for card in cards:
        listing = listing_from_card(card)
        if listing is None:
            continue
        listings.setdefault(listing.id, listing)
    return list(listings.values())


def parse_result(cards: list[dict[str, Any]], payloads: list[Any]) -> list[Listing]:
    """Combine DOM cards (primary) with JSON-walk results (fallback/merge).

    Cards reliably carry price/title/location/image for logged-out search.
    JSON payloads, when present, can add seller/category/timestamp and cover
    listings the DOM hasn't rendered yet.
    """
    by_id: dict[str, Listing] = {l.id: l for l in cards_to_listings(cards)}
    for node_listing in parse_payloads(payloads):
        existing = by_id.get(node_listing.id)
        if existing is None:
            by_id[node_listing.id] = node_listing
        else:
            for key, value in node_listing.to_dict().items():
                if getattr(existing, key) is None and value is not None:
                    setattr(existing, key, value)
    return list(by_id.values())


def _coerce(payload: Any) -> Optional[Any]:
    if payload is None:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, (str, bytes)):
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return None
    return None
