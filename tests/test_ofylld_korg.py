"""Rapporten säger tydligt när korgen inte är fylld."""

import re

import pytest

from veckohandla import report
from veckohandla.pipeline import Result
from veckohandla.planner import Veckoplan


def res(**kw):
    return Result(week="2026-v43", plan=Veckoplan(middagar=[], inkopslista=[], kommentar="Kommentar"), lines=[], **kw)


def text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


@pytest.fixture(autouse=True)
def utan_kommando(monkeypatch):
    monkeypatch.delenv("VECKOHANDLA_FYLL_KOMMANDO", raising=False)


def test_ofylld_korg_visar_standardkommandot_direkt_under_rubriken():
    html = report.render(res())
    assert ("Varukorgen är inte fylld än. Kör python -m veckohandla fyll-varukorg 2026-v43 "
            "på datorn där du är inloggad på Willys.") in text(html)
    assert html.index("</h1>") < html.index("Varukorgen är inte fylld än") < html.index("Kommentar")


def test_kommandot_tas_fran_miljovariabeln(monkeypatch):
    monkeypatch.setenv("VECKOHANDLA_FYLL_KOMMANDO", "./fyll.sh")
    assert "Kör ./fyll.sh på datorn där du är inloggad på Willys." in text(report.render(res()))


def test_ingen_ruta_nar_korgen_ar_fylld():
    html = report.render(res(cart={"total": "100 kr", "missing": []}))
    assert "inte fylld än" not in html and "Varukorgen på Willys är fylld" in html


def test_ingen_ruta_vid_korgfel():
    html = report.render(res(cart_error="Willys-inloggningen har gått ut."))
    assert "inte fylld än" not in html and "Varukorgen fylldes inte." in html
