"""Draftsman FAIL deltas for weld-place-cell."""
from __future__ import annotations

import json
import re
from pathlib import Path

from cabinet_studio.services.drawings import (
    _disconnect_load_wires,
    _rung_is_stub,
    box_hover_detail,
    build_sheets,
    render_svg,
    write_drawings,
)
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.project_store import project_from_dict

_ROOT = Path(__file__).resolve().parents[2]
_CANDIDATES = [
    _ROOT / "saves" / "weld-place-cell.cabinet.json",
    Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\weld-place-cell.cabinet.json"),
]
CABINET = next((p for p in _CANDIDATES if p.is_file()), _CANDIDATES[0])


def _raw():
    return json.loads(CABINET.read_text(encoding="utf-8"))


def _proj():
    return project_from_dict(_raw())


def test_r2_pause_not_in_cycle_seal():
    rungs = _raw()["program"]["rungs"]
    assert len(rungs) >= 5
    r2 = rungs[1]
    assert r2["coil_tag"] == "Cycle_Active"
    assert not any(c["tag"] == "Pause_Active" for c in r2["series"])
    assert any(c["tag"] == "Pause_Active" for c in rungs[3]["series"])
    assert any(c["tag"] == "Pause_Active" for c in rungs[4]["series"])
    assert "Pause must NOT clear Cycle_Active" in r2["comment"]


def test_disc_load_wires_are_w_numbers():
    assert _disconnect_load_wires(_proj()) == ["W101", "W102"]


def test_sh8_sh9_on_rails_with_from_to(tmp_path):
    proj = _proj()
    lib = load_library()
    sheets = build_sheets(proj, lib)
    control = [s for s in sheets if s.kind == "control"]
    assert len(control) >= 2
    # Find sheets by device tags rather than hard-coded sheet numbers (layout/outline count may shift).
    sh_start = next(s for s in control if any(b.tag == "HS_START" for b in s.boxes))
    sh_weld = next(s for s in control if any(b.tag == "Welder_Relay" for b in s.boxes))
    sh_sr = next(s for s in control if any(b.tag == "SR1" for b in s.boxes))
    power = next(s for s in sheets if s.kind == "power" and any(b.tag == "PSU1" for b in s.boxes))

    assert any(b.tag == "HS_STOP" for b in sh_start.boxes)
    assert not any(_rung_is_stub(b, proj) for b in sh_start.boxes if b.tag in {"ES1", "Admin_Reset", "HS_START", "HS_STOP"})
    assert not any(_rung_is_stub(b, proj) for b in sh_weld.boxes if b.tag in {"Arm_Deployed", "Light_Curtain"})

    svg_start = render_svg(sh_start, proj)
    svg_weld = render_svg(sh_weld, proj)
    svg_sr = render_svg(sh_sr, proj)
    svg_psu = render_svg(power, proj)

    assert 'data-wire="+24V"' in svg_start
    assert 'data-wire="+24V"' in svg_weld
    # Wire refs are hover-only now.
    assert 'class="wire-refs"' not in svg_start
    assert 'class="wire-refs"' not in svg_weld
    hs_stop = next(b for b in sh_start.boxes if b.tag == "HS_STOP")
    tip_stop = box_hover_detail(hs_stop)
    assert "W109" in tip_stop or any(r.wire == "W109" for r in hs_stop.connections)
    assert "DI1" in tip_stop or any("DI1" in r.to_label or "DI1" in r.from_label for r in hs_stop.connections)
    weld = next(b for b in sh_weld.boxes if b.tag == "Welder_Relay")
    tip_weld = box_hover_detail(weld)
    assert "W114" in tip_weld or any(r.wire == "W114" for r in weld.connections)
    assert "DO1" in tip_weld or any("DO1" in (r.to_label + r.from_label) for r in weld.connections)
    sr = next(b for b in sh_sr.boxes if b.tag == "SR1")
    tip_sr = box_hover_detail(sr)
    assert "W107" in tip_sr or any(r.wire == "W107" for r in sr.connections)
    assert 'data-tag="DO1"' in svg_sr or any(b.tag == "DO1" for b in sh_sr.boxes)
    psu = next(b for b in power.boxes if b.tag == "PSU1")
    tip_psu = box_hover_detail(psu)
    assert "W102" in tip_psu or any(r.wire == "W102" for r in psu.connections)
    assert "DISC" in tip_psu or any("DISC" in (r.to_label + r.from_label) for r in psu.connections)
    assert "W102" in svg_psu  # still present on data-wire / titles
    write_drawings(proj, lib, tmp_path)
    assert list(tmp_path.glob("*control.svg"))


def test_ton_note_kept_in_program():
    prog = _raw()["program"]
    blob = json.dumps(prog)
    assert "TON" in blob
    assert len(prog["rungs"]) >= 5
    assert "not a structured rung type" in prog["rungs"][4]["comment"] or "TON" in prog["rungs"][4]["comment"]
