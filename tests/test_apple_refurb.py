"""Apple refurb adapter: parse the embedded tiles JSON (no network)."""
from decimal import Decimal
from pathlib import Path
from scrapehound.adapters.apple import AppleRefurbAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "apple_refurb_mac.json"


def test_apple_refurb_parse():
    ps = AppleRefurbAdapter({"region": "au", "category": "mac"}).parse(FIXTURE.read_text())
    assert len(ps) >= 20
    p = sorted(ps, key=lambda x: x.price)[0]
    assert p.id.endswith("/A") and p.price > 0 and p.title.lower().startswith("refurbished")
    assert p.url.startswith("https://www.apple.com/au/shop/product/") and "?" not in p.url
    assert p.image and p.image.startswith("https://")
