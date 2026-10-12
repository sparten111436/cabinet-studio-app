"""Tests for Cabinet Studio v3 ladder IR."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import (
    IR_FORMAT,
    ladder_ir_to_program,
    normalize_ladder_ir,
    program_to_ladder_ir,
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
                    {"tag": "ES1", "normally_closed": True},
                ],
                "coil_tag": "CR1",
                "coil_negated": False,
                "comment": "Seal-in start",
                "contact_tag": "PB_Start",
                "normally_closed": False,
            }
        ],
        "hmi_items": [],
        "plc_text": "",
        "hmi_text": "",
        "text_edited": False,
    }


def test_program_to_ir_seal_in():
    ir = program_to_ladder_ir(_seal_in_program(), project_name="Demo")
    assert ir["format"] == IR_FORMAT
    assert ir["meta"]["not_a_vendor_format"] is True
    assert len(ir["rungs"]) == 1
    kinds = [e["kind"] for e in ir["rungs"][0]["elements"]]
    assert kinds[0] == "or"
    assert kinds[-1] == "coil"
    assert ir["rungs"][0]["elements"][-1]["var"] == "CR1"


def test_ir_round_trip_program():
    original = _seal_in_program()
    ir = program_to_ladder_ir(original, project_name="Demo")
    back = ladder_ir_to_program(ir)
    assert len(back["rungs"]) == 1
    rung = back["rungs"][0]
    assert rung["coil_tag"] == "CR1"
    assert len(rung["parallel"]) == 2
    assert {c["tag"] for c in rung["series"]} == {"PB_Stop", "ES1"}


def test_normalize_rejects_garbage():
    try:
        normalize_ladder_ir("nope")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_variables_include_coil_as_output():
    ir = program_to_ladder_ir(_seal_in_program())
    by_name = {v["name"]: v for v in ir["variables"]}
    assert by_name["CR1"]["class"] == "output"
    assert by_name["PB_Start"]["class"] == "input"
