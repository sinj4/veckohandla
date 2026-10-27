"""kontroll: checklistan med ✓/✗/ℹ️ – inga Claude-anrop, inga ändringar, inget nätverk i testerna."""

import json
import sys

import httpx
import pytest
import yaml

from veckohandla import __main__ as huvud
from veckohandla import kontroll, pipeline
from veckohandla.kontroll import FEL, NOTIS, OK
from veckohandla.models import Offer
from veckohandla.stores import hemkop, ica, willys

CFG = {
    "hushall": {"vuxna": 2, "middagar_per_vecka": 5, "portioner_per_middag": 2, "preferenser": "Gott", "undvik": []},
    "butiker": {"willys": {"namn": "Willys Test", "store_id": "2341"},
                "ica": [{"namn": "ICA A", "erbjudande_slug": "ica-a"},
                        {"namn": "ICA B", "erbjudande_slug": "ica-b", "bara_lokalt": True}]},
    "epost": {"till": "x@example.com"},
    "claude": {"model": "m"},
}


def offer(namn="X"):
    return Offer(store=namn, name="Ost", brand="", deal="", compare_price="", category="")


def http_fel(status):
    req = httpx.Request("GET", "https://www.ica.se/")
    return httpx.HTTPStatusError(str(status), request=req, response=httpx.Response(status, request=req))


@pytest.fixture
def config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(CFG, allow_unicode=True))
    return p


class Session:
    fel = None

    def __init__(self, store_id):
        self.store_id = store_id

    def __enter__(self):
        return self

    def __exit__(self, *e):
        pass

    def valj_butik(self):
        if Session.fel:
            raise Session.fel


@pytest.fixture
def butiker(monkeypatch):
    monkeypatch.setattr(Session, "fel", None)
    monkeypatch.setattr(willys, "WillysSession", Session)
    monkeypatch.setattr(willys, "fetch_offers", lambda sid, namn, kanal="online": [offer()] * (3 if kanal == "online" else 2))
    monkeypatch.setattr(hemkop, "fetch_offers", lambda sid, namn, kanal="online": [offer()])
    monkeypatch.setattr(ica, "fetch_offers", lambda slug, namn: [offer()] * 4)


# ---------- config ----------

def test_config_saknas(tmp_path):
    cfg, p = kontroll.las_config(tmp_path / "config.yaml")
    assert cfg is None and p.status == FEL and "python -m veckohandla init" in p.atgard


@pytest.mark.parametrize("andra, text", [
    (lambda c: c["hushall"].pop("vuxna"), "nyckeln 'vuxna' saknas"),
    (lambda c: c["butiker"].update(e_handel="coop"), "willys eller hemkop"),
    (lambda c: c["hushall"].update(matlador={"dagar": ["helg"], "extra_portioner": 1}), "okänd dag helg"),
    (lambda c: c.update(meny={"lage": "kanske"}), "meny.lage"),
])
def test_ogiltig_config(tmp_path, andra, text):
    c = json.loads(json.dumps(CFG))
    andra(c)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(c, allow_unicode=True))
    cfg, punkt = kontroll.las_config(p)
    assert cfg is None and punkt.status == FEL and text in punkt.text


def test_trasig_yaml(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("hushall: [\n")
    cfg, punkt = kontroll.las_config(p)
    assert cfg is None and punkt.status == FEL and "inte giltig YAML" in punkt.text


# ---------- butiker och kampanjer ----------

def test_e_handelsbutiken(butiker):
    assert kontroll.e_handelsbutik(CFG).rad() == "✓ Willys-butiken Willys Test (2341) finns"
    Session.fel = RuntimeError("Willys valde butik '1'")
    p = kontroll.e_handelsbutik(CFG)
    assert p.status == FEL and "hitta-willys" in p.atgard


def test_kampanjer_per_butik_och_ica_403_som_notis(butiker, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(ica, "fetch_offers", lambda slug, namn: (_ for _ in ()).throw(http_fel(403)) if slug == "ica-a" else [offer()])
    cfg = {**CFG, "butiker": {**CFG["butiker"], "hemkop": {"namn": "Hemköp Test", "store_id": "4127"}}}
    rader = [(p.status, p.text.split(":")[0]) for p in kontroll.kampanjer(cfg)]
    assert rader == [(OK, "Willys Test"), (OK, "Willys Test (i butik)"), (OK, "Hemköp Test"), (NOTIS, "ICA A"), (OK, "ICA B")]


def test_bara_lokalt_i_molnet_ar_notis(butiker, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sist = kontroll.kampanjer(CFG)[-1]
    assert sist.status == NOTIS and sist.text.startswith("ICA B: hämtas inte i molnet")


def test_andra_kampanjfel_ar_fel(butiker, monkeypatch):
    monkeypatch.setattr(ica, "fetch_offers", lambda slug, namn: (_ for _ in ()).throw(http_fel(500)))
    monkeypatch.setattr(willys, "fetch_offers", lambda *a, **k: [])
    punkter = kontroll.kampanjer({**CFG, "butiker": {**CFG["butiker"], "ica": CFG["butiker"]["ica"][:1]}})
    assert [(p.status, p.text) for p in punkter[:2]] == [
        (FEL, "Willys Test: inga kampanjer"), (FEL, "Willys Test (i butik): inga kampanjer")]
    assert punkter[2].status == FEL and punkter[2].text.startswith("ICA A: kampanjerna gick inte att hämta")


# ---------- Claude ----------

class Proc:
    def __init__(self, stdout):
        self.stdout, self.stderr = stdout, ""


@pytest.fixture
def claude_miljo(monkeypatch, tmp_path):
    for v in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_BIN"):
        monkeypatch.delenv(v, raising=False)
    exe = tmp_path / "claude"
    exe.write_text("")
    anrop = []
    status = {"loggedIn": True, "subscriptionType": "pro", "email": "hemlig@example.com"}

    def run(cmd, **kw):
        anrop.append(cmd[1:])
        return Proc("2.1.311 (Claude Code)\n" if cmd[1:] == ["--version"] else json.dumps(status))

    monkeypatch.setenv("CLAUDE_BIN", str(exe))
    monkeypatch.setattr(kontroll.subprocess, "run", run)
    return exe, anrop, status


def test_claude_inloggad_utan_modellanrop(claude_miljo):
    exe, anrop, _ = claude_miljo
    p = kontroll.claude()
    assert p.rad() == f"✓ Claude Code 2.1.311 (Claude Code) ({exe}), inloggad, pro"
    assert anrop == [["--version"], ["auth", "status", "--json"]]  # inga -p-anrop
    assert "hemlig" not in p.rad()


def test_claude_inte_inloggad(claude_miljo):
    claude_miljo[2]["loggedIn"] = False
    p = kontroll.claude()
    assert p.status == FEL and "inte inloggad" in p.text


def test_claude_saknas_men_api_nyckel_finns(monkeypatch):
    monkeypatch.setattr(kontroll, "claude_bin", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert kontroll.claude().status == FEL
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert kontroll.claude().status == OK


# ---------- SMTP, inloggning, data ----------

def test_smtp(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert kontroll.smtp().status == FEL
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    assert kontroll.smtp().rad() == "✓ SMTP-lösenord finns"


def test_inloggning(tmp_path, monkeypatch):
    assert "Ingen sparad Willys-inloggning" in kontroll.inloggning(CFG, tmp_path).text
    (tmp_path / "willys").mkdir()
    monkeypatch.setattr(kontroll, "inloggad_som", lambda nyckel, base: "anonymous")
    assert kontroll.inloggning(CFG, tmp_path).text == "Willys-inloggningen har gått ut"
    monkeypatch.setattr(kontroll, "inloggad_som", lambda nyckel, base: "123")
    assert kontroll.inloggning(CFG, tmp_path).rad() == "✓ Inloggad hos Willys"


def test_data_skrivbar_utan_att_skriva(tmp_path):
    fore = set(tmp_path.rglob("*"))
    assert kontroll.data_skrivbar(tmp_path / "data").text.endswith("(skapas vid första körningen)")
    (tmp_path / "data").mkdir()
    assert kontroll.data_skrivbar(tmp_path / "data").status == OK
    assert set(tmp_path.rglob("*")) == fore | {tmp_path / "data"}
    las = tmp_path / "las"
    las.mkdir(mode=0o500)
    try:
        assert kontroll.data_skrivbar(las / "data").status == FEL
    finally:
        las.chmod(0o700)


# ---------- Hela kontrollen ----------

def test_hela_kontrollen(config, tmp_path, butiker, claude_miljo, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "x")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    utskrift = []
    assert kontroll.kor(config, tmp_path, tmp_path, med_inloggning=False, skriv=utskrift.append) == 0
    text = "\n".join(utskrift)
    assert "✓ Willys Test: 3 kampanjer" in text and "✓ ICA B: 4 kampanjer" in text
    assert "ℹ️ Inloggningen kontrollerades inte (--utan-inloggning)" in text
    assert text.endswith("Allt ser bra ut.")

    monkeypatch.delenv("SMTP_PASSWORD")
    utskrift.clear()
    assert kontroll.kor(config, tmp_path, tmp_path, med_inloggning=False, skriv=utskrift.append) == 1
    assert utskrift[-1] == "\n1 sak att åtgärda."


def test_kommandot_utan_config(tmp_path, monkeypatch, capsys, claude_miljo):
    monkeypatch.setenv("VECKOHANDLA_CONFIG", str(tmp_path / "saknas.yaml"))
    monkeypatch.setattr(huvud, "load_env", lambda: None)
    monkeypatch.setattr(pipeline, "DATA", tmp_path)
    monkeypatch.setattr(sys, "argv", ["veckohandla", "kontroll", "--utan-inloggning"])
    assert huvud.main() == 1
    out = capsys.readouterr().out
    assert "✗" in out and "python -m veckohandla init" in out
