"""Varor som alltid går åt köps i den förpackning som har lägst jämförpris."""

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
