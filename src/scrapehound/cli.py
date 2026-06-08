"""CLI entrypoint.

    scrapehound                     # all sources: scrape, alert, persist
    scrapehound --source rebel      # just one source
    scrapehound --dry-run           # print what would be sent; don't persist
    scrapehound --summary           # send the current snapshot per source
"""
from __future__ import annotations

import argparse
import logging

from . import pipeline
from .config import init_env, load_bots, load_sources


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scrapehound",
                                 description="Generic multi-source scraper with Telegram alerts")
    ap.add_argument("--source", help="run only this source (by key)")
    ap.add_argument("--bot", help="run only sources routed to this bot")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent; don't persist state")
    ap.add_argument("--summary", action="store_true",
                    help="send the current snapshot per source")
    ap.add_argument("--state", default="state", help="state directory")
    ap.add_argument("--config", default="config", help="config directory")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    init_env()
    sources = load_sources(f"{args.config}/sources.yaml")
    bots = load_bots(f"{args.config}/bots.yaml")
    pipeline.run(sources, bots, only=args.source, only_bot=args.bot,
                 dry_run=args.dry_run, summary=args.summary, state_dir=args.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
