"""v0.3.21 AI selection + live AI help (no network: ai_providers._http is faked)."""

from __future__ import annotations

import json
import sys

import pytest

from cabinet_studio import __version__
from cabinet_studio.services import ai_assist as aa
from cabinet_studio.services import ai_providers as ap
from cabinet_studio.services.ladder_sim import ScanSimulator, sim_blockers
from cabinet_studio.services.programming import add_rung_from_elements, empty_program


def C(v, nc=False):
    return {"kind": "contact", "var": v, "form": "NC" if nc else "NO"}


def O(v, form="normal"):
    return {"kind": "coil", "var": v, "form": form}


def _prog():
    p = empty_program()
    p = add_rung_from_elements(p, [{"kind": "or", "branches": [[C("Start_PB")], [C("Run")]]}, C("Stop_PB", True),
                                   C("ES1_OK"), O("Run")], comment="Run seal-in")
    p = add_rung_from_elements(p, [C("Run"), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 2000}], comment="Delay")
    p = add_rung_from_elements(p, [C("T1.DN"), O("Motor")], comment="Motor after delay")
    return p


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CABINET_STUDIO_AI_SETTINGS", str(tmp_path / "ai.json"))
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)


def test_version_is_0321():
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 21)


# ------------------------------------------------------------------ settings + keys
def test_settings_default_builtin_and_round_trip_encrypts_key(tmp_path):
    s = ap.load_settings()
    assert s.provider == ap.BUILTIN and s.label().startswith("Cabinet Studio AI")
    s.provider = "anthropic"
    s.models["anthropic"] = "claude-test"
    s.set_key("anthropic", "sk-ant-SECRET-123")
    ap.save_settings(s)
    raw = (tmp_path / "ai.json").read_text(encoding="utf-8")
    assert "SECRET" not in raw
    if sys.platform == "win32":
        assert '"dpapi:' in raw
    back = ap.load_settings()
    assert back.provider == "anthropic" and back.model_for() == "claude-test"
    assert back.key_for() == "sk-ant-SECRET-123"
    assert back.label() == "Anthropic · claude-test"


def test_env_key_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-env")
    assert ap.AiSettings(provider="gemini").key_for() == "g-env"


def test_unknown_provider_in_file_falls_back(tmp_path):
    (tmp_path / "ai.json").write_text(json.dumps({"provider": "skynet"}), encoding="utf-8")
    assert ap.load_settings().provider == ap.BUILTIN


# ------------------------------------------------------------------ chat per provider
@pytest.mark.parametrize("pid,reply,check", [
    ("openai", {"choices": [{"message": {"content": "hi"}}]},
     lambda url, h, b: url.endswith("/chat/completions") and h["Authorization"] == "Bearer K"
     and b["messages"][0]["role"] == "system"),
    ("anthropic", {"content": [{"type": "text", "text": "hi"}]},
     lambda url, h, b: url.endswith("/v1/messages") and h["x-api-key"] == "K" and b["system"] == "SYS"),
    ("gemini", {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]},
     lambda url, h, b: ":generateContent" in url and h["x-goog-api-key"] == "K"
     and b["contents"][1]["role"] == "model"),
    ("ollama", {"message": {"content": "hi"}},
     lambda url, h, b: url == "http://localhost:11434/api/chat" and b["stream"] is False),
])
def test_chat_request_shape(monkeypatch, pid, reply, check):
    seen = {}

    def fake(method, url, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return reply

    monkeypatch.setattr(ap, "_http", fake)
    s = ap.AiSettings(provider=pid)
    s.set_key(pid, "K")
    msgs = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}, {"role": "user", "content": "q2"}]
    assert ap.chat("SYS", msgs, s) == "hi"
    assert check(seen["url"], seen["headers"], seen["body"])


def test_chat_needs_key_and_builtin_never_calls(monkeypatch):
    monkeypatch.setattr(ap, "_http", lambda *a, **k: pytest.fail("network used"))
    with pytest.raises(ap.AiError, match="No API key"):
        ap.chat("s", [{"role": "user", "content": "x"}], ap.AiSettings(provider="openai"))
    with pytest.raises(ap.AiError, match="Built-in"):
        ap.chat("s", [{"role": "user", "content": "x"}], ap.AiSettings())
    assert "always available" in ap.test_connection(ap.AiSettings())


def test_http_error_messages_are_friendly(monkeypatch):
    import io
    import urllib.error

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b'{"error":{"message":"bad key"}}'))

    monkeypatch.setattr(ap.urllib.request, "urlopen", boom)
    with pytest.raises(ap.AiError, match="rejected.*bad key"):
        ap._http("POST", "https://x", {}, {}, 5)


def test_list_models(monkeypatch):
    monkeypatch.setattr(ap, "_http", lambda m, url, h, b, t: {"models": [{"name": "llama3.1:8b"}]})
    assert ap.list_models(ap.AiSettings(provider="ollama")) == ["llama3.1:8b"]


# ------------------------------------------------------------------ context + built-in answers
def test_program_and_state_text():
    p = _prog()
    text = aa.program_text(p)
    assert "R1: [ XIC Start_PB | XIC Run ] -- XIO Stop_PB -- XIC ES1_OK -- OTE Run" in text
    sim = ScanSimulator.from_program(p, cycle_ms=100)
    sim.scan_once({"ES1_OK": True, "Start_PB": True})
    state = aa.sim_state_text(sim, cursor_index=1, blockers=["x"])
    assert "executing Main R2" in state and "TIMER T1 TON" in state and "Run" in state and "BLOCKERS" in state


def test_explain_rung_names_blockers_and_safety_note():
    p = _prog()
    sim = ScanSimulator.from_program(p, cycle_ms=100)
    sim.scan_once({"ES1_OK": False})
    text = aa.explain_rung(p, 0, sim)
    assert "BLOCKED" in text
    assert "Start_PB must be ON - it is an input" in text
    assert "Run is this rung's own seal-in" in text
    assert "ES1_OK must be ON" in text
    assert aa.SAFETY_NOTE in text
    t3 = aa.explain_rung(p, 2, sim)
    assert "T1.DN must be ON - it comes from T1 (rung R2)" in t3
    assert "Start the simulation" in aa.explain_rung(p, 0, None)


def test_checklist_lists_inputs_timers_and_safety():
    text = aa.test_checklist(_prog())
    assert "Start_PB: used on R1" in text and "TON T1 (R2)" in text and "Safety-related inputs" in text
    assert "Run:" not in text  # coil-driven, not an input


def test_sim_messages_carry_program_and_state():
    p = _prog()
    sim = ScanSimulator.from_program(p, cycle_ms=100)
    msgs = aa.sim_messages([{"role": "user", "content": "old"}], "why?", program=p, sim=sim, selected_index=2,
                           cursor_index=None, blockers=[], project_name="P")
    assert msgs[0]["content"] == "old"
    assert "R3:" in msgs[-1]["content"] and "SIMULATION" in msgs[-1]["content"]
    assert "Selected rung: Main R3" in msgs[-1]["content"] and msgs[-1]["content"].endswith("QUESTION: why?")
    assert "cabinet-rung" in aa.sim_system() and aa.SAFETY_NOTE in aa.sim_system()


# ------------------------------------------------------------------ proposals
def _block(obj):
    return "```cabinet-rung\n" + json.dumps(obj) + "\n```"


def test_valid_proposal_applies_and_runs():
    p = _prog()
    reply = "Fix:\n" + _block({"action": "replace", "rung": 3, "comment": "motor also on jog",
                               "elements": [{"kind": "or", "branches": [[C("T1.DN")], [C("Jog_PB")]]}, O("Motor")]})
    (prop,) = aa.parse_proposals(reply, p)
    assert prop.ok and not prop.safety
    new, rid = aa.apply_proposal(p, prop, sim_blockers_fn=sim_blockers)
    assert rid == p["rungs"][2]["id"]
    assert "R3: [ XIC T1.DN | XIC Jog_PB ] -- OTE Motor" in aa.program_text(new)
    sim = ScanSimulator.from_program(new, cycle_ms=100)
    assert sim.scan_once({"Jog_PB": True})["vars"]["Motor"] is True


def test_add_proposal_after_rung():
    p = _prog()
    (prop,) = aa.parse_proposals(_block({"action": "add", "after": 1, "elements": [C("Run"), O("Lamp")]}), p)
    new, rid = aa.apply_proposal(p, prop)
    assert new["rungs"][1]["id"] == rid and len(new["rungs"]) == 4


@pytest.mark.parametrize("obj,needle", [
    ({"action": "replace", "rung": 9, "elements": [C("A"), O("B")]}, "rung must be"),
    ({"action": "delete", "rung": 1, "elements": [C("A"), O("B")]}, "action must be"),
    ({"action": "add", "elements": [C("A"), O("B", "latch")]}, "coil form"),
    ({"action": "add", "elements": [C("A"), {"kind": "timer", "var": "T", "block": "TP", "pt_ms": 5}]}, "timer block"),
    ({"action": "add", "elements": [C("A"), {"kind": "timer", "var": "T", "block": "TON"}]}, "pt_ms"),
    ({"action": "add", "elements": [C("A"), {"kind": "pid", "var": "P"}]}, "not an instruction"),
    ({"action": "add", "elements": [{"kind": "contact", "var": "A", "form": "NO", "x": 1}, O("B")]}, "unknown field"),
    ({"action": "add", "elements": [C("A"), {"kind": "jsr", "target": "Nowhere"}]}, "not an existing routine"),
    ({"action": "add", "elements": [C("A"), {"kind": "math", "op": "CPT", "dest": "D", "expression": "(A +"}]}, "CPT"),
    ({"action": "add", "elements": [{"kind": "compare", "op": "LIM", "source_a": "N", "source_b": "1"}, O("B")]}, "source_c"),
    ({"action": "add", "elements": [C("bad tag!"), O("B")]}, "not a valid tag"),
    ({"action": "add", "elements": [{"kind": "or", "branches": [[C("A")]]}, O("B")]}, "two non-empty"),
    ({"action": "add", "elements": [], "extra": 1}, "unknown field"),
])
def test_bad_proposals_refused_whole(obj, needle):
    p = _prog()
    (prop,) = aa.parse_proposals(_block(obj), p)
    assert not prop.ok and any(needle in x for x in prop.problems), prop.problems
    with pytest.raises(ValueError, match="Refused"):
        aa.apply_proposal(p, prop)


def test_invalid_json_refused():
    (prop,) = aa.parse_proposals("```cabinet-rung\n{not json}\n```", _prog())
    assert not prop.ok and "JSON" in prop.problems[0]


def test_safety_flag_on_replaced_or_new_safety_tags():
    p = _prog()
    (a,) = aa.parse_proposals(_block({"action": "replace", "rung": 1, "elements": [C("Start_PB"), O("Run")]}), p)
    assert a.safety  # removes ES1_OK from the rung
    (b,) = aa.parse_proposals(_block({"action": "add", "elements": [C("Guard_Closed"), O("X")]}), p)
    assert b.safety


def test_apply_refuses_new_verify_errors(monkeypatch):
    p = _prog()
    (prop,) = aa.parse_proposals(_block({"action": "add", "elements": [C("A"), O("B")]}), p)
    calls = {"n": 0}

    def fake_verify(prog, devices=None):
        calls["n"] += 1
        # new program is checked first (error), then the original (clean)
        return [{"severity": "error", "code": "X", "message": "broken"}] if calls["n"] == 1 else []

    monkeypatch.setattr(aa, "verify_program", fake_verify)
    with pytest.raises(ValueError, match="verify errors: broken"):
        aa.apply_proposal(p, prop)


def test_apply_refuses_sim_blockers():
    p = _prog()
    (prop,) = aa.parse_proposals(_block({"action": "add", "elements": [C("A"), O("B")]}), p)
    with pytest.raises(ValueError, match="simulator could not run"):
        aa.apply_proposal(p, prop, sim_blockers_fn=lambda q: ["CPT empty"])
