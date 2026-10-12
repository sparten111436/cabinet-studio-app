"""v0.3.6 live power-flow map (Studio/TIA online-monitor style highlighting)."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import IR_FORMAT
from cabinet_studio.services.ladder_sim import ScanSimulator, program_rung_flow_keys
from cabinet_studio.services.programming import add_rung, empty_program


def _ir(elements, rid="r1"):
    return {"format": IR_FORMAT, "version": 1, "rungs": [{"id": rid, "elements": elements}]}


def test_series_flow_in_cond_out():
    sim = ScanSimulator(_ir([
        {"kind": "contact", "var": "A", "form": "NO"},
        {"kind": "contact", "var": "B", "form": "NC"},
        {"kind": "coil", "var": "Y", "form": "normal"},
    ]))
    flow = sim.scan_once()["power_flow"]  # A=0, B=0
    assert flow["r1|L|0"] == {"in": True, "cond": False, "out": False}
    # NC contact with B=0 is TRUE (conducts) even though no power reaches it.
    assert flow["r1|L|1"] == {"in": False, "cond": True, "out": False}
    assert flow["r1|L|2"]["in"] is False
    sim.set_force("A", True)
    flow = sim.scan_once()["power_flow"]
    assert flow["r1|L|1"]["out"] is True and flow["r1|L|2"]["in"] is True


def test_or_branch_flow_keys():
    sim = ScanSimulator(_ir([
        {"kind": "or", "branches": [
            [{"kind": "contact", "var": "Start", "form": "NO"}],
            [{"kind": "contact", "var": "Motor", "form": "NO"}],
        ]},
        {"kind": "contact", "var": "Stop", "form": "NC"},
        {"kind": "coil", "var": "Motor", "form": "normal"},
    ]))
    sim.set_force("Start", True)
    flow = sim.scan_once()["power_flow"]
    assert flow["r1|L|0|b0|0"]["out"] is True
    assert flow["r1|L|0|b1|0"]["out"] is False
    assert flow["r1|L|0"]["out"] is True
    assert flow["r1|L|2"]["in"] is True
    sim.set_force("Start", False)
    flow = sim.scan_once()["power_flow"]  # sealed in via Motor branch
    assert flow["r1|L|0|b1|0"]["out"] is True and flow["r1|L|2"]["in"] is True


def test_compare_flow_cond():
    sim = ScanSimulator(_ir([
        {"kind": "compare", "op": "GEQ", "source_a": "Level", "source_b": "5"},
        {"kind": "coil", "var": "High", "form": "normal"},
    ]))
    sim.set_number("Level", 7)
    flow = sim.scan_once()["power_flow"]
    assert flow["r1|L|0"]["cond"] is True and flow["r1|L|1"]["in"] is True


def test_classic_rung_keys_match_scan_flow():
    prog = add_rung(
        empty_program(),
        contact_tag="",
        coil_tag="M1",
        parallel=[[{"tag": "Start", "normally_closed": False}], [{"tag": "M1", "normally_closed": False}]],
        series=[{"tag": "Stop", "normally_closed": True}, {"tag": "ES", "normally_closed": True}],
    )
    rung = prog["rungs"][0]
    keys = program_rung_flow_keys(rung)
    sim = ScanSimulator.from_program(prog)
    sim.set_force("Start", True)
    flow = sim.scan_once()["power_flow"]
    for key in list(keys["parallel"].values()) + list(keys["series"].values()) + [keys["coil"], keys["or"]]:
        assert key in flow, key
    assert flow[keys["coil"]]["in"] is True
    assert flow[keys["series"][1]]["cond"] is True


def test_classic_single_branch_keys():
    prog = add_rung(empty_program(), contact_tag="A", coil_tag="Y")
    keys = program_rung_flow_keys(prog["rungs"][0])
    rid = prog["rungs"][0]["id"]
    assert keys["parallel"][(0, 0)] == f"{rid}|L|0"
    assert keys["coil"] == f"{rid}|L|1"
    assert keys["or"] is None


def test_flow_cleared_on_reset_and_energized_paths_kept():
    sim = ScanSimulator(_ir([{"kind": "contact", "var": "A", "form": "NC"}, {"kind": "coil", "var": "Y"}]))
    r = sim.scan_once()
    assert r["energized_paths"]["r1"] is True and r["power_flow"]
    sim.reset()
    assert sim.power_flow == {}
