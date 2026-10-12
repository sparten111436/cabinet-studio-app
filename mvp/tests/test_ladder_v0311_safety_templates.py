"""v0.3.11 safety template gates (Deflector criteria).

Native sim BEFORE and AFTER PLCopen IR→XML→IR. STOP / E-stop must always drop outputs.
Educational design-aid only — not certified safety logic.
"""
from __future__ import annotations

import pytest

from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import AOI_TEMPLATES, apply_aoi_template
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import empty_program, program_from_dict

CYCLE = 100
SAFETY_TEMPLATES = (
    "MotorStarter",
    "ForwardReverse",
    "EstopInterlock",
    "ValveCycle",
    "TwoHandStart",
    "OffDelayStop",
    "JogOrRun",
)
AID_NEEDLE = "EDUCATIONAL DESIGN AID ONLY"


def _rt(prog: dict) -> dict:
    return program_from_dict(import_plcopen_xml_to_program(export_program_to_plcopen_xml(prog)))


def _sim(prog: dict) -> ScanSimulator:
    return ScanSimulator.from_program(prog, cycle_ms=CYCLE)


@pytest.mark.parametrize("name", SAFETY_TEMPLATES)
def test_safety_template_has_design_aid_marking(name):
    """G-AID: description still carries the note (legacy surface)."""
    from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE

    desc = str(AOI_TEMPLATES[name].get("description") or "")
    assert AID_NEEDLE in desc.upper() or "NFPA 79" in desc or "ISO 13849" in desc
    assert "NFPA 79" in SAFETY_DESIGN_AID_NOTE and "ISO 13849" in SAFETY_DESIGN_AID_NOTE


@pytest.mark.parametrize("roundtrip", [False, True], ids=["native", "plcopen_rt"])
def test_motor_starter_gates(roundtrip):
    prog = apply_aoi_template(empty_program(), "MotorStarter")
    if roundtrip:
        prog = _rt(prog)
    sim = _sim(prog)
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False})["vars"].get("M1") is not True
    sim.scan_once({"PB_Start": True, "PB_Stop": False})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False})["vars"].get("M1") is True
    assert sim.scan_once({"PB_Start": True, "PB_Stop": True})["vars"].get("M1") is not True


@pytest.mark.parametrize("roundtrip", [False, True], ids=["native", "plcopen_rt"])
def test_forward_reverse_gates(roundtrip):
    prog = apply_aoi_template(empty_program(), "ForwardReverse")
    if roundtrip:
        prog = _rt(prog)
    sim = _sim(prog)
    r = sim.scan_once({"PB_Fwd": False, "PB_Rev": False, "PB_Stop": False})
    assert not r["vars"].get("M_Fwd") and not r["vars"].get("M_Rev")
    sim.scan_once({"PB_Fwd": True, "PB_Rev": False, "PB_Stop": False})
    r = sim.scan_once({"PB_Fwd": False, "PB_Rev": False, "PB_Stop": False})
    assert r["vars"].get("M_Fwd") is True and not r["vars"].get("M_Rev")
    # opposite blocked while FWD sealed
    r = sim.scan_once({"PB_Fwd": False, "PB_Rev": True, "PB_Stop": False})
    assert r["vars"].get("M_Fwd") is True and not r["vars"].get("M_Rev")
    assert sim.scan_once({"PB_Stop": True})["vars"].get("M_Fwd") is not True


@pytest.mark.parametrize("roundtrip", [False, True], ids=["native", "plcopen_rt"])
def test_estop_interlock_gates(roundtrip):
    prog = apply_aoi_template(empty_program(), "EstopInterlock")
    if roundtrip:
        prog = _rt(prog)
    sim = _sim(prog)
    assert sim.scan_once({"PB_Start": False, "ES1": False, "Light_Curtain": False})["vars"].get("Machine_Run") is not True
    sim.scan_once({"PB_Start": True, "ES1": False, "Light_Curtain": False})
    assert sim.scan_once({"PB_Start": False, "ES1": False, "Light_Curtain": False})["vars"].get("Machine_Run") is True
    assert sim.scan_once({"PB_Start": False, "ES1": False, "Light_Curtain": True})["vars"].get("Machine_Run") is not True
    sim.scan_once({"PB_Start": True, "ES1": False, "Light_Curtain": False})
    sim.scan_once({"PB_Start": False, "ES1": False, "Light_Curtain": False})
    assert sim.scan_once({"ES1": True, "Light_Curtain": False})["vars"].get("Machine_Run") is not True
    assert sim.scan_once({"PB_Start": True, "ES1": True, "Light_Curtain": False})["vars"].get("Machine_Run") is not True


@pytest.mark.parametrize("roundtrip", [False, True], ids=["native", "plcopen_rt"])
def test_valve_cycle_gates(roundtrip):
    prog = apply_aoi_template(empty_program(), "ValveCycle")
    if roundtrip:
        prog = _rt(prog)
    sim = _sim(prog)
    r = sim.scan_once({"PB_Start": False, "PB_Stop": False, "ES1": False, "Arm_Deployed": False})
    assert not r["vars"].get("Place_Relay") and not r["vars"].get("Welder_Relay")
    sim.scan_once({"PB_Start": True, "PB_Stop": False, "ES1": False, "Arm_Deployed": False})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False, "ES1": False, "Arm_Deployed": True})["vars"].get("Place_Relay") is True
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False, "ES1": False, "Arm_Deployed": True})["vars"].get("Welder_Relay") is True
    r = sim.scan_once({"PB_Start": False, "PB_Stop": False, "ES1": True, "Arm_Deployed": True})
    assert not r["vars"].get("Place_Relay") and not r["vars"].get("Welder_Relay")


@pytest.mark.parametrize("roundtrip", [False, True], ids=["native", "plcopen_rt"])
def test_two_hand_start_gates(roundtrip):
    prog = apply_aoi_template(empty_program(), "TwoHandStart")
    if roundtrip:
        prog = _rt(prog)
    sim = _sim(prog)
    assert sim.scan_once({"PB_Left": True, "PB_Right": False, "PB_Stop": False})["vars"].get("Cycle_Run") is not True
    assert sim.scan_once({"PB_Left": False, "PB_Right": True, "PB_Stop": False})["vars"].get("Cycle_Run") is not True
    # skew: left alone > 0.5 s then right
    for _ in range(60):
        sim.scan_once({"PB_Left": True, "PB_Right": False, "PB_Stop": False})
    assert sim.scan_once({"PB_Left": True, "PB_Right": True, "PB_Stop": False})["vars"].get("Cycle_Run") is not True
    # release both, then concurrent
    sim.scan_once({"PB_Left": False, "PB_Right": False, "PB_Stop": False})
    sim.scan_once({"PB_Left": False, "PB_Right": False, "PB_Stop": False})
    assert sim.scan_once({"PB_Left": True, "PB_Right": True, "PB_Stop": False})["vars"].get("Cycle_Run") is True
    assert sim.scan_once({"PB_Left": True, "PB_Right": True, "PB_Stop": True})["vars"].get("Cycle_Run") is not True


@pytest.mark.parametrize("roundtrip", [False, True], ids=["native", "plcopen_rt"])
def test_off_delay_stop_gates(roundtrip):
    prog = apply_aoi_template(empty_program(), "OffDelayStop")
    if roundtrip:
        prog = _rt(prog)
    sim = _sim(prog)
    assert sim.scan_once({"Auto_Run": False})["vars"].get("Fan1") is not True
    sim.scan_once({"Auto_Run": True})
    assert sim.scan_once({"Auto_Run": True})["vars"].get("Fan1") is True
    off_at = None
    for i in range(50):
        r = sim.scan_once({"Auto_Run": False})
        if not r["vars"].get("Fan1"):
            off_at = i
            break
    assert off_at is not None
    assert 25 <= off_at <= 45  # PT 3000 ms @ 100 ms cycle ≈ 30 scans
    assert sim.scan_once({"Auto_Run": False})["vars"].get("Fan1") is not True


@pytest.mark.parametrize("roundtrip", [False, True], ids=["native", "plcopen_rt"])
def test_jog_or_run_gates(roundtrip):
    prog = apply_aoi_template(empty_program(), "JogOrRun")
    if roundtrip:
        prog = _rt(prog)
    sim = _sim(prog)
    assert sim.scan_once({"PB_Jog": False, "PB_Start": False, "PB_Stop": False})["vars"].get("M1") is not True
    sim.scan_once({"PB_Jog": True, "PB_Stop": False, "PB_Start": False})
    assert sim.scan_once({"PB_Jog": True, "PB_Stop": False})["vars"].get("M1") is True
    assert sim.scan_once({"PB_Jog": False, "PB_Stop": False})["vars"].get("M1") is not True
    assert sim.scan_once({"PB_Jog": True, "PB_Stop": True})["vars"].get("M1") is not True
    sim.scan_once({"PB_Start": True, "PB_Stop": False, "PB_Jog": False})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False})["vars"].get("M1") is True
    assert sim.scan_once({"PB_Stop": True})["vars"].get("M1") is not True


def test_seal_in_plcopen_does_not_collapse_stop_into_seal_or():
    """P1-8: after RT, Stop must remain series — not START|RUN|/STOP|/STOP."""
    prog = apply_aoi_template(empty_program(), "MotorStarter")
    back = _rt(prog)
    from cabinet_studio.services.ladder_ir import program_rung_to_elements

    els = program_rung_to_elements(back["rungs"][0])
    kinds = [e.get("kind") for e in els]
    assert kinds.count("or") == 1  # only the start|seal OR
    assert any(e.get("kind") == "contact" and e.get("var") == "PB_Stop" and e.get("form") == "NC" for e in els)
    # No OR whose branches are only STOP NC duplicates as the sole series logic
    for e in els:
        if e.get("kind") != "or":
            continue
        flat = []
        for br in e.get("branches") or []:
            for c in br:
                flat.append((c.get("var"), c.get("form")))
        assert flat != [("PB_Stop", "NC"), ("PB_Stop", "NC")]
