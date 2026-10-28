"""Kommandon:

  python -m veckohandla init [--ingen-fraga …]          # installationsguide: skriver config.yaml
  python -m veckohandla kontroll [--utan-inloggning]   # kontrollera installationen (inga Claude-anrop)
  python -m veckohandla hitta-willys ORT    # hitta store_id för din Willys
  python -m veckohandla hitta-hemkop ORT    # hitta store_id för ditt Hemköp
  python -m veckohandla erbjudanden        # visa veckans kampanjer (ingen Claude, ingen inloggning)
  python -m veckohandla login              # logga in en gång hos e-handelskedjan (browser-profiles/<kedja>)
  python -m veckohandla kor [--fyll-varukorg] [--ingen-mejl]   # exit 3: kampanjer inte uppe, 4: mejlet skickades inte
  python -m veckohandla fyll-varukorg [VECKA]   # lägg senaste (eller angiven) veckas lista i korgen (butiker.e_handel)

Valläget (meny.lage: val i config): kor tar fram förslag i stället för en färdig meny.
  python -m veckohandla forslag [VECKA]        # visa förslagen med nummer
  python -m veckohandla valj 2 4 5 8 9 [--vecka 2026-v43] [--fyll-varukorg] [--ingen-mejl]

  python -m veckohandla betyg [--vecka 2026-v43]   # sätt + eller − på förra veckans rätter
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
MEJL_MISSLYCKADES = 4  # rapporten är sparad men mejlet kom inte fram


def config_path() -> Path:
    """VECKOHANDLA_CONFIG pekar ut config-filen (t.ex. i ett privat repo); standard är config.yaml här."""
    return Path(os.environ.get("VECKOHANDLA_CONFIG") or ROOT / "config.yaml")


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        sys.exit(f"{path} saknas – kör: python -m veckohandla init")
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
    for kedja in ("willys", "hemkop"):
        h = sub.add_parser(f"hitta-{kedja}")
        h.add_argument("ort")
    i = sub.add_parser("init", help="installationsguide som skriver config.yaml")
    i.add_argument("--config", type=Path, help="var config.yaml skrivs (standard: VECKOHANDLA_CONFIG eller här)")
    i.add_argument("--ingen-fraga", action="store_true", help="inga frågor – svaren tas från flaggorna nedan")
    i.add_argument("--ort", help="ort att söka Willys- och Hemköp-butiker med e-handel i")
    i.add_argument("--kedja", choices=["willys", "hemkop"], help="e-handelskedja (med --butik-id)")
    i.add_argument("--butik-id", help="butikens store_id (annars första butiken med e-handel på --ort)")
    i.add_argument("--butiksnamn", help="namn på butiken (med --butik-id)")
    i.add_argument("--ica", action="append", default=[], metavar="NAMN=SLUG_ELLER_ADRESS",
                   help="ICA-butik att jämföra med (kan anges flera gånger)")
    i.add_argument("--ica-i-molnet", action="store_true", help="hämta ICA även i GitHub Actions (standard: bara lokalt)")
    i.add_argument("--vuxna", type=int, default=2)
    i.add_argument("--barn", default="", help='barnens åldrar, t.ex. "9,7"')
    i.add_argument("--middagar", type=int, default=5)
    i.add_argument("--onskemal", default="", help="önskemål i fritext (standard: exemplets)")
    i.add_argument("--matlador", default="", help='dagar med matlådor, t.ex. "tisdag,torsdag"')
    i.add_argument("--matlador-extra", type=int, default=2)
    i.add_argument("--undvik", default="", help="förval: flaskfritt,vegetariskt,notfritt,laktosfritt")
    i.add_argument("--undvik-egen", default="", help='annat att undvika, separerat med semikolon')
    i.add_argument("--lage", choices=["auto", "val"], default="auto")
    i.add_argument("--epost", default="du@example.com")
    i.add_argument("--smtp-host", default="smtp.gmail.com")
    i.add_argument("--modeller", choices=["billiga", "standard"], default="billiga",
                   help="billiga = Sonnet för menyn, Haiku för produktvalet")
    i.add_argument("--skriv-over", action="store_true", help="skriv över config.yaml (kopia sparas som .bak)")
    i.add_argument("--utan-kontroll", action="store_true", help="kör inte kontroll efteråt")
    ko = sub.add_parser("kontroll", help="kontrollera installationen (inga Claude-anrop, inga ändringar)")
    ko.add_argument("--utan-inloggning", action="store_true",
                    help="öppna inte webbläsarprofilen för att kontrollera inloggningen")
    sub.add_parser("erbjudanden")
    sub.add_parser("login")
    f = sub.add_parser("fyll-varukorg")
    f.add_argument("vecka", nargs="?", help="t.ex. 2026-v42 (standard: senaste)")
    k = sub.add_parser("kor")
    k.add_argument("--fyll-varukorg", action="store_true", help="lägg varorna i varukorgen (ingen beställning)")
    k.add_argument("--ingen-mejl", action="store_true")
    k.add_argument("--en-gang-per-vecka", action="store_true",
                   help="avsluta direkt om veckans plan redan finns (för schemalagda körningar)")
    k.add_argument("--onskemal", default="", help='önskemål bara för den här körningen, t.ex. "fisk två gånger"')
    fo = sub.add_parser("forslag", help="visa veckans förslag med nummer (valläget)")
    fo.add_argument("vecka", nargs="?", help="t.ex. 2026-v43 (standard: senaste)")
    v = sub.add_parser("valj", help="välj bland förslagen och gör veckans inköp (valläget)")
    v.add_argument("nummer", nargs="+", help="förslagens nummer i den ordning de ska ätas (första = måndag)")
    v.add_argument("--vecka", help="t.ex. 2026-v43 (standard: senaste förslagen)")
    v.add_argument("--fyll-varukorg", action="store_true", help="lägg varorna i varukorgen (ingen beställning)")
    v.add_argument("--ingen-mejl", action="store_true")
    b = sub.add_parser("betyg", help="sätt + eller − på förra (eller angiven) veckans rätter")
    b.add_argument("--vecka", help="t.ex. 2026-v43 (standard: förra veckan)")
    b.add_argument("--fran-text", metavar="JSON",
                   help='betyg utan frågor, t.ex. från mobilsidan: {"vecka": "2026-v43", "betyg": '
                        '[{"ratt": "Tacos", "betyg": 1, "kommentar": "god"}]}')
    args = ap.parse_args()

    if args.cmd in ("hitta-willys", "hitta-hemkop"):
        from .stores import hemkop, willys

        find_stores = (willys if args.cmd == "hitta-willys" else hemkop).find_stores
        for s in find_stores(args.ort):
            town = (s.get("address") or {}).get("town") or "?"
            print(f"{s.get('storeId', '?'):>6}  {s.get('name', '?')}  ({town})  e-handel/hämtning: {'ja' if s.get('clickAndCollect') else 'nej'}")
        return 0

    if args.cmd == "init":
        return init(args)

    if args.cmd == "kontroll":
        from . import kontroll, pipeline

        return kontroll.kor(config_path(), pipeline.DATA, ROOT / "browser-profiles",
                            med_inloggning=not args.utan_inloggning)

    cfg = load_config()

    if args.cmd == "erbjudanden":
        from .pipeline import fetch_all_offers

        varningar: list[str] = []
        for o in fetch_all_offers(cfg, varningar):
            print(f"{o.store:28} {o.short()}")
        for v in varningar:
            print(f"VARNING: {v}", file=sys.stderr)
        return 0

    if args.cmd == "forslag":
        return visa_forslag(cfg, args.vecka)

    if args.cmd == "betyg":
        if args.fran_text is not None:
            return betyg_fran_text(args.fran_text)
        return satt_betyg(args.vecka)

    if args.cmd == "login":
        from .browser import login_axfood
        from .pipeline import kedjemodul

        k = kedjemodul(cfg).KEDJA
        print(f"Inloggad på {k.namn} som {login_axfood(k.nyckel, k.namn, k.base)}. "
              f"Sessionen är sparad i browser-profiles/{k.nyckel}.")
        return 0

    from .cart import NotLoggedIn

    # launchd lägger till i loggfilen – en startrad visar var varje körning börjar
    print(f"\n=== veckohandla {args.cmd} startar {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===", flush=True)

    if args.cmd == "fyll-varukorg":
        from .pipeline import IngenKorg, e_handel, fill_saved_cart, kedjemodul, latest_cart_week

        kedjenamn = kedjemodul(cfg).KEDJA.namn
        try:
            week = args.vecka or latest_cart_week()
        except IngenKorg as e:
            print(e, file=sys.stderr)
            return 1
        try:
            res = fill_saved_cart(week, kedja=e_handel(cfg))
        except NotLoggedIn as e:
            print(e, file=sys.stderr)
            return 2
        print(f"Lade till {res['tillagda']} varor, {res['redan_klara']} fanns redan. {kedjenamn}-korgen totalt: {res['total']}")
        if res["annan_enhet"]:
            print(f"Finns redan i annan enhet (rörs inte): {', '.join(res['annan_enhet'])}")
        for b in res.get("byten", []):
            print(f"Bytt till reserv: {b}")
        if res["failed"]:
            print(f"{kedjenamn} nekade (ingen reserv fungerade): {', '.join(res['failed'])}")
        if res["missing"]:
            print(f"För få i korgen efteråt: {', '.join(res['missing'])}")
        return 0

    from .pipeline import IngaForslag, KampanjerInteUppe, OgiltigtVal

    try:
        if args.cmd == "valj":
            return valj(cfg, args)
        return kor(cfg, args)
    except (OgiltigtVal, IngaForslag) as e:
        print(f"Fel: {e}", file=sys.stderr)  # inget anrop har gjorts – rätta kommandot och kör igen
        return 1
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


def init(args) -> int:
    from . import installera, kontroll, pipeline

    config = args.config or config_path()
    f = installera.Fragor()
    if args.ingen_fraga:
        try:
            svar = _init_svar(args)
        except ValueError as e:
            print(f"Fel: {e}", file=sys.stderr)
            return 2
        klar = installera.kor_guiden(f, config, ROOT / "config.example.yaml", ROOT / ".env", svar,
                                     skriv_over=args.skriv_over)
    else:
        klar = installera.kor_guiden(f, config, ROOT / "config.example.yaml", ROOT / ".env")
    if not klar:
        return 1
    load_env()  # ett nytt SMTP-lösenord i .env ska synas i kontrollen
    if not args.utan_kontroll:
        print()
        kontroll.kor(config, pipeline.DATA, ROOT / "browser-profiles", med_inloggning=False)
    login_klar = False
    if not args.ingen_fraga and f.ja("\nLogga in hos e-handelskedjan nu (öppnar ett webbläsarfönster)?", True):
        from .browser import login_axfood
        from .pipeline import kedjemodul

        k = kedjemodul(yaml.safe_load(config.read_text())).KEDJA
        print(f"Inloggad på {k.namn} som {login_axfood(k.nyckel, k.namn, k.base)}.")
        login_klar = True
    installera.nasta_steg(print, login_klar)
    return 0


def _init_svar(args):
    """Svaren för init --ingen-fraga, från flaggorna."""
    from . import installera

    if args.butik_id:
        if not args.kedja:
            raise ValueError("--butik-id kräver --kedja willys eller hemkop")
        namn = args.butiksnamn or f"{'Willys' if args.kedja == 'willys' else 'Hemköp'} {args.butik_id}"
        butik = installera.Butik(args.kedja, args.butik_id, namn)
    elif args.ort:
        butiker = [b for b in installera.hitta_butiker(args.ort) if not args.kedja or b.kedja == args.kedja]
        if not butiker:
            raise ValueError(f"hittade ingen butik med e-handel i {args.ort} – ange --kedja och --butik-id")
        butik = butiker[0]
    else:
        raise ValueError("ange --ort eller --kedja och --butik-id")
    ica = []
    for post in args.ica:
        namn, _, adress = post.partition("=")
        if not adress:
            raise ValueError(f"--ica ska vara NAMN=SLUG, inte {post!r}")
        slug = installera.ica_slug(adress)
        ica.append({"namn": namn.strip(), "erbjudande_slug": slug, **({} if args.ica_i_molnet else {"bara_lokalt": True})})
    undvik = [u.strip() for u in args.undvik.split(",") if u.strip()]
    if okanda := [u for u in undvik if u not in installera.UNDVIK_VAL]:
        raise ValueError(f"okänt förval i --undvik: {', '.join(okanda)} (välj bland {', '.join(installera.UNDVIK_VAL)})")
    return installera.Svar(
        butik=butik, ica=ica, vuxna=args.vuxna, barn=installera.tolka_heltal(args.barn), middagar=args.middagar,
        onskemal=args.onskemal, matlador_dagar=installera.tolka_dagar(args.matlador) if args.matlador else [],
        matlador_extra=args.matlador_extra, undvik_val=undvik,
        undvik_egen=[u for u in args.undvik_egen.split(";") if u.strip()], lage=args.lage, epost=args.epost,
        smtp_host=args.smtp_host, billiga_modeller=args.modeller == "billiga",
    )


def menylage(cfg: dict) -> str:
    lage = (cfg.get("meny") or {}).get("lage", "auto")
    if lage not in ("auto", "val"):
        raise ValueError(f"meny.lage måste vara auto eller val, inte {lage!r}")
    return lage


def kor(cfg: dict, args) -> int:
    from . import pipeline
    from .pipeline import run, week_id

    val = menylage(cfg) == "val"
    if args.en_gang_per_vecka:
        fil = pipeline.forslag_fil(week_id()) if val else pipeline.DATA / f"{week_id()}.json"
        if fil.exists():
            print(f"Veckans {'förslag' if val else 'plan'} finns redan ({week_id()}) – inget att göra.")
            return 0
    if args.onskemal.strip():
        h = cfg["hushall"]
        h["preferenser"] = f"{h.get('preferenser', '').strip()}\nÖnskemål för just den här veckan: {args.onskemal.strip()}"

    if val:
        return _forslagsrapport(cfg, pipeline.foresla(cfg), args)
    return _veckorapport(cfg, run(cfg, fill_cart=args.fyll_varukorg), args)


def valj(cfg: dict, args) -> int:
    from .pipeline import valj as valj_ratter

    return _veckorapport(cfg, valj_ratter(cfg, args.nummer, args.vecka, fill_cart=args.fyll_varukorg), args)


def visa_forslag(cfg: dict, vecka: str | None) -> int:
    from . import report
    from .pipeline import IngaForslag, Forslagsresultat, las_forslag, latest_forslag_week

    try:
        week = vecka or latest_forslag_week()
        forslag = las_forslag(week)
    except IngaForslag as e:
        print(f"Fel: {e}", file=sys.stderr)
        return 1
    res = Forslagsresultat(week=week, forslag=forslag, middagar_per_vecka=cfg["hushall"]["middagar_per_vecka"])
    print(f"Förslag {week}:")
    for i, r in enumerate(forslag.ratter, 1):
        print(f"  {i:>2}. {r.ratt} ({r.tid_min} min)")
    print(f"\nVälj {res.middagar_per_vecka} i den ordning du vill äta dem (första = måndag), t.ex.:\n  {report.valj_exempel(res)}")
    return 0


def satt_betyg(vecka: str | None, fraga=None) -> int:
    """Visa veckans rätter och låt användaren sätta + eller − med en valfri kommentar."""
    import json

    from . import betyg, pipeline

    fraga = fraga or input

    vecka = vecka or pipeline.week_id(dt.date.today() - dt.timedelta(days=7))
    plan = pipeline.DATA / f"{vecka}.json"
    if not plan.exists():
        print(f"Fel: hittade ingen plan för {vecka} ({plan})", file=sys.stderr)
        return 1
    middagar = json.loads(plan.read_text())["middagar"]
    tidigare = {p["ratt"]: p for p in betyg.las(pipeline.DATA) if p["vecka"] == vecka}
    print(f"Betyg för {vecka}. Svara + eller −, Enter hoppar över (ett tidigare betyg står kvar).")
    satta = 0
    for m in middagar:
        nu = tidigare.get(m["ratt"])
        nu_text = f"  [nu: {'+' if nu['betyg'] > 0 else '−'}{' ' + nu['kommentar'] if nu.get('kommentar') else ''}]" if nu else ""
        print(f"\n{m.get('dag', '')}: {m['ratt']}{nu_text}")
        try:
            svar = fraga("Betyg (+/−): ").strip()
            if not svar:
                continue
            if svar not in ("+", "-", "−"):
                print("  Hoppar över – svara + eller −.")
                continue
            kommentar = fraga("Kommentar (valfritt): ")
        except EOFError:
            break
        betyg.satt(pipeline.DATA, m["ratt"], vecka, 1 if svar == "+" else -1, kommentar)
        satta += 1
    print(f"\n{satta} betyg sparade i {betyg.fil(pipeline.DATA)}")
    return 0


def betyg_fran_text(text: str) -> int:
    """Betyg från mobilsidan (workflow-input `betyg`). Allt kontrolleras innan något sparas."""
    import json
    import re

    from . import betyg, pipeline

    try:
        d = json.loads(text)
        vecka, poster = d["vecka"], d["betyg"]
        if not isinstance(vecka, str) or not re.fullmatch(r"\d{4}-v\d{2}", vecka):
            raise ValueError(f"ogiltig vecka {vecka!r}")
        plan = pipeline.DATA / f"{vecka}.json"
        if not plan.exists():
            raise ValueError(f"hittade ingen plan för {vecka}")
        ratter = {m["ratt"] for m in json.loads(plan.read_text())["middagar"]}
        if not isinstance(poster, list) or not 1 <= len(poster) <= len(ratter):
            raise ValueError(f"ange 1–{len(ratter)} betyg")
        kontrollerade = []
        for p in poster:
            ratt, varde, kommentar = p["ratt"], p["betyg"], p.get("kommentar") or ""
            if ratt not in ratter:
                raise ValueError(f"{ratt!r} finns inte i planen för {vecka}")
            if isinstance(varde, bool) or varde not in (1, -1):
                raise ValueError(f"betyget för {ratt} måste vara 1 eller -1")
            if not isinstance(kommentar, str) or len(kommentar) > 500:
                raise ValueError(f"kommentaren för {ratt} får vara högst 500 tecken")
            kontrollerade.append((ratt, varde, kommentar))
    except (ValueError, KeyError, TypeError) as e:
        print(f"Fel i betygen: {e}", file=sys.stderr)
        return 1
    for ratt, varde, kommentar in kontrollerade:
        betyg.satt(pipeline.DATA, ratt, vecka, varde, kommentar)
        print(f"{'+' if varde > 0 else '−'} {ratt}")
    print(f"{len(kontrollerade)} betyg sparade för {vecka}")
    return 0


def _forslagsrapport(cfg: dict, res, args) -> int:
    from . import mobil, pipeline, report

    page = report.render_forslag(res)  # filen i data/ får inga signerade länkar
    out = pipeline.DATA / f"{res.week}-forslag.html"
    out.write_text(page)
    print(f"Förslagsrapport: {out}")
    mejl = report.render_forslag(res, mobil.vecklankar_fran_miljo(res.week))
    mejlfel = None if args.ingen_mejl else _skicka_rapport(cfg, f"Veckoförslag {res.week}", mejl, out)
    if mejlfel:
        print(mejlfel, file=sys.stderr, flush=True)
        return MEJL_MISSLYCKADES
    return 0


def _veckorapport(cfg: dict, res, args) -> int:
    from . import mobil, pipeline, report

    page = report.render(res)  # filen i data/ får inga signerade länkar
    out = pipeline.DATA / f"{res.week}.html"
    out.write_text(page)
    print(f"Rapport: {out}")
    print(f"{res.kedja}-korgen: {res.willys_total:.2f} kr"
          + (f", med flaggade butiksalternativ: {res.med_butiksalternativ:.2f} kr" if res.butik_besparing else ""))

    mejl = report.render(res, mobil.vecklankar_fran_miljo(res.week))
    mejlfel = None if args.ingen_mejl else _skicka_rapport(cfg, f"Veckomeny {res.week}", mejl, out)
    if res.cart_error:
        print(res.cart_error, file=sys.stderr)
    if mejlfel:
        print(mejlfel, file=sys.stderr, flush=True)
        return MEJL_MISSLYCKADES
    if res.cart_error:
        return 2  # syns i loggen att korgen inte fylldes
    return 0


def _skicka_rapport(cfg: dict, subject: str, page: str, out: Path) -> str | None:
    """Mejla rapporten. Returnerar ett felmeddelande om mejlet inte kunde skickas, annars None."""
    import smtplib

    from . import report

    pw = os.environ.get("SMTP_PASSWORD")
    if not pw:
        orsak = "SMTP_PASSWORD saknas (lägg den i .env eller som hemlighet i workflowen)"
    else:
        try:
            report.send(cfg, subject, page, pw)
        except smtplib.SMTPAuthenticationError as e:
            orsak = f"SMTP-inloggningen nekades ({e.smtp_code})"
        except (smtplib.SMTPException, OSError) as e:
            orsak = f"sändningen misslyckades ({type(e).__name__}: {e})"
        else:
            print(f"Mejl skickat till {cfg['epost']['till']}")
            return None
    return f"MEJLET SKICKADES INTE: {orsak}. Rapporten är sparad i {out}."


if __name__ == "__main__":
    sys.exit(main())
