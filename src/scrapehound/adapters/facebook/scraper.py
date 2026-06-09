"""Browser driver: open Marketplace search, dismiss modal, capture JSON.

Marketplace cannot be reached over plain HTTP — Facebook gates listings behind
TLS/fingerprint/behaviour checks and only serves them inside a real browser
context. We drive scrapehound's shared (patchright/undetected) Chromium via
`web.browser_page`, dismiss the dismissable login modal, capture both GraphQL
network responses and embedded JSON script tags, and scroll to hydrate more
results.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote

SEARCH_URL = (
    "https://www.facebook.com/marketplace/{city}/search?query={query}&maxPrice={max_price}"
)
CLOSE_SELECTOR = "div[aria-label='Close']"
GRAPHQL_MARKER = "/api/graphql/"
CARD_SELECTOR = "a[href*='/marketplace/item/']"
# JS run in-page to pull structured fields off each listing card.
_CARD_JS = """els => els.map(a => {
    const img = a.querySelector('img');
    return {
        href: a.getAttribute('href'),
        text: a.innerText,
        img: img ? img.getAttribute('src') : null,
        alt: img ? img.getAttribute('alt') : null,
    };
})"""


def _jitter(base_ms: int, spread_ms: int = 600) -> None:
    time.sleep((base_ms + random.randint(0, spread_ms)) / 1000.0)


@dataclass
class ScrapeResult:
    """Raw capture from a page: DOM cards (primary) and JSON payloads (fallback)."""

    cards: list[dict[str, Any]] = field(default_factory=list)
    payloads: list[Any] = field(default_factory=list)


def scrape_marketplace(
    city: str,
    query: str,
    max_price: int = 100000,
    limit: int = 50,
    headless: bool = True,
    proxy_env: Optional[str] = None,
    nav_timeout_ms: int = 60_000,
) -> ScrapeResult:
    """Capture cards + JSON payloads from a Marketplace search results page."""
    from ...web import browser_page

    url = SEARCH_URL.format(
        city=quote(city), query=quote(query), max_price=max_price
    )
    payloads: list[Any] = []

    with browser_page(headless=headless, proxy_env=proxy_env) as page:
        page.set_default_timeout(nav_timeout_ms)

        # Capture GraphQL responses as they stream in (preferred source).
        def on_response(response):  # noqa: ANN001
            if GRAPHQL_MARKER in response.url:
                try:
                    payloads.append(response.text())
                except Exception:  # response body may be unavailable
                    pass

        page.on("response", on_response)

        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception:
            pass  # navigation may time out; we still try to read what rendered

        _dismiss_modal(page)
        _scroll_to_hydrate(page, limit)

        cards = _extract_cards(page)
        # Fallback: read embedded JSON script tags from the rendered page.
        payloads.extend(_embedded_json(page))

    return ScrapeResult(cards=cards, payloads=payloads)


def _extract_cards(page) -> list[dict[str, Any]]:  # noqa: ANN001
    try:
        return page.eval_on_selector_all(CARD_SELECTOR, _CARD_JS)
    except Exception:
        return []


def _dismiss_modal(page) -> None:  # noqa: ANN001
    try:
        page.wait_for_selector(CLOSE_SELECTOR, timeout=8_000)
        page.click(CLOSE_SELECTOR)
        _jitter(800)
    except Exception:
        # Modal isn't always shown (e.g. cached consent) — not fatal.
        pass


def _scroll_to_hydrate(page, limit: int) -> None:  # noqa: ANN001
    """Scroll until we have `limit` cards rendered or growth stalls."""
    stagnant = 0
    last_count = 0
    for _ in range(40):
        page.mouse.wheel(0, random.randint(1500, 2500))
        _jitter(900)
        count = page.locator(CARD_SELECTOR).count()
        if count >= limit:
            break
        if count <= last_count:
            stagnant += 1
            if stagnant >= 3:
                break
        else:
            stagnant = 0
        last_count = count


def _embedded_json(page) -> list[str]:  # noqa: ANN001
    try:
        return page.eval_on_selector_all(
            "script[type='application/json']",
            "els => els.map(e => e.textContent)",
        )
    except Exception:
        return []
