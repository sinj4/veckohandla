"""Ingredienskontroll av valda Willys-produkter innan korgen sparas.

Namnfiltret (sparrord) missar produkter som inte avslöjar innehållet i namnet – t.ex. Willys
färdiglagade köttbullar ("Gris- och nötkött 73 %"). Här läses ingredienslistan från
/axfood/rest/p/<kod> och jämförs med sparrord + sparrord_ingredienser.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Toppkategorier (första ledet i googleAnalyticsCategory) där saknad ingrediensuppgift ska flaggas
RISK_KATEGORIER = ("kott-chark-och-fagel", "fardigmat")
PAUS_S = 0.5


@dataclass
class Kontroll:
    status: str  # "ok" | "borttagen" | "kontrollera"
    ord: str | None = None  # spärrordet som matchade


def _hamta_willys(code: str) -> dict:
    from .stores import willys

    return willys.product_details(code)


def _detaljer(code: str, cache: dict, hamta: Callable[[str], dict], forsta: list[bool]) -> dict:
    if code not in cache:
        if not forsta[0]:
            time.sleep(PAUS_S)
        forsta[0] = False
        d = hamta(code)
        cache[code] = {
            "ingredients": d.get("ingredients") or "",
            "kategori": (d.get("googleAnalyticsCategory") or "").split("|")[0],
        }
    return cache[code]


def kontrollera(
    codes: list[str],
    ord: list[str],
    cache_path: Path,
    hamta: Callable[[str], dict] = _hamta_willys,
) -> dict[str, Kontroll]:
    """Produktkod -> Kontroll. Svaren cachas per produktkod i cache_path."""
    try:
        cache = json.loads(cache_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    ord = [o.lower() for o in ord if o]
    forsta = [True]
    out: dict[str, Kontroll] = {}
    try:
        for code in dict.fromkeys(codes):
            try:
                d = _detaljer(code, cache, hamta, forsta)
            except Exception:  # nätverk m.m. – osäkert, så flagga i stället för att krascha
                out[code] = Kontroll("kontrollera")
                continue
            text = d["ingredients"].lower()
            if text:
                traff = next((o for o in ord if o in text), None)
                out[code] = Kontroll("borttagen", traff) if traff else Kontroll("ok")
            elif d["kategori"] in RISK_KATEGORIER:
                out[code] = Kontroll("kontrollera")
            else:
                out[code] = Kontroll("ok")
    finally:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return out
