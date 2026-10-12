"""HMI editor UI gate: headlessly clicks EVERY HMI editor / interview button and option menu,
drags and resizes on the canvas, and opens the editor from Drawings and Programming."""

from __future__ import annotations

import os
import traceback
from types import SimpleNamespace

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)

from test_hmi_design import make_project  # noqa: E402


def _all_widgets(widget):
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_all_widgets(child))
    return out


def _pump(w, n=3):
    for _ in range(n):
        try:
            w.update()
        except Exception:
            pass


def _click(ui, btn):
    try:
        btn.invoke()
    except Exception:
        ui.errors.append(traceback.format_exc())
    _pump(ui.root)


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.ui import hmi_editor
    from cabinet_studio.ui.theme import Fonts, choose_families

    answers = {"close": "discard"}
    monkeypatch.setattr(hmi_editor, "ask_choice", lambda *a, **k: answers["close"])
    errors: list[str] = []
    root = ctk.CTk()
    root.withdraw()
    root.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb)))
    ns = SimpleNamespace(root=root, errors=errors, fonts=Fonts(*choose_families(root)), project=make_project(),
                         answers=answers, mod=hmi_editor)
    try:
        yield ns
    finally:
        try:
            root.update()
        except Exception:
            pass
        root.destroy()


def _editor(ui, hook_calls):
    def hook(apply, message):
        hook_calls.append(message)
        apply()

    ed = ui.mod.HmiEditor(ui.root, ui.fonts, ui.project, edit_hook=hook)
    ed.geometry("1280x800")
    _pump(ui.root, 5)
    return ed


def _center(ed, obj):
    g = ed._geom
    return (g["sx"] + (obj.x + obj.w / 2) * g["cw"], g["sy"] + (obj.y + obj.h / 2) * g["ch"])


def test_gate_every_hmi_editor_button_and_menu(ui):
    from cabinet_studio.services import hmi_design as hd
    from cabinet_studio.services.hmi_library import hmi_label, load_hmi_catalog

    calls: list[str] = []
    ed = _editor(ui, calls)
    # Every button / menu in the editor carries hover help.
    for w in _all_widgets(ed):
        if isinstance(w, (ctk.CTkButton, ctk.CTkOptionMenu, ctk.CTkComboBox)):
            assert getattr(w, "_cs_hover_tip", None) is not None, w.cget("text") if isinstance(w, ctk.CTkButton) else w

    # Interview: step through every question (Back once, change an answer), Build HMI.
    _click(ui, ed.interview_btn)
    iv = ed._interview
    assert iv is not None and iv.winfo_exists()
    for w in _all_widgets(iv):
        if isinstance(w, (ctk.CTkButton, ctk.CTkOptionMenu)):
            assert getattr(w, "_cs_hover_tip", None) is not None
    iv.choice_menu._dropdown_callback("Siemens")
    _click(ui, iv.next_btn)
    _click(ui, iv.back_btn)
    assert iv.index == 0 and iv.choice_var.get() == "Siemens"
    for _ in hd.QUESTION_KEYS:
        if not iv.winfo_exists():
            break
        _click(ui, iv.next_btn)
    assert not iv.winfo_exists()
    from cabinet_studio.services.hmi_library import hmi_by_id

    assert hmi_by_id(ed.design.model_id)["maker"] == "Siemens"
    assert [s.name for s in ed.design.screens] == ["Main", "Machine", "Manual", "Alarms"]

    # Interview again: Cancel leaves the design alone; Accept all rebuilds with suggestions.
    before = hd.design_to_json(ed.design)
    _click(ui, ed.interview_btn)
    _click(ui, ed._interview.cancel_btn)
    assert hd.design_to_json(ed.design) == before
    _click(ui, ed.interview_btn)
    _click(ui, ed._interview.accept_btn)
    assert hmi_by_id(ed.design.model_id)["maker"] == "Siemens"  # earlier answers are remembered
    assert len(ed._undo) >= 2

    # Screens: add, select via the list, rename, delete.
    ed.screen_entry.insert(0, "Recipes")
    _click(ui, ed.add_screen_btn)
    assert ed.screen_name == "Recipes"
    main_btn = next(b for b in _all_widgets(ed.screen_list) if isinstance(b, ctk.CTkButton) and b.cget("text") == "Main")
    _click(ui, main_btn)
    assert ed.screen_name == "Main"
    ed.select_screen("Recipes")
    ed.screen_entry.insert(0, "Recipe")
    _click(ui, ed.rename_btn)
    assert ed.design.screen("Recipe") is not None
    _click(ui, ed.rename_btn)  # empty box -> friendly message only

    # Palette: every object type lands on the (empty) Recipe screen.
    for kind in ui.mod.PALETTE_ORDER:  # machine graphics: test_gate_graphics_palette_run_mode_and_export
        btn = ed.palette_buttons[kind]
        _click(ui, btn)
        assert ed._selected() is not None and ed._selected().kind == kind
    screen = ed._screen()
    assert len(screen.objects) == len(ui.mod.PALETTE_ORDER)

    # Canvas: click-select, drag to move, drag the corner to resize.
    _pump(ui.root, 3)
    ed._draw()
    obj = next(o for o in screen.objects if o.kind == "lamp")
    x, y = _center(ed, obj)
    old = (obj.x, obj.y)
    ed._press(SimpleNamespace(x=x, y=y))
    assert ed.selected_id == obj.id
    ed._motion(SimpleNamespace(x=x + 3 * ed._geom["cw"], y=y + 2 * ed._geom["ch"]))
    ed._release(SimpleNamespace(x=0, y=0))
    assert (obj.x, obj.y) != old
    g = ed._geom
    cx, cy = g["sx"] + (obj.x + obj.w) * g["cw"] - 2, g["sy"] + (obj.y + obj.h) * g["ch"] - 2
    w0 = obj.w
    ed._press(SimpleNamespace(x=cx, y=cy))
    ed._motion(SimpleNamespace(x=cx + 2 * g["cw"], y=cy))
    ed._release(SimpleNamespace(x=0, y=0))
    assert obj.w == w0 + 2
    ed._press(SimpleNamespace(x=2, y=2))  # empty space deselects
    assert ed.selected_id is None

    # Properties: label, tag, color, button action, go-to target, Apply.
    btn_obj = next(o for o in screen.objects if o.kind == "momentary")
    ed.selected_id = btn_obj.id
    ed._load_properties()
    ed.label_entry.delete(0, "end")
    ed.label_entry.insert(0, "Run conveyor")
    ed.tag_combo.set("HMI_Start")
    ed.color_menu._dropdown_callback("Amber")
    ed.mode_menu._dropdown_callback(hd.OBJECT_KINDS["toggle"]["name"])
    _click(ui, ed.apply_btn)
    assert (btn_obj.label, btn_obj.tag, btn_obj.color, btn_obj.kind) == ("Run conveyor", "HMI_Start", "Amber", "toggle")
    nav = next(o for o in screen.objects if o.kind == "nav")
    ed.selected_id = nav.id
    ed._load_properties()
    ed.target_menu._dropdown_callback("Alarms")
    _click(ui, ed.apply_btn)
    assert nav.target == "Alarms"

    # Model switch rescales; Undo reverts it.
    other = next(e for e in load_hmi_catalog() if e["id"] == "ab-2713p-t15")
    ed.model_menu._dropdown_callback(hmi_label(other))
    assert ed.design.model_id == "ab-2713p-t15"
    _click(ui, ed.undo_btn)
    assert ed.design.model_id != "ab-2713p-t15"

    # Delete object, Validate, Delete screen, Save.
    ed.selected_id = ed._screen().objects[0].id
    n = len(ed._screen().objects)
    _click(ui, ed.delete_btn)
    assert len(ed._screen().objects) == n - 1
    _click(ui, ed.validate_btn)
    assert ed.status_label.cget("text")
    _click(ui, ed.delete_screen_btn)
    assert ed.design.screen("Recipe") is None
    _click(ui, ed.save_btn)
    assert calls and hd.load_design(ui.project) is not None
    assert not ed.dirty

    # Close with unsaved changes: "Keep editing" stays open, "discard" closes.
    _click(ui, ed.palette_buttons["text"])
    ui.answers["close"] = "cancel"
    _click(ui, ed.close_btn)
    assert ed.winfo_exists()
    ui.answers["close"] = "discard"
    _click(ui, ed.close_btn)
    assert not ed.winfo_exists()
    assert not ui.errors, "\n\n".join(ui.errors)


def test_gate_graphics_palette_run_mode_and_export(ui, tmp_path, monkeypatch):
    """Every MACHINE GRAPHICS button, the Animation menu, Run with simulator / Stop, live press + lamp + animation,
    safety refusal at runtime, Send number, and Export for <maker>."""
    from cabinet_studio.services import hmi_design as hd
    from cabinet_studio.services.hmi_symbols import ANIMATIONS, GRAPHICS
    from cabinet_studio.services.programming import add_rung, empty_program

    ui.project.program = add_rung(empty_program(), contact_tag="HMI_Start", coil_tag="M1")
    ed = _editor(ui, [])
    cv = ed.canvas
    for kind in GRAPHICS:
        btn = ed.palette_buttons[kind]
        assert getattr(btn, "_cs_hover_tip", None) is not None
        ed._screen().objects = []
        _click(ui, btn)
        assert [o.kind for o in ed._screen().objects] == [kind], kind
        assert cv.find_withtag(f"obj:{ed._screen().objects[0].id}"), kind
    # Conveyor picks up the motor run tag; Animation menu + Apply changes set the animation.
    ed._screen().objects = []
    _click(ui, ed.palette_buttons["g_conveyor"])
    conv = ed._selected()
    assert conv.tag == "M1" and conv.anim == "run"
    assert str(ed.anim_menu.cget("state")) == "normal"
    ed.anim_menu._dropdown_callback(ANIMATIONS["fault"])
    _click(ui, ed.apply_btn)
    assert conv.anim == "fault"
    conv.anim = "run"

    screen = ed._screen()
    start = hd.add_object(ed.design, screen, "momentary", label="Start", tag="HMI_Start")
    lamp = hd.add_object(ed.design, screen, "lamp", label="Running", tag="M1", color="Green")
    bad = hd.add_object(ed.design, screen, "momentary", label="Bad", tag="ES1")
    entry = hd.add_object(ed.design, screen, "numeric_entry", label="Level", tag="HMI_Level")
    tank = hd.add_object(ed.design, screen, "g_tank", tag="HMI_Level")
    ed._draw()
    _pump(ui.root)

    _click(ui, ed.run_btn)
    rt = ed.runtime
    assert rt is not None and ed.run_btn.cget("text") == "Stop"
    assert ed.sim_banner.winfo_manager() == "pack" and cv.find_withtag("sim_banner")
    assert str(ed.palette_buttons["g_motor"].cget("state")) == "disabled"
    ev = lambda o: SimpleNamespace(x=_center(ed, o)[0], y=_center(ed, o)[1])  # noqa: E731
    lamp_fill = lambda: cv.itemcget(cv.find_withtag(f"lamp:{lamp.id}")[0], "fill")  # noqa: E731
    conv_coords = lambda: [cv.coords(i) for i in cv.find_withtag(f"obj:{conv.id}")]  # noqa: E731

    ed._press(ev(start))
    assert rt.sim.read("HMI_Start") is True
    ed._run_tick()
    assert lamp_fill() == hd.COLORS["Green"]
    before = conv_coords()
    ed._run_tick()
    assert conv_coords() != before  # belt moves while M1 is ON
    ed._release(ev(start))
    assert rt.sim.read("HMI_Start") is False
    ed._run_tick()
    assert lamp_fill() == "#5a5a5a"
    still = conv_coords()
    ed._run_tick()
    assert conv_coords() == still  # stops with the motor

    ed._press(ev(bad))
    assert "Refused" in ed.status_label.cget("text") and not rt.sim.read("ES1")
    ed._release(ev(bad))

    ed._press(ev(entry))
    assert str(ed.send_btn.cget("state")) == "normal"
    ed.value_entry.insert(0, "80")
    _click(ui, ed.send_btn)
    ed._run_tick()
    assert rt.anim_state(tank)["level"] == pytest.approx(0.8)

    _click(ui, ed.run_btn)
    assert ed.runtime is None and ed.run_btn.cget("text") == "Run with simulator"
    assert ed.sim_banner.winfo_manager() == "" and not cv.find_withtag("sim_banner")
    assert str(ed.palette_buttons["g_motor"].cget("state")) == "normal"

    out = tmp_path / "drawings"
    monkeypatch.setattr("cabinet_studio.services.drawings.default_drawings_folder", lambda project, save_path=None: out)
    assert ed.export_btn.cget("text").startswith("Export for ")
    _click(ui, ed.export_btn)
    written = sorted(p.name for p in (out / "hmi").iterdir())
    assert any(n.endswith("_tags_generic.csv") for n in written) and any(n.endswith(".svg") for n in written)
    assert "nothing is downloaded" in ed.status_label.cget("text")
    assert not ui.errors, ui.errors[0]
    ed.close()


def test_gate_quick_build_buttons(ui, tmp_path, monkeypatch):
    """Every Quick build button / menu: Auto-build, Bind tags, nav bar, Alarm list, CSV, theme, faceplates, Suggest."""
    import tkinter.filedialog as fd

    from cabinet_studio.services import hmi_design as hd

    csv_path = tmp_path / "hmi-tags.csv"
    monkeypatch.setattr(fd, "asksaveasfilename", lambda **k: str(csv_path))
    calls: list[str] = []
    ed = _editor(ui, calls)
    for w in (ed.autobuild_btn, ed.bind_btn, ed.nav_btn, ed.alarms_btn, ed.csv_btn, ed.theme_menu, ed.part_menu,
              ed.fp_menu, ed.faceplate_btn, ed.suggest_btn):
        assert getattr(w, "_cs_hover_tip", None) is not None

    _click(ui, ed.autobuild_btn)
    assert len(ed.design.screens) >= 3 and any(o.group.startswith("motor") for o in ed.design.screen("Main").objects)
    assert hd.validate_design(ed.design, ui.project) == []

    # Faceplate: pick the part and faceplate type, add it to a fresh screen, drag the whole group.
    ed.screen_entry.insert(0, "Faceplates")
    _click(ui, ed.add_screen_btn)
    ed.part_menu._dropdown_callback("M1")
    assert ed.fp_var.get() == hd.FACEPLATES["motor_vfd"]["name"]
    ed.fp_menu._dropdown_callback(hd.FACEPLATES["motor"]["name"])
    _click(ui, ed.faceplate_btn)
    group = ed._selected().group
    members = hd.group_objects(ed._screen(), group)
    assert group == "motor:M1" and len(members) >= 3
    _pump(ui.root)
    ed._draw()
    start = [(o.x, o.y) for o in members]
    x, y = _center(ed, members[1])
    ed._press(SimpleNamespace(x=x, y=y))
    ed._motion(SimpleNamespace(x=x + 4 * ed._geom["cw"], y=y + 3 * ed._geom["ch"]))
    ed._release(SimpleNamespace(x=0, y=0))
    assert [(o.x - 4, o.y - 3) for o in members] == start

    # Nav bar + Bind tags + Suggest tag.
    _click(ui, ed.nav_btn)
    assert {o.target for o in ed._screen().objects if o.kind == "nav"} == {s.name for s in ed.design.screens} - {
        "Faceplates"}
    _click(ui, ed.palette_buttons["lamp"])
    lamp = ed._selected()
    ed.label_entry.delete(0, "end")
    ed.label_entry.insert(0, "Motor contactor")
    _click(ui, ed.apply_btn)
    ed.selected_id = lamp.id
    ed._load_properties()
    ed.tag_combo.set("")
    _click(ui, ed.suggest_btn)
    assert ed.tag_combo.get() == "M1"
    _click(ui, ed.palette_buttons["estop_status"])
    _click(ui, ed.bind_btn)
    assert ed._selected().tag == "ES1"
    _click(ui, ed.bind_btn)  # nothing left to bind -> message only

    # Alarm list window opens (and closes); CSV export writes a file; theme switch.
    _click(ui, ed.alarms_btn)
    win = ed._alarm_win
    assert win is not None and win.winfo_exists()
    assert getattr(win.close_btn, "_cs_hover_tip", None) is not None
    _click(ui, ed.alarms_btn)  # reopening replaces the old window
    _click(ui, ed._alarm_win.close_btn)
    assert not ed._alarm_win.winfo_exists()
    _click(ui, ed.csv_btn)
    assert csv_path.exists() and "Tag Name" in csv_path.read_text(encoding="utf-8")
    for name in hd.THEMES:
        ed.theme_menu._dropdown_callback(name)
        _pump(ui.root)
        assert ed.design.theme == name
    _click(ui, ed.save_btn)
    assert hd.load_design(ui.project).theme == list(hd.THEMES)[-1]
    _click(ui, ed.close_btn)
    assert not ui.errors, "\n\n".join(ui.errors)


def test_gate_open_from_drawings_adds_hmi_sheets(ui):
    from cabinet_studio.services import hmi_design as hd
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui.drawing_viewer import DrawingViewer

    edits = []

    def owner_hook(apply, message):
        edits.append(message)
        apply()

    dv = DrawingViewer(ui.root, ui.fonts, ui.project, load_library(), edit_hook=owner_hook)
    _pump(ui.root)
    assert getattr(dv.hmi_btn, "_cs_hover_tip", None) is not None
    assert not any(s.kind.startswith("hmi-") for s in dv.sheets)
    _click(ui, dv.hmi_btn)
    ed = dv._hmi_editor
    assert ed is not None and ed.winfo_exists()
    _click(ui, dv.hmi_btn)  # second click brings the same window forward
    assert dv._hmi_editor is ed
    _click(ui, ed.interview_btn)
    _click(ui, ed._interview.accept_btn)
    _click(ui, ed.save_btn)
    assert edits and hd.load_design(ui.project) is not None
    kinds = [s.kind for s in dv.sheets]
    assert "hmi-layout" in kinds and "hmi-wiring" in kinds and "hmi-cutout" in kinds
    dv.index = kinds.index("hmi-wiring")
    dv._draw()  # the in-app viewer paints the HMI sheet without error
    _click(ui, ed.close_btn)
    dv.close()
    _pump(ui.root)
    assert not ui.errors, "\n\n".join(ui.errors)


def test_gate_open_from_programming_menu_and_toolbar(ui):
    from cabinet_studio.ui import programming_viewer as pv

    changes = []
    v = pv.ProgrammingViewer(ui.root, ui.fonts, ui.project, lambda msg: changes.append(msg))
    _pump(ui.root)
    btn = next(b for b in _all_widgets(v) if isinstance(b, ctk.CTkButton) and b.cget("text") == "HMI editor")
    assert getattr(btn, "_cs_hover_tip", None) is not None
    _click(ui, btn)
    ed = v._hmi_editor
    assert ed is not None and ed.winfo_exists()
    path, idx = v.commands.menu_index["tools.hmi_editor"]
    v.commands.menus[path].invoke(idx)
    _pump(ui.root)
    assert v._hmi_editor is ed
    _click(ui, ed.save_btn)
    assert changes and "HMI" in changes[-1]
    _click(ui, ed.close_btn)
    v.close()
    _pump(ui.root)
    assert not ui.errors, "\n\n".join(ui.errors)


def _canvas_click(ui, btn):
    try:
        for seq in ("<Enter>", "<Button-1>", "<ButtonRelease-1>"):
            btn._canvas.event_generate(seq, x=5, y=5)
    except Exception:
        ui.errors.append(traceback.format_exc())
    _pump(ui.root)


def test_gate_v0333_hmi_button_visible_on_programming_and_rail(ui):
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.main_window import CabinetStudioApp

    v = pv.ProgrammingViewer(ui.root, ui.fonts, ui.project, lambda msg: None)
    v.geometry("1280x800")
    _pump(ui.root, 6)
    btn = v._hmi_btn
    assert btn.cget("text") == "HMI editor" and getattr(btn, "_cs_hover_tip", None) is not None
    assert btn.winfo_ismapped()
    parent = btn.master
    assert btn.winfo_x() >= 0 and btn.winfo_x() + btn.winfo_width() <= parent.winfo_width()
    assert btn.winfo_rootx() + btn.winfo_width() <= v.winfo_rootx() + v.winfo_width()
    _canvas_click(ui, btn)
    ed = v._hmi_editor
    assert ed is not None and ed.winfo_exists()
    _click(ui, ed.close_btn)
    v.close()
    _pump(ui.root)

    app = CabinetStudioApp(load_library())
    app.report_callback_exception = lambda exc, val, tb: ui.errors.append(
        "".join(traceback.format_exception(exc, val, tb)))
    try:
        app.update()
        rail_btn = app.rail.hmi_btn
        assert rail_btn.cget("text") == "HMI editor" and getattr(rail_btn, "_cs_hover_tip", None) is not None
        assert rail_btn.master is app.rail.output
        app.dirty = False
        _canvas_click(ui, rail_btn)
        app.update()
        ed = app._hmi_editor
        assert ed is not None and ed.winfo_exists() and ed.project is app.project
        rail_btn.invoke()
        app.update()
        assert app._hmi_editor is ed
        ed.save_btn.invoke()
        app.update()
        assert app.dirty
        ed.close_btn.invoke()
        app.update()
    finally:
        app.destroy()
    assert not ui.errors, "\n\n".join(ui.errors)
