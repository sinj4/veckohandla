"""Fyll Willys-varukorgen via webbplatsens egna cart-API i en inloggad webbläsarprofil.

Boten lägger bara till varor – den rör inte befintligt innehåll och lägger aldrig någon order.
"""

from __future__ import annotations

from dataclasses import dataclass

from .browser import store_browser

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
  return {failed,
          total: cart.totalPrice,
          discount: cart.totalDiscount,
          codes: (cart.products || []).map(p => p.code)};
}"""


class NotLoggedIn(RuntimeError):
    pass


@dataclass
class CartLine:
    code: str
    qty: int
    pick_unit: str = "pieces"


def fill_willys(lines: list[CartLine]) -> dict:
    with store_browser("willys") as ctx:
        page = ctx.new_page()
        page.goto("https://www.willys.se/", wait_until="domcontentloaded")
        customer = page.evaluate("async () => (await fetch('/axfood/rest/customer')).json()")
        if customer.get("uid") in (None, "anonymous"):
            raise NotLoggedIn("Inte inloggad på Willys – kör: python -m veckohandla login")
        payload = [
            {
                "productCodePost": l.code,
                "qty": l.qty,
                "pickUnit": l.pick_unit,
                "hideDiscountToolTip": False,
                "noReplacementFlag": False,
            }
            for l in lines
        ]
        res = page.evaluate(_ADD_JS, payload)
        missing = [l.code for l in lines if l.code not in res["codes"]]
        return {"total": res["total"], "discount": res["discount"], "missing": missing}
