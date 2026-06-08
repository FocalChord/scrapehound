"""Generic filter rules, declarative derive, and change detection."""
from decimal import Decimal

from scrapehound.models import Product, Variant
from scrapehound.filtering import Filter, Rule
from scrapehound.derive import derive_attrs
from scrapehound.diff import diff
from scrapehound.store import Store


def P(**kw) -> Product:
    base = dict(id="x", title="t", url="u", price=Decimal("100"))
    base.update(kw)
    return Product(**base)


def test_filter_rules():
    f = Filter(rules=[
        Rule(attr="brand", op="eq", value="New Balance"),
        Rule(field="title", op="not_contains", value=["work boot", "women"]),
        Rule(attr="width", op="in", value=["4E"]),
        Rule(attr="sizes_in_stock", op="intersects", value=[10, 10.5]),
    ])
    base = {"brand": "New Balance", "width": "4E", "sizes_in_stock": [10.0]}
    assert f.matches(P(title="NB 880 4E", attrs=base))
    assert not f.matches(P(title="NB Work Boot", attrs=base))
    assert not f.matches(P(title="x", attrs={**base, "brand": "Asics"}))
    assert not f.matches(P(title="x", attrs={**base, "width": "2E"}))
    assert not f.matches(P(title="x", attrs={**base, "sizes_in_stock": [9.0]}))


def test_filter_price_and_empty():
    assert Filter(rules=[Rule(field="price", op="lte", value=150)]).matches(P(price=Decimal("120")))
    assert not Filter(rules=[Rule(field="price", op="lte", value=150)]).matches(P(price=Decimal("200")))
    assert Filter().matches(P())          # empty matches everything (e.g. leica)


def test_derive_from_title_and_variants():
    p = P(title="Mens New Balance Fresh Foam X 880 V15 (4E Extra Wide)",
          variants=[Variant(options={"Size": "10"}, available=True),
                    Variant(options={"Size": "11"}, available=False),
                    Variant(options={"Size": "10.5"}, available=True)])
    derive_attrs(p, {
        "brand": {"from": "title", "match": ["New Balance", "Asics"]},
        "width": {"from": "title", "regex": r"\b([2468]E)\b", "upper": True,
                  "fallbacks": {"extra wide": "4E"}},
        "sizes_in_stock": {"from_variants": "Size"},
    })
    assert p.attrs["brand"] == "New Balance"
    assert p.attrs["width"] == "4E"
    assert p.attrs["sizes_in_stock"] == [10.0, 10.5]   # only available, numeric, sorted


def test_derive_const():
    p = P()
    derive_attrs(p, {"width": {"const": "4E"}, "sizes_in_stock": {"const": [10, 10.5]}})
    assert p.attrs["width"] == "4E" and p.attrs["sizes_in_stock"] == [10, 10.5]


def test_diff_new_removed_pricechange(tmp_path):
    store = Store("s", tmp_path)
    a = P(id="1", title="A", price=Decimal("100"), source="s")
    b = P(id="2", title="B", price=Decimal("50"), source="s")
    gone = P(id="3", title="C", price=Decimal("70"), source="s")
    prev = {a.key: {**a.model_dump(mode="json"), "price": "120"},
            gone.key: gone.model_dump(mode="json")}
    ch = diff(prev, [a, b], store)
    assert [p.id for p in ch.new] == ["2"]
    assert [p.id for p in ch.removed] == ["3"]
    assert len(ch.price_changes) == 1 and ch.price_changes[0].dropped
