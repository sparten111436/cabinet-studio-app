"""v0.3.11 correctness: Audit Droid P1 regressions + PLCopen XSD structural checks."""
from __future__ import annotations

from pathlib import Path

import pytest

from cabinet_studio.services.ladder_ir import (
    elements_need_storage,
    elements_to_program_rung,
    normalize_ladder_ir,
    program_rung_to_elements,
    program_to_ladder_ir,
    coerce_numeric,
)
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.plcopen_xml import ladder_ir_to_plcopen_xml, plcopen_xml_to_ladder_ir
from cabinet_studio.services.programming import (
    add_nested_or_rung,
    add_rung_from_elements,
    empty_program,
    format_ladder_txt,
)
from cabinet_studio.services.ladder_print import (
    ladder_program_to_svg_pages,
    pack_rungs_onto_pages,
    PAGE_CONTENT_H,
)


def _C(v, f="NO"):
    return {"kind": "contact", "var": v, "form": f}


def _O(v, f="normal"):
    return {"kind": "coil", "var": v, "form": f}


def _sim(rungs, variables=None, routines=None):
    ir = {"format": "cabinet-studio-ladder", "variables": variables or [], "rungs": rungs}
    if routines:
        ir["routines"] = routines
    return ScanSimulator(normalize_ladder_ir(ir))


# ---- P1-2: contact-before-OR / consecutive ORs ----
def test_p1_2_consecutive_ors_do_not_collapse():
    els = [
        {"kind": "or", "branches": [[_C("OA")], [_C("OB")]]},
        {"kind": "or", "branches": [[_C("OC")], [_C("OD")]]},
        _O("Y"),
    ]
    assert elements_need_storage(els)
    rung = elements_to_program_rung(els, comment="consec")
    assert "elements" in rung
    rebuilt = program_rung_to_elements(rung)
    assert rebuilt[0]["kind"] == "or" and rebuilt[1]["kind"] == "or"
    prog = add_rung_from_elements(empty_program(), els, comment="consec")
    sim = ScanSimulator.from_program(prog)
    r = sim.scan_once({"OA": True, "OB": False, "OC": False, "OD": False})
    assert r["vars"]["Y"] is False
    r = sim.scan_once({"OA": True, "OB": False, "OC": True, "OD": False})
    assert r["vars"]["Y"] is True


def test_p1_2_contact_before_or_preserved():
    els = [_C("L"), {"kind": "or", "branches": [[_C("PB_Start")], [_C("M1")]]}, _O("Y")]
    assert elements_need_storage(els)
    prog = add_rung_from_elements(empty_program(), els, comment="lead")
    ir = program_to_ladder_ir(prog)
    xml = ladder_ir_to_plcopen_xml(ir)
    back = plcopen_xml_to_ladder_ir(xml)
    sim = ScanSimulator(back)
    r = sim.scan_once({"L": False, "PB_Start": True, "M1": False})
    assert r["vars"]["Y"] is False
    r = sim.scan_once({"L": True, "PB_Start": True, "M1": False})
    assert r["vars"]["Y"] is True


# ---- P1-7: actuators inside OR branches ----
def test_p1_7_coils_inside_or_energize():
    els = [_C("A"), {"kind": "or", "branches": [[_O("Y1")], [_O("Y2")]]}]
    sim = _sim([{"id": "1", "elements": els}])
    r = sim.scan_once({"A": True})
    assert r["vars"].get("Y1") is True and r["vars"].get("Y2") is True


def test_p1_7_mov_and_ton_inside_or_execute():
    vars_ = [{"name": "N", "class": "numeric", "type": "DINT", "value": 0}]
    els = [
        {
            "kind": "or",
            "branches": [
                [_C("A"), {"kind": "math", "op": "MOV", "dest": "N", "source_a": "5"}],
                [_C("B")],
            ],
        }
    ]
    sim = _sim([{"id": "1", "elements": els}], vars_)
    r = sim.scan_once({"A": True, "B": False})
    assert r["numbers"]["N"] == 5.0

    els_t = [
        _C("A"),
        {
            "kind": "or",
            "branches": [
                [{"kind": "timer", "var": "T9", "block": "TON", "pt_ms": 100}],
                [_O("Y3")],
            ],
        },
    ]
    sim = _sim([{"id": "1", "elements": els_t}])
    for _ in range(5):
        r = sim.scan_once({"A": True})
    assert r["timers"]["T9"]["acc_ms"] > 0


# ---- P1-1: nested OR with series contacts PLCopen RT ----
def test_p1_1_nested_or_series_plcopen_roundtrip():
    prog = add_nested_or_rung(
        empty_program(),
        lead_tag="",
        or_branches=[[{"tag": "X1"}, {"tag": "X2"}], [{"tag": "X3"}]],
        coil_tag="Y",
        comment="X1,X2|X3",
    )
    ir = program_to_ladder_ir(prog)
    xml = ladder_ir_to_plcopen_xml(ir)
    back = plcopen_xml_to_ladder_ir(xml)
    # Property-ish: elements structure preserved via hint
    els = back["rungs"][0]["elements"]
    assert els[0]["kind"] == "or"
    assert len(els[0]["branches"][0]) == 2  # X1,X2 series
    sim = ScanSimulator(back)
    r = sim.scan_once({"X1": False, "X2": False, "X3": True})
    assert r["vars"]["Y"] is True
    r = sim.scan_once({"X1": True, "X2": False, "X3": False})
    assert r["vars"]["Y"] is False
    r = sim.scan_once({"X1": True, "X2": True, "X3": False})
    assert r["vars"]["Y"] is True


# ---- P1-4: address + numeric initial ----
def test_p1_4_plcopen_preserves_address_and_initial_value():
    ir = {
        "format": "cabinet-studio-ladder",
        "variables": [
            {"name": "A", "class": "input", "type": "BOOL", "address": "_IO_EM_DI_00"},
            {"name": "SP", "class": "numeric", "type": "DINT", "value": 42},
            {"name": "Y", "class": "output", "type": "BOOL"},
        ],
        "rungs": [
            {
                "id": "1",
                "elements": [
                    _C("A"),
                    {"kind": "compare", "op": "GRT", "source_a": "SP", "source_b": "10"},
                    _O("Y"),
                ],
            }
        ],
    }
    xml = ladder_ir_to_plcopen_xml(ir)
    assert 'address="_IO_EM_DI_00"' in xml
    assert "initialValue" in xml and "42" in xml
    back = plcopen_xml_to_ladder_ir(xml)
    by_name = {v["name"]: v for v in back["variables"]}
    assert by_name["A"].get("address") == "_IO_EM_DI_00"
    assert float(by_name["SP"].get("value")) == 42.0
    sim = ScanSimulator(back)
    assert sim.scan_once({"A": True})["vars"]["Y"] is True


# ---- P1-5 LIM inverted ----
def test_p1_5_lim_inverted_rockwell():
    num = [{"name": "T", "class": "numeric", "type": "DINT", "value": 0}]
    els = [
        {"kind": "compare", "op": "LIM", "source_a": "T", "source_b": "90", "source_c": "10"},
        _O("Y"),
    ]
    sim = _sim([{"id": "1", "elements": els}], num)
    sim.set_number("T", 95)
    assert sim.scan_once()["vars"]["Y"] is True
    sim.set_number("T", 5)
    assert sim.scan_once()["vars"]["Y"] is True
    sim.set_number("T", 50)
    assert sim.scan_once()["vars"]["Y"] is False
    # Normal band still works
    els2 = [
        {"kind": "compare", "op": "LIM", "source_a": "T", "source_b": "10", "source_c": "90"},
        _O("Y"),
    ]
    sim = _sim([{"id": "1", "elements": els2}], num)
    sim.set_number("T", 50)
    assert sim.scan_once()["vars"]["Y"] is True


# ---- P1-6 typed math ----
def test_p1_6_dint_div_truncates_and_overflow_wraps():
    def math(op, a, b, dest_type="DINT", expr=""):
        v = [
            {"name": "D", "class": "numeric", "type": dest_type, "value": 0},
            {"name": "A", "class": "numeric", "type": "DINT", "value": a},
            {"name": "B", "class": "numeric", "type": "DINT", "value": b},
        ]
        el = {"kind": "math", "op": op, "dest": "D", "source_a": "A", "source_b": "B"}
        if expr:
            el["expression"] = expr
        return _sim([{"id": "1", "elements": [el]}], v).scan_once()["numbers"]["D"]

    assert math("DIV", 7, 2) == 3.0
    assert math("MUL", 2147483647, 2) == -2.0
    assert math("ADD", 2147483647, 1) == -2147483648.0
    assert math("CPT", 0, 0, expr="7/2") == 3.0
    # MOV 3.7 → DINT rounds to 4
    v = [
        {"name": "D", "class": "numeric", "type": "DINT", "value": 0},
        {"name": "A", "class": "numeric", "type": "REAL", "value": 3.7},
    ]
    r = _sim(
        [{"id": "1", "elements": [{"kind": "math", "op": "MOV", "dest": "D", "source_a": "A"}]}],
        v,
    ).scan_once()
    assert r["numbers"]["D"] == 4.0


def test_coerce_numeric_helpers():
    assert coerce_numeric(7 / 2, "DINT", op="DIV") == 3.0
    assert coerce_numeric(3.7, "DINT", op="MOV") == 4.0
    assert coerce_numeric(2147483647 * 2, "DINT", op="MUL") == -2.0


# ---- P1-3 XSD structural / schema ----
def test_p1_3_plcopen_export_has_required_structure():
    ir = {
        "format": "cabinet-studio-ladder",
        "variables": [
            {"name": "A", "class": "input", "type": "BOOL", "address": "%IX0.0"},
            {"name": "Y", "class": "output", "type": "BOOL"},
            {"name": "SP", "class": "numeric", "type": "DINT", "value": 10},
        ],
        "rungs": [
            {
                "id": "1",
                "comment": "line1\nline2",
                "elements": [
                    _C("A"),
                    {"kind": "compare", "op": "GRT", "source_a": "SP", "source_b": "5"},
                    _O("Y"),
                ],
            }
        ],
    }
    xml = ladder_ir_to_plcopen_xml(ir)
    assert "<coordinateInfo>" in xml or "coordinateInfo" in xml
    assert "<dataTypes" in xml or "dataTypes>" in xml
    assert "<instances" in xml
    assert "<configurations" in xml
    # contact/coil use child <variable>
    contact_body = xml.split("<contact")[1].split("</contact>")[0]
    assert 'variable="' not in contact_body  # attribute form forbidden; use child <variable>
    # more direct: after contact open tag, should have <variable> child
    assert "<variable>" in xml
    assert "address=" in xml
    assert "initialValue" in xml


def test_p1_3_plcopen_validates_against_tc6_xsd():
    lxml = pytest.importorskip("lxml")
    from lxml import etree

    xsd_path = Path(__file__).resolve().parent / "tc6_xml_v201.xsd"
    if not xsd_path.is_file():
        xsd_path = Path("/workspace/cabinet-studio/mvp/research/schemas/tc6_xml_v201.xsd")
    if not xsd_path.is_file():
        pytest.skip("TC6 XSD not available")
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    ir = {
        "format": "cabinet-studio-ladder",
        "meta": {"project": "XsdCheck"},
        "variables": [
            {"name": "A", "class": "input", "type": "BOOL"},
            {"name": "Y", "class": "output", "type": "BOOL"},
            {"name": "T1", "class": "timer", "type": "TON", "pt_ms": 1000},
            {"name": "C1", "class": "counter", "type": "CTU", "pv": 5},
            {"name": "Q", "class": "numeric", "type": "DINT"},
            {"name": "SP", "class": "numeric", "type": "DINT", "value": 10},
        ],
        "rungs": [
            {"id": "1", "comment": "simple", "elements": [_C("A"), _O("Y")]},
            {
                "id": "2",
                "comment": "timer",
                "elements": [
                    _C("A"),
                    {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 1000},
                ],
            },
            {
                "id": "3",
                "comment": "math",
                "elements": [
                    _C("A"),
                    {"kind": "math", "op": "DIV", "dest": "Q", "source_a": "7", "source_b": "2"},
                    _O("Y"),
                ],
            },
            {
                "id": "4",
                "comment": "compare",
                "elements": [
                    _C("A"),
                    {"kind": "compare", "op": "GRT", "source_a": "SP", "source_b": "5"},
                    _O("Y"),
                ],
            },
        ],
    }
    xml = ladder_ir_to_plcopen_xml(ir)
    doc = etree.fromstring(xml.encode("utf-8"))
    ok = schema.validate(doc)
    if not ok:
        # Report but allow documenting remaining gaps if structural requireds pass.
        errors = [str(e) for e in schema.error_log][:12]
        # Required structural pieces must not be among failures
        joined = " | ".join(errors)
        assert "coordinateInfo" not in joined or ok
        assert "dataTypes" not in joined or ok
        assert "instances" not in joined or ok
        # Prefer full pass; if residual schema noise remains, surface it clearly.
        pytest.fail("PLCopen export failed TC6 XSD validation:\n" + "\n".join(errors))


# ---- Print P2 continuous numbers / packing ----
def test_print_continuous_rung_numbers_and_packing_height():
    rungs = []
    for i in range(12):
        rungs.append(
            {
                "id": str(i + 1),
                "comment": f"Rung comment {i+1}",
                "elements": [_C(f"I{i}"), _O(f"O{i}")],
            }
        )
    pages = pack_rungs_onto_pages(rungs)
    assert len(pages) >= 1
    svgs = ladder_program_to_svg_pages(rungs, project_name="PackTest")
    assert len(svgs) == len(pages)
    # Continuous numbers: page 2 should not restart at Rung 1 if multi-page
    if len(svgs) > 1:
        body1, _, h1 = svgs[0]
        body2, _, h2 = svgs[1]
        assert "Rung 1:" in body1 or "Rung 1 " in body1
        assert "Rung 1:" not in body2  # should continue
        assert h1 <= PAGE_CONTENT_H + 80
        assert h2 <= PAGE_CONTENT_H + 80
    # Footer present
    assert "Design aid only" in svgs[0][0]


def test_format_ladder_txt_shows_compare_math_names():
    prog = add_rung_from_elements(
        empty_program(),
        [
            _C("A"),
            {"kind": "compare", "op": "GRT", "source_a": "SP", "source_b": "10"},
            {"kind": "math", "op": "MOV", "dest": "D", "source_a": "1"},
            _O("Y"),
        ],
        comment="mathy",
    )
    txt = format_ladder_txt(prog, cabinet_name="T")
    assert "COIL:     (?)" not in txt
    assert "LOGIC:" in txt
    assert "GRT" in txt
    assert "MOV" in txt


def test_ir_xml_ir_property_nested_and_consec():
    """Property-style: IR → XML → IR keeps critical shapes."""
    cases = [
        add_nested_or_rung(
            empty_program(),
            lead_tag="L",
            or_branches=[[{"tag": "A"}, {"tag": "B"}], [{"tag": "C"}]],
            coil_tag="Y",
            comment="lead+series",
        ),
        add_rung_from_elements(
            empty_program(),
            [
                {"kind": "or", "branches": [[_C("OA")], [_C("OB")]]},
                {"kind": "or", "branches": [[_C("OC")], [_C("OD")]]},
                _O("Y"),
            ],
            comment="consec",
        ),
    ]
    for prog in cases:
        ir = program_to_ladder_ir(prog)
        back = plcopen_xml_to_ladder_ir(ladder_ir_to_plcopen_xml(ir))
        assert len(back["rungs"]) == 1
        assert back["rungs"][0]["elements"]
