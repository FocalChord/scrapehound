"""CLI entrypoint.

    scrapehound                      # all sources: scrape, alert, persist
    scrapehound --bot shoes          # only sources routed to a bot
    scrapehound --source rebel       # only one source
    scrapehound --dry-run            # print what would be sent; don't persist
    scrapehound --summary            # send the current snapshot per source

    scrapehound list                 # show configured sources + bots
    scrapehound check                # validate config + bot creds (CI-friendly)
    scrapehound test-bot shoes       # send a test message to a bot
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import pipeline
from .adapters import base
from .config import init_env, load_bots, load_sources

log = logging.getLogger("scrapehound")


def _load(config_dir: str = "config"):
    init_env()
    try:
        return (load_sources(f"{config_dir}/sources.yaml"),
                load_bots(f"{config_dir}/bots.yaml"))
    except Exception as e:
        print(f"✗ config error: {e}")
        raise SystemExit(2)


def _cmd_run(argv) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound")
    ap.add_argument("--source", help="run only this source (by key)")
    ap.add_argument("--bot", help="run only sources routed to this bot")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent; don't persist state")
    ap.add_argument("--summary", action="store_true",
                    help="send the current snapshot per source")
    ap.add_argument("--state", default="state")
    ap.add_argument("--config", default="config")
    args = ap.parse_args(argv)
    sources, bots = _load(args.config)
    pipeline.run(sources, bots, only=args.source, only_bot=args.bot,
                 dry_run=args.dry_run, summary=args.summary, state_dir=args.state)
    return 0


def _cmd_list(argv) -> int:
    sources, bots = _load()
    print("BOTS")
    for name, b in bots.items():
        t, c = b.creds()
        print(f"  {name:10} {'✓ creds' if (t and c) else '✗ no creds'}"
              f"   ({b.token_env} / {b.chat_env})")
    print("\nSOURCES")
    print(f"  {'key':22} {'type':16} {'bot':7} {'notify':11} on")
    for key, s in sources.items():
        print(f"  {key:22} {s.type:16} {s.bot:7} {s.notify:11} {'y' if s.enabled else 'n'}")
    return 0


def _cmd_check(argv) -> int:
    sources, bots = _load()
    errors, warns = [], []
    for name, b in bots.items():
        t, c = b.creds()
        if not (t and c):
            warns.append(f"bot '{name}': missing {b.token_env if not t else b.chat_env}")
    for key, s in sources.items():
        cls = base.REGISTRY.get(s.type)
        if cls is None:
            errors.append(f"source '{key}': unknown type '{s.type}' "
                          f"(known: {sorted(base.REGISTRY)})")
            continue
        opts = s.options()
        for req in getattr(cls, "required", []):
            if not opts.get(req):
                errors.append(f"source '{key}': missing required '{req}' for type '{s.type}'")
        if s.bot not in bots:
            errors.append(f"source '{key}': bot '{s.bot}' not defined in bots.yaml")
    for w in warns:
        print(f"  ! {w}")
    for e in errors:
        print(f"  ✗ {e}")
    if errors:
        print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
        return 1
    print(f"✓ ok — {len(sources)} sources, {len(bots)} bots"
          + (f", {len(warns)} warning(s)" if warns else ""))
    return 0


def _cmd_test_bot(argv) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound test-bot")
    ap.add_argument("bot", help="bot name from bots.yaml")
    args = ap.parse_args(argv)
    _, bots = _load()
    if args.bot not in bots:
        print(f"✗ unknown bot '{args.bot}'; defined: {list(bots)}")
        return 1
    from .notify import TelegramBot
    bot = TelegramBot.from_config(args.bot, bots[args.bot])
    if not bot.has_creds():
        b = bots[args.bot]
        print(f"✗ bot '{args.bot}' has no creds (set {b.token_env} / {b.chat_env})")
        return 1
    bot.send(f"✅ <b>scrapehound</b> test → <b>{args.bot}</b> bot")
    print(f"✓ sent a test message to '{args.bot}'")
    return 0


_COMMANDS = {"run": _cmd_run, "list": _cmd_list, "check": _cmd_check, "test-bot": _cmd_test_bot}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if (argv and not argv[0].startswith("-")) else "run"
    rest = argv if cmd == "run" else argv[1:]
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    handler = _COMMANDS.get(cmd)
    if handler is None:
        print(f"unknown command '{cmd}'; commands: {list(_COMMANDS)}")
        return 2
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main())
