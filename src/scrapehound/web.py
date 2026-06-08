"""Shared HTTP and browser helpers."""
from __future__ import annotations

import json as _json
import os
import re
import tempfile
from contextlib import contextmanager
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def http_client(extra_headers: dict | None = None, timeout: float = 30) -> httpx.Client:
    return httpx.Client(
        timeout=timeout, follow_redirects=True,
        headers={"User-Agent": BROWSER_UA, **(extra_headers or {})},
    )


def _retryable(exc: Exception) -> bool:
    return (isinstance(exc, (httpx.TimeoutException, httpx.TransportError))
            or (isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in (429, 500, 502, 503, 504)))


def get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    """GET with retry/backoff on timeouts, transport errors and 429/5xx."""
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
           retry=retry_if_exception(_retryable), reraise=True)
    def _go():
        r = client.get(url, **kw)
        r.raise_for_status()
        return r
    return _go()


def get_json(client: httpx.Client, url: str, **kw) -> Any:
    return get(client, url, **kw).json()


def extract_json_array(html: str, key: str):
    """Pull a balanced JSON array embedded as \"key\":[ ... ] out of page HTML."""
    i = html.find(f'"{key}":[')
    if i < 0:
        return []
    start = html.index("[", i)
    depth = 0
    for j in range(start, len(html)):
        if html[j] == "[":
            depth += 1
        elif html[j] == "]":
            depth -= 1
            if depth == 0:
                try:
                    return _json.loads(html[start:j + 1])
                except ValueError:
                    return []
    return []


def dig(obj: Any, path: str):
    """Walk a dotted path with numeric indices, e.g. 'price.currentPrice.raw_amount'."""
    cur = obj
    for part in str(path).split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            cur = cur[int(part)] if part.isdigit() and int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def first_url(value) -> str | None:
    """A single URL from a plain string or a srcSet ('a.jpg 1x, b.jpg 2x')."""
    if not value:
        return None
    return re.split(r"[\s,]+", str(value).strip())[0] or None


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
