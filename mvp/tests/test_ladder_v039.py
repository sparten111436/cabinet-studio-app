"""v0.3.9: LIM/MEQ, bitwise AND/OR/XOR/NOT, richer CPT precedence, educational AOI templates."""

from __future__ import annotations

from cabinet_studio import __version__
from cabinet_studio.services.ladder_ir import (
    eval_cpt_expression,
    normalize_compare_op,
    normalize_ladder_ir,
    normalize_math_op,
    program_to_ladder_ir,
    to_dint,
)
from cabinet_studio.services.ladder_print import ladder_program_to_svg
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import (
    apply_aoi_template,
    expand_aoi_template,
    list_aoi_templates,
)
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import (
    add_aoi_template_rungs,
    add_compare_rung,
    add_math_rung,
    empty_program,
    format_plc_text,
)


def test_version_is_039():
    assert __version__.startswith("0.3.")


def test_lim_compare_band():
    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "variables": [{"name": "Level", "class": "numeric", "type": "DINT", "value": 50}],
            "rungs": [
                {
                    "id": "1",
                    "elements": [
                        {"kind": "contact", "var": "EN", "form": "NO"},
                        {
                            "kind": "compare",
                            "op": "LIM",
                            "source_a": "Level",
                            "source_b": "10",
                            "source_c": "90",
                        },
                        {"kind": "coil", "var": "OK", "form": "normal"},
                    ],
                }
            ],
        }
    )
    sim = ScanSimulator(ir)
    r = sim.scan_once({"EN": True})
    assert r["vars"]["OK"] is True
    sim.set_number("Level", 5)
    assert sim.scan_once({"EN": True})["vars"]["OK"] is False
    sim.set_number("Level", 95)
    assert sim.scan_once({"EN": True})["vars"]["OK"] is False
    sim.set_number("Level", 10)
    assert sim.scan_once({"EN": True})["vars"]["OK"] is True


def test_meq_masked_equals_hex():
    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "variables": [{"name": "Status", "class": "numeric", "type": "DINT", "value": 0x0005}],
            "rungs": [
                {
                    "id": "1",
                    "elements": [
                        {
                            "kind": "compare",
                            "op": "MEQ",
                            "source_a": "Status",
                            "source_b": "0x0001",
                            "source_c": "0x0001",
                        },
                        {"kind": "coil", "var": "Bit0", "form": "normal"},
                    ],
                }
            ],
        }
    )
    sim = ScanSimulator(ir)
    assert sim.scan_once()["vars"]["Bit0"] is True
    sim.set_number("Status", 0x0004)
    assert sim.scan_once()["vars"]["Bit0"] is False


def test_bitwise_and_or_xor_not():
    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "variables": [
                {"name": "A", "class": "numeric", "type": "DINT", "value": 0b1100},
                {"name": "B", "class": "numeric", "type": "DINT", "value": 0b1010},
                {"name": "D", "class": "numeric", "type": "DINT", "value": 0},
            ],
            "rungs": [
                {
                    "id": "1",
                    "elements": [
                        {"kind": "math", "op": "AND", "dest": "D", "source_a": "A", "source_b": "B"},
                    ],
                },
                {
                    "id": "2",
                    "elements": [
                        {"kind": "math", "op": "OR", "dest": "E", "source_a": "A", "source_b": "B"},
                    ],
                },
                {
                    "id": "3",
                    "elements": [
                        {"kind": "math", "op": "XOR", "dest": "F", "source_a": "A", "source_b": "B"},
                    ],
                },
                {
                    "id": "4",
                    "elements": [
                        {"kind": "math", "op": "NOT", "dest": "G", "source_a": "A", "source_b": ""},
                    ],
                },
            ],
        }
    )
    r = ScanSimulator(ir).scan_once()
    assert r["numbers"]["D"] == float(0b1000)
    assert r["numbers"]["E"] == float(0b1110)
    assert r["numbers"]["F"] == float(0b0110)
    assert r["numbers"]["G"] == float(to_dint(~to_dint(0b1100)))


def test_cpt_precedence_parens_and_unary():
    assert eval_cpt_expression("2+3*4", float) == 14
    assert eval_cpt_expression("(2+3)*4", float) == 20
    assert eval_cpt_expression("10-3-2", float) == 5  # left-assoc
    assert eval_cpt_expression("-5+2", float) == -3
    assert eval_cpt_expression("A*(B+C/2)", lambda t: {"A": 2, "B": 3, "C": 8}[t]) == 14

    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "variables": [
                {"name": "A", "class": "numeric", "type": "REAL", "value": 2},
                {"name": "B", "class": "numeric", "type": "REAL", "value": 3},
                {"name": "C", "class": "numeric", "type": "REAL", "value": 4},
            ],
            "rungs": [
                {
                    "id": "1",
                    "elements": [
                        {
                            "kind": "math",
                            "op": "CPT",
                            "dest": "Out",
                            "expression": "A*(B+C)",
                        }
                    ],
                }
            ],
        }
    )
    assert ScanSimulator(ir).scan_once()["numbers"]["Out"] == 14


def test_aoi_templates_expand_and_simulate():
    names = {t["name"] for t in list_aoi_templates()}
    assert {"MotorStarter", "TimedStart", "LatchPair", "CounterBatch", "LimitBand", "MaskedFlag"} <= names
    specs = expand_aoi_template("MotorStarter", {"start": "PB_Start", "stop": "PB_Stop", "motor": "M1"})
    assert len(specs) == 1
    assert any(e.get("kind") == "or" for e in specs[0]["elements"])

    prog = empty_program()
    prog = add_aoi_template_rungs(prog, "LimitBand", {
        "enable": "EN", "test": "Level", "low": "10", "high": "90", "ok": "InBand",
    })
    assert len(prog["rungs"]) == 1
    ir = program_to_ladder_ir(prog)
    # seed Level
    for v in ir.get("variables") or []:
        if v.get("name") == "Level":
            v["value"] = 50
    # add Level via numbers after construct
    sim = ScanSimulator(ir)
    sim.set_number("Level", 50)
    assert sim.scan_once({"EN": True})["vars"].get("InBand") is True


def test_plcopen_roundtrip_lim_bitwise_cpt_aoi():
    prog = empty_program()
    prog = add_math_rung(prog, contact_tag="EN", op="AND", dest="MaskOut", source_a="0x00FF", source_b="0x00F0")
    prog = add_math_rung(
        prog, contact_tag="EN", op="CPT", dest="Scaled", source_a="", source_b="", expression="(A+B)*2"
    )
    prog = add_compare_rung(
        prog, contact_tag="EN", op="LIM", source_a="Level", source_b="0", source_c="100", coil_tag="OK"
    )
    prog = apply_aoi_template(prog, "LatchPair", {"set": "S", "reset": "R", "memory": "MEM"})
    txt = format_plc_text(prog["rungs"])
    assert "LIM[" in txt and "AND[" in txt and "CPT[" in txt and "(S)MEM" in txt

    xml = export_program_to_plcopen_xml(prog, project_name="V039")
    assert "LIM" in xml and "AND" in xml
    back = import_plcopen_xml_to_program(xml)
    ops = []
    for rung in back["rungs"]:
        for el in rung.get("elements") or []:
            if el.get("kind") == "compare":
                ops.append(el.get("op"))
                assert el.get("source_c") == "100" or el.get("op") != "LIM"
            if el.get("kind") == "math":
                ops.append(el.get("op"))
    assert "LIM" in ops and "AND" in ops and "CPT" in ops

    svg, _w, _h = ladder_program_to_svg(back["rungs"])
    assert "LIM" in svg


def test_normalize_aliases_039():
    assert normalize_compare_op("LIMIT") == "LIM"
    assert normalize_compare_op("MASK_EQ") == "MEQ"
    assert normalize_math_op("&") == "AND"
    assert normalize_math_op("~") == "NOT"
