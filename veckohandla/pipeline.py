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
from . import ingredienser, lager
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
    butik: Val | None = None  # billigare alternativ i en butik (ICA eller Willys i butik) – varan ligger ändå i korgen
    alternativ: list[Alternativ] = field(default_factory=list)  # huvudval + reserver, i prövningsordning
    bortvalda: list[tuple[Alternativ, str]] = field(default_factory=list)  # (alternativ, orsak) som föll bort
    reserver: list[Alternativ] = field(default_factory=list)  # kvar efter valet – prövas om Willys nekar
    borttagen: str | None = None  # alla alternativ föll bort – köp manuellt
    kontrollera: bool = False  # kött/chark/färdigmat utan ingrediensuppgift
    tillganglighet_okand: bool = False  # tillgänglighetskontrollen gav inget svar – varan antas finnas
    storpack: bool = False  # varan går alltid åt – valt alternativ har lägst jämförpris
    butik_stoppad: str | None = None  # butikskampanjen stoppades av ingredienskontrollen, t.ex. "innehåller gris"
    butik_kontrollera: bool = False  # butiksraden saknar ingrediensuppgift i kött-, chark- eller färdigmatskategori
    butik_spar: float | None = None  # vad butiksalternativet sparar mot korgens pris
    flaggad: bool = False  # butikens samlade besparing når tröskeln – visas som "Billigare i butik"
    gar_alltid_at: str | None = None  # matchad post i hushall.gar_alltid_at (sparas i korgfilen)
    lager_kvar: float | None = None  # uppskattat lager som räcker veckan ut – köps inte

    @property
    def forsta_val(self) -> Product | None:
        return self.alternativ[0].product if self.alternativ else self.product

    @property
    def bytt(self) -> bool:
        return self.product is not None and bool(self.bortvalda)

    @property
    def i_korgen(self) -> bool:
        return self.product is not None and not self.row.kanske_hemma and self.qty > 0

    @property
    def kop_i_butik(self) -> bool:
        """Ingen Willys-produkt men ett butiksalternativ – kan inte ligga i korgen."""
        return self.butik is not None and self.product is None and not self.row.kanske_hemma


@dataclass
class Result:
    week: str
    plan: Veckoplan
    lines: list[Line]
    willys_namn: str = "Willys"
    willys_i_butik_namn: str = "Willys (i butik)"
    butik_flaggor: dict[str, list[Line]] = field(default_factory=dict)  # butik -> flaggade korgrader
    butik_besparing: dict[str, float] = field(default_factory=dict)  # butik -> samlad besparing (flaggade)
    kop_i_butik: dict[str, list[Line]] = field(default_factory=dict)  # butik -> rader utan Willys-produkt
    willys_total: float = 0.0  # korgens pris
    med_butiksalternativ: float = 0.0  # korgens pris om alla flaggade butiksalternativ tas
    kop_i_butik_total: float = 0.0
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


def enhetspris_for_val(alt: Alternativ, log=None) -> float | None:
    """Effektivt pris per enhet för alternativets antal; jämförpriset om det inte går att räkna."""
    pris = alt.product.effektivt_enhetspris(alt.qty)
    if pris is None and alt.product.jamforpris is not None:
        if log:
            log(f"  Storpack: kan inte räkna enheter per förpackning för {alt.product.name} – använder jämförpriset")
        return alt.product.jamforpris
    return pris


def valj_storpack(
    alternativ: list[Alternativ],
    finns: Callable[[str], bool | None],
    ingredienser_ok: Callable[[str], ingredienser.Kontroll] | None,
    log=None,
) -> tuple[Alternativ | None, list[tuple[Alternativ, str]], bool, bool]:
    """För varor som alltid går åt: bland alternativen som klarar tillgänglighet och ingredienser väljs
    det med lägst effektivt pris per enhet för det antal som köps (se enhetspris_for_val). Bara
    alternativ med samma jämförenhet som det första godkända jämförs.

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
    priser = {id(g[0]): enhetspris_for_val(g[0], log) for g in godkanda if g[0].product.jamfor_enhet == enhet}
    jamforbara = [g for g in godkanda if priser.get(id(g[0])) is not None]
    basta = min(jamforbara, key=lambda g: priser[id(g[0])]) if jamforbara else godkanda[0]
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


def giltigt_butiksval(v: Val, butiks_offers: list[Offer]) -> bool:
    """Finns paret butik + butik_kod bland just den butikens kampanjer, och är antalet minst 1?"""
    if not v.butik_kod or not v.butik_antal or v.butik_antal < 1:
        return False
    return any(o.store == v.butik and o.code == v.butik_kod for o in butiks_offers)


def berakna_butikskostnad(v: Val, offers_by_code: dict[str, Offer]) -> None:
    """Räkna kostnaden för en Willys-butikskampanj i koden ur kampanjen (pris per st, "2 för X",
    max per hushåll). Claudes uppskattning behålls bara om kampanjen inte går att tolka."""
    offer = offers_by_code.get(v.butik_kod or "")
    kostnad = offer.kostnad(v.butik_antal) if offer else None
    if kostnad is not None:
        v.butik_kostnad_kr = kostnad
        v.butik_erbjudande = f"{offer.name} {offer.size}: {offer.deal}".strip()
        v.butik_kostnad_beraknad = True


# ICA:s expandedArticleGroupId för kött (6), chark (16), färdiga såser/gratänger (14) och djupfryst (5)
ICA_RISK_KATEGORIER = {5, 6, 14, 16}


def kontrollera_butiksrader(
    lines: list[Line],
    i_butik_namn: str,
    kampanjer: dict[tuple[str, str], Offer],
    ik: ingredienser.Ingredienskontroll,
    log=print,
) -> None:
    """Samma fläskskydd för butiksalternativen som för korgen.

    Willys i butik: ingredienserna för butik_kod kontrolleras (samma cache, samma GET-minne). Träff ->
    butiksalternativet tas bort (e-handelsvaran ligger kvar i korgen). Saknas uppgift i
    kött/chark/färdigmat -> "Kontrollera ingredienser". ICA har ingen ingrediensuppgift: alternativ i
    kött-, chark- och färdigmatskategori flaggas.
    """
    for l in lines:
        if l.butik is None:
            continue
        offer = kampanjer.get((l.butik.butik, l.butik.butik_kod or ""))
        if l.butik.butik == i_butik_namn:
            k = ik.kontrollera(l.butik.butik_kod or "", kategori_om_okand=offer.category if offer else None)
            if k.status == "borttagen":
                l.butik_stoppad = f"kampanjvaran innehåller {k.ord}"
                log(f"  Inte i butik: {l.row.vara} – {l.butik_stoppad}")
                l.butik = None
            else:
                l.butik_kontrollera = k.status == "kontrollera"
        elif offer is None or offer.kategori_id in ICA_RISK_KATEGORIER:
            l.butik_kontrollera = True


def tillampa_butikstroskel(
    lines: list[Line], threshold: float | Callable[[str], float]
) -> tuple[dict[str, list[Line]], dict[str, float], dict[str, list[Line]]]:
    """Flagga billigare butiksalternativ. Inga rader flyttas ur korgen.

    - Alternativ som inte är billigare än korgens pris tas bort.
    - Per butik: når den samlade besparingen tröskeln flaggas butikens korgrader ("Billigare i
      butik"); under tröskeln flaggas inget.
    - Rader utan Willys-produkt men med butiksalternativ blir "Köp i butik", oavsett tröskel.

    `threshold` är ett belopp eller en funktion butiksnamn -> belopp. Returnerar
    (flaggade rader per butik, besparing per flaggad butik, köp i butik per butik). Ändrar `lines`.
    """
    troskel = threshold if callable(threshold) else (lambda store: threshold)
    for l in lines:
        l.flaggad, l.butik_spar = False, None
        if l.butik is None or l.row.kanske_hemma:
            continue
        if l.product is not None and l.willys_cost is not None:
            if l.butik.butik_kostnad_kr >= l.willys_cost:
                l.butik = None  # inte billigare – inget att flagga
            else:
                l.butik_spar = round(l.willys_cost - l.butik.butik_kostnad_kr, 2)

    flaggor: dict[str, list[Line]] = {}
    besparing: dict[str, float] = {}
    kop_i_butik: dict[str, list[Line]] = {}
    for store in sorted({l.butik.butik for l in lines if l.butik is not None}):
        i_korgen = [l for l in lines if l.butik is not None and l.butik.butik == store and l.butik_spar is not None]
        spar = round(sum(l.butik_spar for l in i_korgen), 2)
        if i_korgen and spar >= troskel(store):
            for l in i_korgen:
                l.flaggad = True
            flaggor[store], besparing[store] = i_korgen, spar
        utan = [l for l in lines if l.kop_i_butik and l.butik.butik == store]
        if utan:
            kop_i_butik[store] = utan
    return flaggor, besparing, kop_i_butik


def willys_i_butik_namn(cfg: dict) -> str:
    return f"{cfg['butiker']['willys']['namn']} (i butik)"


def butikens_troskel(cfg: dict) -> Callable[[str], float]:
    """Minsta samlade besparing per butik för att flagga dess alternativ i rapporten."""
    opt = cfg.get("optimering", {})
    i_butik = willys_i_butik_namn(cfg)

    def troskel(store: str) -> float:
        if store == i_butik:
            return opt.get("min_besparing_willys_i_butik_kr", 10)
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


class KampanjerInteUppe(RuntimeError):
    """Veckans kampanjer är inte publicerade än – försök igen senare (exit 3, inget felmejl)."""


def kampanjerna_ar_farska(offers: list[Offer], idag: dt.date) -> bool:
    """Finns någon Willys-kampanj med startdatum i innevarande ISO-vecka?

    Bara Willys butikskampanjer (/search/campaigns/offline) har startDate; e-handelns kampanjer har
    det inte. Veckokampanjerna börjar på måndagen.
    """
    vecka = idag.isocalendar()[:2]
    return any(o.start and o.start.isocalendar()[:2] == vecka for o in offers)


def kontrollera_farska_kampanjer(cfg: dict, offers: list[Offer], idag: dt.date | None = None) -> None:
    """Avbryt innan Claude anropas om veckans kampanjer inte är uppe än."""
    idag = idag or dt.date.today()
    w = cfg["butiker"]["willys"]
    if not any(o.start for o in offers):
        # Butikskampanjerna hämtas inte (i_butik: false) – hämta dem bara för kontrollen
        offers = willys.fetch_offers(w["store_id"], willys_i_butik_namn(cfg), kanal="offline")
    if not kampanjerna_ar_farska(offers, idag):
        raise KampanjerInteUppe("Veckans kampanjer är inte uppe än")


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
    kontrollera_farska_kampanjer(cfg, offers)
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
    gar_poster = lager.las_gar_alltid_at(cfg["hushall"].get("gar_alltid_at", []))
    gar_alltid_at = [p.vara for p in gar_poster]
    choice = planner.choose_products(rows, candidates, butiks_offers, cfg["hushall"].get("undvik", []), gar_alltid_at)

    i_butik_namn = willys_i_butik_namn(cfg)
    i_butik_offers = {o.code: o for o in butiks_offers if o.store == i_butik_namn and o.code}
    by_row = {v.rad: v for v in choice.val}
    lines: list[Line] = []
    for i, r in enumerate(rows):
        v = by_row.get(i)
        if v and v.butik and not giltigt_butiksval(v, butiks_offers):
            varningar.append(
                f"Ogiltigt butiksval för {r.vara}: butik {v.butik!r}, kod {v.butik_kod!r}, antal {v.butik_antal} "
                "– raden ligger kvar i e-handeln"
            )
            log(f"  VARNING: {varningar[-1]}")
            v.butik = None
        if v and v.butik == i_butik_namn:
            berakna_butikskostnad(v, i_butik_offers)
        alt = provningsordning(v, candidates[i])
        prod, qty = (alt[0].product, alt[0].qty) if alt else (None, 0)
        lines.append(
            Line(row=r, product=prod, qty=qty, willys_cost=prod.cost(qty) if prod else None,
                 butik=v if v and v.butik and v.butik_kostnad_kr is not None else None, alternativ=alt)
        )

    result = Result(week=week_id(), plan=plan, lines=lines, offers_count=counts, varningar=varningar,
                    willys_namn=willys_name, willys_i_butik_namn=i_butik_namn)

    ingr_ord = sparrord + [w.lower() for w in cfg["hushall"].get("sparrord_ingredienser", [])]
    with ingredienser.Ingredienskontroll(ingr_ord, DATA / "ingredienser-cache.json") as ik:
        sidor = Produktsidor(sess, ik)
        ik.hamta = sidor.detaljer  # samma GET för tillgänglighet och ingredienser
        ingr = ik.kontrollera if ingr_ord else None

        # Butiksalternativen går genom samma fläskskydd som korgen
        if ingr_ord:
            kampanjer = {(o.store, o.code): o for o in butiks_offers if o.code}
            kontrollera_butiksrader(lines, i_butik_namn, kampanjer, ik, log)

        # Varor som alltid går åt: räcker det uppskattade lagret från tidigare veckors korgar köps de inte
        korgar = lager.senaste_korgar(DATA, result.week) if any(p.per_vecka for p in gar_poster) else []
        for l in lines:
            post = lager.matchande_post(l.row.vara, gar_poster)
            if not post:
                continue
            l.gar_alltid_at = post.vara
            kvar = lager.uppskattat_lager(post, korgar, result.week, log) if post.per_vecka else None
            behov = max(lager.antal_i_behov(l.row.behov) or 0, post.per_vecka or 0)
            if kvar is not None and kvar >= behov and not l.row.kanske_hemma:
                l.row.kanske_hemma, l.lager_kvar = True, kvar
                log(f"  Lager: {l.row.vara} – uppskattat kvar ca {kvar:.0f}, räcker till {behov:.0f} – köps inte")

        willys_lines = [l for l in lines if l.alternativ]
        if willys_lines:
            log("Kontrollerar tillgänglighet i butiken och ingredienser…")
        for l in willys_lines:
            l.storpack = gar_alltid_at_rad(l.row, gar_alltid_at)
            if l.storpack:  # bara rader märkta GÅR ALLTID ÅT väljs på pris per enhet
                valt, l.bortvalda, l.kontrollera, l.tillganglighet_okand = valj_storpack(
                    l.alternativ, sidor.finns, ingr, log)
            else:  # övriga rader behåller Claudes ordning
                valt, l.bortvalda, l.kontrollera, l.tillganglighet_okand = valj_alternativ(l.alternativ, sidor.finns, ingr)
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

    # Flaggning efter tillgänglighets- och ingredienskontrollen, så att besparingen räknas mot den
    # vara som faktiskt ligger i korgen. Inga rader flyttas ur korgen.
    result.butik_flaggor, result.butik_besparing, result.kop_i_butik = tillampa_butikstroskel(
        lines, butikens_troskel(cfg))

    result.willys_total = round(sum(l.willys_cost or 0 for l in lines if l.i_korgen), 2)
    result.med_butiksalternativ = round(result.willys_total - sum(result.butik_besparing.values()), 2)
    result.kop_i_butik_total = round(
        sum(l.butik.butik_kostnad_kr for rader in result.kop_i_butik.values() for l in rader), 2)

    cart_lines = [
        {**_korgrad(l.product, l.qty), "reserver": [_korgrad(a.product, a.qty) for a in l.reserver],
         **({"gar_alltid_at": l.gar_alltid_at} if l.gar_alltid_at else {})}
        for l in lines
        if l.i_korgen  # även rader med billigare butiksalternativ – korgen ska vara komplett
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
    rad = {"code": p.code, "qty": qty, "pick_unit": p.extra.get("pickUnit", "pieces"), "name": p.name, "size": p.size}
    if (n := p.enheter_per_forpackning) is not None:
        rad["enheter"] = round(n, 2)  # används för lagret av varor som alltid går åt
    return rad


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
