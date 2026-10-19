"""Schemalagd veckokörning: config-sökväg, färska kampanjer, en gång per vecka och önskemål."""

import datetime as dt
import sys

import pytest
import yaml

from veckohandla import __main__ as huvud
from veckohandla import pipeline
from veckohandla.models import Offer
from veckohandla.pipeline import KampanjerInteUppe, kampanjerna_ar_farska
from veckohandla.pipeline import kontrollera_farska_kampanjer as KONTROLL  # originalet, före conftest-patchen
from veckohandla.stores import willys

from .conftest import fixtur_json

ONSDAG_V42 = dt.date(2026, 10, 14)
MANDAG_V43 = dt.date(2026, 10, 19)
CFG = {"butiker": {"willys": {"namn": "W", "store_id": "2341"}, "ica": []}}


def offline_offers():
    return [willys._to_offer(i, "W (i butik)") for i in fixtur_json("willys_campaigns_offline.json")["results"]]


# ---------- Startdatum ----------

def test_startdatum_ur_fixturerna():
    assert willys._datum("12/10-2026") == dt.date(2026, 10, 12)
    assert willys._datum(None) is None and willys._datum("31/02-2026") is None
    assert [o.start for o in offline_offers()][:2] == [dt.date(2026, 10, 12)] * 2
    # E-handelns kampanjer saknar startDate (verifierat live) – därför används butiksflödet
    online = [willys._to_offer(i, "W") for i in fixtur_json("willys_campaigns_online.json")["results"]]
    assert all(o.start is None for o in online)


def test_farska_i_innevarande_vecka_men_inte_veckan_efter():
    offers = offline_offers()
    assert kampanjerna_ar_farska(offers, ONSDAG_V42)
    assert not kampanjerna_ar_farska(offers, MANDAG_V43)  # måndag morgon innan nya kampanjer är uppe


def test_kontrollen_avbryter_med_tydligt_meddelande():
    with pytest.raises(KampanjerInteUppe, match="Veckans kampanjer är inte uppe än"):
        KONTROLL(CFG, offline_offers(), idag=MANDAG_V43)
    KONTROLL(CFG, offline_offers(), idag=ONSDAG_V42)  # inget fel


def test_kontrollen_hamtar_butiksflodet_om_det_saknas(monkeypatch):
    anrop = []
    monkeypatch.setattr(willys, "fetch_offers", lambda sid, namn, kanal="online": anrop.append(kanal) or offline_offers())
    utan_start = [Offer(store="W", name="x", brand="", deal="", compare_price="", category="")]
    KONTROLL(CFG, utan_start, idag=ONSDAG_V42)
    assert anrop == ["offline"]


def test_run_avbryter_fore_claude(data_dir, monkeypatch):
    monkeypatch.setattr(pipeline, "kontrollera_farska_kampanjer",
                        lambda cfg, offers, idag=None: KONTROLL(cfg, offers, idag=MANDAG_V43))
    monkeypatch.setattr(pipeline, "fetch_all_offers", lambda cfg, v: offline_offers())

    class Planerare:
        def __init__(self, *a):
            pass

        def plan_week(self, *a):
            raise AssertionError("Claude får inte anropas")

    monkeypatch.setattr(pipeline, "Planner", Planerare)

    class Session:
        butik_vald = True

    cfg = {**CFG, "claude": {"model": "x"}, "hushall": {"sparrord": []}, "optimering": {}}
    with pytest.raises(KampanjerInteUppe):
        pipeline._run(cfg, Session(), False, log=lambda *a: None)


# ---------- Kommandoraden ----------

@pytest.fixture
def config_fil(tmp_path, monkeypatch):
    p = tmp_path / "hem" / "config.yaml"
    p.parent.mkdir()
    p.write_text(yaml.safe_dump({"hushall": {"preferenser": "Barnvänligt."}, "epost": {"till": "x@example.com"},
                                 "butiker": CFG["butiker"]}, allow_unicode=True))
    monkeypatch.setenv("VECKOHANDLA_CONFIG", str(p))
    monkeypatch.setattr(huvud, "load_env", lambda: None)  # läs aldrig en riktig .env i test
    return p


def kor_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["veckohandla", "kor", *argv])
    return huvud.main()


def test_veckohandla_config_pekar_ut_filen(config_fil):
    assert huvud.config_path() == config_fil
    assert huvud.load_config()["hushall"]["preferenser"] == "Barnvänligt."


def test_kampanjer_inte_uppe_ger_exit_3_utan_felmejl(config_fil, data_dir, monkeypatch):
    from veckohandla import report

    monkeypatch.setenv("SMTP_PASSWORD", "fejk")
    monkeypatch.setattr(report, "send", lambda *a, **k: pytest.fail("inget mejl ska skickas"))

    def run(cfg, fill_cart=False):
        raise KampanjerInteUppe("Veckans kampanjer är inte uppe än")

    monkeypatch.setattr(pipeline, "run", run)
    assert kor_main(monkeypatch) == 3


def test_en_gang_per_vecka(config_fil, data_dir, monkeypatch):
    korda = []
    monkeypatch.setattr(pipeline, "run", lambda cfg, fill_cart=False: korda.append(1) or pytest.fail("ska inte köras"))
    (data_dir / f"{pipeline.week_id()}.json").write_text("{}")
    assert kor_main(monkeypatch, "--en-gang-per-vecka", "--ingen-mejl") == 0
    assert korda == []


def test_utan_en_gang_per_vecka_planeras_om(config_fil, data_dir, monkeypatch):
    (data_dir / f"{pipeline.week_id()}.json").write_text("{}")
    korda = []

    class Stopp(Exception):
        pass

    def run(cfg, fill_cart=False):
        korda.append(cfg)
        raise Stopp

    monkeypatch.setattr(pipeline, "run", run)
    assert kor_main(monkeypatch, "--ingen-mejl") == 1  # oväntat fel -> exit 1, men run anropades
    assert len(korda) == 1


def test_onskemal_bara_for_den_har_korningen(config_fil, data_dir, monkeypatch):
    sett = []

    class Stopp(Exception):
        pass

    def run(cfg, fill_cart=False):
        sett.append(cfg["hushall"]["preferenser"])
        raise Stopp

    monkeypatch.setattr(pipeline, "run", run)
    kor_main(monkeypatch, "--ingen-mejl", "--onskemal", "fisk två gånger, ingen kyckling")
    assert sett == ["Barnvänligt.\nÖnskemål för just den här veckan: fisk två gånger, ingen kyckling"]
    assert "fisk" not in config_fil.read_text()  # config-filen ändras inte


# ---------- Mejlet (exit 4) ----------

@pytest.fixture
def mejl_cfg(config_fil):
    cfg = yaml.safe_load(config_fil.read_text())
    cfg["epost"] = {"till": "x@example.com", "fran": "y@example.com", "smtp_host": "smtp.example.com", "smtp_port": 587}
    config_fil.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    return cfg


@pytest.fixture
def klar_korning(data_dir, monkeypatch):
    from veckohandla.planner import Veckoplan

    res = pipeline.Result(week="2026-v43", plan=Veckoplan(middagar=[], inkopslista=[], kommentar=""), lines=[])
    monkeypatch.setattr(pipeline, "run", lambda cfg, fill_cart=False: res)
    return data_dir / "2026-v43.html"


class FejkSMTP:
    """Mockad smtplib.SMTP; fel styrs via klassattribut."""

    login_fel = None
    send_fel = None
    skickade = []

    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, pw):
        if self.login_fel:
            raise self.login_fel

    def send_message(self, msg):
        if self.send_fel:
            raise self.send_fel
        FejkSMTP.skickade.append(msg["To"])


@pytest.fixture
def smtp(monkeypatch):
    import smtplib

    monkeypatch.setattr(FejkSMTP, "login_fel", None)
    monkeypatch.setattr(FejkSMTP, "send_fel", None)
    monkeypatch.setattr(FejkSMTP, "skickade", [])
    monkeypatch.setattr(smtplib, "SMTP", FejkSMTP)
    monkeypatch.setenv("SMTP_PASSWORD", "fejk")
    return FejkSMTP


def test_mejl_skickat_ger_exit_0(mejl_cfg, klar_korning, smtp, monkeypatch, capsys):
    assert kor_main(monkeypatch) == 0
    assert smtp.skickade == ["x@example.com"]
    assert "Mejl skickat till x@example.com" in capsys.readouterr().out


def test_saknat_losenord_ger_exit_4(mejl_cfg, klar_korning, smtp, monkeypatch, capsys):
    monkeypatch.delenv("SMTP_PASSWORD")
    assert kor_main(monkeypatch) == 4
    err = capsys.readouterr().err
    assert "MEJLET SKICKADES INTE: SMTP_PASSWORD saknas" in err and str(klar_korning) in err
    assert klar_korning.exists()  # rapporten sparas ändå
    assert smtp.skickade == []


def test_nekad_inloggning_ger_exit_4(mejl_cfg, klar_korning, smtp, monkeypatch, capsys):
    import smtplib

    smtp.login_fel = smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
    assert kor_main(monkeypatch) == 4
    assert "SMTP-inloggningen nekades (535)" in capsys.readouterr().err
    assert klar_korning.exists()


@pytest.mark.parametrize("fel", ["smtp", "natverk"])
def test_misslyckad_sandning_ger_exit_4(mejl_cfg, klar_korning, smtp, monkeypatch, capsys, fel):
    import smtplib

    smtp.send_fel = smtplib.SMTPRecipientsRefused({"x@example.com": (550, b"nej")}) if fel == "smtp" else OSError("nere")
    assert kor_main(monkeypatch) == 4
    assert "MEJLET SKICKADES INTE: sändningen misslyckades" in capsys.readouterr().err
    assert klar_korning.exists()


def test_ingen_mejl_ger_exit_0_utan_losenord(mejl_cfg, klar_korning, smtp, monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD")
    assert kor_main(monkeypatch, "--ingen-mejl") == 0
    assert klar_korning.exists()
