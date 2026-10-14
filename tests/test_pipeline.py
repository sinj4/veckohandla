import json

import pytest

from veckohandla import pipeline
from veckohandla.models import Offer, Product
from veckohandla.pipeline import Line, filtrera_kategorier, tillampa_butikstroskel, _blocked
from veckohandla.planner import Inkopsrad, Val


# ---------- previous_dishes / korgfiler (regression för punkt 1) ----------

def _plan(ratter):
    return json.dumps({"middagar": [{"ratt": r} for r in ratter], "inkopslista": [], "kommentar": ""})


def test_previous_dishes_ignorerar_korg_och_cache(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline, "week_id", lambda: "2026-v42")
    (data_dir / "2026-v40.json").write_text(_plan(["Tacos"]))
    (data_dir / "2026-v40-korg.json").write_text("[]")  # en lista – fick tidigare previous_dishes att krascha
    (data_dir / "2026-v41.json").write_text(_plan(["Lax"]))
    (data_dir / "2026-v41-korg.json").write_text("[]")
    (data_dir / "2026-v42.json").write_text(_plan(["Den här veckan"]))  # aktuell vecka räknas inte
    (data_dir / "ingredienser-cache.json").write_text("{}")
    assert pipeline.previous_dishes() == ["Tacos", "Lax"]


def test_latest_cart_week(data_dir):
    (data_dir / "2026-v41-korg.json").write_text("[]")
    (data_dir / "2026-v42-korg.json").write_text("[]")
    (data_dir / "2026-v43.json").write_text(_plan([]))  # plan utan korg
    assert pipeline.latest_cart_week() == "2026-v42"


def test_latest_cart_week_utan_korg_ger_tydligt_fel(data_dir):
    with pytest.raises(pipeline.IngenKorg):
        pipeline.latest_cart_week()


# ---------- Butiksalternativ och tröskel (flaggning, inget flyttas ur korgen) ----------

def _rad(vara):
    return Inkopsrad(vara=vara, behov="1 st", sokord=vara, till=["Måndag"])


def _line(vara, willys_kr, ica_kr, butik="ICA X"):
    prod = Product(store="W", code=f"{vara}_ST", name=vara, price=willys_kr) if willys_kr is not None else None
    val = Val(rad=0, willys_kod=prod.code if prod else None, willys_antal=1, butik=butik,
              butik_erbjudande="kampanj", butik_antal=1, butik_kostnad_kr=ica_kr, motivering="")
    return Line(row=_rad(vara), product=prod, qty=1, willys_cost=willys_kr, butik=val)


def test_ica_over_troskeln_flaggas_men_ligger_kvar_i_korgen():
    lines = [_line("lax", 120.0, 60.0), _line("ost", 80.0, 50.0)]
    flaggor, spar, kop = tillampa_butikstroskel(lines, 75)
    assert [l.row.vara for l in flaggor["ICA X"]] == ["lax", "ost"]  # 60 + 30 = 90 ≥ 75
    assert spar["ICA X"] == 90.0 and kop == {}
    assert all(l.flaggad and l.i_korgen for l in lines)
    assert [l.butik_spar for l in lines] == [60.0, 30.0]


def test_ica_under_troskeln_flaggas_inte():
    lines = [_line("tomater", 83.7, 29.0)]  # sparar 54,70 < 75
    flaggor, spar, kop = tillampa_butikstroskel(lines, 75)
    assert flaggor == {} and spar == {} and kop == {}
    assert not lines[0].flaggad and lines[0].i_korgen and lines[0].butik is not None


def test_rad_utan_willys_produkt_blir_kop_i_butik_oavsett_troskel():
    lines = [_line("tomater", 83.7, 29.0), _line("specialost", None, 40.0)]
    flaggor, _, kop = tillampa_butikstroskel(lines, 1000)
    assert flaggor == {}
    assert [l.row.vara for l in kop["ICA X"]] == ["specialost"]


def test_butik_som_inte_ar_billigare_ger_inget_alternativ():
    lines = [_line("ost", 50.0, 60.0)]
    flaggor, _, _ = tillampa_butikstroskel(lines, 0)
    assert flaggor == {} and lines[0].butik is None and lines[0].i_korgen


def test_troskeln_galler_per_butik():
    lines = [_line("lax", 120.0, 60.0, butik="ICA A"), _line("ost", 80.0, 70.0, butik="ICA B")]
    flaggor, spar, _ = tillampa_butikstroskel(lines, lambda store: 50)
    assert list(flaggor) == ["ICA A"] and spar == {"ICA A": 60.0}  # ICA B sparar bara 10
    assert lines[0].flaggad and not lines[1].flaggad


# ---------- Spärrfilter och kategorifilter ----------

def test_sparrfilter():
    ord = ["fläsk", "gris", "korv", "karré", "blandfärs"]
    assert _blocked("Falukorv Prime Patrol", ord)
    assert _blocked("Karré Benfri Bit av Gris", ord)
    assert _blocked("Fläsk & Nötfärs 70/30", ord)
    assert not _blocked("Högrevsfärs 13% Sverige", ord)
    assert not _blocked("Köttbullar Färdiglagade", ord)  # fångas av ingredienskontrollen i stället


def _offer(cat):
    return Offer(store="S", name="x", brand="", deal="", compare_price="", category=cat)


def test_filtrera_kategorier():
    offers = [_offer("dryck|lask"), _offer("halsa-och-skonhet|kroppsvard"), _offer("Hem & fritid"),
              _offer("Frukt & Grönt"), _offer("")]
    kvar = filtrera_kategorier(offers, pipeline.UTESLUT_KATEGORIER)
    assert [o.category for o in kvar] == ["dryck|lask", "Frukt & Grönt", ""]
    assert len(filtrera_kategorier(offers, [])) == 5
