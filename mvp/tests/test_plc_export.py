"""PLC export: L5X well-formed, rung text round-trip, refusal on unmappable elements, vendor files."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.services.plc_export import (
    RllError,
    build_l5x,
    canonical,
    elements_to_rll,
    l5x_rung_texts,
    parse_rll,
    write_plc_exports,
)
from cabinet_studio.services.programming import add_rung_from_elements, empty_program, program_to_dict

C = lambda v, nc=False: {"kind": "contact", "var": v, "form": "NC" if nc else "NO"}  # noqa: E731
COIL = lambda v, form="normal": {"kind": "coil", "var": v, "form": form}  # noqa: E731

RUNGS = [
    [C("Stop_PB", True), {"kind": "or", "branches": [[C("Start_PB")], [C("Motor")]]}, COIL("Motor")],
    [C("Motor"), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 5000}],
    [C("T1.DN"), {"kind": "counter", "var": "C1", "block": "CTU", "pv": 10}, COIL("Done", "set")],
    [C("Reset_PB"), {"kind": "counter", "var": "C1", "block": "RES"}, COIL("Done", "reset")],
    [{"kind": "compare", "op": "LIM", "source_a": "Level", "source_b": "10", "source_c": "90"}, COIL("InRange")],
    [{"kind": "compare", "op": "GEQ", "source_a": "C1.ACC", "source_b": "5"},
     {"kind": "math", "op": "ADD", "source_a": "Count", "source_b": "1", "dest": "Count"},
     {"kind": "math", "op": "MOV", "source_a": "0", "dest": "Speed"},
     {"kind": "math", "op": "CPT", "dest": "Out", "expression": "(Count*2)+Speed"}],
    [C("Start_PB"), {"kind": "oneshot", "block": "OSR", "var": "OS1", "output": "Pulse"}],
    [C("Start_PB"), {"kind": "oneshot", "block": "ONS", "var": "OS2"}, {"kind": "jsr", "target": "Sub1"}],
    [{"kind": "or", "branches": [[C("A"), C("B")], [{"kind": "or", "branches": [[C("C")], [C("D", True)]]}]]},
     COIL("E")],
]


def _project(rungs=RUNGS, catalog="1769-L33ER"):
    prog = empty_program()
    for els in rungs:
        prog = add_rung_from_elements(prog, els, comment="test rung")
    items = [
        PlacedItem(id="p", library_id=None, type_id="plc", x=0, y=0, fields={"tag": "PLC1", "catalog": catalog}),
        PlacedItem(id="m1", library_id=None, type_id="io_module", x=0, y=0,
                   fields={"tag": "IO1", "io_kind": "DI", "point_count": "16", "slot": "1", "parent_tag": "PLC1"}),
        PlacedItem(id="m2", library_id=None, type_id="io_module", x=0, y=0,
                   fields={"tag": "IO2", "io_kind": "DO", "point_count": "16", "slot": "2", "parent_tag": "PLC1"}),
        PlacedItem(id="a", library_id=None, type_id="pushbutton", x=0, y=0,
                   fields={"tag": "Start_PB", "description": "Start"}),
        PlacedItem(id="b", library_id=None, type_id="pushbutton", x=0, y=0, fields={"tag": "Stop_PB"}),
        PlacedItem(id="c", library_id=None, type_id="contactor", x=0, y=0, fields={"tag": "Motor"}),
    ]
    return Project(name="Export Test", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                   items=items, program=program_to_dict(prog))


@pytest.mark.parametrize("els", RUNGS)
def test_rung_text_round_trips_to_same_elements(els):
    text = elements_to_rll(els)
    assert text.endswith(";")
    assert canonical(parse_rll(text)) == canonical(els)


def test_known_rung_text():
    assert elements_to_rll(RUNGS[0]) == "XIO(Stop_PB)[XIC(Start_PB),XIC(Motor)]OTE(Motor);"
    assert elements_to_rll(RUNGS[1]) == "XIC(Motor)TON(T1,5000,0);"
    assert elements_to_rll(RUNGS[4]) == "LIM(10,Level,90)OTE(InRange);"


@pytest.mark.parametrize("bad, words", [
    ([C("A"), {"kind": "pid", "var": "P1"}], "not one Cabinet Studio can write"),
    ([C("A"), COIL("B", "negated")], "negated"),
    ([C("A"), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 0, "pt_tag": "Delay"}], "preset"),
    ([{"kind": "counter", "var": "C1", "block": "LOAD", "pv": 3}], "LOAD"),
])
def test_unmappable_elements_refuse(bad, words):
    with pytest.raises(RllError, match=words):
        elements_to_rll(bad)


def test_l5x_well_formed_with_aliases_and_every_rung_reparses():
    proj = _project()
    xml = build_l5x(proj)
    root = ET.fromstring(xml)
    assert root.tag == "RSLogix5000Content" and root.get("TargetType") == "Program"
    aliases = {t.get("Name"): t.get("AliasFor") for t in root.iter("Tag") if t.get("TagType") == "Alias"}
    assert aliases["Start_PB"] == "Local:1:I.Data.0" and aliases["Motor"] == "Local:2:O.Data.0"
    types = {t.get("Name"): t.get("DataType") for t in root.iter("Tag") if t.get("TagType") == "Base"}
    assert types["T1"] == "TIMER" and types["C1"] == "COUNTER" and types["Count"] == "DINT"
    texts = l5x_rung_texts(xml)["MainRoutine"]
    assert len(texts) == len(RUNGS)
    for text, els in zip(texts, RUNGS):
        assert canonical(parse_rll(text)) == canonical(els)
    assert "NOT A CERTIFIED UL 508A DRAWING" in xml


def test_l5x_refuses_whole_file_on_unknown_instruction():
    proj = _project()
    proj.program["rungs"][0]["elements"].append({"kind": "pid", "var": "P1"})
    with pytest.raises(RllError, match="unknown instruction"):
        build_l5x(proj)


def test_write_exports_per_vendor(tmp_path):
    out = write_plc_exports(_project(), tmp_path / "ab")
    names = {p.name for p in out.files}
    assert {"program.L5X", "ab-tags.csv", "io-list.csv", "rungs.txt", "README.txt"} <= names and not out.refused
    readme = (tmp_path / "ab" / "README.txt").read_text(encoding="utf-8")
    assert "Import Program" in readme and "never the safety function" in readme
    s7 = write_plc_exports(_project(catalog="6ES7214-1AG40-0XB0"), tmp_path / "s7")
    assert {"program-plcopen.xml", "siemens-plc-tags.csv"} <= {p.name for p in s7.files}
    csv_text = (tmp_path / "s7" / "siemens-plc-tags.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("Name,Path,Data Type,Logical Address")
    assert "Start_PB,Default tag table,Bool,%I0.0" in csv_text
    om = write_plc_exports(_project(catalog="NX1P2-9024DT"), tmp_path / "om")
    assert "omron-variables.csv" in {p.name for p in om.files}
    m8 = write_plc_exports(_project(catalog="2080-LC50-24QWB"), tmp_path / "m8")
    assert "micro800-variables.csv" in {p.name for p in m8.files}


def test_export_reports_refusal_instead_of_dropping(tmp_path):
    proj = _project([[C("A"), COIL("B", "negated")]])
    out = write_plc_exports(proj, tmp_path)
    assert out.refused and "negated" in out.refused[0]
    assert not (tmp_path / "program.L5X").exists()
    assert "NOT WRITTEN" in (tmp_path / "README.txt").read_text(encoding="utf-8")
