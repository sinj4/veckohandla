"""Claude-anrop: 1) sätt ihop veckomeny från kampanjerna, 2) välj produkter och butik per inköpsrad."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from .models import Offer, Product


# ---------- Steg 1: veckomeny ----------

class Ingrediens(BaseModel):
    namn: str
    mangd: str = Field(description="Mängd för hela receptet, t.ex. '600 g', '2 st', '1 burk'")


class Middag(BaseModel):
    dag: str
    ratt: str
    beskrivning: str
    tid_min: int
    kampanjvaror: list[str] = Field(description="Vilka veckokampanjer rätten bygger på, med butik")
    ingredienser: list[Ingrediens]
    instruktioner: list[str]


class Inkopsrad(BaseModel):
    vara: str = Field(description="Vad som behövs, generiskt, t.ex. 'kycklingfilé'")
    behov: str = Field(description="Total mängd för veckan, t.ex. '1,2 kg'")
    sokord: str = Field(description="1–2 ord för Willys sök, utan märke eller förpackningsstorlek, t.ex. 'kycklingfilé', 'ägg'")
    till: list[str] = Field(description="Vilka middagar (dag) varan används till")
    kanske_hemma: bool = Field(
        default=False,
        description="Sant för basvaror som ketchup eller senap som de flesta har hemma men som inte står i "
        "skafferilistan. Sådana rader läggs inte i korgen utan listas under 'Kolla om du har hemma'.",
    )


class Veckoplan(BaseModel):
    middagar: list[Middag]
    inkopslista: list[Inkopsrad]
    kommentar: str = Field(description="Kort om hur menyn utnyttjar veckans kampanjer")


# ---------- Steg 2: produktval ----------

class Reserv(BaseModel):
    kod: str = Field(description="Willys-produktkod ur samma rads kandidater")
    antal: int = Field(description="Antal räknat för reservens egen förpackningsstorlek")


class Val(BaseModel):
    rad: int = Field(description="Index i inköpslistan")
    willys_kod: str | None = Field(
        description="Vald Willys-produktkod – alltid när en godtagbar kandidat finns, även om en butikskampanj "
        "är billigare. null bara om ingen kandidat passar"
    )
    willys_antal: int = Field(description="Antal förpackningar/styck. Lösvikt märkt 'per st' räknas i styck (8 bananer = 8)")
    willys_reserver: list[Reserv] = Field(
        default_factory=list,
        description="Högst 3 reservalternativ ur samma rads kandidater, bäst först, om huvudvalet inte finns "
        "eller inte godkänns. Samma krav som huvudvalet.",
    )
    butik: str | None = Field(
        description="Butiken (exakt namn ur butikskampanjerna, ICA eller Willys i butik) om en butikskampanj "
        "är klart billigare än e-handeln, annars null"
    )
    butik_kod: str | None = Field(default=None, description="Kampanjens kod i hakparentes (krävs när butik anges), annars null")
    butik_erbjudande: str | None = None
    butik_antal: int = 0
    butik_kostnad_kr: float | None = Field(default=None, description="Uppskattad kostnad i butiken för behovet")
    butik_kostnad_beraknad: bool = Field(default=False, description="Sätts av koden, inte av dig")
    motivering: str


class Produktval(BaseModel):
    val: list[Val]


def _offers_block(offers: list[Offer]) -> str:
    by_store: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        by_store[o.store].append(o)
    parts = []
    for store, items in by_store.items():
        lines = "\n".join(f"- {o.short()}" for o in items)
        parts.append(f"## {store} ({len(items)} kampanjer)\n{lines}")
    return "\n\n".join(parts)


def _dagar(n: int) -> str:
    """Vilka dagar middagarna gäller, härlett från middagar_per_vecka."""
    if n == 5:
        return "Dagar: måndag–fredag."
    if n == 7:
        return "Dagar: måndag–söndag."
    return f"Välj själv vilka {n} veckodagar middagarna gäller."


def gar_alltid_at_rad(row: Inkopsrad, ord: list[str]) -> bool:
    """Matchar inköpsraden en vara som alltid går åt (hushall.gar_alltid_at)?"""
    vara = row.vara.lower()
    return any(o.lower() in vara for o in ord if o)


class Planner:
    """Anropar Claude via API-nyckel om ANTHROPIC_API_KEY finns, annars via Claude Code (Pro-inloggning)."""

    def __init__(self, model_meny: str, model_produkter: str | None = None):
        self.model_meny = model_meny
        self.model_produkter = model_produkter or model_meny
        self.client = anthropic.Anthropic() if os.environ.get("ANTHROPIC_API_KEY") else None

    def _parse(self, prompt: str, schema: type[BaseModel], system: str, effort: str, model: str):
        if self.client is None:
            return self._parse_claude_code(prompt, schema, system, effort, model)
        resp = self.client.messages.parse(
            model=model,
            max_tokens=16000,
            system=system,
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude avböjde förfrågan")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Svaret blev för långt (max_tokens)")
        return resp.parsed_output

    def _parse_claude_code(self, prompt: str, schema: type[BaseModel], system: str, effort: str, model: str):
        exe = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
        cmd = [
            exe, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema.model_json_schema()),
            "--append-system-prompt", system,
            "--model", model,
            "--effort", effort,
            "--tools", "",
            "--no-session-persistence",
        ]
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1200, env=env)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"Claude Code svarade inte med JSON: {proc.stderr[-500:] or proc.stdout[-500:]}")
        if out.get("is_error") or out.get("structured_output") is None:
            raise RuntimeError(f"Claude Code misslyckades: {str(out.get('result'))[:500]}")
        return schema.model_validate(out["structured_output"])

    def plan_week(self, offers: list[Offer], cfg: dict, previous_dishes: list[str]) -> Veckoplan:
        h = cfg["hushall"]
        barn = h.get("barn") or []
        system = (
            f"Du är en svensk matplanerare som gör billiga, goda{' och barnvänliga' if barn else ''} veckomenyer "
            "genom att utgå från butikernas veckokampanjer. Svara på svenska."
        )
        personer = f"{h['vuxna']} vuxna"
        if barn:
            personer += f" och barn ({', '.join(f'{a} år' for a in barn)})"
        barnregel = " och använd bara varor som barnen rimligen äter" if barn else ""
        prompt = f"""Planera {h['middagar_per_vecka']} middagar för {personer}, {h['portioner_per_middag']} portioner per middag.
{_dagar(h['middagar_per_vecka'])}

Önskemål: {h['preferenser'].strip()}
UNDVIK ALLTID (hårt krav, inga undantag): {'; '.join(h['undvik']) or 'inget särskilt'}
Finns alltid hemma (ska inte stå på inköpslistan): {', '.join(cfg['skafferi'])}
Rätter från de senaste veckorna (upprepa inte): {', '.join(previous_dishes) or 'inga'}

Bygg huvudsakligen på kampanjvarorna nedan, särskilt protein och grönsaker. Läs varunamnen exakt
(t.ex. är kycklinglever inte kycklingfilé){barnregel}.
Det finns tre sorters kampanjer:
- Willys e-handel: läggs direkt i varukorgen. Huvudkällan – allt som går ska finnas här.
- Willys i butik: gäller bara i Willys-butiken. E-handelns motsvarighet läggs ändå i korgen; den
  billigare butikskampanjen visas som tips (t.ex. vid hämtning av ordern).
- ICA-butiker: kräver en egen resa och visas också bara som tips när de är klart billigare. Utnyttja samma ingredienser i flera rätter för att minska svinn, och tänk på mängder (t.ex. en 1 kg-förpackning
räcker till två middagar).

Inköpslistan ska summera hela veckans behov per vara, utan skafferivaror. Markera kanske_hemma för
basvaror som de flesta har hemma (t.ex. ketchup, senap, soja) men som inte står i skafferilistan.

# Veckans kampanjer
{_offers_block(offers)}
"""
        return self._parse(prompt, Veckoplan, system, effort="high", model=self.model_meny)

    def choose_products(
        self,
        rows: list[Inkopsrad],
        candidates: list[list[Product]],
        butiks_offers: list[Offer],
        undvik: list[str],
        gar_alltid_at: list[str] | None = None,
    ) -> Produktval:
        system = (
            "Du matchar inköpsrader mot produkter i Willys e-handel och väljer billigaste rimliga "
            "alternativ med hänsyn till kampanjer, förpackningsstorlek och behov. Svara på svenska."
        )
        blocks = []
        for i, (row, cands) in enumerate(zip(rows, candidates)):
            c = "\n".join(f"  {p.describe()}" for p in cands) or "  (inga träffar)"
            storpack = " – GÅR ALLTID ÅT: ta med storpack" if gar_alltid_at_rad(row, gar_alltid_at or []) else ""
            blocks.append(f"[{i}] {row.vara} – behov {row.behov} – till: {', '.join(row.till)}{storpack}\n{c}")
        butikskampanjer = "\n".join(f"- {o.store}: {f'[{o.code}] ' if o.code else ''}{o.short()}" for o in butiks_offers)
        prompt = f"""Välj för varje inköpsrad den Willys-produkt (kod) och det antal som täcker behovet billigast.
- Antal: priset i listan gäller per förpackning, eller per styck för lösvikt märkt "per st" (vikten
  "ca: 2kg" är vikten per styck – 1 vitkålshuvud á 2 kg räcker till 750 g, 8 bananer = antal 8).
- Föredra kampanjvaror och jämförpris, men välj inte fel sorts vara.
- Utnyttja mängdkampanjer ("2 för") när det inte ger orimligt svinn.
- Hårt krav, välj aldrig en produkt som innehåller: {'; '.join(undvik) or '–'}.
  Är du osäker på om en produkt innehåller något av detta (t.ex. korv utan angivet köttslag): välj en annan.
- Varan måste passa rätten den ska till. Byt aldrig till en annan sorts vara (t.ex. lever i stället
  för filé, kattmat, färdigrätter). Om ingen kandidat passar: willys_kod = null.
- Ange för varje rad med willys_kod upp till 3 willys_reserver, rangordnade, ur samma rads kandidater.
  De används om huvudvalet inte finns i butiken eller stoppas av ingredienskontrollen. Samma krav som
  huvudvalet: samma sorts vara som passar rätten, inget av det som ska undvikas, och antalet räknat för
  reservens egen förpackningsstorlek (t.ex. 2 st á 500 g om huvudvalet var 1 st á 1 kg). Hellre färre
  reserver än en som inte passar.
- Rader märkta "GÅR ALLTID ÅT" gäller varor som hushållet alltid gör av med. Ta med alla godtagbara
  storlekar av samma vara bland huvudval och reserver, även förpackningar som är större än behovet
  (tak ungefär 30 st eller 2 kg per förpackning). Antal: så få förpackningar som täcker behovet,
  normalt 1. Koden väljer sedan den med lägst jämförpris.
- Välj ALLTID en Willys-produkt (willys_kod) när det finns en godtagbar kandidat, även när en
  butikskampanj är billigare. Korgen ska vara komplett; butikskampanjen visas bara som ett tips.
- Butikskampanjerna nedan går inte att lägga i e-handelskorgen. Om en av dem är billigare för samma
  behov: ange dessutom butik (exakt butiksnamn), butik_kod (kampanjens kod i hakparentes – den måste
  höra till samma butik), butik_erbjudande, butik_antal (minst 1) och uppskattad butik_kostnad_kr. För
  "Willys … (i butik)" räknar koden själv kostnaden ur kampanjen. Ett butiksval utan giltig kod
  ignoreras.

# Inköpsrader med Willys-kandidater
{chr(10).join(blocks)}

# Butikskampanjer (ICA-butiker och Willys i butik – inte i e-handeln)
{butikskampanjer}
"""
        return self._parse(prompt, Produktval, system, effort="medium", model=self.model_produkter)
