"""Claude Code-binären: val av sökväg, versionslogg och tydligt fel när binären är för gammal."""

import json
from pathlib import Path

import pytest

from veckohandla import planner
from veckohandla.planner import Planner, Produktval


class Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


OK = json.dumps({"is_error": False, "structured_output": {"val": []}})


@pytest.fixture
def claude_code(monkeypatch):
    """Mockad subprocess.run: --version svarar med en version, annars returneras svaret i listan."""
    anrop = []
    svar = {"version": "2.1.303 (Claude Code)", "parse": Proc(stdout=OK)}

    def run(cmd, **kw):
        anrop.append(cmd)
        if cmd[1:] == ["--version"]:
            return Proc(stdout=svar["version"] + "\n")
        return svar["parse"]

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.setattr(planner.subprocess, "run", run)
    return anrop, svar


def anropa(p: Planner):
    return p._parse("prompt", Produktval, "system", effort="medium", model="claude-opus-5-5")


def test_claude_bin_gar_fore_path(claude_code, monkeypatch):
    anrop, _ = claude_code
    monkeypatch.setenv("CLAUDE_BIN", "/npm/bin/claude")
    monkeypatch.setattr(planner.shutil, "which", lambda n: "/usr/bin/claude")
    anropa(Planner("m"))
    assert anrop[0] == ["/npm/bin/claude", "--version"]
    assert anrop[1][0] == "/npm/bin/claude"


def test_path_och_sedan_local_bin(claude_code, monkeypatch):
    anrop, _ = claude_code
    monkeypatch.setattr(planner.shutil, "which", lambda n: "/usr/bin/claude")
    anropa(Planner("m"))
    assert anrop[-1][0] == "/usr/bin/claude"

    anrop.clear()
    monkeypatch.setattr(planner.shutil, "which", lambda n: None)
    anropa(Planner("m"))
    assert anrop[-1][0] == str(Path.home() / ".local/bin/claude")


def test_version_loggas_en_gang_fore_forsta_anropet(claude_code, monkeypatch, capsys):
    anrop, _ = claude_code
    monkeypatch.setenv("CLAUDE_BIN", "/npm/bin/claude")
    p = Planner("m")
    anropa(p)
    anropa(p)
    assert [c[1:] == ["--version"] for c in anrop] == [True, False, False]
    assert capsys.readouterr().out.count("Claude Code: /npm/bin/claude – version 2.1.303 (Claude Code)") == 1


def test_for_gammal_binar_ger_tydligt_fel(claude_code, monkeypatch):
    _, svar = claude_code
    monkeypatch.setenv("CLAUDE_BIN", "/opt/gammal/claude")
    svar["version"] = "2.1.197 (Claude Code)"
    svar["parse"] = Proc(stdout=json.dumps({
        "is_error": True,
        "result": "API Error: 400 Claude Code 2.1.197 does not support this model; version 2.1.280 or newer is required",
    }), returncode=1)
    with pytest.raises(RuntimeError) as e:
        anropa(Planner("m"))
    msg = str(e.value)
    assert "/opt/gammal/claude" in msg and "2.1.197" in msg and "Uppdatera Claude Code" in msg


def test_for_gammal_binar_aven_i_stderr(claude_code):
    _, svar = claude_code
    svar["parse"] = Proc(stderr="version 2.1.280 or newer is required", returncode=1)
    with pytest.raises(RuntimeError, match="Uppdatera Claude Code"):
        anropa(Planner("m"))


def test_binar_som_saknas_loggas_som_okand(monkeypatch, capsys):
    def run(cmd, **kw):
        if cmd[1:] == ["--version"]:
            raise FileNotFoundError(cmd[0])
        return Proc(stdout=OK)

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_BIN", "/finns/inte/claude")
    monkeypatch.setattr(planner.subprocess, "run", run)
    anropa(Planner("m"))
    assert "Claude Code: /finns/inte/claude – version okänd" in capsys.readouterr().out
