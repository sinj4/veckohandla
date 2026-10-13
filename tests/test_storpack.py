"""Varor som alltid går åt köps i den förpackning som har lägst pris per enhet."""

import pytest

from veckohandla.ingredienser import Kontroll
from veckohandla.models import Product
from veckohandla.pipeline import Alternativ, valj_alternativ, valj_storpack
from veckohandla.planner import Inkopsrad, Planner, gar_alltid_at_rad


def agg(code, pris, st, enhet="st", **kw):
    return Product(store="W", code=code, name=f"Ägg {st}p", price=pris, size=f"{st}p",
                   jamfor_varde=round(pris / st, 2), jamfor_enhet=enhet, **kw)


AGG_6 = Alternativ(agg("AGG6_ST", 19.90, 6), 1)     # 3,32 kr/st
AGG_10 = Alternativ(agg("AGG10_ST", 37.90, 10), 1)  # 3,79 kr/st
AGG_24 = Alternativ(agg("AGG24_ST", 59.90, 24), 1)  # 2,50 kr/st
ALLA_OK = (lambda c: True, lambda c: Kontroll("ok"))


def test_storpack_valjer_lagst_jamforpris():
    valt, bort, _, _ = valj_storpack([AGG_6, AGG_10, AGG_24], *ALLA_OK)
    assert valt is AGG_24 and bort == []
    # Vanliga rader tar fortfarande det första godkända alternativet
    assert valj_alternativ([AGG_6, AGG_10, AGG_24], *ALLA_OK)[0] is AGG_6


def test_storpack_jamfor_inte_olika_enheter():
    # 24p anger jämförpris per kg (lägre siffra) – ska inte jämföras med styckpriserna
    agg_kg = Alternativ(agg("AGG24KG_ST", 59.90, 24, enhet="kg"), 1)
    agg_kg.product.jamfor_varde = 1.80
    valt, _, _, _ = valj_storpack([AGG_10, agg_kg, AGG_6], *ALLA_OK)
    assert valt is AGG_6


def test_storpack_raknar_jamforpris_pa_kampanjpris():
    kampanj_10 = Alternativ(agg("AGG10K_ST", 37.90, 10, promo_qty=1, promo_total=22.0), 1)  # 2,20 kr/st
    assert kampanj_10.product.jamforpris == 2.2
    valt, _, _, _ = valj_storpack([AGG_6, kampanj_10, AGG_24], *ALLA_OK)
    assert valt is kampanj_10


def test_storpack_hoppar_over_det_som_inte_finns():
    valt, bort, _, _ = valj_storpack([AGG_6, AGG_10, AGG_24], lambda c: c != "AGG24_ST", lambda c: Kontroll("ok"))
    assert valt is AGG_6
    assert [(a.product.code, o) for a, o in bort] == [("AGG24_ST", "finns inte i butiken")]


def test_storpack_utan_godkanda():
    assert valj_storpack([AGG_6], lambda c: False, None)[0] is None


def test_gar_alltid_at_matchar_ord_i_vara():
    rad = Inkopsrad(vara="Ägg", behov="4 st", sokord="ägg", till=[])
    assert gar_alltid_at_rad(rad, ["ägg"])
    assert not gar_alltid_at_rad(Inkopsrad(vara="mjölk", behov="1", sokord="mjölk", till=[]), ["ägg"])
    assert not gar_alltid_at_rad(rad, [])


def test_prompten_markerar_storpack():
    cap = {}

    class P(Planner):
        def __init__(self):
            self.model_produkter = "x"
            self.client = None

        def _parse(self, prompt, schema, system, effort, model):
            cap["prompt"] = prompt

    rader = [Inkopsrad(vara="ägg", behov="4 st", sokord="ägg", till=["Onsdag"]),
             Inkopsrad(vara="mjölk", behov="1 l", sokord="mjölk", till=["basvara"])]
    P().choose_products(rader, [[AGG_6.product], []], [], [], ["ägg"])
    rad_agg = next(l for l in cap["prompt"].splitlines() if l.startswith("[0]"))
    rad_mjolk = next(l for l in cap["prompt"].splitlines() if l.startswith("[1]"))
    assert "GÅR ALLTID ÅT" in rad_agg and "GÅR ALLTID ÅT" not in rad_mjolk
    assert "30 st eller 2 kg" in cap["prompt"]


def test_run_valjer_storpack_och_visar_det_i_rapporten(data_dir, monkeypatch):
    import json

    from veckohandla import pipeline, report
    from veckohandla.planner import Produktval, Reserv, Val, Veckoplan

    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])
    produkter = {p.product.code: p.product for p in (AGG_6, AGG_10, AGG_24)}

    class Planerare:
        def __init__(self, *a):
            pass

        def plan_week(self, *a):
            return Veckoplan(middagar=[], inkopslista=[Inkopsrad(vara="ägg", behov="4 st", sokord="ägg", till=["Onsdag"])],
                             kommentar="")

        def choose_products(self, rows, cands, butiker, undvik, gar_alltid_at=None):
            assert gar_alltid_at == ["ägg"]
            return Produktval(val=[Val(rad=0, willys_kod="AGG6_ST", willys_antal=1, butik=None, motivering="",
                                       willys_reserver=[Reserv(kod="AGG10_ST", antal=1), Reserv(kod="AGG24_ST", antal=1)])])

    class Session:
        butik_vald = True

        def search(self, q, store_name):
            return list(produkter.values())

        def kolla(self, code):
            return True, {"ingredients": "ägg"}

    monkeypatch.setattr(pipeline, "Planner", Planerare)
    cfg = {"claude": {"model": "x"}, "butiker": {"willys": {"namn": "Willys Test", "store_id": "1"}, "ica": []},
           "hushall": {"sparrord": [], "gar_alltid_at": ["ägg"]}, "optimering": {}}
    res = pipeline._run(cfg, Session(), False, log=lambda *a: None)
    (rad,) = res.lines
    assert rad.product.code == "AGG24_ST" and rad.storpack and not rad.bytt
    assert [r.product.code for r in rad.reserver] == ["AGG6_ST", "AGG10_ST"]
    korg = json.loads((data_dir / f"{res.week}-korg.json").read_text())
    assert korg[0]["code"] == "AGG24_ST"
    assert "Storpack, lägst jämförpris (2,50 kr/st)" in report.render(res)


# ---------- Punkt 3: effektivt pris per enhet för det antal som köps ----------

def test_2_for_kampanj_raknas_pa_faktiskt_antal():
    from veckohandla.pipeline import provningsordning
    from veckohandla.planner import Reserv, Val

    # Behov 6 ägg. 6p: 25 kr ordinarie (4,17 kr/st), "2 för 40". 10p: 35 kr (3,50 kr/st).
    p6 = Product(store="W", code="AGG6K_ST", name="Ägg 6p", price=25.0, size="6p", jamfor_varde=4.17,
                 jamfor_enhet="st", promo_qty=2, promo_total=40.0)
    p10 = Product(store="W", code="AGG10_ST", name="Ägg 10p", price=35.0, size="10p", jamfor_varde=3.50, jamfor_enhet="st")
    assert p6.jamforpris == 3.34  # kampanjens jämförpris – gäller bara vid köp av 2
    alt = provningsordning(Val(rad=0, willys_kod="AGG6K_ST", willys_antal=1, butik=None, motivering="",
                               willys_reserver=[Reserv(kod="AGG10_ST", antal=1)]), [p6, p10])
    assert [(a.product.code, a.qty) for a in alt] == [("AGG6K_ST", 1), ("AGG10_ST", 1)]  # best_qty: 40 > 25
    assert p6.effektivt_enhetspris(1) == pytest.approx(4.17, abs=0.01)
    valt, _, _, _ = valj_storpack(alt, *ALLA_OK)
    assert valt.product.code == "AGG10_ST"


def test_effektivt_pris_raknar_med_promo_max():
    p = Product(store="W", code="X", name="Ägg 6p", price=30.0, jamfor_varde=5.0, jamfor_enhet="st",
                promo_qty=1, promo_total=18.0, promo_max=1)
    assert p.enheter_per_forpackning == 6.0
    assert p.effektivt_enhetspris(1) == 3.0
    assert p.effektivt_enhetspris(2) == pytest.approx((18 + 30) / 12)  # andra paketet till ordinarie pris


def test_utan_enheter_anvands_jamforpriset_och_loggas():
    loggat = []
    a = Alternativ(Product(store="W", code="A", name="Ägg okänd", price=0.0, jamfor_varde=2.0, jamfor_enhet="st"), 1)
    b = Alternativ(agg("B", 59.90, 24), 1)  # 2,50 kr/st
    valt, _, _, _ = valj_storpack([b, a], *ALLA_OK, log=loggat.append)
    assert valt is a and any("använder jämförpriset" in m for m in loggat)


def test_rad_utan_gar_alltid_at_behaller_claudes_val(data_dir, monkeypatch):
    from veckohandla import pipeline
    from veckohandla.planner import Produktval, Reserv, Val, Veckoplan

    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])
    lok_300g = Product(store="W", code="LOK_ST", name="Gul lök 300g", price=12.0, size="300g", jamfor_varde=40.0, jamfor_enhet="kg")
    lok_2kg = Product(store="W", code="LOK2_ST", name="Gul lök 2kg", price=20.0, size="2kg", jamfor_varde=10.0, jamfor_enhet="kg")

    class Planerare:
        def __init__(self, *a):
            pass

        def plan_week(self, *a):
            return Veckoplan(middagar=[], inkopslista=[Inkopsrad(vara="gul lök", behov="300 g", sokord="lök", till=["Måndag"])],
                             kommentar="")

        def choose_products(self, rows, cands, butiker, undvik, gar_alltid_at=None):
            return Produktval(val=[Val(rad=0, willys_kod="LOK_ST", willys_antal=1, butik=None, motivering="",
                                       willys_reserver=[Reserv(kod="LOK2_ST", antal=1)])])

    class Session:
        butik_vald = True

        def search(self, q, store_name):
            return [lok_300g, lok_2kg]

        def kolla(self, code):
            return True, {"ingredients": ""}

    monkeypatch.setattr(pipeline, "Planner", Planerare)
    cfg = {"claude": {"model": "x"}, "butiker": {"willys": {"namn": "W", "store_id": "1"}, "ica": []},
           "hushall": {"sparrord": [], "gar_alltid_at": ["ägg"]}, "optimering": {}}
    (rad,) = pipeline._run(cfg, Session(), False, log=lambda *a: None).lines
    assert rad.product.code == "LOK_ST" and not rad.storpack  # 2 kg har lägre jämförpris men väljs inte
