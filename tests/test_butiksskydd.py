"""Butikslistorna (Willys i butik och ICA) går genom samma fläskskydd som korgen."""

import pytest

from veckohandla import pipeline, report
from veckohandla.models import Offer, Product
from veckohandla.planner import Inkopsrad, Produktval, Val, Veckoplan

I_BUTIK = "Willys Test (i butik)"
CFG = {"claude": {"model": "x"},
       "butiker": {"willys": {"namn": "Willys Test", "store_id": "1"}, "ica": []},
       "hushall": {"sparrord": ["gris", "bacon"], "sparrord_ingredienser": ["skinka"]},
       "optimering": {"min_besparing_for_delning_kr": 0, "min_besparing_willys_i_butik_kr": 0}}

KAMPANJER = [
    Offer(store=I_BUTIK, name="Köttbullar", brand="", deal="49,90/st", compare_price="", category="fardigmat|kottbullar",
          regular_price="69,90 kr", code="BULLAR_BUTIK", promo_qty=1, promo_total=49.9),
    Offer(store=I_BUTIK, name="Nötfärs", brand="", deal="79,90/st", compare_price="", category="kott-chark-och-fagel|kott",
          regular_price="99,90 kr", code="FARS_BUTIK", promo_qty=1, promo_total=79.9),
    Offer(store=I_BUTIK, name="Tacochips", brand="", deal="2 för 22,00", compare_price="", category="skafferi|chips",
          regular_price="12,50 kr", code="CHIPS_BUTIK", promo_qty=2, promo_total=22.0),
    Offer(store=I_BUTIK, name="Bacon skivat", brand="", deal="25,00/st", compare_price="", category="kott-chark-och-fagel|chark",
          regular_price="35,00 kr", code="BACON_BUTIK", promo_qty=1, promo_total=25.0),
    Offer(store="ICA X", name="Kassler", brand="", deal="59 kr/st", compare_price="", category="Färskvaror",
          code="ICA_KASSLER", kategori_id=6),
    Offer(store="ICA X", name="Äpplen", brand="", deal="10 kr/st", compare_price="", category="Frukt & Grönt",
          code="ICA_APPLE", kategori_id=4),
]
SIDOR = {  # /axfood/rest/p/<kod>: None = 404
    "BULLAR_BUTIK": {"ingredients": "Gris- och nötkött 73 %", "googleAnalyticsCategory": "fardigmat|kottbullar"},
    "FARS_BUTIK": None, "CHIPS_BUTIK": None,
}


def e_handel(code):
    return Product(store="W", code=code, name=f"E-handel {code}", price=200.0, size="1 st")


class Planerare:
    menyns_kampanjer: list = []

    def __init__(self, *a):
        pass

    def plan_week(self, offers, cfg, prev):
        Planerare.menyns_kampanjer = list(offers)
        rader = [Inkopsrad(vara=v, behov="1 st", sokord=v, till=["Måndag"])
                 for v in ("köttbullar", "nötfärs", "tacochips", "kassler", "äpplen")]
        return Veckoplan(middagar=[], inkopslista=rader, kommentar="")

    def choose_products(self, rows, cands, butiker, undvik, gar_alltid_at=None):
        val = lambda i, butik, kod, kr: Val(rad=i, willys_kod=f"E{i}_ST", willys_antal=1, butik=butik, butik_kod=kod,
                                           butik_erbjudande="enligt Claude", butik_antal=1, butik_kostnad_kr=kr, motivering="")
        return Produktval(val=[val(0, I_BUTIK, "BULLAR_BUTIK", 49.9), val(1, I_BUTIK, "FARS_BUTIK", 79.9),
                               val(2, I_BUTIK, "CHIPS_BUTIK", 11.0), val(3, "ICA X", "ICA_KASSLER", 59.0),
                               val(4, "ICA X", "ICA_APPLE", 10.0)])


class Session:
    butik_vald = True

    def search(self, q, store_name):
        i = ["köttbullar", "nötfärs", "tacochips", "kassler", "äpplen"].index(q)
        return [e_handel(f"E{i}_ST")]

    def kolla(self, code):
        if code in SIDOR:
            d = SIDOR[code]
            return (None, None) if d is None else (False, d)  # finns inte i e-handeln
        return True, {"ingredients": "nötkött", "googleAnalyticsCategory": "kott-chark-och-fagel|x"}


@pytest.fixture
def korning(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: list(KAMPANJER))
    monkeypatch.setattr(pipeline, "Planner", Planerare)
    res = pipeline._run(CFG, Session(), False, log=lambda *a: None)
    return res, {l.row.vara: l for l in res.lines}


def test_butiksalternativ_med_sparrord_i_ingredienserna_tas_bort(korning):
    res, rader = korning
    bullar = rader["köttbullar"]
    assert bullar.butik is None and not bullar.flaggad
    assert bullar.i_korgen and bullar.product.code == "E0_ST"  # e-handelsvaran ligger kvar
    assert bullar.butik_stoppad == "kampanjvaran innehåller gris"
    assert "Inte i butik: kampanjvaran innehåller gris" in report.render(res)
    assert bullar not in res.butik_flaggor[I_BUTIK]


def test_butiksvara_utan_ingredienser_i_kottkategori_flaggas(korning):
    res, rader = korning
    assert rader["nötfärs"].flaggad and rader["nötfärs"].butik_kontrollera
    assert rader["tacochips"].flaggad and not rader["tacochips"].butik_kontrollera  # 404 men inte kött


def test_ica_rad_i_kottkategori_far_kontrollera_ingredienser(korning):
    res, rader = korning
    assert rader["kassler"].butik_kontrollera
    assert not rader["äpplen"].butik_kontrollera
    html = report.render(res)
    kasslerrad = html[html.index("på ICA X"):].split("</tr>")[0]
    assert "Kontrollera ingredienserna i butiken" in kasslerrad
    applerad = html[html.index("E-handel E4_ST"):].split("</tr>")[0]
    assert "Kontrollera" not in applerad


def test_namnfiltret_kor_pa_butikskampanjer_fore_menyplaneringen(korning):
    namn = [o.name for o in Planerare.menyns_kampanjer]
    assert "Bacon skivat" not in namn  # spärrordet "bacon" i namnet
    assert "Köttbullar" in namn  # fångas först av ingredienskontrollen


# ---------- Punkt 2: validering av butiksvalet och tröskel per butik ----------

def _kor_med_val(data_dir, monkeypatch, val_fn, cfg=CFG, kampanjer=KAMPANJER):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda c, v: list(kampanjer))

    class P(Planerare):
        def choose_products(self, rows, cands, butiker, undvik, gar_alltid_at=None):
            return Produktval(val=[val_fn(i) for i in range(len(rows))])

    monkeypatch.setattr(pipeline, "Planner", P)
    return pipeline._run(cfg, Session(), False, log=lambda *a: None)


def _val(i, butik=None, kod=None, antal=1, kr=10.0):
    return Val(rad=i, willys_kod=f"E{i}_ST", willys_antal=1, butik=butik, butik_kod=kod,
               butik_erbjudande="enligt Claude", butik_antal=antal, butik_kostnad_kr=kr, motivering="")


@pytest.mark.parametrize("butik,kod,antal", [
    (I_BUTIK, "FINNS_INTE", 1),        # okänd kod
    ("ICA X", "FARS_BUTIK", 1),        # koden hör till en annan butik
    (I_BUTIK, None, 1),                # kod saknas
    (I_BUTIK, "FARS_BUTIK", 0),        # antal saknas
])
def test_ogiltigt_butiksval_ignoreras_med_varning(data_dir, monkeypatch, butik, kod, antal):
    res = _kor_med_val(data_dir, monkeypatch, lambda i: _val(i, butik, kod, antal) if i == 1 else _val(i))
    farsrad = res.lines[1]
    assert farsrad.butik is None and not farsrad.flaggad and farsrad.i_korgen and farsrad.product.code == "E1_ST"
    assert any("Ogiltigt butiksval för nötfärs" in v and repr(kod) in v for v in res.varningar)
    assert "Ogiltigt butiksval för nötfärs" in report.render(res)


def _troskel_cfg(troskel=40):
    return {**CFG, "butiker": {"willys": {"namn": "Willys Test", "store_id": "1"}, "ica": []},
            "hushall": {"sparrord": []}, "optimering": {"min_besparing_willys_i_butik_kr": troskel}}



def _billigare_i_butik(kod):
    # e-handeln kostar 200 kr; kampanjen räknas i koden till 175 kr -> sparar 25 kr per rad
    return Offer(store=I_BUTIK, name=kod, brand="", deal="175,00/st", compare_price="", category="skafferi",
                 regular_price="200,00 kr", code=kod, promo_qty=1, promo_total=175.0)


def test_troskeln_galler_butikens_summa(data_dir, monkeypatch):
    kampanjer = [_billigare_i_butik("K1"), _billigare_i_butik("K2")]
    val2 = lambda i: _val(i, I_BUTIK, f"K{i + 1}") if i < 2 else _val(i)
    res = _kor_med_val(data_dir, monkeypatch, val2, cfg=_troskel_cfg(), kampanjer=kampanjer)
    assert [l.row.vara for l in res.butik_flaggor[I_BUTIK]] == ["köttbullar", "nötfärs"]  # 2 × 25 = 50 ≥ 40
    assert res.butik_besparing[I_BUTIK] == 50.0

    val1 = lambda i: _val(i, I_BUTIK, "K1") if i == 0 else _val(i)
    res = _kor_med_val(data_dir, monkeypatch, val1, cfg=_troskel_cfg(), kampanjer=kampanjer)
    assert res.butik_flaggor == {} and not res.lines[0].flaggad and res.lines[0].i_korgen  # 25 < 40


def test_butikskostnad_over_max_utan_ordinarie_pris_blir_uppskattad(data_dir, monkeypatch):
    kampanj = Offer(store=I_BUTIK, name="Tacochips", brand="", deal="2 för 22,00 (Max 1 köp)", compare_price="",
                    category="skafferi", regular_price="", code="CHIPS2", promo_qty=2, promo_total=22.0, promo_max=1)
    assert kampanj.kostnad(4) is None  # två kampanjomgångar men max 1 och okänt ordinarie pris
    res = _kor_med_val(data_dir, monkeypatch, lambda i: _val(i, I_BUTIK, "CHIPS2", antal=4, kr=60.0) if i == 0 else _val(i),
                       cfg=_troskel_cfg(0), kampanjer=[kampanj])
    rad = res.lines[0]
    assert rad.flaggad and rad.butik.butik_kostnad_kr == 60.0 and not rad.butik.butik_kostnad_beraknad
    assert "60,00 kr (uppskattat)" in report.render(res)


# ---------- Korgen är komplett ----------

def test_flaggade_rader_ligger_anda_i_korgfilen(korning, data_dir):
    import json

    res, rader = korning
    assert rader["nötfärs"].flaggad and rader["kassler"].flaggad
    korg = {k["code"] for k in json.loads((data_dir / f"{res.week}-korg.json").read_text())}
    assert korg == {"E0_ST", "E1_ST", "E2_ST", "E3_ST", "E4_ST"}  # alla rader, även de flaggade
    html = report.render(res)
    assert "<b>ICA X</b>: spar" in html and "ta bort Kassler och Äpplen ur korgen" in html
    assert f"<h2>Korgen: {res.willys_total:,.2f} kr".replace(",", " ").replace(".", ",") in html


def test_rad_utan_willys_produkt_hamnar_under_kop_i_butik(data_dir, monkeypatch):
    import json

    def val(i):
        if i == 3:  # kassler finns bara på ICA
            return Val(rad=i, willys_kod=None, willys_antal=1, butik="ICA X", butik_kod="ICA_KASSLER",
                       butik_erbjudande="Kassler 59 kr/st", butik_antal=1, butik_kostnad_kr=59.0, motivering="")
        return _val(i)

    res = _kor_med_val(data_dir, monkeypatch, val, cfg={**CFG, "optimering": {"min_besparing_for_delning_kr": 1000}})
    kassler = res.lines[3]
    assert kassler.kop_i_butik and not kassler.i_korgen
    assert [l.row.vara for l in res.kop_i_butik["ICA X"]] == ["kassler"]  # trots tröskel 1000
    assert res.kop_i_butik_total == 59.0
    html = report.render(res)
    assert "<h2>Köp i butik – ICA X</h2>" in html and "kassler: Kassler 59 kr/st × 1 ≈ 59,00 kr (uppskattat)" in html
    assert "Plus köp i butik: ca 59,00 kr" in html
    korg = {k["code"] for k in json.loads((data_dir / f"{res.week}-korg.json").read_text())}
    assert "E3_ST" not in korg and len(korg) == 4
