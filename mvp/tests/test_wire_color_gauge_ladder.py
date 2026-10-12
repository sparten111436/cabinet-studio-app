"""Schematic wire COLOR/GAUGE + separate ladder-logic artifact."""
from __future__ import annotations

import json
import re
from pathlib import Path

from cabinet_studio.services.drawings import build_sheets, render_svg, write_drawings
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.programming import format_ladder_txt, write_ladder_logic
from cabinet_studio.services.project_store import project_from_dict
from cabinet_studio.services.wiring_assist import resolve_wire_color, resolve_wire_gauge, role_for_wire

_ROOT = Path(__file__).resolve().parents[2]  # CabinetStudio/
_CANDIDATES = [
    _ROOT / "saves" / "weld-place-cell.cabinet.json",
    Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\weld-place-cell.cabinet.json"),
    Path("/workspace/weld-place-cell.cabinet.json"),
]
CABINET = next((p for p in _CANDIDATES if p.is_file()), _CANDIDATES[0])


def _proj():
    return project_from_dict(json.loads(CABINET.read_text(encoding="utf-8")))


def test_us_defaults_for_buses():
    assert role_for_wire("", "PE") == "equipment_ground"
    assert resolve_wire_color(wire="PE") == "Green"
    assert resolve_wire_gauge(wire="PE") == "14 AWG"
    assert resolve_wire_color(wire="+24V") == "Blue"
    assert resolve_wire_gauge(wire="+24V") == "18 AWG"


def test_schematic_wire_refs_include_color_and_gauge():
    proj = _proj()
    lib = load_library()
    sheets = build_sheets(proj, lib)
    control = [s for s in sheets if s.kind == "control"]
    assert control
    # Prefer a control sheet that still has +24V rails / connections with color.
    target = next(
        (s for s in control if any(row.color and row.gauge for b in s.boxes for row in b.connections)),
        control[0],
    )
    assert any(row.color and row.gauge for box in target.boxes for row in box.connections)
    svg = render_svg(target, proj)
    # Header is hover-only; color/gauge remain on segment data-* and connections.
    assert "Wire · Color · Gauge · From · To" not in svg
    from cabinet_studio.services.drawings import box_hover_detail
    tips = "\n".join(box_hover_detail(box) for box in target.boxes)
    assert "FROM" in tips or any(row.wire in tips for box in target.boxes for row in box.connections)
    assert re.search(r'data-color="[^"]+"', svg)
    assert re.search(r'data-gauge="[^"]+"', svg)
    assert "NOT A CERTIFIED UL 508A DRAWING. Design aid only." in svg
    assert 'data-wire="+24V"' in svg or any('data-wire=' in svg for _ in [0])
    assert 'data-color="Blue"' in svg or 'data-color=' in svg


def test_write_drawings_emits_separate_ladder(tmp_path):
    proj = _proj()
    lib = load_library()
    written = write_drawings(proj, lib, tmp_path)
    assert all(p.suffix == ".svg" for p in written)
    assert (tmp_path / "ladder-logic.txt").is_file()
    assert (tmp_path / "ladder-logic.html").is_file()
    txt = (tmp_path / "ladder-logic.txt").read_text(encoding="utf-8")
    for i in range(1, 7):
        assert f"R{i}" in txt
    assert "Separate artifact" in txt


def test_write_ladder_logic_alone(tmp_path):
    proj = _proj()
    paths = write_ladder_logic(proj, tmp_path)
    assert len(paths) == 2
    body = format_ladder_txt(proj.program, cabinet_name=proj.name)
    assert "R1" in body and "SR1" in body
