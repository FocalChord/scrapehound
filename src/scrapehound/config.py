"""Typed configuration: sources + bots from YAML, secrets from env/.env."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from .models import Filter

CONFIG_DIR = Path("config")


class SourceConfig(BaseModel):
    """One scrape source. Adapter-specific keys (url, base_url, selectors, ...)
    are allowed and passed through to the adapter via options()."""
    model_config = ConfigDict(extra="allow")

    type: str
    bot: str = "default"
    enabled: bool = True
    notify: str = "changes"          # "changes" | "price_drop"
    filter: Optional[Filter] = None

    def options(self) -> dict:
        return self.model_dump(exclude={"bot", "enabled", "notify", "filter"})


class BotConfig(BaseModel):
    """A named Telegram bot; token/chat are read from these env vars."""
    token_env: str
    chat_env: str

    def creds(self) -> tuple[Optional[str], Optional[str]]:
        return os.environ.get(self.token_env), os.environ.get(self.chat_env)


def init_env() -> None:
    """Load .env into the environment (idempotent)."""
    load_dotenv()


def load_sources(path: Path | str = CONFIG_DIR / "sources.yaml") -> dict[str, SourceConfig]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {k: SourceConfig(**v) for k, v in (data.get("sources") or data).items()}


def load_bots(path: Path | str = CONFIG_DIR / "bots.yaml") -> dict[str, BotConfig]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {k: BotConfig(**v) for k, v in (data.get("bots") or data).items()}
