"""Programming UI gate (mandatory from v0.3.7 on — every batch must pass).

Headless Tk (xvfb-run on Linux): invokes EVERY Programming toolbar button, every
Add-instruction button (docked and floating), the rung editor open / edit / close
cycle, and the v0.3.7 tool windows, asserting no exception — neither raised
directly nor reported through Tk's callback handler.
"""

from __future__ import annotations

import os
import re
import traceback

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)

# v0.3.22: Studio (default) = native menus + one compact toolbar; Classic keeps the old
# button strips for one release. Both share the single SimToolbar and one Pop out / Done.
STUDIO_TOOLBAR = {"New…", "Ladder", "PLC text", "HMI text", "Organizer", "Properties", "Pop out ladder", "Verify",
                  "Tags / X-ref", "Watch / Trend", "Done"}
CLASSIC_TOOLBAR = {
    "New program wizard", "Ask questions", "Build starter program", "Build from drawings", "Ladder", "PLC text", "HMI text",
    "Copy PLC", "Copy HMI", "Print", "Export Ladder", "Export PLCopen", "Import PLCopen",
    "Verify (F7)", "Tags / X-ref", "Find / Replace", "Watch / Trend", "Shortcuts (F1)", "Pop out ladder",
}
TOOLBAR = CLASSIC_TOOLBAR
SIM_BAR = {"Run", "Pause", "Step rung", "Step scan", "Stop", "Reset", "Ask AI", "Float I/O"}
SIM_TOOLBAR_LABELS = ["Run", "Pause", "Step rung", "Step scan", "Stop", "Reset", "Normal run", "Ask AI"]
ADD_BUTTONS = [
    "Add rung", "Add timer", "Add counter", "Add nested OR", "Add mid coil", "Add compare",
    "Add math", "Add LIM", "Add MEQ", "Add bitwise", "Add AOI",
    "Add OTL", "Add OTU", "Add one-shot", "Add JSR", "Add SBR", "Add RET",
]
EDIT_BUTTONS = {
    "Add series contact", "Comment…", "Delete rung", "Copy rung", "Paste rung", "Duplicate",
    "Move ↑", "Move ↓", "Copy instr…", "Paste instr", "↶ Undo", "↷ Redo", "Pop out editor",
}
NAV = {"Export .txt", "Sync text from ladder", "Done"}
NEVER_SWEEP = {"Done"}


def _norm(text: str) -> str:
    return re.sub(r"\s*\(\d+\)$", "", str(text or "")).strip()


def _all_widgets(widget):
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_all_widgets(child))
    return out


def _buttons(root):
    return [w for w in _all_widgets(root) if isinstance(w, ctk.CTkButton)]


def _labels(root, *, toplevel=None):
    return {
        _norm(b.cget("text"))
        for b in _buttons(root)
        if toplevel is None or b.winfo_toplevel() is toplevel
    }


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    monkeypatch.setenv("CABINET_STUDIO_AI_SETTINGS", str(tmp_path / "ai_settings.json"))
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    import tkinter.filedialog as fd

    from cabinet_studio.models.project import PlacedItem, Project
    from cabinet_studio.services.plcopen_xml import export_program_to_plcopen_xml
    from cabinet_studio.services.programming import add_rung, empty_program, program_to_dict
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    prog = add_rung(empty_program(), contact_tag="PB_Start", coil_tag="M1", comment="Start motor")
    xml_path = tmp_path / "import.xml"
    xml_path.write_text(export_program_to_plcopen_xml(prog, project_name="Gate"), encoding="utf-8")
    monkeypatch.setattr(pv, "ask_choice", lambda *a, **k: "yes")
    monkeypatch.setattr(fd, "asksaveasfilename", lambda **k: str(tmp_path / f"out{k.get('defaultextension', '.txt')}"))
    monkeypatch.setattr(fd, "askopenfilename", lambda **k: str(xml_path))
    monkeypatch.setattr(pv.webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(
        "cabinet_studio.services.drawings.default_drawings_folder", lambda project, path=None: tmp_path / "drawings"
    )

    errors: list[str] = []
    root = ctk.CTk()
    root.withdraw()
    root.report_callback_exception = lambda exc, val, tb: errors.append(
        "".join(traceback.format_exception(exc, val, tb))
    )
    items = [
        PlacedItem(id="i1", library_id=None, type_id="pushbutton", x=10, y=10, fields={"tag": "PB_Start", "description": "Start PB"}),
        PlacedItem(id="i2", library_id=None, type_id="pushbutton", x=20, y=10, fields={"tag": "PB_Stop"}),
        PlacedItem(id="i3", library_id=None, type_id="contactor", x=30, y=10, fields={"tag": "M1", "description": "Motor"}),
    ]
    project = Project(name="Gate", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                      program=program_to_dict(prog), items=items)
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *_: None)
    v.update()
    v._errors = errors
    try:
        yield v
    finally:
        try:
            if v.winfo_exists():
                v.close()
        except Exception:
            pass
        try:
            root.update()
        except Exception:
            pass
        root.destroy()
        from cabinet_studio.ui import theme

        theme.set_mode("dark", save=False)


def _pump(v, n=2):
    for _ in range(n):
        try:
            v.update()
        except Exception:
            pass


def _invoke(v, label, *, root=None, toplevel=None):
    """Invoke the first live button with this (normalized) label; return it."""
    root = root or v
    for b in _buttons(root):
        try:
            if not b.winfo_exists() or _norm(b.cget("text")) != label:
                continue
            if toplevel is not None and b.winfo_toplevel() is not toplevel:
                continue
        except Exception:
            continue
        try:
            b.invoke()
        except Exception:
            v._errors.append(f"{label}: {traceback.format_exc()}")
        _pump(v)
        return b
    raise AssertionError(f"button {label!r} not found")


def _fill_fields(v):
    v.contact_var.set("PB_Start")
    v.coil_var.set("M1")
    for key, value in {"timer_tag": "T1", "timer_pt": "500", "counter_tag": "C1", "counter_pv": "3",
                       "compare_op": "GEQ", "compare_a": "N7", "compare_b": "2", "compare_c": "100",
                       "math_op": "ADD", "math_dest": "N7", "oneshot_storage": "OS1", "oneshot_output": "P1",
                       "jsr_target": "Motor", "sbr_name": "Motor", "aoi_name": "MotorStarter",
                       "comment": ""}.items():
        v._rung_field_vars[key].set(value)


def _assert_clean(v):
    assert not v._errors, "\n\n".join(v._errors)


def test_gate_every_programming_button_invokes_without_exception(ui):
    """v0.3.22: the full button sweep runs in Studio, then Classic, then Studio again."""
    v = ui
    assert v._built_layout == "studio"
    _sweep_layout(v, "studio")
    v.invoke_command("view.layout.classic")
    _pump(v)
    assert v._built_layout == "classic"
    _sweep_layout(v, "classic")
    v.invoke_command("view.layout.studio")
    _pump(v)
    assert v._built_layout == "studio"
    _sweep_layout(v, "studio")

    # Done closes cleanly.
    _invoke(v, "Done", toplevel=v)
    assert not v.winfo_exists()
    _assert_clean(v)


def _sweep_layout(v, layout):
    toolbar = STUDIO_TOOLBAR if layout == "studio" else CLASSIC_TOOLBAR
    nav = {"Done"} if layout == "studio" else NAV
    present = _labels(v, toplevel=v)
    missing = (toolbar | SIM_BAR | set(ADD_BUTTONS) | EDIT_BUTTONS | nav) - present
    assert not missing, f"{layout}: buttons missing from Programming window: {sorted(missing)}"
    if layout == "studio":
        dropped = {"Pop out view", "Close", "▶  Simulate", "Reset sim", "Done - return to cabinet"} & present
        assert not dropped, f"duplicate / old controls still shown: {dropped}"

    # 1) Every Add-instruction button (docked) adds exactly one rung (Add SBR seeds a routine).
    _fill_fields(v)
    for i, label in enumerate(ADD_BUTTONS):
        before = len(v.program["rungs"])
        v._rung_field_vars["oneshot_storage"].set(f"OS{i}")  # unique storage per one-shot
        v._rung_field_vars["jsr_target"].set(f"Sub{i}")
        v._rung_field_vars["sbr_name"].set(f"Sub{i}")
        _invoke(v, label, toplevel=v)
        if label == "Add SBR":
            assert f"Sub{i}" in (v.program.get("routines") or {}), f"{label} did not create routine"
        elif label == "Add AOI":
            assert len(v.program["rungs"]) >= before + 1, f"{label} did not add a rung"
        else:
            assert len(v.program["rungs"]) == before + 1, f"{label} did not add a rung"
    _assert_clean(v)

    # 2) Edit buttons (copy/paste/move/comment/undo/redo…) docked.
    for label in ["Add series contact", "Copy rung", "Paste rung", "Duplicate", "Move ↑", "Move ↓",
                  "Copy instr…", "Paste instr", "↶ Undo", "↷ Redo", "Comment…", "Delete rung"]:
        _invoke(v, label, toplevel=v)
    _assert_clean(v)

    # 3) Rung editor open → every Add / edit button in the floating window → close.
    _invoke(v, "Pop out editor", toplevel=v)
    win = v._rung_editor_popout
    assert win is not None and win.winfo_exists()
    _fill_fields(v)
    for i, label in enumerate(ADD_BUTTONS):
        before = len(v.program["rungs"])
        v._rung_field_vars["oneshot_storage"].set(f"OSF{i}")
        v._rung_field_vars["jsr_target"].set(f"FSub{i}")
        v._rung_field_vars["sbr_name"].set(f"FSub{i}")
        _invoke(v, label, toplevel=win)
        if label == "Add SBR":
            assert f"FSub{i}" in (v.program.get("routines") or {}), f"floating {label} did not create routine"
        elif label == "Add AOI":
            assert len(v.program["rungs"]) >= before + 1, f"floating {label} did not add a rung"
        else:
            assert len(v.program["rungs"]) == before + 1, f"floating {label} did not add a rung"
    for label in ["Copy rung", "Paste rung", "Duplicate", "Move ↑", "Move ↓", "↶ Undo", "↷ Redo"]:
        _invoke(v, label, toplevel=win)
    _invoke(v, "Dock editor", toplevel=win)
    assert v._rung_editor_popout is None
    _assert_clean(v)

    # 4) Every toolbar + simulation + nav button (except Done, done last).
    for label in sorted(toolbar - NEVER_SWEEP) + sorted(SIM_BAR) + sorted(nav - NEVER_SWEEP):
        was_visible = v.pane_visible(label.lower()) if label in {"Organizer", "Properties"} else None
        _invoke(v, label, toplevel=v)
        if label in {"Pop out ladder", "Float I/O"}:
            _invoke(v, {"Pop out ladder": "Dock ladder", "Float I/O": "Dock I/O"}[label], toplevel=v)
        if was_visible is not None:
            # Step 5's collapse arrows may have hidden the pane on an earlier pass; the button is a toggle.
            assert v.pane_visible(label.lower()) is (not was_visible)
            _invoke(v, label, toplevel=v)
            assert v.pane_visible(label.lower()) is was_visible
            if not was_visible:
                _invoke(v, label, toplevel=v)
                assert v.pane_visible(label.lower())
    _invoke(v, "Stop", toplevel=v)
    _assert_clean(v)

    # 5) Sweep: literally every remaining live button anywhere in the window tree
    #    (question choices, force toggles, tool-window buttons, …), once each.
    swept = 0
    for b in list(_buttons(v)):
        try:
            if not b.winfo_exists():
                continue
            label = _norm(b.cget("text"))
            if label in NEVER_SWEEP and b.winfo_toplevel() is v:
                continue
            b.invoke()
            swept += 1
        except Exception:
            v._errors.append(f"sweep {b}: {traceback.format_exc()}")
        _pump(v, 1)
    assert swept >= 30
    v._sim_stop()
    for closer in (v._dock_ladder_canvas, v._dock_force_strip, v._dock_rung_editor, v._close_all_tool_windows):
        closer()
    _pump(v)
    _assert_clean(v)


def test_gate_rung_editor_open_edit_close_via_window_manager(ui):
    v = ui
    _invoke(v, "Pop out editor", toplevel=v)
    win = v._rung_editor_popout
    _fill_fields(v)
    v._rung_field_vars["timer_tag"].set("T9")
    before = len(v.program["rungs"])
    _invoke(v, "Add timer", toplevel=win)
    assert len(v.program["rungs"]) == before + 1
    texts = " ".join(v.canvas.itemcget(i, "text") for i in v.canvas.find_all() if v.canvas.type(i) == "text")
    assert "T9" in texts  # live redraw
    cb = next(w for w in _all_widgets(win) if isinstance(w, ctk.CTkCheckBox))
    cb.toggle()
    cb.toggle()
    _pump(v)
    # Close through the WM_DELETE_WINDOW protocol (title-bar X)
    win.tk.call(win.protocol("WM_DELETE_WINDOW"))
    _pump(v)
    assert v._rung_editor_popout is None and not win.winfo_exists()
    assert v.timer_tag_entry.get() == "T9"  # state survives dock
    _assert_clean(v)


def test_gate_part_wizard_suggest_and_apply_on_every_step(tmp_path, monkeypatch):
    """v0.3.19: catalog part → definition wizard (main_window passes project / library /
    profile / type_id / field_assists). Click Suggest and Apply suggestion on every field of
    every step, step with Next / Back, then Place on layout."""
    monkeypatch.setenv("CABINET_STUDIO_NO_SPLASH", "1")
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.services.layouts import new_blank_project
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui.main_window import CabinetStudioApp

    errors: list[str] = []
    app = CabinetStudioApp(load_library())
    app.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb)))
    try:
        app.withdraw()
        app._replace_project(new_blank_project("Wizard gate"), None, False, "reset")
        app.add_from_catalog("ab-prox-871c")
        app.update()
        wiz = app._wizard_window
        assert wiz is not None and wiz.winfo_exists()
        clicked = {"Suggest": 0, "Apply suggestion": 0}
        for _step in range(len(wiz.steps)):
            for label in clicked:
                n = 0
                while True:
                    live = [b for b in _buttons(wiz) if b.winfo_exists() and _norm(b.cget("text")) == label]
                    if n >= len(live):
                        break
                    try:
                        live[n].invoke()
                    except Exception:
                        errors.append(f"{label}: {traceback.format_exc()}")
                    app.update()
                    n += 1
                clicked[label] += n
            if wiz.index < len(wiz.steps) - 1:
                wiz._next()
                app.update()
        assert clicked["Suggest"] > 0 and clicked["Apply suggestion"] > 0, clicked
        wiz._back()
        app.update()
        wiz._next()
        app.update()
        wiz._finish()
        app.update()
        if wiz.winfo_exists() and wiz.state() != "withdrawn":
            wiz._finish()
            app.update()
        assert len(app.project.items) == 1 and app.project.items[0].type_id == "sensor"
        assert not errors, "\n\n".join(errors)
    finally:
        app.destroy()


def _speed_menus(root, *, toplevel=None):
    return [
        w for w in _all_widgets(root)
        if isinstance(w, ctk.CTkOptionMenu) and "1 s / rung" in (w.cget("values") or [])
        and (toplevel is None or w.winfo_toplevel() is toplevel)
    ]


def _click_part(v, kind, tag, *, button=1):
    """Real canvas click (event_generate) on a drawn ladder part."""
    v._draw_ladder()
    _pump(v)
    v.canvas.xview_moveto(0)
    v.canvas.yview_moveto(0)
    for x0, y0, x1, y1, k, t in v._click_targets:
        if k == kind and t == tag:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            break
    else:
        raise AssertionError(f"no {kind} {tag} drawn on the ladder")
    ex, ey = int(cx - v.canvas.canvasx(0)), int(cy - v.canvas.canvasy(0))
    v.canvas.event_generate(f"<Button-{button}>", x=ex, y=ey)
    _pump(v)


def _tick(v):
    """One run tick by hand (the scheduled after() is cancelled so the test owns time)."""
    v._sim_cancel_timer()
    v._sim_scan_tick()
    v._sim_cancel_timer()


def test_gate_v0320_rung_by_rung_click_parts_live_edit_and_floating_panel(ui, monkeypatch):
    """v0.3.20: Run walks one rung per tick, ladder parts are clicked to operate them,
    edits while running keep the live state, a blocking edit pauses until fixed, and the
    floating sim panel (every button, speed menu, Keep on top) rides above the ladder pop-out."""
    from types import SimpleNamespace

    from cabinet_studio.services.programming import add_rung_from_elements
    from cabinet_studio.ui import programming_viewer as pv

    v = ui
    clock = [100.0]
    monkeypatch.setattr(pv, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    _fill_fields(v)
    v._rung_field_vars["timer_pt"].set("2000")
    v.coil_var.set("(none)")
    _invoke(v, "Add timer", toplevel=v)
    rungs = v.program["rungs"]
    assert len(rungs) == 2
    v.coil_var.set("Lamp")

    menus = _speed_menus(v, toplevel=v)
    assert menus, "docked speed menu missing"
    menus[0]._dropdown_callback("1 s / rung")
    _pump(v)
    assert v._sim_rung_ms() == 1000

    # Run: one rung per tick with the executing-rung cursor.
    _invoke(v, "Run", toplevel=v)
    v._sim_cancel_timer()
    assert v._sim_running and v._sim_session
    assert v._sim_cursor_rung_id == rungs[0]["id"] and "rung 1/2" in v._sim_status.cget("text")
    _tick(v)
    assert v._sim_cursor_rung_id == rungs[1]["id"] and "rung 2/2" in v._sim_status.cget("text")
    texts = " ".join(v.canvas.itemcget(i, "text") for i in v.canvas.find_all() if v.canvas.type(i) == "text")
    assert "executing" in texts

    # Click the PB_Start contact on the ladder: switched on (forced), shown at once.
    _click_part(v, "contact", "PB_Start")
    sim = v._ensure_scan_sim()
    assert sim.forces.get("PB_Start") is True and "switched ON" in v._sim_status.cget("text")
    assert "PB_Start" in v._sim_active_tags
    _tick(v)  # rung 1 (t=100 s): M1 follows
    assert sim.read("M1")
    clock[0] = 101.0
    _tick(v)  # rung 2: T1 starts timing
    assert sim.timers["T1"]["tt"] and sim.timers["T1"]["acc_ms"] == 0

    # Edit while running: Add rung rebuilds the sim but keeps forces + T1 timing.
    clock[0] = 102.0
    _invoke(v, "Add rung", toplevel=v)
    new_sim = v._ensure_scan_sim()
    assert new_sim is not sim and v._sim_running
    assert new_sim.forces.get("PB_Start") is True and new_sim.timers["T1"]["tt"]
    _tick(v)  # rung 1
    clock[0] = 103.0
    _tick(v)  # rung 2 at 103 s: 2 real seconds since T1 started -> DN
    assert new_sim.timers["T1"]["q"], new_sim.timers["T1"]
    _tick(v)  # rung 3 (the added rung)
    assert v._sim_cursor_rung_id == v.program["rungs"][2]["id"]

    # Coil click forces it, right-click releases; timer click resets.
    _click_part(v, "coil", "M1")
    assert "M1" in new_sim.forces and "forced" in v._sim_status.cget("text")
    _click_part(v, "coil", "M1", button=3)
    assert "M1" not in new_sim.forces and "released" in v._sim_status.cget("text")
    _click_part(v, "timer", "T1")
    assert new_sim.timers["T1"]["acc_ms"] == 0 and not new_sim.timers["T1"]["q"]
    assert "reset" in v._sim_status.cget("text")

    # Pause / Step rung / Step scan / Reset.
    _invoke(v, "Pause", toplevel=v)
    assert not v._sim_running and v._sim_session and "PAUSED" in v._sim_status.cget("text")
    before = v._ensure_scan_sim().rung_cursor
    _invoke(v, "Step rung", toplevel=v)
    assert v._ensure_scan_sim().rung_cursor == (before + 1) % len(v.program["rungs"])
    assert "STEP RUNG" in v._sim_status.cget("text")
    _invoke(v, "Step scan", toplevel=v)
    assert v._sim_cursor_rung_id is None and "Sim STEP scan" in v._sim_status.cget("text")
    _invoke(v, "Reset", toplevel=v)
    assert not v._ensure_scan_sim().forces and "RESET" in v._sim_status.cget("text")

    # A live edit that blocks the sim pauses it (nothing scans) and it resumes once fixed.
    _invoke(v, "Run", toplevel=v)
    v._sim_cancel_timer()
    assert v._sim_running
    good = v.program
    v.program = add_rung_from_elements(
        good, [{"kind": "contact", "var": "PB_Start", "form": "NO"},
               {"kind": "math", "op": "CPT", "dest": "D", "source_a": "1/0"}],
    )
    _tick(v)
    assert not v._sim_running and v._sim_resume_when_fixed
    assert "Sim BLOCKED" in v._sim_status.cget("text") and "resumes when fixed" in v._sim_status.cget("text")
    v.program = good
    v._sim_cancel_timer()
    v._sim_fix_watch()
    v._sim_cancel_timer()
    assert v._sim_running and not v._sim_resume_when_fixed

    # Pop out the ladder while simulating: the sim panel floats above it (transient + topmost).
    _invoke(v, "Pop out ladder", toplevel=v)
    v._sim_cancel_timer()
    win, ladder = v._force_popout, v._canvas_popout
    assert win is not None and win.winfo_exists() and ladder is not None
    assert str(win.wm_transient()) == str(ladder)
    assert bool(win.attributes("-topmost"))
    cb = next(w for w in _all_widgets(win) if isinstance(w, ctk.CTkCheckBox) and w.cget("text") == "Keep on top")
    cb.toggle()
    _pump(v)
    assert not bool(win.attributes("-topmost"))
    cb.toggle()
    _pump(v)
    assert bool(win.attributes("-topmost"))
    assert v._sim_status_float is not None and v._sim_status_float.winfo_toplevel() is win

    # Ladder clicks still work in the pop-out canvas.
    _click_part(v, "contact", "PB_Start")
    assert v._ensure_scan_sim().forces.get("PB_Start") is True

    # Every floating-panel control.
    fmenus = _speed_menus(win, toplevel=win)
    assert fmenus, "floating speed menu missing"
    fmenus[0]._dropdown_callback("PLC speed (full scan)")
    _pump(v)
    v._sim_cancel_timer()
    assert not v._sim_rung_mode()
    for label in ["Pause", "Run", "Step rung", "Step scan", "Pause", "Reset", "Stop"]:
        _invoke(v, label, toplevel=win)
        v._sim_cancel_timer()
    assert not v._sim_running and not v._sim_session
    fmenus[0]._dropdown_callback("0.25 s / rung")
    _pump(v)
    assert v._sim_rung_ms() == 250

    # Dock the ladder: the panel re-attaches to the Programming window.
    _invoke(v, "Dock ladder", toplevel=v)
    assert str(win.wm_transient()) == str(v)
    _invoke(v, "Dock I/O", toplevel=win)
    assert v._force_popout is None and v._sim_status_float is None
    for seq in ("<F6>", "<F9>"):
        assert v.bind(seq), f"{seq} not bound"
    v._sim_stop()
    _assert_clean(v)


def _fake_ai(replies):
    """Stand-in for every AI HTTP call (OpenAI reply shape); records the requests."""
    calls = []

    def fake(method, url, headers, body, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if method == "GET":
            return {"data": [{"id": "gpt-gate-a"}, {"id": "gpt-gate-b"}]}
        reply = replies.pop(0) if replies else "OK"
        if isinstance(reply, Exception):
            raise reply
        return {"choices": [{"message": {"content": reply}}]}

    fake.calls = calls
    return fake


def _checkboxes(root, text):
    return [w for w in _all_widgets(root) if isinstance(w, ctk.CTkCheckBox) and w.cget("text") == text]


def test_gate_v0321_ai_assistant_settings_proposals_and_interview(ui, monkeypatch, tmp_path):
    """v0.3.21: Ask AI (sim bar + floating panel), every quick question, typed questions,
    AI settings (provider, key, show, refresh models, test, save, clear, close), AI rung
    proposals (Apply / Dismiss / refused / safety confirm), AI-failure fallback, keep-on-top
    with the ladder pop-out, and the interview AI picker / live tip / Ask AI."""
    import json as _json

    from cabinet_studio.services import ai_providers as ap
    from cabinet_studio.ui import ai_assistant as aiw
    from cabinet_studio.ui import ai_settings

    v = ui
    monkeypatch.setattr(ai_settings, "SYNC", True)
    replies: list = []
    fake = _fake_ai(replies)
    monkeypatch.setattr(ap, "_http", fake)

    _invoke(v, "Run", toplevel=v)
    v._sim_pause()
    _invoke(v, "Ask AI", toplevel=v)
    win = v._ai_window
    assert win is not None and win.winfo_exists()
    assert "Cabinet Studio AI" in win.ai_label.cget("text")
    assert str(win.wm_transient()) == str(v)

    # Built-in (offline): every quick question + a typed one; no network.
    for label in ("Why is this rung off?", "Explain this rung", "What should I test next?", "Suggest a fix"):
        _invoke(v, label, root=win, toplevel=win)
    win.entry.insert(0, "what does R1 do?")
    _invoke(v, "Ask", root=win, toplevel=win)
    win.entry.insert(0, "and now?")
    win.entry.event_generate("<Return>")
    _pump(v)
    text = win.transcript_text()
    assert "Rung R1" in text and "Test checklist" in text and "PB_Start" in text
    assert not fake.calls

    # AI settings: switch to OpenAI, key (show/clear), refresh models, test, save, close.
    _invoke(v, "AI settings…", root=win, toplevel=win)
    dlg = win._settings_win
    assert dlg is not None and dlg.winfo_exists()
    dlg.provider_var.set(ap.PROVIDERS["openai"]["label"])
    dlg._show_provider()
    assert str(dlg.key_entry.cget("state")) == "normal"
    dlg.key_entry.insert(0, "sk-gate-111")
    (show,) = _checkboxes(dlg, "Show")
    show.toggle()
    _pump(v)
    assert dlg.key_entry.cget("show") == ""
    _invoke(v, "Clear key", root=dlg, toplevel=dlg)
    assert "cleared" in dlg.key_note.cget("text")
    dlg.key_entry.insert(0, "sk-gate-222")
    _invoke(v, "Refresh models", root=dlg, toplevel=dlg)
    assert dlg.model_box.get() in {"gpt-gate-a", "gpt-gate-b"}
    _invoke(v, "Test connection", root=dlg, toplevel=dlg)
    assert "Connected" in dlg.status.cget("text"), dlg.status.cget("text")
    assert fake.calls[-1]["headers"]["Authorization"] == "Bearer sk-gate-222"
    _invoke(v, "Save", root=dlg, toplevel=dlg)
    saved = (tmp_path / "ai_settings.json").read_text(encoding="utf-8")
    assert _json.loads(saved)["provider"] == "openai" and "sk-gate" not in saved
    assert "OpenAI" in win.ai_label.cget("text")
    _invoke(v, "Close", root=dlg, toplevel=dlg)
    assert not dlg.winfo_exists()

    # AI answer with two proposals: one valid, one refused. Apply the valid one live.
    fix = {"action": "replace", "rung": 1, "comment": "seal-in",
           "elements": [{"kind": "or", "branches": [[{"kind": "contact", "var": "PB_Start", "form": "NO"}],
                                                    [{"kind": "contact", "var": "M1", "form": "NO"}]]},
                        {"kind": "contact", "var": "PB_Stop", "form": "NC"},
                        {"kind": "coil", "var": "M1", "form": "normal"}]}
    bad = {"action": "add", "elements": [{"kind": "timer", "var": "T9", "block": "TP", "pt_ms": 5}]}
    replies.append("Add a seal-in.\n```cabinet-rung\n" + _json.dumps(fix) + "\n```\n```cabinet-rung\n"
                   + _json.dumps(bad) + "\n```")
    v._selected_rung_id = v.program["rungs"][0]["id"]
    _invoke(v, "Suggest a fix", root=win, toplevel=win)
    sent = fake.calls[-1]["body"]["messages"][-1]["content"]
    assert "R1:" in sent and "SIMULATION" in sent and "Selected rung: Main R1" in sent
    assert "proposed rung change" in win.transcript_text()
    assert len(win.proposals) == 2 and win.proposals[0].ok and not win.proposals[1].ok
    applies = [b for b in _buttons(win.cards) if b.cget("text") == "Apply"]
    assert str(applies[1].cget("state")) == "disabled"
    assert "Refused" in " ".join(w.cget("text") for w in _all_widgets(win.cards) if isinstance(w, ctk.CTkLabel))
    applies[0].invoke()
    _pump(v)
    assert v._sim_session
    els = v.program["rungs"][0]
    assert "M1" in json_dumps_rung(els) and "PB_Stop" in json_dumps_rung(els)
    assert v._scan_sim is not None
    assert len(win.proposals) == 1
    _invoke(v, "Dismiss", root=win.cards)
    assert not win.proposals

    # Safety-related proposal needs confirmation: Cancel keeps the program, Apply anyway applies.
    unsafe = {"action": "add", "elements": [{"kind": "contact", "var": "ES1_Reset", "form": "NO"},
                                            {"kind": "coil", "var": "M1", "form": "set"}]}
    replies.append("```cabinet-rung\n" + _json.dumps(unsafe) + "\n```")
    win.entry.insert(0, "latch M1 from the reset")
    _invoke(v, "Ask", root=win, toplevel=win)
    assert win.proposals and win.proposals[0].safety
    n = len(v.program["rungs"])
    monkeypatch.setattr(aiw, "ask_choice", lambda *a, **k: "no")
    _invoke(v, "Apply", root=win.cards)
    assert len(v.program["rungs"]) == n
    monkeypatch.setattr(aiw, "ask_choice", lambda *a, **k: "yes")
    _invoke(v, "Apply", root=win.cards)
    assert len(v.program["rungs"]) == n + 1

    # AI failure falls back to the Built-in answer.
    replies.append(ap.AiError("Rate limit or quota reached (429)."))
    _invoke(v, "Explain this rung", root=win, toplevel=win)
    assert "AI unavailable: Rate limit" in win.transcript_text()
    assert "Rung R" in win.transcript_text().split("AI unavailable")[-1]

    # Floating panel Ask AI reuses the window; keep-on-top follows the ladder pop-out.
    _invoke(v, "Float I/O", toplevel=v)
    _invoke(v, "Ask AI", root=v._force_popout, toplevel=v._force_popout)
    assert v._ai_window is win
    _invoke(v, "Pop out ladder", toplevel=v)
    assert str(win.wm_transient()) == str(v._canvas_popout)
    (keep,) = _checkboxes(v._force_popout, "Keep on top")
    keep.toggle()
    _pump(v)
    assert not bool(win.attributes("-topmost"))
    keep.toggle()
    _pump(v)
    assert bool(win.attributes("-topmost"))
    _invoke(v, "Dock ladder", toplevel=v)
    assert str(win.wm_transient()) == str(v)
    _invoke(v, "Clear", root=win, toplevel=win)
    assert not win.transcript_text().strip()
    v._sim_stop()
    _assert_clean(v)

    # Interview: AI picker, live AI tip, Ask AI chat + its quick questions.
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.services.standards import default_profile
    from cabinet_studio.ui.ai_build import AiBuildDialog

    dlg = AiBuildDialog(v, v.fonts, load_library(), default_profile())
    replies.append("Pick 480 VAC for a conveyor motor.")
    dlg.present()
    _pump(v)
    assert "OpenAI" in dlg.ai_pick_btn.cget("text")
    assert dlg.ai_tip.cget("text").startswith("AI tip (OpenAI")
    sent = fake.calls[-1]["body"]["messages"][-1]["content"]
    assert "Current question: What does this machine do?" in sent
    dlg._text_widget.insert("1.0", "Conveyor with one motor")
    replies.append(RuntimeError("offline"))
    _invoke(v, "Next", root=dlg, toplevel=dlg)
    assert "AI unavailable" in dlg.ai_tip.cget("text") and "Siemens or Omron" in dlg.ai_tip.cget("text")
    dlg._choice_var.set("Allen-Bradley")
    replies.append(RuntimeError("offline"))
    _invoke(v, "Next", root=dlg, toplevel=dlg)
    assert "AI unavailable" in dlg.ai_tip.cget("text") and "Most industrial cabinets" in dlg.ai_tip.cget("text")
    _invoke(v, "Ask AI", root=dlg, toplevel=dlg)
    chat = dlg._ai_chat
    assert chat is not None and chat.winfo_exists()
    replies += ["It sets the feed voltage.", "480 VAC."]
    _invoke(v, "Explain this question", root=chat, toplevel=chat)
    _invoke(v, "What do you recommend?", root=chat, toplevel=chat)
    assert "480 VAC." in chat.transcript_text()
    assert "Conveyor with one motor" in fake.calls[-1]["body"]["messages"][-1]["content"]
    _invoke(v, "AI: OpenAI · gpt-gate-a  (change)" if "gpt-gate-a" in dlg.ai_pick_btn.cget("text")
            else _norm(dlg.ai_pick_btn.cget("text")), root=dlg, toplevel=dlg)
    sdlg = dlg._ai_settings_win
    sdlg.provider_var.set(ap.PROVIDERS[ap.BUILTIN]["label"])
    sdlg._show_provider()
    _invoke(v, "Save", root=sdlg, toplevel=sdlg)
    assert "Cabinet Studio AI" in dlg.ai_pick_btn.cget("text")
    chat.destroy()
    _invoke(v, "Cancel", root=dlg, toplevel=dlg)
    dlg.destroy()
    _assert_clean(v)


def json_dumps_rung(rung):
    import json as _json

    return _json.dumps(rung)


def test_gate_shortcuts_are_bound_on_every_programming_window(ui):
    v = ui
    _invoke(v, "Pop out editor", toplevel=v)
    _invoke(v, "Pop out ladder", toplevel=v)
    for win in (v, v._rung_editor_popout, v._canvas_popout):
        for seq in ("<Control-c>", "<Control-v>", "<Control-d>", "<Delete>", "<F7>", "<F5>", "<F10>", "<F6>", "<F9>", "<Control-f>", "<Control-z>"):
            assert win.bind(seq), f"{seq} not bound on {win.title()}"
    _assert_clean(v)


# ----------------------------------------------------------------------------- v0.3.22 UI phase 1

def _menu_invoke(v, cmd_id):
    path, idx = v.commands.menu_index[cmd_id]
    v.commands.menus[path].invoke(idx)
    _pump(v)


def test_gate_v0322_every_menu_entry_invokes(ui, monkeypatch):
    """Every entry of every native menu is clicked with menu.invoke(index); File > Done last."""
    import tkinter as tk

    from cabinet_studio.services import ai_providers as ap
    from cabinet_studio.ui import ai_settings, theme

    v = ui
    monkeypatch.setattr(ai_settings, "SYNC", True)
    monkeypatch.setattr(ap, "_http", _fake_ai([]))
    bar = v.nametowidget(tk.Misc.cget(v, "menu"))
    tops = [bar.entrycget(i, "label") for i in range(bar.index("end") + 1)]
    assert tops == ["File", "Edit", "View", "Rung", "Simulate", "Tools", "Help"]
    entries = v.commands.menu_entries()
    assert {cid for _p, _i, cid in entries} == {cid for cid, c in v.commands.commands.items() if c.menu_path}
    for path, menu in v.commands.menus.items():
        assert menu.index("end") is not None, f"empty menu {path!r}"
    for sub in ("View/Theme", "View/Layout", "Simulate/Speed"):
        assert sub in v.commands.menus

    ran = []
    orig = v.commands._from_menu
    monkeypatch.setattr(v.commands, "_from_menu", lambda cid: (ran.append(cid), orig(cid))[1])
    _fill_fields(v)
    for i, (path, idx, cid) in enumerate(entries):
        if cid == "file.done":
            continue
        v._rung_field_vars["oneshot_storage"].set(f"OSM{i}")
        v._rung_field_vars["jsr_target"].set(f"MSub{i}")
        v._rung_field_vars["sbr_name"].set(f"MSub{i}")
        v.commands.menus[path].invoke(idx)
        _pump(v)
        v._sim_cancel_timer()
        if cid == "view.layout.classic":
            assert v._built_layout == "classic"
        elif cid == "view.layout.studio":
            assert v._built_layout == "studio"
        elif cid == "view.theme.light":
            assert not theme.is_dark() and v.canvas.cget("background") == "#ffffff"
        elif cid == "view.theme.dark":
            assert theme.is_dark() and v.canvas.cget("background") == "#d8d4cc"
        elif cid.startswith("sim.speed."):
            assert v._sim_speed_var.get() == v.commands.get(cid).value
    assert set(ran) == {cid for _p, _i, cid in entries} - {"file.done"}
    v._sim_stop()
    _assert_clean(v)
    _menu_invoke(v, "file.done")
    assert not v.winfo_exists()
    _assert_clean(v)


def test_gate_v0322_toolbar_and_sim_toolbar_in_all_three_places(ui):
    """Every Studio toolbar button, then the one SimToolbar in the toolbar, the ladder pop-out
    and the floating I/O window: same labels, every button, speed menu and Follow rung."""
    v = ui
    assert v.editor.winfo_manager() == "", "Studio: PLC text pane must stay hidden on the Ladder tab"
    v.invoke_command("view.plc")
    assert v.editor.winfo_manager() == "pack"
    v.invoke_command("view.ladder")
    assert v.editor.winfo_manager() == ""
    btns = [b for b in _buttons(v) if getattr(b, "_cs_command_id", None) and b.winfo_toplevel() is v]
    ids = {b._cs_command_id for b in btns}
    assert {"view.ladder", "view.plc", "view.hmi", "view.popout", "tools.verify", "tools.tags", "tools.watch",
            "view.theme_toggle", "file.done", "view.float_io", "sim.run", "sim.pause", "sim.step_rung",
            "sim.step_scan", "sim.stop", "sim.reset", "tools.ask_ai"} <= ids
    for b in btns:
        cid = b._cs_command_id
        if cid == "file.done" or not b.winfo_exists():
            continue
        b.invoke()
        _pump(v)
        v._sim_cancel_timer()
        if cid in {"view.popout", "view.float_io", "view.theme_toggle"}:
            v.invoke_command(cid)  # dock again / theme back
            _pump(v)
    v._sim_stop()
    _assert_clean(v)

    v.invoke_command("sim.run")
    v._sim_cancel_timer()
    v.invoke_command("view.popout")
    v._sim_cancel_timer()
    assert v._canvas_popout is not None and v._force_popout is not None
    places = {"docked": v, "ladder pop-out": v._canvas_popout, "floating I/O": v._force_popout}
    for name, top in places.items():
        bars = [tb for tb in v._sim_toolbars if tb.winfo_exists() and tb.winfo_toplevel() is top]
        assert len(bars) == 1, f"{name}: {len(bars)} sim toolbars"
        tb = bars[0]
        assert [_norm(b.cget("text")) for b in tb.buttons.values()] == SIM_TOOLBAR_LABELS, name
        for b in tb.buttons.values():
            b.invoke()
            _pump(v)
            v._sim_cancel_timer()
        tb.speed_menu._dropdown_callback("0.5 s / rung")
        _pump(v)
        assert v._sim_rung_ms() == 500
        tb.speed_menu._dropdown_callback("1 s / rung")
        before = bool(v._follow_var.get())
        tb.follow.toggle()
        _pump(v)
        assert bool(v._follow_var.get()) is not before
        tb.follow.toggle()
        assert bool(v._follow_var.get()) is before
    dock = [b for b in _buttons(v._canvas_popout) if _norm(b.cget("text")) == "Dock ladder"]
    assert len(dock) == 1
    dock[0].invoke()
    _pump(v)
    assert v._canvas_popout is None
    v._sim_stop()
    v._dock_force_strip()
    _assert_clean(v)


def test_gate_v0322_theme_light_dark_light_redraws(ui):
    from cabinet_studio.ui import theme

    v = ui
    v.invoke_command("tools.watch")
    for mode, ladder_bg, dark in (("light", "#ffffff", False), ("dark", "#d8d4cc", True), ("light", "#ffffff", False)):
        _menu_invoke(v, f"view.theme.{mode}")
        assert theme.is_dark() is dark and theme.saved_mode() == mode
        assert v._theme_var.get() == mode
        assert v.canvas.cget("background") == ladder_bg
        assert v._theme_btn.cget("text") == ("☀ Light" if dark else "☾ Dark")
        assert v._watch_plot.cget("background") == theme.c("PLOT_BG")
        assert v.canvas.find_all(), "ladder not redrawn"
    v.invoke_command("view.popout")
    v.invoke_command("view.theme_toggle")
    _pump(v)
    assert theme.is_dark() and v.canvas.cget("background") == "#d8d4cc" and v.canvas.winfo_toplevel() is v._canvas_popout
    v.invoke_command("view.theme_toggle")
    _pump(v)
    assert not theme.is_dark() and v.canvas.cget("background") == "#ffffff"
    v.invoke_command("view.popout")
    _assert_clean(v)


def test_gate_v0322_follow_rung_keeps_the_executing_rung_in_view(ui, monkeypatch):
    from types import SimpleNamespace

    from cabinet_studio.services.programming import add_rung
    from cabinet_studio.ui import programming_viewer as pv

    v = ui
    clock = [100.0]
    monkeypatch.setattr(pv, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    prog = v.program
    for i in range(39):
        prog = add_rung(prog, contact_tag="PB_Stop" if i == 33 else "PB_Start", coil_tag=f"M{i + 2}",
                        comment=f"Rung {i + 2}")
    v.program = prog
    v._commit(status="40 rungs")
    _pump(v)
    rungs = v.program["rungs"]
    assert len(rungs) == 40

    def visible(rid):
        box = next(b for b in v._rung_hitboxes if b[0] == rid)
        top = v.canvas.canvasy(0)
        return box[2] >= top - 1 and box[4] <= top + v.canvas.winfo_height() + 1

    assert v._follow_var.get()
    v._sim_speed_var.set("1 s / rung")
    v.invoke_command("sim.run")
    v._sim_cancel_timer()
    for _ in range(19):
        _tick(v)
        assert visible(v._sim_cursor_rung_id), "docked: executing rung scrolled out of view"
    assert v.canvas.yview()[0] > 0

    # The user scrolls: Follow waits 3 s before moving the view again.
    v.canvas.yview_moveto(0)
    v._wheel(SimpleNamespace(delta=120))
    y = v.canvas.yview()[0]
    _tick(v)
    assert v.canvas.yview()[0] == y and not visible(v._sim_cursor_rung_id)
    clock[0] += 3.5
    _tick(v)
    assert visible(v._sim_cursor_rung_id)

    # Follow off: the view does not move.
    v.invoke_command("sim.follow")
    assert not v._follow_var.get()
    v.canvas.yview_moveto(0)
    for _ in range(5):
        _tick(v)
        assert v.canvas.yview()[0] == 0.0
    v._sim_toolbars[0].follow.toggle()  # back on from the SimToolbar: jumps to the cursor at once
    _pump(v)
    box = next(b for b in v._rung_hitboxes if b[0] == v._sim_cursor_rung_id)
    assert v._follow_var.get() and visible(v._sim_cursor_rung_id), (
        box, v.canvas.canvasy(0), v.canvas.winfo_height(), v._follow_suspend_until, clock[0], v._sim_session)

    # Popped out: the pop-out canvas follows too.
    v.invoke_command("view.popout")
    v._sim_cancel_timer()
    _pump(v)
    v._draw_ladder(preserve_scroll=False)
    v.canvas.yview_moveto(0)
    for _ in range(12):
        _tick(v)
        assert v.canvas.winfo_toplevel() is v._canvas_popout
        assert visible(v._sim_cursor_rung_id), "pop-out: executing rung scrolled out of view"

    # Full-scan speed: follow the first rung whose state changed (rung 35 reads PB_Stop).
    v._sim_speed_var.set("PLC speed (full scan)")
    v._on_sim_speed()
    v._sim_cancel_timer()
    v.canvas.yview_moveto(0)
    _tick(v)
    _tick(v)
    v._ensure_scan_sim().toggle_force("PB_Stop")
    _tick(v)
    assert v._sim_cursor_rung_id is None and visible(rungs[34]["id"])
    v.invoke_command("view.popout")
    v._sim_stop()
    v._dock_force_strip()
    _assert_clean(v)


def test_gate_v0322_status_bar_tracks_mode_scan_rung_and_errors(ui):
    from cabinet_studio import __version__
    from cabinet_studio.services.ladder_tools import verify_program
    from cabinet_studio.services.programming import LEARNING_NOTE, cabinet_device_tags
    from cabinet_studio.ui.shell.statusbar import EDU_BADGE
    from cabinet_studio.ui.theme import PALETTE

    v = ui
    sb = v.statusbar
    mode = lambda: sb.mode_label.cget("text").strip()  # noqa: E731
    assert mode() == "PROG" and sb.scan_label.cget("text") == "scan -"
    assert sb.badge_label.cget("text") == EDU_BADGE == "Educational ladder + scan sim, not a PLC download"
    assert f"v{__version__}" in sb.version_label.cget("text") and v.meta is sb.version_label
    assert __version__ in v.title() and LEARNING_NOTE in v.title()
    assert sb.rung_label.cget("text") == "rung -/1"
    v.invoke_command("sim.run")
    v._sim_cancel_timer()
    assert mode() == "RUN" and sb.mode_label.cget("fg_color") == PALETTE["BADGE_RUN"]
    assert sb.rung_label.cget("text") == "rung 1/1" and sb.scan_label.cget("text").startswith("scan #")
    _tick(v)
    n = v._ensure_scan_sim().scan_count
    assert sb.scan_label.cget("text") == f"scan #{n}"
    v.invoke_command("sim.pause")
    assert mode() == "STEP" and sb.mode_label.cget("fg_color") == PALETTE["BADGE_STEP"]
    v.invoke_command("sim.step_rung")
    assert mode() == "STEP"
    v.invoke_command("sim.stop")
    assert mode() == "PROG" and sb.scan_label.cget("text") == "scan -"
    v._refresh_error_count()
    issues = verify_program(v.program, cabinet_device_tags(v.project))
    errors = sum(1 for i in issues if i["severity"] == "error")
    assert sb.error_label.cget("text").startswith(f"{errors} error")
    v.coil_var.set("(none)")
    v.contact_var.set("")
    v.invoke_command("rung.add")
    v._refresh_error_count()
    issues = verify_program(v.program, cabinet_device_tags(v.project))
    errors = sum(1 for i in issues if i["severity"] == "error")
    assert sb.error_label.cget("text").startswith(f"{errors} error")
    assert sb.rung_label.cget("text") == f"rung -/{len(v.program['rungs'])}"
    v.status.configure(text="hello")
    assert sb.message.cget("text") == "hello"
    _assert_clean(v)


def test_gate_v0322_copilot_providers_settings_flow(ui, monkeypatch, tmp_path):
    """Tools > AI settings: GitHub Models (Copilot) token flow, then Microsoft Azure OpenAI."""
    import json as _json

    from cabinet_studio.services import ai_providers as ap
    from cabinet_studio.ui import ai_settings

    v = ui
    calls = []

    def fake(method, url, headers, body, timeout):
        calls.append({"url": url, "headers": dict(headers)})
        if url.endswith("/catalog/models"):
            return [{"id": "openai/gpt-4.1", "supported_output_modalities": ["text"]}]
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(ai_settings, "SYNC", True)
    monkeypatch.setattr(ap, "_http", fake)
    _menu_invoke(v, "tools.ai_settings")
    dlg = v._ai_window._settings_win
    assert dlg is not None and dlg.winfo_exists()
    assert "no third-party API" in dlg.microsoft_note.cget("text")
    labels = dlg.provider_menu.cget("values") if hasattr(dlg, "provider_menu") else None
    if labels is not None:
        assert ap.PROVIDERS["github"]["label"] in labels and ap.PROVIDERS["azure_openai"]["label"] in labels

    dlg.provider_var.set(ap.PROVIDERS["github"]["label"])
    dlg._show_provider()
    dlg.key_entry.insert(0, "ghp_GATE")
    _invoke(v, "Refresh models", root=dlg, toplevel=dlg)
    _invoke(v, "Test connection", root=dlg, toplevel=dlg)
    assert "Connected" in dlg.status.cget("text"), dlg.status.cget("text")
    assert calls[-1]["headers"]["Authorization"] == "Bearer ghp_GATE"
    _invoke(v, "Save", root=dlg, toplevel=dlg)
    raw = (tmp_path / "ai_settings.json").read_text(encoding="utf-8")
    assert _json.loads(raw)["provider"] == "github" and "ghp_GATE" not in raw

    dlg.provider_var.set(ap.PROVIDERS["azure_openai"]["label"])
    dlg._show_provider()
    dlg.azure_entries["endpoint"].insert(0, "https://gate.openai.azure.com")
    dlg.azure_entries["deployment"].insert(0, "gate-deploy")
    dlg.key_entry.insert(0, "AZ_GATE")
    _invoke(v, "Refresh models", root=dlg, toplevel=dlg)
    _invoke(v, "Test connection", root=dlg, toplevel=dlg)
    assert "Connected to Azure OpenAI" in dlg.status.cget("text"), dlg.status.cget("text")
    assert calls[-1]["url"].startswith("https://gate.openai.azure.com/openai/deployments/gate-deploy/")
    assert calls[-1]["headers"]["api-key"] == "AZ_GATE"
    _invoke(v, "Save", root=dlg, toplevel=dlg)
    raw = (tmp_path / "ai_settings.json").read_text(encoding="utf-8")
    assert _json.loads(raw)["provider"] == "azure_openai" and "AZ_GATE" not in raw
    assert "Azure OpenAI" in v._ai_window.ai_label.cget("text")
    _invoke(v, "Close", root=dlg, toplevel=dlg)
    assert not dlg.winfo_exists()
    _assert_clean(v)


def test_gate_v0322_main_window_menus_toolbar_header_and_theme(tmp_path, monkeypatch):
    """Main window: every menu entry and toolbar button routes to its app action; header is
    44 px; theme radios repaint the cabinet canvas; the sticky OUTPUT rail is untouched."""
    import tkinter as tk

    monkeypatch.setenv("CABINET_STUDIO_NO_SPLASH", "1")
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui import theme
    from cabinet_studio.ui.main_window import CabinetStudioApp
    from cabinet_studio.ui.shell import main_shell

    shown = []
    monkeypatch.setattr(main_shell, "ask_choice", lambda *a, **k: shown.append(a[2]) or "ok")
    monkeypatch.setattr("cabinet_studio.ui.manual.webbrowser.open", lambda *a, **k: True)
    errors: list[str] = []
    app = CabinetStudioApp(load_library())
    app.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb)))
    try:
        app.update()
        bar = app.nametowidget(tk.Misc.cget(app, "menu"))
        assert [bar.entrycget(i, "label") for i in range(bar.index("end") + 1)] == ["File", "Edit", "View", "Tools", "Help"]
        assert int(app.main_header.cget("height")) == main_shell.HEADER_HEIGHT == 44
        hits: list[str] = []
        targets = ("new_project", "new_from_template", "new_build_with_ai", "open_project", "save", "save_as", "open_programs",
                   "install_desktop_shortcut", "_on_close", "undo", "delete_selected", "add_blank", "view_drawings",
                   "generate_drawings", "open_programming", "guide_build", "ai_suggest", "apply_all_ai_suggestions",
                   "open_ul508a_review")
        for name in targets:
            monkeypatch.setattr(app, name, lambda n=name: hits.append(n))
        for path, idx, cid in app.commands.menu_entries():
            app.commands.menus[path].invoke(idx)
            app.update()
            if cid == "main.theme.light":
                assert not theme.is_dark() and app.canvas_view.canvas.cget("bg") == "#f3f3f5"
                assert app.theme_button.cget("text") == "☾ Dark"
            elif cid == "main.theme.dark":
                assert theme.is_dark() and app.canvas_view.canvas.cget("bg") == "#0d0d0f"
                assert app.theme_button.cget("text") == "☀ Light"
        assert set(hits) == set(targets)
        assert shown == ["Keyboard shortcuts", "About Cabinet Studio"]
        hits.clear()
        for b in _buttons(app.main_toolbar):
            b.invoke()
            app.update()
        assert set(hits) == {"new_project", "new_from_template", "open_project", "save", "undo", "generate_drawings", "view_drawings",
                             "open_programming", "open_ul508a_review"}
        rail = {_norm(b.cget("text")) for b in _buttons(app.rail)}
        assert {"Drawings", "View drawings", "Programming"} <= rail
        values = app.rail.maker_menu.cget("values")
        assert values[:4] == ["All makers", "Allen-Bradley", "Siemens", "Omron"]
        for maker in ("Omron", "Siemens", "All makers"):
            app.rail.maker_menu._dropdown_callback(maker)
            app.update()
            shown_vendors = {w.cget("text").split("·")[-1].strip() for w in _walk_widgets(app.rail.catalog_host)
                             if isinstance(w, ctk.CTkLabel) and "·" in str(w.cget("text"))}
            if maker != "All makers":
                assert shown_vendors == {maker}, (maker, shown_vendors)
            else:
                assert {"Allen-Bradley", "Siemens", "Omron"} <= shown_vendors
        assert not errors, "\n\n".join(errors)
    finally:
        app.destroy()
        theme.set_mode("dark", save=False)


# --------------------------------------------------------------------------- v0.3.23 Phase 2

LAYOUT_THEME_COMBOS = [("studio", "light"), ("studio", "dark"), ("classic", "light"), ("classic", "dark")]


def _set_layout_theme(v, layout, mode):
    from cabinet_studio.ui import theme

    v.invoke_command(f"view.layout.{layout}")
    theme.set_mode(mode, save=False)
    _pump(v)
    assert v._built_layout == layout
    assert theme.is_dark() == (mode == "dark")


def _logic(program):
    from cabinet_studio.services.ladder_ir import program_to_ladder_ir
    from cabinet_studio.services.programming import program_from_dict

    ir = program_to_ladder_ir(program_from_dict(program))
    return ([r["elements"] for r in ir["rungs"]],
            {k: [r["elements"] for r in rr] for k, rr in (ir.get("routines") or {}).items()})


def _assert_round_trip_exact(program, label):
    from cabinet_studio.services.plcopen_xml import (
        export_program_to_plcopen_xml,
        import_plcopen_xml_to_program_checked,
    )

    xml = export_program_to_plcopen_xml(program, project_name="Gate")
    back, _warnings = import_plcopen_xml_to_program_checked(xml)
    assert _logic(back) == _logic(program), f"{label}: PLCopen round trip is not exact"


def _give_io(v):
    fields = v.project.items[0].fields
    fields["io_direction"], fields["io_address"] = "Input", "Local:1:I.Data.0"
    v.project.items[2].fields.update(io_direction="Output", io_address="Local:2:O.Data.0")
    v._device_map = __import__("cabinet_studio.services.programming", fromlist=["devices_by_tag"]).devices_by_tag(
        v.project)


def test_gate_v0323_organizer_every_node_type_both_layouts_and_themes(ui):
    """Every Controller Organizer node kind is clicked (and double-clicked) in Studio and Classic,
    Light and Dark; the pane collapses / expands and its width is remembered."""
    from cabinet_studio.ui.prefs import load_pref
    from cabinet_studio.ui.studio.organizer import KINDS

    v = ui
    _give_io(v)
    _fill_fields(v)
    v._rung_field_vars["sbr_name"].set("Motor")
    v.invoke_command("rung.add_sbr")
    v._rung_field_vars["jsr_target"].set("Motor")
    v.invoke_command("rung.add_jsr")
    for layout, mode in LAYOUT_THEME_COMBOS:
        _set_layout_theme(v, layout, mode)
        org = v.organizer
        org.refresh(force=True)
        nodes = org.nodes_by_kind()
        assert set(KINDS) <= set(nodes), f"{layout}/{mode}: missing node kinds {set(KINDS) - set(nodes)}"
        assert "r:Main" in nodes["routine"] and "r:Motor" in nodes["routine"]
        assert "iop:PB_Start" in nodes["io_point"] and "ct:M1" in nodes["tag"]
        # A real click through the Treeview binding.
        org.tree.selection_set("r:Main")
        _pump(v)
        assert v._tab == "ladder"
        for kind in KINDS:
            for iid in nodes[kind][:3]:
                assert org.open_node(iid) == kind
                _pump(v, 1)
                assert org.open_node(iid, double=True) == kind
                _pump(v, 1)
        org.open_node("r:Motor")
        assert v._tool_window_open("routine") and "Motor" in v.status.cget("text")
        org.open_node("ctags")
        assert v._tool_window_open("tags")
        org.open_node("iop:PB_Start")
        assert "PB_Start" in v.status.cget("text") and "Local:1:I.Data.0" in v.status.cget("text")
        org.open_node("iop:PB_Start", double=True)
        assert v._tag_filter_var.get() == "PB_Start"
        v._close_all_tool_windows()
        # Collapse with the pane button, expand from the menu.
        org.collapse_btn.invoke()
        _pump(v)
        assert not v.pane_visible("organizer") and load_pref("prog_organizer_visible") is False
        _menu_invoke(v, "view.organizer")
        assert v.pane_visible("organizer") and load_pref("prog_organizer_visible") is True
        _assert_clean(v)
    # Width is remembered across a rebuild.
    scale = v._pane_scale()
    v._work.sash_place(0, int(320 * scale), 1)
    _pump(v)
    v._save_pane_widths()
    saved = load_pref("prog_organizer_width")
    assert abs(saved - 320) <= 4, saved
    v.invoke_command("view.layout.classic")
    v.invoke_command("view.layout.studio")
    _pump(v)
    assert abs(v.organizer.winfo_width() / scale - saved) <= 6
    _assert_clean(v)


def test_gate_v0323_palette_every_button_inserts_verifies_and_round_trips(ui):
    """Every instruction-palette button (each Studio 5000 tab) inserts through the existing editor
    path, is verified, and keeps the PLCopen round trip exact — both layouts, both themes."""
    from cabinet_studio.ui.studio.palette import ITEMS, PALETTE_GROUPS

    v = ui
    _fill_fields(v)
    assert [g for g, _ in PALETTE_GROUPS] == ["Bit", "Timer/Counter", "Compare", "Compute/Math", "Move/Logical",
                                              "Program Control"]
    for layout, mode in LAYOUT_THEME_COMBOS:
        _set_layout_theme(v, layout, mode)
        pal = v.palette
        assert set(pal.buttons) == set(ITEMS)
        for group, items in PALETTE_GROUPS:
            pal.show_group(group)
            _pump(v, 1)
            assert pal.current_group == group and pal.tabs.get() == group
            for item in items:
                btn = pal.buttons[item.mnemonic]
                assert btn.winfo_ismapped(), f"{item.mnemonic} not shown on tab {group}"
                v._rung_field_vars["sbr_name"].set(f"P{layout}{mode}")
                v._rung_field_vars["jsr_target"].set(f"P{layout}{mode}")
                btn.invoke()
                _pump(v, 1)
                assert pal.last_result == (item.mnemonic, True), \
                    f"{layout}/{mode} {item.mnemonic}: nothing inserted ({v.status.cget('text')})"
                assert pal.result.cget("text").startswith(f"{item.mnemonic} inserted · verify:")
                _assert_round_trip_exact(v.program, f"{layout}/{mode} {item.mnemonic}")
        v._draw_ladder()
        _assert_wired(v, f"palette {layout}/{mode}")
        _drawn_parts_match_program(v, f"palette {layout}/{mode}")
        _assert_clean(v)


def test_gate_v0323_properties_edits_and_live_values(ui):
    """Properties pane: comment, preset, note, description and operand rename all apply through the
    safe editor functions (undoable); live values show while simulating — both layouts and themes."""
    from cabinet_studio.services.ladder_ir import program_rung_to_elements

    v = ui
    _fill_fields(v)
    for n, (layout, mode) in enumerate(LAYOUT_THEME_COMBOS):
        _set_layout_theme(v, layout, mode)
        props = v.properties
        first = v.program["rungs"][0]["id"]
        v._select_rung(first)
        _pump(v, 1)
        assert props.rung_id == first and props.rows
        props.comment_box.delete("1.0", "end")
        props.comment_box.insert("1.0", f"Comment {n}")
        _invoke(v, "Apply comment", root=props)
        assert v.program["rungs"][0]["comment"] == f"Comment {n}"
        # Row: note + description + rename in one Apply.
        row = next(r for r in props.rows if r["tag"])
        old = row["tag"]
        new = f"{old.split('_')[0]}_R{n}"
        row["note_entry"].delete(0, "end")
        row["note_entry"].insert(0, f"note {n}")
        row["desc_entry"].delete(0, "end")
        row["desc_entry"].insert(0, f"desc {n}")
        row["tag_entry"].delete(0, "end")
        row["tag_entry"].insert(0, new)
        row_buttons = [b for b in _buttons(props.body) if _norm(b.cget("text")) == "Apply"]
        row_buttons[props.rows.index(row)].invoke()
        _pump(v, 1)
        rung = v.program["rungs"][0]
        els = program_rung_to_elements(rung)
        assert any(e.get("var") == new for e in els), f"rename {old}→{new} not applied"
        assert any(e.get("desc") == f"note {n}" for e in els)
        assert (v.program.get("tag_descriptions") or {}).get(old.split(".")[0]) == f"desc {n}"
        _assert_round_trip_exact(v.program, f"{layout}/{mode} properties")
        # Preset on a timer rung.
        v.palette.show_group("Timer/Counter")
        v.palette.buttons["TON"].invoke()
        _pump(v, 1)
        assert props.preset_entry is not None
        props.preset_entry.delete(0, "end")
        props.preset_entry.insert(0, str(2500 + n))
        _invoke(v, "Apply preset", root=props)
        assert v.program["rungs"][-1]["timer"]["pt_ms"] == 2500 + n
        v.invoke_command("edit.undo")
        assert v.program["rungs"][-1]["timer"]["pt_ms"] != 2500 + n
        # Live values while simulating, cleared on Stop.
        v._select_rung(v.program["rungs"][0]["id"])
        v.invoke_command("sim.step_scan")
        _pump(v, 1)
        live = [lbl.cget("text") for lbl, _el in props.live_labels]
        assert any(t in {"ON", "OFF"} for t in live), live
        v.invoke_command("sim.stop")
        _pump(v, 1)
        assert all(lbl.cget("text") == "" for lbl, _el in props.live_labels)
        props.collapse_btn.invoke()
        assert not v.pane_visible("properties")
        _menu_invoke(v, "view.properties")
        assert v.pane_visible("properties")
        _assert_clean(v)


def test_gate_v0323_program_wizard_next_back_finish_cancel(ui):
    """The New Program / Routine wizard: Next / Back / Finish / Cancel / Ask AI for every kind,
    opened from the toolbar (Studio) and the classic strip, Light and Dark."""
    from cabinet_studio.ui.studio.program_wizard import KINDS, STEPS

    v = ui
    for layout, mode in LAYOUT_THEME_COMBOS:
        _set_layout_theme(v, layout, mode)
        opener = "New…" if layout == "studio" else "New program wizard"
        for kind, _title, _blurb in KINDS:
            _invoke(v, opener, toplevel=v)
            w = v._wizard
            assert w is not None and w.winfo_exists() and w.step == 0
            assert w.back_btn.cget("state") == "disabled" and w.finish_btn.cget("state") == "disabled"
            w.kind_buttons[kind].invoke()
            assert w.kind_var.get() == kind
            _invoke(v, "Next ›", root=w)
            assert w.step == 1
            _invoke(v, "‹ Back", root=w)
            assert w.step == 0
            _invoke(v, "Next ›", root=w)
            if kind == "subroutine":
                w.sub_name.set("Main")
                _invoke(v, "Next ›", root=w)
                assert w.step == 1, "routine name Main must be refused"
                w.sub_name.set(f"W{layout}{mode}")
            _invoke(v, "Next ›", root=w)
            assert w.step == len(STEPS) - 1 and w.finish_btn.cget("state") == "normal"
            rungs_before = len(v.program["rungs"])
            _invoke(v, "Finish", root=w)
            assert v._wizard is None and not w.winfo_exists()
            if kind == "program":
                assert v.program["rungs"] and v._answers
            elif kind == "subroutine":
                assert f"W{layout}{mode}" in (v.program.get("routines") or {})
                assert any(el.get("kind") == "jsr" and el.get("target") == f"W{layout}{mode}"
                           for el in v.program["rungs"][-1].get("elements") or [])
            else:
                assert len(v.program["rungs"]) > rungs_before, f"{kind}: nothing added"
            _assert_round_trip_exact(v.program, f"wizard {kind}")
        # Cancel changes nothing; Ask AI opens the assistant.
        snapshot = json_dumps_rung(v.program)
        w = v.open_program_wizard()
        _invoke(v, "Ask AI", root=w)
        _invoke(v, "Cancel", root=w)
        assert v._wizard is None and json_dumps_rung(v.program) == snapshot
        _assert_clean(v)


def test_gate_v0323_main_window_project_explorer_and_compact_rail(tmp_path, monkeypatch):
    """Main window: every Project explorer node kind (click + double-click), explorer collapse /
    expand / width, compact rail on / off with the sticky OUTPUT kept — Light and Dark."""
    monkeypatch.setenv("CABINET_STUDIO_NO_SPLASH", "1")
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.models.project import PlacedItem
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui import theme
    from cabinet_studio.ui.main_window import CabinetStudioApp
    from cabinet_studio.ui.prefs import load_pref
    from cabinet_studio.ui.shell.project_explorer import COMPACT_RAIL_WIDTH

    errors: list[str] = []
    app = CabinetStudioApp(load_library())
    app.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb)))
    try:
        app.update()
        app.project.items.extend([
            PlacedItem(id="d1", library_id=None, type_id="pushbutton", x=10, y=10,
                       fields={"tag": "PB1", "io_direction": "Input", "io_address": "Local:1:I.Data.0"}),
            PlacedItem(id="d2", library_id=None, type_id="contactor", x=40, y=10, fields={"tag": "M1"}),
        ])
        app._refresh_all()
        hits: list[str] = []
        for name in ("edit_item", "generate_drawings", "view_drawings", "open_programming", "open_programs"):
            monkeypatch.setattr(app, name, lambda *a, n=name: hits.append(n))
        exp = app.project_explorer
        for mode in ("light", "dark"):
            theme.set_mode(mode, save=False)
            app.update()
            exp.refresh(force=True)
            nodes = exp.nodes_by_kind()
            assert {"cabinet", "folder", "device", "io_point", "action"} <= set(nodes)
            for kind, iids in nodes.items():
                for iid in iids:
                    if exp.tree.exists(iid):
                        assert exp.open_node(iid) == kind
                        app.update()
                    if exp.tree.exists(iid):
                        assert exp.open_node(iid, double=True) == kind
                        app.update()
            exp.tree.selection_set("dev:d1")
            app.update()
            assert app.selected_id == "d1"
            assert {"edit_item", "generate_drawings", "view_drawings", "open_programming", "open_programs"} <= set(hits)
            hits.clear()
            # Explorer collapse (pane button) / expand (toolbar), width drag remembered.
            exp.collapse_btn.invoke()
            app.update()
            assert not exp.winfo_ismapped() and load_pref("main_explorer_visible") is False
            _invoke_app(app, "Explorer")
            assert exp.winfo_ismapped() and load_pref("main_explorer_visible") is True
            sash = app._explorer_sash
            sash.event_generate("<ButtonPress-1>", rootx=100, rooty=100)
            sash.event_generate("<B1-Motion>", rootx=160, rooty=100)
            sash.event_generate("<ButtonRelease-1>", rootx=160, rooty=100)
            app.update()
            assert load_pref("main_explorer_width") == int(exp.cget("width"))
            # Compact rail: library body hides, sticky OUTPUT stays.
            _invoke_app(app, "Compact rail")
            assert app._rail_compact_var.get() and int(app.rail.cget("width")) == COMPACT_RAIL_WIDTH
            assert not app.rail.body.winfo_ismapped() and app.rail.output.winfo_ismapped()
            assert {"Drawings", "View drawings", "Programming"} <= {_norm(b.cget("text")) for b in _buttons(app.rail.output)}
            _invoke_app(app, "Compact rail")
            assert not app._rail_compact_var.get() and app.rail.body.winfo_ismapped() and app.rail.output.winfo_ismapped()
            assert load_pref("main_rail_compact") is False
        assert not errors, "\n\n".join(errors)
    finally:
        app.destroy()
        theme.set_mode("dark", save=False)


def _invoke_app(app, label):
    for b in _buttons(app.main_toolbar):
        if _norm(b.cget("text")) == label:
            b.invoke()
            app.update()
            return b
    raise AssertionError(f"toolbar button {label!r} not found")


# ---------------------------------------------------------------- v0.3.24 wiring + live timers
def _assert_wired(v, label=""):
    """Every wire end lands on a rail, a part terminal or another wire; every part terminal has a
    wire; no wire runs through a part. Catches short wires, overshoots and stray segments."""
    tol = 1.0
    segs = list(v._wire_segments)
    rows: dict[int, list] = {}
    cols: dict[int, list] = {}
    for s in segs:
        x1, y1, x2, y2 = s
        if abs(y1 - y2) < tol:
            rows.setdefault(round(y1), []).append((min(x1, x2), max(x1, x2)))
        elif abs(x1 - x2) < tol:
            cols.setdefault(round(x1), []).append((min(y1, y2), max(y1, y2)))
        else:
            raise AssertionError(f"{label}: diagonal wire {s}")

    def touches_wire(px, py, own):
        hits = 0
        for a, b in rows.get(round(py), []):
            if a - tol <= px <= b + tol:
                hits += 1
        for a, b in cols.get(round(px), []):
            if a - tol <= py <= b + tol:
                hits += 1
        return hits > own

    problems = []
    for x1, y1, x2, y2 in segs:
        for px, py in ((x1, y1), (x2, y2)):
            if any(abs(px - rx) <= 3 and r0 <= py <= r1 for rx, r0, r1 in v._rails):
                continue
            if any(abs(px - tx) <= tol and abs(py - ty) <= tol for tx, ty in v._terminals):
                continue
            if touches_wire(px, py, 1):
                continue
            problems.append(f"loose wire end at ({px:.0f},{py:.0f})")
    ends = {(round(x), round(y)) for s in segs for x, y in ((s[0], s[1]), (s[2], s[3]))}
    for tx, ty in v._terminals:
        if (round(tx), round(ty)) not in ends:
            problems.append(f"part terminal at ({tx:.0f},{ty:.0f}) has no wire")
    for x0, x1, y in v._bodies:
        for a, b in rows.get(round(y), []):
            if a < x1 - tol and b > x0 + tol:
                problems.append(f"wire runs through the part at ({x0:.0f}..{x1:.0f},{y:.0f})")
    assert not problems, f"{label}: " + "; ".join(problems[:12])


def _drawn_parts_match_program(v, label=""):
    from cabinet_studio.ui.programming_viewer import _el_kind

    def count(items):
        n = 0
        for el in items or []:
            if not isinstance(el, dict):
                continue
            n += sum(count(b) for b in el.get("branches") or []) if _el_kind(el) == "or" else 1
        return n

    want = 0
    for rung in v.program.get("rungs") or []:
        els = v._rung_draw_elements(rung)
        want += count(els) or 0
        if not any(isinstance(e, dict) and _el_kind(e) in {"coil", "timer", "counter", "math", "jsr", "ret",
                                                            "oneshot_out"} for e in els):
            want += 1  # "?" output placeholder
    assert len(v._bodies) == want, f"{label}: {len(v._bodies)} parts drawn, program has {want}"


def _flow_for_every_instruction(v, label=""):
    """After a scan every top-level instruction of every rung has a power-flow record (it executed)."""
    from cabinet_studio.services.ladder_ir import program_to_ladder_ir
    from cabinet_studio.services.programming import program_from_dict

    for rung in program_to_ladder_ir(program_from_dict(v.program))["rungs"]:
        for j, _el in enumerate(rung.get("elements") or []):
            assert f"{rung['id']}|L|{j}" in v._sim_flow, f"{label}: {rung['id']} element {j} did not execute"


def test_gate_v0324_test_bench_ladder_wires_connect_static_and_simulating(ui):
    """The 83-rung PLC Sim Test Bench (every instruction family, nested ORs, mid-rung coils):
    every wire meets its parts, before and while simulating, in both themes."""
    import json
    from pathlib import Path

    from cabinet_studio.services.programming import program_from_dict

    v = ui
    data = json.loads((Path(__file__).parent / "data" / "PLC-Sim-Test-Bench.cabinet.json").read_text(encoding="utf-8"))
    v.program = program_from_dict(data["program"])
    for layout, mode in LAYOUT_THEME_COMBOS[:2]:
        _set_layout_theme(v, layout, mode)
        v._draw_ladder()
        _assert_wired(v, f"static {mode}")
        _drawn_parts_match_program(v, f"static {mode}")
    v._sim_step()
    v._sim_step()
    _pump(v)
    _assert_wired(v, "after two scans")
    _drawn_parts_match_program(v, "after two scans")
    _flow_for_every_instruction(v, "test bench")
    live = [s for s in v.canvas.find_all() if v.canvas.type(s) == "line" and v.canvas.itemcget(s, "width") == "4.0"]
    assert live, "no energized (green) wires while simulating"
    v._sim_stop()
    _assert_clean(v)


def test_gate_v0324_every_add_and_edit_action_draws_connected_and_runs(ui):
    """Every Add-instruction button, series / parallel contact, and an OR branch holding every
    instruction kind: drawn fully connected after each placement, and each placed part executes."""
    from cabinet_studio.services.programming import add_rung_from_elements

    v = ui
    _fill_fields(v)
    for label in ADD_BUTTONS:
        before = json_dumps_rung(v.program)
        _invoke(v, label, toplevel=v)
        assert json_dumps_rung(v.program) != before, f"{label} added nothing: {v.status.cget('text')}"
        _assert_wired(v, label)
        _drawn_parts_match_program(v, label)
    for rung_index in (0, -1):
        v._selected_rung_id = v.program["rungs"][rung_index]["id"]
        v.contact_var.set("PB_Stop")
        v._add_series_contact()
        _assert_wired(v, "series contact")
        v._selected_rung_id = v.program["rungs"][rung_index]["id"]
        v._add_parallel_contact()
        _assert_wired(v, "parallel contact")
        _drawn_parts_match_program(v, "parallel contact")
    every_kind = [
        {"kind": "or", "branches": [
            [{"kind": "contact", "var": "PB_Start", "form": "NO"},
             {"kind": "or", "branches": [[{"kind": "contact", "var": "A1", "form": "NC"}],
                                         [{"kind": "compare", "op": "GRT", "source_a": "N7", "source_b": "2"}]]}],
            [{"kind": "contact", "var": "PB_Stop", "form": "NO"},
             {"kind": "timer", "var": "TB", "block": "TON", "pt_ms": 700},
             {"kind": "counter", "var": "CB", "block": "CTU", "pv": 3}],
            [{"kind": "oneshot", "block": "ONS", "var": "OSB"},
             {"kind": "math", "op": "ADD", "dest": "N8", "source_a": "N8", "source_b": "1"},
             {"kind": "coil", "var": "MidB", "form": "normal"}],
        ]},
        {"kind": "oneshot", "block": "OSR", "var": "OSS", "output": "PulseB"},
        {"kind": "coil", "var": "M1", "form": "normal"},
    ]
    v.program = add_rung_from_elements(v.program, every_kind, comment="every kind in branches")
    v._draw_ladder()
    _assert_wired(v, "every kind in OR branches")
    _drawn_parts_match_program(v, "every kind in OR branches")
    texts = " ".join(v.canvas.itemcget(i, "text") for i in v.canvas.find_all() if v.canvas.type(i) == "text")
    for word in ("TB", "CB", "OSB", "N8", "MidB", "GRT", "PulseB"):
        assert word in texts, f"{word} placed in an OR branch is not drawn"
    v._sim_step()
    _pump(v)
    _assert_wired(v, "every kind simulating")
    _flow_for_every_instruction(v, "every add")
    v._sim_stop()
    _assert_clean(v)


def test_gate_v0324_timer_counts_live_between_rung_visits_and_pause_freezes(ui, monkeypatch):
    """1 s / rung run: a TON keeps timing between visits to its rung; its box shows ACC in
    seconds, time left and a bar, updated in place; DN lights the next rung; Pause freezes it."""
    from types import SimpleNamespace

    from cabinet_studio.services.programming import add_rung_from_elements
    from cabinet_studio.ui import programming_viewer as pv

    v = ui
    clock = [500.0]
    monkeypatch.setattr(pv, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    prog = v.program
    prog = add_rung_from_elements(prog, [{"kind": "contact", "var": "PB_Start", "form": "NO"},
                                         {"kind": "timer", "var": "T5", "block": "TON", "pt_ms": 2000}])
    prog = add_rung_from_elements(prog, [{"kind": "contact", "var": "T5.DN", "form": "NO"},
                                         {"kind": "coil", "var": "Lamp", "form": "normal"}])
    v.program = prog
    v._draw_ladder()
    _speed_menus(v, toplevel=v)[0]._dropdown_callback("1 s / rung")
    _pump(v)
    _invoke(v, "Run", toplevel=v)
    v._sim_cancel_timer()
    _click_part(v, "contact", "PB_Start")
    sim = v._ensure_scan_sim()
    while v._sim_cursor_rung_id != v.program["rungs"][1]["id"]:
        _tick(v)
    assert sim.timers["T5"]["tt"] and sim.timers["T5"]["acc_ms"] == 0

    def texts():
        return " ".join(v.canvas.itemcget(i, "text") for i in v.canvas.find_all() if v.canvas.type(i) == "text")

    assert "TON  on-delay" in texts() and "PRE 2.0 s" in texts()
    acc_item = v._timer_live["T5"][0]["acc"]
    v._sim_running = True
    clock[0] += 0.5
    v._sim_timer_tick()
    v._sim_cancel_timer()
    assert sim.timers["T5"]["acc_ms"] == 500
    assert v.canvas.itemcget(acc_item, "text") == "ACC 0.5 s", "timer box did not count up in place"
    assert "1.5 s left" in texts()
    bx0, bx1, _by0, _by1 = v._timer_live["T5"][0]["bar_x"]
    assert abs(v.canvas.coords(v._timer_live["T5"][0]["bar"])[2] - (bx0 + (bx1 - bx0) * 0.25)) < 1
    clock[0] += 1.6
    v._sim_timer_tick()
    v._sim_cancel_timer()
    assert sim.timers["T5"]["q"] and sim.timers["T5"]["acc_ms"] == 2000
    assert "DN  done" in texts() and "ACC 2.0 s" in texts()
    assert any("T5" in w.cget("text") and "2.0/2.0s DN" in w.cget("text")
               for w in v._force_value_widgets.values()), "I/O strip timer did not update"
    while v._sim_cursor_rung_id != v.program["rungs"][2]["id"]:
        _tick(v)
    assert sim.read("Lamp"), "T5.DN did not turn the lamp on"

    # Pause while timing: paused time is not counted.
    _click_part(v, "timer", "T5")
    while v._sim_cursor_rung_id != v.program["rungs"][1]["id"]:
        _tick(v)
    clock[0] += 0.4
    v._sim_timer_tick()
    v._sim_cancel_timer()
    _invoke(v, "Pause", toplevel=v)
    assert sim.timers["T5"]["acc_ms"] == 400
    clock[0] += 30
    _invoke(v, "Run", toplevel=v)
    v._sim_cancel_timer()
    assert sim.timers["T5"]["acc_ms"] == 400, "time spent paused was counted"
    clock[0] += 0.3
    v._sim_timer_tick()
    v._sim_cancel_timer()
    assert sim.timers["T5"]["acc_ms"] == 700
    v._sim_stop()
    _assert_clean(v)


# ------------------------------------------------------------------ v0.3.25
def _checkbox(v, text):
    for w in _all_widgets(v):
        if isinstance(w, ctk.CTkCheckBox) and w.cget("text") == text and w.winfo_toplevel() is v:
            return w
    raise AssertionError(f"no '{text}' checkbox")


def test_gate_v0325_ai_transcript_copy_paste(ui):
    v = ui
    _invoke(v, "Run", toplevel=v)
    v._sim_pause()
    _invoke(v, "Ask AI", toplevel=v)
    win = v._ai_window
    _invoke(v, "Explain this rung", root=win, toplevel=win)
    v.clipboard_clear()
    _invoke(v, "Copy all", root=win, toplevel=win)
    assert "Pick a quick question" in v.clipboard_get()
    inner = win.transcript._textbox
    inner.tag_add("sel", "1.0", "1.4")
    win._copy_menu.invoke(0)
    assert v.clipboard_get() == "Pick"
    inner.event_generate("<Button-1>", x=5, y=5)
    inner.event_generate("<Control-a>")
    inner.event_generate("<Control-c>")
    _pump(v)
    assert "Pick a quick question" in v.clipboard_get()
    win._copy_menu.invoke(2)
    win._copy_menu.invoke(1)
    assert "Explain" in v.clipboard_get() or "Rung" in v.clipboard_get()
    assert str(inner.cget("state")) == "disabled", "transcript must stay read-only"
    v._sim_stop()


def test_gate_v0325_each_part_lights_left_to_right(ui, tmp_path, monkeypatch):
    from cabinet_studio.services.programming import add_rung_from_elements, empty_program
    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(pv, "_ui_prefs_path", lambda: tmp_path / "ui_prefs.json")
    v = ui
    v.program = add_rung_from_elements(empty_program(), [
        {"kind": "contact", "var": "PB_Start", "form": "NO"},
        {"kind": "contact", "var": "Stop", "form": "NC"},
        {"kind": "coil", "var": "Motor", "form": "normal"}])
    v._draw_ladder()
    _checkbox(v, "Each part").toggle()
    assert v._sim_parts_var.get()
    _speed_menus(v, toplevel=v)[0]._dropdown_callback("1 s / rung")
    _invoke(v, "Run", toplevel=v)
    v._sim_cancel_timer()
    v._sim_running = False
    _click_part(v, "contact", "PB_Start")
    v._sim_step_rung()
    v.after_cancel(v._sim_part_after)
    rid = str(v.program["rungs"][0]["id"])
    assert not any(k.startswith(rid + "|") for k in v._sim_flow), "rung lit before its parts were walked"
    seen = []
    for _ in range(3):
        v._sim_part_tick()
        v.after_cancel(v._sim_part_after)
        seen.append(v._sim_status.cget("text"))
        rects = [i for i in v.canvas.find_all() if v.canvas.type(i) == "rectangle"
                 and v.canvas.itemcget(i, "outline") == pv._PART_HILITE]
        assert len(rects) == 1, "the current part is not highlighted"
    assert "part 1/3: XIC PB_Start → TRUE - power passes" in seen[0]
    assert "part 2/3: XIO Stop → TRUE - power passes" in seen[1]
    assert "part 3/3: OTE Motor → energized (ON)" in seen[2]
    v._sim_part_tick()
    assert v._sim_parts is None and v._sim_part_key is None
    assert v._sim_flow[f"{rid}|L|2"]["in"] and v._sim_energized.get(rid)
    _checkbox(v, "Each part").toggle()
    assert not v._sim_parts_var.get()
    v._sim_stop()


def test_gate_v0325_normal_run_presses_buttons_in_order(ui, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from cabinet_studio.services.programming import add_rung_from_elements, empty_program
    from cabinet_studio.services.sim_autorun import normal_run_plan
    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(pv, "_ui_prefs_path", lambda: tmp_path / "ui_prefs.json")
    clock = [100.0]
    monkeypatch.setattr(pv, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    v = ui
    prog = add_rung_from_elements(empty_program(), [
        {"kind": "or", "branches": [[{"kind": "contact", "var": "Start_PB", "form": "NO"}],
                                    [{"kind": "contact", "var": "Motor", "form": "NO"}]]},
        {"kind": "contact", "var": "Stop_PB", "form": "NO"},
        {"kind": "contact", "var": "OL_Trip", "form": "NC"},
        {"kind": "coil", "var": "Motor", "form": "normal"}])
    prog = add_rung_from_elements(prog, [
        {"kind": "contact", "var": "Motor", "form": "NO"},
        {"kind": "contact", "var": "Part_Present", "form": "NO"},
        {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 1000}])
    prog = add_rung_from_elements(prog, [
        {"kind": "contact", "var": "T1.DN", "form": "NO"},
        {"kind": "coil", "var": "Weld", "form": "normal"}])
    v.program = prog
    v._draw_ladder()
    sim0 = v._ensure_scan_sim(reset=True)
    labels = [s["label"] for s in normal_run_plan(
        [v._rung_draw_elements(r) for r in v._sim_rungs()], sim0.input_tags())]
    assert labels == ["Make safe / ready: Stop_PB ON, OL_Trip OFF", "Press Start_PB", "Release Start_PB",
                      "Part_Present turns ON"]
    _speed_menus(v, toplevel=v)[0]._dropdown_callback("0.25 s / rung")
    _invoke(v, "Normal run", toplevel=v)
    v._sim_cancel_timer()
    assert v._sim_auto is not None and v._sim_auto["i"] == 1
    assert "[Normal run 1/3: Make safe" in v._sim_status.cget("text"), "Part_Present is the pretend machine's"
    assert v._sim_plant is not None and v._sim_plant.parts == ["Part_Present"]
    sim = v._ensure_scan_sim()
    pressed_seen = weld_seen = False
    for _ in range(300):
        if v._sim_auto is None:
            break
        clock[0] += 0.3
        _tick(v)
        if v._sim_auto_after is not None:
            v.after_cancel(v._sim_auto_after)
        v._sim_auto_tick()
        pressed_seen |= sim.forces.get("Start_PB") is True
    assert v._sim_auto is None, "normal run never finished"
    assert pressed_seen and "Start_PB" not in sim.forces, "start must be pressed then released"
    for _ in range(80):
        clock[0] += 0.25
        _tick(v)
        if v._sim_auto_after is not None:
            v.after_cancel(v._sim_auto_after)
        v._sim_auto_tick()
        weld_seen |= sim.read("Weld")
    if v._sim_auto_after is not None:
        v.after_cancel(v._sim_auto_after)
    assert sim.read("Motor"), "motor did not seal in after the start press"
    assert weld_seen, "timer never finished while a part sat at the sensor"
    v._sim_stop()
    assert v._sim_auto is None


def test_gate_v0325_explain_run_narrates_each_part(ui, tmp_path, monkeypatch):
    from cabinet_studio.services.programming import add_rung_from_elements, empty_program
    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(pv, "_ui_prefs_path", lambda: tmp_path / "ui_prefs.json")
    v = ui
    prog = add_rung_from_elements(empty_program(), [
        {"kind": "contact", "var": "PB_Start", "form": "NO", "desc": "Start button"},
        {"kind": "contact", "var": "Stop", "form": "NC"},
        {"kind": "coil", "var": "Motor", "form": "normal"}])
    prog = add_rung_from_elements(prog, [
        {"kind": "contact", "var": "Motor", "form": "NO"},
        {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 2000}])
    v.program = prog
    v._draw_ladder()
    _invoke(v, "Explain run", toplevel=v)
    win = v._explain_win
    assert win is not None and win.winfo_exists()
    _speed_menus(v, toplevel=v)[0]._dropdown_callback("1 s / rung")
    v._sim_step_rung()
    text = win.text_value()
    assert "Rung 1/2" in text
    assert "XIC PB_Start (Start button): WAITING for PB_Start to turn ON (it is OFF)" in text
    assert "an input" in text and "power stops at XIC PB_Start" in text
    v._sim_step_rung()
    assert "XIC Motor: WAITING for Motor to turn ON (it is OFF) - it comes from rung 1" in win.text_value()
    assert "TON T1: WAITING for power to start timing" in win.text_value()
    _click_part(v, "contact", "PB_Start")
    assert ">> PB_Start switched ON" in win.text_value()
    v._sim_step_rung()
    text = win.text_value().split(">> PB_Start switched ON")[-1]
    assert "XIC PB_Start (Start button): needs PB_Start ON and it is ON -> passes power on." in text
    assert "XIO Stop: needs Stop OFF and it is OFF -> passes power on." in text
    assert "OTE Motor: gets power -> Motor turns ON." in text and "rung ENERGIZED" in text
    _checkbox(v, "Each part").toggle()
    v._sim_step_rung()
    v.after_cancel(v._sim_part_after)
    assert "(watching each part...)" in win.text_value()
    v._sim_part_tick()
    v.after_cancel(v._sim_part_after)
    assert win.text_value().rstrip().endswith("needs Motor ON and it is ON -> passes power on.")
    v._sim_part_tick()
    v.after_cancel(v._sim_part_after)
    assert "TON T1: has power, TIMING" in win.text_value()
    v._sim_part_tick()
    assert "RESULT:" in win.text_value().split("TIMING")[-1]
    _checkbox(v, "Each part").toggle()
    v._sim_running = True
    v._sim_pause()
    assert "PAUSED - you pressed Pause" in win.text_value()
    v.clipboard_clear()
    _invoke(v, "Copy all", root=win, toplevel=win)
    assert "PAUSED - you pressed Pause" in v.clipboard_get()
    _invoke(v, "Clear", root=win, toplevel=win)
    assert not win.text_value().strip()
    _invoke(v, "Explain run", toplevel=v)
    assert v._explain_win is win, "second click must reuse the open window"
    v._sim_stop()
    assert "SIM STOPPED." in win.text_value()
    win.destroy()


def test_gate_v0325_interview_use_ai_answer_and_accept_all(ui):
    from cabinet_studio.services import ai_build as ab
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.services.standards import default_profile
    from cabinet_studio.ui.ai_build import AiBuildDialog

    v = ui
    dlg = AiBuildDialog(v, v.fonts, load_library(), default_profile())
    dlg.present()
    _pump(v)
    _invoke(v, "Use AI answer", root=dlg, toplevel=dlg)
    assert "type this one yourself" in dlg.ai_tip.cget("text"), "duty cannot be guessed"
    dlg._text_widget.insert("1.0", "Conveyor with one motor")
    _invoke(v, "Next", root=dlg, toplevel=dlg)
    _invoke(v, "Use AI answer", root=dlg, toplevel=dlg)
    assert dlg._choice_var.get() == "Allen-Bradley", "manufacturer preference question"
    _invoke(v, "Next", root=dlg, toplevel=dlg)
    _invoke(v, "Use AI answer", root=dlg, toplevel=dlg)
    assert dlg._choice_var.get() == "480 VAC"
    _invoke(v, "Next", root=dlg, toplevel=dlg)
    dlg._choice_var.set("120 VAC")
    _invoke(v, "Accept all AI answers", root=dlg, toplevel=dlg)
    assert dlg._phase == "devices" and dlg.next_btn.cget("text") == "Confirm devices"
    a = dlg.answers
    assert a["control_voltage"] == "120 VAC", "an answer the user picked is kept"
    assert a["has_motor"] == "Yes" and a["motor_control"] == "VFD (variable speed)"
    assert a["door_drawing"] == ab.DOOR_YES and a["project_name"] == "Conveyor With One Motor"
    assert str(dlg.use_ai_btn.cget("state")) == "disabled"
    _invoke(v, "Back", root=dlg, toplevel=dlg)
    assert dlg._phase == "interview" and str(dlg.accept_all_btn.cget("state")) == "normal"
    dlg._cancel()


def test_gate_v0328_accept_all_ai_picks_with_maker_curtain_and_stack(ui):
    from cabinet_studio.services import ai_build as ab
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.services.standards import default_profile
    from cabinet_studio.ui.ai_build import AiBuildDialog

    v = ui
    dlg = AiBuildDialog(v, v.fonts, load_library(), default_profile())
    dlg.present()
    _pump(v)
    dlg._text_widget.insert("1.0", "Weld cell with a conveyor motor")
    _invoke(v, "Next", root=dlg, toplevel=dlg)
    dlg._choice_var.set("Omron")
    _invoke(v, "Accept all AI answers", root=dlg, toplevel=dlg)
    a = dlg.answers
    assert a["manufacturer"] == "Omron" and a["light_curtain"] == ab.LC_YES and a["stack_light"] == ab.STACK_YES
    assert dlg._phase == "devices" and dlg.accept_all_btn.cget("text") == "Accept all AI picks"
    for var in dlg._checks.values():
        var.set(False)
    _invoke(v, "Accept all AI picks", root=dlg, toplevel=dlg)
    recs = dlg.result["recommendations"]
    keys = {r.key for r in recs}
    assert {"light_curtain", "safety_relay_lc", "stack_green", "stack_amber", "stack_red"} <= keys
    assert len(recs) == len(dlg._recommendations), "every AI pick is accepted"
    assert next(r for r in recs if r.type_id == "plc").vendor == "Omron"


def test_gate_v0328_hover_help_on_instruction_and_sim_buttons(ui):
    from cabinet_studio.ui.studio.palette import HELP, ITEMS

    v = ui
    pal = v.palette
    assert set(ITEMS) <= set(HELP), "every instruction button has an explanation"
    for group in pal._groups:
        pal.show_group(group)
        _pump(v, 1)
        for mnemonic, btn in pal.buttons.items():
            if btn.winfo_ismapped():
                tip = btn._cs_hover_tip
                tip.show()
                assert tip.tip is not None and mnemonic in tip.title
                tip.hide()
                assert tip.tip is None
    btn = pal.buttons["TON"]
    pal.show_group("Timer/Counter")
    _pump(v, 1)
    btn._canvas.event_generate("<Enter>")
    for _ in range(12):
        _pump(v, 1)
        v.after(60)
    assert btn._cs_hover_tip.tip is not None, "resting the mouse opens the popup"
    btn._canvas.event_generate("<Leave>")
    _pump(v, 1)
    assert btn._cs_hover_tip.tip is None
    tips = [w._cs_hover_tip for w in v.winfo_children() for w in _walk_widgets(w) if "_cs_hover_tip" in w.__dict__]
    assert any("Pretends the machine" in t.text for t in tips), "Normal run explains itself"


def _walk_widgets(w):
    yield w
    for child in w.winfo_children():
        yield from _walk_widgets(child)


def test_gate_v0328_normal_run_pretend_machine_and_safety(ui, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from cabinet_studio.services.programming import add_rung_from_elements, empty_program
    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(pv, "_ui_prefs_path", lambda: tmp_path / "ui_prefs.json")
    clock = [100.0]
    monkeypatch.setattr(pv, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    v = ui
    c = lambda var, form="NO": {"kind": "contact", "var": var, "form": form}  # noqa: E731
    coil = lambda var: {"kind": "coil", "var": var, "form": "normal"}  # noqa: E731
    prog = add_rung_from_elements(empty_program(), [
        {"kind": "or", "branches": [[c("Start_PB")], [c("Motor_Run")]]},
        c("ES1", "NC"), c("LC1", "NC"), coil("Motor_Run")])
    prog = add_rung_from_elements(prog, [c("Motor_Running"), coil("Clamp_Sol")])
    prog = add_rung_from_elements(prog, [c("Clamp_Extended"), coil("Weld")])
    prog = add_rung_from_elements(prog, [c("ES1"), coil("STK_Red")])
    prog = add_rung_from_elements(prog, [c("LC1"), c("ES1", "NC"), coil("STK_Amber")])
    prog = add_rung_from_elements(prog, [c("LC1", "NC"), c("ES1", "NC"), coil("STK_Green")])
    v.program = prog
    v._draw_ladder()
    _speed_menus(v, toplevel=v)[0]._dropdown_callback("0.25 s / rung")
    v._ensure_scan_sim().set_force("LC1", False)
    _invoke(v, "Normal run", toplevel=v)
    v._sim_cancel_timer()
    assert v._ensure_scan_sim().forces.get("LC1") is False, "your safety settings survive the Normal run reset"
    assert "ES1" not in v._ensure_scan_sim().forces, "Normal run never touches the E-stop"
    plant = v._sim_plant
    assert plant is not None and ("Motor_Running", "Motor_Run", False) in plant.links
    sim = v._ensure_scan_sim()

    def run(seconds):
        for _ in range(int(seconds / 0.25)):
            clock[0] += 0.25
            _tick(v)
            if v._sim_auto_after is not None:
                v.after_cancel(v._sim_auto_after)
            v._sim_auto_tick()

    run(20)
    assert v._sim_auto is None and v._sim_plant is not None, "plan done, machine keeps running"
    assert sim.read("Motor_Run") and sim.read("Motor_Running"), dict(sim.forces)
    assert sim.read("Clamp_Sol") and sim.read("Clamp_Extended") and sim.read("Weld"), "sequence ran in order"
    assert sim.read("STK_Green") and not sim.read("STK_Amber")
    sim.set_force("LC1", True)
    run(3)
    assert not sim.read("Motor_Run") and sim.read("STK_Amber") and not sim.read("STK_Green")
    assert not sim.read("Motor_Running"), "feedback drops when the motor stops"
    sim.set_force("ES1", True)
    run(1)
    assert sim.read("STK_Red") and not sim.read("STK_Amber")
    if v._sim_auto_after is not None:
        v.after_cancel(v._sim_auto_after)
    v._sim_stop()
    assert v._sim_plant is None


def test_gate_v0326_drag_parts_on_layout_sheet_and_reset(ui):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_panel_zones_v0325 import LIB, _project

    from cabinet_studio.ui.drawing_viewer import DrawingViewer

    v = ui
    project = _project()
    edits = []

    def hook(apply, msg):
        edits.append(msg)
        apply()

    dv = DrawingViewer(v, v.fonts, project, LIB, edit_hook=hook)
    dv.geometry("1400x1000")
    _pump(v, 4)
    dv._goto(next(n for n, s in enumerate(dv.sheets) if "BACKPLATE" in s.title))
    _pump(v)
    assert "drag any part" in dv.edit_status.cget("text")
    sheet = dv.sheets[dv.index]
    plc = next(b for b in sheet.boxes if b.tag == "PLC1")
    s, ox, oy = dv._draw_scale, dv._draw_ox, dv._draw_oy
    sx = int(ox + (plc.x + plc.w / 2) * s - dv.canvas.canvasx(0))
    sy = int(oy + (plc.y + plc.h / 2) * s - dv.canvas.canvasy(0))
    px, py, pw, ph = sheet.panel
    f = pw / project.backplate_width_in
    target_y = int(oy + (py + 0.6 * f + plc.h / 2) * s - dv.canvas.canvasy(0))
    target_x = int(ox + (px + pw - plc.w / 2 - 0.6 * f) * s - dv.canvas.canvasx(0))
    dv.canvas.event_generate("<ButtonPress-1>", x=sx, y=sy)
    dv.canvas.event_generate("<B1-Motion>", x=(sx + target_x) // 2, y=(sy + target_y) // 2)
    dv.canvas.event_generate("<B1-Motion>", x=target_x, y=target_y)
    dv.canvas.event_generate("<ButtonRelease-1>", x=target_x, y=target_y)
    _pump(v)
    item = next(i for i in project.items if i.fields.get("tag") == "PLC1")
    assert edits and edits[-1].startswith("Moved PLC1"), dv.edit_status.cget("text")
    assert "layout_x_in" in item.fields and float(item.fields["layout_y_in"]) <= 1.0
    moved = next(b for b in dv.sheets[dv.index].boxes if b.tag == "PLC1")
    assert moved.y < plc.y and moved.x > plc.x, "the part is drawn where it was dropped"
    others = [b for b in dv.sheets[dv.index].boxes if b.tag != "PLC1"]
    for b in others:
        assert moved.x + moved.w <= b.x or b.x + b.w <= moved.x or moved.y + moved.h <= b.y or b.y + b.h <= moved.y
    cr = next(b for b in dv.sheets[dv.index].boxes if b.tag == "CR1")
    n = len(edits)
    assert not dv.drop(cr.key, moved.x - cr.x, moved.y - cr.y), "dropping onto another part is refused"
    assert len(edits) == n and "overlap" in dv.edit_status.cget("text")
    _invoke(v, "Reset layout", root=dv, toplevel=dv)
    assert "layout_x_in" not in item.fields and edits[-1].startswith("Layout reset")
    dv.close()


def _zones_fixture():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_panel_zones_v0325 import LIB, _project

    return LIB, _project


def test_gate_v0329_drag_devices_and_text_on_schematics(ui):
    from cabinet_studio.services import drawings as dw
    from cabinet_studio.ui.drawing_viewer import DrawingViewer

    v = ui
    LIB, _project = _zones_fixture()
    project = _project()
    project.interview["supply_voltage"] = "480 VAC"
    edits = []

    def hook(apply, msg):
        edits.append(msg)
        apply()

    dv = DrawingViewer(v, v.fonts, project, LIB, edit_hook=hook)
    dv.geometry("1400x1000")
    _pump(v, 4)

    def to_screen(x, y):
        return (int(dv._draw_ox + x * dv._draw_scale - dv.canvas.canvasx(0)),
                int(dv._draw_oy + y * dv._draw_scale - dv.canvas.canvasy(0)))

    def drag(x0, y0, x1, y1):
        dv.canvas.event_generate("<ButtonPress-1>", x=x0, y=y0)
        dv.canvas.event_generate("<B1-Motion>", x=(x0 + x1) // 2, y=(y0 + y1) // 2)
        dv.canvas.event_generate("<B1-Motion>", x=x1, y=y1)
        dv.canvas.event_generate("<ButtonRelease-1>", x=x1, y=y1)
        _pump(v)

    dv._goto(next(n for n, s in enumerate(dv.sheets) if s.kind == "control"))
    _pump(v)
    assert "drag a device" in dv.edit_status.cget("text")
    sheet = dv.sheets[dv.index]
    movable = [b for b in sheet.boxes if dv._item(dw.schematic_item_id(b)) is not None]
    assert len(movable) >= 2
    first, last = movable[0], movable[-1]
    sx, sy = to_screen(last.x + last.w / 2, last.y + last.h / 2)
    tx, ty = to_screen(last.x + last.w / 2, first.y + first.h / 2)
    drag(sx, sy, tx, ty)
    assert edits and edits[-1].startswith(f"Moved {last.tag} to {first.tag}'s rung"), dv.edit_status.cget("text")
    new = dv.sheets[dv.index]
    tags = [b.tag for b in new.boxes if dv._item(dw.schematic_item_id(b)) is not None]
    assert tags.index(last.tag) < tags.index(first.tag), "dropped device takes the target rung"
    moved = next(b for b in new.boxes if b.tag == last.tag)
    sx, sy = to_screen(moved.x + moved.w / 2, moved.y + moved.h / 2)
    drag(sx, sy, sx + 120, sy)
    assert "along its rung" in edits[-1]
    slid = next(b for b in dv.sheets[dv.index].boxes if b.tag == last.tag)
    assert slid.x > moved.x
    mid = slid.y + slid.h / 2
    assert any(abs(seg.y1 - seg.y2) < 0.5 and abs(seg.y1 - mid) < slid.h and abs(seg.x2 - slid.x) < 1.0
               for seg in dv.sheets[dv.index].segments), "the rung wire reconnects to the moved device"

    dv._goto(next(n for n, s in enumerate(dv.sheets) if s.kind == "power"))
    _pump(v)
    power = dv.sheets[dv.index]
    assert any(t == "POWER IN" for _x, _y, t in power.labels)
    assert any("POWER IN: 480 VAC 3-phase - L1 L2 L3 + PE" in n for n in power.notes)
    n, (lx, ly, text) = next((i, lab) for i, lab in enumerate(power.labels) if dw._is_structural_run_label(lab[2]))
    sx, sy = to_screen(lx + 6, ly - 4)
    drag(sx, sy, sx + 40, sy + 30)
    assert edits[-1] == f"Moved the text '{text}'."
    nx, ny, _t = dv.sheets[dv.index].labels[n]
    assert nx > lx and ny > ly
    _invoke(v, "Reset layout", root=dv, toplevel=dv)
    assert edits[-1].startswith("Schematic reset") and "1 text label" in edits[-1]
    dv._goto(next(n for n, s in enumerate(dv.sheets) if s.kind == "control"))
    _pump(v)
    _invoke(v, "Reset layout", root=dv, toplevel=dv)
    assert edits[-1].startswith("Schematic reset")
    assert not any(k.startswith("sch_") for i in project.items for k in i.fields)
    dv.close()


def test_gate_v0329_drag_instruction_reconnects_ladder(ui, tmp_path, monkeypatch):
    from cabinet_studio.services.ladder_ir import program_rung_to_elements
    from cabinet_studio.services.programming import add_rung_from_elements, empty_program
    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(pv, "_ui_prefs_path", lambda: tmp_path / "ui_prefs.json")
    v = ui
    c = lambda var, form="NO": {"kind": "contact", "var": var, "form": form}  # noqa: E731
    coil = lambda var: {"kind": "coil", "var": var, "form": "normal"}  # noqa: E731
    prog = add_rung_from_elements(empty_program(), [c("Start_PB"), c("Stop_PB", "NC"), coil("Motor")])
    prog = add_rung_from_elements(prog, [c("Aux"), coil("Lamp")])
    v.program = prog
    v._draw_ladder()
    _pump(v)
    r1, r2 = [r["id"] for r in v.program["rungs"]]

    def target(tag):
        x0, y0, x1, y1, _k, _t = next(t for t in v._click_targets if t[5] == tag)
        return int((x0 + x1) / 2 - v.canvas.canvasx(0)), int((y0 + y1) / 2 - v.canvas.canvasy(0))

    def drag(a, b):
        v.canvas.event_generate("<ButtonPress-1>", x=a[0], y=a[1])
        v.canvas.event_generate("<B1-Motion>", x=(a[0] + b[0]) // 2, y=(a[1] + b[1]) // 2)
        v.canvas.event_generate("<B1-Motion>", x=b[0], y=b[1])
        v.canvas.event_generate("<ButtonRelease-1>", x=b[0], y=b[1])
        _pump(v)

    def vars_of(rid):
        rung = next(r for r in v.program["rungs"] if r["id"] == rid)
        return [e.get("var") for e in program_rung_to_elements(rung)]

    ax, ay = target("Aux")
    drag(target("Stop_PB"), (ax - 40, ay))
    assert vars_of(r2) == ["Stop_PB", "Aux", "Lamp"], v.status.cget("text")
    assert vars_of(r1) == ["Start_PB", "Motor"]
    assert "re-connected" in v.status.cget("text")
    drag(target("Motor"), target("Lamp"))
    assert "needs an output" in v.status.cget("text") and vars_of(r1) == ["Start_PB", "Motor"]
    real = pv.verify_program
    monkeypatch.setattr(pv, "verify_program", lambda prog, dev=None: (
        [{"severity": "error"}] if prog is not v.program else []))
    sx, sy = target("Start_PB")
    drag((sx, sy), target("Lamp"))
    assert "would break the program" in v.status.cget("text") and vars_of(r1) == ["Start_PB", "Motor"]
    monkeypatch.setattr(pv, "verify_program", real)


def test_gate_v0330_rung_editor_hover_help_and_comes_to_front(ui, tmp_path, monkeypatch):
    import customtkinter as ctk

    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.rung_help import RUNG_HELP

    monkeypatch.setattr(pv, "_ui_prefs_path", lambda: tmp_path / "ui_prefs.json")
    v = ui
    v._pop_out_rung_editor()
    _pump(v)
    win = v._rung_editor_popout
    assert win is not None

    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)

    buttons = [w for w in walk(win) if isinstance(w, ctk.CTkButton)]
    texts = [b.cget("text") for b in buttons]
    assert "Add rung" in texts and "Paste instr" in texts
    missing = [t for b, t in zip(buttons, texts) if not getattr(b, "_cs_hover_tip", None)]
    assert not missing, f"buttons without hover help: {missing}"
    assert all(t in RUNG_HELP for t in texts)
    add = buttons[texts.index("Add rung")]
    add._canvas.event_generate("<Enter>")
    add._cs_hover_tip.show()
    _pump(v)
    assert add._cs_hover_tip.tip is not None
    add._cs_hover_tip.hide()
    win.geometry("+40000+40000")
    _pump(v)
    v._raise_rung_editor()
    _pump(v)
    assert win.winfo_rootx() < 20000, "a window lost off screen is pulled back"
    v._dock_rung_editor()
    _pump(v)


def test_gate_v0331_delete_replace_one_instruction(ui, tmp_path, monkeypatch):
    import tkinter as tk

    from cabinet_studio.services.ladder_ir import program_rung_to_elements
    from cabinet_studio.services.programming import add_rung_from_elements, empty_program
    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(pv, "_ui_prefs_path", lambda: tmp_path / "ui_prefs.json")
    menus = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, *a, **k: menus.append(self))
    v = ui
    c = lambda var, form="NO": {"kind": "contact", "var": var, "form": form}  # noqa: E731
    coil = lambda var: {"kind": "coil", "var": var, "form": "normal"}  # noqa: E731
    prog = add_rung_from_elements(empty_program(), [
        {"kind": "or", "branches": [[c("Start_PB")], [c("Motor")]]}, c("Stop_PB", "NC"), coil("Motor")])
    v.program = prog
    v._draw_ladder()
    _pump(v)
    rid = v.program["rungs"][0]["id"]

    def at(tag, n=0):
        hits = sorted((t for t in v._click_targets if t[5] == tag), key=lambda t: (t[0], t[1]))
        x0, y0, x1, y1, _k, _t = hits[n]
        return int((x0 + x1) / 2 - v.canvas.canvasx(0)), int((y0 + y1) / 2 - v.canvas.canvasy(0))

    def els():
        return program_rung_to_elements(next(r for r in v.program["rungs"] if r["id"] == rid))

    def click(tag, n=0):
        x, y = at(tag, n)
        v.canvas.event_generate("<ButtonPress-1>", x=x, y=y)
        v.canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
        _pump(v)

    click("Stop_PB")
    assert "Selected Stop_PB" in v.status.cget("text")
    v.contact_var.set("Guard_OK")
    v.nc_var.set("NO")
    _invoke(v, "Replace instr", toplevel=v)
    assert [e.get("var") for e in els()][1:] == ["Guard_OK", "Motor"], v.status.cget("text")
    _pump(v)
    click("Guard_OK")
    _invoke(v, "Delete instr", toplevel=v)
    assert [e.get("var") for e in els()][1:] == ["Motor"] and "Deleted Guard_OK" in v.status.cget("text")
    _pump(v)
    x, y = at("Start_PB")
    v.canvas.event_generate("<Button-3>", x=x, y=y)
    _pump(v)
    menu = menus[-1]
    menu.invoke(_menu_entry(menu, "Change NO / NC"))
    assert els()[0]["branches"][0][0]["form"] == "NC"
    _pump(v)
    v.contact_var.set("Reset_PB")
    x, y = at("Start_PB")
    v.canvas.event_generate("<Button-3>", x=x, y=y)
    _pump(v)
    menus[-1].invoke(_menu_entry(menus[-1], "Add contact Reset_PB after"))
    assert [e["var"] for e in els()[0]["branches"][0]] == ["Start_PB", "Reset_PB"]
    _pump(v)
    v.coil_var.set("Lamp")
    x, y = at("Motor", 1)
    v.canvas.event_generate("<Button-3>", x=x, y=y)
    _pump(v)
    menus[-1].invoke(_menu_entry(menus[-1], "Replace with coil Lamp"))
    assert els()[-1]["var"] == "Lamp"
    _pump(v)
    x, y = at("Motor")
    v.canvas.event_generate("<Button-3>", x=x, y=y)
    _pump(v)
    menus[-1].invoke(_menu_entry(menus[-1], "Delete Motor"))
    assert [e.get("var") for e in els()] == ["Start_PB", "Reset_PB", "Lamp"], "a one-path branch flattens in series"


def test_gate_v0329_layout_power_entry_and_ground_bar():
    from cabinet_studio.services import drawings as dw

    LIB, _project = _zones_fixture()
    project = _project()
    project.interview["supply_voltage"] = "120 VAC"
    plate = next(s for s in dw.build_sheets(project, LIB) if "BACKPLATE" in s.title)
    assert any(t.startswith("POWER IN 120 VAC (L1 N + PE)") for _x, _y, t in plate.labels)
    assert any(b.key == dw.PE_BAR_KEY for b in plate.boxes)
    assert any("PE lands on the ground bar" in n for n in plate.notes)


def _menu_entry(menu, label):
    for i in range((menu.index("end") or 0) + 1):
        if menu.type(i) in ("command", "cascade") and menu.entrycget(i, "label").startswith(label):
            return i
    raise AssertionError(f"menu entry {label!r} not found")


def test_gate_v0327_right_click_copy_paste_delete_add_part(ui, monkeypatch):
    import sys
    import tkinter as tk
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_panel_zones_v0325 import LIB, _project

    from cabinet_studio.ui.drawing_viewer import DrawingViewer

    popped = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, *_a, **_k: popped.append(self))
    v = ui
    project = _project()
    edits = []

    def hook(apply, msg):
        edits.append(msg)
        apply()

    dv = DrawingViewer(v, v.fonts, project, LIB, edit_hook=hook)
    dv.geometry("1400x1000")
    _pump(v, 4)
    dv._goto(next(n for n, s in enumerate(dv.sheets) if "BACKPLATE" in s.title))
    _pump(v)
    sheet = dv.sheets[dv.index]
    s, ox, oy = dv._draw_scale, dv._draw_ox, dv._draw_oy

    def screen(x, y):
        return int(ox + x * s - dv.canvas.canvasx(0)), int(oy + y * s - dv.canvas.canvasy(0))

    cr = next(b for b in sheet.boxes if b.tag == "CR1")
    dv.canvas.event_generate("<Button-3>", x=screen(cr.x + cr.w / 2, 0)[0], y=screen(0, cr.y + cr.h / 2)[1])
    _pump(v)
    menu = popped[-1]
    assert menu.entrycget(_menu_entry(menu, "Paste here"), "state") == "disabled"
    menu.invoke(_menu_entry(menu, "Copy CR1"))
    assert "Copied CR1" in dv.edit_status.cget("text")
    for _ in range(40):
        n_items = len(project.items)
        if dv.paste_part() is None:
            break
    assert len(project.items) == n_items, "a full plate refuses the paste"
    assert "No room" in dv.edit_status.cget("text")
    assert len([s for s in dv.sheets if s.kind == "layout" and "BACKPLATE" in s.title]) == 1
    project.items = [i for i in project.items if not i.fields.get("tag", "").startswith("CR") or i.fields["tag"] == "CR1"]
    n_items = len(project.items)

    project.interview["enclosure_selection"] = ""
    project.backplate_width_in, project.backplate_height_in = 48.0, 60.0
    dv._edit(lambda: None, "bigger plate")
    _pump(v)
    sheet = dv.sheets[dv.index]
    s, ox, oy = dv._draw_scale, dv._draw_ox, dv._draw_oy
    px, py, pw, ph = sheet.panel
    blank = next(((x, y) for y in range(int(py + ph - 30), int(py), -20) for x in range(int(px + 20), int(px + pw), 20)
                  if not any(b.x - 120 <= x <= b.x + b.w + 20 and b.y - 120 <= y <= b.y + b.h + 20
                             for b in sheet.boxes)), None)
    assert blank is not None
    dv.canvas.event_generate("<Button-3>", x=screen(*blank)[0], y=screen(*blank)[1])
    _pump(v)
    menu = popped[-1]
    menu.invoke(_menu_entry(menu, "Paste here"))
    assert len(project.items) == n_items + 1 and edits[-1].startswith("Pasted CR")
    new = project.items[-1]
    assert new.fields["tag"] != "CR1" and new.type_id == next(i for i in project.items if i.fields.get("tag") == "CR1").type_id
    assert "io_address" not in new.fields and "wire_numbers" not in new.fields
    assert any(b.key == new.id for b in dv.sheets[dv.index].boxes), (
        [s.title for s in dv.sheets], dv.edit_status.cget("text"), new.fields)

    assert dv.copy_part(new.id) and dv.paste_part() and len(project.items) == n_items + 2

    choices = dv.part_choices()
    assert choices and not {c[1] for c in choices} & {"Motor", "Sensor", "Light curtain"}
    assert [c[0] for c in choices][:1] == ["Allen-Bradley"] and {"Siemens", "Omron"} <= {c[0] for c in choices}
    _invoke(v, "Add part", root=dv, toplevel=dv)
    add_menu = popped[-1]
    assert add_menu.entrycget(0, "label") == "Allen-Bradley"
    maker_menu = add_menu.nametowidget(add_menu.entrycget(0, "menu"))
    sub = maker_menu.nametowidget(maker_menu.entrycget(0, "menu"))
    sub.invoke(0)
    assert edits[-1].startswith("Added"), edits[-1]
    assert len(project.items) == n_items + 3

    cr_box = next(b for b in dv.sheets[dv.index].boxes if b.tag == "CR1")
    dv.selected_key = cr_box.key
    menu = dv._context_menu(cr_box.key, None, None)
    menu.invoke(_menu_entry(menu, "Delete CR1"))
    assert not any(i.fields.get("tag") == "CR1" for i in project.items) and edits[-1].startswith("Deleted CR1")
    dv.close()
