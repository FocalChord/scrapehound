"""Apple adapter parse (no network) from a captured-shape payload."""
from scrapehound.adapters.apple import AppleAdapter

RAW = {
    "store": "Highpoint",
    "pickup": {"MU973X/A": {"pickupDisplay": "ineligible",
                            "messageTypes": {"regular": {"storePickupProductTitle": "Mac Studio"}}}},
    "delivery": {"MU973X/A": {"regular": {"deliveryOptionMessages": [{"displayName": "16-18 weeks"}]}}},
}


def test_apple_parse():
    p = AppleAdapter({"region": "au", "parts": ["MU973X/A"]}).parse(RAW)[0]
    assert p.id == "MU973X/A" and p.title == "Mac Studio"
    assert p.price is None                       # availability monitor, no price
    assert p.attrs["pickup"] == "ineligible"
    assert p.attrs["ships"] == "16-18 weeks"
