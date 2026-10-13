"""Uppskattat lager för varor som alltid går åt (hushall.gar_alltid_at med per_vecka).

Underlaget är de senaste <vecka>-korg.json. De visar vad som planerades, inte vad som faktiskt köptes
eller åts – det duger som uppskattning.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

VECKOR_BAKAT = 4
_ENHETER_I_NAMN = re.compile(r"(\d+)\s*(?:p|st|-?pack)\b", re.I)
_TAL = re.compile(r"(\d+(?:[.,]\d+)?)")


@dataclass
class GarAlltidAt:
    vara: str
    per_vecka: float | None = None  # vad hushållet gör av med totalt per vecka, inte bara till middagarna


def las_gar_alltid_at(poster: list) -> list[GarAlltidAt]:
    """hushall.gar_alltid_at: antingen namn ("ägg") eller {vara: ägg, per_vecka: 12}."""
    out = []
    for p in poster or []:
        if isinstance(p, dict):
            out.append(GarAlltidAt(str(p["vara"]), p.get("per_vecka")))
        elif p:
            out.append(GarAlltidAt(str(p)))
    return out


def matchar(text: str, post: GarAlltidAt) -> bool:
    """Samma regel som när inköpsrader märks GÅR ALLTID ÅT: ordet finns i texten."""
    return post.vara.lower() in (text or "").lower()


def matchande_post(text: str, poster: list[GarAlltidAt]) -> GarAlltidAt | None:
    return next((p for p in poster if matchar(text, p)), None)


def antal_i_behov(behov: str) -> float | None:
    """'6 st' -> 6, '4' -> 4; None om inget tal finns."""
    m = _TAL.search(behov or "")
    return float(m.group(1).replace(",", ".")) if m else None


def enheter_i_rad(rad: dict) -> float | None:
    """Enheter per förpackning ur korgraden: sparat fält, annars ur namn/storlek (t.ex. '24p')."""
    if rad.get("enheter"):
        return float(rad["enheter"])
    m = _ENHETER_I_NAMN.search(f"{rad.get('name', '')} {rad.get('size', '')}")
    return float(m.group(1)) if m else None


def _mandag(vecka: str) -> dt.date:
    ar, v = vecka.split("-v")
    return dt.date.fromisocalendar(int(ar), int(v), 1)


def _veckor_mellan(fran: str, till: str) -> int:
    return (_mandag(till) - _mandag(fran)).days // 7


def kopt(rader: list[dict], post: GarAlltidAt, log=None) -> float:
    """Köpta enheter av varan i en korgfil. Nya filer har gar_alltid_at per rad; äldre matchas på namnet."""
    summa = 0.0
    for r in rader:
        traff = r["gar_alltid_at"] == post.vara if "gar_alltid_at" in r else matchar(r.get("name", ""), post)
        if not traff:
            continue
        enheter = enheter_i_rad(r)
        if enheter is None:
            if log:
                log(f"  Lager: kan inte räkna enheter för {r.get('name')!r} – hoppar över raden")
            continue
        summa += r.get("qty", 0) * enheter
    return summa


def uppskattat_lager(post: GarAlltidAt, korgar: list[tuple[str, list[dict]]], nu: str, log=None) -> float | None:
    """Följ lagret vecka för vecka: + köpt, − per_vecka för varje vecka som går (aldrig under 0).

    `korgar` är (vecka, korgrader) för tidigare veckor. None om per_vecka saknas eller inget köpts.
    """
    if not post.per_vecka:
        return None
    lager, forra = 0.0, None
    nagot = False
    for vecka, rader in sorted(korgar):
        if forra is not None:
            lager = max(0.0, lager - post.per_vecka * _veckor_mellan(forra, vecka))
        k = kopt(rader, post, log)
        nagot = nagot or k > 0
        lager += k
        forra = vecka
    if not nagot or forra is None:
        return None
    return max(0.0, lager - post.per_vecka * _veckor_mellan(forra, nu))


def senaste_korgar(data: Path, nu: str, antal: int = VECKOR_BAKAT) -> list[tuple[str, list[dict]]]:
    """De `antal` senaste korgfilerna före veckan `nu`."""
    filer = sorted(f for f in data.glob("*-v[0-9][0-9]-korg.json") if f.stem.removesuffix("-korg") < nu)
    out = []
    for f in filer[-antal:]:
        try:
            out.append((f.stem.removesuffix("-korg"), json.loads(f.read_text())))
        except (json.JSONDecodeError, OSError):
            continue
    return out
