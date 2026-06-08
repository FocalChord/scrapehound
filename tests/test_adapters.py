"""HTTP adapter parsers against real captured fixtures."""
import json
from decimal import Decimal
from pathlib import Path

from scrapehound.adapters.shopify import ShopifyAdapter
from scrapehound.adapters.sfcc_jsonld import SfccJsonLdAdapter
from scrapehound.adapters.magento_graphql import MagentoGraphQLAdapter
from scrapehound.models import Filter

FX = Path(__file__).parent / "fixtures"
SHOE = Filter(brand="New Balance", widths=["4E"], sizes=[10, 10.5])


def test_shopify_parse():
    raw = json.loads((FX / "shopify_trc_880.json").read_text())
    p = ShopifyAdapter({"base_url": "https://shop.therunningcompany.com.au"}).parse(raw, SHOE)[0]
    assert p.price == Decimal("230.00")
    assert p.attrs["width"] == "4E" and 10.0 in p.attrs["sizes_in_stock"]
    assert p.image and p.url.endswith("/products/mens-new-balance-fresh-foam-x-880-v15-4e-extra-wide")


def test_sfcc_jsonld_parse():
    html = (FX / "rebel_624_pdp.html").read_text()
    p = SfccJsonLdAdapter({"base_url": "https://www.rebelsport.com.au",
                           "link_regex": "x"}).parse([html], SHOE)[0]
    assert p.price == Decimal("119.99") and p.was_price == Decimal("139.99") and p.on_sale
    assert 10.0 in p.attrs["sizes_in_stock"]


def test_magento_parse_and_variant_sizes():
    fixture = json.loads((FX / "taf_graphql_nb4e.json").read_text())
    raw = {"items": fixture["data"]["products"]["items"]}
    ps = MagentoGraphQLAdapter({"graphql_url": "x",
                                "base_url": "https://www.theathletesfoot.com.au"}).parse(raw, SHOE)
    assert ps and any(p.attrs["width"] == "4E" for p in ps)
    assert any(p.id == "M880K154E.BLK" and p.on_sale for p in ps)   # the 30%-off black 880

    vraw = json.loads((FX / "taf_variant_m880k15.json").read_text())
    sizes = MagentoGraphQLAdapter.variant_sizes(vraw, {10.0, 10.5})
    assert 10.0 in sizes and 10.5 in sizes
