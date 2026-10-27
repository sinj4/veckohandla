"""Prishistorik: kompakt sparning per vecka och markering mot medianen av ordinarie pris."""

import json

import pytest

from veckohandla import pipeline, priser, report
from veckohandla.models import Offer, Product
from veckohandla.pipeline import Line, Result
from veckohandla.planner import Inkopsrad, Veckoplan, _offers_block


def willys(pris_st, ordinarie="20,00 kr", kod="101_ST", namn="Kaffe", store="Willys"):
    return Offer(store=store, name=namn, brand="Zoégas", deal=f"{pris_st:.2f}/st", compare_price="50,00 kr/kg",
                 category="", regular_price=ordinarie, code=kod, promo_qty=1, promo_total=pris_st)


def ica(deal, ordinarie="20,00", id="5004121223", namn="Äpplen i påse"):
    return Offer(store="ICA X", name=namn, brand="", deal=deal, compare_price="10:00/kg", category="",
                 regular_price=ordinarie, code=id)


def historik(data_dir, veckor, offers_per_vecka):
    for v, offers in zip(veckor, offers_per_vecka):
        priser.spara(v, offers, data_dir)


# ---------- Kampanjpris och sparning ----------

@pytest.mark.parametrize("offer, pris", [
    (Offer(store="W", name="Läsk", brand="", deal="3 för 53", compare_price="", category="", code="1_ST",
           promo_qty=3, promo_total=53.0), 17.67),
    (Offer(store="W", name="Lax", brand="", deal="", compare_price="", category="", code="1_KG",
           promo_qty=1, promo_total=99.0), None),  # viktvara – enheten kan skilja
    (ica("2 för 35 kr (Max 1 köp/hushåll)"), 17.5),
    (ica("10 kr/st (Max 1 köp/hushåll)"), 10.0),
    (ica("29,90 kr/kg"), None),
    (ica("25% rabatt"), None),
])
def test_kampanjpris(offer, pris):
    assert priser.kampanjpris(offer) == pris


def test_sparas_kompakt(data_dir):
    fil = priser.spara("2026-v44", [willys(15.0), ica("2 för 35 kr")], data_dir)
    assert fil == data_dir / "priser" / "2026-v44.json"
    assert json.loads(fil.read_text()) == [
        {"butik": "Willys", "kod": "101_ST", "namn": "Kaffe", "kampanjpris": 15.0, "ordinarie": 20.0,
         "jamforpris": "50,00 kr/kg", "varumarke": "Zoégas"},
        {"butik": "ICA X", "kod": "", "namn": "Äpplen i påse", "kampanjpris": 17.5, "ordinarie": 20.0,
         "jamforpris": "10:00/kg"},  # ICA:s id är ett erbjudande-id, ingen produktkod
    ]
    assert list(data_dir.glob(pipeline.PLAN_GLOB)) == []


# ---------- Markering ----------

@pytest.mark.parametrize("pris, notis", [
    (17.0, "bra pris"),        # 15 % under medianen 20
    (17.01, ""),               # knappt
    (19.0, "vanligt pris"),    # inom 5 %
    (21.0, "vanligt pris"),
    (18.5, ""),                # mellan gränserna
])
def test_bedomning_mot_medianen(pris, notis):
    assert priser.bedom(pris, [19.0, 20.0, 25.0]) == notis


def test_ingen_markering_med_mindre_an_tre_veckor(data_dir):
    historik(data_dir, ["2026-v42", "2026-v43"], [[willys(15.0)], [willys(15.0)]])
    offers = [willys(10.0)]
    assert priser.markera("2026-v44", offers, data_dir) == [] and offers[0].prisnotis == ""

    historik(data_dir, ["2026-v41"], [[willys(15.0)]])
    assert priser.markera("2026-v44", offers, data_dir) == offers and offers[0].prisnotis == "bra pris"


def test_bara_de_senaste_atta_veckorna_fore_aktuell_vecka(data_dir):
    gamla = [f"2026-v{v:02d}" for v in range(30, 33)]  # ordinarie 100 kr – ska inte räknas
    nya = [f"2026-v{v:02d}" for v in range(33, 41)]  # 8 veckor med ordinarie 20 kr
    historik(data_dir, gamla + nya, [[willys(15.0, "100,00 kr")]] * 3 + [[willys(15.0)]] * 8)
    priser.spara("2026-v44", [willys(5.0, "1,00 kr")], data_dir)  # aktuell vecka räknas inte
    priser.spara("2026-v45", [willys(5.0, "1,00 kr")], data_dir)  # inte heller senare veckor
    assert priser.historik("2026-v44", data_dir)["Willys|101_ST"] == [20.0] * 8
    o = willys(19.5)
    priser.markera("2026-v44", [o], data_dir)
    assert o.prisnotis == "vanligt pris"


def test_ica_kopplas_ihop_pa_namn_trots_nytt_id(data_dir):
    historik(data_dir, ["2026-v41", "2026-v42", "2026-v43"],
             [[ica("2 för 35 kr", "25,00", id=str(i))] for i in range(3)])
    o = ica("2 för 35 kr", "25,00", id="999")
    priser.markera("2026-v44", [o], data_dir)
    assert o.prisnotis == "bra pris"  # 17,50 mot median 25


def test_samma_kod_i_olika_butiker_hals_isar(data_dir):
    historik(data_dir, ["2026-v41", "2026-v42", "2026-v43"], [[willys(15.0, store="Willys (i butik)")]] * 3)
    o = willys(10.0)
    priser.markera("2026-v44", [o], data_dir)
    assert o.prisnotis == ""


# ---------- Planeraren, flödet och rapporten ----------

def test_planeraren_far_markeringen():
    o, p = willys(10.0), willys(19.0, kod="102_ST", namn="Te")
    utan = _offers_block([o, p])
    assert "BRA PRIS" not in utan and "Prismarkering" not in utan
    o.prisnotis, p.prisnotis = "bra pris", "vanligt pris"
    med = _offers_block([o, p])
    assert med.startswith("Prismarkering ur prishistoriken: BRA PRIS = minst 15 % under medianen")
    assert "Kaffe (Zoégas): 10.00/st [50,00 kr/kg, ord. 20,00 kr] – BRA PRIS" in med
    assert "Te (Zoégas): 19.00/st [50,00 kr/kg, ord. 20,00 kr] – VANLIGT PRIS" in med


def test_kampanjerna_markeras_och_sparas_i_flodet(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline, "week_id", lambda today=None: "2026-v44")
    historik(data_dir, ["2026-v41", "2026-v42", "2026-v43"], [[willys(15.0)]] * 3)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [willys(10.0)])
    cfg = {"butiker": {"willys": {"namn": "Willys"}}, "hushall": {}, "optimering": {"uteslut_kategorier": []}}
    logg = []
    offers, _ = pipeline._kampanjer(cfg, logg.append, [])
    assert offers[0].prisnotis == "bra pris"
    assert "  Prishistorik: 1 med bra pris, 0 med vanligt pris" in logg
    assert json.loads((data_dir / "priser" / "2026-v44.json").read_text())[0]["kampanjpris"] == 10.0


def test_rapporten_visar_markeringen():
    bra, vanlig = willys(10.0), willys(19.0, kod="102_ST", namn="Te")
    bra.prisnotis, vanlig.prisnotis = "bra pris", "vanligt pris"
    prod = Product(store="Willys", code="101_ST", name="Kaffe", price=10.0)
    rad = Inkopsrad(vara="kaffe", behov="1 st", sokord="kaffe", till=["Måndag"])
    res = Result(week="2026-v44", plan=Veckoplan(middagar=[], inkopslista=[rad], kommentar=""),
                 lines=[Line(row=rad, product=prod, qty=1, willys_cost=10.0)], willys_namn="Willys",
                 prismarkerade=[bra, vanlig])
    html = report.render(res)
    assert "Prishistorik (8 veckor): 1 kampanjer med bra pris, 1 med vanligt pris." in html
    assert "Bra pris den här veckan (1)" in html and "Willys: Kaffe – 10.00/st (ord. 20,00 kr)" in html
    rad_html = html[html.index(">Kaffe</a>"):]
    assert rad_html.index("🏷️ bra pris") < rad_html.index("</tr>")
    assert "Prishistorik" not in report.render(Result(week="v", plan=res.plan, lines=[]))
