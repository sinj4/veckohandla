"""Butiksval, sökfel och tillgänglighetsfel får inte ge tysta följdfel."""

import pytest

from veckohandla import pipeline, report
from veckohandla.models import Product
from veckohandla.planner import Inkopsrad, Produktval, Val, Veckoplan

CFG = {"claude": {"model": "x"}, "butiker": {"willys": {"namn": "Willys Test", "store_id": "2341"}, "ica": []},
       "hushall": {"sparrord": []}, "optimering": {"min_besparing_for_delning_kr": 75}}


def prod(code):
    return Product(store="W", code=code, name=f"Vara {code}", price=10.0, size="1 st")


class FejkPlanerare:
    produktval_anrop = 0

    def __init__(self, *a):
        pass

    def plan_week(self, *a):
        rader = [Inkopsrad(vara=v, behov="1 st", sokord=v, till=["Måndag"]) for v in ("ägg", "mjölk")]
        return Veckoplan(middagar=[], inkopslista=rader, kommentar="")

    def choose_products(self, rows, cands, ica, undvik):
        FejkPlanerare.produktval_anrop += 1
        return Produktval(val=[
            Val(rad=i, willys_kod=c[0].code if c else None, willys_antal=1, ica_butik=None, motivering="")
            for i, c in enumerate(cands)
        ])


class FejkSession:
    def __init__(self, store_id, valj_fel=None, sok_fel=None):
        self.valj_fel, self.sok_fel = valj_fel, sok_fel
        self.butik_vald = False
        self.sokningar = 0

    def __enter__(self):
        return self

    def __exit__(self, *e):
        pass

    def valj_butik(self):
        if self.valj_fel:
            raise self.valj_fel
        self.butik_vald = True

    def search(self, q, store_name):
        self.sokningar += 1
        if self.sok_fel:
            raise self.sok_fel
        return [prod(f"{q}_ST")]

    def tillganglig(self, code):
        return True

    def product_details(self, code):
        return {"ingredients": ""}


@pytest.fixture
def miljo(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])
    monkeypatch.setattr(pipeline, "Planner", FejkPlanerare)
    FejkPlanerare.produktval_anrop = 0
    skapade = []

    def anvand(**kw):
        def ny(store_id):
            s = FejkSession(store_id, **kw)
            skapade.append(s)
            return s
        monkeypatch.setattr(pipeline.willys, "WillysSession", ny)
        return skapade

    return anvand


def test_butiksval_misslyckas_ger_varning_och_sok_utan_butik(miljo, monkeypatch):
    skapade = miljo(valj_fel=ConnectionError("nätet nere"))
    utan_butik = []
    monkeypatch.setattr(pipeline.willys, "search",
                        lambda q, store_name: utan_butik.append(q) or [prod(f"{q}_ST")])
    res = pipeline.run(CFG, log=lambda *a: None)
    assert any("Kunde inte välja butik, sökningen gäller hela Willys sortiment" in v for v in res.varningar)
    assert utan_butik == ["ägg", "mjölk"] and skapade[0].sokningar == 0
    assert [l.product.code for l in res.lines] == ["ägg_ST", "mjölk_ST"]
    assert "Kunde inte välja butik" in report.render(res)


def test_butiken_valjs_innan_claude_anropas(miljo, monkeypatch):
    ordning = []
    skapade = miljo()
    monkeypatch.setattr(FejkSession, "valj_butik", lambda self: ordning.append("butik") or setattr(self, "butik_vald", True))
    monkeypatch.setattr(FejkPlanerare, "plan_week", lambda self, *a: ordning.append("meny") or Veckoplan(
        middagar=[], inkopslista=[Inkopsrad(vara="ägg", behov="1", sokord="ägg", till=[])], kommentar=""))
    pipeline.run(CFG, log=lambda *a: None)
    assert ordning == ["butik", "meny"]


def test_alla_sokningar_misslyckas_avbryter_fore_produktvalet(miljo):
    miljo(sok_fel=TimeoutError("timeout"))
    with pytest.raises(pipeline.AllaSokningarMisslyckades, match="Alla 2 sökningar"):
        pipeline.run(CFG, log=lambda *a: None)
    assert FejkPlanerare.produktval_anrop == 0


def test_tillganglighet_503_behaller_alternativet_och_flaggar(miljo, monkeypatch):
    miljo()
    monkeypatch.setattr(FejkSession, "tillganglig", lambda self, code: None if code == "ägg_ST" else True)
    res = pipeline.run(CFG, log=lambda *a: None)
    agg, mjolk = res.lines
    assert agg.product.code == "ägg_ST" and agg.tillganglighet_okand and not agg.bortvalda
    assert not mjolk.tillganglighet_okand
    assert "Kunde inte kontrollera om varan finns i butiken" in report.render(res)
