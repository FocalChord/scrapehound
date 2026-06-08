"""Filter matching and change detection."""
from decimal import Decimal

from scrapehound.models import Product, Filter, parse_brand, parse_width
from scrapehound.diff import diff
from scrapehound.store import Store


def P(**kw) -> Product:
    base = dict(id="x", title="t", url="u", price=Decimal("100"))
    base.update(kw)
    return Product(**base)


def test_filter_brand_width_size():
    f = Filter(brand="New Balance", widths=["4E"], sizes=[10, 10.5],
               require_size_in_stock=True)
    ok = P(title="New Balance 880 (4E)",
           attrs={"brand": "New Balance", "width": "4E", "sizes_in_stock": [10.0]})
    assert f.matches(ok)
    assert not f.matches(P(title="Asics 4E",
                           attrs={"brand": "Asics", "width": "4E", "sizes_in_stock": [10.0]}))
    assert not f.matches(P(title="NB", attrs={"brand": "New Balance", "width": "2E",
                                              "sizes_in_stock": [10.0]}))
    assert not f.matches(P(title="NB", attrs={"brand": "New Balance", "width": "4E",
                                              "sizes_in_stock": [9.0]}))


def test_filter_exclude_terms():
    f = Filter(exclude_terms=["work boot"])
    assert not f.matches(P(title="NB Composite Work Boot"))
    assert f.matches(P(title="NB 880 running"))


def test_empty_filter_matches_all():
    assert Filter().matches(P(title="anything at all"))


def test_helpers():
    assert parse_width("Mens New Balance 880 (4E X-Wide)") == "4E"
    assert parse_brand("Mens New Balance Fresh Foam") == "New Balance"


def test_diff_new_removed_pricechange(tmp_path):
    store = Store("s", tmp_path)
    a = P(id="1", title="A", price=Decimal("100"), source="s")  # was 120 -> drop
    b = P(id="2", title="B", price=Decimal("50"), source="s")   # new
    gone = P(id="3", title="C", price=Decimal("70"), source="s")
    prev = {a.key: {**a.model_dump(mode="json"), "price": "120"},
            gone.key: gone.model_dump(mode="json")}
    ch = diff(prev, [a, b], store)
    assert [p.id for p in ch.new] == ["2"]
    assert [p.id for p in ch.removed] == ["3"]
    assert len(ch.price_changes) == 1 and ch.price_changes[0].dropped
