"""v0.3.7 Programming window: copy/paste, verify panel, tag list + X-ref, find/replace, shortcuts."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from test_programming_ui_gate import _assert_clean, _buttons, _invoke, _norm, _pump, ui  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)


def test_version_banner_is_037(ui):
    from cabinet_studio import __version__

    assert __version__.startswith("0.3.")
    assert f"v{__version__}" in ui.meta.cget("text")


def test_copy_paste_duplicate_move_via_handlers_and_undo(ui):
    v = ui
    first = v.program["rungs"][0]["id"]
    v._selected_rung_id = first
    v._copy_rung()
    v._paste_rung()
    assert len(v.program["rungs"]) == 2 and v._selected_rung_id != first
    assert v._ladder_clip["kind"] == "rungs"
    v._duplicate_rung()
    assert len(v.program["rungs"]) == 3
    sel = v._selected_rung_id
    v._move_rung_up()
    assert [r["id"] for r in v.program["rungs"]].index(sel) == 1
    v._undo()
    assert [r["id"] for r in v.program["rungs"]].index(sel) == 2
    # Instruction copy via chooser → paste into another rung
    v._selected_rung_id = first
    v._copy_instruction()
    _pump(v)
    chooser = v._tool_windows["copy_instr"]
    xic = next(b for b in _buttons(chooser) if _norm(b.cget("text")).startswith("XIC"))
    xic.invoke()
    _pump(v)
    assert "copy_instr" not in v._tool_windows and v._ladder_clip["kind"] == "instruction"
    target = v.program["rungs"][-1]["id"]
    v._selected_rung_id = target
    v._paste_instruction()
    from cabinet_studio.services.ladder_ir import program_rung_to_elements

    els = program_rung_to_elements(next(r for r in v.program["rungs"] if r["id"] == target))
    assert sum(1 for e in els if e["kind"] == "contact") == 2
    _assert_clean(v)


def test_keyboard_shortcuts_fire_and_are_text_safe(ui):
    v = ui
    v.focus_force()
    v.canvas.focus_set()
    _pump(v, 3)
    v._selected_rung_id = v.program["rungs"][0]["id"]
    handlers = {seq: fn for seq, fn, _safe in v._shortcut_bindings()}
    assert {"<Control-c>", "<Control-v>", "<Control-d>", "<F7>", "<Control-f>", "<Control-t>", "<F1>"} <= set(handlers)
    v._kb(handlers["<Control-d>"])()
    assert len(v.program["rungs"]) == 2
    v._kb(handlers["<Up>"])()
    assert v._selected_rung_id == v.program["rungs"][0]["id"]
    v._kb(handlers["<End>"])()
    assert v._selected_rung_id == v.program["rungs"][-1]["id"]
    v._kb(handlers["<F7>"], text_safe=True)()
    assert v._tool_window_open("verify")
    # Typing in an entry: non-text-safe shortcuts are skipped (Delete must not kill a rung).
    v.timer_tag_entry.focus_force()
    _pump(v, 3)
    if v._focus_is_text_input():
        before = len(v.program["rungs"])
        assert v._kb(handlers["<Delete>"])() is None
        assert len(v.program["rungs"]) == before
    _assert_clean(v)


def test_verify_panel_lists_issues_and_jumps_to_rung(ui):
    v = ui
    v.contact_var.set("Ghost_Bit")
    v.coil_var.set("M1")
    v._add_rung()
    ghost_rung = v.program["rungs"][-1]["id"]
    v._selected_rung_id = v.program["rungs"][0]["id"]
    v._open_verify_panel()
    _pump(v)
    codes = {i["code"] for i in v._verify_issues}
    assert {"MISSING_TAG", "DUP_OTE"} <= codes
    assert "warning" in v._verify_summary_lbl.cget("text")
    row = next(b for b in _buttons(v._verify_list) if "Ghost_Bit" in b.cget("text"))
    row.invoke()
    _pump(v)
    assert v._selected_rung_id == ghost_rung
    # Panel refreshes live after an edit (undo removes the bad rung)
    v._undo()
    _pump(v)
    assert "MISSING_TAG" not in {i["code"] for i in v._verify_issues}
    _assert_clean(v)


def test_tag_list_description_save_undo_and_where_used(ui):
    v = ui
    v._open_tag_list()
    _pump(v)
    assert "M1" in v._tag_desc_entries and "PB_Stop" in v._tag_desc_entries
    ent = v._tag_desc_entries["M1"]
    ent.insert(0, "Main conveyor motor")
    v._save_tag_entry("M1", ent)
    assert v.program["tag_descriptions"]["M1"] == "Main conveyor motor"
    assert v.project.program["tag_descriptions"]["M1"] == "Main conveyor motor"
    v._show_tag_xref("M1")
    _pump(v)
    assert "2 reference" not in v._tag_xref_label.cget("text")  # only the coil
    assert "1 reference" in v._tag_xref_label.cget("text")
    ref_btn = next(b for b in _buttons(v._tag_xref_frame) if "OTE M1" in b.cget("text"))
    ref_btn.invoke()
    v._new_tag_name.insert(0, "N7")
    v._new_tag_desc.insert(0, "Part count")
    v._add_tag_description()
    assert v.program["tag_descriptions"]["N7"] == "Part count"
    v._undo()
    assert "N7" not in (v.program.get("tag_descriptions") or {})
    v._undo()
    assert not (v.program.get("tag_descriptions") or {})
    v._tag_filter_var.set("pb_")
    v._refresh_tag_list()
    assert set(v._tag_desc_entries) == {"PB_Start", "PB_Stop"}
    _assert_clean(v)


def test_find_replace_window_renames_everywhere_and_undo(ui):
    v = ui
    v.contact_var.set("M1")
    v.coil_var.set("M1")
    v._add_rung()  # M1 now read + written
    v._open_find_replace()
    _pump(v)
    v._find_entry.delete(0, "end")
    v._find_entry.insert(0, "M1")
    refs = v._find_all()
    assert len(refs) == 3
    v._replace_entry.insert(0, "Motor_1")
    n = v._replace_tags(selected_only=False)
    assert n == 3
    from cabinet_studio.services.ladder_tools import find_tag_refs

    assert not find_tag_refs(v.program, "M1", whole=True, match_case=True)
    assert v._find_entry.get() == "Motor_1"
    v._undo()
    assert len(find_tag_refs(v.program, "M1", whole=True)) == 3
    v._replace_entry.delete(0, "end")
    v._replace_entry.insert(0, "bad name")
    assert v._replace_tags(selected_only=False) == 0
    assert "not a valid tag" in v.status.cget("text")
    _assert_clean(v)


def test_tool_windows_close_with_viewer_and_print_has_cross_reference(ui, monkeypatch, tmp_path):
    v = ui
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    from cabinet_studio.services.ladder_tools import set_tag_description

    v.program = set_tag_description(v.program, "M1", "Main conveyor motor")
    v.print_ladder()
    page = (tmp_path / "cabinet_studio_ladder_print.html").read_text(encoding="utf-8")
    assert "Tag cross-reference" in page and "Main conveyor motor" in page and "R1: OTE M1" in page
    v._open_verify_panel()
    v._open_tag_list()
    v._open_find_replace()
    v._show_shortcuts()
    _pump(v)
    wins = list(v._tool_windows.values())
    assert len(wins) == 4 and v.grab_current() is None  # non-modal
    v.close()
    assert all(not w.winfo_exists() for w in wins)


def test_force_strip_floats_and_docks_with_live_toggles(ui):
    v = ui
    v._toggle_force_popout()
    _pump(v)
    win = v._force_popout
    assert win is not None and win.winfo_exists() and v.grab_current() is None
    assert v._force_strip.winfo_toplevel() is win
    v._sim_step()
    _pump(v)
    assert "PB_Start" in v._force_buttons and v._force_buttons["PB_Start"].winfo_toplevel() is win
    v._force_buttons["PB_Start"].invoke()
    _pump(v)
    assert v._ensure_scan_sim().forces.get("PB_Start") is True
    assert v._force_buttons["PB_Start"].winfo_toplevel() is win  # rebuilt in the float
    win.tk.call(win.protocol("WM_DELETE_WINDOW"))
    _pump(v)
    assert v._force_popout is None and not win.winfo_exists()
    assert v._force_strip is v._force_home_strip and v._force_strip.winfo_toplevel() is v
    assert v._force_buttons["PB_Start"].winfo_toplevel() is v
    _assert_clean(v)
