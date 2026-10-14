"""Uppskattat lager för varor som alltid går åt."""

import json

import pytest

from veckohandla import lager, pipeline, report
from veckohandla.lager import GarAlltidAt, uppskattat_lager
from veckohandla.models import Product
from veckohandla.planner import Inkopsrad, Produktval, Val, Veckoplan

AGG = GarAlltidAt("ägg", per_vecka=12)
KORGRAD_24 = {"code": "AGG24_ST", "qty": 1, "name": "Ägg 24p Frigående Garant", "size": "24p", "enheter": 24.0,
              "gar_alltid_at": "ägg"}


def test_las_gar_alltid_at_tar_namn_och_poster():
    poster = lager.las_gar_alltid_at(["mjölk", {"vara": "ägg", "per_vecka": 12}])
    assert poster == [GarAlltidAt("mjölk"), GarAlltidAt("ägg", 12)]


def test_lager_en_vecka_efter_kop():
    assert uppskattat_lager(AGG, [("2026-v41", [KORGRAD_24])], "2026-v42") == 12


def test_lager_tre_veckor_efter_kop_ar_slut():
    assert uppskattat_lager(AGG, [("2026-v39", [KORGRAD_24])], "2026-v42") == 0


def test_lager_foljer_flera_kop_vecka_for_vecka():
    korgar = [("2026-v40", [KORGRAD_24]), ("2026-v41", [KORGRAD_24])]
    assert uppskattat_lager(AGG, korgar, "2026-v42") == 24  # 24 −12 +24 −12


def test_aldre_korgfil_utan_nyckel_matchas_pa_namnet():
    gammal = {"code": "AGG24_ST", "qty": 1, "name": "Ägg 24p Frigående Inomhus Medium Garant", "size": "24p"}
    annat = {"code": "MJOLK_ST", "qty": 2, "name": "Mellanmjölk 1,5l", "size": "1,5l"}
    assert uppskattat_lager(AGG, [("2026-v41", [gammal, annat])], "2026-v42") == 12


def test_utan_per_vecka_eller_kop_ingen_uppskattning():
    assert uppskattat_lager(GarAlltidAt("ägg"), [("2026-v41", [KORGRAD_24])], "2026-v42") is None
    assert uppskattat_lager(AGG, [], "2026-v42") is None


# ---------- hela _run ----------

AGG_24 = Product(store="W", code="AGG24_ST", name="Ägg 24p Frigående Garant", price=59.90, size="24p",
                 jamfor_varde=2.50, jamfor_enhet="st")


class Planerare:
    def __init__(self, *a):
        pass

    def plan_week(self, *a):
        return Veckoplan(middagar=[], inkopslista=[Inkopsrad(vara="ägg", behov="6 st", sokord="ägg", till=["Onsdag"])],
                         kommentar="")

    def choose_products(self, rows, cands, butiker, undvik, gar_alltid_at=None):
        return Produktval(val=[Val(rad=0, willys_kod="AGG24_ST", willys_antal=1, butik=None, motivering="")])


class Session:
    butik_vald = True

    def search(self, q, store_name):
        return [AGG_24]

    def kolla(self, code):
        return True, {"ingredients": "ägg"}


def kor(data_dir, monkeypatch, gar_alltid_at, tidigare: dict[str, list[dict]]):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])
    monkeypatch.setattr(pipeline, "Planner", Planerare)
    monkeypatch.setattr(pipeline, "week_id", lambda: "2026-v42")
    for vecka, rader in tidigare.items():
        (data_dir / f"{vecka}-korg.json").write_text(json.dumps(rader))
    cfg = {"claude": {"model": "x"}, "butiker": {"willys": {"namn": "W", "store_id": "1"}, "ica": []},
           "hushall": {"sparrord": [], "gar_alltid_at": gar_alltid_at}, "optimering": {}}
    res = pipeline._run(cfg, Session(), False, log=lambda *a: None)
    korg = json.loads((data_dir / "2026-v42-korg.json").read_text())
    return res, korg


def test_lagret_racker_raden_hamnar_under_kolla_om_du_har_hemma(data_dir, monkeypatch):
    res, korg = kor(data_dir, monkeypatch, [{"vara": "ägg", "per_vecka": 12}], {"2026-v41": [KORGRAD_24]})
    (rad,) = res.lines
    assert rad.row.kanske_hemma and rad.lager_kvar == 12
    assert korg == []
    html = report.render(res)
    assert "Kolla om du har hemma" in html and "Uppskattat kvar: ca 12 st" in html


def test_kop_tre_veckor_tillbaka_raden_kops(data_dir, monkeypatch):
    res, korg = kor(data_dir, monkeypatch, [{"vara": "ägg", "per_vecka": 12}], {"2026-v39": [KORGRAD_24]})
    (rad,) = res.lines
    assert not rad.row.kanske_hemma and rad.lager_kvar is None
    assert korg[0]["code"] == "AGG24_ST"
    assert korg[0]["gar_alltid_at"] == "ägg" and korg[0]["enheter"] == 24  # 59,90 / 2,50 = 23,96 -> 24 st


def test_post_som_bara_ar_ett_namn_fungerar_som_forut(data_dir, monkeypatch):
    res, korg = kor(data_dir, monkeypatch, ["ägg"], {"2026-v41": [KORGRAD_24]})
    (rad,) = res.lines
    assert rad.storpack and not rad.row.kanske_hemma
    assert korg[0]["code"] == "AGG24_ST"


def test_lager_med_enheter_fran_riktiga_priser(data_dir, monkeypatch):
    # Korgfilen från förra veckan skrivs av koden själv (enheter ur 59,90 kr / 2,50 kr/st)
    from veckohandla.pipeline import _korgrad
    forra = {**_korgrad(AGG_24, 1), "gar_alltid_at": "ägg"}
    res, korg = kor(data_dir, monkeypatch, [{"vara": "ägg", "per_vecka": 12}], {"2026-v41": [forra]})
    assert res.lines[0].row.kanske_hemma and res.lines[0].lager_kvar == 12 and korg == []


# ---------- storpack och lager tillsammans med en flaggad rad ----------

def _kor_med_butiksagg(data_dir, monkeypatch, tidigare):
    from veckohandla.models import Offer

    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "week_id", lambda: "2026-v42")
    butiksagg = Offer(store="W (i butik)", name="Ägg 30p", brand="", deal="49,90/st", compare_price="", category="mejeri",
                      regular_price="79,90 kr", code="AGG30_BUTIK", promo_qty=1, promo_total=49.9)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [butiksagg])
    agg_6 = Product(store="W", code="AGG6_ST", name="Ägg 6p", price=19.90, size="6p", jamfor_varde=3.32, jamfor_enhet="st")

    class P(Planerare):
        def choose_products(self, rows, cands, butiker, undvik, gar_alltid_at=None):
            from veckohandla.planner import Reserv
            return Produktval(val=[Val(rad=0, willys_kod="AGG6_ST", willys_antal=1, motivering="",
                                       willys_reserver=[Reserv(kod="AGG24_ST", antal=1)],
                                       butik="W (i butik)", butik_kod="AGG30_BUTIK", butik_erbjudande="", butik_antal=1,
                                       butik_kostnad_kr=49.9)])

    class S(Session):
        def search(self, q, store_name):
            return [agg_6, AGG_24]

    monkeypatch.setattr(pipeline, "Planner", P)
    for vecka, rader in tidigare.items():
        (data_dir / f"{vecka}-korg.json").write_text(json.dumps(rader))
    cfg = {"claude": {"model": "x"}, "butiker": {"willys": {"namn": "W", "store_id": "1"}, "ica": []},
           "hushall": {"sparrord": [], "gar_alltid_at": [{"vara": "ägg", "per_vecka": 12}]},
           "optimering": {"min_besparing_willys_i_butik_kr": 10}}
    res = pipeline._run(cfg, S(), False, log=lambda *a: None)
    return res, json.loads((data_dir / "2026-v42-korg.json").read_text())


def test_storpack_med_flaggat_butiksalternativ(data_dir, monkeypatch):
    res, korg = _kor_med_butiksagg(data_dir, monkeypatch, {"2026-v39": [KORGRAD_24]})  # lagret slut
    (rad,) = res.lines
    assert rad.storpack and rad.product.code == "AGG24_ST"  # lägst pris per enhet bland e-handelns ägg
    assert rad.flaggad and rad.butik_spar == pytest.approx(59.90 - 49.90)  # mot storpackets pris
    assert [k["code"] for k in korg] == ["AGG24_ST"]  # ligger ändå i korgen
    html = report.render(res)
    assert "Storpack, lägst jämförpris" in html and "Billigare i butik:" in html


def test_lager_racker_flaggas_inte_och_kops_inte(data_dir, monkeypatch):
    res, korg = _kor_med_butiksagg(data_dir, monkeypatch, {"2026-v41": [KORGRAD_24]})  # 12 kvar
    (rad,) = res.lines
    assert rad.row.kanske_hemma and rad.lager_kvar == 12
    assert not rad.flaggad and res.butik_flaggor == {} and res.kop_i_butik == {}
    assert korg == []
