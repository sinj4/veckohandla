"""Hemköp: samma Axfood-API som Willys, butiker.e_handel och Hemköp som jämförelsebutik."""

import json
import sys

import httpx
import pytest

from veckohandla import __main__ as huvud
from veckohandla import pipeline, priser, report
from veckohandla.models import Offer, Product
from veckohandla.planner import Inkopsrad, Produktval, Val, Veckoplan
from veckohandla.stores import axfood, hemkop, willys

from .conftest import fixtur_json


def mock(monkeypatch, modul, routes, anrop=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if anrop is not None:
            anrop.append((request.method, request.url.path))
        svar = routes[request.url.path]
        return svar if isinstance(svar, httpx.Response) else httpx.Response(200, json=svar)

    monkeypatch.setattr(modul, "_client",
                        lambda: httpx.Client(base_url=modul.BASE, transport=httpx.MockTransport(handler)))


# ---------- Axfood-API:t mot Hemköps fixturer ----------

def test_kedjorna_delar_api_men_inte_bas_url():
    assert (willys.KEDJA.nyckel, willys.KEDJA.namn, willys.KEDJA.base) == ("willys", "Willys", "https://www.willys.se")
    assert (hemkop.KEDJA.nyckel, hemkop.KEDJA.namn, hemkop.KEDJA.base) == ("hemkop", "Hemköp", "https://www.hemkop.se")
    assert isinstance(hemkop.session("4127"), axfood.AxfoodSession)


def test_hemkop_kampanjer_online_och_i_butik(monkeypatch):
    mock(monkeypatch, hemkop, {"/search/campaigns/online": fixtur_json("hemkop_campaigns_online.json"),
                               "/search/campaigns/offline": fixtur_json("hemkop_campaigns_offline.json")})
    online = hemkop.fetch_offers("4127", "Hemköp Skanstull")
    i_butik = hemkop.fetch_offers("4127", "Hemköp Skanstull (i butik)", kanal="offline")
    assert len(online) == 3 and len(i_butik) == 3
    for o in online + i_butik:
        assert o.code.endswith(("_ST", "_KG")) and o.name and o.deal and o.regular_price
        assert o.promo_total is not None  # online: prisobjekt, i butik: tal – båda tolkas
    assert all(o.start for o in i_butik) and not any(o.start for o in online)


def test_hemkop_sok_och_butiker(monkeypatch):
    mock(monkeypatch, hemkop, {"/search": fixtur_json("hemkop_search.json"),
                               "/axfood/rest/search/store": fixtur_json("hemkop_stores.json")})
    produkter = hemkop.search("kycklingfilé", "Hemköp Skanstull")
    assert produkter and all(p.url.startswith("https://www.hemkop.se/produkt/") for p in produkter)
    assert all(p.price > 0 for p in produkter)
    butiker = hemkop.find_stores("Stockholm")
    assert [b["storeId"] for b in butiker] == ["4127", "4162"]


def test_hemkop_session_valjer_butik_och_laser_produkt(monkeypatch):
    produkt = fixtur_json("hemkop_produkt.json")
    anrop = []
    mock(monkeypatch, hemkop, {
        "/axfood/rest/csrf-token": "tok",
        "/axfood/rest/v2/store/activate": {},
        "/axfood/rest/v2/store/active": {"storeId": "4127"},
        f"/axfood/rest/p/{produkt['code']}": produkt,
        "/search": fixtur_json("hemkop_search.json"),
    }, anrop)
    with hemkop.session("4127") as sess:
        finns, d = sess.kolla(produkt["code"])
        assert sess.butik_vald and finns is True and d["ingredients"]
        assert sess.search("kyckling", "H")[0].url.startswith("https://www.hemkop.se/")
    assert anrop[:3] == [("GET", "/axfood/rest/csrf-token"), ("POST", "/axfood/rest/v2/store/activate"),
                         ("GET", "/axfood/rest/v2/store/active")]


def test_fel_butik_namnger_kedjan(monkeypatch):
    mock(monkeypatch, hemkop, {"/axfood/rest/csrf-token": "tok", "/axfood/rest/v2/store/activate": {},
                               "/axfood/rest/v2/store/active": {"storeId": "9999"}})
    with pytest.raises(axfood.ButiksvalMisslyckades, match="Hemköp valde butik '9999'"):
        hemkop.session("4127").valj_butik()


# ---------- Config ----------

W = {"namn": "Willys Test", "store_id": "0000"}
H = {"namn": "Hemköp Test", "store_id": "4127"}


def test_e_handel_standard_ar_willys():
    cfg = {"butiker": {"willys": W, "ica": []}}
    assert pipeline.e_handel(cfg) == "willys" and pipeline.kedjemodul(cfg) is willys
    assert pipeline.jamforelsekedjor(cfg) == []
    assert pipeline.willys_i_butik_namn(cfg) == "Willys Test (i butik)"


def test_e_handel_hemkop_och_willys_som_jamforelse():
    cfg = {"butiker": {"e_handel": "hemkop", "willys": W, "hemkop": H, "ica": []}}
    assert pipeline.kedjemodul(cfg) is hemkop
    assert pipeline.jamforelsekedjor(cfg) == [("willys", W)]
    assert pipeline.axfood_butiker(cfg) == {"Hemköp Test (i butik)", "Willys Test"}


@pytest.mark.parametrize("butiker, fel", [
    ({"e_handel": "coop", "willys": W}, "willys eller hemkop"),
    ({"e_handel": "hemkop", "willys": W}, "butiker.hemkop saknas"),
])
def test_felaktig_e_handel(butiker, fel):
    with pytest.raises(ValueError, match=fel):
        pipeline.e_handel({"butiker": butiker})


def test_jamforelsekedjans_butikskampanjer_hamtas(monkeypatch):
    hamtat = []
    monkeypatch.setattr(willys, "fetch_offers", lambda sid, namn, kanal="online": hamtat.append(("W", kanal)) or [])

    def hemkop_offers(sid, namn, kanal="online"):
        hamtat.append(("H", kanal))
        return [Offer(store=namn, name="Lax", brand="", deal="", compare_price="", category="", code="1_ST")]

    monkeypatch.setattr(hemkop, "fetch_offers", hemkop_offers)
    offers = pipeline.fetch_all_offers({"butiker": {"willys": W, "hemkop": H, "ica": []}}, [])
    assert hamtat == [("W", "online"), ("W", "offline"), ("H", "offline")]  # bara Hemköps butikskampanjer
    assert [o.store for o in offers] == ["Hemköp Test"]


def test_jamforelsekedja_som_fallerar_ger_varning(monkeypatch):
    monkeypatch.setattr(willys, "fetch_offers", lambda *a, **k: [])
    monkeypatch.setattr(hemkop, "fetch_offers", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("nere")))
    varningar = []
    pipeline.fetch_all_offers({"butiker": {"willys": W, "hemkop": H, "ica": []}}, varningar)
    assert varningar == ["Kunde inte hämta kampanjer från Hemköp Test: nere"]


# ---------- Hela flödet med Hemköp som e-handel ----------

class FejkSession:
    skapade: list = []

    def __init__(self, store_id):
        self.store_id, self.butik_vald = store_id, False
        FejkSession.skapade.append(store_id)

    def __enter__(self):
        return self

    def __exit__(self, *e):
        pass

    def valj_butik(self):
        self.butik_vald = True

    def search(self, q, store_name):
        return [Product(store=store_name, code=f"{q}_ST", name=f"Vara {q}", price=30.0, size="1 st")]

    def kolla(self, code):
        ingr = "fläsk" if code == "korv_ST" else "nötkött"
        return True, {"ingredients": ingr, "googleAnalyticsCategory": "kott"}


class Planerare:
    args: tuple = ()

    def __init__(self, *a):
        Planerare.args = a

    def plan_week(self, *a):
        rader = [Inkopsrad(vara=v, behov="1 st", sokord=v, till=["Måndag"]) for v in ("nötfärs", "lax")]
        return Veckoplan(middagar=[], inkopslista=rader, kommentar="")

    def choose_products(self, rows, cands, butiks_offers, undvik, gar=None):
        return Produktval(val=[
            Val(rad=0, willys_kod="nötfärs_ST", willys_antal=1, butik="Willys Test", butik_kod="101_ST",
                butik_antal=1, butik_kostnad_kr=99.0, motivering=""),
            Val(rad=1, willys_kod="lax_ST", willys_antal=1, butik="Willys Test", butik_kod="korv_ST",
                butik_antal=1, butik_kostnad_kr=5.0, motivering=""),
        ])


def test_flodet_med_hemkop_som_e_handel_och_willys_som_jamforelse(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "week_id", lambda today=None: "2026-v44")
    monkeypatch.setattr(pipeline, "Planner", Planerare)
    monkeypatch.setattr(hemkop, "HemkopSession", FejkSession)
    monkeypatch.setattr(willys, "WillysSession", lambda *a: pytest.fail("Willys används bara för jämförelse"))
    FejkSession.skapade = []
    jamfor = [Offer(store="Willys Test", name="Nötfärs", brand="", deal="20,00/st", compare_price="", category="kott",
                    regular_price="30,00 kr", code="101_ST", promo_qty=1, promo_total=20.0),
              Offer(store="Willys Test", name="Korv", brand="", deal="5 kr", compare_price="", category="kott",
                    regular_price="10,00 kr", code="korv_ST", promo_qty=1, promo_total=5.0)]
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: jamfor)
    cfg = {"claude": {"model": "m"}, "butiker": {"e_handel": "hemkop", "willys": W, "hemkop": H, "ica": []},
           "hushall": {"sparrord": ["fläsk"]}, "optimering": {"min_besparing_for_delning_kr": 0}}

    res = pipeline.run(cfg, log=lambda *a: None)

    assert FejkSession.skapade == ["4127"]
    assert Planerare.args == ("m", "m", "Hemköp", ["Willys Test"])
    assert (res.kedja, res.kedja_url, res.willys_namn) == ("Hemköp", "https://www.hemkop.se/", "Hemköp Test")
    farsen, laxen = res.lines
    assert farsen.product.code == "nötfärs_ST" and laxen.product.code == "lax_ST"
    # Willys-kampanjen räknas i koden som för "i butik" (Claude uppskattade 99 kr)
    assert farsen.butik.butik_kostnad_kr == 20.0 and farsen.butik.butik_kostnad_beraknad
    assert res.butik_flaggor == {"Willys Test": [farsen]}
    # Samma fläskskydd för jämförelsekedjans kampanjer som för korgen
    assert laxen.butik is None and laxen.butik_stoppad == "kampanjvaran innehåller fläsk"
    # Prishistoriken sparas för jämförelsekedjan med produktkod
    sparat = json.loads((data_dir / "priser" / "2026-v44.json").read_text())
    assert {(p["butik"], p["kod"]) for p in sparat} == {("Willys Test", "101_ST"), ("Willys Test", "korv_ST")}

    html = report.render(res)
    assert "inloggad på Hemköp" in html and "Hemköp Test –" in html


def test_butiksflaggor_for_jamforelsekedjan():
    rad = Inkopsrad(vara="lax", behov="1 st", sokord="lax", till=[])
    prod = Product(store="Hemköp Test", code="1_ST", name="Lax", price=100.0)
    val = Val(rad=0, willys_kod="1_ST", willys_antal=1, butik="Willys Test", butik_kod="2_ST", butik_antal=1,
              butik_kostnad_kr=60.0, motivering="")
    lines = [pipeline.Line(row=rad, product=prod, qty=1, willys_cost=100.0, butik=val)]
    cfg = {"butiker": {"e_handel": "hemkop", "willys": W, "hemkop": H}, "optimering": {"min_besparing_for_delning_kr": 30}}
    flaggor, spar, _ = pipeline.tillampa_butikstroskel(lines, pipeline.butikens_troskel(cfg))
    assert spar == {"Willys Test": 40.0} and flaggor["Willys Test"] == lines


def test_prishistorik_for_bada_kedjorna(data_dir):
    def o(store, pris):
        return Offer(store=store, name="Kaffe", brand="", deal="", compare_price="", category="",
                     regular_price="50,00 kr", code="101_ST", promo_qty=1, promo_total=pris)

    for v in ("2026-v41", "2026-v42", "2026-v43"):
        priser.spara(v, [o("Hemköp Test", 45.0), o("Willys Test", 45.0)], data_dir)
    nu = [o("Hemköp Test", 40.0), o("Willys Test", 49.0)]
    priser.markera("2026-v44", nu, data_dir)
    assert [x.prisnotis for x in nu] == ["bra pris", "vanligt pris"]


# ---------- Korg, inloggning och kommandon per kedja ----------

def test_korgen_fylls_i_kedjans_profil(data_dir, monkeypatch):
    from veckohandla import cart

    (data_dir / "2026-v44-korg.json").write_text(json.dumps([{"code": "1_ST", "qty": 1, "pick_unit": "pieces"}]))
    sett = []
    monkeypatch.setattr(cart, "fill_axfood", lambda lines, *a: sett.append(a) or {"total": "1"})
    pipeline.fill_saved_cart("2026-v44", lambda *a: None, "hemkop")
    pipeline.fill_saved_cart("2026-v44", lambda *a: None)
    assert sett == [("hemkop", "Hemköp", "https://www.hemkop.se"), ("willys", "Willys", "https://www.willys.se")]


def test_ej_inloggad_namnger_kedjan(monkeypatch):
    from veckohandla import cart

    class Sida:
        def goto(self, *a, **k):
            pass

        def evaluate(self, js, *a):
            return {"uid": "anonymous"}

    class Ctx:
        def new_page(self):
            return Sida()

    profiler = []

    class Webblasare:
        def __init__(self, nyckel):
            profiler.append(nyckel)

        def __enter__(self):
            return Ctx()

        def __exit__(self, *e):
            pass

    monkeypatch.setattr(cart, "store_browser", Webblasare)
    with pytest.raises(cart.NotLoggedIn, match="Inte inloggad på Hemköp"):
        cart.fill_axfood([], "hemkop", "Hemköp", "https://www.hemkop.se")
    assert profiler == ["hemkop"]


@pytest.fixture
def config(tmp_path, monkeypatch):
    def skriv(butiker):
        p = tmp_path / "config.yaml"
        p.write_text(json.dumps({"butiker": butiker, "hushall": {}}))
        monkeypatch.setenv("VECKOHANDLA_CONFIG", str(p))

    monkeypatch.setattr(huvud, "load_env", lambda: None)
    return skriv


def kor(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["veckohandla", *argv])
    return huvud.main()


def test_login_per_kedja(config, monkeypatch, capsys):
    from veckohandla import browser

    sett = []
    monkeypatch.setattr(browser, "login_axfood", lambda *a: sett.append(a) or "Anna")
    config({"e_handel": "hemkop", "hemkop": H})
    assert kor(monkeypatch, "login") == 0
    config({"willys": W})
    assert kor(monkeypatch, "login") == 0
    assert sett == [("hemkop", "Hemköp", "https://www.hemkop.se"), ("willys", "Willys", "https://www.willys.se")]
    assert "Sessionen är sparad i browser-profiles/hemkop" in capsys.readouterr().out


def test_fyll_varukorg_anvander_e_handel(config, data_dir, monkeypatch):
    (data_dir / "2026-v44-korg.json").write_text("[]")
    sett = []
    monkeypatch.setattr(pipeline, "fill_saved_cart", lambda week, log=print, kedja="willys": sett.append((week, kedja)) or
                        {"tillagda": 0, "redan_klara": 0, "total": "0", "annan_enhet": [], "failed": [], "missing": []})
    config({"e_handel": "hemkop", "hemkop": H})
    assert kor(monkeypatch, "fyll-varukorg") == 0
    assert sett == [("2026-v44", "hemkop")]


def test_hitta_hemkop(config, monkeypatch, capsys):
    mock(monkeypatch, hemkop, {"/axfood/rest/search/store": fixtur_json("hemkop_stores.json")})
    config({"willys": W})
    assert kor(monkeypatch, "hitta-hemkop", "Stockholm") == 0
    out = capsys.readouterr().out
    assert "4127  Hemköp Stockholm Skanstull" in out
