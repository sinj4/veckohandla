"""Claude-anrop: 1) sätt ihop veckomeny från kampanjerna, 2) välj produkter och butik per inköpsrad."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from . import betyg as betygmodul
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


class Ratt(BaseModel):
    """En föreslagen rätt i valläget – som Middag men utan dag."""

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


class Veckoforslag(BaseModel):
    ratter: list[Ratt] = Field(description="Rätterna i den ordning de ska numreras (1, 2, 3 …)")
    kommentar: str = Field(description="Kort om hur förslagen utnyttjar veckans kampanjer")


class Inkopslista(BaseModel):
    inkopslista: list[Inkopsrad]
    kommentar: str = Field(description="Kort om hur de valda rätterna utnyttjar veckans kampanjer")


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


# ---------- Förbrukning ----------

@dataclass
class Forbrukning:
    """Summerad förbrukning för ett steg. kostnad_usd finns bara från Claude Code (listpris)."""

    anrop: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_skapad_tokens: int = 0
    cache_last_tokens: int = 0
    kostnad_usd: float | None = None
    modeller: list[str] = field(default_factory=list)

    @property
    def in_tokens(self) -> int:
        return self.input_tokens + self.cache_skapad_tokens + self.cache_last_tokens

    def lagg_till(self, usage: dict, kostnad_usd: float | None, modell: str) -> None:
        self.anrop += 1
        self.input_tokens += usage.get("input_tokens") or 0
        self.output_tokens += usage.get("output_tokens") or 0
        self.cache_skapad_tokens += usage.get("cache_creation_input_tokens") or 0
        self.cache_last_tokens += usage.get("cache_read_input_tokens") or 0
        if kostnad_usd is not None:
            self.kostnad_usd = round((self.kostnad_usd or 0) + kostnad_usd, 6)
        if modell not in self.modeller:
            self.modeller.append(modell)

    def __iadd__(self, other: "Forbrukning") -> "Forbrukning":
        self.anrop += other.anrop
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_skapad_tokens += other.cache_skapad_tokens
        self.cache_last_tokens += other.cache_last_tokens
        if other.kostnad_usd is not None:
            self.kostnad_usd = round((self.kostnad_usd or 0) + other.kostnad_usd, 6)
        self.modeller += [m for m in other.modeller if m not in self.modeller]
        return self

    def text(self) -> str:
        t = f"{_tal(self.in_tokens)} tokens in, {_tal(self.output_tokens)} ut"
        if self.kostnad_usd is not None:
            t += f", ≈ {self.kostnad_usd:.2f} USD".replace(".", ",")
        return t


def _tal(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def forbrukning_text(sammanfattning: dict) -> str:
    """'meny: 41 000 tokens in, 2 300 ut, ≈ 0,35 USD · produktval: … · totalt: …'"""
    delar = [f"{steg}: {Forbrukning(**f).text()}" for steg, f in sammanfattning["steg"].items()]
    delar.append(f"totalt: {Forbrukning(**sammanfattning['totalt']).text()}")
    text = " · ".join(delar)
    if sammanfattning.get("kalla") == "claude-code" and sammanfattning["totalt"].get("kostnad_usd") is not None:
        text += " (listpris – med abonnemang räknas det mot kvoten)"
    return text


def _offers_block(offers: list[Offer]) -> str:
    by_store: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        by_store[o.store].append(o)
    parts = []
    for store, items in by_store.items():
        lines = "\n".join(f"- {o.short()}" for o in items)
        parts.append(f"## {store} ({len(items)} kampanjer)\n{lines}")
    if any(o.prisnotis for o in offers):
        parts.insert(0, "Prismarkering ur prishistoriken: BRA PRIS = minst 15 % under medianen av ordinarie pris de "
                        "senaste 8 veckorna (prioritera), VANLIGT PRIS = inom 5 % av medianen, alltså ingen riktig rea.")
    return "\n\n".join(parts)


def _dagar(n: int) -> str:
    """Vilka dagar middagarna gäller, härlett från middagar_per_vecka."""
    if n == 5:
        return "Dagar: måndag–fredag."
    if n == 7:
        return "Dagar: måndag–söndag."
    return f"Välj själv vilka {n} veckodagar middagarna gäller."


def _andra_butiker(jamforelse: list[str]) -> str:
    return "ICA-butiker" if not jamforelse else f"ICA-butiker och {', '.join(jamforelse)}"


def _kampanjtyper(kedja: str, jamforelse: list[str]) -> str:
    return f"""Det finns tre sorters kampanjer:
- {kedja} e-handel: läggs direkt i varukorgen. Huvudkällan – allt som går ska finnas här.
- {kedja} i butik: gäller bara i {kedja}-butiken. E-handelns motsvarighet läggs ändå i korgen; den
  billigare butikskampanjen visas som tips (t.ex. vid hämtning av ordern).
- {_andra_butiker(jamforelse)}: kräver en egen resa och visas också bara som tips när de är klart billigare."""

INKOPSREGEL = """Inköpslistan ska summera hela veckans behov per vara, utan skafferivaror. Markera kanske_hemma för
basvaror som de flesta har hemma (t.ex. ketchup, senap, soja) men som inte står i skafferilistan."""


VECKODAGAR = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]


def matlador(h: dict) -> tuple[list[str], int]:
    """hushall.matlador -> (dagar i gemener, extra portioner). Av (([], 0)) om nyckeln saknas."""
    m = h.get("matlador") or {}
    dagar = [str(d).strip().lower() for d in m.get("dagar") or []]
    extra = int(m.get("extra_portioner") or 0)
    if okanda := [d for d in dagar if d not in VECKODAGAR]:
        raise ValueError(f"hushall.matlador.dagar: okänd dag {', '.join(okanda)} (använd t.ex. tisdag, torsdag)")
    if extra < 0:
        raise ValueError("hushall.matlador.extra_portioner kan inte vara negativt")
    return (dagar, extra) if dagar and extra else ([], 0)


def matlador_for(dag: str, h: dict) -> int:
    """Extra portioner till matlådor för en middag, utifrån dagen ('Tisdag', 'tisdag 28/10' …)."""
    dagar, extra = matlador(h)
    forsta = (dag.split() or [""])[0].strip(",:").lower()
    return extra if forsta in dagar else 0


def _matladerad(h: dict) -> str:
    dagar, extra = matlador(h)
    if not dagar:
        return ""
    namn = dagar[0] if len(dagar) == 1 else f"{', '.join(dagar[:-1])} och {dagar[-1]}"
    p = h["portioner_per_middag"]
    return (f"\nMatlådor: på {namn} lagas {p + extra} portioner i stället för {p} ({extra} extra till matlådor). "
            "Ingredienserna för de dagarna och inköpslistan ska räcka till det.")


def _meny_system(cfg: dict) -> str:
    barn = cfg["hushall"].get("barn") or []
    return (
        f"Du är en svensk matplanerare som gör billiga, goda{' och barnvänliga' if barn else ''} veckomenyer "
        "genom att utgå från butikernas veckokampanjer. Svara på svenska."
    )


def _personer(h: dict) -> str:
    personer = f"{h['vuxna']} vuxna"
    if barn := h.get("barn") or []:
        personer += f" och barn ({', '.join(f'{a} år' for a in barn)})"
    return personer


def _hushallsrader(cfg: dict, previous_dishes: list[str], smak: betygmodul.Smak | None = None) -> str:
    h = cfg["hushall"]
    rader = f"""Önskemål: {h['preferenser'].strip()}
UNDVIK ALLTID (hårt krav, inga undantag): {'; '.join(h['undvik']) or 'inget särskilt'}
Finns alltid hemma (ska inte stå på inköpslistan): {', '.join(cfg['skafferi'])}
Rätter från de senaste veckorna (upprepa inte): {', '.join(previous_dishes) or 'inga'}"""
    if smak and smak.gillade:
        rader += f"\nGillade rätter (gärna liknande): {betygmodul.text(smak.gillade)}"
    if smak and smak.ogillade:
        rader += f"\nOgillade rätter (undvik dem och liknande): {betygmodul.text(smak.ogillade)}"
    return rader


def _kampanjgrund(h: dict) -> str:
    barnregel = " och använd bara varor som barnen rimligen äter" if h.get("barn") else ""
    return f"""Bygg huvudsakligen på kampanjvarorna nedan, särskilt protein och grönsaker. Läs varunamnen exakt
(t.ex. är kycklinglever inte kycklingfilé){barnregel}."""


def gar_alltid_at_rad(row: Inkopsrad, ord: list[str]) -> bool:
    """Matchar inköpsraden en vara som alltid går åt (hushall.gar_alltid_at)?"""
    vara = row.vara.lower()
    return any(o.lower() in vara for o in ord if o)


# Vilket steg ett anrop hör till avgörs av svarsschemat
STEG = {"Veckoplan": "meny", "Veckoforslag": "meny", "Produktval": "produktval", "Inkopslista": "inköpslista"}


class Planner:
    """Anropar Claude via API-nyckel om ANTHROPIC_API_KEY finns, annars via Claude Code (Pro-inloggning)."""

    kedja: str = "Willys"
    jamforelse: list[str] | tuple[str, ...] = ()

    def __init__(
        self, model_meny: str, model_produkter: str | None = None, kedja: str = "Willys", jamforelse: list[str] | None = None
    ):
        self.model_meny = model_meny
        self.model_produkter = model_produkter or model_meny
        self.kedja = kedja  # e-handelskedjan (Willys eller Hemköp)
        self.jamforelse = jamforelse or ()  # andra Axfood-butiker som bara jämförs, t.ex. "Hemköp Trosa"
        self.client = anthropic.Anthropic() if os.environ.get("ANTHROPIC_API_KEY") else None
        self._claude: tuple[str, str] | None = None  # (sökväg, version), loggas vid första anropet
        self.forbrukning: dict[str, Forbrukning] = {}  # steg -> summerad förbrukning

    def _registrera(self, schema: type[BaseModel], usage: dict, kostnad_usd: float | None, modell: str) -> None:
        steg = STEG.get(schema.__name__, schema.__name__)
        self.forbrukning.setdefault(steg, Forbrukning()).lagg_till(usage, kostnad_usd, modell)

    def forbrukning_sammanfattning(self) -> dict:
        """Förbrukningen per steg och totalt, som JSON-vänlig dict."""
        totalt = Forbrukning()
        for f in self.forbrukning.values():
            totalt += f
        return {
            "kalla": "claude-code" if self.client is None else "api",
            "steg": {k: asdict(v) for k, v in self.forbrukning.items()},
            "totalt": asdict(totalt),
        }

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
        if resp.usage is not None:  # API-svaret har tokens men ingen kostnad
            self._registrera(schema, resp.usage.model_dump(), None, model)
        if resp.stop_reason == "refusal":
            raise RuntimeError("Claude avböjde förfrågan")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Svaret blev för långt (max_tokens)")
        return resp.parsed_output

    def _claude_bin(self) -> tuple[str, str]:
        """Välj Claude Code-binär (CLAUDE_BIN, PATH, ~/.local/bin) och logga sökväg och version en gång."""
        if self._claude is None:
            exe = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
            try:
                v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
                version = (v.stdout or v.stderr).strip() or "okänd"
            except (OSError, subprocess.SubprocessError) as e:
                version = f"okänd ({e})"
            print(f"Claude Code: {exe} – version {version}", flush=True)
            self._claude = (exe, version)
        return self._claude

    def _parse_claude_code(self, prompt: str, schema: type[BaseModel], system: str, effort: str, model: str):
        exe, version = self._claude_bin()
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
        svar = f"{proc.stdout}\n{proc.stderr}"
        if "does not support this model" in svar or "newer is required" in svar:
            raise RuntimeError(
                f"Claude Code är för gammal för modellen {model}: {exe} (version {version}). "
                f"Uppdatera Claude Code. Svar: {svar.strip()[-300:]}"
            )
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"Claude Code svarade inte med JSON: {proc.stderr[-500:] or proc.stdout[-500:]}")
        if isinstance(out.get("usage"), dict):
            self._registrera(schema, out["usage"], out.get("total_cost_usd"), model)
        if out.get("is_error") or out.get("structured_output") is None:
            raise RuntimeError(f"Claude Code misslyckades: {str(out.get('result'))[:500]}")
        return schema.model_validate(out["structured_output"])

    def plan_week(
        self, offers: list[Offer], cfg: dict, previous_dishes: list[str], smak: betygmodul.Smak | None = None
    ) -> Veckoplan:
        h = cfg["hushall"]
        prompt = f"""Planera {h['middagar_per_vecka']} middagar för {_personer(h)}, {h['portioner_per_middag']} portioner per middag.
{_dagar(h['middagar_per_vecka'])}{_matladerad(h)}

{_hushallsrader(cfg, previous_dishes, smak)}

{_kampanjgrund(h)}
{_kampanjtyper(self.kedja, self.jamforelse)} Utnyttja samma ingredienser i flera rätter för att minska svinn, och tänk på mängder (t.ex. en 1 kg-förpackning
räcker till två middagar).

{INKOPSREGEL}

# Veckans kampanjer
{_offers_block(offers)}
"""
        return self._parse(prompt, Veckoplan, _meny_system(cfg), effort="high", model=self.model_meny)

    def propose_dishes(
        self, offers: list[Offer], cfg: dict, previous_dishes: list[str], antal: int, smak: betygmodul.Smak | None = None
    ) -> Veckoforslag:
        """Valläget: `antal` fristående rätter att välja bland, utan dagar och utan inköpslista."""
        h = cfg["hushall"]
        prompt = f"""Föreslå {antal} middagsrätter för {_personer(h)}, {h['portioner_per_middag']} portioner per rätt.
Vi väljer sedan själva {h['middagar_per_vecka']} av dem till veckan, så varje rätt ska stå för sig själv och
inte ha någon veckodag.
Variera rätterna enligt önskemålen, så att det finns flera att välja på av varje sort som önskemålen
nämner (t.ex. minst två med fisk och minst två vegetariska när önskemålen tar upp fisk och vegetariskt).
Ange ingredienserna med mängd för {h['portioner_per_middag']} portioner.

{_hushallsrader(cfg, previous_dishes, smak)}

{_kampanjgrund(h)}
{_kampanjtyper(self.kedja, self.jamforelse)}

# Veckans kampanjer
{_offers_block(offers)}
"""
        return self._parse(prompt, Veckoforslag, _meny_system(cfg), effort="high", model=self.model_meny)

    def shopping_list(self, middagar: list[Middag], cfg: dict) -> Inkopslista:
        """Valläget: inköpslistan för de valda rätterna."""
        system = "Du gör inköpslistor till svenska veckomenyer. Svara på svenska."
        h = cfg["hushall"]

        def matlada(m: Middag) -> str:
            extra = matlador_for(m.dag, h)
            if not extra:
                return ""
            p = h["portioner_per_middag"]
            return (f"\nMatlådor: laga {p + extra} portioner ({extra} extra). Ingredienserna nedan gäller {p} "
                    "portioner – skala upp dem i inköpslistan.")

        ratter = "\n\n".join(
            f"## {m.dag}: {m.ratt}{matlada(m)}\nKampanjvaror: {', '.join(m.kampanjvaror) or '–'}\n"
            + "\n".join(f"- {i.mangd} {i.namn}" for i in m.ingredienser)
            for m in middagar
        )
        prompt = f"""Gör inköpslistan till de här {len(middagar)} middagarna, {cfg['hushall']['portioner_per_middag']} portioner per middag.
Finns alltid hemma (ska inte stå på inköpslistan): {', '.join(cfg['skafferi'])}

{INKOPSREGEL}
Ange i `till` vilka middagar (dag) varan används till.

# Middagar
{ratter}
"""
        return self._parse(prompt, Inkopslista, system, effort="medium", model=self.model_produkter)

    def choose_products(
        self,
        rows: list[Inkopsrad],
        candidates: list[list[Product]],
        butiks_offers: list[Offer],
        undvik: list[str],
        gar_alltid_at: list[str] | None = None,
    ) -> Produktval:
        system = (
            f"Du matchar inköpsrader mot produkter i {self.kedja} e-handel och väljer billigaste rimliga "
            "alternativ med hänsyn till kampanjer, förpackningsstorlek och behov. Svara på svenska."
        )
        blocks = []
        for i, (row, cands) in enumerate(zip(rows, candidates)):
            c = "\n".join(f"  {p.describe()}" for p in cands) or "  (inga träffar)"
            storpack = " – GÅR ALLTID ÅT: ta med storpack" if gar_alltid_at_rad(row, gar_alltid_at or []) else ""
            blocks.append(f"[{i}] {row.vara} – behov {row.behov} – till: {', '.join(row.till)}{storpack}\n{c}")
        butikskampanjer = "\n".join(f"- {o.store}: {f'[{o.code}] ' if o.code else ''}{o.short()}" for o in butiks_offers)
        k = self.kedja
        axfood_i_butik = f'"{k} … (i butik)"' + "".join(f' och "{n}"' for n in self.jamforelse)
        prompt = f"""Välj för varje inköpsrad den {k}-produkt (kod) och det antal som täcker behovet billigast.
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
- Välj ALLTID en {k}-produkt (willys_kod) när det finns en godtagbar kandidat, även när en
  butikskampanj är billigare. Korgen ska vara komplett; butikskampanjen visas bara som ett tips.
- Butikskampanjerna nedan går inte att lägga i e-handelskorgen. Om en av dem är billigare för samma
  behov: ange dessutom butik (exakt butiksnamn), butik_kod (kampanjens kod i hakparentes – den måste
  höra till samma butik), butik_erbjudande, butik_antal (minst 1) och uppskattad butik_kostnad_kr. För
  {axfood_i_butik} räknar koden själv kostnaden ur kampanjen. Ett butiksval utan giltig kod
  ignoreras.

# Inköpsrader med {k}-kandidater
{chr(10).join(blocks)}

# Butikskampanjer ({_andra_butiker(self.jamforelse)} och {k} i butik – inte i e-handeln)
{butikskampanjer}
"""
        return self._parse(prompt, Produktval, system, effort="medium", model=self.model_produkter)
