"""HTML-rapport (mejlas) med meny, recept, Willys-korg och ev. ICA-butikslistor."""

from __future__ import annotations

import html
import re
import smtplib
from email.message import EmailMessage

from .pipeline import Result


def _kr(x: float | None) -> str:
    return "–" if x is None else f"{x:,.2f} kr".replace(",", " ").replace(".", ",")


def _code(text: str) -> str:
    """`kommando` -> <code>kommando</code> (texten är redan HTML-escapad)."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def byte_text(l) -> str:
    """'Bytt: <första valet> → <reserv> (orsak)'; fler bortvalda läggs till efter."""
    (forsta, orsak), *ovriga = l.bortvalda
    text = f"Bytt: {forsta.product.name} {forsta.product.size} → {l.product.name} {l.product.size} ({orsak})"
    for alt, o in ovriga:
        text += f"; även {alt.product.name} hoppades över ({o})"
    return text


def render(res: Result) -> str:
    e = html.escape
    parts = [
        "<html><body style='font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:720px;margin:auto;color:#222'>",
        f"<h1>Veckohandla {e(res.week)}</h1>",
        f"<p>{e(res.plan.kommentar)}</p>",
        "<p style='color:#666;font-size:13px'>Kampanjer skannade: "
        + ", ".join(f"{e(k)} {v}" for k, v in res.offers_count.items())
        + "</p>",
    ]

    for v in res.varningar:
        parts.append(
            "<p style='background:#fff6e0;border:1px solid #e6c46e;padding:10px;border-radius:8px;font-size:14px'>"
            f"⚠️ {e(v)}</p>"
        )

    if res.cart_error:
        parts.append(
            "<p style='background:#fdecea;border:1px solid #e0a39c;padding:12px;border-radius:8px'>"
            f"⚠️ <b>Varukorgen fylldes inte.</b> {_code(e(res.cart_error))}</p>"
        )

    if res.cart is not None:
        missing = res.cart.get("missing") or []
        msg = f"✅ Varukorgen på Willys är fylld (korgens total: {e(str(res.cart.get('total')))})."
        if missing:
            msg += f" ⚠️ {len(missing)} varor kom inte med eller fick för lågt antal: {e(', '.join(missing))}."
        if res.cart.get("byten"):
            msg += " Willys nekade varor som ersattes med reserv: " + e("; ".join(res.cart["byten"])) + "."
        if res.cart.get("annan_enhet"):
            msg += f" Fanns redan i annan enhet och rördes inte: {e(', '.join(res.cart['annan_enhet']))}."
        msg += " Gå in på <a href='https://www.willys.se/'>willys.se</a>, välj tid och beställ."
        parts.append(f"<p style='background:#eef7ee;padding:12px;border-radius:8px'>{msg}</p>")

    parts.append("<h2>Meny</h2>")
    for m in res.plan.middagar:
        parts.append(f"<h3>{e(m.dag)}: {e(m.ratt)} <small style='color:#666'>({m.tid_min} min)</small></h3>")
        parts.append(f"<p>{e(m.beskrivning)}</p>")
        if m.kampanjvaror:
            parts.append(f"<p style='color:#2a7a2a;font-size:13px'>Kampanj: {e(', '.join(m.kampanjvaror))}</p>")
        ingr = "".join(f"<li>{e(i.mangd)} {e(i.namn)}</li>" for i in m.ingredienser)
        steps = "".join(f"<li>{e(s)}</li>" for s in m.instruktioner)
        parts.append(f"<details><summary>Recept</summary><ul>{ingr}</ul><ol>{steps}</ol></details>")

    parts.append(f"<h2>{e(res.willys_namn)} – {_kr(res.willys_total)}</h2><table cellpadding='4' style='border-collapse:collapse;font-size:14px'>")
    parts.append("<tr style='text-align:left;border-bottom:1px solid #ccc'><th>Vara</th><th>Produkt</th><th>Antal</th><th>Pris</th></tr>")
    for l in res.lines:
        if l.buy_at_ica or l.row.kanske_hemma:
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
            promo = f"<br><small style='color:#c00'>{e(l.product.promo_text)}</small>" if l.product.promo_text else ""
            parts.append(
                f"<tr><td>{e(l.row.vara)}<br><small style='color:#666'>{e(l.row.behov)}</small></td>"
                f"<td><a href='{e(l.product.url)}'>{e(l.product.name)}</a> {e(l.product.size)}{promo}{kolla}{bytt}</td>"
                f"<td>{l.qty}</td><td>{_kr(l.willys_cost)}</td></tr>"
            )
        else:
            parts.append(f"<tr><td>{e(l.row.vara)}</td><td colspan='3' style='color:#c00'>Hittade ingen passande vara – köp manuellt</td></tr>")
    parts.append("</table>")

    hemma = [l for l in res.lines if l.row.kanske_hemma and not l.buy_at_ica]
    if hemma:
        parts.append("<h2>Kolla om du har hemma</h2><p style='color:#666;font-size:13px'>Ligger inte i korgen.</p><ul>")
        for l in hemma:
            if l.product:
                parts.append(f"<li>{e(l.row.vara)} ({e(l.row.behov)}): {e(l.product.name)} {e(l.product.size)} – {_kr(l.willys_cost)}</li>")
            else:
                parts.append(f"<li>{e(l.row.vara)} ({e(l.row.behov)})</li>")
        parts.append("</ul>")

    for store, lines in res.ica_lists.items():
        saving = res.ica_savings.get(store)
        rubrik = f"sparar ca {_kr(saving)}" if saving else "finns inte på Willys"
        parts.append(f"<h2>{e(store)} – i butik ({rubrik})</h2><ul>")
        for l in lines:
            parts.append(f"<li>{e(l.row.vara)}: {e(l.ica.ica_erbjudande or '')} × {l.ica.ica_antal} ≈ {_kr(l.ica.ica_kostnad_kr)}</li>")
        parts.append("</ul>")

    total = res.willys_total + res.ica_total
    parts.append(f"<h2>Totalt ca {_kr(total)}</h2></body></html>")
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
