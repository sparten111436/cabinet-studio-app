"""v0.3.7 ladder tools: copy/paste, verify, tag DB + cross-ref, find/replace, reorder."""

from __future__ import annotations

import pytest

from cabinet_studio.services import ladder_tools as lt
from cabinet_studio.services.ladder_ir import program_rung_to_elements
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.plcopen_xml import export_program_to_plcopen_xml, import_plcopen_xml_to_program
from cabinet_studio.services.programming import (
    add_compare_rung,
    add_counter_rung,
    add_latch_rung,
    add_math_rung,
    add_oneshot_rung,
    add_rung,
    add_timer_rung,
    empty_program,
    program_from_dict,
    program_to_dict,
)

DEVICES = [
    {"tag": "PB_Start", "type_id": "pushbutton", "description": "Start pushbutton"},
    {"tag": "PB_Stop", "type_id": "pushbutton", "description": "Stop pushbutton"},
    {"tag": "M1", "type_id": "contactor", "description": "Conveyor motor starter"},
    {"tag": "LT_Run", "type_id": "pilot_light", "description": "Run light"},
]


def _base():
    p = add_rung(empty_program(), contact_tag="PB_Start", coil_tag="M1", comment="Start")
    p = add_timer_rung(p, contact_tag="M1", timer_tag="T1", pt_ms=2000, coil_tag="", comment="delay")
    p = add_rung(p, contact_tag="T1.DN", coil_tag="LT_Run")
    return p


def _ids(p):
    return [r["id"] for r in p["rungs"]]


# --- copy / paste ---------------------------------------------------------


def test_copy_paste_rung_inserts_after_with_fresh_id_and_lossless_elements():
    p = _base()
    first = _ids(p)[0]
    clip = lt.copy_rungs(p, [first])
    text = lt.clip_to_text(clip)
    assert lt.clip_from_text(text)["kind"] == "rungs"
    p2, new_ids = lt.paste_rungs(p, lt.clip_from_text(text), after_id=first)
    assert len(p2["rungs"]) == 4
    assert _ids(p2)[1] == new_ids[0] and new_ids[0] not in _ids(p)
    assert program_rung_to_elements(p2["rungs"][1]) == program_rung_to_elements(p["rungs"][0])
    assert p2["rungs"][1]["comment"] == "Start"
    assert "M1" in p2["plc_text"]


def test_paste_nested_or_oneshot_rung_round_trips_and_simulates():
    p = add_oneshot_rung(empty_program(), contact_tag="PB_Start", block="OSR", storage_tag="OS1", output_tag="P1")
    p = add_compare_rung(p, contact_tag="PB_Start", op="GEQ", source_a="N7", source_b="3", coil_tag="M1")
    clip = lt.copy_rungs(p, _ids(p))
    p2, ids = lt.paste_rungs(p, clip)
    assert len(ids) == 2 and len(p2["rungs"]) == 4
    assert program_rung_to_elements(p2["rungs"][3]) == program_rung_to_elements(p["rungs"][1])
    sim = ScanSimulator.from_program(p2)
    sim.scan_once()  # no crash with pasted elements


def test_clip_from_text_rejects_foreign_text():
    assert lt.clip_from_text("hello") is None
    assert lt.clip_from_text('{"format":"other"}') is None
    with pytest.raises(ValueError):
        lt.paste_rungs(empty_program(), {"format": "nope"})


def test_copy_paste_instruction_input_goes_before_output_and_output_appends():
    p = _base()
    rid0, rid1 = _ids(p)[0], _ids(p)[1]
    stop = lt.copy_instruction(p, rid0, (0,))
    assert stop["element"]["kind"] == "contact"
    p2 = lt.paste_instruction(p, stop, rid1)
    els = program_rung_to_elements(next(r for r in p2["rungs"] if r["id"] == rid1))
    kinds = [e["kind"] for e in els]
    assert kinds.index("contact") < kinds.index("timer")
    assert sum(1 for e in els if e["kind"] == "contact") == 2
    coil_clip = lt.copy_instruction(p, rid0, (1,))
    assert coil_clip["element"]["kind"] == "coil"
    p3 = lt.paste_instruction(p2, coil_clip, rid1)
    els3 = program_rung_to_elements(next(r for r in p3["rungs"] if r["id"] == rid1))
    assert els3[-1] == {"kind": "coil", "var": "M1", "form": "normal"}
    assert any(e["kind"] == "timer" for e in els3)
    with pytest.raises(ValueError):
        lt.paste_rungs(p, coil_clip)


def test_paste_second_timer_keeps_both():
    p = _base()
    rid1 = _ids(p)[1]
    clip = lt.copy_instruction(p, rid1, (1,))
    clip["element"]["var"] = "T2"
    p2 = lt.paste_instruction(p, clip, rid1)
    els = program_rung_to_elements(next(r for r in p2["rungs"] if r["id"] == rid1))
    assert [e["var"] for e in els if e["kind"] == "timer"] == ["T1", "T2"]
    assert program_rung_to_elements(program_from_dict(program_to_dict(p2))["rungs"][1]) == els


def test_duplicate_and_move_rung():
    p = _base()
    a, b, c = _ids(p)
    p2, dup = lt.duplicate_rung(p, a)
    assert _ids(p2) == [a, dup, b, c]
    p3 = lt.move_rung(p2, c, -3)
    assert _ids(p3)[0] == c
    p4 = lt.move_rung(p3, c, -1)  # clamps
    assert _ids(p4)[0] == c
    p5 = lt.move_rung(p4, c, 1)
    assert _ids(p5)[1] == c


# --- tag DB / cross-ref -----------------------------------------------------


def test_tag_table_rows_descriptions_and_where_used():
    p = lt.set_tag_description(_base(), "T1", "Motor run proving delay")
    rows = {r["name"]: r for r in lt.tag_table(p, DEVICES)}
    assert rows["PB_Start"]["source"] == "device" and rows["PB_Start"]["class"] == "input"
    assert rows["PB_Start"]["description"] == "Start pushbutton"
    assert rows["T1"]["class"] == "timer" and rows["T1"]["type"] == "TON"
    assert rows["T1"]["description"] == "Motor run proving delay"
    # T1.DN contact counts toward T1
    assert {x["role"] for x in rows["T1"]["refs"]} >= {"TON", "XIC"}
    assert rows["M1"]["writes"] == 1 and rows["M1"]["reads"] == 1
    assert rows["PB_Stop"]["uses"] == 0
    xref = lt.cross_reference(p, "T1")
    assert [x["rung_index"] for x in xref] == [2, 3]
    assert lt.cross_reference(p, "T1.DN")[0]["label"] == "XIC T1.DN"
    html = lt.format_cross_reference_html(p, DEVICES)
    assert "Motor run proving delay" in html and "R3: XIC T1.DN" in html


def test_tag_descriptions_survive_dict_round_trip_and_clear():
    p = lt.set_tag_description(empty_program(), "N7", "Part count")
    d = program_to_dict(p)
    assert d["tag_descriptions"] == {"N7": "Part count"}
    assert program_from_dict(d)["tag_descriptions"] == {"N7": "Part count"}
    p2 = lt.set_tag_description(d, "N7", "  ")
    assert "tag_descriptions" not in program_to_dict(p2)
    assert "tag_descriptions" not in program_to_dict(empty_program())


def test_plcopen_round_trips_tag_descriptions():
    p = _base()
    p = add_compare_rung(p, contact_tag="PB_Start", op="GEQ", source_a="N7", source_b="3", coil_tag="LT_Run")
    p = lt.set_tag_description(p, "T1", "Proving delay")
    p = lt.set_tag_description(p, "N7", "Part count")
    p = lt.set_tag_description(p, "M1", "Main motor")
    xml = export_program_to_plcopen_xml(p, project_name="Desc", devices=DEVICES)
    assert "Proving delay" in xml and "Part count" in xml and "Start pushbutton" in xml
    back = import_plcopen_xml_to_program(xml)
    descs = back["tag_descriptions"]
    assert descs["T1"] == "Proving delay"
    assert descs["N7"] == "Part count"
    assert descs["M1"] == "Main motor"  # user text wins over device text
    assert descs["PB_Start"] == "Start pushbutton"
    # Timer preset still parsed from the documentation's first line
    t = next(r for r in back["rungs"] if r.get("timer"))
    assert t["timer"]["pt_ms"] == 2000


# --- find / replace -------------------------------------------------------------


def test_find_and_replace_tag_members_expression_and_description():
    p = _base()
    p = add_math_rung(p, contact_tag="T1.DN", op="CPT", dest="N7", source_a="", expression="N7+1")
    p = add_compare_rung(p, contact_tag="PB_Start", op="GEQ", source_a="N7", source_b="10", coil_tag="LT_Run")
    p = lt.set_tag_description(p, "T1", "Proving delay")
    assert len(lt.find_tag_refs(p, "T1", whole=True)) == 3
    assert len(lt.find_tag_refs(p, "n7")) >= 3  # case-insensitive substring
    p2, n = lt.replace_tag(p, "T1", "T_Prove")
    assert n == 3
    assert not lt.find_tag_refs(p2, "T1", whole=True, match_case=True)
    assert lt.find_tag_refs(p2, "T_Prove.DN", whole=True)
    assert p2["tag_descriptions"] == {"T_Prove": "Proving delay"}
    p3, n3 = lt.replace_tag(p2, "N7", "Count")
    assert n3 == 3
    math = next(e for r in p3["rungs"] for e in program_rung_to_elements(r) if e["kind"] == "math")
    assert math["dest"] == "Count" and math["expression"] == "Count+1"
    sim = ScanSimulator.from_program(p3)
    sim.scan_once()


def test_replace_limited_to_rungs_and_validates_name():
    p = _base()
    first = _ids(p)[0]
    p2, n = lt.replace_tag(p, "M1", "M2", rung_ids=[first])
    assert n == 1
    assert program_rung_to_elements(p2["rungs"][1])[0]["var"] == "M1"
    with pytest.raises(ValueError):
        lt.replace_tag(p, "M1", "bad name")
    with pytest.raises(ValueError):
        lt.replace_tag(p, "M1", "123")
    same, zero = lt.replace_tag(p, "Nope", "X1")
    assert zero == 0 and _ids(same) == _ids(p)


# --- verify -----------------------------------------------------------------------


def _codes(issues, severity=None):
    return {i["code"] for i in issues if severity is None or i["severity"] == severity}


def test_verify_clean_program_has_no_errors_or_warnings():
    p = add_rung(empty_program(), contact_tag="PB_Start", coil_tag="M1")
    p = add_rung(p, contact_tag="M1", coil_tag="LT_Run")
    issues = lt.verify_program(p, DEVICES)
    assert not _codes(issues, "error") and not _codes(issues, "warning")
    assert lt.verify_summary(issues).startswith("Verify OK")


def test_verify_flags_missing_tags_undriven_bad_presets_dup_storage():
    p = add_rung(empty_program(), contact_tag="Ghost_Bit", coil_tag="LT_Run")         # missing tag
    p = add_rung(p, contact_tag="M1", coil_tag="LT_Run")                               # undriven M1 + dup OTE
    p = add_timer_rung(p, contact_tag="PB_Start", timer_tag="T1", pt_ms=0)             # bad preset
    p = add_timer_rung(p, contact_tag="PB_Stop", timer_tag="T1", pt_ms=500)            # dup timer instance
    p = add_counter_rung(p, contact_tag="PB_Start", counter_tag="C1", block="CTU", pv=0)  # PRE<=0 warning
    p = add_counter_rung(p, contact_tag="PB_Stop", counter_tag="C9", block="RES")      # RES unknown counter
    p = add_oneshot_rung(p, contact_tag="PB_Start", block="ONS", storage_tag="OS1", coil_tag="LT_Run")
    p = add_oneshot_rung(p, contact_tag="PB_Stop", block="OSR", storage_tag="OS1", output_tag="P1")  # dup storage
    p = add_math_rung(p, contact_tag="PB_Start", op="DIV", dest="N7", source_a="10", source_b="0")
    p = add_math_rung(p, contact_tag="PB_Start", op="ADD", dest="5", source_a="1", source_b="2")
    p = add_rung(p, contact_tag="T7.DN", coil_tag="Aux")                               # undefined member
    p = add_latch_rung(p, contact_tag="PB_Start", coil_tag="Latch1", latch=True)       # OTL never OTU
    p = add_rung(p, contact_tag="PB_Start", coil_tag="")                               # no output
    issues = lt.verify_program(p, DEVICES)
    errors, warnings = _codes(issues, "error"), _codes(issues, "warning")
    assert {"BAD_PRESET", "DUP_INSTANCE", "DUP_STORAGE", "DIV_ZERO", "LITERAL_DEST", "UNDEFINED_MEMBER", "NO_OUTPUT"} <= errors
    assert {"MISSING_TAG", "UNDRIVEN_COIL", "DUP_OTE", "BAD_PRESET", "UNKNOWN_COUNTER", "LATCH_NO_UNLATCH"} <= warnings
    missing = next(i for i in issues if i["code"] == "MISSING_TAG")
    assert missing["tag"] == "Ghost_Bit" and missing["rung_index"] == 1 and missing["rung_id"]
    # errors sort first
    assert issues[0]["severity"] == "error"
    text = lt.format_verify_text(issues)
    assert "[ERROR]" in text and "DUP_STORAGE" in text


def test_verify_storage_bit_written_elsewhere_and_empty_program():
    p = add_oneshot_rung(empty_program(), contact_tag="PB_Start", block="ONS", storage_tag="OS1", coil_tag="M1")
    p = add_rung(p, contact_tag="PB_Stop", coil_tag="OS1")
    assert "DUP_STORAGE" in _codes(lt.verify_program(p, DEVICES), "error")
    assert _codes(lt.verify_program(empty_program(), DEVICES)) == {"EMPTY_PROGRAM"}


def test_verify_output_device_with_no_coil_is_info_and_described_tag_not_missing():
    p = add_rung(empty_program(), contact_tag="Aux_Input", coil_tag="M1")
    issues = lt.verify_program(p, DEVICES)
    assert any(i["code"] == "UNDRIVEN_COIL" and i["tag"] == "LT_Run" and i["severity"] == "info" for i in issues)
    assert "MISSING_TAG" in _codes(issues)
    p2 = lt.set_tag_description(p, "Aux_Input", "Spare input from HMI")
    assert "MISSING_TAG" not in _codes(lt.verify_program(p2, DEVICES))
