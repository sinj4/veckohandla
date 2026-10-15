import json
import socket
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def inget_natverk(monkeypatch):
    """Testerna får inte göra nätverksanrop."""

    def stopp(*args, **kwargs):
        raise RuntimeError("Nätverksanrop i test – använd fixturer")

    monkeypatch.setattr(socket.socket, "connect", stopp)
    monkeypatch.setattr(socket, "create_connection", stopp)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    from veckohandla import pipeline

    monkeypatch.setattr(pipeline, "DATA", tmp_path)
    return tmp_path


def fixtur_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def fixtur_text(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture(autouse=True)
def farska_kampanjer(monkeypatch):
    """Kampanjerna räknas som färska i testerna; tester av själva kontrollen använder originalet."""
    from veckohandla import pipeline

    monkeypatch.setattr(pipeline, "kontrollera_farska_kampanjer", lambda cfg, offers, idag=None: None)
