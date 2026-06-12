"""Pipeline branch logic: a previously-empty source must still alert on its
first real item (regression: empty `{}` baseline was mistaken for first run)."""
from decimal import Decimal

from scrapehound import pipeline
from scrapehound.adapters import base
from scrapehound.config import SourceConfig
from scrapehound.models import Product

_OUT: list[Product] = []


@base.register("faketest")
class _FakeAdapter(base.Adapter):
    def fetch_raw(self):
        return None

    def parse(self, raw):
        return list(_OUT)


def _run(tmp_path, capsys):
    # no bot configured -> pipeline prints previews instead of sending, and
    # (dry_run=False) persists state so the second run sees the first's baseline.
    sources = {"fk": SourceConfig(type="faketest", bot="none", notify="changes")}
    pipeline.run(sources, {}, dry_run=False, state_dir=str(tmp_path))
    return capsys.readouterr().out


def test_empty_baseline_then_new_item_alerts(tmp_path, capsys):
    store_dir = tmp_path
    # 1) truly first run, source is empty (everything filtered out) -> baseline, no alert
    _OUT.clear()
    out = _run(store_dir, capsys)
    assert "PRICE DROP" not in out and "new" not in out.lower()
    assert (store_dir / "fk.json").exists()        # file written even when empty

    # 2) a real item appears -> must alert (it's new), not silently re-baseline
    _OUT[:] = [Product(source="fk", id="A", title="Apple Pencil Pro",
                       url="u", price=Decimal("189.00"))]
    out = _run(store_dir, capsys)
    assert "Apple Pencil Pro" in out                # the previously-swallowed alert
