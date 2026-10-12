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


class Veckoplan(BaseModel):
    middagar: list[Middag]
    inkopslista: list[Inkopsrad]
    kommentar: str = Field(description="Kort om hur menyn utnyttjar veckans kampanjer")


# ---------- Steg 2: produktval ----------

class Val(BaseModel):
    rad: int = Field(description="Index i inköpslistan")
    willys_kod: str | None = Field(description="Vald Willys-produktkod eller null om inget passar")
    willys_antal: int = Field(description="Antal förpackningar/styck. Lösvikt märkt 'per st' räknas i styck (8 bananer = 8)")
    ica_butik: str | None = Field(description="ICA-butik om en ICA-kampanj är klart billigare, annars null")
    ica_erbjudande: str | None = None
    ica_antal: int = 0
    ica_kostnad_kr: float | None = Field(default=None, description="Uppskattad kostnad på ICA för behovet")
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


class Planner:
    """Anropar Claude via API-nyckel om ANTHROPIC_API_KEY finns, annars via Claude Code (Pro-inloggning)."""

    def __init__(self, model: str):
        self.model = model
        self.client = anthropic.Anthropic() if os.environ.get("ANTHROPIC_API_KEY") else None

    def _parse(self, prompt: str, schema: type[BaseModel], system: str, effort: str):
        if self.client is None:
            return self._parse_claude_code(prompt, schema, system, effort)
        resp = self.client.messages.parse(
            model=self.model,
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

    def _parse_claude_code(self, prompt: str, schema: type[BaseModel], system: str, effort: str):
        exe = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
        cmd = [
            exe, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema.model_json_schema()),
            "--append-system-prompt", system,
            "--model", self.model,
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
Willys-kampanjerna gäller e-handeln där allt handlas; ICA-butikernas kampanjer går bara att köpa i butik,
så använd dem bara när de är klart billigare. Utnyttja samma ingredienser i flera rätter för att minska svinn, och tänk på mängder (t.ex. en 1 kg-förpackning
räcker till två middagar).

Inköpslistan ska summera hela veckans behov per vara, utan skafferivaror.

# Veckans kampanjer
{_offers_block(offers)}
"""
        return self._parse(prompt, Veckoplan, system, effort="high")

    def choose_products(
        self,
        rows: list[Inkopsrad],
        candidates: list[list[Product]],
        ica_offers: list[Offer],
        undvik: list[str],
    ) -> Produktval:
        system = (
            "Du matchar inköpsrader mot produkter i Willys e-handel och väljer billigaste rimliga "
            "alternativ med hänsyn till kampanjer, förpackningsstorlek och behov. Svara på svenska."
        )
        blocks = []
        for i, (row, cands) in enumerate(zip(rows, candidates)):
            c = "\n".join(f"  {p.describe()}" for p in cands) or "  (inga träffar)"
            blocks.append(f"[{i}] {row.vara} – behov {row.behov} – till: {', '.join(row.till)}\n{c}")
        ica = "\n".join(f"- {o.store}: {o.short()}" for o in ica_offers)
        prompt = f"""Välj för varje inköpsrad den Willys-produkt (kod) och det antal som täcker behovet billigast.
- Antal: priset i listan gäller per förpackning, eller per styck för lösvikt märkt "per st" (vikten
  "ca: 2kg" är vikten per styck – 1 vitkålshuvud á 2 kg räcker till 750 g, 8 bananer = antal 8).
- Föredra kampanjvaror och jämförpris, men välj inte fel sorts vara.
- Utnyttja mängdkampanjer ("2 för") när det inte ger orimligt svinn.
- Hårt krav, välj aldrig en produkt som innehåller: {'; '.join(undvik) or '–'}.
  Är du osäker på om en produkt innehåller något av detta (t.ex. korv utan angivet köttslag): välj en annan.
- Varan måste passa rätten den ska till. Byt aldrig till en annan sorts vara (t.ex. lever i stället
  för filé, kattmat, färdigrätter). Om ingen kandidat passar: willys_kod = null.
- Om en ICA-kampanj nedan är tydligt billigare för samma behov, ange ica_butik, ica_erbjudande, ica_antal
  och uppskattad ica_kostnad_kr. Välj ändå en Willys-produkt som reserv.

# Inköpsrader med Willys-kandidater
{chr(10).join(blocks)}

# ICA-kampanjer (bara i butik)
{ica}
"""
        return self._parse(prompt, Produktval, system, effort="medium")
