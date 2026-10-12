"""Tests for PLCopen XML interchange."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import program_to_ladder_ir
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    ladder_ir_to_plcopen_xml,
    plcopen_xml_to_ladder_ir,
)


def _seal_in_program():
    return {
        "answers": {},
        "rungs": [
            {
                "id": "r1",
                "parallel": [
                    [{"tag": "PB_Start", "normally_closed": False}],
                    [{"tag": "CR1", "normally_closed": False}],
                ],
                "series": [
                    {"tag": "PB_Stop", "normally_closed": True},
                ],
                "coil_tag": "CR1",
                "coil_negated": False,
                "comment": "Seal-in",
                "contact_tag": "PB_Start",
                "normally_closed": False,
            }
        ],
        "hmi_items": [],
        "plc_text": "",
        "hmi_text": "",
        "text_edited": False,
    }


def test_export_contains_contacts_and_coil():
    xml = export_program_to_plcopen_xml(_seal_in_program(), project_name="Demo")
    assert "plcopen.org/xml/tc6" in xml
    assert "PB_Start" in xml
    assert "CR1" in xml
    assert "<contact" in xml or "contact " in xml
    assert "<coil" in xml or "coil " in xml


def test_plcopen_round_trip_preserves_coil():
    ir = program_to_ladder_ir(_seal_in_program(), project_name="Demo")
    xml = ladder_ir_to_plcopen_xml(ir)
    back = plcopen_xml_to_ladder_ir(xml)
    assert back["rungs"], "expected at least one rung after import"
    coils = [
        e["var"]
        for rung in back["rungs"]
        for e in rung["elements"]
        if e.get("kind") == "coil"
    ]
    assert "CR1" in coils
    contacts = [
        e["var"]
        for rung in back["rungs"]
        for e in rung["elements"]
        if e.get("kind") == "contact"
    ]
    # OR branches flatten into contact vars somewhere
    flat_or = []
    for rung in back["rungs"]:
        for e in rung["elements"]:
            if e.get("kind") == "or":
                for br in e.get("branches") or []:
                    for item in br:
                        flat_or.append(item.get("var"))
    all_contactish = set(contacts) | set(flat_or)
    assert "PB_Start" in all_contactish or "PB_Stop" in all_contactish
