"""Ingredienskontroll av valda Willys-produkter innan korgen sparas.

Namnfiltret (sparrord) missar produkter som inte avslöjar innehållet i namnet – t.ex. Willys
färdiglagade köttbullar ("Gris- och nötkött 73 %"). Här läses ingredienslistan från
/axfood/rest/p/<kod> och jämförs med sparrord + sparrord_ingredienser.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Toppkategorier (första ledet i googleAnalyticsCategory) där saknad ingrediensuppgift ska flaggas
RISK_KATEGORIER = ("kott-chark-och-fagel", "fardigmat")
PAUS_S = 0.5
MAX_ALDER_DAGAR = 30  # ingredienslistor kan ändras – hämta på nytt efter så här många dagar


@dataclass
class Kontroll:
    status: str  # "ok" | "borttagen" | "kontrollera"
    ord: str | None = None  # spärrordet som matchade


def _hamta_willys(code: str) -> dict:
    from .stores import willys

    return willys.product_details(code)


class Ingredienskontroll:
    """Kontrollerar en produkt i taget – ingredienser hämtas först när en produkt faktiskt prövas.

    Cachen läses en gång och skrivs med spara() (eller när with-blocket lämnas).
    """

    def __init__(
        self,
        ord: list[str],
        cache_path: Path,
        hamta: Callable[[str], dict] = _hamta_willys,
        idag: dt.date | None = None,
    ):
        self.ord = [o.lower() for o in ord if o]
        self.idag = idag or dt.date.today()
        self.cache_path = cache_path
        self.hamta = hamta
        self._forsta = True
        try:
            self.cache = json.loads(cache_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}

    def __enter__(self) -> Ingredienskontroll:
        return self

    def __exit__(self, *exc) -> None:
        self.spara()

    def spara(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1))

    def _farsk(self, post: dict | None) -> bool:
        """Poster utan hämtningsdatum räknas som gamla."""
        try:
            hamtad = dt.date.fromisoformat(post["hamtad"])
        except (TypeError, KeyError, ValueError):
            return False
        return (self.idag - hamtad).days < MAX_ALDER_DAGAR

    def _detaljer(self, code: str) -> dict:
        if not self._farsk(self.cache.get(code)):
            if not self._forsta:
                time.sleep(PAUS_S)
            self._forsta = False
            d = self.hamta(code)
            self.cache[code] = {
                "ingredients": d.get("ingredients") or "",
                "kategori": (d.get("googleAnalyticsCategory") or "").split("|")[0],
                "hamtad": self.idag.isoformat(),
            }
        return self.cache[code]

    def kontrollera(self, code: str) -> Kontroll:
        try:
            d = self._detaljer(code)
        except Exception:  # nätverk m.m. – osäkert, så flagga i stället för att krascha
            return Kontroll("kontrollera")
        text = d["ingredients"].lower()
        if text:
            traff = next((o for o in self.ord if o in text), None)
            return Kontroll("borttagen", traff) if traff else Kontroll("ok")
        if d["kategori"] in RISK_KATEGORIER:
            return Kontroll("kontrollera")
        return Kontroll("ok")


def kontrollera(
    codes: list[str],
    ord: list[str],
    cache_path: Path,
    hamta: Callable[[str], dict] = _hamta_willys,
) -> dict[str, Kontroll]:
    """Produktkod -> Kontroll för flera produkter. Svaren cachas per produktkod i cache_path."""
    with Ingredienskontroll(ord, cache_path, hamta) as k:
        return {code: k.kontrollera(code) for code in dict.fromkeys(codes)}
