"""Telegram notification: named bots + HTML cards.

A `TelegramBot` is a token+chat pair resolved from a BotConfig. Formatting is
mode-aware: `changes` sends new/removed/price-change cards (digidirect style),
`price_drop` sends only drops + newly-on-sale items (shoe style). The same card
builders feed both real sends and dry-run previews.
"""
from __future__ import annotations

import html

import httpx

from ..config import BotConfig
from ..diff import Changes, PriceChange
from ..models import Product


def _e(s) -> str:
    return html.escape(str(s))


def _money(v) -> str:
    return f"${v:,.2f}"


def _link(text: str, url: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{_e(text)}</a>'


def _button(p: Product):
    return {"text": "View ↗", "url": p.url} if p.url else None


def _price_line(p: Product) -> str:
    s = f"<b>{_money(p.price)}</b>"
    if p.on_sale:
        s += f"  <s>{_money(p.was_price)}</s> -{p.percent_off}%"
    return s


# Each builder returns (photo_url, caption_html, button).
def card_new(p: Product, source: str):
    return p.image, (f"\U0001f195 <b>{_e(p.title)}</b>\n{_price_line(p)}\n"
                     f"\U0001f3f7️ <i>{_e(source)}</i>"), _button(p)


def card_removed(p: Product, source: str):
    return None, (f"❌ <b>{_e(p.title)}</b>\nNo longer available\n"
                  f"\U0001f3f7️ <i>{_e(source)}</i>"), None


def card_price_change(pc: PriceChange, source: str):
    p = pc.product
    arrow = "\U0001f4c9" if pc.dropped else "\U0001f4c8"
    cap = f"{arrow} <b>{_e(p.title)}</b>\n{_money(pc.old_price)} → <b>{_money(pc.new_price)}</b>"
    if pc.dropped and pc.all_time_low:
        cap += "  \U0001f525 all-time low"
    cap += f"\n\U0001f3f7️ <i>{_e(source)}</i>"
    return p.image, cap, _button(p)


def _cards_for(changes: Changes, source: str, mode: str):
    cards = []
    if mode == "price_drop":
        cards += [card_price_change(pc, source) for pc in changes.price_changes if pc.dropped]
        cards += [card_new(p, source) for p in changes.new if p.on_sale]
    else:  # "changes"
        cards += [card_new(p, source) for p in changes.new]
        cards += [card_removed(p, source) for p in changes.removed]
        cards += [card_price_change(pc, source) for pc in changes.price_changes]
    return cards


def preview_changes(changes: Changes, source: str, mode: str) -> str:
    cards = _cards_for(changes, source, mode)
    return "\n\n".join(c[1] for c in cards) or "(nothing to send)"


def summary_text(products: list[Product], source: str, limit: int = 40) -> str:
    ps = sorted(products, key=lambda x: x.price)
    lines = [f"\U0001f4cb <b>{_e(source)}</b> — {len(ps)} item(s)", ""]
    for p in ps[:limit]:
        lines.append(f"{_price_line(p)}  {_link(p.title, p.url)}")
    if len(ps) > limit:
        lines.append(f"… +{len(ps) - limit} more")
    return "\n".join(lines)


class TelegramBot:
    def __init__(self, name: str, token: str | None, chat_id: str | None):
        self.name = name
        self.token = token
        self.chat_id = chat_id

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
