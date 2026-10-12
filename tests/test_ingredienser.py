import json

import pytest

from veckohandla import ingredienser

DETALJER = {
    "KOTTBULLAR_ST": {"ingredients": "INGREDIENSER: Gris- och nötkött 73 %, lök, potatis",
                      "googleAnalyticsCategory": "fardigmat|kottbullar-och-farsprodukter"},
    "NOTKOTTBULLAR_ST": {"ingredients": "Ingredienser: Nötkött 80 %, lök, ströbröd",
                         "googleAnalyticsCategory": "fardigmat|kottbullar-och-farsprodukter"},
    "KORV_UTAN_INFO_ST": {"ingredients": "", "googleAnalyticsCategory": "kott-chark-och-fagel|chark"},
    "ZUCCHINI_ST": {"ingredients": "", "googleAnalyticsCategory": "frukt-och-gront|gronsaker"},
    "SKINKPIZZA_ST": {"ingredients": "Vetemjöl, tomat, SKINKA 12 %, ost", "googleAnalyticsCategory": "fardigmat|pizza"},
}
ORD = ["gris", "skinka", "fläsk", "ister"]


@pytest.fixture(autouse=True)
def ingen_paus(monkeypatch):
    monkeypatch.setattr(ingredienser, "PAUS_S", 0)


def test_kontrollera(tmp_path):
    anrop = []

    def hamta(code):
        anrop.append(code)
        return DETALJER[code]

    res = ingredienser.kontrollera(list(DETALJER), ORD, tmp_path / "cache.json", hamta)
    assert res["KOTTBULLAR_ST"].status == "borttagen" and res["KOTTBULLAR_ST"].ord == "gris"
    assert res["NOTKOTTBULLAR_ST"].status == "ok"  # köttbullar på bara nöt släpps igenom
    assert res["KORV_UTAN_INFO_ST"].status == "kontrollera"
    assert res["ZUCCHINI_ST"].status == "ok"  # grönsaker utan ingredienslista är ok
    assert res["SKINKPIZZA_ST"].ord == "skinka"  # versaler i ingredienslistan
    assert len(anrop) == len(DETALJER)


def test_cache_per_produktkod(tmp_path):
    cache = tmp_path / "cache.json"
    ingredienser.kontrollera(["KOTTBULLAR_ST"], ORD, cache, lambda c: DETALJER[c])
    assert "KOTTBULLAR_ST" in json.loads(cache.read_text())

    def far_inte_anropas(code):
        raise AssertionError("ska läsas från cachen")

    res = ingredienser.kontrollera(["KOTTBULLAR_ST"], ORD, cache, far_inte_anropas)
    assert res["KOTTBULLAR_ST"].status == "borttagen"


def test_hamtfel_ger_kontrollera_och_cachas_inte(tmp_path):
    cache = tmp_path / "cache.json"

    def trasig(code):
        raise ConnectionError("nere")

    res = ingredienser.kontrollera(["X_ST"], ORD, cache, trasig)
    assert res["X_ST"].status == "kontrollera"
    assert json.loads(cache.read_text()) == {}


def test_paus_mellan_anrop(tmp_path, monkeypatch):
    sovit = []
    monkeypatch.setattr(ingredienser, "PAUS_S", 0.5)
    monkeypatch.setattr(ingredienser.time, "sleep", sovit.append)
    ingredienser.kontrollera(["ZUCCHINI_ST", "KOTTBULLAR_ST", "SKINKPIZZA_ST"], ORD, tmp_path / "c.json",
                             lambda c: DETALJER[c])
    assert sovit == [0.5, 0.5]  # ingen paus före första anropet
