"""Generic embedded_json adapter — Apple refurb is now just a config of it."""
from pathlib import Path
from scrapehound.adapters.embedded_json import EmbeddedJsonAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "apple_refurb_mac.json"
CFG = {
    "url": "https://www.apple.com/au/shop/refurbished/mac",
    "base_url": "https://www.apple.com",
    "key": "tiles",
    "map": {"id": "partNumber", "title": "title",
            "price": "price.currentPrice.raw_amount",
            "url": "productDetailsUrl", "image": "image.sources.0.srcSet"},
}


def test_embedded_json_apple_refurb():
    ps = EmbeddedJsonAdapter(CFG).parse(FIXTURE.read_text())
    assert len(ps) >= 20
    p = sorted(ps, key=lambda x: x.price)[0]
    assert p.id.endswith("/A") and p.price > 0
    assert p.title.lower().startswith("refurbished")
    assert p.url.startswith("https://www.apple.com/au/shop/product/") and "?" not in p.url
    assert p.image and p.image.startswith("https://")
