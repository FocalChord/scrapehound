"""Typed configuration: sources + bots from YAML, secrets from env/.env."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, field_validator

from .filtering import Filter

CONFIG_DIR = Path("config")


class SourceConfig(BaseModel):
    """One scrape source. Adapter-specific keys (url, base_url, selectors,
    search, prefilter, ...) are allowed and passed to the adapter via options()."""
    model_config = ConfigDict(extra="allow")

    type: str
    bot: str = "default"
    enabled: bool = True
    notify: str = "changes"          # "changes" | "price_drop"
    watch: list[str] = ["price"]     # fields/attrs to detect changes in
    derive: dict = {}                # attr name -> derivation spec
    filter: Filter = Filter()        # list of rules in YAML

    @field_validator("filter", mode="before")
    @classmethod
    def _coerce_filter(cls, v):
        return {"rules": v} if isinstance(v, list) else v

    def options(self) -> dict:
        return self.model_dump(
            exclude={"bot", "enabled", "notify", "watch", "filter", "derive"})


class BotConfig(BaseModel):
    token_env: str
    chat_env: str

    def creds(self) -> tuple[Optional[str], Optional[str]]:
        return os.environ.get(self.token_env), os.environ.get(self.chat_env)


def init_env() -> None:
    load_dotenv(".env")          # the project's .env (cwd), not the package dir


def _section(data: dict, key: str) -> dict:
    # support both {key: {...}} and a bare top-level mapping; tolerate empty.
    return (data[key] if key in data else data) or {}


def load_sources(path: Path | str = CONFIG_DIR / "sources.yaml") -> dict[str, SourceConfig]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {k: SourceConfig(**v) for k, v in _section(data, "sources").items()}


def load_bots(path: Path | str = CONFIG_DIR / "bots.yaml") -> dict[str, BotConfig]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {k: BotConfig(**v) for k, v in _section(data, "bots").items()}
