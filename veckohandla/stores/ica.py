"""ICA: veckoerbjudanden från ica.se (inbäddad JSON på butikens erbjudandesida).

ICA:s e-handel (handlaprivatkund.ica.se) blockerar automatiserade webbläsare, så den
används inte – ICA-kampanjer blir i stället en kompletterande lista för butiksbesök.
"""

from __future__ import annotations

import json
import re

import httpx

from ..models import Offer

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36",
    "Accept-Language": "sv-SE,sv;q=0.9",
}


def _get(url: str) -> str:
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _js_object(html: str, marker: str) -> dict:
    """Plocka ut ett inbäddat `window.X = {...}`-objekt och gör det till giltig JSON."""
    start = html.find(marker)
    if start < 0:
        raise ValueError(f"Hittade inte {marker!r} – har ICA ändrat sidan?")
    body = html[start + len(marker):]
    body = body[: body.find("</script>")].strip().rstrip(";")
    body = re.sub(r"(?<=[:\[,])undefined(?=[,\]}])", "null", body)
    body = re.sub(r"new Map\(\[\]\)", "null", body)
    obj, _ = json.JSONDecoder().raw_decode(body)
    return obj


def fetch_offers(slug: str, store_name: str) -> list[Offer]:
    html = _get(f"https://www.ica.se/erbjudanden/{slug}/")
    data = _js_object(html, "window.__INITIAL_DATA__ = ")
    offers = []
    for o in data.get("offers", {}).get("weeklyOffers", []):
        d = o.get("details", {})
        store = (o.get("stores") or [{}])[0]
        deal = d.get("mechanicInfo", "")
        if o.get("restriction"):
            deal += f" ({o['restriction']})"
        offers.append(
            Offer(
                store=store_name,
                name=d.get("name", ""),
                brand=d.get("brand", ""),
                deal=deal,
                compare_price=o.get("comparisonPrice", ""),
                category=o.get("category", {}).get("articleGroupName", ""),
                regular_price=store.get("regularPrice", ""),
                online=store.get("onlineInd"),
            )
        )
    return offers
