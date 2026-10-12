"""Gemensamt omförsök för butikernas HTTP-anrop."""

from __future__ import annotations

import time
from typing import Callable

import httpx

PAUSER_S = (2, 5)  # paus före försök 2 och 3
_sleep = time.sleep  # byts ut i tester


def med_omforsok(anrop: Callable[[], httpx.Response]) -> httpx.Response:
    """Upp till 3 försök vid timeout, anslutningsfel eller 5xx. 4xx försöks inte igen."""
    for forsok in range(len(PAUSER_S) + 1):
        sista = forsok == len(PAUSER_S)
        try:
            r = anrop()
        except httpx.TransportError:  # timeout, anslutningsfel m.m.
            if sista:
                raise
        else:
            if r.status_code < 500 or sista:
                r.raise_for_status()
                return r
        _sleep(PAUSER_S[forsok])
    raise AssertionError("onåbar")
