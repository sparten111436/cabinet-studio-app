"""Geometry parse/save helpers for canvas pop-out windows (no GUI)."""

from __future__ import annotations

import json

from cabinet_studio.ui.util import (
    format_geometry,
    geometry_is_reasonable,
    load_ui_geometry,
    parse_geometry,
    save_ui_geometry,
    ui_geometry_path,
)


def test_parse_and_format_roundtrip():
    assert parse_geometry("1280x860+40+20") == (1280, 860, 40, 20)
    assert parse_geometry("1100x720+-1920+100") == (1100, 720, -1920, 100)
    assert parse_geometry("bad") is None
    assert parse_geometry("") is None
    assert format_geometry(1280, 860, 40, 20) == "1280x860+40+20"


def test_reasonable_accepts_second_monitor_coords():
    assert geometry_is_reasonable(1000, 700, -1920, 0, min_w=1000, min_h=700)
    assert geometry_is_reasonable(1280, 860, 2000, 100, min_w=1000, min_h=700)
    assert not geometry_is_reasonable(200, 200, 0, 0, min_w=1000, min_h=700)
    assert not geometry_is_reasonable(1000, 700, 999999, 0, min_w=1000, min_h=700)


def test_save_load_geometry(tmp_path, monkeypatch):
    monkeypatch.setenv("CABINET_STUDIO_HOME", str(tmp_path / "CabinetStudio"))
    # Force saves under the override home.
    from cabinet_studio.services import paths as paths_mod
    monkeypatch.setattr(
        "cabinet_studio.ui.util.saves_directory",
        lambda origin=None: paths_mod.saves_directory(),
    )
    key = "programming_canvas"
    save_ui_geometry(key, "1280x860+-100+50")
    path = ui_geometry_path()
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[key] == "1280x860+-100+50"
    assert load_ui_geometry(key) == "1280x860+-100+50"
    save_ui_geometry("drawings_canvas", "1100x820+80+60")
    assert load_ui_geometry("drawings_canvas") == "1100x820+80+60"
    # invalid geom ignored
    save_ui_geometry(key, "nope")
    assert load_ui_geometry(key) == "1280x860+-100+50"
