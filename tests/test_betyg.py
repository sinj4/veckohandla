"""Betyg: data/betyg.json, kommandot betyg och vad planeraren får se."""

import datetime as dt
import json
import sys

import pytest

from veckohandla import __main__ as huvud
from veckohandla import betyg, pipeline
from veckohandla.planner import Planner, Veckoforslag, Veckoplan

CFG = {"hushall": {"vuxna": 2, "barn": [], "middagar_per_vecka": 5, "portioner_per_middag": 4,
                   "preferenser": "Gott.", "undvik": ["fläsk"]}, "skafferi": ["salt"]}


# ---------- Filen ----------

def test_satt_skriver_och_ersatter_samma_ratt_och_vecka(data_dir):
    betyg.satt(data_dir, "Tacos", "2026-v43", 1, "  barnen älskade den ")
    betyg.satt(data_dir, "Lax", "2026-v43", -1)
    betyg.satt(data_dir, "Tacos", "2026-v43", -1, "för starkt")
    assert json.loads((data_dir / "betyg.json").read_text()) == [
        {"ratt": "Lax", "vecka": "2026-v43", "betyg": -1},
        {"ratt": "Tacos", "vecka": "2026-v43", "betyg": -1, "kommentar": "för starkt"},
    ]
    with pytest.raises(ValueError):
        betyg.satt(data_dir, "Lax", "2026-v43", 0)


def test_smak_senaste_betyget_galler_och_hogst_15_gillade(data_dir):
    for i in range(20):
        betyg.satt(data_dir, f"Rätt {i}", f"2026-v{20 + i:02d}", 1)
    betyg.satt(data_dir, "Tacos", "2026-v30", 1)
    betyg.satt(data_dir, "tacos", "2026-v41", -1, "tröttnat")  # senare betyg vinner
    betyg.satt(data_dir, "Soppa", "2026-v01", -1)
    s = betyg.smak(data_dir)
    assert len(s.gillade) == 15 and s.gillade[0]["ratt"] == "Rätt 19"
    assert "Tacos" not in [p["ratt"] for p in s.gillade]
    assert [p["ratt"] for p in s.ogillade] == ["tacos", "Soppa"]  # alla ogillade, senaste först
    assert not betyg.smak(data_dir / "tom")


# ---------- Planeraren ----------

@pytest.fixture
def prompter(monkeypatch):
    sett = []
    monkeypatch.setattr(Planner, "_parse", lambda self, prompt, schema, *a, **k: sett.append(prompt) or schema)
    return sett


def test_bada_lagena_far_gillade_och_ogillade(data_dir, prompter):
    betyg.satt(data_dir, "Tacos", "2026-v43", 1, "barnen älskade den")
    betyg.satt(data_dir, "Lax i ugn", "2026-v43", 1)
    betyg.satt(data_dir, "Linsgryta", "2026-v42", -1, "för starkt")
    s = betyg.smak(data_dir)
    Planner("m").plan_week([], CFG, [], s)
    Planner("m").propose_dishes([], CFG, [], 10, s)
    for prompt in prompter:
        assert "Gillade rätter (gärna liknande): Tacos (barnen älskade den), Lax i ugn" in prompt
        assert "Ogillade rätter (undvik dem och liknande): Linsgryta (för starkt)" in prompt


def test_utan_betyg_ar_prompten_som_forut(prompter):
    Planner("m").plan_week([], CFG, ["Soppa"], betyg.Smak())
    Planner("m").plan_week([], CFG, ["Soppa"])
    assert prompter[0] == prompter[1]
    assert "Gillade" not in prompter[0] and "Ogillade" not in prompter[0]


def test_flodet_skickar_betygen_i_bada_lagena(data_dir, monkeypatch):
    betyg.satt(data_dir, "Tacos", "2026-v43", 1)
    sett = []

    class Planerare:
        def __init__(self, *a):
            pass

        def plan_week(self, offers, cfg, prev, smak):
            sett.append(("auto", smak))
            raise StopIteration

        def propose_dishes(self, offers, cfg, prev, antal, smak):
            sett.append(("val", smak))
            return Veckoforslag(ratter=[], kommentar="")

    monkeypatch.setattr(pipeline, "Planner", Planerare)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])
    cfg = {"claude": {"model": "m"}, "butiker": {"willys": {"namn": "W"}}, "hushall": {"middagar_per_vecka": 5},
           "optimering": {}}
    with pytest.raises(StopIteration):
        pipeline._run(cfg, object(), False, log=lambda *a: None)
    pipeline.foresla(cfg, log=lambda *a: None)
    assert [(lage, [p["ratt"] for p in s.gillade]) for lage, s in sett] == [("auto", ["Tacos"]), ("val", ["Tacos"])]


# ---------- Kommandot ----------

def plan(data_dir, vecka, ratter):
    middagar = [{"dag": d, "ratt": r} for d, r in zip(["Måndag", "Tisdag", "Onsdag"], ratter)]
    (data_dir / f"{vecka}.json").write_text(json.dumps({"middagar": middagar, "inkopslista": [], "kommentar": ""}))


def svar(*rader):
    it = iter(rader)

    def fraga(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return fraga


def test_betyg_for_forra_veckan(data_dir, capsys):
    forra = pipeline.week_id(dt.date.today() - dt.timedelta(days=7))
    plan(data_dir, forra, ["Tacos", "Lax", "Soppa"])
    assert huvud.satt_betyg(None, svar("+", "barnen älskade den", "", "−", "")) == 0
    assert betyg.las(data_dir) == [
        {"ratt": "Tacos", "vecka": forra, "betyg": 1, "kommentar": "barnen älskade den"},
        {"ratt": "Soppa", "vecka": forra, "betyg": -1},
    ]
    assert "2 betyg sparade" in capsys.readouterr().out


def test_betyg_med_vecka_visar_tidigare_och_tal_ctrl_d(data_dir, capsys):
    plan(data_dir, "2026-v40", ["Tacos", "Lax"])
    betyg.satt(data_dir, "Tacos", "2026-v40", 1, "god")
    assert huvud.satt_betyg("2026-v40", svar("x", "-")) == 0  # ogiltigt svar hoppas över, sedan EOF
    out = capsys.readouterr().out
    assert "Måndag: Tacos  [nu: + god]" in out and "Hoppar över" in out
    assert betyg.las(data_dir) == [{"ratt": "Tacos", "vecka": "2026-v40", "betyg": 1, "kommentar": "god"}]


def test_betyg_utan_plan_ger_fel(data_dir, capsys):
    assert huvud.satt_betyg("2026-v01", svar()) == 1
    assert "hittade ingen plan för 2026-v01" in capsys.readouterr().err


def test_betyg_fran_kommandoraden(data_dir, tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("hushall: {}\n")
    monkeypatch.setenv("VECKOHANDLA_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setattr(huvud, "load_env", lambda: None)
    plan(data_dir, "2026-v40", ["Tacos"])
    monkeypatch.setattr("builtins.input", svar("+", ""))
    monkeypatch.setattr(sys, "argv", ["veckohandla", "betyg", "--vecka", "2026-v40"])
    assert huvud.main() == 0
    assert betyg.las(data_dir) == [{"ratt": "Tacos", "vecka": "2026-v40", "betyg": 1}]
