from __future__ import annotations

import datetime as dt
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
    code: str = ""  # produktkod (Willys) eller erbjudande-id (ICA)
    kategori_id: int | None = None  # ICA: expandedArticleGroupId
    start: dt.date | None = None  # kampanjens startdatum (Willys butikskampanjer har det)
    size: str = ""
    # Tolkad kampanj (Willys), för att räkna kostnad i koden i stället för att låta Claude uppskatta
    promo_qty: int | None = None
    promo_total: float | None = None
    promo_max: int | None = None
    prisnotis: str = ""  # "bra pris" / "vanligt pris" ur prishistoriken (priser.py), annars tom

    def kostnad(self, antal: int) -> float | None:
        """Kostnad för `antal` st enligt kampanjen, eller None om kampanjen inte går att tolka.

        Utöver max per hushåll gäller ordinarie pris; saknas det kan kostnaden inte räknas.
        """
        if not self.promo_qty or self.promo_total is None or antal < 1:
            return None
        ordinarie = parse_kr(self.regular_price)
        p = Product(store=self.store, code=self.code, name=self.name, price=ordinarie or 0.0,
                    promo_qty=self.promo_qty, promo_total=self.promo_total, promo_max=self.promo_max)
        kampanj_st = antal - antal % self.promo_qty
        if self.promo_max is not None:
            kampanj_st = min(kampanj_st, self.promo_max * self.promo_qty)
        if antal > kampanj_st and ordinarie is None:
            return None  # delvis ordinarie pris, men det priset är okänt
        return p.cost(antal)

    def short(self) -> str:
        brand = f" ({self.brand})" if self.brand else ""
        reg = f", ord. {self.regular_price}" if self.regular_price else ""
        notis = f" – {self.prisnotis.upper()}" if self.prisnotis else ""
        return f"{self.name}{brand}: {self.deal} [{self.compare_price}{reg}]{notis}"


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
    jamfor_varde: float | None = None  # ordinarie jämförpris, t.ex. 2.50
    jamfor_enhet: str = ""  # t.ex. "st", "kg", "l"

    @property
    def enheter_per_forpackning(self) -> float | None:
        """Ordinarie pris / ordinarie jämförpris, t.ex. 72 kr / 3,00 kr/st = 24 st.

        Jämförpriset är avrundat (59,90 / 2,50 = 23,96), så styckvaror avrundas till heltal.
        """
        if self.jamfor_varde and self.price > 0:
            n = self.price / self.jamfor_varde
            return float(max(1, round(n))) if self.jamfor_enhet == "st" else n
        return None

    def effektivt_enhetspris(self, antal: int) -> float | None:
        """Pris per enhet för det antal som faktiskt köps, med mängdkampanj och max per hushåll.

        Jämförpriset från en "2 för"-kampanj gäller bara om man köper kampanjantalet – det här gör inte.
        """
        n = self.enheter_per_forpackning
        if not n or antal < 1:
            return None
        return round(self.cost(antal) / (antal * n), 4)

    @property
    def jamforpris(self) -> float | None:
        """Jämförpris per enhet; gäller en kampanj räknas det på kampanjpriset."""
        if self.jamfor_varde is None:
            return None
        if self.promo_qty and self.promo_total is not None and self.price > 0:
            return round(self.jamfor_varde * (self.promo_total / self.promo_qty) / self.price, 2)
        return self.jamfor_varde

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


_KR = re.compile(r"(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)")


def parse_kr(text: str | None) -> float | None:
    """'27,90 kr' -> 27.9, '1 049,00 kr' -> 1049.0; None om inget pris finns."""
    m = _KR.search(text or "")
    if not m:
        return None
    return float(m.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "."))
