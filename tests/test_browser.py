"""Generic browser adapter against both rendered fixtures (NB + DigiDirect)."""
from pathlib import Path

from scrapehound.adapters.browser import BrowserAdapter
from scrapehound.config import load_sources

FX = Path(__file__).parent / "fixtures"
SOURCES = load_sources(Path(__file__).parent.parent / "config" / "sources.yaml")


def test_newbalance_selectors():
    s = SOURCES["newbalance_au"]
    ps = BrowserAdapter(s.options()).parse((FX / "nb_au_plp_4e.html").read_text(), s.filter)
    assert ps
    for p in ps:
        assert p.attrs["width"] == "4E" and p.attrs["brand"] == "New Balance"
        assert p.price > 0
        assert set(p.attrs["sizes_in_stock"]) == {10.0, 10.5}   # from faceted filter


def test_digidirect_leica_selectors():
    s = SOURCES["leica_digidirect"]
    ps = BrowserAdapter(s.options()).parse((FX / "digidirect_leica.html").read_text(), s.filter)
    assert len(ps) >= 5
    for p in ps:
        assert p.price > 0 and p.id and p.title
