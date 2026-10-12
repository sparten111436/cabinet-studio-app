"""v0.3.6 one-shots: ONS / OSR / OSF — IR, scan sim, print, PLCopen, text."""

from __future__ import annotations

import pytest

from cabinet_studio.services.ladder_ir import (
    IR_FORMAT,
    clean_elements,
    ladder_ir_to_program,
    normalize_ladder_ir,
    program_to_ladder_ir,
)
from cabinet_studio.services.ladder_print import ladder_program_to_svg
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
    ladder_ir_to_plcopen_xml,
    plcopen_xml_to_ladder_ir,
)
from cabinet_studio.services.programming import add_oneshot_rung, empty_program, format_plc_text


def _ir(elements):
    return {"format": IR_FORMAT, "version": 1, "rungs": [{"id": "r1", "elements": elements}]}


def _ons_ladder():
    return _ir([
        {"kind": "contact", "var": "PB_Cycle", "form": "NO"},
        {"kind": "oneshot", "block": "ONS", "var": "OS1"},
        {"kind": "coil", "var": "Cycle_Pulse", "form": "normal"},
    ])


def test_ons_true_for_exactly_one_scan_per_press():
    sim = ScanSimulator(_ons_ladder())
    sim.set_force("PB_Cycle", True)
    seen = [sim.scan_once()["vars"]["Cycle_Pulse"] for _ in range(4)]
    assert seen == [True, False, False, False]
    sim.set_force("PB_Cycle", False)
    assert sim.scan_once()["vars"]["Cycle_Pulse"] is False
    sim.set_force("PB_Cycle", True)
    assert sim.scan_once()["vars"]["Cycle_Pulse"] is True
    assert sim.scan_once()["vars"]["Cycle_Pulse"] is False


def test_ons_can_feed_a_counter_one_count_per_press():
    ladder = _ir([
        {"kind": "contact", "var": "PB_Cycle", "form": "NO"},
        {"kind": "oneshot", "block": "ONS", "var": "OS1"},
        {"kind": "counter", "var": "C1", "block": "CTU", "pv": 3},
    ])
    sim = ScanSimulator(ladder)
    for _press in range(3):
        sim.set_force("PB_Cycle", True)
        for _ in range(3):
            sim.scan_once()
        sim.set_force("PB_Cycle", False)
        sim.scan_once()
    assert sim.counters["C1"]["acc"] == 3
    assert sim.read("C1.DN") is True


def test_osr_pulses_output_bit_and_passes_power():
    ladder = _ir([
        {"kind": "contact", "var": "PB", "form": "NO"},
        {"kind": "oneshot", "block": "OSR", "var": "OS2", "output": "Start_Pulse"},
        {"kind": "coil", "var": "Held_Lamp", "form": "normal"},
    ])
    sim = ScanSimulator(ladder)
    sim.set_force("PB", True)
    r1 = sim.scan_once()
    r2 = sim.scan_once()
    assert r1["vars"]["Start_Pulse"] is True and r2["vars"]["Start_Pulse"] is False
    assert r1["vars"]["Held_Lamp"] is True and r2["vars"]["Held_Lamp"] is True  # passthrough
    sim.set_force("PB", False)
    assert sim.scan_once()["vars"]["Start_Pulse"] is False


def test_osf_pulses_on_falling_edge_only():
    ladder = _ir([
        {"kind": "contact", "var": "PB", "form": "NO"},
        {"kind": "oneshot", "block": "OSF", "var": "OS3", "output": "Release_Pulse"},
    ])
    sim = ScanSimulator(ladder)
    sim.set_force("PB", True)
    assert sim.scan_once()["vars"]["Release_Pulse"] is False
    assert sim.scan_once()["vars"]["Release_Pulse"] is False
    sim.set_force("PB", False)
    assert sim.scan_once()["vars"]["Release_Pulse"] is True
    assert sim.scan_once()["vars"]["Release_Pulse"] is False


def test_storage_and_output_bits_are_not_forceable_inputs():
    sim = ScanSimulator(_ir([
        {"kind": "contact", "var": "PB", "form": "NO"},
        {"kind": "oneshot", "block": "OSR", "var": "OS2", "output": "Pulse"},
    ]))
    assert sim.input_tags() == ["PB"]
    assert "OS2" not in sim.input_tags() and "Pulse" not in sim.input_tags()


def test_oneshot_aliases_and_validation():
    els = clean_elements([
        {"kind": "R_TRIG", "var": "a"},
        {"kind": "oneshot", "block": "F_TRIG", "storage": "b", "output": "c"},
        {"kind": "osr", "var": "d", "output": "e"},
        {"kind": "oneshot", "block": "ONS"},  # no storage -> dropped
    ])
    assert [e["block"] for e in els] == ["ONS", "OSF", "OSR"] or [e["block"] for e in els][1:] == ["OSF", "OSR"]
    assert els[1]["var"] == "b" and els[1]["output"] == "c"
    assert len(els) == 3


def test_add_oneshot_rung_program_roundtrip():
    prog = add_oneshot_rung(empty_program(), contact_tag="PB", block="OSR", storage_tag="OS1", output_tag="P1")
    rung = prog["rungs"][-1]
    assert rung["elements"][1] == {"kind": "oneshot", "block": "OSR", "var": "OS1", "output": "P1"}
    back = ladder_ir_to_program(program_to_ladder_ir(prog))
    assert back["rungs"][0]["elements"][1]["output"] == "P1"
    with pytest.raises(ValueError):
        add_oneshot_rung(empty_program(), contact_tag="PB", block="OSF", storage_tag="OS1")
    with pytest.raises(ValueError):
        add_oneshot_rung(empty_program(), contact_tag="PB", block="ONS", storage_tag="")


def test_oneshot_plcopen_roundtrip_uses_iec_trig_blocks():
    prog = add_oneshot_rung(empty_program(), contact_tag="PB", block="ONS", storage_tag="OS1", coil_tag="Out1")
    prog = add_oneshot_rung(prog, contact_tag="PB2", block="OSF", storage_tag="OS2", output_tag="Rel")
    xml = export_program_to_plcopen_xml(prog, project_name="OS demo")
    assert 'typeName="R_TRIG"' in xml and 'typeName="F_TRIG"' in xml
    assert "ONESHOT ONS storage=OS1" in xml
    back = import_plcopen_xml_to_program(xml)
    e0 = back["rungs"][0]["elements"]
    e1 = back["rungs"][1]["elements"]
    assert e0[1] == {"kind": "oneshot", "block": "ONS", "var": "OS1"}
    assert e0[2]["var"] == "Out1"
    assert e1[1] == {"kind": "oneshot", "block": "OSF", "var": "OS2", "output": "Rel"}


def test_foreign_r_trig_without_hint_imports_as_ons():
    ir = normalize_ladder_ir(_ons_ladder())
    xml = ladder_ir_to_plcopen_xml(ir)
    # Strip our lossless hint + ONESHOT doc to mimic a foreign tool export.
    import re

    xml = re.sub(r"<documentation>cabinet-studio-elements:.*?</documentation>", "", xml, flags=re.S)
    xml = re.sub(r"<documentation>ONESHOT[^<]*</documentation>", "", xml)
    back = plcopen_xml_to_ladder_ir(xml)
    kinds = [e["kind"] for e in back["rungs"][0]["elements"]]
    assert "oneshot" in kinds
    os_el = next(e for e in back["rungs"][0]["elements"] if e["kind"] == "oneshot")
    assert os_el["block"] == "ONS" and os_el["var"] == "OS1"


def test_oneshot_print_and_text():
    prog = add_oneshot_rung(empty_program(), contact_tag="PB", block="ONS", storage_tag="OS1", coil_tag="Out1")
    prog = add_oneshot_rung(prog, contact_tag="PB", block="OSR", storage_tag="OS2", output_tag="P2")
    svg, _w, _h = ladder_program_to_svg(prog["rungs"])
    assert ">ONS<" in svg and "OSR (rising)" in svg and "O P2" in svg
    text = format_plc_text(prog["rungs"])
    assert "ONS[OS1]" in text and "OSR[OS2→P2]" in text
