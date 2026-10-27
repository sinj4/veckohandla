"""Betyg på ätna rätter i data/betyg.json: [{ratt, vecka, betyg: 1 | -1, kommentar?}].

Planeraren får de 15 senaste gillade rätterna ("gärna liknande") och alla ogillade ("undvik och liknande").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

MAX_GILLADE = 15


@dataclass
class Smak:
    gillade: list[dict] = field(default_factory=list)  # senaste först
    ogillade: list[dict] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.gillade or self.ogillade)


def fil(data: Path) -> Path:
    return data / "betyg.json"


def las(data: Path) -> list[dict]:
    f = fil(data)
    return json.loads(f.read_text()) if f.exists() else []


def satt(data: Path, ratt: str, vecka: str, betyg: int, kommentar: str = "") -> None:
    """Sätt (eller ändra) betyget för en rätt en viss vecka."""
    if betyg not in (1, -1):
        raise ValueError("Betyget måste vara +1 eller -1")
    poster = [p for p in las(data) if not (p["ratt"] == ratt and p["vecka"] == vecka)]
    post = {"ratt": ratt, "vecka": vecka, "betyg": betyg}
    if kommentar.strip():
        post["kommentar"] = kommentar.strip()
    data.mkdir(parents=True, exist_ok=True)
    fil(data).write_text(json.dumps(poster + [post], ensure_ascii=False, indent=2))


def smak(data: Path) -> Smak:
    """Senaste betyget per rätt avgör; gillade begränsas till de 15 senaste."""
    senaste: dict[str, dict] = {}
    for p in sorted(las(data), key=lambda p: p["vecka"]):  # stabil: senare poster samma vecka vinner
        senaste[p["ratt"].strip().lower()] = p
    poster = sorted(senaste.values(), key=lambda p: p["vecka"], reverse=True)
    return Smak(gillade=[p for p in poster if p["betyg"] > 0][:MAX_GILLADE],
                ogillade=[p for p in poster if p["betyg"] < 0])


def text(poster: list[dict]) -> str:
    """'Tacos (barnen älskade den), Lax i ugn'"""
    return ", ".join(p["ratt"] + (f" ({p['kommentar']})" if p.get("kommentar") else "") for p in poster)
