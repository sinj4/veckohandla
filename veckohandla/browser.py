"""Gemensam Playwright-webbläsare med sparad profil per butik (inloggning överlever mellan körningar)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

PROFILES = Path(__file__).resolve().parent.parent / "browser-profiles"


@contextmanager
def store_browser(store_key: str, headless: bool = True):
    PROFILES.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        ctx: BrowserContext = pw.chromium.launch_persistent_context(
            str(PROFILES / store_key),
            headless=headless,
            locale="sv-SE",
            viewport={"width": 1280, "height": 900},
        )
        try:
            yield ctx
        finally:
            ctx.close()


def login_axfood(nyckel: str, namn: str, base: str, timeout_min: int = 10) -> str:
    """Öppna ett synligt fönster och vänta tills användaren loggat in (BankID) hos kedjan.

    Inloggningen sparas i browser-profiles/<nyckel>, t.ex. browser-profiles/hemkop.
    """
    with store_browser(nyckel, headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{base}/")
        print(f"Logga in i {namn}-fönstret som öppnades (väntar upp till {timeout_min} min)…", flush=True)
        deadline = time.monotonic() + timeout_min * 60
        while time.monotonic() < deadline:
            page.wait_for_timeout(3000)
            try:
                c = page.evaluate("async () => (await fetch('/axfood/rest/customer')).json()")
            except Exception:  # sidan kan navigera mitt i inloggningen
                continue
            if c.get("uid") not in (None, "anonymous"):
                page.wait_for_timeout(2000)  # låt sessionscookies sparas i profilen
                return c.get("firstName") or c["uid"]
        raise TimeoutError("Ingen inloggning upptäcktes – kör login igen")


def login_willys(timeout_min: int = 10) -> str:
    return login_axfood("willys", "Willys", "https://www.willys.se", timeout_min)
