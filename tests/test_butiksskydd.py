"""Butikslistorna (Willys i butik och ICA) går genom samma fläskskydd som korgen."""

import pytest

from veckohandla import pipeline, report
from veckohandla.models import Offer, Product
from veckohandla.planner import Inkopsrad, Produktval, Val, Veckoplan

I_BUTIK = "Willys Test (i butik)"
CFG = {"claude": {"model": "x"},
       "butiker": {"willys": {"namn": "Willys Test", "store_id": "1", "hamtar_i_butik": True}, "ica": []},
       "hushall": {"sparrord": ["gris", "bacon"], "sparrord_ingredienser": ["skinka"]},
       "optimering": {"min_besparing_for_delning_kr": 0}}

KAMPANJER = [
    Offer(store=I_BUTIK, name="Köttbullar", brand="", deal="49,90/st", compare_price="", category="fardigmat|kottbullar",
          regular_price="69,90 kr", code="BULLAR_BUTIK", promo_qty=1, promo_total=49.9),
    Offer(store=I_BUTIK, name="Nötfärs", brand="", deal="79,90/st", compare_price="", category="kott-chark-och-fagel|kott",
          regular_price="99,90 kr", code="FARS_BUTIK", promo_qty=1, promo_total=79.9),
    Offer(store=I_BUTIK, name="Tacochips", brand="", deal="2 för 22,00", compare_price="", category="skafferi|chips",
          regular_price="12,50 kr", code="CHIPS_BUTIK", promo_qty=2, promo_total=22.0),
    Offer(store=I_BUTIK, name="Bacon skivat", brand="", deal="25,00/st", compare_price="", category="kott-chark-och-fagel|chark",
          regular_price="35,00 kr", code="BACON_BUTIK", promo_qty=1, promo_total=25.0),
    Offer(store="ICA X", name="Kassler", brand="", deal="59 kr/st", compare_price="", category="Färskvaror",
          code="ICA_KASSLER", kategori_id=6),
    Offer(store="ICA X", name="Äpplen", brand="", deal="10 kr/st", compare_price="", category="Frukt & Grönt",
          code="ICA_APPLE", kategori_id=4),
]
SIDOR = {  # /axfood/rest/p/<kod>: None = 404
    "BULLAR_BUTIK": {"ingredients": "Gris- och nötkött 73 %", "googleAnalyticsCategory": "fardigmat|kottbullar"},
    "FARS_BUTIK": None, "CHIPS_BUTIK": None,
}


def e_handel(code):
    return Product(store="W", code=code, name=f"E-handel {code}", price=200.0, size="1 st")


class Planerare:
    menyns_kampanjer: list = []

    def __init__(self, *a):
        pass

    def plan_week(self, offers, cfg, prev):
        Planerare.menyns_kampanjer = list(offers)
        rader = [Inkopsrad(vara=v, behov="1 st", sokord=v, till=["Måndag"])
                 for v in ("köttbullar", "nötfärs", "tacochips", "kassler", "äpplen")]
        return Veckoplan(middagar=[], inkopslista=rader, kommentar="")

    def choose_products(self, rows, cands, butiker, undvik, gar_alltid_at=None):
        val = lambda i, butik, kod, kr: Val(rad=i, willys_kod=f"E{i}_ST", willys_antal=1, butik=butik, butik_kod=kod,
                                           butik_erbjudande="enligt Claude", butik_antal=1, butik_kostnad_kr=kr, motivering="")
        return Produktval(val=[val(0, I_BUTIK, "BULLAR_BUTIK", 49.9), val(1, I_BUTIK, "FARS_BUTIK", 79.9),
                               val(2, I_BUTIK, "CHIPS_BUTIK", 11.0), val(3, "ICA X", "ICA_KASSLER", 59.0),
                               val(4, "ICA X", "ICA_APPLE", 10.0)])


class Session:
    butik_vald = True

    def search(self, q, store_name):
        i = ["köttbullar", "nötfärs", "tacochips", "kassler", "äpplen"].index(q)
        return [e_handel(f"E{i}_ST")]

    def kolla(self, code):
        if code in SIDOR:
            d = SIDOR[code]
            return (None, None) if d is None else (False, d)  # finns inte i e-handeln
        return True, {"ingredients": "nötkött", "googleAnalyticsCategory": "kott-chark-och-fagel|x"}


@pytest.fixture
def korning(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: list(KAMPANJER))
    monkeypatch.setattr(pipeline, "Planner", Planerare)
    res = pipeline._run(CFG, Session(), False, log=lambda *a: None)
    return res, {l.row.vara: l for l in res.lines}


def test_butiksrad_med_sparrord_i_ingredienserna_flyttas_till_e_handeln(korning):
    res, rader = korning
    bullar = rader["köttbullar"]
    assert not bullar.i_butik and bullar.product.code == "E0_ST"
    assert bullar.butik_stoppad == "kampanjvaran innehåller gris"
    assert "Inte i butik: kampanjvaran innehåller gris" in report.render(res)
    assert bullar not in res.butik_listor[I_BUTIK]


def test_butiksvara_utan_ingredienser_i_kottkategori_flaggas(korning):
    res, rader = korning
    assert rader["nötfärs"].i_butik and rader["nötfärs"].butik_kontrollera
    assert rader["tacochips"].i_butik and not rader["tacochips"].butik_kontrollera  # 404 men inte kött


def test_ica_rad_i_kottkategori_far_kontrollera_ingredienser(korning):
    res, rader = korning
    assert rader["kassler"].butik_kontrollera
    assert not rader["äpplen"].butik_kontrollera
    html = report.render(res)
    ica_del = html[html.index("<h2>ICA X"):]
    assert "Kontrollera ingredienser" in ica_del.split("</li>")[0]  # kasslerraden


def test_namnfiltret_kor_pa_butikskampanjer_fore_menyplaneringen(korning):
    namn = [o.name for o in Planerare.menyns_kampanjer]
    assert "Bacon skivat" not in namn  # spärrordet "bacon" i namnet
    assert "Köttbullar" in namn  # fångas först av ingredienskontrollen
