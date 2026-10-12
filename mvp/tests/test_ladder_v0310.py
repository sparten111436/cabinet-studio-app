"""v0.3.10: more educational AOI/FB templates; Watch/Trend pause + labels + CSV; OpenPLC note present."""

from __future__ import annotations

from pathlib import Path

from cabinet_studio import __version__
from cabinet_studio.services.ladder_ir import program_to_ladder_ir
from cabinet_studio.services.ladder_print import ladder_program_to_svg
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import (
    AOI_TEMPLATES,
    apply_aoi_template,
    expand_aoi_template,
    list_aoi_templates,
)
from cabinet_studio.services.ladder_tools import WatchTrendBuffer
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import add_aoi_template_rungs, empty_program, format_plc_text


NEW_TEMPLATES_0310 = {
    "ForwardReverse",
    "OffDelayStop",
    "PulseExtend",
    "TwoHandStart",
    "EstopInterlock",
    "ValveCycle",
    "BatchReset",
    "JogOrRun",
    "ScaleSetpoint",
}

LEGACY_TEMPLATES = {
    "MotorStarter",
    "TimedStart",
    "LatchPair",
    "CounterBatch",
    "LimitBand",
    "MaskedFlag",
}


def test_version_is_0310():
    # Batch version gate: 0.3.10 introduced AOI/Watch polish; 0.3.11 is the
    # correctness hotfix on top of that line.
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 10)  # strict: parsed, not a prefix match


def test_aoi_catalog_includes_legacy_and_new():
    names = {t["name"] for t in list_aoi_templates()}
    assert LEGACY_TEMPLATES <= names
    assert NEW_TEMPLATES_0310 <= names
    assert len(AOI_TEMPLATES) >= 15


def test_forward_reverse_expand_and_simulate():
    specs = expand_aoi_template(
        "ForwardReverse",
        {"fwd_pb": "PB_Fwd", "rev_pb": "PB_Rev", "stop": "PB_Stop", "fwd": "M_Fwd", "rev": "M_Rev"},
    )
    assert len(specs) == 2
    prog = apply_aoi_template(empty_program(), "ForwardReverse")
    ir = program_to_ladder_ir(prog)
    sim = ScanSimulator(ir)
    # NC Stop conducts when Stop tag is False (not pressed)
    r = sim.scan_once({"PB_Fwd": True, "PB_Stop": False, "PB_Rev": False})
    assert r["vars"].get("M_Fwd") is True
    assert r["vars"].get("M_Rev") is not True
    # Seal holds without PB
    r = sim.scan_once({"PB_Fwd": False, "PB_Stop": False, "PB_Rev": False})
    assert r["vars"].get("M_Fwd") is True
    # Stop pressed (True) opens NC → drops out
    r = sim.scan_once({"PB_Fwd": False, "PB_Stop": True, "PB_Rev": False})
    assert r["vars"].get("M_Fwd") is not True


def test_two_hand_and_estop_templates():
    prog = add_aoi_template_rungs(
        empty_program(),
        "TwoHandStart",
        {"left": "L", "right": "R", "stop": "S", "cycle": "CY"},
    )
    ir = program_to_ladder_ir(prog)
    sim = ScanSimulator(ir)
    # NC Stop: False = not pressed = path closed
    assert sim.scan_once({"L": True, "R": False, "S": False})["vars"].get("CY") is not True
    assert sim.scan_once({"L": True, "R": True, "S": False})["vars"].get("CY") is True

    prog2 = add_aoi_template_rungs(
        empty_program(),
        "EstopInterlock",
        {"start": "ST", "estop": "ES", "curtain": "LC", "run": "RUN"},
    )
    sim2 = ScanSimulator(program_to_ladder_ir(prog2))
    # ES/LC are NC: False = healthy (not tripped) so contact conducts
    assert sim2.scan_once({"ST": True, "ES": False, "LC": False})["vars"].get("RUN") is True
    assert sim2.scan_once({"ST": False, "ES": True, "LC": False})["vars"].get("RUN") is not True


def test_valve_cycle_batch_reset_scale_plcopen_print():
    prog = empty_program()
    prog = apply_aoi_template(prog, "ValveCycle")
    prog = apply_aoi_template(prog, "BatchReset", {"pulse": "P", "reset": "RST", "counter": "C1", "preset": "3", "done": "DONE"})
    prog = apply_aoi_template(prog, "ScaleSetpoint", {"enable": "EN", "raw": "Raw", "work": "Work", "scale": "2", "scaled": "Out"})
    assert len(prog.get("aoi_templates_used") or []) == 3
    txt = format_plc_text(prog["rungs"])
    assert "Place_Relay" in txt or "CTU[" in txt or "MOV[" in txt

    xml = export_program_to_plcopen_xml(prog, project_name="V0310")
    back = import_plcopen_xml_to_program(xml)
    assert len(back["rungs"]) >= 3
    svg, _w, _h = ladder_program_to_svg(back["rungs"])
    assert isinstance(svg, str) and len(svg) > 100
    assert "rect" in svg

    # BatchReset sim: 3 pulses → DN
    ir = program_to_ladder_ir(apply_aoi_template(empty_program(), "BatchReset", {
        "pulse": "P", "reset": "RST", "counter": "C1", "preset": "3", "done": "DONE",
    }))
    sim = ScanSimulator(ir)
    for _ in range(3):
        sim.scan_once({"P": False, "RST": False})
        sim.scan_once({"P": True, "RST": False})
    assert sim.scan_once({"P": False, "RST": False})["vars"].get("DONE") is True


def test_jog_or_run_and_pulse_extend_expand():
    specs = expand_aoi_template("JogOrRun")
    # v0.3.12: RunMode OTE seal + motor rung (2 rungs); non-retentive (no OTL).
    assert len(specs) == 2
    assert any(e.get("kind") == "or" for e in specs[0]["elements"])
    assert any(e.get("kind") == "or" for e in specs[1]["elements"])
    assert not any(
        e.get("kind") == "coil" and str(e.get("form") or "").lower() in {"set", "reset"}
        for s in specs for e in s["elements"]
    )
    specs2 = expand_aoi_template("PulseExtend")
    assert len(specs2) == 3
    kinds = [e.get("kind") for s in specs2 for e in s["elements"]]
    assert "oneshot" in kinds and "timer" in kinds


def test_off_delay_expand():
    specs = expand_aoi_template("OffDelayStop", {"enable": "Auto", "timer": "T1", "pt_ms": "1000", "output": "Fan"})
    assert len(specs) == 2
    assert any(e.get("block") == "TOF" for e in specs[0]["elements"] if e.get("kind") == "timer")
    # v0.3.11: enable alone feeds TOF (no output seal on timer IN).
    assert not any(e.get("kind") == "or" for e in specs[0]["elements"])


def test_watch_pause_labels_csv(tmp_path: Path):
    w = WatchTrendBuffer(capacity=10)
    w.add_tag("PB_Start", label="Start PB")
    w.add_tag("C1.ACC", label="Count ACC")
    assert w.series_label("PB_Start") == "Start PB"
    assert w.series_label("C1.ACC") == "Count ACC"

    for i in range(3):
        w.record({
            "vars": {"PB_Start": True},
            "numbers": {},
            "timers": {},
            "counters": {"C1": {"acc": i, "pre": 5, "dn": False}},
            "scan_count": i + 1,
        })
    assert len(w.samples) == 3

    w.pause()
    assert w.paused is True
    w.record({
        "vars": {"PB_Start": False},
        "numbers": {},
        "timers": {},
        "counters": {"C1": {"acc": 99, "pre": 5, "dn": False}},
        "scan_count": 99,
    })
    assert len(w.samples) == 3  # paused — no new sample
    assert w.series("C1.ACC")[-1] == 2.0

    w.resume()
    w.record({
        "vars": {"PB_Start": False},
        "numbers": {},
        "timers": {},
        "counters": {"C1": {"acc": 7, "pre": 5, "dn": False}},
        "scan_count": 4,
    })
    assert len(w.samples) == 4
    assert w.series("C1.ACC")[-1] == 7.0

    csv_text = w.to_csv()
    assert "Start PB" in csv_text and "Count ACC" in csv_text
    assert "PB_Start" in csv_text  # raw tag row when labels differ
    assert "NOT A CERTIFIED UL 508A DRAWING" in csv_text
    assert "NFPA 79" in csv_text
    out = w.export_csv(tmp_path / "watch.csv")
    assert Path(out).is_file()
    body = Path(out).read_text(encoding="utf-8")
    # v0.3.14 REG-4: header is row 1; design-aid notes are trailing comment rows
    import csv as _csv
    import io as _io
    lines = body.splitlines()
    assert lines[0].lower().startswith("scan")
    reader = _csv.DictReader(_io.StringIO(body))
    assert reader.fieldnames and reader.fieldnames[0].lower() == "scan"
    data = [r for r in reader if str(r.get("scan") or "") not in {"#", "#tag"} and not str(r.get("scan") or "").startswith("#")]
    assert data, "DictReader saw no numeric sample rows"
    assert str(data[0]["scan"]).lstrip("-").isdigit()
    assert "NOT A CERTIFIED UL 508A DRAWING" in body.splitlines()[-2] or any(
        "NOT A CERTIFIED UL 508A DRAWING" in ln for ln in body.splitlines()[-3:]
    )

    assert w.toggle_pause() is True
    assert w.toggle_pause() is False


def test_openplc_runtime_research_note_exists():
    note = Path(__file__).resolve().parents[1] / "research" / "OPENPLC-RUNTIME-SIDECAR.md"
    assert note.is_file()
    text = note.read_text(encoding="utf-8")
    assert "MIT" in text
    assert "GPL" in text
    assert "sidecar" in text.lower()
    assert "Do not embed" in text or "do not embed" in text.lower()
