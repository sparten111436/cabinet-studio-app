"""v0.3.12: G-AID on all surfaces, pure-XML TwoHandStart, JogOrRun non-retentive."""
from __future__ import annotations

import re

import pytest

from cabinet_studio import __version__
from cabinet_studio.services.ladder_ir import program_rung_to_elements
from cabinet_studio.services.ladder_print import ladder_program_to_svg_pages
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import (
    AOI_TEMPLATES,
    SAFETY_DESIGN_AID_NOTE,
    SAFETY_TEMPLATE_NAMES,
    apply_aoi_template,
    expand_aoi_template,
)
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import (
    empty_program,
    format_ladder_txt,
    format_plc_text,
    program_from_dict,
)

CYCLE = 100
AID_NEEDLES = ("Educational design aid only", "NFPA 79", "ISO 13849", "hardwired")


def _assert_aid(text: str, surface: str) -> None:
    low = (text or "").lower()
    for needle in AID_NEEDLES:
        assert needle.lower() in low, f"{surface} missing {needle!r}"


def _rt(prog: dict) -> dict:
    return program_from_dict(import_plcopen_xml_to_program(export_program_to_plcopen_xml(prog)))


def _strip_embed(xml: str) -> str:
    """Remove Cabinet Studio sidecar payload so import must use pure LD graph."""
    return re.sub(r"cabinet-studio-elements:[^<]*", "", xml or "")


def _graph_only(prog: dict) -> dict:
    xml = export_program_to_plcopen_xml(prog, project_name="QA")
    return program_from_dict(import_plcopen_xml_to_program(_strip_embed(xml)))


def test_version_is_0312():
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 12)  # strict: parsed, not a prefix match


@pytest.mark.parametrize("name", sorted(SAFETY_TEMPLATE_NAMES))
def test_g_aid_all_surfaces(name):
    """G-AID must appear on rung comments, print SVG, PLCopen, ladder txt, plc_text."""
    assert name in AOI_TEMPLATES
    prog = apply_aoi_template(empty_program(), name)
    first_comment = str((prog.get("rungs") or [{}])[0].get("comment") or "")
    _assert_aid(first_comment, f"{name} first rung comment")
    _assert_aid(str(AOI_TEMPLATES[name].get("description") or ""), f"{name} description")

    xml = export_program_to_plcopen_xml(prog, project_name="QA")
    _assert_aid(xml, f"{name} PLCopen XML")
    # v0.3.13: UL design-aid line must also appear in PLCopen documentation
    assert "NOT A CERTIFIED UL 508A DRAWING" in xml

    pages = ladder_program_to_svg_pages(prog["rungs"], width=1000, project_name="QA")
    svg = "\n".join(pg[0] for pg in pages)
    _assert_aid(svg, f"{name} print SVG")
    assert "NOT A CERTIFIED UL 508A DRAWING" in svg

    _assert_aid(format_ladder_txt(prog, cabinet_name="QA"), f"{name} ladder txt")
    _assert_aid(format_plc_text(prog["rungs"]), f"{name} plc_text")


def test_twohand_pure_xml_no_one_hand_start():
    """Strip embedded rung copy — TwoHandStart must still refuse one-hand start."""
    prog = apply_aoi_template(empty_program(), "TwoHandStart")
    g = _graph_only(prog)
    # Cycle rung must keep series contacts inside the start OR branch
    cycle = None
    for r in g["rungs"]:
        els = program_rung_to_elements(r)
        if any(e.get("kind") == "coil" and e.get("var") == "Cycle_Run" for e in els):
            cycle = els
            break
    assert cycle is not None
    ors = [e for e in cycle if e.get("kind") == "or"]
    assert len(ors) == 1
    branches = ors[0]["branches"]
    assert len(branches) == 2
    # One branch is the seal (Cycle alone); the other has Left+Right(+locks)
    lens = sorted(len(b) for b in branches)
    assert lens == [1, 4], f"expected seal+series branch, got {branches!r}"
    assert any(e.get("var") == "PB_Stop" and e.get("form") == "NC" for e in cycle)

    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    for _ in range(5):
        r = sim.scan_once({"PB_Left": True, "PB_Right": False, "PB_Stop": False})
    assert r["vars"].get("Cycle_Run") is not True
    for _ in range(5):
        r = sim.scan_once({"PB_Left": False, "PB_Right": True, "PB_Stop": False})
    assert r["vars"].get("Cycle_Run") is not True
    # Concurrent still starts
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    sim.scan_once({"PB_Left": False, "PB_Right": False, "PB_Stop": False})
    assert sim.scan_once({"PB_Left": True, "PB_Right": True, "PB_Stop": False})["vars"].get("Cycle_Run") is True


@pytest.mark.parametrize("name", sorted(SAFETY_TEMPLATE_NAMES))
def test_safety_templates_still_safe_after_graph_only_rt(name):
    """Graph-only RT must not self-start at power-up for any safety template."""
    prog = apply_aoi_template(empty_program(), name)
    g = _graph_only(prog)
    # Must actually import rungs — empty program would vacuously pass power-up checks.
    assert len(g.get("rungs") or []) >= 1, f"{name} graph-only import dropped every rung"
    assert len(g["rungs"]) == len(prog.get("rungs") or []), (
        f"{name} rung count {len(g.get('rungs') or [])} != native {len(prog.get('rungs') or [])}"
    )
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    idle = {
        "PB_Start": False, "PB_Stop": False, "PB_Jog": False,
        "PB_Fwd": False, "PB_Rev": False, "PB_Left": False, "PB_Right": False,
        "ES1": False, "Light_Curtain": False, "Arm_Deployed": False, "Auto_Run": False,
    }
    r = sim.scan_once(idle)
    for tag in ("M1", "M_Fwd", "M_Rev", "Machine_Run", "Place_Relay", "Welder_Relay", "Cycle_Run", "Fan1", "RunMode"):
        assert r["vars"].get(tag) is not True, f"{name} graph-only power-up {tag}=ON"


def test_jog_or_run_ote_non_retentive_power_cycle():
    """RunMode OTE seal must clear across a fresh simulator (power-loss model)."""
    from cabinet_studio.services.ladder_ir import _coil_el, _contact_el
    from cabinet_studio.services.programming import add_rung_from_elements

    specs = expand_aoi_template("JogOrRun")
    assert len(specs) == 2
    # No OTL/OTU on RunMode — structural gate (OTE seal, not latched)
    for s in specs:
        for e in s["elements"]:
            if e.get("kind") == "coil" and e.get("var") == "RunMode":
                form = str(e.get("form") or "normal").lower()
                assert form in {"normal", ""}, f"RunMode must be OTE not {form!r}"
                assert form not in {"set", "reset", "otl", "otu"}

    prog = apply_aoi_template(empty_program(), "JogOrRun")
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    sim.scan_once({"PB_Start": True, "PB_Stop": False, "PB_Jog": False})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False, "PB_Jog": False})["vars"].get("M1") is True
    assert sim.vars.get("RunMode") is True

    # Power cycle: brand-new scan memory — OTE seal must be off
    sim2 = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    r = sim2.scan_once({"PB_Start": False, "PB_Stop": False, "PB_Jog": False})
    assert r["vars"].get("RunMode") is not True
    assert r["vars"].get("M1") is not True

    # Structural: JogOrRun must not use OTL/OTU on RunMode (old latched design).
    jog_els = []
    for rr in prog["rungs"]:
        jog_els.extend(program_rung_to_elements(rr))
    assert not any(
        e.get("kind") == "coil"
        and e.get("var") == "RunMode"
        and str(e.get("form") or "").lower() in {"set", "reset"}
        for e in jog_els
    ), "JogOrRun RunMode must be OTE seal, not OTL/OTU"
    # Contrast fixture: OTL RunMode stays True on a fresh sim if BOOL memory is retained
    latched = add_rung_from_elements(
        empty_program(),
        [
            _contact_el("PB_Start"),
            _coil_el("RunMode", form="set"),
        ],
        comment="legacy OTL (must NOT match JogOrRun)",
    )
    sim_l = ScanSimulator.from_program(latched, cycle_ms=CYCLE)
    sim_l.scan_once({"PB_Start": True})
    assert sim_l.vars.get("RunMode") is True
    sim_l2 = ScanSimulator.from_program(latched, cycle_ms=CYCLE)
    sim_l2.vars["RunMode"] = True  # retained OTL memory across "power loss"
    assert sim_l2.scan_once({"PB_Start": False})["vars"].get("RunMode") is True
    # OTE JogOrRun: truly fresh simulator (empty memory) is off — already asserted above.
    # Seeding RunMode on an OTE seal would re-seal (by design); that is not the power-cycle model.

    # Jog still momentary after power cycle
    sim2.scan_once({"PB_Jog": True, "PB_Stop": False, "PB_Start": False})
    assert sim2.scan_once({"PB_Jog": True, "PB_Stop": False})["vars"].get("M1") is True
    assert sim2.scan_once({"PB_Jog": False, "PB_Stop": False})["vars"].get("M1") is not True


def test_jog_or_run_logic_gates_still_hold():
    prog = apply_aoi_template(empty_program(), "JogOrRun")
    for roundtrip in (False, True):
        p = _rt(prog) if roundtrip else prog
        sim = ScanSimulator.from_program(p, cycle_ms=CYCLE)
        assert sim.scan_once({"PB_Jog": False, "PB_Start": False, "PB_Stop": False})["vars"].get("M1") is not True
        sim.scan_once({"PB_Jog": True, "PB_Stop": False, "PB_Start": False})
        assert sim.scan_once({"PB_Jog": True, "PB_Stop": False})["vars"].get("M1") is True
        assert sim.scan_once({"PB_Jog": False, "PB_Stop": False})["vars"].get("M1") is not True
        assert sim.scan_once({"PB_Jog": True, "PB_Stop": True})["vars"].get("M1") is not True
        sim.scan_once({"PB_Start": True, "PB_Stop": False, "PB_Jog": False})
        assert sim.scan_once({"PB_Start": False, "PB_Stop": False})["vars"].get("M1") is True
        assert sim.scan_once({"PB_Stop": True})["vars"].get("M1") is not True


def test_motor_starter_graph_only_stop_still_series():
    prog = apply_aoi_template(empty_program(), "MotorStarter")
    g = _graph_only(prog)
    els = program_rung_to_elements(g["rungs"][0])
    assert any(e.get("kind") == "contact" and e.get("var") == "PB_Stop" and e.get("form") == "NC" for e in els)
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False})["vars"].get("M1") is not True
    sim.scan_once({"PB_Start": True, "PB_Stop": False})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False})["vars"].get("M1") is True
    assert sim.scan_once({"PB_Stop": True})["vars"].get("M1") is not True


def test_reg1_add_series_contact_on_motor_starter_elements():
    """REG-1: edit_rung(series=…) must update stored elements (UI Add series path)."""
    from cabinet_studio.services.programming import edit_rung, format_plc_text

    prog = apply_aoi_template(empty_program(), "MotorStarter")
    rid = prog["rungs"][0]["id"]
    series = list(prog["rungs"][0].get("series") or [])
    series.append({"tag": "GUARD", "normally_closed": False})
    prog = edit_rung(prog, rid, series=series)
    els = program_rung_to_elements(prog["rungs"][0])
    assert any(e.get("kind") == "contact" and e.get("var") == "GUARD" for e in els)
    assert "GUARD" in format_plc_text(prog["rungs"])
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    # GUARD=0 blocks start
    sim.scan_once({"PB_Start": True, "PB_Stop": False, "GUARD": False})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False, "GUARD": False})["vars"].get("M1") is not True
    # GUARD=1 allows seal
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    sim.scan_once({"PB_Start": True, "PB_Stop": False, "GUARD": True})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False, "GUARD": True})["vars"].get("M1") is True


def test_new_b_twohand_two_instances_independent_skew():
    """NEW-B: two TwoHandStart instances must not share skew timers/locks."""
    p = apply_aoi_template(empty_program(), "TwoHandStart", {
        "left": "L1", "right": "R1", "stop": "S1", "cycle": "PRESS1", "skew_ms": "500",
    })
    p = apply_aoi_template(p, "TwoHandStart", {
        "left": "L2", "right": "R2", "stop": "S2", "cycle": "PRESS2", "skew_ms": "500",
    })
    comments = " ".join(r.get("comment") or "" for r in p["rungs"])
    assert "PRESS1_T_LeftSkew" in str(p) or "PRESS1_LeftLock" in str(
        [[e for e in program_rung_to_elements(r)] for r in p["rungs"]]
    )
    # Hold L1 alone past skew, then R1 — must NOT start (lock engaged)
    sim = ScanSimulator.from_program(p, cycle_ms=CYCLE)
    for _ in range(10):
        sim.scan_once({"L1": True, "R1": False, "S1": False, "L2": False, "R2": False, "S2": False})
    r = sim.scan_once({"L1": True, "R1": True, "S1": False, "L2": False, "R2": False, "S2": False})
    assert r["vars"].get("PRESS1") is not True
    # Instance 2 still works with concurrent hands
    sim = ScanSimulator.from_program(p, cycle_ms=CYCLE)
    sim.scan_once({"L1": False, "R1": False, "S1": False, "L2": False, "R2": False, "S2": False})
    r = sim.scan_once({"L1": False, "R1": False, "S1": False, "L2": True, "R2": True, "S2": False})
    assert r["vars"].get("PRESS2") is True


def test_p1_1_series_or_pure_xml_no_rewire():
    """P1-1: (X1·X2)|X3 must survive hint-stripped PLCopen import."""
    from cabinet_studio.services.programming import add_rung_from_elements
    from cabinet_studio.services.ladder_ir import _contact_el, _coil_el

    els = [
        {
            "kind": "or",
            "branches": [
                [_contact_el("X1"), _contact_el("X2")],
                [_contact_el("X3")],
            ],
        },
        _coil_el("Y"),
    ]
    prog = add_rung_from_elements(empty_program(), els, comment="series-or")
    g = _graph_only(prog)
    back = program_rung_to_elements(g["rungs"][0])
    ors = [e for e in back if e.get("kind") == "or"]
    assert len(ors) == 1
    branches = ors[0]["branches"]
    lens = sorted(len(b) for b in branches)
    assert lens == [1, 2], f"rewired to {branches!r}"
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    # X3 alone → Y
    assert sim.scan_once({"X1": False, "X2": False, "X3": True})["vars"].get("Y") is True
    # X1 alone → not Y
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": True, "X2": False, "X3": False})["vars"].get("Y") is not True
    # X1·X2 → Y
    assert sim.scan_once({"X1": True, "X2": True, "X3": False})["vars"].get("Y") is True


def test_p1_6_ui_math_div_is_dint():
    """P1-6: UI add_math_rung DIV 7/2 → 3 (DINT), not 3.5."""
    from cabinet_studio.services.programming import add_math_rung

    prog = add_math_rung(
        empty_program(),
        contact_tag="EN",
        op="DIV",
        dest="Q",
        source_a="7",
        source_b="2",
    )
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    r = sim.scan_once({"EN": True})
    assert r["numbers"].get("Q") == 3.0
    prog2 = add_math_rung(
        empty_program(),
        contact_tag="EN",
        op="MOV",
        dest="D",
        source_a="3.7",
    )
    sim2 = ScanSimulator.from_program(prog2, cycle_ms=CYCLE)
    assert sim2.scan_once({"EN": True})["numbers"].get("D") == 4.0


def test_viewer_add_series_uses_append_helper():
    """Viewer Add series must call append_series_contact (REG-2), not empty legacy series."""
    from pathlib import Path as _P
    from cabinet_studio.ui import programming_viewer as pv

    src = _P(pv.__file__).read_text(encoding="utf-8")
    assert "def _add_series_contact" in src
    assert "append_series_contact" in src
    assert "Add series contact" in src
    # Must not rebuild solely from target.get("series") without elements fallback
    assert "series_contacts_from_rung" in src or "append_series_contact(" in src
