"""Fyll Willys-varukorgen via webbplatsens egna cart-API i en inloggad webbläsarprofil.

Boten lägger bara till det som fattas – den tar aldrig bort något ur korgen och lägger aldrig någon order.
Att köra fyllningen flera gånger ger därför inte dubbla mängder.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .browser import store_browser

_CART_JS = "async () => (await fetch('/axfood/rest/cart')).json()"

# En vara per anrop: skickas en ogiltig vara i samma anrop tappar Willys även giltiga varor
_ADD_JS = """async (products) => {
  const tok = JSON.parse(await (await fetch('/axfood/rest/csrf-token')).text());
  const failed = [];
  for (const p of products) {
    const r = await fetch('/axfood/rest/cart/addProducts', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': tok},
      body: JSON.stringify({products: [p]}),
    });
    if (!r.ok) failed.push(p.productCodePost);
  }
  const cart = await (await fetch('/axfood/rest/cart')).json();
  return {failed, cart};
}"""


class NotLoggedIn(RuntimeError):
    pass


@dataclass
class CartLine:
    code: str
    qty: int
    pick_unit: str = "pieces"
    name: str = ""
    size: str = ""

    @property
    def label(self) -> str:
        """Det som visas i rapport och terminal, t.ex. 'Högrevsfärs 13% Sverige Garant 500g'."""
        return f"{self.name} {self.size}".strip() or self.code


@dataclass
class KorgDiff:
    att_lagga: list[CartLine] = field(default_factory=list)  # qty = det som fattas
    redan_klara: list[CartLine] = field(default_factory=list)
    annan_enhet: list[CartLine] = field(default_factory=list)  # finns redan, men i annan plockenhet


def i_korgen(cart: dict) -> dict[str, tuple[float, str]]:
    """Produktkod -> (antal i plockenhet, plockenhet) ur svaret från GET /axfood/rest/cart.

    `pickQuantity` är antalet i `pickUnit` (8 bananer = 8). `quantity` är gram för lösvikt och
    används därför inte.
    """
    out: dict[str, tuple[float, str]] = {}
    for p in cart.get("products") or []:
        unit = (p.get("pickUnit") or {}).get("code") or "pieces"
        out[p["code"]] = (float(p.get("pickQuantity") or 0), unit)
    return out


def korg_diff(onskat: list[CartLine], cart: dict) -> KorgDiff:
    """Räkna ut vad som behöver läggas till för att korgen ska innehålla minst `onskat`."""
    finns = i_korgen(cart)
    diff = KorgDiff()
    for line in onskat:
        have, unit = finns.get(line.code, (0.0, line.pick_unit))
        if line.code in finns and unit != line.pick_unit:
            diff.annan_enhet.append(line)
        elif have >= line.qty:
            diff.redan_klara.append(line)
        else:
            diff.att_lagga.append(CartLine(line.code, math.ceil(line.qty - have), line.pick_unit, line.name, line.size))
    return diff


def fill_willys(lines: list[CartLine]) -> dict:
    with store_browser("willys") as ctx:
        page = ctx.new_page()
        page.goto("https://www.willys.se/", wait_until="domcontentloaded")
        customer = page.evaluate("async () => (await fetch('/axfood/rest/customer')).json()")
        if customer.get("uid") in (None, "anonymous"):
            raise NotLoggedIn("Inte inloggad på Willys – kör: python -m veckohandla login")

        diff = korg_diff(lines, page.evaluate(_CART_JS))
        payload = [
            {
                "productCodePost": l.code,
                "qty": l.qty,
                "pickUnit": l.pick_unit,
                "hideDiscountToolTip": False,
                "noReplacementFlag": False,
            }
            for l in diff.att_lagga
        ]
        res = page.evaluate(_ADD_JS, payload) if payload else {"failed": [], "cart": page.evaluate(_CART_JS)}

    return sammanfatta(lines, diff, res["failed"], res["cart"])


def sammanfatta(lines: list[CartLine], diff: KorgDiff, failed: list[str], cart: dict) -> dict:
    """Kontrollera att korgen efteråt har minst önskat antal av varje vara och beskriv avvikelser med namn."""
    finns = i_korgen(cart)
    by_code = {l.code: l for l in lines}
    annan = {l.code for l in diff.annan_enhet}
    for_lite = [l for l in lines if l.code not in annan and finns.get(l.code, (0.0, ""))[0] < l.qty]
    return {
        "total": cart.get("totalPrice"),
        "discount": cart.get("totalDiscount"),
        "tillagda": len(diff.att_lagga),
        "redan_klara": len(diff.redan_klara),
        "annan_enhet": [l.label for l in diff.annan_enhet],
        "failed": [by_code[c].label if c in by_code else c for c in failed],  # Willys svarade med fel
        "missing": [l.label for l in for_lite],  # för få i korgen efteråt, oavsett orsak
    }
