"""HTTP adapters: parse fixtures into generic Products + variants, then derive."""
import json
from decimal import Decimal
from pathlib import Path

from scrapehound.adapters.shopify import ShopifyAdapter
from scrapehound.adapters.jsonld import JsonLdAdapter
from scrapehound.adapters.magento_graphql import MagentoGraphQLAdapter
from scrapehound.derive import derive_attrs

FX = Path(__file__).parent / "fixtures"
DERIVE = {
    "brand": {"from": "title", "match": ["New Balance"]},
    "width": {"from": "title", "regex": r"\b([2468]E)\b", "upper": True,
              "fallbacks": {"extra wide": "4E", "x-wide": "4E"}},
    "sizes_in_stock": {"from_variants": "Size"},
}


def test_shopify_parse_variants_then_derive():
    raw = json.loads((FX / "shopify_trc_880.json").read_text())
    p = ShopifyAdapter({"base_url": "https://shop.therunningcompany.com.au"}).parse(raw)[0]
    assert p.price == Decimal("230.00") and p.variants and p.image
    derive_attrs(p, DERIVE)
    assert p.attrs["width"] == "4E" and 10.0 in p.attrs["sizes_in_stock"]


def test_jsonld_parse_then_derive():
    html = (FX / "rebel_624_pdp.html").read_text()
    p = JsonLdAdapter({"base_url": "https://www.rebelsport.com.au",
                       "link_regex": "x"}).parse([html])[0]
    assert p.price == Decimal("119.99") and p.was_price == Decimal("139.99") and p.on_sale
    derive_attrs(p, DERIVE)
    assert 10.0 in p.attrs["sizes_in_stock"]


def test_magento_parse_and_variants():
    fixture = json.loads((FX / "taf_graphql_nb4e.json").read_text())
    raw = {"items": fixture["data"]["products"]["items"]}
    ps = MagentoGraphQLAdapter({"graphql_url": "x",
                                "base_url": "https://www.theathletesfoot.com.au"}).parse(raw)
    for p in ps:
        derive_attrs(p, {"width": DERIVE["width"]})
    assert any(p.attrs["width"] == "4E" for p in ps)
    assert any(p.id == "M880K154E.BLK" and p.on_sale for p in ps)   # the 30%-off black 880

    vraw = json.loads((FX / "taf_variant_m880k15.json").read_text())
    variants = MagentoGraphQLAdapter._variants(vraw)
    sizes = sorted(float(v.options["Size"]) for v in variants if v.available)
    assert 10.0 in sizes and 10.5 in sizes
