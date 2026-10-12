"""Willys: veckokampanjer per butik och sök i e-handelns sortiment (öppna JSON-endpoints)."""

from __future__ import annotations

import re

import httpx

from ..models import Offer, Product, parse_promo_max

BASE = "https://www.willys.se"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128 Safari/537.36",
    "Accept": "application/json",
}


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, headers=HEADERS, timeout=30, follow_redirects=True)


def find_stores(query: str) -> list[dict]:
    with _client() as c:
        r = c.get("/axfood/rest/search/store", params={"q": query, "online": "false"})
        r.raise_for_status()
        return r.json().get("results") or []


def fetch_offers(store_id: str, store_name: str) -> list[Offer]:
    """E-handelns kampanjer (det boten kan lägga i varukorgen), inte butikens hyllkampanjer."""
    offers: list[Offer] = []
    with _client() as c:
        page = 0
        while True:
            r = c.get(
                "/search/campaigns/online",
                params={"q": store_id, "type": "PERSONAL_GENERAL", "page": page, "size": 100},
            )
            r.raise_for_status()
            data = r.json()
            for item in data.get("results", []):
                promo = (item.get("potentialPromotions") or [{}])[0]
                offers.append(
                    Offer(
                        store=store_name,
                        name=item.get("name", ""),
                        brand=item.get("manufacturer") or "",
                        deal=(promo.get("conditionLabel") or "") + " " + (promo.get("rewardLabel") or ""),
                        compare_price=promo.get("comparePrice") or "",
                        category=item.get("googleAnalyticsCategory") or "",
                        regular_price=item.get("price") or "",
                        online=item.get("online"),
                    )
                )
            page += 1
            if page >= data.get("pagination", {}).get("numberOfPages", 0):
                break
    for o in offers:
        o.deal = o.deal.strip()
    return offers


_APPROX = re.compile(r"ca:?\s*(\d+(?:[.,]\d+)?)\s*(kg|g)\b", re.I)


def _piece_weight_kg(display: str) -> float | None:
    """'ca: 120g' -> 0.12, 'ca: 1.2kg' -> 1.2"""
    if m := _APPROX.search(display or ""):
        v = float(m.group(1).replace(",", "."))
        return v if m.group(2).lower() == "kg" else v / 1000
    return None


def _to_product(item: dict, store_name: str) -> Product:
    p = Product(
        store=store_name,
        code=item["code"],
        name=f"{item.get('name', '')} {item.get('manufacturer') or ''}".strip(),
        price=float(item.get("priceValue") or 0),
        compare_price=f"{item.get('comparePrice', '')}/{item.get('comparePriceUnit', '')}",
        size=item.get("displayVolume") or "",
        url=f"{BASE}/produkt/{item['code']}",
        extra={"pickUnit": "pieces"},
    )
    # Lösvikt (_KG) köps per styck; priset per kg räknas om till uppskattat styckpris
    weight = _piece_weight_kg(p.size) if p.code.endswith("_KG") else None
    if p.code.endswith("_KG") and weight is None:
        p.extra["pickUnit"] = "kilogram"
    elif weight:
        p.price = round(p.price * weight, 2)
        p.extra["weight_kg"] = weight
    promos = [x for x in item.get("potentialPromotions") or [] if x.get("price") is not None]
    if promos:
        pr = promos[0]
        qty = pr.get("qualifyingCount") or 1
        # Sök-API:t anger styckpris i ett objekt ("2 för 15" -> value 7.5), kampanj-API:t totalpris som tal
        price = pr["price"]
        total = float(price["value"]) * qty if isinstance(price, dict) else float(price)
        if weight:
            total = round(total * weight, 2)
        p.promo_qty, p.promo_total = qty, total
        p.promo_text = f"{pr.get('conditionLabel') or ''} {pr.get('rewardLabel') or ''}".strip()
        p.promo_max = pr.get("redeemLimit") or parse_promo_max(pr.get("redeemLimitLabel") or "")
        if pr.get("redeemLimitLabel"):
            p.promo_text += f" ({pr['redeemLimitLabel']})"
    return p


def search(query: str, store_name: str, limit: int = 8) -> list[Product]:
    with _client() as c:
        r = c.get("/search", params={"q": query, "size": limit, "page": 0})
        r.raise_for_status()
        results = r.json().get("results") or []
        return [_to_product(i, store_name) for i in results[:limit] if i.get("online", True)]
