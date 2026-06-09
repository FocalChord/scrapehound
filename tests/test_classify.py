"""Semantic matcher: parsing, ordering, and fail-safe behaviour (Gemini mocked)."""
import json

import httpx

from scrapehound import classify


def _fake_response(decisions, *, start=1):
    """decisions: list of bools -> the {n, keep} object array Gemini returns."""
    objs = [{"n": start + i, "keep": d} for i, d in enumerate(decisions)]
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(objs)}]}}]}
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "https://x"))


def test_match_titles_keep_drop(monkeypatch):
    titles = ["Leica M6 Classic", "Leica M3 Double Stroke", "Leica M6 TTL 0.85"]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response([True, False, True]))
    assert classify.match_titles("Leica M6 body", titles, api_key="x") == [True, False, True]


def test_no_api_key_keeps_all(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    titles = ["a", "b", "c"]
    # must not call the network at all
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    assert classify.match_titles("spec", titles) == [True, True, True]


def test_api_error_fails_open(monkeypatch):
    # non-retryable error -> immediate fail-open (no long backoff loop)
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(httpx, "post", boom)
    assert classify.match_titles("spec", ["a", "b"], api_key="x") == [True, True]


def test_missing_numbers_default_keep(monkeypatch):
    # model returns a verdict only for listing 2 -> 1 and 3 default to keep
    objs = [{"n": 2, "keep": False}]
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(objs)}]}}]}
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: httpx.Response(200, json=payload, request=httpx.Request("POST", "https://x")))
    assert classify.match_titles("spec", ["a", "b", "c"], api_key="x") == [True, False, True]


def test_semantic_keep_filters(monkeypatch):
    items = [{"t": "Leica M6"}, {"t": "Leica M5"}, {"t": "Leica M6 TTL"}]
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _fake_response([True, False, True]))
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    kept = classify.semantic_keep(items, "Leica M6", key=lambda x: x["t"])
    assert kept == [{"t": "Leica M6"}, {"t": "Leica M6 TTL"}]
