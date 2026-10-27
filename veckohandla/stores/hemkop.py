"""Hemköp: tunt lager ovanpå Axfood-API:t (se axfood.py). Samma endpoints som Willys."""

from __future__ import annotations

import httpx

from ..models import Offer, Product
from . import axfood

BASE = "https://www.hemkop.se"


def _client() -> httpx.Client:
    return axfood.ny_klient(BASE)


# klienten slås upp vid varje anrop, så att _client kan bytas ut i tester
KEDJA = axfood.Kedja("hemkop", "Hemköp", BASE, klient=lambda: _client())


def find_stores(query: str) -> list[dict]:
    return KEDJA.find_stores(query)


def product_details(code: str) -> dict:
    return KEDJA.product_details(code)


def fetch_offers(store_id: str, store_name: str, kanal: str = "online") -> list[Offer]:
    return KEDJA.fetch_offers(store_id, store_name, kanal)


def search(query: str, store_name: str, limit: int = 8) -> list[Product]:
    return KEDJA.search(query, store_name, limit)


class HemkopSession(axfood.AxfoodSession):
    def __init__(self, store_id: str, client: httpx.Client | None = None):
        super().__init__(KEDJA, store_id, client)


def session(store_id: str) -> axfood.AxfoodSession:
    return HemkopSession(store_id)
