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
from .config import init_env, load_bots, load_comps, load_sources

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


def _cmd_init(argv) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound init")
    ap.add_argument("dir", nargs="?", default=".", help="project directory")
    args = ap.parse_args(argv)
    from . import scaffold
    root = scaffold.init_project(args.dir)
    print(f"✓ scaffolded a scrapehound project in {root}/")
    print("\nnext:")
    print("  uv sync")
    print("  scrapehound bot mybot --token <BOTFATHER_TOKEN>   # message the bot first")
    print("  scrapehound add <store-url> --bot mybot")
    print("  scrapehound preview <source>   &&   scrapehound --dry-run")
    return 0


def _cmd_add(argv) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound add")
    ap.add_argument("url", help="a store / listing URL")
    ap.add_argument("--name", help="source key (default: from the domain)")
    ap.add_argument("--bot", default="default", help="bot to route alerts to")
    args = ap.parse_args(argv)
    from . import scaffold
    try:
        name, typ = scaffold.add_source(args.url, args.name, args.bot)
    except FileNotFoundError:
        print("✗ no config/ here — run `scrapehound init` first")
        return 1
    except Exception as e:
        print(f"✗ {e}")
        return 1
    print(f"✓ added source '{name}' (type: {typ}, bot: {args.bot})")
    if typ == "browser":
        print("  → couldn't auto-detect the platform; fill in the CSS selectors "
              "(marked TODO) in config/sources.yaml")
    print(f"  then:  scrapehound preview {name}")
    return 0


def _cmd_bot(argv) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound bot")
    ap.add_argument("name", help="a name for this bot (used for routing)")
    ap.add_argument("--token", help="BotFather token (prompted if omitted)")
    ap.add_argument("--chat-id", help="override chat id (else auto-discovered)")
    args = ap.parse_args(argv)
    from . import scaffold
    token = args.token
    if not token:
        try:
            token = input(f"Bot token for '{args.name}' (from @BotFather): ").strip()
        except EOFError:
            print("✗ pass --token")
            return 1
    try:
        chat = scaffold.add_bot(args.name, token, args.chat_id)
    except FileNotFoundError:
        print("✗ no config/ here — run `scrapehound init` first")
        return 1
    if chat:
        print(f"✓ connected bot '{args.name}' (chat {chat}) — creds in .env + config/bots.yaml")
    else:
        print(f"⚠ added bot '{args.name}', but no chat found. Message the bot once, then "
              f"re-run:  scrapehound bot {args.name} --token <token>")
    print(f"  for CI, add {args.name.upper()}_BOT_TOKEN and {args.name.upper()}_CHAT_ID "
          "as repo secrets.")
    return 0


def _cmd_preview(argv) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound preview")
    ap.add_argument("source", help="source key to dry-extract")
    args = ap.parse_args(argv)
    sources, _ = _load()
    if args.source not in sources:
        print(f"✗ unknown source '{args.source}'; have: {list(sources)}")
        return 1
    s = sources[args.source]
    from .derive import derive_attrs
    opts = {**s.options(), "max_products": s.options().get("max_products", 25)}
    items = base.REGISTRY[s.type](opts).collect()
    for p in items:
        derive_attrs(p, s.derive)
    kept = [p for p in items if s.filter.matches(p)]
    print(f"extracted {len(items)} → {len(kept)} after filter\n")
    for p in (kept or items)[:10]:
        attrs = "  ".join(f"{k}={v}" for k, v in p.attrs.items())
        price = f"${p.price}" if p.price is not None else ""
        print(f"  {price:>9}  {p.title[:48]}   {attrs}")
    return 0


def _cmd_comps(argv) -> int:
    sub = argv[0] if argv else "stats"
    rest = argv[1:]
    if sub == "collect":
        return _comps_collect(rest)
    if sub == "stats":
        return _comps_stats(rest)
    print(f"unknown comps subcommand '{sub}'; use: collect | stats")
    return 2


def _comps_collect(argv) -> int:
    from . import comps
    ap = argparse.ArgumentParser(prog="scrapehound comps collect")
    ap.add_argument("--key", help="collect only this comps source")
    ap.add_argument("--config", default="config")
    ap.add_argument("--state", default="state")
    args = ap.parse_args(argv)
    init_env()
    sources = load_comps(f"{args.config}/sources.yaml")
    if not sources:
        print("no `comps:` sources configured in sources.yaml")
        return 1
    if args.key and args.key not in sources:
        print(f"✗ unknown comps source '{args.key}'; have: {list(sources)}")
        return 1
    for key, src in sources.items():
        if args.key and key != args.key:
            continue
        try:
            added, total = comps.collect(key, src, args.state)
            print(f"  {key:22} +{added} new  (store: {total})")
        except Exception as e:  # noqa: BLE001
            log.warning("[comps:%s] ERROR: %s", key, e)
    return 0


def _comps_stats(argv) -> int:
    from . import comps
    ap = argparse.ArgumentParser(prog="scrapehound comps stats")
    ap.add_argument("key", help="comps source key")
    ap.add_argument("--window", type=int, help="single window in days (else 30/90/365)")
    ap.add_argument("--currency", help="restrict to a currency (default: most common)")
    ap.add_argument("--condition", help="restrict to a condition (e.g. 'Pre-owned')")
    ap.add_argument("--state", default="state")
    args = ap.parse_args(argv)
    windows = (args.window,) if args.window else (30, 90, 365)
    s = comps.stats(args.key, args.state, windows=windows,
                    currency=args.currency, condition=args.condition)
    if not s["total"]:
        print(f"no comps stored for '{args.key}' yet — run: scrapehound comps collect")
        return 1
    span = f"  ·  {s['span'][0]} → {s['span'][1]}" if s.get("span") else ""
    cond = f"  ·  {s['condition']}" if s.get("condition") else ""
    print(f"\n{args.key}  ({s['currency']})  ·  {s['total']} comps stored{span}{cond}")
    print("market value = realized (auction + Buy It Now); Best-Offer "
          "asking prices excluded\n")
    cols = ["n", "min", "p50", "p90", "p95", "max"]
    money = lambda v: ("$" + format(v, ",.0f")) if v is not None else "—"  # noqa: E731
    head = "  ".join(f"{c:>8}" for c in cols)
    print(f"  {'window':>7}  {head}  {'auction p50':>13}  {'BO excl':>8}")
    print(f"  {'-'*7}  " + "  ".join("-" * 8 for _ in cols) + f"  {'-'*13}  {'-'*8}")
    for w in windows:
        seg = s["windows"][w]
        rz, au = seg["realized"], seg["auction"]
        label = f"{w}d"
        if not rz.get("n"):
            print(f"  {label:>7}  {'0':>8}  (no realized sales in window)")
            continue
        cells = [f"{rz['n']:>8}" if c == "n" else f"{money(rz.get(c)):>8}" for c in cols]
        au_p50 = f"{money(au.get('p50'))} (n={au['n']})" if au.get("n") else "—"
        print(f"  {label:>7}  " + "  ".join(cells)
              + f"  {au_p50:>13}  {seg['counts']['offer']:>8}")
    print()
    return 0


def _cmd_dashboard(argv) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound dashboard")
    ap.add_argument("--out", default="docs", help="output directory for the static site")
    args = ap.parse_args(argv)
    from .dashboard import build_site
    out = build_site(args.out)
    print(f"✓ built static dashboard in {out}/  (open {out}/index.html or serve it)")
    return 0


_COMMANDS = {
    "run": _cmd_run, "list": _cmd_list, "check": _cmd_check, "test-bot": _cmd_test_bot,
    "init": _cmd_init, "add": _cmd_add, "bot": _cmd_bot, "preview": _cmd_preview,
    "comps": _cmd_comps, "dashboard": _cmd_dashboard,
}


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
