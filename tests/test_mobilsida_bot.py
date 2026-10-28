"""Botens del av mobilsidan: betyg --fran-text och signerade knappar i mejlet (men aldrig i data/)."""

import json
import sys

import pytest

from veckohandla import __main__ as huvud
from veckohandla import betyg, mobil, pipeline, report

from .test_vallage import FORSLAG, VECKA, config_fil, kor_main, mejl, miljo, spara_forslag  # noqa: F401

NYCKEL = "lanknyckel-" + "q" * 50


def plan(data_dir, vecka="2026-v43", ratter=("Tacos", "Lax")):
    (data_dir / f"{vecka}.json").write_text(json.dumps({"middagar": [{"dag": "Måndag", "ratt": r} for r in ratter],
                                                        "inkopslista": [], "kommentar": ""}))


def fran_text(monkeypatch, text):
    monkeypatch.setattr(huvud, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["veckohandla", "betyg", "--fran-text", text])
    return huvud.main()


# ---------- betyg --fran-text ----------

def test_betyg_fran_text(data_dir, tmp_path, monkeypatch, capsys):
    (tmp_path / "config.yaml").write_text("hushall: {}\n")
    monkeypatch.setenv("VECKOHANDLA_CONFIG", str(tmp_path / "config.yaml"))
    plan(data_dir)
    text = json.dumps({"vecka": "2026-v43", "betyg": [{"ratt": "Tacos", "betyg": 1, "kommentar": "god"},
                                                      {"ratt": "Lax", "betyg": -1}]}, ensure_ascii=False)
    assert fran_text(monkeypatch, text) == 0
    assert betyg.las(data_dir) == [{"ratt": "Tacos", "vecka": "2026-v43", "betyg": 1, "kommentar": "god"},
                                   {"ratt": "Lax", "vecka": "2026-v43", "betyg": -1}]
    assert "2 betyg sparade för 2026-v43" in capsys.readouterr().out


@pytest.mark.parametrize("data, fel", [
    ("inte json", "Fel i betygen"),
    ({"vecka": "v43", "betyg": [{"ratt": "Tacos", "betyg": 1}]}, "ogiltig vecka"),
    ({"vecka": "2026-v40", "betyg": [{"ratt": "Tacos", "betyg": 1}]}, "hittade ingen plan för 2026-v40"),
    ({"vecka": "2026-v43", "betyg": []}, "ange 1–2 betyg"),
    ({"vecka": "2026-v43", "betyg": [{"ratt": "Pizza", "betyg": 1}]}, "'Pizza' finns inte i planen"),
    ({"vecka": "2026-v43", "betyg": [{"ratt": "Tacos", "betyg": 2}]}, "måste vara 1 eller -1"),
    ({"vecka": "2026-v43", "betyg": [{"ratt": "Tacos", "betyg": True}]}, "måste vara 1 eller -1"),
    ({"vecka": "2026-v43", "betyg": [{"ratt": "Tacos", "betyg": 1}, {"ratt": "Lax", "betyg": 5}]}, "Lax"),
    ({"vecka": "2026-v43", "betyg": [{"ratt": "Tacos", "betyg": 1, "kommentar": "x" * 501}]}, "högst 500"),
    ({"vecka": "2026-v43"}, "Fel i betygen"),
])
def test_ogiltiga_betyg_sparar_ingenting(data_dir, tmp_path, monkeypatch, capsys, data, fel):
    (tmp_path / "config.yaml").write_text("hushall: {}\n")
    monkeypatch.setenv("VECKOHANDLA_CONFIG", str(tmp_path / "config.yaml"))
    plan(data_dir)
    assert fran_text(monkeypatch, data if isinstance(data, str) else json.dumps(data)) == 1
    assert fel in capsys.readouterr().err
    assert betyg.las(data_dir) == []  # inte ens de giltiga posterna före felet


# ---------- signerade knappar ----------

@pytest.fixture
def mobilmiljo(monkeypatch):
    monkeypatch.setenv("MOBIL_ADRESS", "https://veckohandla-mobil.example.workers.dev")
    monkeypatch.setenv("LANKNYCKEL", NYCKEL)


def test_forslagsmejlet_far_valj_knappen_men_inte_filen(config_fil, miljo, mejl, mobilmiljo, monkeypatch, capsys):  # noqa: F811
    config_fil({"lage": "val", "forslag": 4})
    assert kor_main(monkeypatch, "kor") == 0
    (amne, mejltext), = mejl
    lank = mobil.vecklank("https://veckohandla-mobil.example.workers.dev", NYCKEL, VECKA, "valj")
    assert "✅ Välj rätter" in mejltext and lank.replace("&", "&amp;") in mejltext
    fil = (miljo / f"{VECKA}-forslag.html").read_text()
    assert "Välj rätter" not in fil and "t=" not in fil
    utskrift = capsys.readouterr()
    for text in (mejltext, fil, utskrift.out, utskrift.err):
        assert NYCKEL not in text


def test_veckomejlet_far_betygsknappen(config_fil, miljo, mejl, mobilmiljo, monkeypatch):  # noqa: F811
    config_fil({"lage": "val"})
    spara_forslag(miljo)
    assert kor_main(monkeypatch, "valj", "1") == 0
    (_, mejltext), = mejl
    assert "⭐ Sätt betyg på förra veckans rätter" in mejltext and "vy=betyg" in mejltext
    assert "📱 Fyll korgen på mobilen" in mejltext  # korgen är inte fylld
    fil = (miljo / f"{VECKA}.html").read_text()
    assert "Sätt betyg" not in fil and "📱 Fyll korgen på mobilen" in fil  # korglänken är ingen hemlighet
    assert NYCKEL not in mejltext + fil


def test_inga_knappar_utan_mobil_adress(config_fil, miljo, mejl, monkeypatch):  # noqa: F811
    monkeypatch.delenv("MOBIL_ADRESS", raising=False)
    monkeypatch.setenv("LANKNYCKEL", NYCKEL)
    config_fil({"lage": "val"})
    assert kor_main(monkeypatch, "kor") == 0
    assert "Välj rätter" not in mejl[0][1]
