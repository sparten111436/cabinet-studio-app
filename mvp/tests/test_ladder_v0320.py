"""v0.3.20 ladder import: OR branch order follows the file on a hint-less import."""

from __future__ import annotations

import re

import pytest

from cabinet_studio.services.ladder_ir import program_to_ladder_ir
from cabinet_studio.services.plcopen_xml import export_program_to_plcopen_xml, import_plcopen_xml_to_program_checked
from cabinet_studio.services.programming import add_rung_from_elements, empty_program, program_from_dict


def C(tag, nc=False):
    return {"kind": "contact", "var": tag, "form": "NC" if nc else "NO"}


def OR(*branches):
    return {"kind": "or", "branches": [list(b) for b in branches]}


def O(tag):
    return {"kind": "coil", "var": tag, "form": "normal"}


def _elements(prog):
    return program_to_ladder_ir(program_from_dict(prog))["rungs"][0]["elements"]


@pytest.mark.parametrize(
    "els",
    [
        # fuzz seed 298084: a branch opening with a nested OR came back first
        [OR([C("Y")], [OR([C("X4")], [C("PB_Stop")]), C("X1")]), O("Y1")],
        [OR([C("Y"), C("M1"), C("X4", True)], [OR([C("X4")], [C("PB_Stop")]), C("X1")]), O("Y1")],
        [C("X1"), {"kind": "compare", "op": "GRT", "source_a": "D", "source_b": "9"},
         OR([C("Y"), C("M1"), C("X4", True)], [OR([C("X4")], [C("PB_Stop")]), C("X1")]),
         {"kind": "oneshot", "block": "ONS", "var": "ONS1"}, O("Y1")],
        [OR([OR([C("A")], [C("B")]), C("C")], [C("D")]), O("Y")],
        [OR([C("D")], [OR([C("A")], [C("B")]), C("C")], [C("E")]), O("Y")],
    ],
)
def test_hintless_round_trip_keeps_or_branch_order(els):
    prog = add_rung_from_elements(empty_program(), els)
    xml = re.sub(r"cabinet-studio-elements:[^<]*", "", export_program_to_plcopen_xml(prog, project_name="T"))
    back, _warnings = import_plcopen_xml_to_program_checked(xml)
    assert _elements(back) == _elements(prog)


# --------------------------------------------- OR-into-OR join with one wire deleted
CROSS = [OR([C("A")], [C("B")], [C("E")]), OR([C("Cx")], [C("Dx")]), O("Y")]


def _drop_first_wire_into(xml: str, tag: str) -> str:
    pat = (
        r'(<contact localId="\d+"[^>]*>(?:(?!</contact>).)*?)<connection refLocalId="\d+"/>'
        r'((?:(?!</contact>).)*?<variable>%s</variable>)' % re.escape(tag)
    )
    out, n = re.subn(pat, r"\1\2", xml, count=1, flags=re.S)
    assert n == 1
    return out


def test_full_or_into_or_join_still_imports_exactly():
    prog = add_rung_from_elements(empty_program(), CROSS)
    xml = export_program_to_plcopen_xml(prog, project_name="T")
    for variant in (xml, re.sub(r"cabinet-studio-elements:[^<]*", "", xml)):
        back, _w = import_plcopen_xml_to_program_checked(variant)
        assert _elements(back) == _elements(prog)


@pytest.mark.parametrize("hinted", [True, False])
@pytest.mark.parametrize("tag", ["Cx", "Dx"])
def test_or_into_or_join_with_a_deleted_wire_refuses(hinted, tag):
    """Fuzz seeds 298336 / 298395 (also in 0.3.19): the rebuilt rung repeated contacts and
    imported different logic. A partial cross-wiring is now refused, hint or no hint."""
    prog = add_rung_from_elements(empty_program(), CROSS)
    xml = export_program_to_plcopen_xml(prog, project_name="T")
    if not hinted:
        xml = re.sub(r"cabinet-studio-elements:[^<]*", "", xml)
    bad = _drop_first_wire_into(xml, tag)
    with pytest.raises(ValueError, match="cross-connected") as ei:
        import_plcopen_xml_to_program_checked(bad)
    assert "Nothing was imported" in str(ei.value) and tag in str(ei.value)
