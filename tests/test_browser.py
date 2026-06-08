"""Browser adapter + the source's own derive/filter config, on both fixtures."""
from pathlib import Path

from scrapehound.adapters.browser import BrowserAdapter
from scrapehound.config import load_sources
from scrapehound.derive import derive_attrs

FX = Path(__file__).parent / "fixtures"
SOURCES = load_sources(Path(__file__).parent.parent / "config" / "sources.yaml")


def test_newbalance_extract_derive_filter():
    s = SOURCES["newbalance_au"]
    ps = BrowserAdapter(s.options()).parse((FX / "nb_au_plp_4e.html").read_text())
    assert ps
    for p in ps:
        derive_attrs(p, s.derive)        # const brand/width/sizes from config
        assert p.attrs["brand"] == "New Balance" and p.attrs["width"] == "4E"
        assert p.attrs["sizes_in_stock"] == [10, 10.5]
        assert s.filter.matches(p)


def test_digidirect_leica_extract_no_filter():
    s = SOURCES["leica_digidirect"]
    ps = BrowserAdapter(s.options()).parse((FX / "digidirect_leica.html").read_text())
    assert len(ps) >= 5
    for p in ps:
        assert p.price > 0 and p.id and p.title
        assert s.filter.matches(p)        # leica has no filter -> matches all
