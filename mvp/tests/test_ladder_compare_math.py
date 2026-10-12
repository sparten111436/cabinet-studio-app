"""Compare / math / OTL-OTU (v0.3.5)."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import normalize_ladder_ir, program_to_ladder_ir
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.plcopen_xml import (
    ladder_ir_to_plcopen_xml,
    plcopen_xml_to_ladder_ir,
)
from cabinet_studio.services.programming import (
    add_compare_rung,
    add_latch_rung,
    add_math_rung,
    empty_program,
    format_plc_text,
    program_from_dict,
    program_to_dict,
)


def test_math_add_and_compare_geq():
    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "variables": [
                {"name": "N7_0", "class": "numeric", "type": "DINT", "value": 0},
            ],
            "rungs": [
                {
                    "id": "1",
                    "elements": [
                        {"kind": "contact", "var": "EN", "form": "NO"},
                        {
                            "kind": "math",
                            "op": "ADD",
                            "dest": "N7_0",
                            "source_a": "N7_0",
                            "source_b": "1",
                        },
                    ],
                },
                {
                    "id": "2",
                    "elements": [
                        {"kind": "contact", "var": "EN", "form": "NO"},
                        {"kind": "compare", "op": "GEQ", "source_a": "N7_0", "source_b": "3"},
                        {"kind": "coil", "var": "OUT", "form": "normal"},
                    ],
                },
            ],
        }
    )
    sim = ScanSimulator(ir)
    assert sim.scan_once({"EN": True})["numbers"]["N7_0"] == 1
    assert sim.scan_once({"EN": True})["vars"].get("OUT") is False
    r = sim.scan_once({"EN": True})
    assert r["numbers"]["N7_0"] == 3
    assert r["vars"]["OUT"] is True


def test_all_compare_ops():
    def run(op, a, b, expect):
        ir = normalize_ladder_ir(
            {
                "format": "cabinet-studio-ladder",
                "rungs": [
                    {
                        "id": "1",
                        "elements": [
                            {"kind": "compare", "op": op, "source_a": str(a), "source_b": str(b)},
                            {"kind": "coil", "var": "OUT", "form": "normal"},
                        ],
                    }
                ],
            }
        )
        return ScanSimulator(ir).scan_once()["vars"]["OUT"] is expect

    assert run("EQU", 5, 5, True)
    assert run("NEQ", 5, 4, True)
    assert run("GRT", 6, 5, True)
    assert run("LES", 4, 5, True)
    assert run("GEQ", 5, 5, True)
    assert run("LEQ", 5, 5, True)
    assert run("GRT", 5, 5, False)


def test_math_ops_mov_div():
    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "variables": [
                {"name": "A", "class": "numeric", "type": "DINT", "value": 10},
                {"name": "B", "class": "numeric", "type": "DINT", "value": 0},
                {"name": "C", "class": "numeric", "type": "DINT", "value": 0},
            ],
            "rungs": [
                {
                    "id": "1",
                    "elements": [
                        {"kind": "math", "op": "MOV", "dest": "B", "source_a": "A", "source_b": ""},
                    ],
                },
                {
                    "id": "2",
                    "elements": [
                        {
                            "kind": "math",
                            "op": "DIV",
                            "dest": "C",
                            "source_a": "A",
                            "source_b": "2",
                        },
                    ],
                },
            ],
        }
    )
    sim = ScanSimulator(ir)
    r = sim.scan_once()
    assert r["numbers"]["B"] == 10
    assert r["numbers"]["C"] == 5


def test_otl_otu_latch():
    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "rungs": [
                {
                    "id": "1",
                    "elements": [
                        {"kind": "contact", "var": "SET", "form": "NO"},
                        {"kind": "coil", "var": "MEM", "form": "set"},
                    ],
                },
                {
                    "id": "2",
                    "elements": [
                        {"kind": "contact", "var": "RST", "form": "NO"},
                        {"kind": "coil", "var": "MEM", "form": "reset"},
                    ],
                },
            ],
        }
    )
    sim = ScanSimulator(ir)
    sim.scan_once({"SET": True})
    assert sim.vars["MEM"] is True
    sim.scan_once({"SET": False})
    assert sim.vars["MEM"] is True
    sim.scan_once({"RST": True})
    assert sim.vars["MEM"] is False


def test_program_helpers_and_plcopen_round_trip():
    prog = empty_program()
    prog = add_math_rung(prog, contact_tag="EN", op="ADD", dest="N7_0", source_a="N7_0", source_b="1")
    prog = add_compare_rung(
        prog, contact_tag="EN", op="EQU", source_a="N7_0", source_b="1", coil_tag="HIT"
    )
    prog = add_latch_rung(prog, contact_tag="PB", coil_tag="MEM", latch=True)
    prog = add_latch_rung(prog, contact_tag="RST", coil_tag="MEM", latch=False)
    txt = format_plc_text(prog["rungs"])
    assert "ADD[" in txt and "EQU[" in txt and "(S)MEM" in txt

    # dict round-trip keeps elements
    again = program_from_dict(program_to_dict(prog))
    assert again["rungs"][0]["elements"][1]["kind"] == "math"
    assert again["rungs"][2]["elements"][-1]["form"] == "set"

    ir = program_to_ladder_ir(prog)
    xml = ladder_ir_to_plcopen_xml(ir)
    assert "ADD" in xml and "EQU" in xml
    back = plcopen_xml_to_ladder_ir(xml)
    kinds = [e["kind"] for e in back["rungs"][0]["elements"]]
    assert "math" in kinds
    assert back["rungs"][2]["elements"][-1]["form"] == "set"
