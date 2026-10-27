"""Matlådor: extra portioner vissa dagar i prompten, inköpslistan och rapporten."""

import pytest

from veckohandla import pipeline, report
from veckohandla.pipeline import Result
from veckohandla.planner import Ingrediens, Middag, Planner, Veckoplan, matlador, matlador_for

from .test_vallage import CFG as VAL_CFG, FORSLAG, VECKA, FejkPlanerare, miljo, spara_forslag  # noqa: F401

H = {"vuxna": 2, "barn": [], "middagar_per_vecka": 5, "portioner_per_middag": 4, "preferenser": "Gott.",
     "undvik": ["fläsk"]}
MATLADOR = {"dagar": ["Tisdag", "torsdag"], "extra_portioner": 2}


def test_standard_ar_av():
    assert matlador(H) == ([], 0)
    assert matlador({**H, "matlador": {"dagar": ["tisdag"], "extra_portioner": 0}}) == ([], 0)
    assert matlador_for("Tisdag", H) == 0


def test_dagar_och_extra_portioner():
    h = {**H, "matlador": MATLADOR}
    assert matlador(h) == (["tisdag", "torsdag"], 2)
    assert [matlador_for(d, h) for d in ("Måndag", "Tisdag", "tisdag 28/10", "Torsdag:", "Fredag")] == [0, 2, 2, 2, 0]


@pytest.mark.parametrize("fel, text", [
    ({"dagar": ["tisdagar"], "extra_portioner": 2}, "okänd dag tisdagar"),
    ({"dagar": ["tisdag"], "extra_portioner": -1}, "negativt"),
])
def test_felaktig_config(fel, text):
    with pytest.raises(ValueError, match=text):
        matlador({**H, "matlador": fel})


@pytest.fixture
def prompter(monkeypatch):
    sett = []
    monkeypatch.setattr(Planner, "_parse", lambda self, prompt, schema, *a, **k: sett.append(prompt) or schema)
    return sett


def test_auto_prompten(prompter):
    cfg = {"hushall": H, "skafferi": ["salt"]}
    Planner("m").plan_week([], cfg, [])
    Planner("m").plan_week([], {**cfg, "hushall": {**H, "matlador": MATLADOR}}, [])
    utan, med = prompter
    assert "Matlådor" not in utan
    rad = ("Matlådor: på tisdag och torsdag lagas 6 portioner i stället för 4 (2 extra till matlådor). "
           "Ingredienserna för de dagarna och inköpslistan ska räcka till det.")
    assert med == utan.replace("Dagar: måndag–fredag.\n", f"Dagar: måndag–fredag.\n{rad}\n")


def test_auto_flodet_markerar_dagarna(data_dir, monkeypatch):
    from .test_robusthet import CFG, FejkSession

    class Planerare(FejkPlanerare):
        def plan_week(self, *a):
            middagar = [Middag(dag=d, ratt=d, beskrivning="", tid_min=10, kampanjvaror=[], ingredienser=[],
                               instruktioner=[]) for d in ("Måndag", "Tisdag", "Torsdag")]
            return Veckoplan(middagar=middagar, inkopslista=[], kommentar="")

    monkeypatch.setattr(pipeline, "Planner", Planerare)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])
    cfg = {**CFG, "hushall": {**CFG["hushall"], "portioner_per_middag": 4, "matlador": MATLADOR}}
    res = pipeline._run(cfg, FejkSession("1"), False, log=lambda *a: None)
    assert res.matlador == {"Tisdag": 2, "Torsdag": 2}


def test_vallaget_galler_ratterna_pa_matladedagarna(miljo, prompter):  # noqa: F811
    spara_forslag(miljo)
    cfg = {**VAL_CFG, "hushall": {**VAL_CFG["hushall"], "matlador": {"dagar": ["tisdag"], "extra_portioner": 2}}}
    res = pipeline.valj(cfg, ["4", "1", "3"], log=lambda *a: None)
    assert res.matlador == {"Tisdag": 2}
    mandag, tisdag, _ = res.plan.middagar
    assert tisdag.ratt == "Lax"
    assert tisdag.instruktioner == ["Laga 6 portioner (2 extra till matlådor) – skala upp mängderna i receptet.", "Laga"]
    assert mandag.instruktioner == ["Laga"]
    assert FORSLAG.ratter[0].instruktioner == ["Laga"]  # förslagen ändras inte

    # Riktiga planerarens inköpsprompt för samma val
    Planner("m").shopping_list(res.plan.middagar, {**cfg, "skafferi": ["salt"]})
    prompt = prompter[-1]
    assert ("## Tisdag: Lax\nMatlådor: laga 6 portioner (2 extra). Ingredienserna nedan gäller 4 portioner – "
            "skala upp dem i inköpslistan.\n") in prompt
    assert "## Måndag: Pasta\nKampanjvaror" in prompt


def test_felaktig_matladeconfig_stoppar_valj_fore_anrop(miljo, monkeypatch):  # noqa: F811
    spara_forslag(miljo)
    monkeypatch.setattr(pipeline.willys, "WillysSession", lambda *a: pytest.fail("ingen Willys-session"))
    cfg = {**VAL_CFG, "hushall": {**VAL_CFG["hushall"], "matlador": {"dagar": ["helg"], "extra_portioner": 2}}}
    with pytest.raises(ValueError, match="okänd dag helg"):
        pipeline.valj(cfg, ["1"], log=lambda *a: None)


def test_rapporten_markerar_matladorna():
    middagar = [Middag(dag=d, ratt=r, beskrivning="", tid_min=20, kampanjvaror=[], instruktioner=[],
                       ingredienser=[Ingrediens(namn="lax", mangd="600 g")]) for d, r in (("Måndag", "Tacos"), ("Tisdag", "Lax"))]
    res = Result(week="2026-v44", plan=Veckoplan(middagar=middagar, inkopslista=[], kommentar=""), lines=[],
                 matlador={"Tisdag": 2})
    html = report.render(res)
    tisdag = html[html.index("Tisdag: Lax"):]
    assert "+2 matlådor" in tisdag[:tisdag.index("</h3>")]
    assert html.count("matlådor") == 1
