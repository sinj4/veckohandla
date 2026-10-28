"""ICA blockerar automatiska anrop (403): bara_lokalt och 403 ger en neutral rad i stället för en varning."""

import httpx
import pytest

from veckohandla import pipeline, report
from veckohandla.models import Offer
from veckohandla.pipeline import ICA_LOKALT, Notis, Result
from veckohandla.planner import Veckoforslag, Veckoplan
from veckohandla.stores import ica, willys

ICA_A = {"namn": "ICA A", "erbjudande_slug": "ica-a"}
ICA_B = {"namn": "ICA B", "erbjudande_slug": "ica-b"}


def cfg(*ica_butiker):
    return {"butiker": {"willys": {"namn": "W", "store_id": "1", "i_butik": False}, "ica": list(ica_butiker)}}


@pytest.fixture
def hamtat(monkeypatch):
    monkeypatch.setattr(willys, "fetch_offers", lambda *a, **k: [])
    sett = []

    def ica_offers(slug, namn):
        sett.append(slug)
        return [Offer(store=namn, name="Ost", brand="", deal="", compare_price="", category="")]

    monkeypatch.setattr(ica, "fetch_offers", ica_offers)
    return sett


def fel(status):
    req = httpx.Request("GET", "https://www.ica.se/erbjudanden/ica-a/")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError(f"Client error '{status}'", request=req, response=resp)


# ---------- bara_lokalt ----------

def test_bara_lokalt_hoppas_over_i_github_actions(hamtat, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    varningar = []
    offers = pipeline.fetch_all_offers(cfg({**ICA_A, "bara_lokalt": True}, ICA_B), varningar)
    assert hamtat == ["ica-b"] and [o.store for o in offers] == ["ICA B"]
    assert varningar == [ICA_LOKALT] and isinstance(varningar[0], Notis)


def test_bara_lokalt_hamtas_pa_datorn(hamtat, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    varningar = []
    pipeline.fetch_all_offers(cfg({**ICA_A, "bara_lokalt": True}, ICA_B), varningar)
    assert hamtat == ["ica-a", "ica-b"] and varningar == []


# ---------- 403 utan bara_lokalt ----------

def test_403_ger_neutral_rad_och_tips(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(willys, "fetch_offers", lambda *a, **k: [])
    monkeypatch.setattr(ica, "fetch_offers", lambda slug, namn: (_ for _ in ()).throw(fel(403)))
    varningar = []
    pipeline.fetch_all_offers(cfg(ICA_A), varningar)
    (v,) = varningar
    assert v == ICA_LOKALT and isinstance(v, Notis)
    assert v.tips == ("Tips: ICA A svarade 403 – sätt bara_lokalt: true för butiken i config.yaml så hämtas den "
                      "bara på datorn.")


@pytest.mark.parametrize("undantag", [fel(500), fel(429), httpx.ConnectError("nere")])
def test_andra_fel_ar_fortfarande_varningar(monkeypatch, undantag):
    monkeypatch.setattr(willys, "fetch_offers", lambda *a, **k: [])
    monkeypatch.setattr(ica, "fetch_offers", lambda slug, namn: (_ for _ in ()).throw(undantag))
    varningar = []
    pipeline.fetch_all_offers(cfg(ICA_A), varningar)
    (v,) = varningar
    assert v.startswith("Kunde inte hämta kampanjer från ICA A:") and not isinstance(v, Notis)


# ---------- Logg och rapporter ----------

def test_loggen_visar_raden_en_gang_med_tips(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda c, v: v.extend([
        Notis(ICA_LOKALT, tips="Tips: ICA A …"), Notis(ICA_LOKALT, tips="Tips: ICA B …"), "Annat fel"]) or [])
    logg = []
    pipeline._kampanjer({**cfg(), "hushall": {}, "optimering": {}}, logg.append, [], kontrollera_farska=False)
    assert [r for r in logg if "ICA" in r or "fel" in r] == [
        f"  {ICA_LOKALT}", "  Tips: ICA A …", "  Tips: ICA B …", "  VARNING: Annat fel"]


def test_notisens_text():
    assert ICA_LOKALT == ("ICA blockerar automatiska anrop just nu (403). Rätterna och korgen påverkas inte, "
                          "men ICA-priser jämförs inte.")


def test_rapporterna_visar_neutral_rad_i_stallet_for_varning():
    varningar = [Notis(ICA_LOKALT), Notis(ICA_LOKALT, tips="Tips"), "Kunde inte hämta X"]
    plan = Veckoplan(middagar=[], inkopslista=[], kommentar="")
    vecka = report.render(Result(week="2026-v44", plan=plan, lines=[], varningar=varningar))
    forslag = report.render_forslag(pipeline.Forslagsresultat(
        week="2026-v44", forslag=Veckoforslag(ratter=[], kommentar=""), middagar_per_vecka=5, varningar=varningar))
    for html in (vecka, forslag):
        assert html.count(ICA_LOKALT) == 1
        assert f"⚠️ {ICA_LOKALT}" not in html and f"ℹ️ {ICA_LOKALT}" in html
        assert "⚠️ Kunde inte hämta X" in html
        assert "Tips" not in html  # tipset står bara i loggen
