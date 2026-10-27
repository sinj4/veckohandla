"""HTML-rapport (mejlas) med meny, recept, korgen (Willys eller Hemköp) och ev. butikslistor."""

from __future__ import annotations

import html
import os
import re
import smtplib
from email.message import EmailMessage

from .pipeline import Forslagsresultat, Notis, Result
from .planner import forbrukning_text


def _kr(x: float | None) -> str:
    return "–" if x is None else f"{x:,.2f} kr".replace(",", " ").replace(".", ",")


def _code(text: str) -> str:
    """`kommando` -> <code>kommando</code> (texten är redan HTML-escapad)."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def _kr0(x: float) -> str:
    return f"{x:,.0f} kr".replace(",", " ")


def _versal(t: str) -> str:
    return t[:1].upper() + t[1:]


def _upprakning(namn: list[str]) -> str:
    """['A', 'B', 'C'] -> 'A, B och C'"""
    return namn[0] if len(namn) == 1 else f"{', '.join(namn[:-1])} och {namn[-1]}"


def _etikett(res: Result, store: str) -> str:
    return f"{res.kedja} i butik" if store == res.willys_i_butik_namn else store


def byte_text(l) -> str:
    """'Bytt: <första valet> → <reserv> (orsak)'; fler bortvalda läggs till efter."""
    (forsta, orsak), *ovriga = l.bortvalda
    text = f"Bytt: {forsta.product.name} {forsta.product.size} → {l.product.name} {l.product.size} ({orsak})"
    for alt, o in ovriga:
        text += f"; även {alt.product.name} hoppades över ({o})"
    return text


def fyll_kommando(week: str) -> str:
    """Kommandot som fyller korgen; VECKOHANDLA_FYLL_KOMMANDO (t.ex. ./fyll.sh i molnet) går före standard."""
    return os.environ.get("VECKOHANDLA_FYLL_KOMMANDO") or f"python -m veckohandla fyll-varukorg {week}"


def valj_kommando(week: str) -> str:
    """Kommandot som väljer bland förslagen (numren skrivs efter)."""
    return os.environ.get("VECKOHANDLA_FYLL_KOMMANDO") or f"python -m veckohandla valj --vecka {week} --fyll-varukorg"


def valj_exempel(res: Forslagsresultat) -> str:
    """T.ex. './fyll.sh 1 3 5 7 9' – lika många nummer som middagar per vecka, utspridda över förslagen."""
    n = len(res.forslag.ratter)
    antal = min(res.middagar_per_vecka, n)
    steg = max(1, n // antal) if antal else 1
    return f"{valj_kommando(res.week)} {' '.join(str(1 + i * steg) for i in range(antal))}"


def _prisetikett(notis: str) -> str:
    if notis == "bra pris":
        return " <small style='background:#e6f4e6;color:#1d6b1d;padding:1px 5px;border-radius:4px'>🏷️ bra pris</small>"
    if notis == "vanligt pris":
        return " <small style='background:#eee;color:#666;padding:1px 5px;border-radius:4px'>vanligt pris</small>"
    return ""


def _prislista(markerade: list) -> str:
    """Kort sammanfattning av prishistoriken med veckans bra priser i en utfällbar lista."""
    if not markerade:
        return ""
    e = html.escape
    bra = [o for o in markerade if o.prisnotis == "bra pris"]
    rader = "".join(f"<li>{e(o.store)}: {e(o.name)} – {e(o.deal)} (ord. {e(o.regular_price)})</li>" for o in bra)
    lista = f"<details><summary>Bra pris den här veckan ({len(bra)})</summary><ul>{rader}</ul></details>" if bra else ""
    return (f"<div style='color:#666;font-size:13px'>Prishistorik (8 veckor): {len(bra)} kampanjer med bra pris, "
            f"{len(markerade) - len(bra)} med vanligt pris.{lista}</div>")


def _varningar(varningar: list[str]) -> list[str]:
    """Varningar i gul ruta; neutrala notiser (t.ex. att ICA jämförs på datorn) som grå rad, en gång var."""
    e = html.escape
    ut, sedda = [], set()
    for v in varningar:
        if isinstance(v, Notis):
            if v not in sedda:
                sedda.add(v)
                ut.append(f"<p style='color:#666;font-size:13px'>ℹ️ {e(v)}</p>")
            continue
        ut.append(
            "<p style='background:#fff6e0;border:1px solid #e6c46e;padding:10px;border-radius:8px;font-size:14px'>"
            f"⚠️ {e(v)}</p>"
        )
    return ut


def _kostnadsrad(kostnad: dict | None) -> str:
    if not kostnad:
        return ""
    return f"<p style='color:#999;font-size:11px;margin-top:24px'>Claude: {html.escape(forbrukning_text(kostnad))}</p>"


def render_forslag(res: Forslagsresultat) -> str:
    e = html.escape
    parts = [
        "<html><body style='font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:720px;margin:auto;color:#222'>",
        f"<h1>Veckoförslag {e(res.week)}</h1>",
        "<div style='background:#eaf2fb;border:1px solid #9cc0e6;padding:12px;border-radius:8px'>"
        f"<b>Välj {res.middagar_per_vecka} rätter</b> genom att köra kommandot med deras nummer på datorn där du är "
        f"inloggad på {e(res.kedja)}, i den ordning du vill äta dem (första blir måndag):<br>"
        f"<code style='font-size:15px'>{e(valj_exempel(res))}</code><br>"
        "<small>Då görs inköpslistan för just de rätterna, korgen fylls och du får veckans rapport.</small></div>",
        f"<p>{e(res.forslag.kommentar)}</p>",
        "<p style='color:#666;font-size:13px'>Kampanjer skannade: "
        + ", ".join(f"{e(k)} {v}" for k, v in res.offers_count.items())
        + "</p>",
        _prislista(res.prismarkerade),
    ]
    parts += _varningar(res.varningar)
    for i, r in enumerate(res.forslag.ratter, 1):
        kampanj = (f"<p style='color:#2a7a2a;font-size:13px;margin:6px 0 0'>Kampanj: {e(', '.join(r.kampanjvaror))}</p>"
                   if r.kampanjvaror else "")
        parts.append(
            "<div style='border:1px solid #ddd;border-radius:10px;padding:10px 14px;margin:10px 0'>"
            f"<h3 style='margin:0'><span style='display:inline-block;min-width:2em;color:#2a6db0'>{i}.</span>"
            f"{e(r.ratt)} <small style='color:#666;font-weight:normal'>({r.tid_min} min)</small></h3>"
            f"<p style='margin:6px 0 0'>{e(r.beskrivning)}</p>{kampanj}</div>"
        )
    parts.append(_kostnadsrad(res.kostnad))
    parts.append("</body></html>")
    return "\n".join(parts)


def render(res: Result) -> str:
    e = html.escape
    parts = [
        "<html><body style='font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:720px;margin:auto;color:#222'>",
        f"<h1>Veckohandla {e(res.week)}</h1>",
    ]
    if res.cart is None and not res.cart_error:
        parts.append(
            "<p style='background:#fff6e0;border:1px solid #e6c46e;padding:12px;border-radius:8px'>"
            "🛒 <b>Varukorgen är inte fylld än.</b> Kör "
            f"<code>{e(fyll_kommando(res.week))}</code> på datorn där du är inloggad på {e(res.kedja)}.</p>"
        )
    parts += [
        f"<p>{e(res.plan.kommentar)}</p>",
        "<p style='color:#666;font-size:13px'>Kampanjer skannade: "
        + ", ".join(f"{e(k)} {v}" for k, v in res.offers_count.items())
        + "</p>",
        _prislista(res.prismarkerade),
    ]
    notis = {(o.store, o.code): o.prisnotis for o in res.prismarkerade}

    parts += _varningar(res.varningar)

    if res.cart_error:
        parts.append(
            "<p style='background:#fdecea;border:1px solid #e0a39c;padding:12px;border-radius:8px'>"
            f"⚠️ <b>Varukorgen fylldes inte.</b> {_code(e(res.cart_error))}</p>"
        )

    if res.cart is not None:
        missing = res.cart.get("missing") or []
        msg = f"✅ Varukorgen på {e(res.kedja)} är fylld (korgens total: {e(str(res.cart.get('total')))})."
        if missing:
            msg += f" ⚠️ {len(missing)} varor kom inte med eller fick för lågt antal: {e(', '.join(missing))}."
        if res.cart.get("byten"):
            msg += f" {e(res.kedja)} nekade varor som ersattes med reserv: " + e("; ".join(res.cart["byten"])) + "."
        if res.cart.get("annan_enhet"):
            msg += f" Fanns redan i annan enhet och rördes inte: {e(', '.join(res.cart['annan_enhet']))}."
        doman = res.kedja_url.removeprefix("https://www.").rstrip("/")
        msg += f" Gå in på <a href='{e(res.kedja_url)}'>{e(doman)}</a>, välj tid och beställ."
        parts.append(f"<p style='background:#eef7ee;padding:12px;border-radius:8px'>{msg}</p>")

    if res.butik_flaggor:
        rader = "".join(
            f"<li><b>{e(_etikett(res, store))}</b>: spar {_kr0(res.butik_besparing[store])}, "
            f"ta bort {e(_upprakning([_versal(l.row.vara) for l in flaggade]))} ur korgen</li>"
            for store, flaggade in res.butik_flaggor.items()
        )
        parts.append(
            "<div style='background:#eaf2fb;border:1px solid #9cc0e6;padding:10px 12px;border-radius:8px;font-size:14px'>"
            "<b>Billigare i butik</b> – allt ligger i korgen, men så här mycket sparar du om du tar bort "
            f"varorna och köper dem i butiken:<ul style='margin:6px 0 0'>{rader}</ul></div>"
        )

    parts.append("<h2>Meny</h2>")
    for m in res.plan.middagar:
        matlada = (f" <small style='background:#f3ecfb;color:#5b3a8c;padding:1px 6px;border-radius:4px'>"
                   f"+{res.matlador[m.dag]} matlådor</small>" if res.matlador.get(m.dag) else "")
        parts.append(f"<h3>{e(m.dag)}: {e(m.ratt)} <small style='color:#666'>({m.tid_min} min)</small>{matlada}</h3>")
        parts.append(f"<p>{e(m.beskrivning)}</p>")
        if m.kampanjvaror:
            parts.append(f"<p style='color:#2a7a2a;font-size:13px'>Kampanj: {e(', '.join(m.kampanjvaror))}</p>")
        ingr = "".join(f"<li>{e(i.mangd)} {e(i.namn)}</li>" for i in m.ingredienser)
        steps = "".join(f"<li>{e(s)}</li>" for s in m.instruktioner)
        parts.append(f"<details><summary>Recept</summary><ul>{ingr}</ul><ol>{steps}</ol></details>")

    parts.append(f"<h2>{e(res.willys_namn)} – {_kr(res.willys_total)}</h2><table cellpadding='4' style='border-collapse:collapse;font-size:14px'>")
    parts.append("<tr style='text-align:left;border-bottom:1px solid #ccc'><th>Vara</th><th>Produkt</th><th>Antal</th><th>Pris</th></tr>")
    for l in res.lines:
        if l.row.kanske_hemma or l.kop_i_butik:
            continue
        if l.borttagen:
            parts.append(
                f"<tr><td>{e(l.row.vara)}<br><small style='color:#666'>{e(l.row.behov)}</small></td>"
                f"<td colspan='3' style='color:#c00'><b>Köp manuellt</b> – inget alternativ fungerade: {e(l.borttagen)}</td></tr>"
            )
        elif l.product:
            kolla = "<br><small style='color:#b36b00'>⚠️ Kontrollera ingredienser</small>" if l.kontrollera else ""
            if l.tillganglighet_okand:
                kolla += "<br><small style='color:#b36b00'>⚠️ Kunde inte kontrollera om varan finns i butiken</small>"
            bytt = f"<br><small style='color:#1a5fb4'>{e(byte_text(l))}</small>" if l.bytt else ""
            if l.butik_stoppad:
                bytt += f"<br><small style='color:#b36b00'>Inte i butik: {e(l.butik_stoppad)}</small>"
            if l.flaggad:
                b = l.butik
                pris = _kr(b.butik_kostnad_kr) + ("" if b.butik_kostnad_beraknad else " (uppskattat)")
                kolla_b = " Kontrollera ingredienserna i butiken." if l.butik_kontrollera else ""
                bytt += (
                    "<br><span style='display:inline-block;margin-top:3px;background:#eaf2fb;padding:2px 6px;border-radius:4px;color:#1a4f8b'>"
                    f"Billigare i butik: {e(b.butik_erbjudande or '')} {e(pris)} på {e(b.butik)}, spar {_kr(l.butik_spar)}."
                    f"{_prisetikett(notis.get((b.butik, b.butik_kod or ''), ''))} "
                    f"Ta bort ur korgen om du köper den där.{e(kolla_b)}</span>"
                )
            if l.storpack:
                jp = l.product.effektivt_enhetspris(l.qty) or l.product.jamforpris
                pris = f" ({jp:.2f} kr/{l.product.jamfor_enhet})".replace(".", ",") if jp is not None else ""
                bytt += f"<br><small style='color:#2a7a2a'>Storpack, lägst jämförpris{e(pris)}</small>"
            promo = f"<br><small style='color:#c00'>{e(l.product.promo_text)}</small>" if l.product.promo_text else ""
            promo += _prisetikett(notis.get((res.willys_namn, l.product.code), ""))
            parts.append(
                f"<tr><td>{e(l.row.vara)}<br><small style='color:#666'>{e(l.row.behov)}</small></td>"
                f"<td><a href='{e(l.product.url)}'>{e(l.product.name)}</a> {e(l.product.size)}{promo}{kolla}{bytt}</td>"
                f"<td>{l.qty}</td><td>{_kr(l.willys_cost)}</td></tr>"
            )
        else:
            parts.append(f"<tr><td>{e(l.row.vara)}</td><td colspan='3' style='color:#c00'>Hittade ingen passande vara – köp manuellt</td></tr>")
    parts.append("</table>")

    hemma = [l for l in res.lines if l.row.kanske_hemma]
    if hemma:
        parts.append("<h2>Kolla om du har hemma</h2><p style='color:#666;font-size:13px'>Ligger inte i korgen.</p><ul>")
        for l in hemma:
            kvar = f" – Uppskattat kvar: ca {l.lager_kvar:.0f} st" if l.lager_kvar is not None else ""
            if l.product:
                parts.append(f"<li>{e(l.row.vara)} ({e(l.row.behov)}): {e(l.product.name)} {e(l.product.size)} – {_kr(l.willys_cost)}{kvar}</li>")
            else:
                parts.append(f"<li>{e(l.row.vara)} ({e(l.row.behov)}){kvar}</li>")
        parts.append("</ul>")

    for store, rader in res.kop_i_butik.items():
        parts.append(f"<h2>Köp i butik – {e(_etikett(res, store))}</h2>"
                     "<p style='color:#666;font-size:13px'>Finns inte i e-handeln och ligger därför inte i korgen.</p><ul>")
        for l in rader:
            b = l.butik
            pris = _kr(b.butik_kostnad_kr) + ("" if b.butik_kostnad_beraknad else " (uppskattat)")
            kolla = " <small style='color:#b36b00'>⚠️ Kontrollera ingredienser</small>" if l.butik_kontrollera else ""
            parts.append(f"<li>{e(l.row.vara)}: {e(b.butik_erbjudande or '')} × {b.butik_antal} ≈ {pris}{kolla}</li>")
        parts.append("</ul>")

    parts.append(f"<h2>Korgen: {_kr(res.willys_total)}</h2>")
    if res.butik_besparing:
        parts.append(f"<p>Om du tar alla flaggade butiksalternativ: <b>{_kr(res.med_butiksalternativ)}</b> "
                     f"(spar {_kr(sum(res.butik_besparing.values()))})</p>")
    if res.kop_i_butik_total:
        parts.append(f"<p>Plus köp i butik: ca {_kr(res.kop_i_butik_total)}</p>")
    parts.append(_kostnadsrad(res.kostnad))
    parts.append("</body></html>")
    return "\n".join(parts)


def send(cfg: dict, subject: str, body_html: str, password: str) -> None:
    ec = cfg["epost"]
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, ec["fran"], ec["till"]
    msg.set_content("Öppna mejlet i en HTML-kapabel klient.")
    msg.add_alternative(body_html, subtype="html")
    with smtplib.SMTP(ec["smtp_host"], ec["smtp_port"]) as s:
        s.starttls()
        s.login(ec["fran"], password)
        s.send_message(msg)
