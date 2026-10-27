"""Valläget: förslag som sparas och mejlas, val av rätter och samma flöde som auto-läget därefter."""

import json
import re
import sys

import pytest
import yaml

from veckohandla import __main__ as huvud
from veckohandla import pipeline, report
from veckohandla.models import Offer, Product
from veckohandla.planner import Ingrediens, Inkopslista, Inkopsrad, Produktval, Ratt, Val, Veckoforslag, Veckoplan

VECKA = "2026-v43"
CFG = {"claude": {"model": "x"}, "butiker": {"willys": {"namn": "Willys Test", "store_id": "2341"}, "ica": []},
       "hushall": {"middagar_per_vecka": 3, "portioner_per_middag": 4, "sparrord": []},
       "optimering": {}, "meny": {"lage": "val", "forslag": 4}}


def ratt(namn):
    return Ratt(ratt=namn, beskrivning=f"Om {namn}", tid_min=30, kampanjvaror=[f"{namn}-kampanj – Willys"],
                ingredienser=[Ingrediens(namn=namn.lower(), mangd="500 g")], instruktioner=["Laga"])


FORSLAG = Veckoforslag(ratter=[ratt(n) for n in ("Lax", "Tacos", "Linsgryta", "Pasta")], kommentar="Bra vecka")


def prod(code):
    return Product(store="W", code=code, name=f"Vara {code}", price=10.0, size="1 st")


class FejkPlanerare:
    anrop: list = []

    def __init__(self, *a):
        pass

    def plan_week(self, *a):
        FejkPlanerare.anrop.append("plan_week")
        return Veckoplan(middagar=[], inkopslista=[Inkopsrad(vara="ägg", behov="1 st", sokord="ägg", till=[])],
                         kommentar="auto")

    def propose_dishes(self, offers, cfg, previous, antal, smak=None):
        FejkPlanerare.anrop.append(("propose_dishes", antal, previous))
        return FORSLAG

    def shopping_list(self, middagar, cfg):
        FejkPlanerare.anrop.append(("shopping_list", [m.ratt for m in middagar]))
        rader = [Inkopsrad(vara=m.ratt.lower(), behov="500 g", sokord=m.ratt.lower(), till=[m.dag]) for m in middagar]
        return Inkopslista(inkopslista=rader, kommentar="Valda rätter")

    def choose_products(self, rows, cands, butiks_offers, undvik, gar_alltid_at=None):
        FejkPlanerare.anrop.append("choose_products")
        return Produktval(val=[Val(rad=i, willys_kod=c[0].code, willys_antal=1, butik=None, motivering="")
                               for i, c in enumerate(cands)])


class FejkSession:
    def __init__(self, store_id):
        self.butik_vald = False

    def __enter__(self):
        return self

    def __exit__(self, *e):
        pass

    def valj_butik(self):
        self.butik_vald = True

    def search(self, q, store_name):
        return [prod(f"{q}_ST")]

    def kolla(self, code):
        return True, {"ingredients": ""}


@pytest.fixture
def miljo(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "week_id", lambda today=None: VECKA)
    monkeypatch.setattr(pipeline, "fetch_all_offers",
                        lambda cfg, v: [Offer(store="Willys Test", name="Lax", brand="", deal="", compare_price="", category="")])
    monkeypatch.setattr(pipeline, "Planner", FejkPlanerare)
    monkeypatch.setattr(pipeline.willys, "WillysSession", FejkSession)
    monkeypatch.setattr(FejkPlanerare, "anrop", [])
    return data_dir


def spara_forslag(data_dir, vecka=VECKA):
    (data_dir / f"{vecka}-forslag.json").write_text(FORSLAG.model_dump_json())


# ---------- Förslagsfilen och veckoplanerna ----------

def test_forslagsfilen_matchas_inte_av_plan_globben(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline, "week_id", lambda today=None: "2026-v44")
    spara_forslag(data_dir, "2026-v43")
    (data_dir / "2026-v42.json").write_text(json.dumps({"middagar": [{"ratt": "Soppa"}]}))
    assert [f.name for f in data_dir.glob(pipeline.PLAN_GLOB)] == ["2026-v42.json"]
    assert [f.name for f in data_dir.glob(pipeline.FORSLAG_GLOB)] == ["2026-v43-forslag.json"]
    assert pipeline.previous_dishes() == ["Soppa"]  # förslagen räknas inte som ätna rätter
    with pytest.raises(pipeline.IngenKorg):
        pipeline.latest_cart_week()


def test_foresla_sparar_numrerade_forslag(miljo, monkeypatch):
    (miljo / "2026-v42.json").write_text(json.dumps({"middagar": [{"ratt": "Förra veckans soppa"}]}))
    res = pipeline.foresla(CFG, log=lambda *a: None)
    assert FejkPlanerare.anrop == [("propose_dishes", 4, ["Förra veckans soppa"])]
    assert res.week == VECKA and res.middagar_per_vecka == 3
    assert pipeline.las_forslag(VECKA) == FORSLAG
    assert pipeline.latest_forslag_week() == VECKA


# ---------- Val av nummer ----------

@pytest.mark.parametrize("nummer, fel", [
    ([], "minst ett nummer"),
    (["0"], "Nummer 0 finns inte – förslagen är numrerade 1–4"),
    (["5"], "Nummer 5 finns inte"),
    (["2", "x"], "'x' är inget nummer"),
    (["2", "2"], "Nummer 2 är valt två gånger"),
])
def test_ogiltiga_nummer(nummer, fel):
    with pytest.raises(pipeline.OgiltigtVal, match=fel):
        pipeline.valda_middagar(FORSLAG, nummer)


def test_hogst_sju_ratter():
    forslag = Veckoforslag(ratter=[ratt(str(i)) for i in range(10)], kommentar="")
    with pytest.raises(pipeline.OgiltigtVal, match="Högst 7"):
        pipeline.valda_middagar(forslag, list(range(1, 9)))


def test_dagar_i_vald_ordning():
    middagar = pipeline.valda_middagar(FORSLAG, ["4", "1", "3"])
    assert [(m.dag, m.ratt) for m in middagar] == [("Måndag", "Pasta"), ("Tisdag", "Lax"), ("Onsdag", "Linsgryta")]
    assert middagar[0].ingredienser == FORSLAG.ratter[3].ingredienser


def test_ogiltiga_nummer_stoppar_fore_alla_anrop(miljo, monkeypatch):
    spara_forslag(miljo)
    monkeypatch.setattr(pipeline.willys, "WillysSession", lambda *a: pytest.fail("ingen Willys-session"))
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda *a: pytest.fail("inga kampanjer"))
    with pytest.raises(pipeline.OgiltigtVal):
        pipeline.valj(CFG, ["1", "9"], log=lambda *a: None)
    assert FejkPlanerare.anrop == []


def test_saknade_forslag_ger_tydligt_fel(miljo):
    with pytest.raises(pipeline.IngaForslag, match="kör först"):
        pipeline.valj(CFG, ["1"], log=lambda *a: None)


# ---------- valj går genom det gemensamma flödet ----------

def test_valj_gar_genom_gemensamma_flodet(miljo, monkeypatch):
    spara_forslag(miljo)
    handla = []
    original = pipeline._handla
    monkeypatch.setattr(pipeline, "_handla", lambda *a, **k: handla.append(a[6]) or original(*a, **k))
    monkeypatch.setattr(pipeline, "kontrollera_farska_kampanjer", lambda *a, **k: pytest.fail("ingen färskhetskontroll"))

    res = pipeline.valj(CFG, ["2", "1"], log=lambda *a: None)

    assert handla == [VECKA]
    assert FejkPlanerare.anrop == [("shopping_list", ["Tacos", "Lax"]), "choose_products"]
    assert [(m.dag, m.ratt) for m in res.plan.middagar] == [("Måndag", "Tacos"), ("Tisdag", "Lax")]
    assert [l.product.code for l in res.lines] == ["tacos_ST", "lax_ST"]
    assert res.plan.kommentar == "Valda rätter" and res.cart is None

    plan = json.loads((miljo / f"{VECKA}.json").read_text())
    assert [m["ratt"] for m in plan["middagar"]] == ["Tacos", "Lax"]  # bara de valda rätterna
    korg = json.loads((miljo / f"{VECKA}-korg.json").read_text())
    assert [r["code"] for r in korg] == ["tacos_ST", "lax_ST"]


def test_valj_varnar_om_forslagen_ar_fran_en_annan_vecka(miljo):
    spara_forslag(miljo, "2026-v42")
    res = pipeline.valj(CFG, ["1"], week="2026-v42", log=lambda *a: None)
    assert res.week == "2026-v42"
    assert any("Förslagen gäller 2026-v42" in v for v in res.varningar)


def test_valj_fyller_korgen_med_fill_cart(miljo, monkeypatch):
    spara_forslag(miljo)
    fyllda = []
    monkeypatch.setattr(pipeline, "fill_saved_cart", lambda week, log=None, kedja="willys": fyllda.append((week, kedja)) or {"total": "1", "missing": []})
    res = pipeline.valj(CFG, ["3"], fill_cart=True, log=lambda *a: None)
    assert fyllda == [(VECKA, "willys")] and res.cart is not None


# ---------- Kommandoraden ----------

@pytest.fixture
def config_fil(tmp_path, monkeypatch):
    def skriv(meny):
        cfg = {**CFG, "epost": {"till": "x@example.com"}}
        cfg = {k: v for k, v in cfg.items() if k != "meny"} | ({"meny": meny} if meny else {})
        p = tmp_path / "config.yaml"
        p.write_text(yaml.safe_dump(cfg, allow_unicode=True))
        monkeypatch.setenv("VECKOHANDLA_CONFIG", str(p))
        return p

    monkeypatch.setattr(huvud, "load_env", lambda: None)
    monkeypatch.delenv("VECKOHANDLA_FYLL_KOMMANDO", raising=False)
    return skriv


def kor_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["veckohandla", *argv])
    return huvud.main()


@pytest.fixture
def mejl(monkeypatch):
    skickade = []
    monkeypatch.setenv("SMTP_PASSWORD", "fejk")
    monkeypatch.setattr(report, "send", lambda cfg, subject, body, pw: skickade.append((subject, body)))
    return skickade


def test_auto_lage_utan_meny_kor_som_forut(config_fil, miljo, mejl, monkeypatch):
    config_fil(None)
    assert kor_main(monkeypatch, "kor") == 0
    assert FejkPlanerare.anrop == ["plan_week", "choose_products"]
    assert [s for s, _ in mejl] == [f"Veckomeny {VECKA}"]
    assert (miljo / f"{VECKA}.json").exists() and not (miljo / f"{VECKA}-forslag.json").exists()


def test_okant_lage_ger_fel(config_fil, miljo, monkeypatch):
    config_fil({"lage": "kanske"})
    assert kor_main(monkeypatch, "kor", "--ingen-mejl") == 1
    assert FejkPlanerare.anrop == []


def test_kor_i_vallaget_mejlar_forslagen(config_fil, miljo, mejl, monkeypatch):
    config_fil({"lage": "val", "forslag": 4})
    monkeypatch.setenv("VECKOHANDLA_FYLL_KOMMANDO", "./fyll.sh")
    assert kor_main(monkeypatch, "kor", "--en-gang-per-vecka") == 0
    assert FejkPlanerare.anrop == [("propose_dishes", 4, [])]  # ingen meny, inget produktval
    assert not (miljo / f"{VECKA}.json").exists() and not (miljo / f"{VECKA}-korg.json").exists()
    assert (miljo / f"{VECKA}-forslag.json").exists() and (miljo / f"{VECKA}-forslag.html").exists()

    (subject, body), = mejl
    assert subject == f"Veckoförslag {VECKA}"
    text = re.sub(r"<[^>]+>", "", body)
    assert "./fyll.sh 1 2 3" in text
    assert body.index("./fyll.sh 1 2 3") < body.index("Lax")  # instruktionen står överst
    for i, namn in enumerate(["Lax", "Tacos", "Linsgryta", "Pasta"], 1):
        assert f"{i}.{namn} (30 min)" in text and f"Om {namn}" in text and f"{namn}-kampanj – Willys" in text


def test_en_gang_per_vecka_tittar_pa_forslagsfilen(config_fil, miljo, mejl, monkeypatch):
    config_fil({"lage": "val"})
    (miljo / f"{VECKA}.json").write_text("{}")  # en plan räcker inte i valläget
    assert kor_main(monkeypatch, "kor", "--en-gang-per-vecka") == 0
    assert FejkPlanerare.anrop and mejl

    FejkPlanerare.anrop.clear()
    assert kor_main(monkeypatch, "kor", "--en-gang-per-vecka") == 0
    assert FejkPlanerare.anrop == []


def test_forslagsmejl_som_misslyckas_ger_exit_4(config_fil, miljo, monkeypatch):
    config_fil({"lage": "val"})
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert kor_main(monkeypatch, "kor") == 4
    assert (miljo / f"{VECKA}-forslag.html").exists()


def test_valj_fran_kommandoraden(config_fil, miljo, mejl, monkeypatch):
    config_fil({"lage": "val"})
    spara_forslag(miljo)
    assert kor_main(monkeypatch, "valj", "3", "1") == 0
    (subject, body), = mejl
    assert subject == f"Veckomeny {VECKA}"
    assert "Måndag: Linsgryta" in body and "Tisdag: Lax" in body
    assert "python -m veckohandla fyll-varukorg 2026-v43" in body  # korgen är inte fylld


def test_valj_med_ogiltigt_nummer_fran_kommandoraden(config_fil, miljo, monkeypatch, capsys):
    config_fil({"lage": "val"})
    spara_forslag(miljo)
    assert kor_main(monkeypatch, "valj", "1", "7", "--ingen-mejl") == 1
    assert "Fel: Nummer 7 finns inte – förslagen är numrerade 1–4" in capsys.readouterr().err
    assert FejkPlanerare.anrop == []


def test_forslag_skrivs_ut_med_nummer(config_fil, miljo, monkeypatch, capsys):
    config_fil({"lage": "val"})
    spara_forslag(miljo)
    monkeypatch.setenv("VECKOHANDLA_FYLL_KOMMANDO", "./fyll.sh")
    assert kor_main(monkeypatch, "forslag") == 0
    out = capsys.readouterr().out
    assert " 1. Lax (30 min)" in out and " 4. Pasta (30 min)" in out and "./fyll.sh 1 2 3" in out


# ---------- Prompterna ----------

def test_forslagsprompten(monkeypatch):
    from veckohandla.planner import Planner

    sett = []
    monkeypatch.setattr(Planner, "_parse", lambda self, prompt, schema, system, effort, model:
                        sett.append((prompt, schema, model)) or FORSLAG)
    cfg = {"hushall": {"vuxna": 2, "barn": [6], "middagar_per_vecka": 5, "portioner_per_middag": 4,
                       "preferenser": "Fisk och vegetariskt varje vecka.", "undvik": ["fläsk", "gris"]},
           "skafferi": ["salt"]}
    p = Planner("meny-modell", "produkt-modell")
    p.propose_dishes([Offer(store="W", name="Lax", brand="", deal="", compare_price="", category="")],
                     cfg, ["Tacos"], 10)
    prompt, schema, model = sett[0]
    assert schema is Veckoforslag and model == "meny-modell"
    assert "Föreslå 10 middagsrätter för 2 vuxna och barn (6 år), 4 portioner per rätt." in prompt
    assert "inte ha någon veckodag" in prompt and "minst två med fisk och minst två vegetariska" in prompt
    assert "UNDVIK ALLTID (hårt krav, inga undantag): fläsk; gris" in prompt
    assert "Rätter från de senaste veckorna (upprepa inte): Tacos" in prompt
    assert "dag" not in Veckoforslag.model_json_schema()["$defs"]["Ratt"]["properties"]

    middagar = pipeline.valda_middagar(FORSLAG, [2, 1])
    p.shopping_list(middagar, cfg)
    prompt, schema, model = sett[1]
    assert schema is Inkopslista and model == "produkt-modell"
    assert "## Måndag: Tacos" in prompt and "- 500 g lax" in prompt
    assert "Finns alltid hemma (ska inte stå på inköpslistan): salt" in prompt and "kanske_hemma" in prompt
