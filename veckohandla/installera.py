"""Installationsguiden `python -m veckohandla init`: frågor i terminalen → config.yaml (och ev. .env).

Med --ingen-fraga tas alla svar från flaggor, så att guiden går att testa och skripta.
"""

from __future__ import annotations

import getpass
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import yamltext

# Förval för "Undvik": (text till undvik, spärrord i produktnamn, spärrord i ingredienser)
UNDVIK_VAL: dict[str, tuple[str, list[str], list[str]]] = {
    "flaskfritt": (
        "fläsk/griskött i alla former (även korv, falukorv, blandfärs, bacon, skinka)",
        ["fläsk", "gris", "bacon", "skinka", "korv", "salami", "chorizo", "karré", "kassler", "isterband",
         "blandfärs", "gyros", "leverpastej", "mortadella", "kåldolm", "ister", "coppa", "nduja", "lardo", "pork"],
        ["fläsk", "griskött", "gris", "bacon", "skinka", "ister", "svinkött"],
    ),
    "vegetariskt": (
        "kött, fågel, fisk och skaldjur (vegetariskt)",
        ["kyckling", "nötfärs", "köttfärs", "fläsk", "bacon", "skinka", "korv", "salami", "kalkon", "lamm",
         "högrev", "entrecote", "köttbullar", "lax", "torsk", "sej", "kolja", "räkor", "tonfisk", "sill"],
        ["kött", "kyckling", "gris", "fisk", "räkor", "gelatin", "ansjovis"],
    ),
    "notfritt": (
        "nötter och jordnötter (allergi)",
        ["nötter", "jordnöt", "cashew", "hasselnöt", "mandel", "valnöt", "pistage", "pekan", "paranöt", "macadamia"],
        ["nötter", "jordnöt", "cashew", "hasselnöt", "mandel", "valnöt", "pistage", "pekan", "paranöt", "macadamia"],
    ),
    # Ordfiltren matchar delsträngar: "laktos" och "mjölk" skulle stoppa även laktosfria varor
    "laktosfritt": ("laktos (laktosfria varianter går bra)", [], []),
}
UNDVIK_NAMN = {"flaskfritt": "fläskfritt", "vegetariskt": "vegetariskt", "notfritt": "nötfritt",
               "laktosfritt": "laktosfritt"}

BILLIGA_MODELLER = {"model": "claude-sonnet-5-5", "model_meny": "claude-sonnet-5-5",
                    "model_produkter": "claude-haiku-5-5"}
VECKODAGAR = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]


@dataclass
class Butik:
    kedja: str  # willys eller hemkop
    store_id: str
    namn: str


@dataclass
class Svar:
    butik: Butik
    ica: list[dict] = field(default_factory=list)  # {namn, erbjudande_slug, bara_lokalt}
    vuxna: int = 2
    barn: list[int] = field(default_factory=list)
    middagar: int = 5
    onskemal: str = ""
    matlador_dagar: list[str] = field(default_factory=list)
    matlador_extra: int = 2
    undvik_val: list[str] = field(default_factory=list)
    undvik_egen: list[str] = field(default_factory=list)
    lage: str = "auto"
    epost: str = "du@example.com"
    smtp_host: str = "smtp.gmail.com"
    billiga_modeller: bool = True


# ---------- config ----------

def bygg_config(exempel: str, s: Svar) -> str:
    """config.yaml-text från config.example.yaml med svaren insatta (kommentarerna behålls)."""
    t = exempel
    h = ("hushall",)
    t = yamltext.satt(t, h + ("vuxna",), s.vuxna)
    t = yamltext.satt(t, h + ("barn",), s.barn)
    t = yamltext.satt(t, h + ("middagar_per_vecka",), s.middagar)
    t = yamltext.satt(t, h + ("portioner_per_middag",), s.vuxna + len(s.barn))
    if s.onskemal.strip():
        t = yamltext.satt(t, h + ("preferenser",), s.onskemal.strip())
    if s.matlador_dagar:
        t = yamltext.satt(t, h + ("matlador",), {"dagar": s.matlador_dagar, "extra_portioner": s.matlador_extra})
    undvik, sparrord, ingr = [], [], []
    for val in s.undvik_val:
        text, ord_, ingr_ord = UNDVIK_VAL[val]
        undvik.append(text)
        sparrord += [o for o in ord_ if o not in sparrord]
        ingr += [o for o in ingr_ord if o not in ingr]
    undvik += [u.strip() for u in s.undvik_egen if u.strip()]
    t = yamltext.satt(t, h + ("undvik",), undvik)
    t = yamltext.satt(t, h + ("sparrord",), sparrord)
    t = yamltext.satt(t, h + ("sparrord_ingredienser",), ingr)

    b = s.butik
    t = yamltext.satt(t, ("butiker", "e_handel"), b.kedja)
    for kedja in ("willys", "hemkop"):  # exemplets butik ska inte bli en jämförelsebutik
        if kedja != b.kedja:
            t = yamltext.ta_bort(t, ("butiker", kedja))
    t = yamltext.satt(t, ("butiker", b.kedja), {"namn": b.namn, "store_id": str(b.store_id), "i_butik": True})
    t = yamltext.satt(t, ("butiker", "ica"), s.ica)

    t = yamltext.satt(t, ("meny", "lage"), s.lage)
    t = yamltext.satt(t, ("epost", "till"), s.epost)
    t = yamltext.satt(t, ("epost", "fran"), s.epost)
    t = yamltext.satt(t, ("epost", "smtp_host"), s.smtp_host)
    if s.billiga_modeller:
        for k, v in BILLIGA_MODELLER.items():
            t = yamltext.satt(t, ("claude", k), v)
    return t


def skriv_env(path: Path, nyckel: str, varde: str) -> None:
    """Sätt NYCKEL=värde i .env (övriga rader behålls). Filen blir bara läsbar för användaren."""
    rader = path.read_text().splitlines() if path.exists() else []
    ny = f"{nyckel}={varde}"
    for i, rad in enumerate(rader):
        if re.match(rf"^\s*{re.escape(nyckel)}\s*=", rad):
            rader[i] = ny
            break
    else:
        rader.append(ny)
    path.write_text("\n".join(rader) + "\n")
    path.chmod(0o600)


def ica_slug(text: str) -> str:
    """'https://www.ica.se/erbjudanden/ica-kvantum-x-123/' eller 'ica-kvantum-x-123' -> slug."""
    m = re.search(r"/erbjudanden/([^/?#]+)", text)
    return (m.group(1) if m else text).strip().strip("/")


def ica_namn(slug: str) -> str:
    """'ica-supermarket-vagnharad-1004281' -> 'ICA Supermarket Vagnharad' (förslag; å/ä/ö saknas i sluggen)."""
    ord_ = [o for o in slug.split("-") if o and not o.isdigit()]
    return " ".join(o.upper() if o == "ica" else o.capitalize() for o in ord_) or slug


def tolka_heltal(text: str) -> list[int]:
    return [int(x) for x in re.split(r"[,\s]+", text.strip()) if x]


def tolka_dagar(text: str) -> list[str]:
    dagar = [d.lower() for d in re.split(r"[,\s]+", text.strip()) if d]
    if okanda := [d for d in dagar if d not in VECKODAGAR]:
        raise ValueError(f"okänd dag: {', '.join(okanda)}")
    return dagar


# ---------- frågor ----------

class Fragor:
    """Frågor med standardsvar (Enter = standard). `inmatning` och `losen` kan bytas ut i tester."""

    def __init__(self, inmatning: Callable[[str], str] = input, losen: Callable[[str], str] = getpass.getpass,
                 skriv: Callable[[str], None] = print):
        self.inmatning, self.losen, self.skriv = inmatning, losen, skriv

    def text(self, fraga: str, standard: str = "") -> str:
        svar = self.inmatning(f"{fraga}{f' [{standard}]' if standard else ''}: ").strip()
        return svar or standard

    def heltal(self, fraga: str, standard: int, minst: int = 0) -> int:
        while True:
            svar = self.text(fraga, str(standard))
            if svar.isdigit() and int(svar) >= minst:
                return int(svar)
            self.skriv(f"  Svara med ett heltal (minst {minst}).")

    def ja(self, fraga: str, standard: bool = True) -> bool:
        while True:
            svar = self.inmatning(f"{fraga} [{'J/n' if standard else 'j/N'}]: ").strip().lower()
            if not svar:
                return standard
            if svar in ("j", "ja", "y", "yes"):
                return True
            if svar in ("n", "nej", "no"):
                return False

    def val(self, fraga: str, alternativ: list[str], standard: int = 1) -> int:
        """Numrerad lista; returnerar index (0-baserat)."""
        for i, a in enumerate(alternativ, 1):
            self.skriv(f"  {i}. {a}")
        while True:
            svar = self.text(fraga, str(standard))
            if svar.isdigit() and 1 <= int(svar) <= len(alternativ):
                return int(svar) - 1
            self.skriv(f"  Välj ett nummer mellan 1 och {len(alternativ)}.")


def hitta_butiker(ort: str) -> list[Butik]:
    """Willys- och Hemköp-butiker med e-handel (hämtning) på orten."""
    from .stores import hemkop, willys

    butiker = []
    for kedja, modul in (("willys", willys), ("hemkop", hemkop)):
        try:
            resultat = modul.find_stores(ort)
        except Exception:
            continue
        for s in resultat:
            if s.get("clickAndCollect") and s.get("storeId"):
                butiker.append(Butik(kedja, str(s["storeId"]), s.get("name") or s.get("displayName") or str(s["storeId"])))
    return butiker


def fraga_butik(f: Fragor, sok: Callable[[str], list[Butik]] = hitta_butiker) -> Butik:
    f.skriv("\n— Butik —\nKorgen fylls i Willys eller Hemköps e-handel (båda ägs av Axfood och fungerar likadant).")
    while True:
        ort = f.text("Vilken ort handlar du i?")
        butiker = sok(ort) if ort else []
        if butiker:
            f.skriv(f"Butiker med e-handel i {ort}:")
            i = f.val("Välj butik", [f"{b.namn} ({'Willys' if b.kedja == 'willys' else 'Hemköp'})" for b in butiker])
            return butiker[i]
        f.skriv(f"Hittade ingen Willys eller Hemköp med e-handel i {ort or '(tom ort)'}. Prova en närliggande ort,"
                " eller skriv butikens id direkt (finns i adressen på butikens sida).")
        if f.ja("Ange butiks-id själv?", False):
            kedja = ("willys", "hemkop")[f.val("Kedja", ["Willys", "Hemköp"])]
            store_id = f.text("Butikens id (t.ex. 2341)")
            return Butik(kedja, store_id, f.text("Butikens namn", f"{'Willys' if kedja == 'willys' else 'Hemköp'} {store_id}"))


def fraga_ica(f: Fragor) -> list[dict]:
    f.skriv("\n— ICA (valfritt) —\n"
            "ICA-butikernas veckokampanjer kan jämföras med korgen; billigare ICA-varor flaggas i rapporten.\n"
            "Butikerna går inte att söka fram automatiskt (ica.se blockerar det), så klistra in adressen till\n"
            "butikens erbjudandesida: gå till ica.se/butiker, välj butiken och sedan Erbjudanden. Adressen ser ut\n"
            "som https://www.ica.se/erbjudanden/ica-supermarket-exempel-12345/. Tom rad = klart.\n"
            "ICA svarar 403 till GitHub Actions, så butikerna hämtas som standard bara när du kör på datorn\n"
            "(bara_lokalt: true).")
    butiker = []
    while True:
        adress = f.text("Erbjudandesida eller slug (Enter = klart)")
        if not adress:
            return butiker
        slug = ica_slug(adress)
        namn = f.text("Butikens namn", ica_namn(slug))
        lokalt = f.ja("Hämta bara på datorn (rekommenderas, ICA blockerar molnet)?", True)
        butiker.append({"namn": namn, "erbjudande_slug": slug, **({"bara_lokalt": True} if lokalt else {})})


def fraga_hushall(f: Fragor, s: Svar) -> None:
    f.skriv("\n— Hushåll —")
    s.vuxna = f.heltal("Antal vuxna", 2, minst=1)
    while True:
        try:
            s.barn = tolka_heltal(f.text("Barnens åldrar, t.ex. 9, 7 (Enter = inga barn)"))
            break
        except ValueError:
            f.skriv("  Skriv åldrarna som tal separerade med komma.")
    s.middagar = f.heltal("Middagar per vecka", 5, minst=1)
    s.onskemal = f.text("Önskemål om maten i fritext (Enter = exemplets: barnvänligt, fisk och vegetariskt varje vecka)")
    if f.ja("Laga extra portioner till matlådor vissa dagar?", False):
        while True:
            try:
                s.matlador_dagar = tolka_dagar(f.text("Vilka dagar", "tisdag, torsdag"))
                break
            except ValueError as e:
                f.skriv(f"  {e}")
        s.matlador_extra = f.heltal("Extra portioner de dagarna", 2, minst=1)


def fraga_undvik(f: Fragor, s: Svar) -> None:
    f.skriv("\n— Undvik —\nFörval fyller i både hårda krav till Claude och spärrord som koden filtrerar på.")
    nycklar = list(UNDVIK_VAL)
    for i, k in enumerate(nycklar, 1):
        f.skriv(f"  {i}. {UNDVIK_NAMN[k]}")
    while True:
        svar = f.text("Välj förval med nummer, t.ex. 1 3 (Enter = inga)")
        try:
            valda = tolka_heltal(svar)
            s.undvik_val = [nycklar[i - 1] for i in valda if 1 <= i <= len(nycklar)]
            if len(s.undvik_val) == len(valda):
                break
        except ValueError:
            pass
        f.skriv(f"  Skriv nummer mellan 1 och {len(nycklar)}.")
    if "laktosfritt" in s.undvik_val:
        f.skriv("  Laktosfritt blir bara ett krav till Claude: ordfilter på \"laktos\" eller \"mjölk\" skulle\n"
                "  stoppa även laktosfria varor.")
    egen = f.text("Annat att undvika, separerat med semikolon (Enter = inget)")
    s.undvik_egen = [x for x in (e.strip() for e in egen.split(";")) if x]


def fraga_lage(f: Fragor, s: Svar) -> None:
    f.skriv("\n— Läge —\n"
            "  auto: boten gör en färdig meny varje vecka och lägger allt i korgen.\n"
            "  val:  boten föreslår tio rätter, du väljer vilka (t.ex. ./fyll.sh 2 4 5 8 9) och får korgen för dem.")
    s.lage = ("auto", "val")[f.val("Läge", ["auto", "val"])]


def fraga_mejl(f: Fragor, s: Svar, env: Path) -> None:
    f.skriv("\n— Mejl —\nVeckans rapport mejlas. Med Gmail behövs ett app-lösenord "
            "(https://myaccount.google.com/apppasswords).")
    while True:
        s.epost = f.text("Din e-postadress")
        if "@" in s.epost:
            break
        f.skriv("  Ange en e-postadress.")
    s.smtp_host = f.text("SMTP-server", "smtp.gmail.com")
    losen = f.losen("App-lösenord (visas inte; Enter = hoppa över och lägg till senare i .env): ").strip()
    if losen:
        skriv_env(env, "SMTP_PASSWORD", losen)
        f.skriv(f"  Lösenordet är sparat i {env}.")


def fraga_claude(f: Fragor, s: Svar) -> None:
    from . import kontroll

    f.skriv("\n— Claude —")
    p = kontroll.claude()
    f.skriv(p.rad())
    if p.status != kontroll.OK:
        f.skriv("  Claude behövs för menyn. Antingen Claude Code med ett Pro- eller Max-abonnemang\n"
                "  (npm install -g @anthropic-ai/claude-code, sedan `claude` och logga in), eller en\n"
                "  ANTHROPIC_API_KEY i .env (betalas per token). Du kan ordna det efter installationen.")
    s.billiga_modeller = f.ja("Börja billigt: Sonnet för menyn och Haiku för produktvalet?", True)


# ---------- hela guiden ----------

def kor_guiden(f: Fragor, config: Path, exempel: Path, env: Path, svar: Svar | None = None,
               sok: Callable[[str], list[Butik]] = hitta_butiker, skriv_over: bool | None = None) -> bool:
    """Ställ frågorna (om inga svar ges) och skriv config.yaml. Returnerar False om användaren avbröt."""
    if svar is None:
        f.skriv("Veckohandla – installation. Enter väljer standardsvaret inom hakparentes.")
        s = Svar(butik=fraga_butik(f, sok))
        s.ica = fraga_ica(f)
        fraga_hushall(f, s)
        fraga_undvik(f, s)
        fraga_lage(f, s)
        fraga_mejl(f, s, env)
        fraga_claude(f, s)
    else:
        s = svar
    if config.exists():
        if skriv_over is None:
            skriv_over = f.ja(f"\n{config} finns redan. Skriva över den (en kopia sparas som config.yaml.bak)?", False)
        if not skriv_over:
            f.skriv("Avbrutet – config.yaml är orörd.")
            return False
        shutil.copy2(config, config.with_name("config.yaml.bak"))
        f.skriv(f"Kopia sparad: {config.with_name('config.yaml.bak')}")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(bygg_config(exempel.read_text(), s))
    f.skriv(f"\nSkrev {config}")
    return True


def nasta_steg(skriv: Callable[[str], None], login_klar: bool) -> None:
    steg = [] if login_klar else ["Logga in hos e-handelskedjan en gång: python -m veckohandla login"]
    steg += [
        "Kontrollera alltid_kop, gar_alltid_at och skafferi i config.yaml (exemplets varor ligger kvar)",
        "Testkör utan mejl: python -m veckohandla kor --ingen-mejl (rapporten hamnar i data/)",
        "Fyll korgen: python -m veckohandla fyll-varukorg – granska den sedan på webbplatsen och beställ själv",
        "Vill du köra i molnet varje vecka: se mallen sinj4/veckohandla-mall",
    ]
    skriv("\nNästa steg:")
    for i, t in enumerate(steg, 1):
        skriv(f"  {i}. {t}")

