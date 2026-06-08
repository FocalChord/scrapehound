"""Generic browser adapter: scrape any rendered listing page via CSS selectors.

Config-driven, so one adapter covers very different sites:
  - digidirect (regular headless Chromium, cookie dismiss, text prices)
  - New Balance AU (real Chrome headful via patchright to beat Akamai, prices in
    a `content` attribute, sizes implied by the faceted URL)

Selectors use a "css" or "css@attr" syntax (attr reads an attribute, otherwise
inner text). fetch_raw renders the page; parse is pure (selectolax over the HTML),
so it is unit-testable against a saved fixture.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from .base import Adapter, register
from ..models import Product, Filter, to_decimal, parse_brand, parse_width
from ..web import browser_page


def _origin(url: str) -> str:
    s = urlsplit(url)
    return f"{s.scheme}://{s.netloc}"


def _extract(node, spec: Optional[str]):
    if not spec:
        return None
    sel, _, attr = spec.partition("@")
    target = node.css_first(sel) if sel else node
    if target is None:
        return None
    return target.attributes.get(attr) if attr else target.text(strip=True)


@register("browser")
class BrowserAdapter(Adapter):
    def fetch_raw(self, filt: Optional[Filter]) -> str:
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
                try:
                    page.wait_for_selector(c["wait_for"], timeout=c.get("wait_timeout", 30000))
                except Exception:
                    pass
            page.wait_for_timeout(c.get("settle_ms", 3000))
            html = page.content()
        block = c.get("block_text")
        if block and block in html:
            raise RuntimeError(f"{c['url']} blocked (matched {block!r})")
        return html

    def parse(self, raw: str, filt: Optional[Filter]) -> list[Product]:
        c = self.config
        sels = c["selectors"]
        base = c.get("base_url") or _origin(c["url"])
        static = c.get("static_attrs") or {}
        sizes = sorted(filt.targets) if (c.get("sizes_from_filter") and filt) else None

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

            attrs = {"brand": parse_brand(title)}
            if parse_width(title):
                attrs["width"] = parse_width(title)
            attrs.update(static)
            if sizes is not None:
                attrs["sizes_in_stock"] = sizes

            products.append(Product(
                id=str(sku), title=title, url=url or base, price=price,
                was_price=was if (was and was > price) else None,
                image=_extract(node, sels.get("image")), attrs=attrs,
            ))
        return products
