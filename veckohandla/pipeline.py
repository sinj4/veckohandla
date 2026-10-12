"""Hela veckokörningen: kampanjer → meny → produktval → prisjämförelse → (varukorg) → rapport."""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .models import Offer, Product
from .planner import Inkopsrad, Planner, Val, Veckoplan
from . import ingredienser
from .stores import ica, willys

# Kan bytas ut i tester (monkeypatch pipeline.DATA) eller via miljövariabeln VECKOHANDLA_DATA
DATA = Path(os.environ.get("VECKOHANDLA_DATA") or Path(__file__).resolve().parent.parent / "data")

# Veckoplaner heter t.ex. 2026-v42.json; korgfiler (2026-v42-korg.json) och cache ska inte matcha
PLAN_GLOB = "*-v[0-9][0-9].json"
KORG_GLOB = "*-v[0-9][0-9]-korg.json"


@dataclass
class Line:
    row: Inkopsrad
    product: Product | None
    qty: int
    willys_cost: float | None
    ica: Val | None = None  # satt om varan ska köpas på ICA i stället
    borttagen: str | None = None  # spärrord som hittades i ingredienserna – läggs inte i korgen
    kontrollera: bool = False  # kött/chark/färdigmat utan ingrediensuppgift

    @property
    def buy_at_ica(self) -> bool:
        return self.ica is not None


@dataclass
class Result:
    week: str
    plan: Veckoplan
    lines: list[Line]
    willys_namn: str = "Willys"
    ica_lists: dict[str, list[Line]] = field(default_factory=dict)
    willys_total: float = 0.0
    ica_total: float = 0.0
    ica_savings: dict[str, float] = field(default_factory=dict)
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


def fetch_all_offers(cfg: dict, varningar: list[str] | None = None) -> list[Offer]:
    """Willys-fel stoppar körningen; en ICA-butik som fallerar hoppas över med en varning."""
    stores = cfg["butiker"]
    offers = willys.fetch_offers(stores["willys"]["store_id"], stores["willys"]["namn"])
    for s in stores.get("ica", []):
        try:
            offers += ica.fetch_offers(s["erbjudande_slug"], s["namn"])
        except Exception as e:  # nätverk, ändrad sida m.m.
            if varningar is None:
                raise
            varningar.append(f"Kunde inte hämta kampanjer från {s['namn']}: {e}")
    return offers


def run(cfg: dict, fill_cart: bool = False, log=print) -> Result:
    planner = Planner(cfg["claude"]["model"])
    willys_name = cfg["butiker"]["willys"]["namn"]

    log("Hämtar veckans kampanjer…")
    varningar: list[str] = []
    offers = fetch_all_offers(cfg, varningar)
    for v in varningar:
        log(f"  VARNING: {v}")
    sparrord = [w.lower() for w in cfg["hushall"].get("sparrord", [])]
    offers = [o for o in offers if not _blocked(f"{o.name} {o.brand}", sparrord)]
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

    log(f"Söker {len(rows)} varor i Willys sortiment…")
    candidates: list[list[Product]] = []
    for r in rows:
        try:
            found = willys.search(r.sokord, willys_name)
            if not found and r.vara.lower() != r.sokord.lower():
                found = willys.search(r.vara, willys_name)
            candidates.append([p for p in found if not _blocked(p.name, sparrord)])
        except Exception as e:  # en enskild sökning ska inte stoppa hela körningen
            log(f"  sökning misslyckades för {r.sokord!r}: {e}")
            candidates.append([])
        time.sleep(0.5)

    log("Väljer produkter och jämför med ICA-kampanjer…")
    ica_offers = [o for o in offers if o.store != willys_name]
    choice = planner.choose_products(rows, candidates, ica_offers, cfg["hushall"].get("undvik", []))

    by_row = {v.rad: v for v in choice.val}
    lines: list[Line] = []
    for i, r in enumerate(rows):
        v = by_row.get(i)
        prod = next((p for p in candidates[i] if v and p.code == v.willys_kod), None)
        qty = prod.best_qty(max(1, v.willys_antal)) if prod and v else 0
        lines.append(
            Line(row=r, product=prod, qty=qty, willys_cost=prod.cost(qty) if prod else None,
                 ica=v if v and v.ica_butik and v.ica_kostnad_kr is not None else None)
        )

    # Ett ICA-besök lönar sig bara om det sparar tillräckligt – annars köps allt på Willys
    threshold = cfg["optimering"]["min_besparing_for_delning_kr"]
    result = Result(week=week_id(), plan=plan, lines=lines, offers_count=counts, varningar=varningar,
                    willys_namn=willys_name)
    stores = {l.ica.ica_butik for l in lines if l.buy_at_ica}
    for store in stores:
        store_lines = [l for l in lines if l.buy_at_ica and l.ica.ica_butik == store]
        saving = sum((l.willys_cost or 0) - l.ica.ica_kostnad_kr for l in store_lines if l.willys_cost)
        if saving >= threshold or any(l.product is None for l in store_lines):
            result.ica_lists[store] = store_lines
            result.ica_savings[store] = round(saving, 2)
        else:
            for l in store_lines:
                if l.product:
                    l.ica = None

    ingr_ord = sparrord + [w.lower() for w in cfg["hushall"].get("sparrord_ingredienser", [])]
    willys_lines = [l for l in lines if l.product and not l.buy_at_ica]
    if ingr_ord and willys_lines:
        log("Kontrollerar ingredienser…")
        kontroll = ingredienser.kontrollera(
            [l.product.code for l in willys_lines], ingr_ord, DATA / "ingredienser-cache.json"
        )
        for l in willys_lines:
            k = kontroll[l.product.code]
            if k.status == "borttagen":
                l.borttagen = k.ord
                log(f"  Borttagen: {l.product.name} innehåller {k.ord!r}")
            l.kontrollera = k.status == "kontrollera"

    result.willys_total = round(sum(l.willys_cost or 0 for l in lines if not l.buy_at_ica and not l.borttagen), 2)
    result.ica_total = round(sum(l.ica.ica_kostnad_kr for l in lines if l.buy_at_ica), 2)

    cart_lines = [
        {"code": l.product.code, "qty": l.qty, "pick_unit": l.product.extra.get("pickUnit", "pieces"),
         "name": l.product.name, "size": l.product.size}
        for l in lines
        if l.product and not l.buy_at_ica and not l.borttagen and l.qty > 0
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
    from .cart import CartLine, fill_willys

    saved = json.loads((DATA / f"{week}-korg.json").read_text())
    log(f"Lägger {len(saved)} varor i Willys-varukorgen…")
    return fill_willys([
        CartLine(x["code"], x["qty"], x["pick_unit"], x.get("name", ""), x.get("size", "")) for x in saved
    ])
