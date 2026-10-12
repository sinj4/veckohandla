import json

import pytest

from veckohandla import pipeline
from veckohandla.models import Offer, Product
from veckohandla.pipeline import Line, filtrera_kategorier, tillampa_ica_troskel, _blocked
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


# ---------- ICA-tröskeln (punkt 8) ----------

def _rad(vara):
    return Inkopsrad(vara=vara, behov="1 st", sokord=vara, till=["Måndag"])


def _line(vara, willys_kr, ica_kr, butik="ICA X"):
    prod = Product(store="W", code=f"{vara}_ST", name=vara, price=willys_kr) if willys_kr is not None else None
    val = Val(rad=0, willys_kod=prod.code if prod else None, willys_antal=1, ica_butik=butik,
              ica_erbjudande="kampanj", ica_antal=1, ica_kostnad_kr=ica_kr, motivering="")
    return Line(row=_rad(vara), product=prod, qty=1, willys_cost=willys_kr, ica=val)


def test_ica_over_troskeln_behaller_listan():
    lines = [_line("lax", 120.0, 60.0), _line("ost", 80.0, 50.0)]
    listor, spar = tillampa_ica_troskel(lines, 75)
    assert [l.row.vara for l in listor["ICA X"]] == ["lax", "ost"]
    assert spar["ICA X"] == 90.0


def test_ica_under_troskeln_flyttar_rader_med_willys_alternativ():
    lines = [_line("tomater", 83.7, 29.0), _line("specialost", None, 40.0)]
    listor, spar = tillampa_ica_troskel(lines, 75)
    # Tomaterna köps på Willys; bara raden utan Willys-alternativ blir kvar på ICA
    assert lines[0].ica is None and not lines[0].buy_at_ica
    assert [l.row.vara for l in listor["ICA X"]] == ["specialost"]
    assert spar["ICA X"] == 0.0


def test_ica_under_troskeln_utan_rader_kvar_ger_ingen_lista():
    lines = [_line("tomater", 83.7, 29.0)]
    listor, _ = tillampa_ica_troskel(lines, 75)
    assert listor == {}


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
