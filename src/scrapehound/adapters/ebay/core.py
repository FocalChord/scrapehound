"""Vendored eBay search core — anti-bot HTTP session + regex result parser.

Lifted from a standalone zero-dependency scraper and trimmed to what the
`ebay` adapter needs: the `Session` (Akamai-resistant HTTP — cookie warming,
adaptive pacing, identity/proxy rotation), the search-URL builder, and the
search-results parser. The CLI, CSV/JSON output, and detail-page enrichment of
the original tool are intentionally dropped — the adapter emits generic
`Product`s and the pipeline owns persistence.

Pure standard library, plus optional `curl_cffi` for a browser-grade TLS+HTTP/2
fingerprint (the cleanest lever against Akamai Bot Manager; falls back to a
subprocess `curl`).
"""
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse

# --------------------------------------------------------------------------- #
# Site registry — add new sites here. (subdomain "www" assumed.)
# --------------------------------------------------------------------------- #
SITES = {
    "us": {"domain": "www.ebay.com",    "lang": "en-US,en;q=0.9"},
    "au": {"domain": "www.ebay.com.au", "lang": "en-AU,en;q=0.9"},
    "uk": {"domain": "www.ebay.co.uk",  "lang": "en-GB,en;q=0.9"},
    "de": {"domain": "www.ebay.de",     "lang": "de-DE,de;q=0.9,en;q=0.8"},
    "ca": {"domain": "www.ebay.ca",     "lang": "en-CA,en;q=0.9,fr;q=0.8"},
    "fr": {"domain": "www.ebay.fr",     "lang": "fr-FR,fr;q=0.9,en;q=0.8"},
    "it": {"domain": "www.ebay.it",     "lang": "it-IT,it;q=0.9,en;q=0.8"},
    "es": {"domain": "www.ebay.es",     "lang": "es-ES,es;q=0.9,en;q=0.8"},
}

# Currency per site, used when a price string carries no explicit symbol.
SITE_CURRENCY = {"us": "USD", "au": "AUD", "uk": "GBP", "de": "EUR",
                 "ca": "CAD", "fr": "EUR", "it": "EUR", "es": "EUR"}

# A pool of realistic desktop browser UAs. Rotated on hard blocks (and
# optionally per page) so a single fingerprint isn't hammered.
USER_AGENTS = [
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
     "Gecko/20100101 Firefox/124.0"),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"),
]

# eBay search query-parameter mappings.
CONDITION_CODES = {
    "new": "1000",
    "open-box": "1500",
    "used": "3000",
    "parts": "7000",
}
SORT_CODES = {
    "best": "12",       # Best Match
    "newest": "10",     # Newly Listed
    "ending": "1",      # Ending Soonest
    "price-low": "15",  # Price + Shipping: lowest first
    "price-high": "16",  # Price + Shipping: highest first
}

# Selectors / markers isolated here so they are easy to update if eBay changes.
CARD_SPLIT_RE = re.compile(r'su-card-container su-card-container--')
ITM_HREF_RE = re.compile(r'href=["\']?(https?://[^"\' >]*?/itm/(\d+)[^"\' >]*)')
IMG_ID_RE = re.compile(r':g:([A-Za-z0-9~_\-]+)')
TITLE_RE = re.compile(
    r's-card__title.*?su-styled-text primary default["\']?>(.*?)</span>', re.S)
SUBTITLE_RE = re.compile(
    r's-card__subtitle.*?su-styled-text secondary default["\']?>(.*?)</span>', re.S)
PRICE_RE = re.compile(r's-card__price["\']?>(.*?)</span>', re.S)
ATTR_PRIMARY_RE = re.compile(
    r'attributes__primary(.*?)(?:attributes__secondary|su-card-container__footer|$)', re.S)
ATTR_SECONDARY_RE = re.compile(
    r'attributes__secondary(.*?)(?:su-card-container__footer|$)', re.S)
SECONDARY_LARGE_RE = re.compile(
    r'su-styled-text secondary large["\']?>(.*?)</span>', re.S)
ANY_STYLED_SPAN_RE = re.compile(
    r'su-styled-text[^>]*>(.*?)</span>', re.S)
FEEDBACK_RE = re.compile(r'([\d.]+)%\s*positive\s*\(([\d.,KkMm]+)\)')
USERNAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._\-]{2,}')
LOCATION_RE = re.compile(r'(?:Located in|>from)\s+([A-Z][A-Za-z .()\-]{1,30}?)\s*<')
# sold/completed cards show "Sold <date>": AU/UK "17 May 2026" or US "May 17, 2026"
SOLD_RE = re.compile(
    r'Sold\s+(\d{1,2}\s+[A-Z][a-z]{2,}\.?\s+\d{4}'
    r'|[A-Z][a-z]{2,}\.?\s+\d{1,2},?\s*\d{4})')
WATCHERS_RE = re.compile(r'([\d,]+)\s+watchers?')
BIDS_RE = re.compile(r'([\d,]+)\s+bids?')
TIMELEFT_RE = re.compile(r'(\d+[dhms]\s*(?:left)?|Time\s*left[^<]*)', re.I)
SPONSORED_RE = re.compile(r'\bSpons[o؜​]*red\b|\bSponsored\b', re.I)

TAG_RE = re.compile(r'<[^>]+>')


def clean(text):
    """Strip tags, unescape entities, collapse whitespace."""
    if text is None:
        return None
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


# curl_cffi (optional) impersonates a real browser's TLS (JA3/JA4) *and* HTTP/2
# (Akamai SETTINGS-frame) fingerprint from inside Python — the cleanest way past
# Akamai Bot Manager. Vanilla curl matches TLS but not the HTTP/2 frame order.
try:
    from curl_cffi import requests as _curl_cffi_requests  # noqa: N813
    HAS_CURL_CFFI = True
except Exception:  # noqa: BLE001
    HAS_CURL_CFFI = False

# Browser profiles for curl_cffi impersonation (rotated on hard blocks).
IMPERSONATE_TARGETS = ["chrome", "chrome124", "chrome131", "safari17_2",
                       "edge101"]


# --------------------------------------------------------------------------- #
# HTTP session: browser-fingerprint backend + cookie warming + adaptive pacing.
#
# Akamai Bot Manager gates on a layered signal — TLS fingerprint (JA4), IP
# reputation (datacenter vs residential), and a validly-minted _abck cookie
# (produced by bmak.js sensor telemetry a plain HTTP client cannot generate).
# We can't mint _abck headlessly, so we maximize the levers we *can* control:
# a browser-like TLS/HTTP2 fingerprint (curl_cffi preferred, else subprocess
# curl), polite + adaptive pacing, and identity/proxy rotation on blocks.
# Use a residential/mobile proxy for the IP-reputation lever.
# --------------------------------------------------------------------------- #
class Session:
    def __init__(self, site, delay=2.0, retries=4, verbose=False,
                 proxies=None, rotate_ua=True, backend="auto", adaptive=True,
                 max_delay=30.0):
        self.site = site
        self.cfg = SITES[site]
        self.delay = delay
        self.base_delay = delay
        self.max_delay = max_delay
        self.adaptive = adaptive
        self.retries = retries
        self.verbose = verbose
        self.rotate_ua = rotate_ua
        self.proxies = list(proxies) if proxies else []
        self._proxy_idx = 0
        self.proxy = self.proxies[0] if self.proxies else None
        self._tmp = tempfile.mkdtemp(prefix="ebay_scrape_")
        self._jar_n = 0
        self.jar = os.path.join(self._tmp, "cookies0.txt")
        self._ua_idx = 0
        self.ua = USER_AGENTS[0]
        self._imp_idx = 0
        self.impersonate = IMPERSONATE_TARGETS[0]
        self._warmed = False
        self._last_request = 0.0
        self._clean_streak = 0
        # request/outcome counters (telemetry)
        self.stats = {"requests": 0, "ok": 0, "soft": 0, "blocked": 0}

        # resolve backend
        if backend == "auto":
            backend = "curl_cffi" if HAS_CURL_CFFI else "curl"
        if backend == "curl_cffi" and not HAS_CURL_CFFI:
            self.log("curl_cffi not installed; falling back to subprocess curl")
            backend = "curl"
        self.backend = backend
        self.curl = shutil.which("curl")
        if backend == "curl" and not self.curl:
            raise RuntimeError("need 'curl' on PATH or `pip install curl_cffi`.")
        self._cr = None
        if backend == "curl_cffi":
            self._new_cr_session()
        self.log("HTTP backend: %s" % self.backend)

    def log(self, *a):
        if self.verbose:
            print("[ebay]", *a, file=sys.stderr)

    def _new_cr_session(self):
        try:
            self._cr = _curl_cffi_requests.Session(impersonate=self.impersonate)
        except Exception:  # noqa: BLE001
            self._cr = _curl_cffi_requests.Session(impersonate="chrome")

    def new_identity(self):
        """Rotate fingerprint + proxy + fresh cookies (a brand-new session)."""
        self._ua_idx = (self._ua_idx + 1) % len(USER_AGENTS)
        self.ua = USER_AGENTS[self._ua_idx]
        self._imp_idx = (self._imp_idx + 1) % len(IMPERSONATE_TARGETS)
        self.impersonate = IMPERSONATE_TARGETS[self._imp_idx]
        if self.proxies:
            self._proxy_idx = (self._proxy_idx + 1) % len(self.proxies)
            self.proxy = self.proxies[self._proxy_idx]
        self._jar_n += 1
        self.jar = os.path.join(self._tmp, "cookies%d.txt" % self._jar_n)
        if self.backend == "curl_cffi":
            self._new_cr_session()
        self._warmed = False
        self.log("rotated identity -> imp=%s ua[%d] proxy=%s"
                 % (self.impersonate, self._ua_idx, self.proxy or "-"))

    def _headers(self, referer):
        return {
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,*/*;q=0.8"),
            "Accept-Language": self.cfg["lang"],
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if referer else "none",
            "Upgrade-Insecure-Requests": "1",
            "Referer": referer or ("https://%s/" % self.cfg["domain"]),
        }

    def _fetch(self, url, referer):
        if self.backend == "curl_cffi":
            return self._fetch_cr(url, referer)
        return self._fetch_curl(url, referer)

    def _fetch_cr(self, url, referer):
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        try:
            r = self._cr.get(url, headers=self._headers(referer),
                             proxies=proxies, timeout=45, allow_redirects=True)
            return r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            self.log("curl_cffi error:", e)
            return 0, ""

    def _fetch_curl(self, url, referer):
        out = os.path.join(self._tmp, "body.html")
        cmd = [self.curl, "-sL", "--compressed", "--max-time", "45",
               "-A", self.ua]
        for k, v in self._headers(referer).items():
            if k == "Referer":
                continue
            cmd += ["-H", "%s: %s" % (k, v)]
        cmd += ["-e", referer or ("https://%s/" % self.cfg["domain"]),
                "-b", self.jar, "-c", self.jar,
                "-w", "%{http_code}", "-o", out, url]
        if self.proxy:
            cmd[1:1] = ["-x", self.proxy]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return 0, ""
        try:
            status = int((p.stdout or "0").strip()[-3:])
        except ValueError:
            status = 0
        body = ""
        if os.path.exists(out):
            with open(out, encoding="utf-8", errors="replace") as f:
                body = f.read()
        return status, body

    @staticmethod
    def _is_challenge(body, status):
        if status in (403, 429, 503) or status == 0:
            return True
        if len(body) < 20000:
            low = body.lower()
            if any(k in low for k in (
                    "pardon our interruption", "captcha", "splashui",
                    "are you a human", "verify you are", "access denied",
                    "robot")):
                return True
            # a real results page is large; a tiny page with no cards is suspect
            if "su-card-container" not in body and "/itm/" not in body:
                return True
        return False

    def warm(self):
        url = "https://%s/" % self.cfg["domain"]
        self.log("warming cookies via", url)
        status, _ = self._fetch(url, None)
        self._warmed = status == 200
        if not self._warmed:
            self.log("warm returned status", status)

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request
        wait = self.delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def report_quality(self, soft_throttled):
        """Adaptive pacing: callers report whether a parsed page looked
        degraded (e.g. listings but no location). Soft-throttle => slow down;
        a run of clean pages => gently speed back toward base delay."""
        if not self.adaptive:
            return
        if soft_throttled:
            self.stats["soft"] += 1
            self._clean_streak = 0
            old = self.delay
            self.delay = min(self.delay * 1.6 + 0.5, self.max_delay)
            self.log("soft-throttle signal; delay %.1f -> %.1fs" % (old, self.delay))
        else:
            self._clean_streak += 1
            if self._clean_streak >= 4 and self.delay > self.base_delay:
                self.delay = max(self.base_delay, self.delay * 0.85)
                self._clean_streak = 0
                self.log("clean streak; relaxing delay -> %.1fs" % self.delay)

    def get(self, url, referer=None):
        if not self._warmed:
            self.warm()
        last_body = ""
        for attempt in range(1, self.retries + 1):
            self._throttle()
            self.stats["requests"] += 1
            status, body = self._fetch(url, referer)
            last_body = body or last_body
            if body and not self._is_challenge(body, status):
                self.stats["ok"] += 1
                self.log("OK %s (%d bytes)" % (url.split("?")[0], len(body)))
                return body
            self.stats["blocked"] += 1
            backoff = min(2.0 * attempt + (attempt % 3) * 0.7, 12.0)
            self.log("attempt %d/%d blocked (status %s, %d bytes); backoff %.1fs"
                     % (attempt, self.retries, status, len(body or ""), backoff))
            # adaptive: a hard block means we're going too fast for this IP
            if self.adaptive:
                self.delay = min(self.delay * 1.8 + 1.0, self.max_delay)
            # rotate fingerprint/proxy/cookies on a hard block; else re-warm
            if status in (403, 429, 503, 0) or len(body or "") < 8000:
                if self.rotate_ua or self.proxies:
                    self.new_identity()
                else:
                    self._warmed = False
                self.warm()
            time.sleep(backoff)
        self.log("giving up on", url)
        return last_body

    def close(self):
        try:
            if self._cr is not None:
                self._cr.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Search URL builder
# --------------------------------------------------------------------------- #
def search_url(site, query, page, *, ipg=60, category=None, min_price=None,
               max_price=None, condition=None, buy_it_now=False, auction=False,
               located_in_country=False, sold=False, completed=False, sort=None):
    """Build an eBay search-results URL for one page of `query` on `site`."""
    base = "https://%s/sch/i.html" % SITES[site]["domain"]
    params = {"_nkw": query, "_pgn": page, "_ipg": ipg}
    if category:
        params["_sacat"] = category
    if min_price is not None:
        params["_udlo"] = min_price
    if max_price is not None:
        params["_udhi"] = max_price
    if condition:
        params["LH_ItemCondition"] = CONDITION_CODES[condition]
    if buy_it_now:
        params["LH_BIN"] = 1
    if auction:
        params["LH_Auction"] = 1
    if located_in_country:
        params["LH_PrefLoc"] = 1
    if sold:
        params["LH_Sold"] = 1
    if completed:
        params["LH_Complete"] = 1
    if sort:
        params["_sop"] = SORT_CODES[sort]
    return base + "?" + urllib.parse.urlencode(params)


# With the "Australia only" location filter (LH_PrefLoc=1) eBay still appends an
# "N items found from eBay international sellers" section after the local results.
# To get a true located-in-country view we parse only the markup before it.
_INTL_DIVIDER_RE = re.compile(r'(?:items?|results?)\s+found\s+from[^<]{0,40}international', re.I)


def local_segment(body: str) -> str:
    """Markup up to eBay's 'international sellers' divider (local results only)."""
    m = _INTL_DIVIDER_RE.search(body) or re.search(r'international sellers', body, re.I)
    return body[:m.start()] if m else body


# --------------------------------------------------------------------------- #
# Parsing: search results
# --------------------------------------------------------------------------- #
def _classify_attributes(attr_texts):
    """Sort a card's secondary-large attribute strings into named fields."""
    out = {"buying_format": None, "shipping": None, "free_shipping": False,
           "item_location": None, "bids": None, "time_left": None,
           "best_offer": False, "returns": None, "extras": []}
    for t in attr_texts:
        low = t.lower()
        if not t:
            continue
        if "buy it now" in low:
            out["buying_format"] = "Buy It Now"
        elif "best offer" in low or "or best offer" in low:
            out["best_offer"] = True
            out["buying_format"] = out["buying_format"] or "Best Offer"
        elif "bid" in low:
            m = BIDS_RE.search(t)
            if m:
                out["bids"] = int(m.group(1).replace(",", ""))
            out["buying_format"] = "Auction"
        elif "left" in low and ("d " in low or "h " in low or "m " in low
                                or "time" in low):
            out["time_left"] = t
        elif ("shipping" in low or "delivery" in low or "postage" in low):
            out["shipping"] = t
            if "free" in low:
                out["free_shipping"] = True
        elif low.startswith("located in") or low.startswith("from "):
            out["item_location"] = re.sub(r"^(Located in|from)\s+", "", t,
                                          flags=re.I)
        elif "return" in low:
            out["returns"] = t
        else:
            out["extras"].append(t)
    return out


def parse_search(body, site):
    """Parse one search-result page into a list of listing dicts."""
    # authoritative promoted/rank map from embedded JSON, if present
    promoted = {}
    for m in re.finditer(
            r'"itemId":(\d+),"VarId":\d+,"promoted":(true|false),"rank":(\d+)',
            body):
        promoted[m.group(1)] = {"promoted": m.group(2) == "true",
                                "rank": int(m.group(3))}

    listings = []
    segments = CARD_SPLIT_RE.split(body)[1:]
    for seg in segments:
        hm = ITM_HREF_RE.search(seg)
        if not hm:
            continue
        item_id = hm.group(2)
        if len(item_id) < 9:  # skip "Shop on eBay" promo placeholders (id 123456)
            continue
        url = html.unescape(hm.group(1))

        tm = TITLE_RE.search(seg)
        title = clean(tm.group(1)) if tm else None
        if not title or title.lower() in ("shop on ebay", "new listing"):
            continue

        pm = PRICE_RE.search(seg)
        price_raw = clean(pm.group(1)) if pm else None
        price_val, currency = parse_price(price_raw, site)

        sm = SUBTITLE_RE.search(seg)
        condition = clean(sm.group(1)) if sm else None

        # primary attribute rows
        ap = ATTR_PRIMARY_RE.search(seg)
        attr_texts = []
        if ap:
            attr_texts = [clean(x) for x in SECONDARY_LARGE_RE.findall(ap.group(1))]
        attrs = _classify_attributes([a for a in attr_texts if a])

        # seller + feedback (secondary attributes). Two markup shapes exist:
        #   normal:    <span primary large>name </span><span primary large>NN% positive (C)</span>
        #   top-rated: <span ... default>name NN% positive (C)</span>
        seller_name = seller_pct = seller_count = None
        asec = ATTR_SECONDARY_RE.search(seg)
        if asec:
            txt = clean(" ".join(ANY_STYLED_SPAN_RE.findall(asec.group(1))))
            fm = FEEDBACK_RE.search(txt)
            if fm:
                seller_pct = float(fm.group(1))
                seller_count = expand_count(fm.group(2))
                before = txt[:fm.start()]
                names = USERNAME_RE.findall(before)
                seller_name = names[-1] if names else (before.strip() or None)
            else:
                names = USERNAME_RE.findall(txt)
                seller_name = names[-1] if names else None

        # fallback: location can appear outside attributes__primary in some
        # page variants; scan the whole card if not already found.
        if not attrs["item_location"]:
            lm = LOCATION_RE.search(seg)
            if lm:
                attrs["item_location"] = clean(lm.group(1))

        watchers = None
        wm = WATCHERS_RE.search(seg)
        if wm:
            watchers = int(wm.group(1).replace(",", ""))
        if attrs["time_left"] is None:
            tlm = TIMELEFT_RE.search(seg)
            if tlm and "left" in tlm.group(1).lower():
                attrs["time_left"] = clean(tlm.group(1))

        sponsored = item_id in promoted and promoted[item_id]["promoted"]
        if not sponsored and SPONSORED_RE.search(seg):
            sponsored = True

        # sold / completed comps (when scraping with sold/completed)
        sold_date = None
        is_sold = False
        sdm = SOLD_RE.search(seg)
        if sdm:
            is_sold = True
            sold_date = clean(sdm.group(1))

        im = IMG_ID_RE.search(url)
        image_url = ("https://i.ebayimg.com/images/g/%s/s-l500.jpg" % im.group(1)
                     if im else None)

        listings.append({
            "item_id": item_id,
            "title": title,
            "url": url,
            "price": price_val,
            "price_raw": price_raw,
            "currency": currency,
            "condition": condition,
            "buying_format": attrs["buying_format"],
            "best_offer": attrs["best_offer"],
            "bids": attrs["bids"],
            "time_left": attrs["time_left"],
            "shipping": attrs["shipping"],
            "free_shipping": attrs["free_shipping"],
            "item_location": attrs["item_location"],
            "returns": attrs["returns"],
            "seller_name": seller_name,
            "seller_feedback_pct": seller_pct,
            "seller_feedback_count": seller_count,
            "watchers": watchers,
            "sponsored": sponsored,
            "is_sold": is_sold,
            "sold_date": sold_date,
            "rank": promoted.get(item_id, {}).get("rank"),
            "image_url": image_url,
            "site": site,
        })
    return listings


def expand_count(s):
    """'2.5K' -> 2500, '1,145' -> 1145, '6.2K' -> 6200."""
    s = s.replace(",", "").strip()
    mult = 1
    if s and s[-1] in "Kk":
        mult, s = 1000, s[:-1]
    elif s and s[-1] in "Mm":
        mult, s = 1000000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


def parse_price(raw, site):
    """Return (numeric_value_or_None, currency_code) from a price string."""
    if not raw:
        return None, None
    currency = None
    if "AU $" in raw or "AU$" in raw:
        currency = "AUD"
    elif "US $" in raw or raw.strip().startswith("$"):
        currency = "USD"
    elif "C $" in raw or "CA$" in raw:
        currency = "CAD"
    elif "£" in raw or "GBP" in raw:
        currency = "GBP"
    elif "€" in raw or "EUR" in raw:
        currency = "EUR"
    if currency is None:
        currency = SITE_CURRENCY.get(site)
    # take the first number; handle both 1,234.56 and 1.234,56 formats
    m = re.search(r"[\d][\d.,]*", raw)
    if not m:
        return None, currency
    num = m.group(0)
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):   # european 1.234,56
            num = num.replace(".", "").replace(",", ".")
        else:                                  # 1,234.56
            num = num.replace(",", "")
    elif "," in num:
        # ambiguous: ,dd at end = decimal, else thousands
        if re.search(r",\d{2}$", num):
            num = num.replace(",", ".")
        else:
            num = num.replace(",", "")
    try:
        return float(num), currency
    except ValueError:
        return None, currency
