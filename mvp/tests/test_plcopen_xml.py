"""Tests for PLCopen XML interchange (contacts, coils, OR, timers)."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import program_to_ladder_ir
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    ladder_ir_to_plcopen_xml,
    plcopen_xml_to_ladder_ir,
)
from cabinet_studio.services.programming import add_timer_rung, empty_program


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
    flat_or = []
    for rung in back["rungs"]:
        for e in rung["elements"]:
            if e.get("kind") == "or":
                for br in e.get("branches") or []:
                    for item in br:
                        flat_or.append(item.get("var"))
    all_contactish = set(contacts) | set(flat_or)
    assert "PB_Start" in all_contactish or "PB_Stop" in all_contactish


def test_plcopen_round_trip_series_parallel_and_coil():
    ir = program_to_ladder_ir(_seal_in_program(), project_name="Demo")
    xml = ladder_ir_to_plcopen_xml(ir)
    back = plcopen_xml_to_ladder_ir(xml)
    assert len(back["rungs"]) >= 1
    els = back["rungs"][0]["elements"]
    kinds = [e["kind"] for e in els]
    assert "coil" in kinds
    # Parallel OR should survive as or or as multiple contacts
    has_or = "or" in kinds
    contact_vars = set()
    for e in els:
        if e.get("kind") == "contact":
            contact_vars.add(e.get("var"))
        elif e.get("kind") == "or":
            for br in e.get("branches") or []:
                for item in br:
                    contact_vars.add(item.get("var"))
    assert "PB_Start" in contact_vars
    assert "CR1" in contact_vars or any(
        e.get("kind") == "coil" and e.get("var") == "CR1" for e in els
    )
    if has_or:
        assert len(next(e for e in els if e["kind"] == "or")["branches"]) >= 2


def test_plcopen_timer_round_trip():
    prog = add_timer_rung(
        empty_program(),
        contact_tag="PB_Start",
        timer_tag="T_Delay",
        block="TON",
        pt_ms=1500,
        coil_tag="CR1",
    )
    ir = program_to_ladder_ir(prog, project_name="TimerCab")
    xml = ladder_ir_to_plcopen_xml(ir)
    assert 'typeName="TON"' in xml
    assert 'instanceName="T_Delay"' in xml
    assert "T#1500ms" in xml or "T#1.5s" in xml or "pt_ms=1500" in xml
    back = plcopen_xml_to_ladder_ir(xml)
    timers = [
        e
        for rung in back["rungs"]
        for e in rung["elements"]
        if e.get("kind") == "timer"
    ]
    assert len(timers) == 1
    assert timers[0]["var"] == "T_Delay"
    assert timers[0]["block"] == "TON"
    assert timers[0]["pt_ms"] == 1500
    coils = [e["var"] for rung in back["rungs"] for e in rung["elements"] if e.get("kind") == "coil"]
    assert "CR1" in coils


def test_plcopen_tof_rto_blocks():
    for block, pt in (("TOF", 800), ("RTO", 2500)):
        prog = add_timer_rung(
            empty_program(),
            contact_tag="IN1",
            timer_tag=f"T_{block}",
            block=block,
            pt_ms=pt,
        )
        ir = program_to_ladder_ir(prog)
        xml = ladder_ir_to_plcopen_xml(ir)
        assert f'typeName="{block}"' in xml
        back = plcopen_xml_to_ladder_ir(xml)
        timers = [e for r in back["rungs"] for e in r["elements"] if e.get("kind") == "timer"]
        assert timers[0]["block"] == block
        assert timers[0]["pt_ms"] == pt
