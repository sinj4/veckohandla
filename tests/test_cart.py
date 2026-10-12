from veckohandla.cart import CartLine, korg_diff, sammanfatta


def rad(code, pick_qty, unit="pieces", gram=None):
    """Rad som i GET /axfood/rest/cart: pickQuantity i plockenheten, quantity i gram för lösvikt."""
    return {"code": code, "pickQuantity": pick_qty, "pickUnit": {"code": unit, "name": "st"},
            "quantity": gram if gram is not None else pick_qty}


FEJKAD_KORG = {
    "totalPrice": "123,00 kr",
    "products": [
        rad("101203891_ST", 2),                    # högrevsfärs, redan rätt antal
        rad("100254920_KG", 8, gram=1440),         # 8 bananer = 1440 g
        rad("101233933_ST", 1),                    # mjölk, en för lite
        rad("101264066_KG", 1, unit="kilogram"),   # finns i annan plockenhet
        rad("999_ST", 5),                          # användarens egen vara
    ],
}


def test_korg_diff_lagger_bara_till_det_som_fattas():
    onskat = [
        CartLine("101203891_ST", 2, name="Högrevsfärs"),
        CartLine("100254920_KG", 8, name="Banan"),
        CartLine("101233933_ST", 2, name="Mellanmjölk"),
        CartLine("101264066_KG", 1, name="Flankstek"),
        CartLine("100268130_ST", 2, name="Zucchini", size="ca 360g"),
    ]
    d = korg_diff(onskat, FEJKAD_KORG)
    assert [(l.code, l.qty) for l in d.att_lagga] == [("101233933_ST", 1), ("100268130_ST", 2)]
    assert [l.code for l in d.redan_klara] == ["101203891_ST", "100254920_KG"]
    assert [l.code for l in d.annan_enhet] == ["101264066_KG"]
    assert d.att_lagga[1].label == "Zucchini ca 360g"  # namn och storlek följer med


def test_korg_diff_andra_korningen_lagger_inget():
    onskat = [CartLine("101203891_ST", 2), CartLine("100254920_KG", 8)]
    assert korg_diff(onskat, FEJKAD_KORG).att_lagga == []


def test_korg_diff_fler_i_korgen_ror_inget():
    assert korg_diff([CartLine("999_ST", 1)], FEJKAD_KORG).att_lagga == []


def test_korg_diff_tom_korg():
    d = korg_diff([CartLine("A_ST", 3)], {"products": None})
    assert [(l.code, l.qty) for l in d.att_lagga] == [("A_ST", 3)]


def test_sammanfatta_visar_namn_och_kontrollerar_antal():
    onskat = [CartLine("A_ST", 2, name="Ägg", size="6p"), CartLine("B_ST", 3, name="Zucchini"),
              CartLine("C_ST", 1, name="Vitlök Solo", size="ca: 20g")]
    d = korg_diff(onskat, {"products": []})
    efter = {"totalPrice": "99 kr", "products": [rad("A_ST", 2), rad("B_ST", 1)]}
    res = sammanfatta(onskat, d, ["C_ST"], efter)
    assert res["failed"] == ["Vitlök Solo ca: 20g"]
    assert res["missing"] == ["Zucchini", "Vitlök Solo ca: 20g"]  # B fick för lågt antal trots 200
    assert res["tillagda"] == 3


def test_korg_diff_summerar_rader_med_samma_kod():
    # Bananer både i alltid_kop (8) och i ett recept (4); korgen har redan 10
    korg = {"products": [rad("100254920_KG", 10, gram=1800)]}
    onskat = [CartLine("100254920_KG", 8, name="Banan"), CartLine("100254920_KG", 4, name="Banan")]
    d = korg_diff(onskat, korg)
    assert [(l.code, l.qty) for l in d.att_lagga] == [("100254920_KG", 2)]
    assert onskat[0].qty == 8  # originalraderna ändras inte


def test_korg_diff_summerar_inte_olika_plockenheter():
    d = korg_diff([CartLine("X_KG", 2, "pieces"), CartLine("X_KG", 1, "kilogram")], {"products": []})
    assert sorted((l.pick_unit, l.qty) for l in d.att_lagga) == [("kilogram", 1), ("pieces", 2)]


def test_sammanfatta_kontrollerar_summerat_antal():
    onskat = [CartLine("B_ST", 2, name="Banan"), CartLine("B_ST", 2, name="Banan")]
    d = korg_diff(onskat, {"products": []})
    res = sammanfatta(onskat, d, [], {"products": [rad("B_ST", 3)]})
    assert res["missing"] == ["Banan"]  # 3 i korgen räcker inte för 2 + 2
