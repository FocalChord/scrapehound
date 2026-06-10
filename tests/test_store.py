"""Store: change-only history, stable snapshots, lossless compaction."""
import json
from decimal import Decimal

from scrapehound.models import Product
from scrapehound.store import Store


def P(id, price):
    return Product(source="s", id=id, title="t", price=Decimal(str(price)))


def test_history_appends_only_on_price_change(tmp_path):
    st = Store("s", tmp_path)
    st.save([P("a", 100)], "t1")     # baseline
    st.save([P("a", 100)], "t2")     # unchanged -> no row
    st.save([P("a", 90)], "t3")      # price moved -> one row
    rows = [l for l in st.history_path.read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    assert st.all_time_low("s:a") == Decimal("90.00")


def test_snapshot_byte_stable_on_noop(tmp_path):
    st = Store("s", tmp_path)
    st.save([P("a", 100)], "2026-01-01T00:00:00+00:00")
    snap1 = st.state_path.read_text()
    st.save([P("a", 100)], "2026-02-02T09:09:09+00:00")   # same data, later ts
    assert st.state_path.read_text() == snap1             # no git churn


def test_compact_collapses_runs_losslessly(tmp_path):
    st = Store("s", tmp_path)
    st.history_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"key": "s:a", "price": "100", "scraped_at": "t1"},
        {"key": "s:a", "price": "100", "scraped_at": "t2"},   # dup
        {"key": "s:a", "price": "90", "scraped_at": "t3"},
        {"key": "s:a", "price": "90", "scraped_at": "t4"},    # dup
        {"key": "s:a", "price": "95", "scraped_at": "t5"},
    ]
    st.history_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    low_before = st.low_point("s:a")
    assert st.compact_history() == 2                          # two dups removed
    kept = [json.loads(l) for l in st.history_path.read_text().splitlines() if l.strip()]
    assert [r["price"] for r in kept] == ["100", "90", "95"]  # transitions kept, dates intact
    assert st.low_point("s:a") == low_before                  # all-time-low unchanged
