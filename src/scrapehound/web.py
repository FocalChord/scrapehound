"""Shared HTTP and browser helpers."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager

import httpx

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def http_client(extra_headers: dict | None = None, timeout: float = 30) -> httpx.Client:
    return httpx.Client(
        timeout=timeout, follow_redirects=True,
        headers={"User-Agent": BROWSER_UA, **(extra_headers or {})},
    )


@contextmanager
def browser_page(headless: bool = True, channel: str | None = None,
                 proxy_env: str | None = None):
    """A patchright (undetected) Chromium/Chrome page, auto-closed on exit.

    channel="chrome" uses the real Chrome binary (needed to beat Akamai); the
    default bundled Chromium is fine for unprotected sites. proxy_env names an
    environment variable holding a proxy URL, if any.
    """
    from patchright.sync_api import sync_playwright

    kwargs = dict(headless=headless, no_viewport=True)
    if channel:
        kwargs["channel"] = channel
    proxy = os.environ.get(proxy_env) if proxy_env else None
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(tempfile.mkdtemp(), **kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            yield page
        finally:
            ctx.close()
