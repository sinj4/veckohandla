"""Kontroll av installationen: config, butiker, kampanjer, Claude, SMTP, inloggning och data/.

Gör inga Claude-anrop och ändrar ingenting. Varje kontroll ger ✓, ✗ (med vad man ska göra) eller ℹ️ (notis).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
import yaml

OK, FEL, NOTIS = "ok", "fel", "notis"


@dataclass
class Punkt:
    status: str  # OK, FEL eller NOTIS
    text: str
    atgard: str = ""

    def rad(self) -> str:
        tecken = {OK: "✓", FEL: "✗", NOTIS: "ℹ️"}[self.status]
        return f"{tecken} {self.text}" + (f"\n    → {self.atgard}" if self.atgard else "")


# ---------- config ----------

def las_config(path: Path) -> tuple[dict | None, Punkt]:
    """Finns config.yaml och är den giltig?"""
    from . import pipeline
    from .__main__ import menylage
    from .planner import matlador

    if not path.exists():
        return None, Punkt(FEL, f"{path} saknas", "Kör: python -m veckohandla init")
    try:
        cfg = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        return None, Punkt(FEL, f"{path} är inte giltig YAML ({e})", "Rätta filen eller kör init igen")
    try:
        h = cfg["hushall"]
        for nyckel in ("vuxna", "middagar_per_vecka", "portioner_per_middag", "preferenser"):
            h[nyckel]
        pipeline.e_handel(cfg)
        butik = pipeline.e_handel_butik(cfg)
        butik["namn"], butik["store_id"]
        cfg["epost"]["till"]
        cfg["claude"]["model"]
        matlador(h)
        menylage(cfg)
    except KeyError as e:
        return None, Punkt(FEL, f"{path}: nyckeln {e} saknas", "Jämför med config.example.yaml eller kör init igen")
    except (ValueError, TypeError) as e:
        return None, Punkt(FEL, f"{path}: {e}", "Rätta filen eller kör init igen")
    return cfg, Punkt(OK, f"{path} finns och är giltig")


# ---------- butiker och kampanjer ----------

def e_handelsbutik(cfg: dict) -> Punkt:
    """Går e-handelsbutiken att välja i en anonym session (samma butiksval som veckokörningen)?"""
    from . import pipeline

    kedja, butik = pipeline.kedjemodul(cfg), pipeline.e_handel_butik(cfg)
    namn = f"{kedja.KEDJA.namn}-butiken {butik['namn']} ({butik['store_id']})"
    try:
        with kedja.session(butik["store_id"]) as sess:
            sess.valj_butik()
    except Exception as e:
        return Punkt(FEL, f"{namn} gick inte att välja: {e}",
                     f"Hitta rätt store_id: python -m veckohandla hitta-{kedja.KEDJA.nyckel} <ort>")
    return Punkt(OK, f"{namn} finns")


def _ar_403(e: Exception) -> bool:
    return isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403


def kampanjer(cfg: dict) -> list[Punkt]:
    """Hämta kampanjerna per butik, som veckokörningen gör. 403 från ICA är en notis, inte ett fel."""
    from . import pipeline
    from .stores import ica

    punkter = []

    def prova(namn: str, hamta: Callable[[], list], ica_butik: bool = False) -> None:
        try:
            n = len(hamta())
        except Exception as e:
            if ica_butik and _ar_403(e):
                punkter.append(Punkt(NOTIS, f"{namn}: {pipeline.ICA_LOKALT}"))
            else:
                punkter.append(Punkt(FEL, f"{namn}: kampanjerna gick inte att hämta ({e})",
                                     "Kontrollera butiken i config.yaml och nätverket"))
            return
        if n:
            punkter.append(Punkt(OK, f"{namn}: {n} kampanjer"))
        else:
            punkter.append(Punkt(FEL, f"{namn}: inga kampanjer", "Kontrollera butiken i config.yaml"))

    kedja, butik = pipeline.kedjemodul(cfg), pipeline.e_handel_butik(cfg)
    prova(butik["namn"], lambda: kedja.fetch_offers(butik["store_id"], butik["namn"]))
    if butik.get("i_butik", True):
        i_butik = pipeline.willys_i_butik_namn(cfg)
        prova(i_butik, lambda: kedja.fetch_offers(butik["store_id"], i_butik, kanal="offline"))
    for nyckel, c in pipeline.jamforelsekedjor(cfg):
        prova(c["namn"], lambda c=c, nyckel=nyckel: pipeline.KEDJOR[nyckel].fetch_offers(c["store_id"], c["namn"], kanal="offline"))
    for s in cfg["butiker"].get("ica") or []:
        if s.get("bara_lokalt") and pipeline.i_molnet():
            punkter.append(Punkt(NOTIS, f"{s['namn']}: hämtas inte i molnet (bara_lokalt) – {pipeline.ICA_LOKALT}"))
            continue
        prova(s["namn"], lambda s=s: ica.fetch_offers(s["erbjudande_slug"], s["namn"]), ica_butik=True)
    return punkter


# ---------- Claude ----------

def claude_bin() -> str | None:
    """Samma ordning som planeraren: CLAUDE_BIN, claude i PATH, ~/.local/bin/claude."""
    for kandidat in (os.environ.get("CLAUDE_BIN"), shutil.which("claude"), str(Path.home() / ".local/bin/claude")):
        if kandidat and Path(kandidat).exists():
            return kandidat
    return None


def claude_status(exe: str) -> tuple[str, dict]:
    """(version, auth-status) via `claude --version` och `claude auth status --json` – inga modellanrop."""
    v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
    version = (v.stdout or v.stderr).strip() or "okänd"
    a = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=60)
    try:
        status = json.loads(a.stdout)
    except json.JSONDecodeError:
        status = {}
    return version, status


def claude() -> Punkt:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Punkt(OK, "ANTHROPIC_API_KEY finns – Anthropic API används (betalas per token)")
    exe = claude_bin()
    if exe is None:
        return Punkt(FEL, "Varken Claude Code eller ANTHROPIC_API_KEY hittades",
                     "Installera Claude Code (npm install -g @anthropic-ai/claude-code) och logga in med "
                     "`claude`, eller lägg ANTHROPIC_API_KEY i .env")
    try:
        version, status = claude_status(exe)
    except (OSError, subprocess.SubprocessError) as e:
        return Punkt(FEL, f"Claude Code ({exe}) gick inte att köra: {e}", "Installera om Claude Code")
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or status.get("loggedIn"):
        konto = f", {status['subscriptionType']}" if status.get("subscriptionType") else ""
        return Punkt(OK, f"Claude Code {version} ({exe}), inloggad{konto}")
    return Punkt(FEL, f"Claude Code {version} ({exe}) är inte inloggad",
                 "Kör `claude` och logga in med ditt Pro- eller Max-konto (eller lägg ANTHROPIC_API_KEY i .env)")


# ---------- SMTP, inloggning, data ----------

def smtp() -> Punkt:
    if os.environ.get("SMTP_PASSWORD"):
        return Punkt(OK, "SMTP-lösenord finns")
    return Punkt(FEL, "SMTP_PASSWORD saknas – rapporten kan inte mejlas",
                 "Lägg app-lösenordet i .env (SMTP_PASSWORD=…), eller kör init igen. "
                 "Gmail: https://myaccount.google.com/apppasswords")


def inloggning(cfg: dict, profiler: Path) -> Punkt:
    """Läser /axfood/rest/customer i kedjans sparade webbläsarprofil (headless, ingen korg rörs)."""
    from . import pipeline

    k = pipeline.kedjemodul(cfg).KEDJA
    atgard = "Kör: python -m veckohandla login"
    if not (profiler / k.nyckel).exists():
        return Punkt(FEL, f"Ingen sparad {k.namn}-inloggning ({profiler / k.nyckel})", atgard)
    try:
        uid = inloggad_som(k.nyckel, k.base)
    except Exception as e:
        return Punkt(FEL, f"{k.namn}-inloggningen gick inte att kontrollera: {e}", atgard)
    if uid in (None, "anonymous"):
        return Punkt(FEL, f"{k.namn}-inloggningen har gått ut", atgard)
    return Punkt(OK, f"Inloggad hos {k.namn}")


def inloggad_som(nyckel: str, base: str) -> str | None:
    from .browser import store_browser

    with store_browser(nyckel) as ctx:
        page = ctx.new_page()
        page.goto(f"{base}/", wait_until="domcontentloaded")
        return page.evaluate("async () => (await fetch('/axfood/rest/customer')).json()").get("uid")


def data_skrivbar(data: Path) -> Punkt:
    """Skrivbar utan att skriva något: katalogen själv, eller närmaste befintliga förälder."""
    finns = data
    while not finns.exists() and finns != finns.parent:
        finns = finns.parent
    if finns.is_dir() and os.access(finns, os.W_OK | os.X_OK):
        return Punkt(OK, f"{data} är skrivbar" + ("" if data.exists() else " (skapas vid första körningen)"))
    return Punkt(FEL, f"{data} är inte skrivbar", "Ändra rättigheterna eller sätt VECKOHANDLA_DATA")


# ---------- hela kontrollen ----------

def kor(config: Path, data: Path, profiler: Path, med_inloggning: bool = True, skriv=print) -> int:
    """Skriv checklistan. Returnerar 0 om inget är fel, annars 1."""
    punkter: list[Punkt] = []

    def visa(p: Punkt) -> None:
        punkter.append(p)
        skriv(p.rad())

    skriv("Kontrollerar installationen …\n")
    cfg, p = las_config(config)
    visa(p)
    if cfg is not None:
        visa(e_handelsbutik(cfg))
        for p in kampanjer(cfg):
            visa(p)
    visa(claude())
    visa(smtp())
    if cfg is not None and med_inloggning:
        visa(inloggning(cfg, profiler))
    elif cfg is not None:
        visa(Punkt(NOTIS, "Inloggningen kontrollerades inte (--utan-inloggning)"))
    visa(data_skrivbar(data))
    fel = sum(p.status == FEL for p in punkter)
    if not fel:
        skriv("\nAllt ser bra ut.")
    else:
        skriv(f"\n{fel} {'sak' if fel == 1 else 'saker'} att åtgärda.")
    return 1 if fel else 0
