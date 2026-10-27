"""Prishistorik: veckans kampanjer sparas kompakt i data/priser/<vecka>.json och jämförs med tidigare veckor.

En kampanj är "bra pris" om kampanjpriset per styck är minst 15 % under medianen av ordinarie pris de
senaste 8 veckorna, och "vanligt pris" om det ligger inom 5 % av medianen. Med färre än 3 veckors
historik för varan görs ingen markering.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from .models import Offer, parse_kr

BRA_PRIS = "bra pris"
VANLIGT_PRIS = "vanligt pris"

HISTORIK_VECKOR = 8
MIN_VECKOR = 3
BRA_GRANS = 0.15  # minst 15 % under medianen
VANLIGT_GRANS = 0.05  # inom 5 % av medianen

_AXFOOD_KOD = re.compile(r"_(ST|KG)$")
_ICA_FOR = re.compile(r"^\s*(\d+)\s*för\s*(\d+(?:[,.]\d+)?)\s*kr\b", re.IGNORECASE)
_ICA_ST = re.compile(r"^\s*(\d+(?:[,.]\d+)?)\s*kr/st\b", re.IGNORECASE)


def produktkod(o: Offer) -> str:
    """Axfood-produktkod (Willys, Hemköp – samma koder). ICA:s kod är ett erbjudande-id som byts varje vecka och räknas inte."""
    return o.code if _AXFOOD_KOD.search(o.code) else ""


def nyckel(butik: str, kod: str, namn: str, varumarke: str) -> str:
    """Samma vara över veckor: produktkoden om den finns, annars namn och varumärke."""
    return f"{butik}|{kod}" if kod else f"{butik}|{namn.strip().lower()}|{varumarke.strip().lower()}"


def kampanjpris(o: Offer) -> float | None:
    """Kampanjpris per styck, eller None om det inte går att jämföra med ordinarie styckpris.

    Viktvaror (Willys _KG, ICA kr/kg) hoppas över: kampanj och ordinarie pris kan ha olika enhet.
    """
    if o.code.endswith("_KG"):
        return None
    if o.promo_qty and o.promo_total is not None:
        return round(o.promo_total / o.promo_qty, 2)
    if m := _ICA_FOR.match(o.deal):
        return round(float(m.group(2).replace(",", ".")) / int(m.group(1)), 2)
    if m := _ICA_ST.match(o.deal):
        return float(m.group(1).replace(",", "."))
    return None


def _post(o: Offer) -> dict:
    post = {"butik": o.store, "kod": produktkod(o), "namn": o.name, "kampanjpris": kampanjpris(o),
            "ordinarie": parse_kr(o.regular_price), "jamforpris": o.compare_price}
    if o.brand:
        post["varumarke"] = o.brand
    return post


def katalog(data: Path) -> Path:
    return data / "priser"


def spara(week: str, offers: list[Offer], data: Path) -> Path:
    d = katalog(data)
    d.mkdir(parents=True, exist_ok=True)
    fil = d / f"{week}.json"
    fil.write_text(json.dumps([_post(o) for o in offers], ensure_ascii=False, separators=(",", ":")))
    return fil


def historik(week: str, data: Path) -> dict[str, list[float]]:
    """Ordinarie pris per vara ur de senaste 8 veckorna före `week` (en notering per vecka)."""
    filer = [f for f in sorted(katalog(data).glob("*-v[0-9][0-9].json")) if f.stem < week][-HISTORIK_VECKOR:]
    priser: dict[str, list[float]] = {}
    for f in filer:
        sett = set()
        for p in json.loads(f.read_text()):
            k = nyckel(p["butik"], p.get("kod") or "", p["namn"], p.get("varumarke") or "")
            if p.get("ordinarie") is not None and k not in sett:
                sett.add(k)
                priser.setdefault(k, []).append(p["ordinarie"])
    return priser


def bedom(pris: float | None, ordinarie: list[float]) -> str:
    """'bra pris', 'vanligt pris' eller '' (ingen markering)."""
    if pris is None or len(ordinarie) < MIN_VECKOR:
        return ""
    median = statistics.median(ordinarie)
    if median <= 0:
        return ""
    if pris <= median * (1 - BRA_GRANS):
        return BRA_PRIS
    if abs(pris - median) <= median * VANLIGT_GRANS:
        return VANLIGT_PRIS
    return ""


def markera(week: str, offers: list[Offer], data: Path) -> list[Offer]:
    """Sätt prisnotis på veckans kampanjer utifrån historiken. Returnerar de markerade."""
    hist = historik(week, data)
    markerade = []
    for o in offers:
        o.prisnotis = bedom(kampanjpris(o), hist.get(nyckel(o.store, produktkod(o), o.name, o.brand), []))
        if o.prisnotis:
            markerade.append(o)
    return markerade
