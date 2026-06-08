"""Generic browser adapter: scrape any rendered listing via CSS selectors.

Config-driven so one adapter covers very different sites (DigiDirect headless,
New Balance headful via patchright). Selectors use "css" or "css@attr" syntax.
fetch_raw renders the page; parse is pure (selectolax over the HTML). It extracts
generic fields only — domain attributes come from the derive step.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from .base import Adapter, register
from ..models import Product, to_decimal

log = logging.getLogger("scrapehound")


def _origin(url: str) -> str:
    s = urlsplit(url)
    return f"{s.scheme}://{s.netloc}"


def _extract(node, spec):
    if not spec:
        return None
    sel, _, attr = spec.partition("@")
    target = node.css_first(sel) if sel else node
    if target is None:
        return None
    return target.attributes.get(attr) if attr else target.text(strip=True)


@register("browser")
class BrowserAdapter(Adapter):
    def fetch_raw(self) -> str:
        """Render the page, retrying on transient slow renders/timeouts. After
        all attempts fail it raises, and the pipeline skips the source (state
        preserved) rather than reporting everything as removed."""
        attempts = int(self.config.get("retries", 3))
        err = None
        for attempt in range(1, attempts + 1):
            try:
                return self._render()
            except Exception as e:
                err = e
                log.warning("[browser] render attempt %d/%d failed: %s", attempt, attempts, e)
        raise err

    def _render(self) -> str:
        from ..web import browser_page
        c = self.config
        with browser_page(headless=c.get("headless", True), channel=c.get("channel")) as page:
            if c.get("warm_url"):
                page.goto(c["warm_url"], wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
            page.goto(c["url"], wait_until="domcontentloaded", timeout=60000)
            if c.get("dismiss"):
                try:
                    btn = page.locator(c["dismiss"]).first
                    if btn.is_visible(timeout=5000):
                        btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass
            if c.get("wait_for"):
                page.wait_for_selector(c["wait_for"], timeout=c.get("wait_timeout", 30000))
            page.wait_for_timeout(c.get("settle_ms", 3000))
            html = page.content()
        block = c.get("block_text")
        if block and block in html:
            raise RuntimeError(f"{c['url']} blocked (matched {block!r})")
        return html

    def parse(self, raw: str) -> list[Product]:
        c = self.config
        sels = c["selectors"]
        base = c.get("base_url") or _origin(c["url"])
        products: list[Product] = []
        for node in HTMLParser(raw).css(sels["container"]):
            title = _extract(node, sels.get("title"))
            price = to_decimal(_extract(node, sels.get("price")))
            if not title or price is None:
                continue
            url = _extract(node, sels.get("url")) or ""
            if url.startswith("/"):
                url = base + url
            was = to_decimal(_extract(node, sels.get("was_price")))
            sku = _extract(node, sels.get("sku")) or (
                url.rstrip("/").rsplit("/", 1)[-1] if url else title)
            products.append(Product(
                id=str(sku), title=title, url=url or base, price=price,
                was_price=was if (was and was > price) else None,
                image=_extract(node, sels.get("image")),
            ))
        return products
