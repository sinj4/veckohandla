"""Mobillänkar: korgen som #veckohandla=-länk (maxlängd, kortning) och signerade veckolänkar."""

import json

import pytest

from veckohandla import mobil, pipeline, report
from veckohandla.pipeline import Result
from veckohandla.planner import Veckoplan

BASE = "https://www.willys.se"


def korg(n, reserver=0, kod_langd=12):
    return [{"code": f"{i:0{kod_langd - 3}d}_ST", "qty": 2, "pick_unit": "pieces" if i % 3 else "kilogram",
             "name": "Namn", "size": "1 st",
             "reserver": [{"code": f"{i}{j:06d}_ST", "qty": 1, "pick_unit": "pieces", "name": "R"} for j in range(reserver)]}
            for i in range(n)]


def test_lang_form_med_reserver_nar_den_far_plats():
    lank = mobil.korg_lank(korg(3, reserver=1), "willys", BASE)
    assert lank.startswith(f"{BASE}/#veckohandla=") and len(lank) <= mobil.MAX_LANGD
    d = mobil.avkoda(lank)
    assert d["version"] == 1 and d["kedja"] == "willys"
    assert d["rader"][0] == {"kod": "000000000_ST", "antal": 2, "enhet": "kilogram",
                             "reserver": [{"kod": "0000000_ST", "antal": 1, "enhet": "pieces"}]}
    assert "name" not in json.dumps(d)  # bara kod, antal och enhet


def test_kortade_faltnamn_och_sedan_utan_reserver():
    kort = mobil.avkoda(mobil.korg_lank(korg(30, reserver=1), "hemkop", "https://www.hemkop.se"))
    assert set(kort) == {"v", "s", "r"} and kort["s"] == "hemkop"
    assert kort["r"][1] == {"k": "000000001_ST", "a": 2, "e": "p", "r": [{"k": "1000000_ST", "a": 1, "e": "p"}]}
    utan = mobil.avkoda(mobil.korg_lank(korg(40, reserver=1), "willys", BASE))
    assert set(utan) == {"v", "s", "r"} and all("r" not in rad for rad in utan["r"])
    assert len(utan["r"]) == 40


def test_maxlangd():
    for n in range(1, 120):
        try:
            lank = mobil.korg_lank(korg(n, reserver=3), "willys", BASE)
        except mobil.ForLangLank as e:
            assert "max 4000" in str(e)
            assert n > 60  # en vanlig veckokorg (30–40 rader) får alltid plats
            break
        assert len(lank) <= mobil.MAX_LANGD
    else:
        pytest.fail("länken borde till slut bli för lång")


def test_veckolank_ar_signerad_och_innehaller_inte_nyckeln(monkeypatch):
    nyckel = "hemlig-lanknyckel-" + "x" * 40
    lank = mobil.vecklank("https://mobil.example.workers.dev/", nyckel, "2026-v44", "valj")
    assert lank.startswith("https://mobil.example.workers.dev/?v=2026-v44&t=") and lank.endswith("&vy=valj")
    assert nyckel not in lank
    # Samma algoritm som Workern: HMAC-SHA256(nyckel, "veckohandla:<vecka>") som base64url utan utfyllnad
    # Vektorn är kontrollerad med: printf 'veckohandla:2026-v44' | openssl dgst -sha256 -hmac nyckel -binary
    assert mobil.token("nyckel", "2026-v44") == "Sjw8DQBbjMYhOQ0V7TyGUAG9Yg_JSE_03nNubM65AMI"
    assert mobil.token(nyckel, "2026-v44") != mobil.token(nyckel, "2026-v45")
    monkeypatch.delenv("MOBIL_ADRESS", raising=False)
    monkeypatch.setenv("LANKNYCKEL", nyckel)
    assert mobil.vecklankar_fran_miljo("2026-v44") is None
    monkeypatch.setenv("MOBIL_ADRESS", "https://m.example")
    assert set(mobil.vecklankar_fran_miljo("2026-v44")) == {"valj", "betyg"}


def test_mobillanken_sparas_och_ar_ingen_veckoplan(data_dir):
    from veckohandla.stores import willys

    lank = pipeline.spara_mobillank("2026-v44", korg(2), willys.KEDJA, log=lambda *a: None)
    assert json.loads((data_dir / "2026-v44-mobillank.json").read_text()) == {"kedja": "willys", "lank": lank}
    assert list(data_dir.glob(pipeline.PLAN_GLOB)) == [] and list(data_dir.glob(pipeline.KORG_GLOB)) == []


def test_rapporten_har_knappen_nar_korgen_inte_ar_fylld():
    plan = Veckoplan(middagar=[], inkopslista=[], kommentar="")
    res = Result(week="2026-v44", plan=plan, lines=[], mobillank=f"{BASE}/#veckohandla=abc")
    html = report.render(res)
    assert "📱 Fyll korgen på mobilen" in html and f"href='{BASE}/#veckohandla=abc'" in html
    assert "Kräver bokmärket eller iPhone-genvägen" in html
    assert "Fyll korgen på mobilen" not in report.render(Result(week="v", plan=plan, lines=[], mobillank="x",
                                                                 cart={"total": "1", "missing": []}))
