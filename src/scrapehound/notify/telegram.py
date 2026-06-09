"""Telegram notification: named bots + HTML cards.

Mode-aware: `changes` sends new/removed/changed cards; `price_drop` sends only
price drops + newly-on-sale items. Cards are sent as a `sendMessage` with a large
link preview, so the product image is pulled from the page and tapping it (or the
linked title) opens the retailer — no upload, no button. Price drops show the
all-time low and the date it was reached.
"""
from __future__ import annotations

import datetime as dt
import html

import httpx

from ..config import BotConfig
from ..diff import Change, Changes
from ..models import Product, as_number


def _e(s) -> str:
    return html.escape(str(s))


def _money(v) -> str:
    if v is None or v == "":
        return "—"
    try:
        return f"${float(str(v).replace(',', '').replace('$', '')):,.2f}"
    except ValueError:
        return f"${v}"


def _num(s) -> str:
    f = float(s)
    return str(int(f)) if f == int(f) else str(f)


def _sizes(p: Product) -> str:
    v = p.attrs.get("sizes_in_stock")
    if not isinstance(v, list) or not v:
        return ""
    return ", ".join(_num(s) for s in v)


def _fmt_date(iso) -> str:
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%-d %b %Y")
    except (ValueError, TypeError):
        return _e(iso)


def _link(text: str, url: str) -> str:
    if not url:
        return f"<b>{_e(text)}</b>"
    return f'<a href="{html.escape(url, quote=True)}">{_e(text)}</a>'


def _title_link(p: Product) -> str:
    return _link(p.title, p.url)


def _attrs_line(p: Product) -> str:
    return "  ".join(f"{k}: {_e(v)}" for k, v in p.attrs.items() if v not in (None, "", []))


def _detail(p: Product) -> str:
    if p.price is not None:
        s = f"<b>{_money(p.price)}</b>"
        if p.on_sale:
            s += f"  <s>{_money(p.was_price)}</s> -{p.percent_off}%"
        return s
    return _attrs_line(p)


def _low_line(ch: Change) -> str:
    if ch.low_price is None:
        return ""
    if ch.all_time_low:
        return f"\U0001f525 <b>all-time low</b> · {_money(ch.low_price)}"
    return f"\U0001f4c9 lowest was {_money(ch.low_price)} · {_fmt_date(ch.low_date)}"


def card_new(p: Product, source: str):
    return p.image, f"\U0001f195 {_title_link(p)}\n{_detail(p)}\n<i>{_e(source)}</i>", p.url


def card_removed(p: Product, source: str):
    return None, f"❌ <b>{_e(p.title)}</b>\nno longer listed\n<i>{_e(source)}</i>", None


def card_change(ch: Change, source: str):
    p = ch.product
    if ch.field != "price":
        body = (f"\U0001f514 {_title_link(p)}\n"
                f"{_e(ch.field)}: {_e(ch.old)}  ➜  <b>{_e(ch.new)}</b>\n"
                f"<i>{_e(source)}</i>")
        return p.image, body, p.url

    lines = ["\U0001f525 <b>PRICE DROP</b>" if ch.dropped else "\U0001f4c8 <b>Price up</b>",
             _title_link(p),
             f"<s>{_money(ch.old)}</s>  ➜  <b>{_money(ch.new)}</b>"]
    o, n = as_number(ch.old), as_number(ch.new)
    if ch.dropped and o and n:
        pct = p.percent_off
        extra = f"  ·  <b>{pct}% off</b>" if pct else ""
        lines.append(f"\U0001f4b8 save <b>{_money(o - n)}</b>{extra}")
    if low := _low_line(ch):
        lines.append(low)
    if sizes := _sizes(p):
        lines.append(f"\U0001f7e2 sizes {sizes}")
    lines.append(f"<i>{_e(source)}</i>")
    return p.image, "\n".join(lines), p.url


def _cards_for(changes: Changes, source: str, mode: str):
    cards = []
    if mode == "price_drop":
        cards += [card_change(c, source) for c in changes.changes
                  if c.field == "price" and c.dropped]
        cards += [card_new(p, source) for p in changes.new if p.on_sale]
    else:  # "changes"
        cards += [card_new(p, source) for p in changes.new]
        cards += [card_removed(p, source) for p in changes.removed]
        cards += [card_change(c, source) for c in changes.changes]
    return cards


def preview_changes(changes: Changes, source: str, mode: str) -> str:
    cards = _cards_for(changes, source, mode)
    return "\n\n".join(c[1] for c in cards) or "(nothing to send)"


def summary_text(products: list[Product], source: str, limit: int = 40) -> str:
    ps = sorted(products, key=lambda x: (x.price is None, x.price or 0))
    lines = [f"\U0001f4cb <b>{_e(source)}</b> — {len(ps)} item(s)", ""]
    for p in ps[:limit]:
        lines.append(f"{_detail(p)}  {_link(p.title, p.url)}")
    if len(ps) > limit:
        lines.append(f"… +{len(ps) - limit} more")
    return "\n".join(lines)


class TelegramBot:
    def __init__(self, name: str, token: str | None, chat_id: str | None):
        self.name, self.token, self.chat_id = name, token, chat_id

    @classmethod
    def from_config(cls, name: str, cfg: BotConfig) -> "TelegramBot":
        token, chat = cfg.creds()
        return cls(name, token, chat)

    def has_creds(self) -> bool:
        return bool(self.token and self.chat_id)

    def _api(self, method: str, payload: dict) -> dict:
        r = httpx.post(f"https://api.telegram.org/bot{self.token}/{method}",
                       json={"chat_id": self.chat_id, **payload}, timeout=30)
        r.raise_for_status()
        return r.json()

    def send(self, text: str) -> dict:
        return self._api("sendMessage", {"text": text, "parse_mode": "HTML",
                                         "link_preview_options": {"is_disabled": True}})

    def send_card(self, photo: str | None, caption: str, url: str | None) -> dict:
        # Real uploaded photo (always shows); the title in the caption is the link,
        # so there's no button. No image -> message with a link preview as fallback.
        if photo:
            try:
                return self._api("sendPhoto", {"photo": photo, "caption": caption,
                                               "parse_mode": "HTML"})
            except httpx.HTTPError:
                pass
        preview = ({"url": url, "prefer_large_media": True, "show_above_text": True}
                   if url else {"is_disabled": True})
        return self._api("sendMessage", {"text": caption, "parse_mode": "HTML",
                                         "link_preview_options": preview})

    def send_changes(self, changes: Changes, source: str, mode: str) -> int:
        cards = _cards_for(changes, source, mode)
        for photo, caption, url in cards:
            self.send_card(photo, caption, url)
        return len(cards)
