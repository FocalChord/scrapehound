"""Orchestrator: for each source, scrape -> diff -> notify the routed bot.

Per source it keeps its own state file and routes alerts to its configured bot.
A source that suddenly returns nothing (but had products before) is treated as a
likely failure and skipped, so a transient block can't wipe state or fire a wave
of false "removed" alerts.
"""
from __future__ import annotations

import datetime as dt
import logging

from . import adapters  # noqa: F401  (registers adapters)
from .adapters import base
from .config import BotConfig, SourceConfig
from .derive import derive_attrs
from .diff import diff
from .notify import TelegramBot, preview_changes, summary_text
from .store import Store

log = logging.getLogger("scrapehound")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _bot_for(src: SourceConfig, bots: dict[str, BotConfig]) -> TelegramBot | None:
    cfg = bots.get(src.bot)
    return TelegramBot.from_config(src.bot, cfg) if cfg else None


def run(sources: dict[str, SourceConfig], bots: dict[str, BotConfig], *,
        only: str | None = None, only_bot: str | None = None, dry_run: bool = False,
        summary: bool = False, state_dir: str = "state") -> None:
    for key, src in sources.items():
        if not src.enabled or (only and key != only) or (only_bot and src.bot != only_bot):
            continue
        cls = base.REGISTRY.get(src.type)
        if cls is None:
            log.warning("unknown adapter type %r for %s; skipping", src.type, key)
            continue
        try:
            products = cls(src.options()).collect()       # extract (platform)
        except Exception as e:
            log.warning("[%s] ERROR: %s", key, e)
            continue

        ts = now_iso()
        for p in products:
            p.source, p.scraped_at = key, ts
            derive_attrs(p, src.derive)                   # derive (domain config)
        products = [p for p in products if src.filter.matches(p)]   # select (rules)
        log.info("[%s] %d product(s)", key, len(products))

        store = Store(key, state_dir)
        previous = store.load()
        bot = _bot_for(src, bots)

        if summary:
            _emit(bot, summary_text(products, key), dry_run)
        elif not previous:
            log.info("[%s] first run, establishing baseline", key)
        elif not products:
            log.warning("[%s] empty scrape but %d known previously; skipping",
                        key, len(previous))
            continue
        else:
            changes = diff(previous, products, store, watch=tuple(src.watch))
            if changes.any():
                log.info("[%s] %s", key, changes.summary())
                if dry_run or not (bot and bot.has_creds()):
                    _emit(None, f"--- {src.bot} / {src.notify} ---\n"
                          + preview_changes(changes, src.bot, src.notify), True)
                else:
                    n = bot.send_changes(changes, src.bot, src.notify)
                    log.info("[telegram:%s] sent %d card(s)", src.bot, n)
            else:
                log.info("[%s] no changes", key)

        if not dry_run:
            store.save(products, ts)


def _emit(bot: TelegramBot | None, text: str, dry_run: bool) -> None:
    if dry_run or not (bot and bot.has_creds()):
        print("\n" + text)
    else:
        bot.send(text)
