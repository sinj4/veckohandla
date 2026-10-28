"""Bokmärket: Nodes testlöpare mot källan och den minifierade versionen, och README:s javascript:-URL."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

from veckohandla import mobil

ROT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROT / "verktyg"))
import bokmarke_url  # noqa: E402

NODE = shutil.which("node")


def _rader(korg: list[dict], med_reserver: bool) -> list[dict]:
    """Det bokmärket ska få fram ur länken, i bokmärkets egen form."""
    return [{"kod": r["code"], "antal": r["qty"], "enhet": r["pick_unit"],
             "reserver": _rader(r.get("reserver", []), False) if med_reserver else []} for r in korg]


def lankar(tmp_path) -> Path:
    """Länkar kodade av Python i alla tre former, för att Node ska avkoda dem på samma sätt."""
    korg = [{"code": "101_ST", "qty": 2, "pick_unit": "pieces", "reserver": [{"code": "102_ST", "qty": 3, "pick_unit": "pieces"}]},
            {"code": "103_KG", "qty": 1, "pick_unit": "kilogram"}]
    fall = []
    for n, kedja, form in ((1, "willys", "lång"), (25, "hemkop", "kort med reserver"), (45, "willys", "kort utan reserver")):
        lank = mobil.korg_lank(korg * n, kedja, f"https://www.{kedja}.se")
        d = mobil.avkoda(lank)
        med_reserver = "rader" in d or any("r" in r for r in d["r"])
        assert form == ("lång" if "rader" in d else "kort med reserver" if med_reserver else "kort utan reserver")
        fall.append({"lank": lank, "kedja": kedja, "rader": _rader(korg * n, med_reserver)})
    fil = tmp_path / "lankar.json"
    fil.write_text(json.dumps(fall))
    return fil


@pytest.mark.skipif(not NODE, reason="node saknas")
@pytest.mark.parametrize("variant", ["kalla", "minifierad"])
def test_node_testerna(tmp_path, variant):
    fil = bokmarke_url.KALLA
    if variant == "minifierad":
        fil = tmp_path / "bokmarke.min.js"
        fil.write_text(unquote(bokmarke_url.javascript_url().removeprefix("javascript:")))
    r = subprocess.run([NODE, "--test", str(ROT / "tests" / "js" / "bokmarke.test.mjs")], capture_output=True,
                       text=True, timeout=120, env={"PATH": "/usr/bin:/bin", "BOKMARKE_FIL": str(fil),
                                                   "BOKMARKE_LANKAR": str(lankar(tmp_path))})
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "# SKIP" not in r.stdout and "ℹ fail 0" in r.stdout


def test_minifieringen_tar_bort_kommentarer_och_radbrytningar():
    kod = bokmarke_url.minifiera(bokmarke_url.KALLA.read_text())
    assert "\n" not in kod and "/*" not in kod and kod.startswith("(function () {")


def test_readme_har_aktuell_bokmarkes_url():
    readme = (ROT / "README.md").read_text()
    assert bokmarke_url.minifiera(bokmarke_url.KALLA.read_text()) in readme, "genvägskoden i README är inaktuell"
    assert bokmarke_url.javascript_url() in readme, \
        "Kör python verktyg/bokmarke_url.py och uppdatera README (avsnittet Fyll korgen på mobilen)"
