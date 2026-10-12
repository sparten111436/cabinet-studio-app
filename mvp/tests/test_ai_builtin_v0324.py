"""v0.3.24: the free offline Cabinet Studio AI answers typed questions from the program + live sim."""

from cabinet_studio.services import ai_assist as aa
from cabinet_studio.services.ai_providers import BUILTIN, PROVIDERS, AiSettings
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.programming import add_rung_from_elements, empty_program


def _program():
    p = empty_program()
    p = add_rung_from_elements(p, [{"kind": "contact", "var": "PB_Start", "form": "NO"},
                                   {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 2000}])
    p = add_rung_from_elements(p, [{"kind": "contact", "var": "T1.DN", "form": "NO"},
                                   {"kind": "coil", "var": "Motor", "form": "normal"}])
    p = add_rung_from_elements(p, [{"kind": "contact", "var": "PB_Stop", "form": "NO"},
                                   {"kind": "coil", "var": "Motor", "form": "normal"}])
    p = add_rung_from_elements(p, [{"kind": "contact", "var": "PB_Start", "form": "NO"},
                                   {"kind": "counter", "var": "C1", "block": "CTU", "pv": 3}])
    return p


def test_default_ai_is_free_offline_and_needs_no_key():
    s = AiSettings()
    assert s.provider == BUILTIN and not PROVIDERS[BUILTIN]["needs_key"]
    assert s.label() == "Cabinet Studio AI (free, offline)"


def test_builtin_answers_tags_rungs_glossary_problems_and_timers():
    p = _program()
    sim = ScanSimulator.from_program(p)
    sim.scan_once()
    why = aa.builtin_answer(p, sim, "why is Motor off?")
    assert "Motor is OFF" in why and "R2" in why and "R3" in why
    assert "input" in aa.builtin_answer(p, sim, "what does PB_Start do")
    assert "Rung R1" in aa.builtin_answer(p, sim, "explain rung 1")
    assert "on-delay" in aa.builtin_answer(p, sim, "what is a TON?")
    probs = aa.builtin_answer(p, sim, "check for problems")
    assert "Motor is driven by normal coils on R2, R3" in probs and "C1" in probs and "RES" in probs
    assert "T1 TON" in aa.builtin_answer(p, sim, "show timers")
    assert "Test checklist" in aa.builtin_answer(p, sim, "what should I test next")
    assert "free, offline" in aa.builtin_answer(p, sim, "hello")
    assert aa.SAFETY_NOTE in aa.builtin_answer(p, sim, "how should the e-stop work?")
