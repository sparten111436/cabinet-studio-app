"""Tests for educational scan simulator."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import program_to_ladder_ir
from cabinet_studio.services.ladder_sim import ScanSimulator, scan_once


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


def test_scan_start_seal_in_and_stop():
    sim = ScanSimulator.from_program(_seal_in_program())
    # Idle: stop/estop NC contacts need TRUE physical = not pressed.
    # Convention: tag TRUE means device actuated. NC contact conducts when tag FALSE.
    # So PB_Stop=False, ES1=False means buttons not pressed → NC conducts.
    r = sim.scan_once({"PB_Start": False, "PB_Stop": False, "ES1": False})
    assert r["vars"]["CR1"] is False

    # Press start
    r = sim.scan_once({"PB_Start": True})
    assert r["vars"]["CR1"] is True

    # Release start — seal-in holds
    r = sim.scan_once({"PB_Start": False})
    assert r["vars"]["CR1"] is True
    assert r["energized_paths"]["r1"] is True

    # Press stop (NC opens when Stop tag TRUE)
    r = sim.scan_once({"PB_Stop": True})
    assert r["vars"]["CR1"] is False


def test_scan_once_helper():
    ir = program_to_ladder_ir(_seal_in_program())
    result = scan_once(ir, {"PB_Start": True, "PB_Stop": False, "ES1": False})
    assert result["vars"]["CR1"] is True
    assert result["scan_count"] == 1


def test_force_wins_over_coil():
    sim = ScanSimulator.from_program(_seal_in_program())
    sim.set_force("CR1", False)
    r = sim.scan_once({"PB_Start": True, "PB_Stop": False, "ES1": False})
    # Force keeps CR1 false even though path energized
    assert r["vars"]["CR1"] is False
