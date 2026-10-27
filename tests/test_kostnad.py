"""Claude-förbrukning: summering per steg, kostnadsfil, logg och rad i rapporten."""

import json
from types import SimpleNamespace

import pytest
from anthropic.types import Usage

from veckohandla import pipeline, planner, report
from veckohandla.pipeline import Result
from veckohandla.planner import Planner, Produktval, Veckoplan, forbrukning_text


class Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def claude_svar(struktur, inn, ut, cache_skapad, cache_last, kostnad):
    return json.dumps({
        "is_error": False, "structured_output": struktur, "total_cost_usd": kostnad,
        "usage": {"input_tokens": inn, "output_tokens": ut, "cache_creation_input_tokens": cache_skapad,
                  "cache_read_input_tokens": cache_last, "service_tier": "standard"},
    })


@pytest.fixture
def claude_code(monkeypatch):
    svar = []

    def run(cmd, **kw):
        if cmd[1:] == ["--version"]:
            return Proc(stdout="2.1.308 (Claude Code)")
        return Proc(stdout=svar.pop(0))

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_BIN", "/x/claude")
    monkeypatch.setattr(planner.subprocess, "run", run)
    return svar


TOM_PLAN = {"middagar": [], "inkopslista": [], "kommentar": ""}


def test_claude_code_summeras_per_steg(claude_code):
    claude_code += [
        claude_svar(TOM_PLAN, 10, 2000, 30000, 0, 0.30),
        claude_svar({"val": []}, 5, 500, 0, 30000, 0.05),
        claude_svar({"val": []}, 5, 400, 0, 30000, 0.04),
    ]
    p = Planner("opus", "sonnet")
    p._parse("x", Veckoplan, "s", effort="high", model="opus")
    p._parse("x", Produktval, "s", effort="medium", model="sonnet")
    p._parse("x", Produktval, "s", effort="medium", model="sonnet")

    s = p.forbrukning_sammanfattning()
    assert s["kalla"] == "claude-code"
    assert s["steg"]["meny"] == {"anrop": 1, "input_tokens": 10, "output_tokens": 2000, "cache_skapad_tokens": 30000,
                                 "cache_last_tokens": 0, "kostnad_usd": 0.3, "modeller": ["opus"]}
    assert s["steg"]["produktval"]["anrop"] == 2 and s["steg"]["produktval"]["output_tokens"] == 900
    assert s["totalt"]["anrop"] == 3 and s["totalt"]["kostnad_usd"] == 0.39
    assert s["totalt"]["modeller"] == ["opus", "sonnet"]
    assert forbrukning_text(s) == (
        "meny: 30 010 tokens in, 2 000 ut, ≈ 0,30 USD · produktval: 60 010 tokens in, 900 ut, ≈ 0,09 USD · "
        "totalt: 90 020 tokens in, 2 900 ut, ≈ 0,39 USD (listpris – med abonnemang räknas det mot kvoten)"
    )


def test_forbrukning_registreras_aven_nar_svaret_ar_fel(claude_code):
    claude_code.append(json.dumps({"is_error": True, "result": "fel", "usage": {"input_tokens": 3, "output_tokens": 1},
                                   "total_cost_usd": 0.01}))
    p = Planner("m")
    with pytest.raises(RuntimeError):
        p._parse("x", Veckoplan, "s", effort="high", model="m")
    assert p.forbrukning["meny"].anrop == 1


def test_api_ger_tokens_men_ingen_kostnad(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fejk")
    p = Planner("haiku", "haiku")
    usage = Usage(input_tokens=100, output_tokens=50, cache_read_input_tokens=1000, cache_creation_input_tokens=0)

    def parse(**kw):
        return SimpleNamespace(usage=usage, stop_reason="end_turn", parsed_output=Produktval(val=[]))

    p.client = SimpleNamespace(messages=SimpleNamespace(parse=parse))
    p._parse("x", Produktval, "s", effort="medium", model="haiku")
    s = p.forbrukning_sammanfattning()
    assert s["kalla"] == "api"
    assert s["steg"]["produktval"]["input_tokens"] == 100 and s["totalt"]["kostnad_usd"] is None
    assert forbrukning_text(s) == "produktval: 1 100 tokens in, 50 ut · totalt: 1 100 tokens in, 50 ut"


def test_kostnadsfilen_far_en_post_per_korning(data_dir, claude_code):
    claude_code += [claude_svar(TOM_PLAN, 1, 2, 0, 0, 0.01), claude_svar(TOM_PLAN, 1, 2, 0, 0, 0.02)]
    loggat = []
    for korning in ("förslag", "veckomeny"):
        p = Planner("m")
        p._parse("x", Veckoplan, "s", effort="high", model="m")
        pipeline.spara_forbrukning("2026-v44", p, korning, loggat.append)
    poster = json.loads((data_dir / "2026-v44-kostnad.json").read_text())
    assert [(x["korning"], x["totalt"]["kostnad_usd"]) for x in poster] == [("förslag", 0.01), ("veckomeny", 0.02)]
    assert loggat[0].startswith("Claude-förbrukning: meny: 1 tokens in, 2 ut, ≈ 0,01 USD")
    assert list(data_dir.glob(pipeline.PLAN_GLOB)) == []  # kostnadsfilen är ingen veckoplan


def test_rapporten_har_en_kostnadsrad_langst_ner():
    kostnad = {"kalla": "api", "steg": {}, "totalt": {"input_tokens": 5, "output_tokens": 7}}
    res = Result(week="2026-v44", plan=Veckoplan(middagar=[], inkopslista=[], kommentar=""), lines=[], kostnad=kostnad)
    html = report.render(res)
    assert "Claude: totalt: 5 tokens in, 7 ut" in html
    assert html.index("Claude: totalt") > html.index("Korgen:")
    assert "Claude:" not in report.render(Result(week="v", plan=res.plan, lines=[]))
