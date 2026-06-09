"""Semantic listing matcher — "does this listing match what I asked for?"

eBay's search is fuzzy (a query for "leica m6" returns M2/M3/M5; "pokemon
heartgold cib" returns cartridge-only). Hand-written token filters are brittle.
Instead, a comps source can carry a plain-English `match:` spec, and each
candidate's title is judged keep/drop by an LLM — no token lists to maintain.

Uses Google Gemini Flash (generous free tier) via its REST API; the only
dependency is httpx (already vendored). Fail-safe by design: if GEMINI_API_KEY
is unset or the call errors, every candidate is kept (the declarative `filter`
still applies), so collection never breaks on a classifier hiccup.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

log = logging.getLogger("scrapehound")

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_DEFAULT_MODEL = "gemini-2.5-flash-lite"
_CHUNK = 50  # titles per request

_SYSTEM = (
    "You are a precise e-commerce listing classifier. You are given a TARGET "
    "description and a numbered list of marketplace listing titles. For EACH "
    "numbered title decide whether the listing genuinely matches the TARGET. Be "
    "strict: reject different models/variants, accessories, parts, empties, or "
    "wrong condition even if keywords overlap. Return a JSON array with one "
    "object per listing: {\"n\": the listing number, \"keep\": true if it "
    "matches the TARGET else false}. Include every listing number exactly once."
)
_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {"n": {"type": "INTEGER"}, "keep": {"type": "BOOLEAN"}},
        "required": ["n", "keep"],
    },
}


def match_titles(spec: str, titles: list[str], *, model: str | None = None,
                 api_key: str | None = None) -> list[bool]:
    """Return a keep/drop bool per title. Falls back to all-True on any problem."""
    keep = [True] * len(titles)
    if not titles:
        return keep
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.info("[match] GEMINI_API_KEY not set; skipping semantic match")
        return keep
    model = model or os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)

    out: list[bool] = []
    for start in range(0, len(titles), _CHUNK):
        chunk = titles[start:start + _CHUNK]
        verdict = _classify_chunk(spec, chunk, model, api_key)  # {1-based n: keep}
        if verdict is None:
            out.extend([True] * len(chunk))      # fail open for this chunk
        else:
            # align by listing number; any missing number defaults to keep
            out.extend(verdict.get(i + 1, True) for i in range(len(chunk)))
    return out


def _classify_chunk(spec: str, titles: list[str], model: str,
                    api_key: str) -> dict[int, bool] | None:
    listing_block = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    body = {
        "system_instruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"parts": [{"text": f"TARGET: {spec}\n\nLISTINGS:\n{listing_block}"}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
        },
    }
    url = _ENDPOINT.format(model=model)
    try:
        r = httpx.post(url, json=body, headers={"x-goog-api-key": api_key},
                       timeout=60)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        decisions = json.loads(text)
        if not isinstance(decisions, list):
            return None
        return {int(d["n"]): bool(d["keep"]) for d in decisions
                if isinstance(d, dict) and "n" in d and "keep" in d}
    except Exception as e:  # noqa: BLE001  (fail open — never break collection)
        log.warning("[match] Gemini classify failed (%s); keeping chunk", e)
        return None


def semantic_keep(items: list, spec: str, *, key=lambda x: x) -> list:
    """Filter `items` by an LLM match against `spec`. `key` maps item -> title."""
    if not spec or not items:
        return items
    titles = [str(key(it) or "") for it in items]
    decisions = match_titles(spec, titles)
    kept = [it for it, ok in zip(items, decisions) if ok]
    if len(kept) != len(items):
        log.info("[match] %d/%d kept against spec", len(kept), len(items))
    return kept
