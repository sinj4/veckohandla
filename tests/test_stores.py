import httpx
import pytest

from veckohandla.stores import http, ica, willys

from .conftest import fixtur_json, fixtur_text


def sok_item(code: str) -> dict:
    return next(i for i in fixtur_json("willys_search.json")["results"] if i["code"] == code)


# ---------- Willys ----------

def test_to_product_styckvara_med_mangdkampanj():
    p = willys._to_product(sok_item("100268130_ST"), "W")  # zucchini, "2 för 15,00"
    assert p.extra["pickUnit"] == "pieces"
    assert "weight_kg" not in p.extra
    assert p.price == 11.9
    assert (p.promo_qty, p.promo_total) == (2, 15.0)  # sök-API:t anger styckpris i objekt
    assert p.promo_max == 5
    assert p.cost(2) == 15.0


def test_to_product_losvikt_per_styck():
    p = willys._to_product(sok_item("100147388_KG"), "W")  # ingefära "ca: 120g"
    assert p.extra["pickUnit"] == "pieces"
    assert p.extra["weight_kg"] == pytest.approx(0.12)
    assert p.price == pytest.approx(59.9 * 0.12, abs=0.01)  # kr/kg omräknat till styckpris
    assert p.promo_total == pytest.approx(39.9 * 0.12, abs=0.01)


def test_to_product_losvikt_per_kg():
    p = willys._to_product(sok_item("100150587_KG"), "W")  # potatis utan "ca"-vikt
    assert p.extra["pickUnit"] == "kilogram"
    assert "weight_kg" not in p.extra


def test_piece_weight():
    assert willys._piece_weight_kg("ca: 120g") == pytest.approx(0.12)
    assert willys._piece_weight_kg("ca: 1.2kg") == pytest.approx(1.2)
    assert willys._piece_weight_kg("ca 360g") == pytest.approx(0.36)
    assert willys._piece_weight_kg("500g") is None
    assert willys._piece_weight_kg(None) is None


def _mock_client(monkeypatch, routes: dict[str, dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=routes[request.url.path])

    monkeypatch.setattr(
        willys, "_client",
        lambda: httpx.Client(base_url=willys.BASE, transport=httpx.MockTransport(handler)),
    )


def test_willys_fetch_offers(monkeypatch):
    _mock_client(monkeypatch, {"/search/campaigns/online": fixtur_json("willys_campaigns_online.json")})
    offers = willys.fetch_offers("0000", "Willys Test")
    assert len(offers) == 3
    assert {o.store for o in offers} == {"Willys Test"}
    assert offers[1].category.startswith("halsa-och-skonhet")
    assert all(o.deal == o.deal.strip() and o.deal for o in offers)


def test_willys_search(monkeypatch):
    _mock_client(monkeypatch, {"/search": fixtur_json("willys_search.json")})
    produkter = willys.search("vad som helst", "W")
    assert [p.code for p in produkter][:3] == ["100268130_ST", "100147388_KG", "100150587_KG"]


# ---------- ICA ----------

def test_js_object_tal_undefined_och_map():
    html = fixtur_text("ica_erbjudanden.html")
    data = ica._js_object(html, "window.__INITIAL_DATA__ = ")
    assert data["generic"]["isOspAvailable"] is None
    assert data["products"]["values"] is None
    assert len(data["offers"]["weeklyOffers"]) == 3


def test_js_object_saknad_markor():
    with pytest.raises(ValueError):
        ica._js_object("<html></html>", "window.__INITIAL_DATA__ = ")


def test_ica_fetch_offers(monkeypatch):
    monkeypatch.setattr(ica, "_get", lambda url: fixtur_text("ica_erbjudanden.html"))
    offers = ica.fetch_offers("ica-test-1", "ICA Test")
    assert [o.name for o in offers] == ["Äpplen i påse", "Salami Milano, Napoili", "Hushållsduk"]
    assert offers[1].deal.startswith("2 för 35 kr")
    assert offers[2].category == "Hem & fritid"
    assert offers[0].regular_price


# ---------- Omförsök ----------

def _svar(*steg):
    it = iter(steg)

    def anrop():
        x = next(it)
        if isinstance(x, Exception):
            raise x
        return httpx.Response(x, request=httpx.Request("GET", "https://example.test"))

    return anrop


def test_omforsok_vid_natverksfel_och_5xx(monkeypatch):
    pauser = []
    monkeypatch.setattr(http, "_sleep", pauser.append)
    r = http.med_omforsok(_svar(httpx.ConnectTimeout("t"), 503, 200))
    assert r.status_code == 200
    assert pauser == [2, 5]


def test_inget_omforsok_vid_4xx(monkeypatch):
    pauser = []
    monkeypatch.setattr(http, "_sleep", pauser.append)
    with pytest.raises(httpx.HTTPStatusError):
        http.med_omforsok(_svar(404, 200))
    assert pauser == []


def test_ger_upp_efter_tre_forsok(monkeypatch):
    monkeypatch.setattr(http, "_sleep", lambda s: None)
    with pytest.raises(httpx.HTTPStatusError):
        http.med_omforsok(_svar(500, 502, 503))


def test_js_object_tal_mellanslag():
    html = '<script>window.X = {"a": undefined, "b": [1, undefined ], "c": new Map([])};</script>'
    assert ica._js_object(html, "window.X = ") == {"a": None, "b": [1, None], "c": None}


def test_tolka_promo_med_tomt_prisobjekt():
    # Riktig post (Potatisbröd): price-objektet saknar value
    pr = {"price": {"currencyIso": None, "value": None}, "qualifyingCount": None, "rewardLabel": "24,90/st"}
    assert willys._tolka_promo(pr, None) is None
    o = willys._to_offer({"code": "X_ST", "name": "Potatisbröd", "potentialPromotions": [pr]}, "W")
    assert o.promo_qty is None and o.kostnad(1) is None
