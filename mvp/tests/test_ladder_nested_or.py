"""Nested OR branches + mid-rung coils (v0.3.4): IR, sim, text, PLCopen."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import (
    clean_elements,
    elements_have_mid_rung_coil,
    elements_have_nested_or,
    ladder_ir_to_program,
    normalize_ladder_ir,
    program_to_ladder_ir,
)
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.plcopen_xml import (
    ladder_ir_to_plcopen_xml,
    plcopen_xml_to_ladder_ir,
)
from cabinet_studio.services.programming import (
    add_mid_coil_rung,
    add_nested_or_rung,
    empty_program,
    format_ladder_txt,
    format_plc_text,
    program_from_dict,
    program_to_dict,
)


def _nested_or_elements():
    # A -- ( B  OR  ( C -- ( D OR E ) ) ) -- (OUT)
    return [
        {"kind": "contact", "var": "A", "form": "NO"},
        {
            "kind": "or",
            "branches": [
                [{"kind": "contact", "var": "B", "form": "NO"}],
                [
                    {"kind": "contact", "var": "C", "form": "NO"},
                    {
                        "kind": "or",
                        "branches": [
                            [{"kind": "contact", "var": "D", "form": "NO"}],
                            [{"kind": "contact", "var": "E", "form": "NO"}],
                        ],
                    },
                ],
            ],
        },
        {"kind": "coil", "var": "OUT", "form": "normal"},
    ]


def _mid_coil_elements():
    return [
        {"kind": "contact", "var": "A", "form": "NO"},
        {"kind": "coil", "var": "M", "form": "normal"},
        {"kind": "contact", "var": "B", "form": "NO"},
        {"kind": "coil", "var": "C", "form": "normal"},
    ]


def test_normalize_preserves_nested_or():
    ir = normalize_ladder_ir(
        {"format": "cabinet-studio-ladder", "rungs": [{"id": "1", "elements": _nested_or_elements()}]}
    )
    els = ir["rungs"][0]["elements"]
    assert elements_have_nested_or(els)
    assert els[1]["branches"][1][1]["kind"] == "or"
    assert els[1]["branches"][1][1]["branches"][0][0]["var"] == "D"


def test_normalize_preserves_mid_rung_coil():
    ir = normalize_ladder_ir(
        {"format": "cabinet-studio-ladder", "rungs": [{"id": "1", "elements": _mid_coil_elements()}]}
    )
    els = ir["rungs"][0]["elements"]
    assert elements_have_mid_rung_coil(els)
    kinds = [e["kind"] for e in els]
    assert kinds == ["contact", "coil", "contact", "coil"]


def test_nested_or_scan_semantics():
    ir = normalize_ladder_ir(
        {"format": "cabinet-studio-ladder", "rungs": [{"id": "1", "elements": _nested_or_elements()}]}
    )
    sim = ScanSimulator(ir)
    assert sim.scan_once({"A": True, "B": True})["vars"]["OUT"] is True
    assert sim.scan_once({"A": True, "B": False, "C": True, "D": True})["vars"]["OUT"] is True
    assert sim.scan_once({"A": True, "B": False, "C": True, "D": False, "E": True})["vars"]["OUT"] is True
    assert sim.scan_once({"A": True, "B": False, "C": True, "D": False, "E": False})["vars"]["OUT"] is False
    assert sim.scan_once({"A": False, "B": True})["vars"]["OUT"] is False


def test_mid_rung_coil_scan_passthrough():
    """CCW/Logix-style: coil does not clear continuity for later contacts."""
    ir = normalize_ladder_ir(
        {"format": "cabinet-studio-ladder", "rungs": [{"id": "1", "elements": _mid_coil_elements()}]}
    )
    sim = ScanSimulator(ir)
    r = sim.scan_once({"A": True, "B": False})
    assert r["vars"]["M"] is True
    assert r["vars"]["C"] is False
    r = sim.scan_once({"A": True, "B": True})
    assert r["vars"]["M"] is True
    assert r["vars"]["C"] is True
    r = sim.scan_once({"A": False, "B": True})
    assert r["vars"]["M"] is False
    assert r["vars"]["C"] is False


def test_program_helpers_round_trip():
    prog = add_nested_or_rung(
        empty_program(),
        lead_tag="A",
        or_branches=[
            [{"tag": "B", "normally_closed": False}],
            [
                {"tag": "C", "normally_closed": False},
                {
                    "kind": "or",
                    "branches": [
                        [{"kind": "contact", "var": "D", "form": "NO"}],
                        [{"kind": "contact", "var": "E", "form": "NO"}],
                    ],
                },
            ],
        ],
        coil_tag="OUT",
        comment="nested demo",
    )
    assert prog["rungs"][0].get("elements")
    data = program_to_dict(prog)
    back = program_from_dict(data)
    assert back["rungs"][0].get("elements")
    ir = program_to_ladder_ir(back)
    assert elements_have_nested_or(ir["rungs"][0]["elements"])

    mid = add_mid_coil_rung(
        empty_program(),
        contact_tag="A",
        mid_coil_tag="M",
        after_contact_tag="B",
        coil_tag="C",
    )
    assert mid["rungs"][0].get("elements") or mid["rungs"][0].get("mid_coils")
    ir2 = program_to_ladder_ir(mid)
    assert elements_have_mid_rung_coil(ir2["rungs"][0]["elements"])
    text = format_plc_text(mid["rungs"])
    assert "M" in text and "C" in text
    assert "Mid-rung" in format_ladder_txt(mid) or "M" in format_ladder_txt(mid)


def test_plcopen_nested_or_and_mid_coil_round_trip():
    ir = normalize_ladder_ir(
        {
            "format": "cabinet-studio-ladder",
            "meta": {"project": "NestDemo"},
            "rungs": [
                {"id": "1", "comment": "nested", "elements": _nested_or_elements()},
                {"id": "2", "comment": "mid", "elements": _mid_coil_elements()},
            ],
        }
    )
    xml = ladder_ir_to_plcopen_xml(ir)
    assert "cabinet-studio-elements:" in xml
    assert "OUT" in xml and "M" in xml
    back = plcopen_xml_to_ladder_ir(xml)
    assert len(back["rungs"]) == 2
    assert elements_have_nested_or(back["rungs"][0]["elements"])
    assert elements_have_mid_rung_coil(back["rungs"][1]["elements"])
    # Semantics survive the trip
    sim = ScanSimulator(back)
    assert sim.scan_once({"A": True, "B": True})["vars"]["OUT"] is True
    # Second rung M/C — forces apply across whole program
    sim2 = ScanSimulator(normalize_ladder_ir({"format": "cabinet-studio-ladder", "rungs": [back["rungs"][1]]}))
    r = sim2.scan_once({"A": True, "B": True})
    assert r["vars"]["M"] is True and r["vars"]["C"] is True


def test_ir_program_ir_keeps_nested_structure():
    ir = normalize_ladder_ir(
        {"format": "cabinet-studio-ladder", "rungs": [{"id": "1", "elements": _nested_or_elements()}]}
    )
    prog = ladder_ir_to_program(ir)
    assert prog["rungs"][0].get("elements")
    again = program_to_ladder_ir(prog)
    assert elements_have_nested_or(again["rungs"][0]["elements"])
    assert clean_elements(again["rungs"][0]["elements"])[1]["branches"][1][1]["kind"] == "or"
