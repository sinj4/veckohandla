"""Ändra värden i en YAML-text och behåll kommentarerna (för config.yaml från config.example.yaml).

Radbaserat och avsett för filer med block-stil som config.example.yaml: en nyckel per rad, två
mellanslags indrag. Resultatet ska alltid kontrolleras med yaml.safe_load.
"""

from __future__ import annotations

import json
import re
import textwrap

_PLAIN = re.compile(r"^[A-Za-zÅÄÖåäöÉé@][\wåäöÅÄÖéÉ@.+/ -]*$")
_SPECIAL = {"true", "false", "yes", "no", "on", "off", "null", "~"}


def _indrag(rad: str) -> int:
    return len(rad) - len(rad.lstrip(" "))


def _innehall(rad: str) -> bool:
    s = rad.strip()
    return bool(s) and not s.startswith("#")


def _block_slut(rader: list[str], start: int, indrag: int) -> int:
    """Index efter nyckelns block: första raden med innehåll eller kommentar på samma eller lägre indrag."""
    i = start + 1
    while i < len(rader):
        if rader[i].strip() and _indrag(rader[i]) <= indrag:
            break
        i += 1
    while i > start + 1 and not rader[i - 1].strip():  # tomma rader hör till nästa nyckel
        i -= 1
    return i


def _hitta(rader: list[str], sokvag: tuple[str, ...]) -> tuple[int, int, int] | None:
    """(rad, blockets slut, indrag) för nyckeln, eller None."""
    start, slut, indrag = -1, len(rader), -2
    for nyckel in sokvag:
        monster = re.compile(rf"^( *){re.escape(nyckel)}:(\s|$)")
        barn_indrag = None
        hittad = None
        for i in range(start + 1, slut):
            if not _innehall(rader[i]):
                continue
            ind = _indrag(rader[i])
            if barn_indrag is None:
                barn_indrag = ind
            if ind != barn_indrag:
                continue
            m = monster.match(rader[i])
            if m:
                hittad = i
                break
        if hittad is None:
            return None
        start, indrag = hittad, barn_indrag
        slut = _block_slut(rader, start, indrag)
    return start, slut, indrag


def _skalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if _PLAIN.match(s) and s.lower() not in _SPECIAL and ": " not in s and " #" not in s:
        return s
    return json.dumps(s, ensure_ascii=False)


def _ar_enkel(v) -> bool:
    return not isinstance(v, (list, dict))


def _rendera(nyckel: str, v, indrag: int, kommentar: str = "") -> list[str]:
    pre = " " * indrag
    if isinstance(v, str) and len(v) > 70:  # lång fritext som folded scalar
        rader = textwrap.wrap(" ".join(v.split()), width=90)
        return [f"{pre}{nyckel}: >\n"] + [f"{pre}  {r}\n" for r in rader]
    if _ar_enkel(v):
        rad = f"{pre}{nyckel}: {_skalar(v)}"
    elif isinstance(v, list) and all(_ar_enkel(x) for x in v):
        rad = f"{pre}{nyckel}: [{', '.join(_skalar(x) for x in v)}]"
    elif isinstance(v, list):
        ut = [f"{pre}{nyckel}:\n"]
        for post in v:
            forsta = True
            for k, x in post.items():
                prefix = f"{pre}  - " if forsta else f"{pre}    "
                ut += [prefix + r.lstrip(" ") if j == 0 else r for j, r in enumerate(_rendera(k, x, indrag + 4))]
                forsta = False
        return ut
    else:
        ut = [f"{pre}{nyckel}:\n"]
        for k, x in v.items():
            ut += _rendera(k, x, indrag + 2)
        return ut
    return [f"{rad}{kommentar}\n"]


def satt(text: str, sokvag: tuple[str, ...], varde) -> str:
    """Sätt värdet för nyckeln. Saknas den läggs den sist i föräldrablocket (föräldern måste finnas)."""
    rader = text.splitlines(keepends=True)
    hittad = _hitta(rader, sokvag)
    if hittad:
        start, slut, indrag = hittad
        kommentar = ""
        if slut == start + 1:  # behåll en kommentar på samma rad (läggs bara till på enradiga värden)
            if m := re.search(r"(\s+#.*)$", rader[start].rstrip("\n")):
                kommentar = m.group(1)
        nya = _rendera(sokvag[-1], varde, indrag, kommentar)
        return "".join(rader[:start] + nya + rader[slut:])
    foralder = _hitta(rader, sokvag[:-1]) if len(sokvag) > 1 else None
    if foralder is None:
        return text.rstrip("\n") + "\n\n" + "".join(_rendera(sokvag[-1], varde, 0))
    start, slut, indrag = foralder
    barn = next((_indrag(r) for r in rader[start + 1:slut] if _innehall(r)), indrag + 2)
    return "".join(rader[:slut] + _rendera(sokvag[-1], varde, barn) + rader[slut:])


def ta_bort(text: str, sokvag: tuple[str, ...]) -> str:
    rader = text.splitlines(keepends=True)
    hittad = _hitta(rader, sokvag)
    if not hittad:
        return text
    start, slut, _ = hittad
    return "".join(rader[:start] + rader[slut:])
