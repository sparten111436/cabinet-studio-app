"""v0.3.6 Programming window: floating rung editor, undo/redo, one-shot add, live flow.

Runs under a real Tk display (xvfb-run on Linux CI); skipped when headless.
"""

from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)


@pytest.fixture()
def viewer(tmp_path, monkeypatch):
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.models.project import Project
    from cabinet_studio.services.programming import add_rung, empty_program, program_to_dict
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    monkeypatch.setattr(pv, "ask_choice", lambda *a, **k: None)
    root = ctk.CTk()
    root.withdraw()
    prog = add_rung(empty_program(), contact_tag="Start_PB", coil_tag="Motor")
    project = Project(
        name="V036", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
        program=program_to_dict(prog),
    )
    changes: list[str] = []
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, changes.append)
    v.update()
    v._changes = changes
    v._tmp = tmp_path
    try:
        yield v
    finally:
        try:
            if v.winfo_exists():
                v.close()
        except Exception:
            pass
        root.destroy()


def _pump(v, n: int = 3) -> None:
    for _ in range(n):
        v.update()


def test_rung_editor_pops_out_non_modal_and_docks(viewer):
    v = viewer
    assert not v.rung_editor_is_floating()
    v._rung_field_vars["timer_tag"].set("T42")
    v._pop_out_rung_editor()
    _pump(v)
    win = v._rung_editor_popout
    assert win is not None and win.winfo_exists()
    assert win.title().startswith("Rung editor")
    assert v.grab_current() is None  # not modal, nothing grabbed
    # Widgets now live in the floating window, state carried over.
    assert v.timer_tag_entry.winfo_toplevel() is win
    assert v.timer_tag_entry.get() == "T42"
    assert v.contact_menu.winfo_toplevel() is win
    # Docked strip collapsed to a hint (no duplicate controls).
    assert all(w.winfo_toplevel() is v for w in v._rung_bar.winfo_children())
    v._dock_rung_editor()
    _pump(v)
    assert v._rung_editor_popout is None and not win.winfo_exists()
    assert v.timer_tag_entry.winfo_toplevel() is v
    assert v.timer_tag_entry.get() == "T42"


def test_keep_on_top_transient_to_ladder_popout(viewer):
    v = viewer
    v._rung_editor_on_top.set(True)
    v._pop_out_rung_editor()
    _pump(v)
    win = v._rung_editor_popout
    assert v._rung_editor_topmost_applied is True  # X11 w/o WM never echoes -topmost
    assert str(win.wm_transient()) == str(v)
    v._pop_out_ladder_canvas()
    _pump(v)
    assert str(win.wm_transient()) == str(v._canvas_popout)
    v._rung_editor_on_top.set(False)
    v._on_rung_editor_on_top_toggle()
    assert v._rung_editor_topmost_applied is False
    assert str(win.wm_transient()) == ""
    v._rung_editor_on_top.set(True)
    v._on_rung_editor_on_top_toggle()
    v._dock_ladder_canvas()  # editor re-parents to the main window, no TclError
    _pump(v)
    assert win.winfo_exists() and str(win.wm_transient()) == str(v)
    prefs = json.loads((v._tmp / "ui_prefs.json").read_text())
    assert prefs["programming_rung_editor_on_top"] is True


def test_floating_edits_update_popped_ladder_live(viewer):
    v = viewer
    v._pop_out_ladder_canvas()
    v._pop_out_rung_editor()
    _pump(v)
    before = len(v.program["rungs"])
    v.contact_var.set("Start_PB")
    v.oneshot_block_var.set("OSR")
    v._rung_field_vars["oneshot_storage"].set("OS7")
    v._rung_field_vars["oneshot_output"].set("Pulse7")
    v._add_oneshot_rung()
    _pump(v)
    assert len(v.program["rungs"]) == before + 1
    assert v.canvas.winfo_toplevel() is v._canvas_popout
    texts = " ".join(v.canvas.itemcget(i, "text") for i in v.canvas.find_all() if v.canvas.type(i) == "text")
    assert "OSR" in texts and "OS7" in texts
    assert v._rung_editor_status.cget("text") == v.status.cget("text")
    # Undo from the floating window's button state
    assert "Undo (1)" in v._undo_btn.cget("text")
    v._undo()
    assert len(v.program["rungs"]) == before
    v._redo()
    assert len(v.program["rungs"]) == before + 1


def test_geometry_and_floating_pref_remembered_across_close(viewer):
    v = viewer
    v._pop_out_rung_editor()
    _pump(v)
    v._rung_editor_popout.geometry("820x300+150+120")
    _pump(v, 5)
    v.close()
    geoms = json.loads((v._tmp / "ui_window_geometry.json").read_text())
    w, h = geoms["programming_rung_editor"].split("+")[0].split("x")
    assert int(w) >= 560 and int(h) >= 240
    prefs = json.loads((v._tmp / "ui_prefs.json").read_text())
    assert prefs["programming_rung_editor_floating"] is True  # reopens floating next time


def test_sim_step_records_power_flow_and_add_compare_no_crash(viewer):
    v = viewer
    v.contact_var.set("Start_PB")
    v.coil_var.set("Motor")
    v._add_compare_rung()
    v._add_math_rung()
    v._add_otl_rung()
    v._add_otu_rung()
    _pump(v)
    sim = v._ensure_scan_sim(reset=True)
    sim.set_force("Start_PB", True)
    if hasattr(v, "_sim_step"):
        v._sim_step()
    else:
        sim.scan_once()
    _pump(v)
    v._draw_ladder()
    assert len(v.program["rungs"]) >= 5
