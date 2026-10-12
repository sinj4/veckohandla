from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass
class Offer:
    """En veckokampanj från en butik (butikens erbjudandesida)."""

    store: str
    name: str
    brand: str
    deal: str  # t.ex. "2 för 35 kr", "21,90/st"
    compare_price: str
    category: str
    regular_price: str = ""
    online: bool | None = None

    def short(self) -> str:
        brand = f" ({self.brand})" if self.brand else ""
        reg = f", ord. {self.regular_price}" if self.regular_price else ""
        return f"{self.name}{brand}: {self.deal} [{self.compare_price}{reg}]"


@dataclass
class Product:
    """En vara i e-handelns sortiment med pris och ev. kampanj."""

    store: str
    code: str  # Willys: productCode, ICA: retailerProductId
    name: str
    price: float  # ordinarie styckpris
    compare_price: str = ""
    size: str = ""
    promo_qty: int | None = None  # "2 för 48" -> 2
    promo_total: float | None = None  # "2 för 48" -> 48.0
    promo_text: str = ""
    promo_max: int | None = None  # max antal kampanjköp per hushåll
    url: str = ""
    extra: dict = field(default_factory=dict)

    def cost(self, qty: int) -> float:
        """Kostnad för qty st med hänsyn till mängdkampanj."""
        if self.promo_qty and self.promo_total is not None:
            bundles, rest = divmod(qty, self.promo_qty)
            if self.promo_max is not None and bundles > self.promo_max:
                rest += (bundles - self.promo_max) * self.promo_qty
                bundles = self.promo_max
            return round(bundles * self.promo_total + rest * self.price, 2)
        return round(qty * self.price, 2)

    def best_qty(self, qty: int) -> int:
        """Höj antalet till kampanjtröskeln om det inte kostar mer per behov (t.ex. 1 st á 30 vs 2 för 30)."""
        if self.promo_qty and self.promo_total is not None and qty % self.promo_qty:
            up = math.ceil(qty / self.promo_qty) * self.promo_qty
            if self.cost(up) <= self.cost(qty) + 0.01:
                return up
        return qty

    def describe(self) -> str:
        promo = f" KAMPANJ: {self.promo_text}" if self.promo_text else ""
        unit = " per st (lösvikt, uppskattat)" if "weight_kg" in self.extra else ""
        if self.extra.get("pickUnit") == "kilogram":
            unit = " per kg (antal = kg)"
        return f"[{self.code}] {self.name} {self.size} – {self.price:.2f} kr{unit} ({self.compare_price}){promo}"


_MAX = re.compile(r"max\s*(\d+)\s*(?:köp|erbj|st)", re.I)


def parse_promo_max(text: str) -> int | None:
    m = _MAX.search(text or "")
    return int(m.group(1)) if m else None
