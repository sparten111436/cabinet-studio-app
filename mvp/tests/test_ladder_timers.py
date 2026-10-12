"""Timer symbols + sim ACC/DN + IR round-trip."""

from __future__ import annotations

from cabinet_studio.services.ladder_ir import ladder_ir_to_program, program_to_ladder_ir
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.programming import add_timer_rung, empty_program, program_from_dict, program_to_dict


def _timer_program(block: str = "TON", pt_ms: int = 200):
    return add_timer_rung(
        empty_program(),
        contact_tag="PB_Start",
        timer_tag="T1",
        block=block,
        pt_ms=pt_ms,
        normally_closed=False,
        coil_tag="CR1",
        comment=f"{block} demo",
    )


def test_program_dict_preserves_timer():
    prog = _timer_program("TOF", 500)
    data = program_to_dict(prog)
    assert data["rungs"][0]["timer"]["tag"] == "T1"
    assert data["rungs"][0]["timer"]["block"] == "TOF"
    assert data["rungs"][0]["timer"]["pt_ms"] == 500
    back = program_from_dict(data)
    assert back["rungs"][0]["timer"]["block"] == "TOF"


def test_ir_round_trip_keeps_timer():
    prog = _timer_program("RTO", 150)
    ir = program_to_ladder_ir(prog, project_name="TimerDemo")
    kinds = [e["kind"] for e in ir["rungs"][0]["elements"]]
    assert "timer" in kinds
    assert "coil" in kinds
    tmr = next(e for e in ir["rungs"][0]["elements"] if e["kind"] == "timer")
    assert tmr["var"] == "T1"
    assert tmr["block"] == "RTO"
    assert tmr["pt_ms"] == 150
    back = ladder_ir_to_program(ir)
    assert back["rungs"][0]["timer"]["tag"] == "T1"
    assert back["rungs"][0]["timer"]["pt_ms"] == 150


def test_ton_reaches_dn():
    ir = program_to_ladder_ir(_timer_program("TON", 200))
    sim = ScanSimulator(ir, cycle_ms=50)
    r = sim.scan_once({"PB_Start": True})
    assert r["timers"]["T1"]["acc_ms"] == 50
    assert r["timers"]["T1"]["q"] is False
    for _ in range(3):
        r = sim.scan_once()
    assert r["timers"]["T1"]["q"] is True
    assert r["vars"]["T1"] is True
    # Drop IN — TON resets
    r = sim.scan_once({"PB_Start": False})
    assert r["timers"]["T1"]["q"] is False
    assert r["timers"]["T1"]["acc_ms"] == 0


def test_tof_holds_then_drops():
    ir = program_to_ladder_ir(_timer_program("TOF", 100))
    sim = ScanSimulator(ir, cycle_ms=50)
    r = sim.scan_once({"PB_Start": True})
    assert r["timers"]["T1"]["q"] is True
    r = sim.scan_once({"PB_Start": False})
    assert r["timers"]["T1"]["q"] is True  # still timing out
    r = sim.scan_once()
    assert r["timers"]["T1"]["q"] is False


def test_rto_retentive_acc():
    ir = program_to_ladder_ir(_timer_program("RTO", 200))
    sim = ScanSimulator(ir, cycle_ms=50)
    sim.scan_once({"PB_Start": True})
    sim.scan_once({"PB_Start": False})
    assert sim.timers["T1"]["acc_ms"] == 50  # retained
    assert sim.timers["T1"]["q"] is False
    for _ in range(3):
        sim.scan_once({"PB_Start": True})
    assert sim.timers["T1"]["q"] is True
