"""Telegram notification: named bots + HTML cards.

Mode-aware: `changes` sends new/removed/changed cards; `price_drop` sends only
price drops + newly-on-sale items. Handles any watched field (price, or attrs
like availability/lead-time) and price-less products. Card builders feed both
real sends and dry-run previews.
"""
from __future__ import annotations

import html

import httpx

from ..config import BotConfig
from ..diff import Change, Changes
from ..models import Product


def _e(s) -> str:
    return html.escape(str(s))


def _money(v) -> str:
    if v is None or v == "":
        return "—"
    try:
        return f"${float(str(v).replace(',', '').replace('$', '')):,.2f}"
    except ValueError:
        return f"${v}"


def _link(text: str, url: str) -> str:
    if not url:
        return f"<b>{_e(text)}</b>"
    return f'<a href="{html.escape(url, quote=True)}">{_e(text)}</a>'


def _button(p: Product):
    return {"text": "View ↗", "url": p.url} if p.url else None


def _attrs_line(p: Product) -> str:
    return "  ".join(f"{k}: {_e(v)}" for k, v in p.attrs.items() if v not in (None, "", []))


def _detail(p: Product) -> str:
    if p.price is not None:
        s = f"<b>{_money(p.price)}</b>"
        if p.on_sale:
            s += f"  <s>{_money(p.was_price)}</s> -{p.percent_off}%"
        return s
    return _attrs_line(p)


def card_new(p: Product, source: str):
    return p.image, f"\U0001f195 <b>{_e(p.title)}</b>\n{_detail(p)}\n\U0001f3f7️ <i>{_e(source)}</i>", _button(p)


def card_removed(p: Product, source: str):
    return None, f"❌ <b>{_e(p.title)}</b>\nno longer listed\n\U0001f3f7️ <i>{_e(source)}</i>", None


def card_change(ch: Change, source: str):
    p = ch.product
    if ch.field == "price":
        arrow = "\U0001f4c9" if ch.dropped else "\U0001f4c8"
        line = f"{_money(ch.old)} → <b>{_money(ch.new)}</b>"
        if ch.dropped and ch.all_time_low:
            line += "  \U0001f525 all-time low"
    else:
        arrow = "\U0001f514"
        line = f"{_e(ch.field)}: {_e(ch.old)} → <b>{_e(ch.new)}</b>"
    return p.image, f"{arrow} <b>{_e(p.title)}</b>\n{line}\n\U0001f3f7️ <i>{_e(source)}</i>", _button(p)


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
                                         "disable_web_page_preview": True})

    def send_card(self, photo: str | None, caption: str, button: dict | None) -> dict:
        markup = {"inline_keyboard": [[button]]} if button else None
        if photo:
            try:
                payload = {"photo": photo, "caption": caption, "parse_mode": "HTML"}
                if markup:
                    payload["reply_markup"] = markup
                return self._api("sendPhoto", payload)
            except httpx.HTTPError:
                pass
        payload = {"text": caption, "parse_mode": "HTML", "disable_web_page_preview": False}
        if markup:
            payload["reply_markup"] = markup
        return self._api("sendMessage", payload)

    def send_changes(self, changes: Changes, source: str, mode: str) -> int:
        cards = _cards_for(changes, source, mode)
        for photo, caption, button in cards:
            self.send_card(photo, caption, button)
        return len(cards)
