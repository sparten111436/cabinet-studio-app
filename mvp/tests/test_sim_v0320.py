"""v0.3.20 simulation: rung-by-rung run, real-second timers, edit-while-running state carry."""

from __future__ import annotations

from cabinet_studio import __version__
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.programming import add_rung_from_elements, empty_program


def C(tag, nc=False):
    return {"kind": "contact", "var": tag, "form": "NC" if nc else "NO"}


def O(tag):
    return {"kind": "coil", "var": tag, "form": "normal"}


def TON(tag, pt_ms, block="TON"):
    return {"kind": "timer", "var": tag, "block": block, "pt_ms": pt_ms}


def CTU(tag, pv):
    return {"kind": "counter", "var": tag, "block": "CTU", "pv": pv}


def _prog(*rungs):
    prog = empty_program()
    for els in rungs:
        prog = add_rung_from_elements(prog, list(els))
    return prog


def _sim(prog):
    return ScanSimulator.from_program(prog, cycle_ms=100)


def test_version_is_0320():
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 20)


def test_scan_rung_runs_one_rung_at_a_time_and_a_pass_is_one_scan():
    sim = _sim(_prog([C("A"), O("B")], [C("B"), O("C")], [C("C"), O("D")]))
    sim.set_force("A", True)
    r = sim.scan_rung(0)
    assert r["rung_index"] == 0 and r["next_rung"] == 1
    assert sim.read("B") and not sim.read("C") and not sim.read("D")
    assert r["scan_count"] == 0
    r = sim.scan_rung(sim.rung_cursor)
    assert sim.read("C") and not sim.read("D")
    r = sim.scan_rung(sim.rung_cursor)
    assert sim.read("D")
    assert r["rung_index"] == 2 and r["next_rung"] == 0 and r["scan_count"] == 1
    assert sim.rung_cursor == 0


def test_scan_rung_keeps_other_rungs_highlights_and_replaces_its_own():
    prog = _prog([C("A"), O("B")], [C("X"), O("Y")])
    sim = _sim(prog)
    sim.scan_once()
    r0, r1 = (r["id"] for r in prog["rungs"])
    assert any(k.startswith(r1 + "|") for k in sim.power_flow)
    sim.set_force("A", True)
    sim.scan_rung(0)
    assert any(k.startswith(r1 + "|") for k in sim.power_flow)  # rung 2 not re-run, still shown
    assert sim.last_energized[r0] is True


def test_scan_rung_on_empty_program_is_harmless():
    sim = _sim(empty_program())
    r = sim.scan_rung(5)
    assert r["rung_index"] == -1 and r["next_rung"] == 0


def test_clock_timer_counts_real_seconds_between_its_own_evaluations():
    sim = _sim(_prog([C("A"), TON("T1", 3000)], [C("T1.DN"), O("Lamp")]))
    sim.set_force("A", True)
    sim.clock_ms = 10_000.0
    sim.scan_once()
    assert sim.timers["T1"]["acc_ms"] == 0 and sim.timers["T1"]["tt"]  # start scan adds 0
    sim.clock_ms = 11_000.0
    sim.scan_once()
    assert sim.timers["T1"]["acc_ms"] == 1000 and not sim.read("Lamp")
    sim.clock_ms = 13_250.0
    sim.scan_once()
    assert sim.timers["T1"]["q"] and sim.read("Lamp")
    sim.set_force("A", False)
    sim.clock_ms = 14_000.0
    sim.scan_once()
    assert sim.timers["T1"]["acc_ms"] == 0 and not sim.read("Lamp")


def test_clock_timer_restart_does_not_count_the_time_it_was_off():
    sim = _sim(_prog([C("A"), TON("T1", 5000)]))
    sim.set_force("A", True)
    sim.clock_ms = 0.0
    sim.scan_once()
    sim.clock_ms = 2000.0
    sim.scan_once()
    sim.set_force("A", False)
    sim.clock_ms = 3000.0
    sim.scan_once()
    sim.set_force("A", True)
    sim.clock_ms = 60_000.0
    sim.scan_once()
    assert sim.timers["T1"]["acc_ms"] == 0 and not sim.timers["T1"]["q"]


def test_five_second_timer_takes_five_real_seconds_at_one_second_per_rung():
    rungs = [[C("A"), TON("T1", 5000)]] + [[C(f"X{i}"), O(f"Y{i}")] for i in range(3)]
    sim = _sim(_prog(*rungs))
    sim.set_force("A", True)
    t = 0.0
    done_at = None
    for _ in range(40):
        sim.clock_ms = t
        sim.scan_rung(sim.rung_cursor)
        if sim.timers["T1"]["q"] and done_at is None:
            done_at = t
        t += 1000.0
    # 4 rungs at 1 s: the timer rung runs at t=0,4,8 s -> DN when checked at 8 s (>= 5 s).
    assert done_at == 8000.0


def test_tof_with_clock_holds_for_its_preset():
    sim = _sim(_prog([C("A"), TON("T2", 2000, block="TOF")]))
    sim.set_force("A", True)
    sim.clock_ms = 0.0
    sim.scan_once()
    assert sim.timers["T2"]["q"]
    sim.set_force("A", False)
    sim.clock_ms = 500.0
    sim.scan_once()
    assert sim.timers["T2"]["q"] and sim.timers["T2"]["acc_ms"] == 0
    sim.clock_ms = 1500.0
    sim.scan_once()
    assert sim.timers["T2"]["q"]
    sim.clock_ms = 2600.0
    sim.scan_once()
    assert not sim.timers["T2"]["q"]


def test_without_clock_timers_keep_legacy_cycle_ms():
    sim = _sim(_prog([C("A"), TON("T1", 1000)]))
    sim.set_force("A", True)
    sim.scan_once()
    sim.scan_once()
    assert sim.timers["T1"]["acc_ms"] == 200


def test_adopt_state_carries_values_timers_counters_and_forces_after_an_edit():
    before = _prog([C("A"), TON("T1", 5000)], [C("PE"), CTU("C1", 5)], [C("Gone"), O("Old")])
    old = _sim(before)
    old.set_force("A", True)
    old.set_force("Gone", True)
    old.clock_ms = 0.0
    old.scan_once()
    old.clock_ms = 1500.0
    old.scan_once()
    for _ in range(3):
        old.set_force("PE", True)
        old.scan_once()
        old.set_force("PE", False)
        old.scan_once()
    assert old.counters["C1"]["acc"] == 3 and old.timers["T1"]["acc_ms"] == 1500
    old.rung_cursor = 1
    # Edit: drop the "Gone" rung, lower the counter preset, add a new rung.
    after = _prog([C("A"), TON("T1", 5000)], [C("PE"), CTU("C1", 2)], [C("New"), O("Lamp")])
    after["rungs"][0]["id"] = before["rungs"][0]["id"]
    new = _sim(after)
    new.adopt_state(old)
    assert new.forces == {"A": True, "PE": False}
    assert "Gone" not in new.forces
    assert new.timers["T1"]["acc_ms"] == 1500
    assert new.counters["C1"]["acc"] == 3 and new.counters["C1"]["dn"]  # DN re-checked vs new PV
    assert new.rung_cursor == 1 and new.scan_count == old.scan_count
    new.clock_ms = 2500.0
    new.scan_once()
    assert new.timers["T1"]["acc_ms"] == 2500  # keeps counting real time across the edit


def test_adopt_state_drops_highlights_of_changed_rungs_only():
    before = _prog([C("A"), O("B")], [C("X"), O("Y")])
    old = _sim(before)
    old.scan_once()
    after = _prog([C("A"), O("B")], [C("X"), C("Z"), O("Y")])
    for i in range(2):
        after["rungs"][i]["id"] = before["rungs"][i]["id"]
    new = _sim(after)
    new.adopt_state(old)
    r0, r1 = before["rungs"][0]["id"], before["rungs"][1]["id"]
    assert any(k.startswith(r0 + "|") for k in new.power_flow)
    assert not any(k.startswith(r1 + "|") for k in new.power_flow)


def test_reset_instruction_zeroes_timers_and_counters():
    sim = _sim(_prog([C("A"), TON("T1", 300)], [C("PE"), CTU("C1", 1)]))
    sim.set_force("A", True)
    sim.set_force("PE", True)
    for _ in range(5):
        sim.scan_once()
    assert sim.timers["T1"]["q"] and sim.counters["C1"]["dn"]
    assert sim.reset_instruction("T1") and sim.timers["T1"]["acc_ms"] == 0 and not sim.read("T1")
    assert sim.reset_instruction("C1.DN") and sim.counters["C1"]["acc"] == 0 and not sim.read("C1")
    assert not sim.reset_instruction("A")
