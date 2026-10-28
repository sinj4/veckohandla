"""Minifiera bokmarke/bokmarke.js till en javascript:-URL för bokmärket (README) och skriv ut den.

Tar bort blockkommentarer, helradskommentarer och radbrytningar. Skriptet skrivs därför med semikolon och
utan kommentarer efter kod på samma rad; testerna kör både källan och den minifierade versionen.

    python verktyg/bokmarke_url.py            # javascript:-URL
    python verktyg/bokmarke_url.py --kod      # minifierad kod (för iPhone-genvägen)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote

KALLA = Path(__file__).resolve().parent.parent / "bokmarke" / "bokmarke.js"
# Tecken som får stå okodade i URL:en; resten (mellanslag, %, å/ä/ö, emoji) procentkodas
SAKRA = "!*'();:@&=+$,/?#[]{}<>|.~-_\"^`\\"


def minifiera(kod: str) -> str:
    kod = re.sub(r"/\*.*?\*/", "", kod, flags=re.S)
    rader = [r.strip() for r in kod.splitlines()]
    return " ".join(r for r in rader if r and not r.startswith("//"))


def javascript_url(kod: str | None = None) -> str:
    return "javascript:" + quote(minifiera(kod if kod is not None else KALLA.read_text()), safe=SAKRA)


if __name__ == "__main__":
    print(minifiera(KALLA.read_text()) if "--kod" in sys.argv else javascript_url())
