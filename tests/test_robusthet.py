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
            Val(rad=i, willys_kod=c[0].code if c else None, willys_antal=1, butik=None, motivering="")
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

    def kolla(self, code):
        finns = self.tillganglig(code)
        return finns, (self.product_details(code) if finns else None)


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


def test_hogst_ett_get_per_produkt_och_korning(data_dir, monkeypatch):
    import collections
    import json

    import httpx

    from veckohandla.planner import Reserv
    from veckohandla.stores import http, willys

    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(http, "_sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])

    sidor = {
        "A_ST": {"ingredients": "Gris- och nötkött", "googleAnalyticsCategory": "fardigmat|x"},
        "B_ST": {"ingredients": "Nötkött", "googleAnalyticsCategory": "fardigmat|x"},
        "C_ST": {"ingredients": "Nötkött, lök", "googleAnalyticsCategory": "fardigmat|x"},
    }
    get_p = collections.Counter()

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/axfood/rest/csrf-token":
            return httpx.Response(200, json="t")
        if p == "/axfood/rest/v2/store/activate":
            return httpx.Response(200, json={})
        if p == "/axfood/rest/v2/store/active":
            return httpx.Response(200, json={"storeId": "2341"})
        if p == "/search":
            return httpx.Response(200, json={"results": [
                {"code": c, "name": f"Vara {c}", "priceValue": 10.0, "online": True} for c in ("A_ST", "B_ST", "C_ST", "D_ST")]})
        if p.startswith("/axfood/rest/p/"):
            code = p.rsplit("/", 1)[1]
            get_p[code] += 1
            return httpx.Response(200, json=sidor[code]) if code in sidor else httpx.Response(404)
        return httpx.Response(500)

    monkeypatch.setattr(willys, "_client",
                        lambda: httpx.Client(base_url=willys.BASE, transport=httpx.MockTransport(handler)))

    class Planerare(FejkPlanerare):
        def plan_week(self, *a):
            rader = [Inkopsrad(vara=v, behov="1 st", sokord=v, till=["Måndag"]) for v in ("bullar", "färs", "saknas")]
            return Veckoplan(middagar=[], inkopslista=rader, kommentar="")

        def choose_products(self, rows, cands, ica, undvik):
            r = lambda *k: [Reserv(kod=x, antal=1) for x in k]
            return Produktval(val=[
                Val(rad=0, willys_kod="A_ST", willys_antal=1, butik=None, motivering="", willys_reserver=r("B_ST", "C_ST")),
                Val(rad=1, willys_kod="B_ST", willys_antal=1, butik=None, motivering="", willys_reserver=r("C_ST")),
                Val(rad=2, willys_kod="D_ST", willys_antal=1, butik=None, motivering=""),
            ])

    monkeypatch.setattr(pipeline, "Planner", Planerare)
    cfg = {**CFG, "hushall": {"sparrord": ["gris"]}}
    res = pipeline.run(cfg, log=lambda *a: None)

    assert dict(get_p) == {"A_ST": 1, "B_ST": 1, "C_ST": 1, "D_ST": 1}
    rad0, rad1, rad2 = res.lines
    assert rad0.product.code == "B_ST" and rad0.bortvalda[0][1] == "innehåller gris"
    assert [r.product.code for r in rad0.reserver] == ["C_ST"]
    assert rad1.product.code == "B_ST"
    assert rad2.product is None and "finns inte i butiken" in rad2.borttagen
    # Tillgänglighetsanropet fyllde ingredienscachen med datum
    cache = json.loads((data_dir / "ingredienser-cache.json").read_text())
    assert set(cache) == {"A_ST", "B_ST", "C_ST"} and all(v.get("hamtad") for v in cache.values())
