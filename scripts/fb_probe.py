"""Diagnostic probe: what does Facebook Marketplace actually serve this host?

Navigates the logged-out Marketplace search like the adapter does, then dumps
what it sees (final URL, title, content length, card count, login-wall markers)
plus a screenshot + HTML snapshot to DEBUG_DIR. Used to diagnose why CI returns
zero listings and to test egress workarounds (WARP / Tor / proxy).

Env:
  QUERY, CITY, MAX_PRICE  — search params (defaults: dyson airwrap / melbourne / 1000)
  BROWSER_PROXY           — if set, route the browser through this proxy URL
  DEBUG_DIR               — where to write fb.png / fb.html (default: fb-debug)
"""
from __future__ import annotations

import os
from urllib.parse import quote

from scrapehound.web import browser_page

QUERY = os.environ.get("QUERY", "dyson airwrap")
CITY = os.environ.get("CITY", "melbourne")
MAX_PRICE = os.environ.get("MAX_PRICE", "1000")
DEBUG_DIR = os.environ.get("DEBUG_DIR", "fb-debug")
CARD_SELECTOR = "a[href*='/marketplace/item/']"
URL = (f"https://www.facebook.com/marketplace/{quote(CITY)}/search"
       f"?query={quote(QUERY)}&maxPrice={MAX_PRICE}")

MARKERS = [
    "You must log in to continue",
    "Log in",
    "Log In",
    "marketplace",
    "Marketplace",
    "isn't available",
    "temporarily blocked",
    "We limit how often",
    "security check",
    "captcha",
]


def main() -> int:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    proxy_env = "BROWSER_PROXY" if os.environ.get("BROWSER_PROXY") else None
    print(f"== fb_probe ==\nURL: {URL}\nproxy: {os.environ.get('BROWSER_PROXY', '(none)')}")

    with browser_page(headless=True, proxy_env=proxy_env) as page:
        page.set_default_timeout(60_000)
        try:
            page.goto(URL, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            print(f"goto error: {e}")
        page.wait_for_timeout(5000)
        # try to dismiss the (dismissable) login modal
        try:
            page.locator("div[aria-label='Close']").first.click(timeout=5000)
            page.wait_for_timeout(1500)
        except Exception:
            print("no dismissable Close modal")
        # nudge lazy-loading
        for _ in range(8):
            page.mouse.wheel(0, 2200)
            page.wait_for_timeout(1000)

        content = page.content()
        try:
            n_cards = page.locator(CARD_SELECTOR).count()
        except Exception:
            n_cards = -1

        print(f"FINAL_URL:   {page.url}")
        print(f"TITLE:       {page.title()!r}")
        print(f"CONTENT_LEN: {len(content)}")
        print(f"CARD_COUNT:  {n_cards}")
        low = content.lower()
        for m in MARKERS:
            if m.lower() in low:
                print(f"  marker present: {m!r}")

        try:
            page.screenshot(path=os.path.join(DEBUG_DIR, "fb.png"))
        except Exception as e:  # noqa: BLE001
            print(f"screenshot error: {e}")
        with open(os.path.join(DEBUG_DIR, "fb.html"), "w", encoding="utf-8") as f:
            f.write(content[:800_000])
    print("== done ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
