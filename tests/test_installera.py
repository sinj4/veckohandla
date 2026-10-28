"""init: config.yaml från config.example.yaml (kommentarer kvar), frågor med standardsvar och --ingen-fraga."""

import stat
import sys
from pathlib import Path

import pytest
import yaml

from veckohandla import __main__ as huvud
from veckohandla import installera, kontroll, yamltext
from veckohandla.installera import Butik, Fragor, Svar

EXEMPEL = Path(__file__).resolve().parent.parent / "config.example.yaml"


def bygg(**kw):
    s = Svar(butik=kw.pop("butik", Butik("willys", "1234", "Willys Testort")), **kw)
    text = installera.bygg_config(EXEMPEL.read_text(), s)
    return text, yaml.safe_load(text)


# ---------- yamltext ----------

def test_yamltext_satter_lagger_till_och_tar_bort():
    t = "a:\n  b: 1   # kommentar\n  c: [x]\n# mellan\nd:\n  e: 2\n"
    t = yamltext.satt(t, ("a", "b"), "två ord")
    t = yamltext.satt(t, ("a", "ny"), {"x": 1})
    t = yamltext.ta_bort(t, ("a", "c"))
    t = yamltext.satt(t, ("f",), ["1", "ja"])
    assert yaml.safe_load(t) == {"a": {"b": "två ord", "ny": {"x": 1}}, "d": {"e": 2}, "f": ["1", "ja"]}
    assert "  b: två ord   # kommentar\n" in t and "# mellan" in t


# ---------- config ----------

def test_config_med_alla_svar_och_kommentarerna_kvar():
    text, cfg = bygg(
        butik=Butik("hemkop", "4127", "Hemköp Testort"),
        ica=[{"namn": "ICA Test", "erbjudande_slug": "ica-test-1", "bara_lokalt": True}],
        vuxna=2, barn=[6, 3], middagar=4, onskemal="Mycket grönsaker: gärna soppor # och gryta",
        matlador_dagar=["tisdag"], matlador_extra=3, undvik_val=["flaskfritt", "notfritt", "laktosfritt"],
        undvik_egen=["svamp"], lage="val", epost="test@example.com",
    )
    h = cfg["hushall"]
    assert (h["vuxna"], h["barn"], h["middagar_per_vecka"], h["portioner_per_middag"]) == (2, [6, 3], 4, 4)
    assert h["preferenser"] == "Mycket grönsaker: gärna soppor # och gryta"
    assert h["matlador"] == {"dagar": ["tisdag"], "extra_portioner": 3}
    assert h["undvik"] == [installera.UNDVIK_VAL["flaskfritt"][0], installera.UNDVIK_VAL["notfritt"][0],
                           installera.UNDVIK_VAL["laktosfritt"][0], "svamp"]
    assert "fläsk" in h["sparrord"] and "cashew" in h["sparrord"] and "laktos" not in h["sparrord"]
    assert "svinkött" in h["sparrord_ingredienser"] and "mandel" in h["sparrord_ingredienser"]
    assert cfg["butiker"] == {"e_handel": "hemkop", "hemkop": {"namn": "Hemköp Testort", "store_id": "4127", "i_butik": True},
                              "ica": [{"namn": "ICA Test", "erbjudande_slug": "ica-test-1", "bara_lokalt": True}]}
    assert cfg["meny"]["lage"] == "val" and cfg["epost"]["till"] == cfg["epost"]["fran"] == "test@example.com"
    assert cfg["claude"] == {"model": "claude-sonnet-5-5", "model_meny": "claude-sonnet-5-5",
                             "model_produkter": "claude-haiku-5-5"}
    # Kommentarerna från exemplet finns kvar, även på samma rad som värdet
    for kommentar in ("# Fritext som skickas till menyplaneraren", "# Hårda krav", "# Basvaror som alltid finns hemma",
                      "lage: val        # auto = färdig meny"):
        assert kommentar in text
    # Exemplets Willys-butik och ICA-butiker följer inte med
    assert '"0000"' not in text and "Exempelstad" not in text and "ica-supermarket-exempelstad" not in text


def test_minimal_config_ar_giltig_for_kontrollen(tmp_path):
    text, cfg = bygg(undvik_val=[], billiga_modeller=False)
    assert cfg["butiker"] == {"e_handel": "willys", "willys": {"namn": "Willys Testort", "store_id": "1234", "i_butik": True},
                              "ica": []}
    assert "matlador" not in cfg["hushall"] and cfg["hushall"]["undvik"] == []
    assert cfg["claude"]["model_meny"] == "claude-opus-5-5"  # exemplets modeller
    assert cfg["hushall"]["preferenser"].startswith("Barnvänlig vardagsmat")  # exemplets önskemål
    p = tmp_path / "config.yaml"
    p.write_text(text)
    assert kontroll.las_config(p)[1].status == kontroll.OK


def test_skriv_env_behaller_andra_rader(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# kommentar\nANTHROPIC_API_KEY=a\nSMTP_PASSWORD=gammalt\n")
    installera.skriv_env(env, "SMTP_PASSWORD", "nytt")
    assert env.read_text() == "# kommentar\nANTHROPIC_API_KEY=a\nSMTP_PASSWORD=nytt\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    installera.skriv_env(tmp_path / "ny.env", "SMTP_PASSWORD", "x")
    assert (tmp_path / "ny.env").read_text() == "SMTP_PASSWORD=x\n"


@pytest.mark.parametrize("text, slug", [
    ("https://www.ica.se/erbjudanden/ica-supermarket-test-1004281/", "ica-supermarket-test-1004281"),
    ("https://www.ica.se/erbjudanden/ica-kvantum-x-5/?utm=1", "ica-kvantum-x-5"),
    (" ica-nara-y-9 ", "ica-nara-y-9"),
])
def test_ica_slug(text, slug):
    assert installera.ica_slug(text) == slug


def test_ica_namn():
    assert installera.ica_namn("ica-supermarket-exempelstad-000000") == "ICA Supermarket Exempelstad"


# ---------- interaktivt ----------

class Skript:
    def __init__(self, *svar):
        self.svar, self.fragor = list(svar), []

    def __call__(self, fraga):
        self.fragor.append(fraga)
        return self.svar.pop(0)


@pytest.fixture
def claude_ok(monkeypatch):
    monkeypatch.setattr(kontroll, "claude", lambda: kontroll.Punkt(kontroll.OK, "Claude Code finns"))


def test_hela_guiden_interaktivt(tmp_path, claude_ok):
    skript = Skript(
        "Testort", "2",                                      # ort, butik nr 2
        "https://www.ica.se/erbjudanden/ica-test-butik-77/", "", "", "",   # ICA: adress, namn = förslag, bara lokalt = ja, klart
        "", "8, 5", "", "", "j", "onsdag fredag", "",        # vuxna 2, barn, middagar 5, önskemål, matlådor
        "1 3", "selleri; koriander",                         # undvik
        "2",                                                 # läge val
        "test@example.com", "",                              # e-post, smtp
        "",                                                  # billiga modeller = ja
    )
    utskrift = []
    f = Fragor(skript, losen=lambda fraga: "hemligt-losenord", skriv=utskrift.append)
    sok = lambda ort: [Butik("willys", "1", "Willys A"), Butik("hemkop", "2", "Hemköp B")] if ort == "Testort" else []
    config, env = tmp_path / "config.yaml", tmp_path / ".env"
    assert installera.kor_guiden(f, config, EXEMPEL, env, sok=sok)
    assert skript.svar == []
    cfg = yaml.safe_load(config.read_text())
    assert cfg["butiker"]["e_handel"] == "hemkop" and cfg["butiker"]["hemkop"]["store_id"] == "2"
    assert cfg["butiker"]["ica"] == [{"namn": "ICA Test Butik", "erbjudande_slug": "ica-test-butik-77", "bara_lokalt": True}]
    h = cfg["hushall"]
    assert (h["vuxna"], h["barn"], h["portioner_per_middag"]) == (2, [8, 5], 4)
    assert h["matlador"] == {"dagar": ["onsdag", "fredag"], "extra_portioner": 2}
    assert h["undvik"][-2:] == ["selleri", "koriander"] and "cashew" in h["sparrord"]
    assert cfg["meny"]["lage"] == "val" and cfg["epost"]["till"] == "test@example.com"
    assert env.read_text() == "SMTP_PASSWORD=hemligt-losenord\n"
    alla = "\n".join(utskrift + skript.fragor)
    assert "hemligt-losenord" not in alla and str(config) not in config.read_text()
    assert "ICA blockerar automatiska anrop just nu (403). Rätterna och korgen påverkas inte, men ICA-priser\njämförs inte." in alla


def test_guiden_fragar_igen_vid_ogiltiga_svar(tmp_path, claude_ok):
    skript = Skript(
        "Ingenstans", "j", "1", "555", "Willys Egen",  # ingen träff: ange id själv (kedja 1 = Willys)
        "",                                            # ICA: klart
        "noll", "0", "",                               # vuxna: ogiltigt, för litet, standard 2
        "", "", "", "",                                # barn, middagar, önskemål, matlådor (nej)
        "9", "",                                       # undvik: ogiltigt nummer, sedan inga
        "",                                            # annat att undvika
        "3", "1",                                      # läge: ogiltigt, sedan auto
        "ingen-adress", "a@b.se", "",                  # e-post: ogiltig, giltig; smtp standard
        "n",                                           # standardmodeller
    )
    utskrift = []
    f = Fragor(skript, losen=lambda fraga: "", skriv=utskrift.append)
    assert installera.kor_guiden(f, tmp_path / "config.yaml", EXEMPEL, tmp_path / ".env", sok=lambda ort: [])
    assert skript.svar == []
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert cfg["butiker"]["willys"] == {"namn": "Willys Egen", "store_id": "555", "i_butik": True}
    assert cfg["hushall"]["vuxna"] == 2 and cfg["claude"]["model"] == "claude-opus-5-5"
    assert not (tmp_path / ".env").exists()
    for meddelande in ("Svara med ett heltal (minst 1).", "Skriv nummer mellan 1 och 4.",
                       "Välj ett nummer mellan 1 och 2.", "Ange en e-postadress."):
        assert any(meddelande in u for u in utskrift), meddelande


def test_befintlig_config_skrivs_bara_over_efter_fraga(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("gammal: ja\n")
    s = Svar(butik=Butik("willys", "1", "W"))
    assert not installera.kor_guiden(Fragor(Skript(""), skriv=lambda t: None), config, EXEMPEL, tmp_path / ".env", s)
    assert config.read_text() == "gammal: ja\n" and not (tmp_path / "config.yaml.bak").exists()
    assert installera.kor_guiden(Fragor(Skript("j"), skriv=lambda t: None), config, EXEMPEL, tmp_path / ".env", s)
    assert (tmp_path / "config.yaml.bak").read_text() == "gammal: ja\n"
    assert yaml.safe_load(config.read_text())["butiker"]["willys"]["store_id"] == "1"


# ---------- init --ingen-fraga ----------

def init(monkeypatch, *argv):
    monkeypatch.setattr(huvud, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["veckohandla", "init", "--ingen-fraga", "--utan-kontroll", *argv])
    return huvud.main()


def test_init_ingen_fraga(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(installera, "hitta_butiker", lambda ort: [Butik("hemkop", "4127", "Hemköp Testort")])
    config = tmp_path / "config.yaml"
    assert init(monkeypatch, "--config", str(config), "--ort", "Testort", "--barn", "7",
                "--ica", "ICA Test=https://www.ica.se/erbjudanden/ica-test-3/", "--undvik", "vegetariskt",
                "--matlador", "tisdag,torsdag", "--lage", "val", "--epost", "a@example.com") == 0
    cfg = yaml.safe_load(config.read_text())
    assert cfg["butiker"]["e_handel"] == "hemkop"
    assert cfg["butiker"]["ica"] == [{"namn": "ICA Test", "erbjudande_slug": "ica-test-3", "bara_lokalt": True}]
    assert cfg["hushall"]["matlador"]["dagar"] == ["tisdag", "torsdag"] and cfg["hushall"]["portioner_per_middag"] == 3
    out = capsys.readouterr().out
    assert "Nästa steg:" in out and "python -m veckohandla login" in out


@pytest.mark.parametrize("argv, fel", [
    (["--butik-id", "1"], "--butik-id kräver --kedja"),
    (["--ort", "Ingenstans"], "hittade ingen butik med e-handel i Ingenstans"),
    (["--kedja", "willys", "--butik-id", "1", "--undvik", "glutenfritt"], "okänt förval i --undvik: glutenfritt"),
    (["--kedja", "willys", "--butik-id", "1", "--ica", "bara-slug"], "--ica ska vara NAMN=SLUG"),
    ([], "ange --ort"),
])
def test_init_ingen_fraga_fel(tmp_path, monkeypatch, capsys, argv, fel):
    monkeypatch.setattr(installera, "hitta_butiker", lambda ort: [])
    assert init(monkeypatch, "--config", str(tmp_path / "config.yaml"), *argv) == 2
    assert fel in capsys.readouterr().err and not (tmp_path / "config.yaml").exists()


def test_init_ingen_fraga_skriver_inte_over_utan_flagga(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("gammal: ja\n")
    args = ["--config", str(config), "--kedja", "willys", "--butik-id", "9"]
    assert init(monkeypatch, *args) == 1 and config.read_text() == "gammal: ja\n"
    assert init(monkeypatch, *args, "--skriv-over") == 0
    assert (tmp_path / "config.yaml.bak").exists()
