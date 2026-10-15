"""Kommandon:

  python -m veckohandla hitta-willys ORT    # hitta store_id för din Willys
  python -m veckohandla erbjudanden        # visa veckans kampanjer (ingen Claude, ingen inloggning)
  python -m veckohandla login              # logga in på Willys en gång (sparas i browser-profiles/)
  python -m veckohandla kor [--fyll-varukorg] [--ingen-mejl]
  python -m veckohandla fyll-varukorg [VECKA]   # lägg senaste (eller angiven) veckas lista i Willys-korgen
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def config_path() -> Path:
    """VECKOHANDLA_CONFIG pekar ut config-filen (t.ex. i ett privat repo); standard är config.yaml här."""
    return Path(os.environ.get("VECKOHANDLA_CONFIG") or ROOT / "config.yaml")


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        sys.exit(f"{path} saknas – kör: cp config.example.yaml config.yaml och anpassa den")
    return yaml.safe_load(path.read_text())


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser(prog="veckohandla")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hitta-willys")
    h.add_argument("ort")
    sub.add_parser("erbjudanden")
    sub.add_parser("login")
    f = sub.add_parser("fyll-varukorg")
    f.add_argument("vecka", nargs="?", help="t.ex. 2026-v42 (standard: senaste)")
    k = sub.add_parser("kor")
    k.add_argument("--fyll-varukorg", action="store_true", help="lägg varorna i Willys-varukorgen (ingen beställning)")
    k.add_argument("--ingen-mejl", action="store_true")
    k.add_argument("--en-gang-per-vecka", action="store_true",
                   help="avsluta direkt om veckans plan redan finns (för schemalagda körningar)")
    k.add_argument("--onskemal", default="", help='önskemål bara för den här körningen, t.ex. "fisk två gånger"')
    args = ap.parse_args()

    if args.cmd == "hitta-willys":
        from .stores.willys import find_stores

        for s in find_stores(args.ort):
            town = (s.get("address") or {}).get("town") or "?"
            print(f"{s.get('storeId', '?'):>6}  {s.get('name', '?')}  ({town})  e-handel/hämtning: {'ja' if s.get('clickAndCollect') else 'nej'}")
        return 0

    cfg = load_config()

    if args.cmd == "erbjudanden":
        from .pipeline import fetch_all_offers

        varningar: list[str] = []
        for o in fetch_all_offers(cfg, varningar):
            print(f"{o.store:28} {o.short()}")
        for v in varningar:
            print(f"VARNING: {v}", file=sys.stderr)
        return 0

    if args.cmd == "login":
        from .browser import login_willys

        print(f"Inloggad på Willys som {login_willys()}. Sessionen är sparad.")
        return 0

    from .cart import NotLoggedIn

    # launchd lägger till i loggfilen – en startrad visar var varje körning börjar
    print(f"\n=== veckohandla {args.cmd} startar {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===", flush=True)

    if args.cmd == "fyll-varukorg":
        from .pipeline import IngenKorg, fill_saved_cart, latest_cart_week

        try:
            week = args.vecka or latest_cart_week()
        except IngenKorg as e:
            print(e, file=sys.stderr)
            return 1
        try:
            res = fill_saved_cart(week)
        except NotLoggedIn as e:
            print(e, file=sys.stderr)
            return 2
        print(f"Lade till {res['tillagda']} varor, {res['redan_klara']} fanns redan. Willys-korgen totalt: {res['total']}")
        if res["annan_enhet"]:
            print(f"Finns redan i annan enhet (rörs inte): {', '.join(res['annan_enhet'])}")
        for b in res.get("byten", []):
            print(f"Bytt till reserv: {b}")
        if res["failed"]:
            print(f"Willys nekade (ingen reserv fungerade): {', '.join(res['failed'])}")
        if res["missing"]:
            print(f"För få i korgen efteråt: {', '.join(res['missing'])}")
        return 0

    from .pipeline import KampanjerInteUppe

    try:
        return kor(cfg, args)
    except KampanjerInteUppe as e:
        print(e, flush=True)  # inte ett fel – schemat försöker igen senare
        return 3
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr, flush=True)
        if not args.ingen_mejl:
            _felmejl(cfg, tb)
        return 1


def _felmejl(cfg: dict, tb: str) -> None:
    """Skicka ett kort felmejl. Fel här får inte dölja det ursprungliga felet."""
    pw = os.environ.get("SMTP_PASSWORD")
    if not pw:
        return
    try:
        import html

        from . import report
        from .pipeline import week_id

        sista = "\n".join(tb.rstrip().splitlines()[-30:])
        body = f"<html><body><p>Veckohandla misslyckades.</p><pre>{html.escape(sista)}</pre></body></html>"
        report.send(cfg, f"Veckohandla misslyckades {week_id()}", body, pw)
    except Exception as e:
        print(f"(Kunde inte heller skicka felmejl: {e})", file=sys.stderr)


def kor(cfg: dict, args) -> int:
    from . import pipeline, report
    from .pipeline import run, week_id

    if args.en_gang_per_vecka and (pipeline.DATA / f"{week_id()}.json").exists():
        print(f"Veckans plan finns redan ({week_id()}) – inget att göra.")
        return 0
    if args.onskemal.strip():
        h = cfg["hushall"]
        h["preferenser"] = f"{h.get('preferenser', '').strip()}\nÖnskemål för just den här veckan: {args.onskemal.strip()}"

    res = run(cfg, fill_cart=args.fyll_varukorg)

    page = report.render(res)
    out = pipeline.DATA / f"{res.week}.html"
    out.write_text(page)
    print(f"Rapport: {out}")
    print(f"Willys-korgen: {res.willys_total:.2f} kr"
          + (f", med flaggade butiksalternativ: {res.med_butiksalternativ:.2f} kr" if res.butik_besparing else ""))

    if not args.ingen_mejl:
        pw = os.environ.get("SMTP_PASSWORD")
        if not pw:
            print("SMTP_PASSWORD saknas – hoppar över mejl (lägg den i .env)", file=sys.stderr)
        else:
            report.send(cfg, f"Veckomeny {res.week}", page, pw)
            print(f"Mejl skickat till {cfg['epost']['till']}")
    if res.cart_error:
        print(res.cart_error, file=sys.stderr)
        return 2  # syns i loggen att korgen inte fylldes
    return 0


if __name__ == "__main__":
    sys.exit(main())
