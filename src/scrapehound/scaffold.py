"""Onboarding scaffolds: create a project, add a bot, add a source by URL.

These let a new user go from nothing to a running watcher without learning the
YAML schema by hand.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .web import http_client

# ---------------------------------------------------------------- init templates
_SOURCES_YAML = """\
# Sources to watch. Add one with:  scrapehound add <url> --bot <bot>
#
# Each source: type (adapter) + bot (routing) + notify (changes|price_drop)
#   + optional derive (compute attrs) + optional filter (rules; omit = keep all).
sources: {}
"""

_BOTS_YAML = """\
# Telegram bots. Connect one with:  scrapehound bot <name> --token <token>
bots: {}
"""

_ENV_EXAMPLE = "# Bot tokens/chat ids are added here by `scrapehound bot <name>`.\n"

_GITIGNORE = ".venv/\n__pycache__/\n*.pyc\n.env\n.pytest_cache/\n"

_PYPROJECT = """\
[project]
name = "%(name)s"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["scrapehound @ git+https://github.com/FocalChord/scrapehound"]
"""

_WORKFLOW = """\
name: scrape
on:
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch: {}
permissions:
  contents: write
concurrency:
  group: scrape
  cancel-in-progress: false
jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run patchright install --with-deps chromium   # for `browser` sources
      - name: Run
        env:                                                  # add a secret per bot
          # EXAMPLE_BOT_TOKEN: ${{ secrets.EXAMPLE_BOT_TOKEN }}
          # EXAMPLE_CHAT_ID: ${{ secrets.EXAMPLE_CHAT_ID }}
          DUMMY: ""
        run: xvfb-run -a uv run scrapehound
      - name: Commit state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add state/
          git diff --cached --quiet && exit 0
          git commit -m "update state [skip ci]"
          for i in 1 2 3 4 5; do
            git pull --no-rebase -X ours -q origin main || true
            git push && exit 0; sleep $((RANDOM % 6 + 3))
          done
"""

_README = """\
# %(name)s

A [scrapehound](https://github.com/FocalChord/scrapehound) watcher.

## Get started

```bash
uv sync
scrapehound bot mybot --token <BOTFATHER_TOKEN>   # message the bot first
scrapehound add https://somestore.com --bot mybot # auto-detects the platform
scrapehound preview somestore                     # see what it extracts
scrapehound check                                 # validate everything
scrapehound --dry-run                             # what it would alert on
```

Push to GitHub and add each bot's `*_BOT_TOKEN` / `*_CHAT_ID` as Actions secrets;
the workflow runs on a schedule and commits state back.
"""


def init_project(target: str) -> Path:
    root = Path(target)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    files = {
        "config/sources.yaml": _SOURCES_YAML,
        "config/bots.yaml": _BOTS_YAML,
        ".env.example": _ENV_EXAMPLE,
        ".gitignore": _GITIGNORE,
        "pyproject.toml": _PYPROJECT % {"name": root.name or "watcher"},
        ".github/workflows/scrape.yml": _WORKFLOW,
        "README.md": _README % {"name": root.name or "watcher"},
        "state/.gitkeep": "",
    }
    for rel, content in files.items():
        p = root / rel
        if not p.exists():
            p.write_text(content)
    return root


# ---------------------------------------------------------------- platform detect
def detect_platform(url: str) -> tuple[str, dict]:
    """Return (adapter_type, extra_config) for a store URL. Falls back to browser."""
    base = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
    try:
        with http_client({"Accept": "application/json"}) as c:
            r = c.get(f"{base}/products.json?limit=1")
            if r.status_code == 200 and isinstance(r.json().get("products"), list):
                return "shopify", {"base_url": base}
    except Exception:
        pass
    try:
        with http_client() as c:
            html = c.get(base).text.lower()
        if "cdn.shopify.com" in html or "shopify" in html:
            return "shopify", {"base_url": base}
    except Exception:
        pass
    return "browser", {"url": url}


def _source_block(name: str, bot: str, typ: str, extra: dict) -> str:
    lines = [f"\n  {name}:", f"    type: {typ}", f"    bot: {bot}", "    notify: changes"]
    for k, v in extra.items():
        lines.append(f'    {k}: "{v}"')
    if typ == "shopify":
        lines += [
            "    # prefilter: [[brand], [keyword]]   # cheap fetch-time pruning",
            "    # filter:                           # omit to keep everything",
            "    #   - {field: title, op: contains_any, value: [your, keywords]}",
        ]
    else:  # browser — needs selectors filled in
        lines += [
            '    wait_for: ".PRODUCT"            # TODO selector shown when items load',
            "    selectors:",
            '      container: ".PRODUCT"         # TODO',
            '      title: ".TITLE"               # TODO',
            "      price: \"meta[itemprop='price']@content\"   # TODO (text or @attr)",
            '      url: "a@href"                 # TODO',
            '      image: "img@src"              # TODO',
        ]
    return "\n".join(lines) + "\n"


def add_source(url: str, name: str | None, bot: str, config_dir: str = "config") -> tuple[str, str]:
    typ, extra = detect_platform(url)
    name = name or (urlsplit(url).netloc.split(".")[0] or "source").replace("-", "_")
    path = Path(config_dir) / "sources.yaml"
    text = path.read_text()
    if f"\n  {name}:" in text:
        raise ValueError(f"source '{name}' already exists in {path}")
    # ensure a non-empty `sources:` mapping
    text = text.replace("sources: {}", "sources:")
    path.write_text(text.rstrip("\n") + "\n" + _source_block(name, bot, typ, extra))
    return name, typ


def add_bot(name: str, token: str, chat_id: str | None, config_dir: str = "config",
            env_path: str = ".env") -> str | None:
    """Append a bot to bots.yaml and write its creds to .env. Returns chat_id."""
    env = f"{name.upper()}_BOT_TOKEN", f"{name.upper()}_CHAT_ID"
    if chat_id is None:
        chat_id = _discover_chat_id(token)
    bots = Path(config_dir) / "bots.yaml"
    text = bots.read_text().replace("bots: {}", "bots:")
    if f"\n  {name}:" not in text:
        text = text.rstrip("\n") + f"\n  {name}:\n    token_env: {env[0]}\n    chat_env: {env[1]}\n"
        bots.write_text(text)
    envf = Path(env_path)
    lines = envf.read_text().splitlines() if envf.exists() else []
    lines = [l for l in lines if not l.startswith((env[0] + "=", env[1] + "="))]
    lines += [f"{env[0]}={token}", f"{env[1]}={chat_id or ''}"]
    envf.write_text("\n".join(lines) + "\n")
    return chat_id


def _discover_chat_id(token: str) -> str | None:
    try:
        r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    except Exception:
        return None
    for upd in reversed(r.get("result", [])):
        chat = (upd.get("message") or upd.get("channel_post") or {}).get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return None
