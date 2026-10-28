import httpx
import pytest

from veckohandla.stores import http, willys

from .conftest import fixtur_json


@pytest.fixture(autouse=True)
def ingen_paus(monkeypatch):
    monkeypatch.setattr(http, "_sleep", lambda s: None)


def mock_willys(aktiv_butik="0000", saknas=()):
    anrop = []

    def handler(req: httpx.Request) -> httpx.Response:
        anrop.append((req.method, req.url.path, dict(req.url.params)))
        path = req.url.path
        if path == "/axfood/rest/csrf-token":
            return httpx.Response(200, json="tok-123")
        if path == "/axfood/rest/v2/store/activate":
            assert req.headers["X-CSRF-Token"] == "tok-123"
            return httpx.Response(200, json={})
        if path == "/axfood/rest/v2/store/active":
            return httpx.Response(200, json={"storeId": aktiv_butik})
        if path == "/search":
            return httpx.Response(200, json=fixtur_json("willys_search.json"))
        if path.startswith("/axfood/rest/p/"):
            code = path.rsplit("/", 1)[1]
            if code in saknas:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"code": code, "outOfStock": code.startswith("SLUT"), "ingredients": ""})
        return httpx.Response(500)

    client = httpx.Client(base_url=willys.BASE, transport=httpx.MockTransport(handler))
    return willys.WillysSession("0000", client=client), anrop


def test_butik_valjs_en_gang_och_ateranvands():
    sess, anrop = mock_willys()
    with sess:
        sess.search("kyckling", "W")
        sess.search("vitlök", "W")
        sess.product_details("100268130_ST")
        sess.tillganglig("100268130_ST")
    activate = [a for a in anrop if a[1] == "/axfood/rest/v2/store/activate"]
    assert len(activate) == 1
    assert activate[0][0] == "POST" and activate[0][2]["storeId"] == "0000"
    # Butiken väljs innan första sökningen
    assert [a[1] for a in anrop].index("/axfood/rest/v2/store/active") < [a[1] for a in anrop].index("/search")
    assert sum(1 for a in anrop if a[1] == "/search") == 2


def test_fel_butik_stoppar():
    sess, _ = mock_willys(aktiv_butik="9999")
    with sess, pytest.raises(willys.ButiksvalMisslyckades):
        sess.search("kyckling", "W")


def test_tillganglig():
    sess, _ = mock_willys(saknas={"100026936_KG"})
    with sess:
        assert sess.tillganglig("100764898_ST") is True
        assert sess.tillganglig("100026936_KG") is False  # 404 = finns inte i butiken
        assert sess.tillganglig("SLUT_ST") is False  # outOfStock


def test_tillganglig_okand_vid_503_och_natverksfel():
    def handler(req):
        p = req.url.path
        if p == "/axfood/rest/csrf-token":
            return httpx.Response(200, json="t")
        if p == "/axfood/rest/v2/store/activate":
            return httpx.Response(200, json={})
        if p == "/axfood/rest/v2/store/active":
            return httpx.Response(200, json={"storeId": "0000"})
        if p == "/axfood/rest/p/NERE_ST":
            return httpx.Response(503)
        if p == "/axfood/rest/p/TIMEOUT_ST":
            raise httpx.ConnectTimeout("t")
        return httpx.Response(404)

    c = httpx.Client(base_url=willys.BASE, transport=httpx.MockTransport(handler))
    with willys.WillysSession("0000", client=c) as sess:
        assert sess.tillganglig("NERE_ST") is None  # efter omförsöken: okänt, ingen krasch
        assert sess.tillganglig("TIMEOUT_ST") is None
        assert sess.tillganglig("SAKNAS_ST") is False  # 404 betyder som förut att varan inte finns
