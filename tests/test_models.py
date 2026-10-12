from veckohandla.models import Product, parse_promo_max


def produkt(**kw) -> Product:
    return Product(store="W", code="X_ST", name="X", **kw)


def test_cost_utan_kampanj():
    assert produkt(price=12.5).cost(3) == 37.5


def test_cost_mangdkampanj():
    p = produkt(price=11.9, promo_qty=2, promo_total=15.0)
    assert p.cost(1) == 11.9
    assert p.cost(2) == 15.0
    assert p.cost(3) == 26.9  # en kampanjomgång + en till ordinarie pris


def test_cost_med_promo_max():
    p = produkt(price=29.55, promo_qty=2, promo_total=48.0, promo_max=1)
    assert p.cost(2) == 48.0
    assert p.cost(4) == 48.0 + 2 * 29.55  # bara en kampanjomgång per hushåll


def test_best_qty_hojer_till_kampanj_som_inte_kostar_mer():
    p = produkt(price=30.0, promo_qty=2, promo_total=30.0)
    assert p.best_qty(1) == 2


def test_best_qty_hojer_inte_om_det_blir_dyrare():
    p = produkt(price=29.55, promo_qty=2, promo_total=48.0)
    assert p.best_qty(1) == 1
    assert produkt(price=10.0).best_qty(3) == 3


def test_best_qty_respekterar_promo_max():
    # Utöver första kampanjomgången kostar varan ordinarie pris – ingen anledning att höja
    p = produkt(price=20.0, promo_qty=2, promo_total=20.0, promo_max=1)
    assert p.best_qty(1) == 2
    assert p.best_qty(3) == 3


def test_parse_promo_max():
    assert parse_promo_max("2 för 48 kr -- Max 1 erbj/hushåll") == 1
    assert parse_promo_max("Max 5 köp") == 5
    assert parse_promo_max("Max 2 köp/hushåll") == 2
    assert parse_promo_max("2 för 26,00") is None
