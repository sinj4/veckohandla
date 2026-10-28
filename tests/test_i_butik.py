"""Willys butikskampanjer (gäller bara i butik): hämtning, dubbletter, kostnad och tröskel."""

import httpx
import pytest

from veckohandla import pipeline
from veckohandla.models import Offer, Product
from veckohandla.pipeline import Line, berakna_butikskostnad, butikens_troskel, tillampa_butikstroskel
from veckohandla.planner import Inkopsrad, Val
from veckohandla.stores import willys

from .conftest import fixtur_json

CFG = {"butiker": {"willys": {"namn": "Willys Test", "store_id": "0000"}, "ica": []},
       "optimering": {"min_besparing_for_delning_kr": 75}}


def offline_item(code):
    return next(i for i in fixtur_json("willys_campaigns_offline.json")["results"]
                if i["potentialPromotions"][0]["mainProductCode"] == code)


# ---------- Hämtning och dubbletter ----------

def test_to_offer_tar_kod_ur_mainproductcode():
    o = willys._to_offer(offline_item("101840286_ST"), "Willys Test (i butik)")
    assert o.code == "101840286_ST"
    assert (o.name, o.size, o.deal) == ("Nötfärs", "800g", "79,90/st")
    assert (o.promo_qty, o.promo_total) == (1, 79.9)
    assert o.online is False


def test_fetch_all_offers_tar_bort_dubbletter_mot_e_handeln(monkeypatch):
    routes = {"/search/campaigns/online": fixtur_json("willys_campaigns_online.json"),
              "/search/campaigns/offline": fixtur_json("willys_campaigns_offline.json")}
    monkeypatch.setattr(willys, "_client", lambda: httpx.Client(
        base_url=willys.BASE, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=routes[r.url.path]))))
    offers = pipeline.fetch_all_offers(CFG, [])
    i_butik = [o for o in offers if o.store == "Willys Test (i butik)"]
    online = [o for o in offers if o.store == "Willys Test"]
    assert len(online) == 3
    # Läsk 1,5l (101859661_ST) har kampanj även i e-handeln och tas bort ur butikslistan
    assert sorted(o.code for o in i_butik) == sorted(["101840286_ST", offline_item_kod_2for()])
    assert "101859661_ST" in {o.code for o in online}


def offline_item_kod_2for():
    return next(i["potentialPromotions"][0]["mainProductCode"] for i in fixtur_json("willys_campaigns_offline.json")["results"]
                if i["name"] == "Bambuskott")


def test_i_butik_kan_stangas_av(monkeypatch):
    anrop = []
    monkeypatch.setattr(willys, "fetch_offers", lambda sid, namn, kanal="online": anrop.append(kanal) or [])
    pipeline.fetch_all_offers({**CFG, "butiker": {**CFG["butiker"], "willys": {**CFG["butiker"]["willys"], "i_butik": False}}}, [])
    assert anrop == ["online"]


def test_butikskampanjfel_ger_varning(monkeypatch):
    def fetch(sid, namn, kanal="online"):
        if kanal == "offline":
            raise httpx.ConnectError("nere")
        return []
    monkeypatch.setattr(willys, "fetch_offers", fetch)
    varningar = []
    pipeline.fetch_all_offers(CFG, varningar)
    assert varningar and "butikskampanjer" in varningar[0]


# ---------- Kostnad räknad i koden ----------

def test_kostnad_pris_per_styck():
    o = willys._to_offer(offline_item("101840286_ST"), "W")
    assert o.kostnad(1) == 79.9
    assert o.kostnad(2) == 159.8


def test_kostnad_2_for_med_max_per_hushall_fran_fixtur():
    o = willys._to_offer(offline_item(offline_item_kod_2for()), "W")  # Bambuskott 2 för 22, max 5, ord. 14,90
    assert (o.promo_qty, o.promo_total, o.promo_max) == (2, 22.0, 5)
    assert o.kostnad(2) == 22.0
    assert o.kostnad(3) == 22.0 + 14.9
    assert o.kostnad(12) == 5 * 22.0 + 2 * 14.9  # över max: ordinarie pris


def test_kostnad_2_for_40_max_1():
    o = Offer(store="W", name="x", brand="", deal="2 för 40,00", compare_price="", category="",
              regular_price="25,00 kr", code="X_ST", promo_qty=2, promo_total=40.0, promo_max=1)
    assert o.kostnad(2) == 40.0
    assert o.kostnad(4) == 40.0 + 2 * 25.0
    o.regular_price = ""
    assert o.kostnad(2) == 40.0
    assert o.kostnad(4) is None  # delvis ordinarie pris men okänt – går inte att räkna


def _val(kod, antal, uppskattat=99.0, butik="Willys Test (i butik)"):
    return Val(rad=0, willys_kod=None, willys_antal=1, butik=butik, butik_kod=kod, butik_erbjudande="enligt Claude",
               butik_antal=antal, butik_kostnad_kr=uppskattat, motivering="")


def test_berakna_butikskostnad_ersatter_claudes_uppskattning():
    o = willys._to_offer(offline_item("101840286_ST"), "W")
    v = _val("101840286_ST", 1)
    berakna_butikskostnad(v, {o.code: o})
    assert v.butik_kostnad_kr == 79.9 and v.butik_kostnad_beraknad
    assert "79,90/st" in v.butik_erbjudande


def test_berakna_butikskostnad_behaller_uppskattning_om_kampanjen_saknas():
    v = _val("OKAND_ST", 1, uppskattat=55.0)
    berakna_butikskostnad(v, {})
    assert v.butik_kostnad_kr == 55.0 and not v.butik_kostnad_beraknad


# ---------- Tröskel ----------

def _line(vara, willys_kr, butik_kr, butik="Willys Test (i butik)"):
    prod = Product(store="W", code=f"{vara}_ST", name=vara, price=willys_kr)
    v = _val(f"{vara}_B", 1, uppskattat=butik_kr, butik=butik)
    return Line(row=Inkopsrad(vara=vara, behov="1", sokord=vara, till=[]), product=prod, qty=1, willys_cost=willys_kr, butik=v)


def test_troskel_standard():
    tr = butikens_troskel(CFG)
    assert tr("Willys Test (i butik)") == 10 and tr("ICA X") == 75
    lines = [_line("färs", 89.9, 85.9)]  # sparar 4 kr < 10
    flaggor, _, _ = tillampa_butikstroskel(lines, tr)
    assert flaggor == {} and lines[0].i_korgen and not lines[0].flaggad
    lines = [_line("färs", 89.9, 79.9)]  # sparar 10 kr
    flaggor, spar, _ = tillampa_butikstroskel(lines, tr)
    assert spar["Willys Test (i butik)"] == pytest.approx(10.0) and lines[0].flaggad and lines[0].i_korgen


def test_troskel_fran_config():
    cfg = {**CFG, "optimering": {"min_besparing_willys_i_butik_kr": 40, "min_besparing_for_delning_kr": 75}}
    assert butikens_troskel(cfg)("Willys Test (i butik)") == 40


def test_rapporten_flaggar_raden_och_sammanfattar_per_butik():
    from veckohandla import report
    from veckohandla.pipeline import Result
    from veckohandla.planner import Veckoplan

    l = _line("nötfärs", 109.0, 0)
    o = willys._to_offer(offline_item("101840286_ST"), "W")
    l.butik.butik_kod, l.butik.butik_antal = o.code, 1
    berakna_butikskostnad(l.butik, {o.code: o})
    res = Result(week="2026-v42", plan=Veckoplan(middagar=[], inkopslista=[], kommentar=""), lines=[l],
                 willys_namn="Willys Test", willys_i_butik_namn="Willys Test (i butik)")
    res.butik_flaggor, res.butik_besparing, res.kop_i_butik = tillampa_butikstroskel([l], butikens_troskel(CFG))
    res.willys_total = 109.0
    res.med_butiksalternativ = round(109.0 - res.butik_besparing["Willys Test (i butik)"], 2)
    html = report.render(res)
    assert ("Billigare i butik: Nötfärs 800g: 79,90/st 79,90 kr på Willys Test (i butik), spar 29,10 kr. "
            "Ta bort ur korgen om du köper den där.") in html
    assert "<b>Willys i butik</b>: spar 29 kr, ta bort Nötfärs ur korgen" in html
    assert "<h2>Korgen: 109,00 kr</h2>" in html
    assert "Om du tar alla flaggade butiksalternativ: <b>79,90 kr</b>" in html
