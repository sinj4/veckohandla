"""Hela veckokörningen: kampanjer → meny → produktval → prisjämförelse → (varukorg) → rapport."""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .models import Offer, Product
from .planner import Inkopsrad, Planner, Val, Veckoplan, gar_alltid_at_rad
from . import ingredienser
from .stores import ica, willys

# Kan bytas ut i tester (monkeypatch pipeline.DATA) eller via miljövariabeln VECKOHANDLA_DATA
DATA = Path(os.environ.get("VECKOHANDLA_DATA") or Path(__file__).resolve().parent.parent / "data")

# Veckoplaner heter t.ex. 2026-v42.json; korgfiler (2026-v42-korg.json) och cache ska inte matcha
PLAN_GLOB = "*-v[0-9][0-9].json"
KORG_GLOB = "*-v[0-9][0-9]-korg.json"


@dataclass
class Alternativ:
    product: Product
    qty: int


@dataclass
class Line:
    row: Inkopsrad
    product: Product | None
    qty: int
    willys_cost: float | None
    butik: Val | None = None  # satt om varan ska köpas i en butik (ICA eller Willys i butik) i stället för e-handeln
    alternativ: list[Alternativ] = field(default_factory=list)  # huvudval + reserver, i prövningsordning
    bortvalda: list[tuple[Alternativ, str]] = field(default_factory=list)  # (alternativ, orsak) som föll bort
    reserver: list[Alternativ] = field(default_factory=list)  # kvar efter valet – prövas om Willys nekar
    borttagen: str | None = None  # alla alternativ föll bort – köp manuellt
    kontrollera: bool = False  # kött/chark/färdigmat utan ingrediensuppgift
    tillganglighet_okand: bool = False  # tillgänglighetskontrollen gav inget svar – varan antas finnas
    storpack: bool = False  # varan går alltid åt – valt alternativ har lägst jämförpris

    @property
    def forsta_val(self) -> Product | None:
        return self.alternativ[0].product if self.alternativ else self.product

    @property
    def bytt(self) -> bool:
        return self.product is not None and bool(self.bortvalda)

    @property
    def i_butik(self) -> bool:
        return self.butik is not None


@dataclass
class Result:
    week: str
    plan: Veckoplan
    lines: list[Line]
    willys_namn: str = "Willys"
    willys_i_butik_namn: str = "Willys (i butik)"
    hamtar_i_butik: bool = False
    butik_listor: dict[str, list[Line]] = field(default_factory=dict)
    willys_total: float = 0.0
    butik_total: float = 0.0
    butik_besparing: dict[str, float] = field(default_factory=dict)
    cart: dict | None = None
    cart_error: str | None = None  # t.ex. att Willys-inloggningen gått ut
    varningar: list[str] = field(default_factory=list)
    offers_count: dict[str, int] = field(default_factory=dict)


def week_id(today: dt.date | None = None) -> str:
    y, w, _ = (today or dt.date.today()).isocalendar()
    return f"{y}-v{w:02d}"


def previous_dishes(weeks: int = 3) -> list[str]:
    current = week_id()
    files = [f for f in sorted(DATA.glob(PLAN_GLOB)) if f.stem != current][-weeks:]
    dishes = []
    for f in files:
        dishes += [m["ratt"] for m in json.loads(f.read_text())["middagar"]]
    return dishes


def _blocked(name: str, words: list[str]) -> bool:
    n = name.lower()
    return any(w in n for w in words)


# Används om optimering.uteslut_kategorier saknas i config. Willys: första ledet i
# googleAnalyticsCategory, ICA: articleGroupName. Jämförs utan hänsyn till versaler.
UTESLUT_KATEGORIER = [
    "halsa-och-skonhet", "hem-och-stad", "djur", "blommor-och-tradgard",
    "Hälsa & skönhet", "Hem & fritid",
]


def filtrera_kategorier(offers: list[Offer], uteslut: list[str]) -> list[Offer]:
    """Ta bort kampanjer i kategorier som inte är mat (hygien, städ, djurmat …)."""
    bort = {k.lower() for k in uteslut}
    return [o for o in offers if o.category.split("|")[0].strip().lower() not in bort]


MAX_RESERVER = 3


def provningsordning(val: Val | None, kandidater: list[Product]) -> list[Alternativ]:
    """Huvudval följt av högst 3 reserver – bara koder som finns bland radens kandidater.

    Antalet justeras med best_qty för respektive produkt (mängdkampanjer).
    """
    if val is None or not val.willys_kod:
        return []
    by_code = {p.code: p for p in kandidater}
    ordning = [(val.willys_kod, val.willys_antal)] + [(r.kod, r.antal) for r in val.willys_reserver[:MAX_RESERVER]]
    out: list[Alternativ] = []
    for kod, antal in ordning:
        p = by_code.get(kod)
        if p and all(a.product.code != kod for a in out):
            out.append(Alternativ(p, p.best_qty(max(1, antal))))
    return out


def valj_alternativ(
    alternativ: list[Alternativ],
    finns: Callable[[str], bool | None],
    ingredienser_ok: Callable[[str], ingredienser.Kontroll] | None,
) -> tuple[Alternativ | None, list[tuple[Alternativ, str]], bool, bool]:
    """Pröva alternativen i ordning: först tillgänglighet i butiken, sedan ingredienser.

    `finns` ger True/False, eller None om det inte gick att avgöra – då antas varan finnas.
    Returnerar (valt alternativ eller None, bortvalda med orsak, kontrollera-flagga,
    tillgänglighet-okänd-flagga). Ingredienser hämtas bara för alternativ som faktiskt prövas.
    """
    bortvalda: list[tuple[Alternativ, str]] = []
    for alt in alternativ:
        tillganglig = finns(alt.product.code)
        if tillganglig is False:
            bortvalda.append((alt, "finns inte i butiken"))
            continue
        kontrollera = False
        if ingredienser_ok:
            k = ingredienser_ok(alt.product.code)
            if k.status == "borttagen":
                bortvalda.append((alt, f"innehåller {k.ord}"))
                continue
            kontrollera = k.status == "kontrollera"
        return alt, bortvalda, kontrollera, tillganglig is None
    return None, bortvalda, False, False


def valj_storpack(
    alternativ: list[Alternativ],
    finns: Callable[[str], bool | None],
    ingredienser_ok: Callable[[str], ingredienser.Kontroll] | None,
) -> tuple[Alternativ | None, list[tuple[Alternativ, str]], bool, bool]:
    """För varor som alltid går åt: bland alternativen som klarar tillgänglighet och ingredienser väljs
    det med lägst jämförpris. Bara alternativ med samma jämförenhet som det första godkända jämförs.

    Returnerar samma fyrtupel som valj_alternativ.
    """
    godkanda: list[tuple[Alternativ, bool, bool]] = []
    bortvalda: list[tuple[Alternativ, str]] = []
    rest = list(alternativ)
    while rest:
        valt, bort, kolla, okand = valj_alternativ(rest, finns, ingredienser_ok)
        bortvalda += bort
        if valt is None:
            break
        godkanda.append((valt, kolla, okand))
        rest = rest[rest.index(valt) + 1:]
    if not godkanda:
        return None, bortvalda, False, False
    enhet = godkanda[0][0].product.jamfor_enhet
    jamforbara = [g for g in godkanda if g[0].product.jamfor_enhet == enhet and g[0].product.jamforpris is not None]
    basta = min(jamforbara, key=lambda g: g[0].product.jamforpris) if jamforbara else godkanda[0]
    return basta[0], bortvalda, basta[1], basta[2]


def godkanda_reserver(
    reserver: list[Alternativ],
    ingredienser_ok: Callable[[str], ingredienser.Kontroll] | None,
) -> list[Alternativ]:
    """Reserver som sparas till korgfyllningen måste klara ingredienskontrollen (tillgängligheten
    avgör Willys när varan läggs i korgen)."""
    if not ingredienser_ok:
        return list(reserver)
    return [r for r in reserver if ingredienser_ok(r.product.code).status != "borttagen"]


def berakna_butikskostnad(v: Val, offers_by_code: dict[str, Offer]) -> None:
    """Räkna kostnaden för en Willys-butikskampanj i koden ur kampanjen (pris per st, "2 för X",
    max per hushåll). Claudes uppskattning behålls bara om kampanjen inte går att tolka."""
    offer = offers_by_code.get(v.butik_kod or "")
    kostnad = offer.kostnad(v.butik_antal) if offer else None
    if kostnad is not None:
        v.butik_kostnad_kr = kostnad
        v.butik_erbjudande = f"{offer.name} {offer.size}: {offer.deal}".strip()
        v.butik_kostnad_beraknad = True


def tillampa_butikstroskel(
    lines: list[Line], threshold: float | Callable[[str], float]
) -> tuple[dict[str, list[Line]], dict[str, float]]:
    """Behåll en butikslista (ICA eller Willys i butik) bara om den sparar minst tröskeln i kr.

    `threshold` är ett belopp eller en funktion butiksnamn -> belopp. Rader där butiken inte är
    billigare än e-handeln flyttas alltid tillbaka. Under tröskeln flyttas rader med Willys-alternativ
    tillbaka till e-handeln (l.butik = None); bara rader utan alternativ blir kvar på butikslistan.
    Ändrar `lines` på plats.
    """
    troskel = threshold if callable(threshold) else (lambda store: threshold)
    for l in lines:
        if l.i_butik and l.willys_cost is not None and l.butik.butik_kostnad_kr >= l.willys_cost:
            l.butik = None
    butik_listor: dict[str, list[Line]] = {}
    butik_besparing: dict[str, float] = {}
    for store in sorted({l.butik.butik for l in lines if l.i_butik}):
        threshold = troskel(store)
        store_lines = [l for l in lines if l.i_butik and l.butik.butik == store]
        saving = sum((l.willys_cost or 0) - l.butik.butik_kostnad_kr for l in store_lines if l.willys_cost)
        if saving < threshold:
            for l in store_lines:
                if l.product:
                    l.butik = None
            store_lines = [l for l in store_lines if l.product is None]
        if store_lines:
            butik_listor[store] = store_lines
            butik_besparing[store] = round(saving if saving >= threshold else 0.0, 2)
    return butik_listor, butik_besparing


def willys_i_butik_namn(cfg: dict) -> str:
    return f"{cfg['butiker']['willys']['namn']} (i butik)"


def butikens_troskel(cfg: dict) -> Callable[[str], float]:
    """Besparingströskel per butik. Hämtas e-handelsordern i Willys-butiken krävs ingen tröskel för
    butikens egna kampanjer – de köps ändå på plats."""
    w = cfg["butiker"]["willys"]
    opt = cfg.get("optimering", {})
    i_butik = willys_i_butik_namn(cfg)

    def troskel(store: str) -> float:
        if store == i_butik:
            return 0.0 if w.get("hamtar_i_butik", False) else opt.get("min_besparing_willys_i_butik_kr", 40)
        return opt.get("min_besparing_for_delning_kr", 75)

    return troskel


def fetch_all_offers(cfg: dict, varningar: list[str] | None = None) -> list[Offer]:
    """Willys e-handelsfel stoppar körningen; butikskampanjer och ICA-butiker som fallerar hoppas över
    med en varning."""
    stores = cfg["butiker"]
    w = stores["willys"]
    offers = willys.fetch_offers(w["store_id"], w["namn"])
    if w.get("i_butik", True):
        try:
            online = {o.code for o in offers if o.code}
            # Varor med kampanj även i e-handeln köps där – bara rena butikskampanjer behålls
            offers += [o for o in willys.fetch_offers(w["store_id"], willys_i_butik_namn(cfg), kanal="offline")
                       if o.code not in online]
        except Exception as e:
            if varningar is None:
                raise
            varningar.append(f"Kunde inte hämta Willys butikskampanjer: {e}")
    for s in stores.get("ica", []):
        try:
            offers += ica.fetch_offers(s["erbjudande_slug"], s["namn"])
        except Exception as e:  # nätverk, ändrad sida m.m.
            if varningar is None:
                raise
            varningar.append(f"Kunde inte hämta kampanjer från {s['namn']}: {e}")
    return offers


def run(cfg: dict, fill_cart: bool = False, log=print) -> Result:
    # En anonym Willys-session per körning med rätt butik vald – sortimentet styrs av sessionens butik.
    # Butiken väljs först, innan något Claude-anrop görs.
    varningar: list[str] = []
    with willys.WillysSession(cfg["butiker"]["willys"]["store_id"]) as sess:
        log("Väljer Willys-butik…")
        try:
            sess.valj_butik()
        except Exception as e:
            varningar.append(f"Kunde inte välja butik, sökningen gäller hela Willys sortiment ({e})")
            log(f"  VARNING: {varningar[-1]}")
        return _run(cfg, sess, fill_cart, log, varningar)


class AllaSokningarMisslyckades(RuntimeError):
    pass


def _run(cfg: dict, sess: willys.WillysSession, fill_cart: bool, log, varningar: list[str] | None = None) -> Result:
    c = cfg["claude"]
    planner = Planner(c.get("model_meny") or c["model"], c.get("model_produkter") or c["model"])
    willys_name = cfg["butiker"]["willys"]["namn"]

    log("Hämtar veckans kampanjer…")
    varningar = varningar if varningar is not None else []
    fore_kampanjer = len(varningar)
    offers = fetch_all_offers(cfg, varningar)
    for v in varningar[fore_kampanjer:]:
        log(f"  VARNING: {v}")
    sparrord = [w.lower() for w in cfg["hushall"].get("sparrord", [])]
    offers = [o for o in offers if not _blocked(f"{o.name} {o.brand}", sparrord)]
    uteslut = cfg.get("optimering", {}).get("uteslut_kategorier", UTESLUT_KATEGORIER)
    fore = len(offers)
    offers = filtrera_kategorier(offers, uteslut)
    log(f"  {fore - len(offers)} kampanjer som inte är mat filtrerades bort")
    counts: dict[str, int] = {}
    for o in offers:
        counts[o.store] = counts.get(o.store, 0) + 1
    log("  " + ", ".join(f"{k}: {v}" for k, v in counts.items()))

    log("Planerar veckomeny med Claude…")
    plan = planner.plan_week(offers, cfg, previous_dishes())
    for m in plan.middagar:
        log(f"  {m.dag}: {m.ratt}")

    rows = list(plan.inkopslista) + [
        Inkopsrad(vara=a["namn"], behov=f"{a['antal']} st", sokord=a["namn"], till=["basvara"])
        for a in cfg.get("alltid_kop", [])
    ]

    # Utan vald butik söks hela sortimentet; reserver och failed-hanteringen tar hand om det som saknas
    sok = sess.search if sess.butik_vald else willys.search
    log(f"Söker {len(rows)} varor i Willys sortiment{'' if sess.butik_vald else ' (utan vald butik)'}…")
    candidates: list[list[Product]] = []
    misslyckade = 0
    senaste_fel: Exception | None = None
    for r in rows:
        try:
            found = sok(r.sokord, willys_name)
            if not found and r.vara.lower() != r.sokord.lower():
                found = sok(r.vara, willys_name)
            candidates.append([p for p in found if not _blocked(p.name, sparrord)])
        except Exception as e:  # en enskild sökning ska inte stoppa hela körningen
            log(f"  sökning misslyckades för {r.sokord!r}: {e}")
            candidates.append([])
            misslyckade += 1
            senaste_fel = e
        time.sleep(0.5)
    if rows and misslyckade == len(rows):
        raise AllaSokningarMisslyckades(
            f"Alla {len(rows)} sökningar mot Willys misslyckades – avbryter innan produktvalet. "
            f"Senaste fel: {senaste_fel}"
        )

    log("Väljer produkter och jämför med butikskampanjer…")
    butiks_offers = [o for o in offers if o.store != willys_name]
    gar_alltid_at = cfg["hushall"].get("gar_alltid_at", [])
    choice = planner.choose_products(rows, candidates, butiks_offers, cfg["hushall"].get("undvik", []), gar_alltid_at)

    i_butik_namn = willys_i_butik_namn(cfg)
    i_butik_offers = {o.code: o for o in butiks_offers if o.store == i_butik_namn and o.code}
    by_row = {v.rad: v for v in choice.val}
    lines: list[Line] = []
    for i, r in enumerate(rows):
        v = by_row.get(i)
        if v and v.butik == i_butik_namn:
            berakna_butikskostnad(v, i_butik_offers)
        alt = provningsordning(v, candidates[i])
        prod, qty = (alt[0].product, alt[0].qty) if alt else (None, 0)
        lines.append(
            Line(row=r, product=prod, qty=qty, willys_cost=prod.cost(qty) if prod else None,
                 butik=v if v and v.butik and v.butik_kostnad_kr is not None else None, alternativ=alt)
        )

    # Ett butiksbesök lönar sig bara om det sparar tillräckligt – annars köps allt i e-handeln
    result = Result(week=week_id(), plan=plan, lines=lines, offers_count=counts, varningar=varningar,
                    willys_namn=willys_name, willys_i_butik_namn=i_butik_namn,
                    hamtar_i_butik=cfg["butiker"]["willys"].get("hamtar_i_butik", False))
    result.butik_listor, result.butik_besparing = tillampa_butikstroskel(lines, butikens_troskel(cfg))

    ingr_ord = sparrord + [w.lower() for w in cfg["hushall"].get("sparrord_ingredienser", [])]
    willys_lines = [l for l in lines if l.alternativ and not l.i_butik]
    if willys_lines:
        log("Kontrollerar tillgänglighet i butiken och ingredienser…")
        with ingredienser.Ingredienskontroll(ingr_ord, DATA / "ingredienser-cache.json") as ik:
            sidor = Produktsidor(sess, ik)
            ik.hamta = sidor.detaljer  # samma GET för tillgänglighet och ingredienser
            ingr = ik.kontrollera if ingr_ord else None
            for l in willys_lines:
                l.storpack = gar_alltid_at_rad(l.row, gar_alltid_at)
                valj = valj_storpack if l.storpack else valj_alternativ
                valt, l.bortvalda, l.kontrollera, l.tillganglighet_okand = valj(l.alternativ, sidor.finns, ingr)
                if valt is None:
                    l.product, l.qty, l.willys_cost = None, 0, None
                    l.borttagen = "; ".join(f"{a.product.name}: {orsak}" for a, orsak in l.bortvalda)
                    log(f"  Köp manuellt: {l.row.vara} ({l.borttagen})")
                    continue
                l.product, l.qty, l.willys_cost = valt.product, valt.qty, valt.product.cost(valt.qty)
                if l.bortvalda:
                    log(f"  Bytt: {l.forsta_val.name} → {valt.product.name} ({l.bortvalda[0][1]})")
                if l.storpack:  # övriga godtagbara storlekar blir reserver, i ordning
                    bort = {a.product.code for a, _ in l.bortvalda}
                    rest = [a for a in l.alternativ if a is not valt and a.product.code not in bort]
                else:
                    rest = l.alternativ[l.alternativ.index(valt) + 1:]
                l.reserver = godkanda_reserver(rest, ingr)

    result.willys_total = round(
        sum(l.willys_cost or 0 for l in lines if l.product and not l.i_butik and not l.row.kanske_hemma), 2
    )
    result.butik_total = round(sum(l.butik.butik_kostnad_kr for l in lines if l.i_butik), 2)

    cart_lines = [
        {**_korgrad(l.product, l.qty), "reserver": [_korgrad(a.product, a.qty) for a in l.reserver]}
        for l in lines
        if l.product and not l.i_butik and not l.row.kanske_hemma and l.qty > 0
    ]
    DATA.mkdir(exist_ok=True)
    (DATA / f"{result.week}.json").write_text(plan.model_dump_json(indent=2))
    (DATA / f"{result.week}-korg.json").write_text(json.dumps(cart_lines, ensure_ascii=False, indent=2))

    if fill_cart:
        from .cart import NotLoggedIn

        try:
            result.cart = fill_saved_cart(result.week, log)
        except NotLoggedIn as e:
            # Rapporten och mejlet ska ändå komma fram – korgen kan fyllas i efterhand
            log(str(e))
            result.cart_error = (
                "Willys-inloggningen har gått ut. Kör `python -m veckohandla login` och sedan "
                f"`python -m veckohandla fyll-varukorg {result.week}`."
            )
    return result


def _korgrad(p: Product, qty: int) -> dict:
    return {"code": p.code, "qty": qty, "pick_unit": p.extra.get("pickUnit", "pieces"), "name": p.name, "size": p.size}


class Produktsidor:
    """Högst ett GET mot /axfood/rest/p/<kod> per produkt och körning.

    Tillgänglighetsanropet lägger ingredienser och kategori i ingredienscachen, så att
    ingredienskontrollen inte hämtar samma sida igen. Svaren sparas bara under körningen –
    tillgängligheten cachas aldrig mellan körningar.
    """

    PAUS_S = 0.5

    def __init__(self, sess: willys.WillysSession, ik: ingredienser.Ingredienskontroll):
        self.sess, self.ik = sess, ik
        self._svar: dict[str, tuple[bool | None, dict | None]] = {}

    def _hamta(self, code: str) -> tuple[bool | None, dict | None]:
        if code not in self._svar:
            self._svar[code] = finns, d = self.sess.kolla(code)
            if d is not None:
                self.ik.lagg_in(code, d)
            time.sleep(self.PAUS_S)  # var snäll mot Willys
        return self._svar[code]

    def finns(self, code: str) -> bool | None:
        if not self.sess.butik_vald:
            return True  # utan vald butik säger tillgängligheten inget
        return self._hamta(code)[0]

    def detaljer(self, code: str) -> dict:
        d = self._hamta(code)[1]
        if d is None:
            raise LookupError(f"Kunde inte läsa produktsidan för {code}")
        return d


class IngenKorg(RuntimeError):
    pass


def latest_cart_week() -> str:
    """Senaste veckan som har en sparad korgfil, t.ex. '2026-v42'."""
    files = sorted(DATA.glob(KORG_GLOB))
    if not files:
        raise IngenKorg(f"Hittade ingen sparad korg i {DATA} – kör först: python -m veckohandla kor")
    return files[-1].stem.removesuffix("-korg")


def fill_saved_cart(week: str, log=print) -> dict:
    """Lägg en sparad veckas inköpslista i Willys-varukorgen (utan att planera om)."""
    from .cart import fill_willys

    saved = json.loads((DATA / f"{week}-korg.json").read_text())
    log(f"Lägger {len(saved)} varor i Willys-varukorgen…")
    return fill_willys([_cartline(x) for x in saved])


def _cartline(x: dict):
    from .cart import CartLine

    return CartLine(x["code"], x["qty"], x["pick_unit"], x.get("name", ""), x.get("size", ""),
                    reserver=[_cartline(r) for r in x.get("reserver", [])])
