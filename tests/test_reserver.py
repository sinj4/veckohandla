from veckohandla.cart import CartLine, fyll_korg
from veckohandla.ingredienser import Kontroll
from veckohandla.models import Product
from veckohandla.pipeline import Alternativ, godkanda_reserver, provningsordning, valj_alternativ
from veckohandla.planner import Reserv, Val


def prod(code, price=10.0, **kw):
    return Product(store="W", code=code, name=f"Vara {code}", price=price, size="500g", **kw)


KANDIDATER = [prod("A_ST", 20.0), prod("B_ST", 12.0, promo_qty=2, promo_total=12.0), prod("C_ST", 15.0), prod("D_ST")]


def val(huvud="A_ST", antal=1, reserver=(("B_ST", 1), ("C_ST", 2))):
    return Val(rad=0, willys_kod=huvud, willys_antal=antal, ica_butik=None, motivering="",
               willys_reserver=[Reserv(kod=k, antal=a) for k, a in reserver])


# ---------- prövningsordning ----------

def test_provningsordning_huvudval_sedan_reserver_med_best_qty():
    alt = provningsordning(val(), KANDIDATER)
    assert [(a.product.code, a.qty) for a in alt] == [("A_ST", 1), ("B_ST", 2), ("C_ST", 2)]  # B höjs till "2 för 12" (kostar inte mer än 1 st)


def test_provningsordning_hoppar_over_okanda_koder_och_dubbletter_max_3():
    v = val(reserver=(("X_ST", 1), ("A_ST", 1), ("B_ST", 1), ("C_ST", 1), ("D_ST", 1)))
    # Högst 3 reserver tas från modellen; X finns inte bland kandidaterna och A är redan huvudval
    assert [a.product.code for a in provningsordning(v, KANDIDATER)] == ["A_ST", "B_ST"]


def test_provningsordning_utan_val():
    assert provningsordning(None, KANDIDATER) == []
    assert provningsordning(val(huvud=None), KANDIDATER) == []


# ---------- valj_alternativ ----------

def ingr(stoppade: dict[str, str]):
    anrop = []

    def kontroll(code):
        anrop.append(code)
        return Kontroll("borttagen", stoppade[code]) if code in stoppade else Kontroll("ok")

    return kontroll, anrop


def test_huvudval_med_404_ger_reserv():
    alt = provningsordning(val(), KANDIDATER)
    kontroll, anrop = ingr({})
    valt, bort, _, _ = valj_alternativ(alt, lambda c: c != "A_ST", kontroll)
    assert valt.product.code == "B_ST" and valt.qty == 2
    assert [(a.product.code, o) for a, o in bort] == [("A_ST", "finns inte i butiken")]
    assert anrop == ["B_ST"]  # ingredienser hämtas inte för varan som inte finns


def test_huvudval_borttaget_av_ingrediens_ger_reserv():
    alt = provningsordning(val(), KANDIDATER)
    kontroll, anrop = ingr({"A_ST": "gris"})
    valt, bort, _, _ = valj_alternativ(alt, lambda c: True, kontroll)
    assert valt.product.code == "B_ST"
    assert [(a.product.code, o) for a, o in bort] == [("A_ST", "innehåller gris")]
    assert anrop == ["A_ST", "B_ST"]  # C prövas aldrig – ingredienser bara när de behövs


def test_alla_alternativ_faller_bort():
    alt = provningsordning(val(), KANDIDATER)
    kontroll, _ = ingr({"B_ST": "skinka"})
    valt, bort, _, _ = valj_alternativ(alt, lambda c: c != "A_ST" and c != "C_ST", kontroll)
    assert valt is None
    assert [o for _, o in bort] == ["finns inte i butiken", "innehåller skinka", "finns inte i butiken"]


def test_kontrollera_flagga_foljer_valt_alternativ():
    alt = provningsordning(val(), KANDIDATER)
    valt, _, kolla, _ = valj_alternativ(alt, lambda c: True, lambda c: Kontroll("kontrollera"))
    assert valt.product.code == "A_ST" and kolla is True


def test_utan_sparrord_kontrolleras_bara_tillganglighet():
    alt = provningsordning(val(), KANDIDATER)
    valt, _, _, _ = valj_alternativ(alt, lambda c: True, None)
    assert valt.product.code == "A_ST"


def test_godkanda_reserver_filtrerar_pa_ingredienser():
    reserver = [Alternativ(prod("B_ST"), 1), Alternativ(prod("C_ST"), 1)]
    kontroll, _ = ingr({"B_ST": "gris"})
    assert [r.product.code for r in godkanda_reserver(reserver, kontroll)] == ["C_ST"]


# ---------- reserv vid failed när korgen fylls ----------

class FejkadWillys:
    """Fejkad korg: nekar koderna i `nekar`, annars läggs varan till."""

    def __init__(self, nekar=(), start=None):
        self.nekar = set(nekar)
        self.rader = dict(start or {})
        self.anrop: list[list[str]] = []

    def cart(self):
        return {"totalPrice": "1 kr", "products": [
            {"code": c, "pickQuantity": q, "pickUnit": {"code": "pieces"}} for c, q in self.rader.items()]}

    def lagg_till(self, payload):
        self.anrop.append([p["productCodePost"] for p in payload])
        failed = []
        for p in payload:
            if p["productCodePost"] in self.nekar:
                failed.append(p["productCodePost"])
            else:
                self.rader[p["productCodePost"]] = self.rader.get(p["productCodePost"], 0) + p["qty"]
        return {"failed": failed, "cart": self.cart()}


def test_reserv_provas_nar_willys_nekar():
    w = FejkadWillys(nekar={"A_ST", "B_ST"})
    rad = CartLine("A_ST", 1, name="Vitlök Solo", reserver=[CartLine("B_ST", 1, name="Vitlök Kapsel"),
                                                          CartLine("C_ST", 2, name="Vitlök 250g"),
                                                          CartLine("D_ST", 1, name="Vitlök Fläta")])
    res = fyll_korg([rad, CartLine("E_ST", 1, name="Ägg")], w.cart, w.lagg_till)
    assert w.anrop == [["A_ST", "E_ST"], ["B_ST"], ["C_ST"]]  # en gång per reserv, D behövs aldrig
    assert w.rader == {"E_ST": 1, "C_ST": 2}
    assert res["byten"] == ["Vitlök Solo → Vitlök 250g"]
    assert res["failed"] == [] and res["missing"] == []


def test_alla_reserver_nekas():
    w = FejkadWillys(nekar={"A_ST", "B_ST"})
    rad = CartLine("A_ST", 1, name="Vitlök Solo", reserver=[CartLine("B_ST", 1, name="Vitlök Kapsel")])
    res = fyll_korg([rad], w.cart, w.lagg_till)
    assert res["byten"] == []
    assert res["failed"] == ["Vitlök Solo"]
    assert res["missing"] == ["Vitlök Solo"]


def test_reserv_som_redan_ligger_i_korgen_laggs_inte_till_igen():
    w = FejkadWillys(nekar={"A_ST"}, start={"B_ST": 1})
    rad = CartLine("A_ST", 1, name="Vitlök Solo", reserver=[CartLine("B_ST", 1, name="Vitlök Kapsel")])
    res = fyll_korg([rad], w.cart, w.lagg_till)
    assert w.anrop == [["A_ST"]]
    assert res["byten"] == ["Vitlök Solo → Vitlök Kapsel"]


# ---------- hela _run med fejkad planerare och session ----------

def test_run_byter_till_reserv_och_sparar_reserver(data_dir, monkeypatch):
    import json

    from veckohandla import pipeline
    from veckohandla.planner import Inkopsrad, Produktval, Veckoplan

    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: [])

    class FejkPlanerare:
        def __init__(self, *a):
            pass

        def plan_week(self, *a):
            rader = [Inkopsrad(vara=v, behov="1 st", sokord=v, till=["Måndag"]) for v in ("vitlök", "köttbullar", "ost")]
            return Veckoplan(middagar=[], inkopslista=rader, kommentar="")

        def choose_products(self, rows, cands, ica, undvik):
            return Produktval(val=[
                Val(rad=0, willys_kod="SOLO_KG", willys_antal=1, ica_butik=None, motivering="",
                    willys_reserver=[Reserv(kod="KAPSEL_ST", antal=1), Reserv(kod="FLATA_ST", antal=1)]),
                Val(rad=1, willys_kod="BULLAR_ST", willys_antal=1, ica_butik=None, motivering="", willys_reserver=[]),
                Val(rad=2, willys_kod="OST_ST", willys_antal=1, ica_butik=None, motivering="",
                    willys_reserver=[Reserv(kod="SKINKOST_ST", antal=1)]),
            ])

    class FejkSession:
        butik_vald = True
        sortiment = {"vitlök": ["SOLO_KG", "KAPSEL_ST", "FLATA_ST"], "köttbullar": ["BULLAR_ST"], "ost": ["OST_ST", "SKINKOST_ST"]}
        ingredienser = {"BULLAR_ST": "Gris- och nötkött", "SKINKOST_ST": "ost, skinka"}

        def search(self, q, store_name):
            return [prod(c) for c in self.sortiment[q]]

        def tillganglig(self, code):
            return code != "SOLO_KG"

        def product_details(self, code):
            return {"ingredients": self.ingredienser.get(code, "")}

    monkeypatch.setattr(pipeline, "Planner", FejkPlanerare)
    cfg = {"claude": {"model": "x"}, "butiker": {"willys": {"namn": "Willys Test", "store_id": "1"}, "ica": []},
           "hushall": {"sparrord": ["gris"], "sparrord_ingredienser": ["skinka"]},
           "optimering": {"min_besparing_for_delning_kr": 75}}
    res = pipeline._run(cfg, FejkSession(), False, log=lambda *a: None)

    vitlok, bullar, ost = res.lines
    assert vitlok.product.code == "KAPSEL_ST" and vitlok.bytt
    assert [(a.product.code, o) for a, o in vitlok.bortvalda] == [("SOLO_KG", "finns inte i butiken")]
    assert bullar.product is None and "innehåller gris" in bullar.borttagen  # köp manuellt
    assert ost.product.code == "OST_ST" and ost.reserver == []  # skinkosten klarar inte kontrollen

    korg = json.loads((data_dir / f"{res.week}-korg.json").read_text())
    assert [k["code"] for k in korg] == ["KAPSEL_ST", "OST_ST"]
    assert [r["code"] for r in korg[0]["reserver"]] == ["FLATA_ST"]

    from veckohandla import report
    html = report.render(res)
    assert "Bytt: Vara SOLO_KG 500g → Vara KAPSEL_ST 500g (finns inte i butiken)" in html
    assert "Köp manuellt" in html
