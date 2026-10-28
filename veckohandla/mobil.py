"""Mobillänkar: korgen som `#veckohandla=`-länk för bokmärket, och signerade veckolänkar till mobilsidan.

Korglänken: https://www.willys.se/#veckohandla=<data> (eller www.hemkop.se), där <data> är base64url av en
kompakt JSON med kod, antal och plockenhet per rad plus reserver. Bokmärket (bokmarke/bokmarke.js) läser den
på kedjans webbplats och lägger till det som fattas i korgen. Länken innehåller inga hemligheter.

Veckolänken: <MOBIL_ADRESS>/?v=<vecka>&t=<HMAC-SHA256(LANKNYCKEL, "veckohandla:<vecka>")>. Mobilsidan godtar
den bara för den veckan (och veckan efter), och bara för val, betyg och status. Själva nyckeln lämnar aldrig
Workern eller GitHub-secrets.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from urllib.parse import urlencode

# Länken ska fungera i mejlappar och som adress i mobilens webbläsare; 4000 tecken räcker för ca 30 rader
# med en reserv var (korta fältnamn) och för ca 80 rader utan reserver
MAX_LANGD = 4000
ENHETER = {"pieces": "p", "kilogram": "k"}


class ForLangLank(ValueError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _rad(rad: dict, korta: bool, reserver: bool) -> dict:
    kod, antal, enhet = rad["code"], rad["qty"], rad.get("pick_unit", "pieces")
    if korta:
        ut = {"k": kod, "a": antal, "e": ENHETER.get(enhet, enhet)}
        if reserver and rad.get("reserver"):
            ut["r"] = [_rad(r, True, False) for r in rad["reserver"]]
    else:
        ut = {"kod": kod, "antal": antal, "enhet": enhet}
        if reserver and rad.get("reserver"):
            ut["reserver"] = [_rad(r, False, False) for r in rad["reserver"]]
    return ut


def korg_lank(korg: list[dict], kedja: str, base: str) -> str:
    """Länk som bokmärket fyller korgen från. `korg` är raderna i data/<vecka>-korg.json.

    Blir länken för lång kortas fältnamnen, och sedan utelämnas reserverna. Räcker inte det kastas
    ForLangLank.
    """
    for korta, reserver in ((False, True), (True, True), (True, False)):
        rader = [_rad(r, korta, reserver) for r in korg]
        data = {"v": 1, "s": kedja, "r": rader} if korta else {"version": 1, "kedja": kedja, "rader": rader}
        kodat = _b64url(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
        lank = f"{base}/#veckohandla={kodat}"
        if len(lank) <= MAX_LANGD:
            return lank
    raise ForLangLank(f"Korglänken blir {len(lank)} tecken även utan reserver (max {MAX_LANGD})")


def avkoda(lank: str) -> dict:
    """Data ur en korglänk (för tester och felsökning)."""
    kodat = lank.split("#veckohandla=", 1)[1]
    return json.loads(base64.urlsafe_b64decode(kodat + "=" * (-len(kodat) % 4)))


def token(nyckel: str, vecka: str) -> str:
    return _b64url(hmac.new(nyckel.encode(), f"veckohandla:{vecka}".encode(), hashlib.sha256).digest())


def vecklank(adress: str, nyckel: str, vecka: str, vy: str) -> str:
    """Signerad länk till mobilsidan för en vecka, t.ex. vy="valj" eller "betyg"."""
    return f"{adress.rstrip('/')}/?{urlencode({'v': vecka, 't': token(nyckel, vecka), 'vy': vy})}"


def vecklankar_fran_miljo(vecka: str) -> dict[str, str] | None:
    """{'valj': …, 'betyg': …} om MOBIL_ADRESS och LANKNYCKEL finns, annars None (då visas inga knappar)."""
    adress, nyckel = os.environ.get("MOBIL_ADRESS"), os.environ.get("LANKNYCKEL")
    if not adress or not nyckel:
        return None
    return {vy: vecklank(adress, nyckel, vecka, vy) for vy in ("valj", "betyg")}
