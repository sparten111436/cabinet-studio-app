"""CTU / CTD / RES / LOAD counters: program dict, IR, scan sim, text, PLCopen (v0.3.3)."""

from __future__ import annotations

import pytest

from cabinet_studio.services.ladder_ir import (
    collect_tags,
    ladder_ir_to_program,
    normalize_ladder_ir,
    program_to_ladder_ir,
)
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.plcopen_xml import (
    import_plcopen_xml_to_program,
    ladder_ir_to_plcopen_xml,
    plcopen_xml_to_ladder_ir,
)
from cabinet_studio.services.programming import (
    add_counter_rung,
    add_rung,
    edit_rung,
    empty_program,
    format_ladder_txt,
    format_plc_text,
    program_from_dict,
    program_to_dict,
)


def _ctu_program(pre: int = 3):
    prog = add_counter_rung(
        empty_program(),
        contact_tag="PE_Part",
        counter_tag="C1",
        block="CTU",
        pv=pre,
        comment="Count parts",
    )
    prog = add_counter_rung(prog, contact_tag="PB_Reset", counter_tag="C1", block="RES")
    prog = add_rung(prog, contact_tag="C1.DN", coil_tag="Batch_Lamp", comment="Batch done")
    return prog


def _ctd_program(pre: int = 2):
    prog = add_counter_rung(empty_program(), contact_tag="PB_Load", counter_tag="C2", block="LOAD", pv=pre)
    prog = add_counter_rung(prog, contact_tag="PE_Out", counter_tag="C2", block="CTD", pv=pre)
    prog = add_rung(prog, contact_tag="C2", coil_tag="Empty_Lamp")
    return prog


def _pulse(sim: ScanSimulator, tag: str) -> dict:
    sim.scan_once({tag: True})
    return sim.scan_once({tag: False})


def test_program_dict_preserves_counter():
    data = program_to_dict(_ctu_program(7))
    assert data["rungs"][0]["counter"] == {"tag": "C1", "block": "CTU", "pv": 7}
    assert data["rungs"][1]["counter"]["block"] == "RES"
    back = program_from_dict(data)
    assert back["rungs"][0]["counter"]["pv"] == 7
    # edit_rung can drop / replace the counter
    cleared = edit_rung(back, back["rungs"][0]["id"], counter=None)
    assert "counter" not in cleared["rungs"][0]
    swapped = edit_rung(back, back["rungs"][0]["id"], counter={"tag": "C9", "block": "CTD", "pv": 4})
    assert swapped["rungs"][0]["counter"] == {"tag": "C9", "block": "CTD", "pv": 4}


def test_ir_round_trip_keeps_counter_and_vars():
    ir = program_to_ladder_ir(_ctu_program(5), project_name="CountDemo")
    ctr = next(e for e in ir["rungs"][0]["elements"] if e["kind"] == "counter")
    assert ctr == {"kind": "counter", "var": "C1", "block": "CTU", "pv": 5}
    by_name = {v["name"]: v for v in ir["variables"]}
    assert by_name["C1"]["class"] == "counter"
    assert by_name["C1"]["type"] == "CTU"
    assert by_name["C1"]["pv"] == 5
    assert "C1.DN" not in by_name  # member read is not a separate input variable
    inputs, outputs, _all = collect_tags(ir)
    assert "C1.DN" not in inputs
    assert {"PE_Part", "PB_Reset"} <= inputs
    assert "C1" in outputs
    back = ladder_ir_to_program(normalize_ladder_ir(ir))
    assert back["rungs"][0]["counter"] == {"tag": "C1", "block": "CTU", "pv": 5}
    assert back["rungs"][1]["counter"]["block"] == "RES"


def test_ctu_counts_rising_edges_and_dn():
    sim = ScanSimulator(program_to_ladder_ir(_ctu_program(3)), cycle_ms=50)
    r = sim.scan_once({"PE_Part": True})
    assert r["counters"]["C1"]["acc"] == 1
    assert r["counters"]["C1"]["cu"] is True
    # Held input does not count again (edge only)
    r = sim.scan_once()
    assert r["counters"]["C1"]["acc"] == 1
    r = sim.scan_once({"PE_Part": False})
    assert r["counters"]["C1"]["cu"] is False
    _pulse(sim, "PE_Part")
    assert sim.counters["C1"]["acc"] == 2
    assert sim.counters["C1"]["dn"] is False
    assert sim.read("Batch_Lamp") is False
    r = _pulse(sim, "PE_Part")
    assert r["counters"]["C1"]["acc"] == 3
    assert r["counters"]["C1"]["dn"] is True
    assert sim.read("C1") is True and sim.read("C1.DN") is True
    assert r["vars"]["Batch_Lamp"] is True
    # Keeps counting past PRE (CCW CV / Rockwell ACC)
    _pulse(sim, "PE_Part")
    assert sim.counters["C1"]["acc"] == 4
    assert sim.counters["C1"]["dn"] is True


def test_res_zeros_acc_without_double_count():
    sim = ScanSimulator(program_to_ladder_ir(_ctu_program(2)), cycle_ms=50)
    sim.scan_once({"PE_Part": True})  # ACC 1, CU held
    r = sim.scan_once({"PB_Reset": True})
    assert r["counters"]["C1"]["acc"] == 0
    assert r["counters"]["C1"]["dn"] is False
    r = sim.scan_once({"PB_Reset": False})
    # PE_Part still held: no new rising edge -> stays 0
    assert r["counters"]["C1"]["acc"] == 0
    sim.scan_once({"PE_Part": False})
    r = _pulse(sim, "PE_Part")
    assert r["counters"]["C1"]["acc"] == 1


def test_ctd_load_count_down_dn_at_zero():
    sim = ScanSimulator(program_to_ladder_ir(_ctd_program(2)), cycle_ms=50)
    # Before LOAD, ACC=0 so CTD DN (ACC<=0) is true — same as CCW CTD Q at CV=0.
    assert sim.counters["C2"]["block"] == "CTD"
    assert sim.counters["C2"]["dn"] is True
    r = _pulse(sim, "PB_Load")
    assert r["counters"]["C2"]["acc"] == 2
    assert r["counters"]["C2"]["dn"] is False
    assert r["vars"]["Empty_Lamp"] is False
    r = _pulse(sim, "PE_Out")
    assert r["counters"]["C2"]["acc"] == 1
    assert r["counters"]["C2"]["cd"] is False
    r = _pulse(sim, "PE_Out")
    assert r["counters"]["C2"]["acc"] == 0
    assert r["counters"]["C2"]["dn"] is True
    assert r["vars"]["Empty_Lamp"] is True
    r = _pulse(sim, "PE_Out")
    assert r["counters"]["C2"]["acc"] == -1  # keeps counting down like CCW CV


def test_counter_clamps_and_sets_ov():
    sim = ScanSimulator(program_to_ladder_ir(_ctu_program(5)), cycle_ms=50)
    sim.counters["C1"]["acc"] = 32767
    r = _pulse(sim, "PE_Part")
    assert r["counters"]["C1"]["acc"] == 32767
    assert r["counters"]["C1"]["ov"] is True
    assert sim.read("C1.OV") is True
    sim.scan_once({"PB_Reset": True})
    assert sim.counters["C1"]["ov"] is False


def test_sim_reset_clears_counters():
    sim = ScanSimulator(program_to_ladder_ir(_ctu_program(1)), cycle_ms=50)
    _pulse(sim, "PE_Part")
    assert sim.counters["C1"]["dn"] is True
    sim.reset()
    assert sim.counters["C1"]["acc"] == 0
    assert sim.counters["C1"]["dn"] is False
    assert sim.counters["C1"]["pre"] == 1


def test_plc_text_and_ladder_txt_show_counters():
    prog = _ctu_program(4)
    text = format_plc_text(prog["rungs"])
    assert "CTU[C1/PRE=4]" in text
    assert "(RES C1)" in text
    assert "DN when ACC>=PRE" in text
    txt = format_ladder_txt(prog, cabinet_name="Demo")
    assert ("COUNTER:" in txt or "CTU" in txt) and ("CTU[C1/PRE=4]" in txt or "CTU C1" in txt)


def test_plcopen_counter_round_trip():
    prog = _ctu_program(6)
    prog = add_counter_rung(prog, contact_tag="PE_Out", counter_tag="C2", block="CTD", pv=9)
    ir = program_to_ladder_ir(prog, project_name="CountCab")
    xml = ladder_ir_to_plcopen_xml(ir)
    assert 'typeName="CTU"' in xml and 'instanceName="C1"' in xml
    assert 'typeName="CTD"' in xml and 'instanceName="C2"' in xml
    assert 'formalParameter="CU"' in xml and 'formalParameter="RESET"' in xml
    assert 'formalParameter="CD"' in xml and 'formalParameter="LOAD"' in xml
    assert 'formalParameter="PV"' in xml and 'formalParameter="CV"' in xml
    assert 'typeName="RES"' in xml
    assert ("variable=\"C1.Q\"" in xml or ">C1.Q</variable>" in xml)  # attr (legacy) or child (TC6)
    assert '<derived name="CTU"/>' in xml
    back = plcopen_xml_to_ladder_ir(xml)
    counters = [e for r in back["rungs"] for e in r["elements"] if e.get("kind") == "counter"]
    assert {"kind": "counter", "var": "C1", "block": "CTU", "pv": 6} in counters
    assert {"kind": "counter", "var": "C2", "block": "CTD", "pv": 9} in counters
    assert any(c["block"] == "RES" and c["var"] == "C1" for c in counters)
    contacts = [e["var"] for r in back["rungs"] for e in r["elements"] if e.get("kind") == "contact"]
    assert "C1.DN" in contacts
    by_name = {v["name"]: v for v in back["variables"]}
    assert by_name["C1"]["class"] == "counter" and by_name["C1"]["pv"] == 6
    assert by_name["C2"]["type"] == "CTD"
    # Program-level import keeps counter rungs and coils
    program = import_plcopen_xml_to_program(xml)
    blocks = [r.get("counter", {}).get("block") for r in program["rungs"]]
    assert blocks[:2] == ["CTU", "RES"]
    assert any(r["coil_tag"] == "Batch_Lamp" for r in program["rungs"])
    # Imported program simulates the same as the original
    sim = ScanSimulator(plcopen_xml_to_ladder_ir(xml), cycle_ms=50)
    for _ in range(6):
        _pulse(sim, "PE_Part")
    assert sim.read("Batch_Lamp") is True


def test_plcopen_import_ctud_and_load_blocks():
    prog = _ctd_program(3)
    xml = ladder_ir_to_plcopen_xml(program_to_ladder_ir(prog))
    assert 'typeName="LOAD"' in xml
    back = plcopen_xml_to_ladder_ir(xml)
    counters = [e for r in back["rungs"] for e in r["elements"] if e.get("kind") == "counter"]
    assert counters[0]["block"] == "LOAD" and counters[0]["pv"] == 3
    # v0.3.19 (TC6 allowlist): a foreign CTUD up/down counter used to import as a plain CTU,
    # silently dropping its count-down input. Cabinet Studio never exports CTUD; refuse it.
    xml2 = xml.replace('typeName="CTD"', 'typeName="CTUD"')
    with pytest.raises(ValueError, match="CTUD"):
        plcopen_xml_to_ladder_ir(xml2)


def test_timer_members_readable():
    from cabinet_studio.services.programming import add_timer_rung

    prog = add_timer_rung(empty_program(), contact_tag="PB_Start", timer_tag="T1", block="TON", pt_ms=100)
    prog = add_rung(prog, contact_tag="T1.DN", coil_tag="CR1")
    sim = ScanSimulator(program_to_ladder_ir(prog), cycle_ms=50)
    assert "T1.DN" not in sim.input_tags()
    sim.scan_once({"PB_Start": True})
    assert sim.read("T1.TT") is True and sim.read("T1.EN") is True
    r = sim.scan_once()
    r = sim.scan_once()
    assert sim.read("T1.DN") is True
    assert r["vars"]["CR1"] is True
