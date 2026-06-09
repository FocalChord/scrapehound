"""Marketplace listing model and field normalization (vendored, pure).

The intermediate shape the parser produces before the adapter maps it onto
scrapehound's generic `Product`. Kept separate from scrapehound's own models to
avoid confusion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, fields
from typing import Any, Optional

ITEM_URL = "https://www.facebook.com/marketplace/item/{id}/"
_ITEM_ID_RE = re.compile(r"/marketplace/item/(\d+)")
# Matches "$500", "C$1,200", "£20", "€15.50", or the literal "Free".
_PRICE_RE = re.compile(r"^(?:[A-Z]{0,3}[$£€][\d,]+(?:\.\d+)?|Free)\b", re.IGNORECASE)


@dataclass
class Listing:
    id: str
    title: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = None
    location: Optional[str] = None
    sold: Optional[bool] = None
    created_time: Optional[int] = None
    seller_name: Optional[str] = None
    seller_id: Optional[str] = None
    image_url: Optional[str] = None
    category_id: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id and not self.url:
            self.url = ITEM_URL.format(id=self.id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_complete(self) -> bool:
        """True when this listing has a price (the field sparse views often drop)."""
        return self.price is not None

    @property
    def needs_enrichment(self) -> bool:
        """True when detail-only fields are missing.

        Search cards never carry ``creation_time`` or ``description``; these only
        appear on the item detail page, so enrichment targets their absence.
        """
        return self.created_time is None or self.description is None


def listing_from_node(node: dict[str, Any]) -> Optional[Listing]:
    """Map a raw Marketplace JSON node into a Listing.

    Facebook nests pricing under ``listing_price`` and the seller under
    ``marketplace_listing_seller``; both can be absent on search pages.
    """
    node_id = node.get("id") or node.get("story_key")
    if not node_id:
        return None

    price_obj = node.get("listing_price") or {}
    seller = node.get("marketplace_listing_seller") or {}
    photo = (
        node.get("primary_listing_photo", {})
        .get("image", {})
        .get("uri")
    )
    # PDP nodes expose `redacted_description` (a struct with `.text`) rather than
    # a plain description string.
    desc = node.get("redacted_description")
    if isinstance(desc, dict):
        desc = desc.get("text")

    return Listing(
        id=str(node_id),
        title=node.get("marketplace_listing_title") or node.get("custom_title"),
        # PDP price may lack `formatted_amount`; fall back to a bare amount.
        price=price_obj.get("formatted_amount") or price_obj.get("amount"),
        currency=price_obj.get("currency"),
        location=(node.get("location_text") or {}).get("text")
        if isinstance(node.get("location_text"), dict)
        else node.get("location_text"),
        sold=node.get("is_sold"),
        created_time=node.get("creation_time"),
        seller_name=seller.get("name"),
        seller_id=str(seller["id"]) if seller.get("id") else None,
        image_url=photo,
        category_id=str(node["marketplace_listing_category_id"])
        if node.get("marketplace_listing_category_id")
        else None,
        description=desc,
    )


def listing_from_card(card: dict[str, Any]) -> Optional[Listing]:
    """Map a DOM-extracted Marketplace card into a Listing.

    Logged-out search results render as anchor cards rather than structured
    JSON, so this is the primary extraction path. A card carries:
      - ``href``  -> ``/marketplace/item/{id}/?...``
      - ``text``  -> newline-joined: price(s), title, location
      - ``img``   -> image src
      - ``alt``   -> ``"{title} in {location}"`` (used to split title/location)
    """
    href = card.get("href") or ""
    match = _ITEM_ID_RE.search(href)
    if not match:
        return None
    item_id = match.group(1)

    lines = [ln.strip() for ln in (card.get("text") or "").splitlines() if ln.strip()]
    prices = [ln for ln in lines if _PRICE_RE.match(ln)]
    price = prices[0] if prices else None

    # The alt text "<title> in <location>" is the most reliable split.
    title: Optional[str] = None
    location: Optional[str] = None
    alt = card.get("alt")
    if alt and " in " in alt:
        title, location = alt.rsplit(" in ", 1)
    else:
        non_price = [ln for ln in lines if ln not in prices]
        if non_price:
            location = non_price[-1]
            title = " ".join(non_price[:-1]) or None

    return Listing(
        id=item_id,
        title=title,
        price=price,
        location=location,
        image_url=card.get("img"),
    )


def fieldnames() -> list[str]:
    return [f.name for f in fields(Listing)]
