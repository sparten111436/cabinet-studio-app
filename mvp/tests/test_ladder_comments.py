"""v0.3.6 richer rung comments (multi-line) + instruction notes."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import program_to_ladder_ir, ladder_ir_to_program
from cabinet_studio.services.ladder_print import (
    comment_extra_height,
    ladder_program_to_svg,
    rung_block_height_from_elements,
)
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
    plcopen_xml_to_ladder_ir,
)
from cabinet_studio.services.programming import (
    add_rung,
    empty_program,
    format_plc_text,
    program_from_dict,
    program_to_dict,
    rung_instruction_list,
    set_instruction_notes,
    set_rung_comment,
)

COMMENT = "Motor 1 start/stop seal-in\nStop + E-Stop are NC (fail-safe wiring)\nDesign aid only"


def _seal_prog():
    return add_rung(
        empty_program(),
        contact_tag="",
        coil_tag="M1",
        parallel=[[{"tag": "Start", "normally_closed": False}], [{"tag": "M1", "normally_closed": False}]],
        series=[{"tag": "Stop", "normally_closed": True}],
    )


def test_multiline_comment_survives_save_load():
    prog = _seal_prog()
    rid = prog["rungs"][0]["id"]
    prog = set_rung_comment(prog, rid, COMMENT + "   \n")
    again = program_from_dict(program_to_dict(prog))
    assert again["rungs"][0]["comment"] == COMMENT


def test_text_export_uses_first_line_title_and_slash_lines():
    prog = _seal_prog()
    prog = set_rung_comment(prog, prog["rungs"][0]["id"], COMMENT)
    text = format_plc_text(prog["rungs"])
    assert "Rung 1 - Motor 1 start/stop seal-in" in text
    assert "  // Stop + E-Stop are NC (fail-safe wiring)" in text


def test_print_svg_comment_block_grows_rung():
    els = [{"kind": "contact", "var": "A"}, {"kind": "coil", "var": "Y"}]
    assert comment_extra_height("one line") == 0
    assert rung_block_height_from_elements(els, COMMENT) > rung_block_height_from_elements(els, "one line")
    prog = _seal_prog()
    prog = set_rung_comment(prog, prog["rungs"][0]["id"], COMMENT)
    svg, _w, _h = ladder_program_to_svg(prog["rungs"])
    assert "Rung 1: Motor 1 start/stop seal-in" in svg
    assert "Stop + E-Stop are NC (fail-safe wiring)" in svg
    assert 'stroke-dasharray="3,2"' in svg


def test_plcopen_comment_object_roundtrip_simple_rung():
    prog = _seal_prog()
    prog = set_rung_comment(prog, prog["rungs"][0]["id"], COMMENT)
    xml = export_program_to_plcopen_xml(prog)
    assert "<comment " in xml and "xhtml:p" in xml
    back = import_plcopen_xml_to_program(xml)
    assert back["rungs"][0]["comment"] == COMMENT


def test_plcopen_legacy_first_contact_doc_still_imports_comment():
    legacy = """<?xml version="1.0"?>
<project xmlns="http://www.plcopen.org/xml/tc6_0201"><types><pous><pou name="Main" pouType="program"><body><LD>
<leftPowerRail localId="1"><connectionPointOut/></leftPowerRail>
<contact localId="2" negated="false" variable="A"><connectionPointIn><connection refLocalId="1"/></connectionPointIn><connectionPointOut/><documentation>Old style comment</documentation></contact>
<coil localId="3" variable="Y"><connectionPointIn><connection refLocalId="2"/></connectionPointIn></coil>
<rightPowerRail localId="4"><connectionPointIn><connection refLocalId="3"/></connectionPointIn></rightPowerRail>
</LD></body></pou></pous></types></project>"""
    ir = plcopen_xml_to_ladder_ir(legacy)
    assert ir["rungs"][0]["comment"] == "Old style comment"


def test_instruction_notes_on_classic_rung():
    prog = _seal_prog()
    rid = prog["rungs"][0]["id"]
    items = rung_instruction_list(prog["rungs"][0])
    labels = [label for _p, label, _n in items]
    assert labels == ["XIC Start", "XIC M1", "XIO Stop", "OTE M1"]
    seal_path = items[1][0]
    stop_path = items[2][0]
    prog = set_instruction_notes(prog, rid, {seal_path: "seal-in aux contact", stop_path: "  red mushroom  "})
    rung = prog["rungs"][0]
    assert rung["coil_tag"] == "M1"  # classic fields still in sync
    notes = {label: note for _p, label, note in rung_instruction_list(rung)}
    assert notes["XIC M1"] == "seal-in aux contact" and notes["XIO Stop"] == "red mushroom"
    # clear one note
    prog = set_instruction_notes(prog, rid, {stop_path: ""})
    notes = {label: note for _p, label, note in rung_instruction_list(prog["rungs"][0])}
    assert notes["XIO Stop"] == ""


def test_notes_survive_ir_plcopen_print_and_text():
    prog = _seal_prog()
    rid = prog["rungs"][0]["id"]
    path = rung_instruction_list(prog["rungs"][0])[2][0]
    prog = set_instruction_notes(prog, rid, {path: "Stop PB NC"})
    back = ladder_ir_to_program(program_to_ladder_ir(prog))
    assert any(e.get("desc") == "Stop PB NC" for e in back["rungs"][0]["elements"])
    xml = export_program_to_plcopen_xml(prog)
    assert "note: Stop PB NC" in xml
    imported = import_plcopen_xml_to_program(xml)
    assert any(e.get("desc") == "Stop PB NC" for e in imported["rungs"][0]["elements"])
    svg, _w, _h = ladder_program_to_svg(prog["rungs"])
    assert "Stop PB NC" in svg
    assert "{Stop PB NC}" in format_plc_text(prog["rungs"])
