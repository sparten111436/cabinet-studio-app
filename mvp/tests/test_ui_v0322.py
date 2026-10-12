"""v0.3.22 UI phase 1: command registry, Light / Dark / System theme, and prints that never follow the theme."""

from __future__ import annotations

import json
import os
import re
import tempfile
import types
import webbrowser

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from cabinet_studio import __version__
from cabinet_studio.ui import theme

needs_display = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)
FOOTER = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."
SAFETY = "NFPA 79 / ISO 13849"


@pytest.fixture(autouse=True)
def _prefs(tmp_path, monkeypatch):
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    yield tmp_path
    theme.set_mode("dark", save=False)


def test_version_is_0322():
    assert tuple(int(p) for p in __version__.split(".")) >= (0, 3, 22)


# --------------------------------------------------------------------------- theme

def test_every_colour_is_a_light_dark_pair():
    for name, pair in theme.PALETTE.items():
        assert isinstance(pair, tuple) and len(pair) == 2, name
        assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in pair), name
    assert theme.BG == ("#f3f3f5", "#0d0d0f") and theme.PANEL[0] == "#ffffff" and theme.TEXT[0] == "#1b1b22"
    # Accents darkened for contrast on the light background.
    assert theme.ORANGE[0] != theme.ORANGE[1] and theme.CYAN[0] != theme.CYAN[1]


def test_c_and_ladder_palette_follow_the_mode():
    theme.set_mode("light", save=False)
    assert theme.c("BG") == "#f3f3f5" and theme.c(theme.TEXT) == "#1b1b22" and theme.c("#123456") == "#123456"
    assert theme.ladder_palette()["bg"] == "#ffffff"
    theme.set_mode("dark", save=False)
    assert theme.c("BG") == "#0d0d0f" and theme.ladder_palette()["bg"] == "#d8d4cc"


def test_mode_is_saved_loaded_and_listeners_fire(_prefs):
    assert theme.saved_mode() == "dark"  # existing installs keep the dark look
    seen = []
    cb = theme.on_theme_change(seen.append)
    try:
        theme.set_mode("light")
        assert theme.saved_mode() == "light" and theme.current_mode() == "light"
        prefs = json.loads((_prefs / "ui_prefs.json").read_text(encoding="utf-8"))
        assert prefs["ui_theme_mode"] == "light"
        assert theme.toggle_mode() == "dark"
        theme.set_mode("system")
        assert theme.load_mode() == "system"
        theme.set_mode("bogus")
        assert theme.current_mode() == "dark"
        assert seen == ["light", "dark", "system", "dark"]
    finally:
        theme.remove_theme_listener(cb)

    def broken(_mode):
        raise RuntimeError("window gone")

    theme.on_theme_change(broken)
    theme.set_mode("light", save=False)
    assert broken not in theme._listeners


# --------------------------------------------------------------------------- commands

@needs_display
def test_registry_builds_menus_buttons_and_invokes():
    import tkinter as tk

    from cabinet_studio.ui.commands import CommandRegistry

    root = ctk.CTk()
    root.withdraw()
    try:
        ran = []
        flag = tk.BooleanVar(master=root, value=False)
        pick = tk.StringVar(master=root, value="a")
        reg = CommandRegistry()
        reg.add("f.one", "One", lambda: ran.append("one"), menu="File", shortcut="Ctrl+1")
        reg.separator("File")
        reg.add("f.sub", "Deep", lambda: ran.append("deep"), menu="File/Sub")
        reg.add("v.flag", "Flag", lambda: ran.append(("flag", flag.get())), menu="View", kind="check", variable=flag)
        reg.add("v.b", "B", lambda: ran.append(("pick", pick.get())), menu="View", kind="radio", variable=pick, value="b")
        reg.add("x.off", "Off", lambda: ran.append("off"), menu="View", enabled_fn=lambda: False)
        reg.add("t.only", "Toolbar only", lambda: ran.append("tool"))
        with pytest.raises(ValueError):
            reg.add("f.one", "dup", lambda: None)
        bar = reg.build_menubar(root)
        assert str(tk.Misc.cget(root, "menu")) == str(bar)
        assert [bar.entrycget(i, "label") for i in range(bar.index("end") + 1)] == ["File", "View"]
        assert {cid for _p, _i, cid in reg.menu_entries()} == {"f.one", "f.sub", "v.flag", "v.b", "x.off"}
        assert reg.menus["File"].entrycget(reg.menu_index["f.one"][1], "accelerator") == "Ctrl+1"
        assert reg.menus["View"].entrycget(reg.menu_index["x.off"][1], "state") == "disabled"
        for path, idx, _cid in reg.menu_entries():
            reg.menus[path].invoke(idx)
        assert ran == ["one", "deep", ("flag", True), ("pick", "b")]
        reg.invoke("v.flag")
        assert flag.get() is False and ran[-1] == ("flag", False)
        assert reg.invoke("x.off") is None and "off" not in ran
        btn = reg.button(root, "t.only", text="Tool")
        assert btn._cs_command_id == "t.only"
        btn.invoke()
        assert ran[-1] == "tool"
    finally:
        root.destroy()


# --------------------------------------------------------------------------- prints stay white

def _print_html(prog, tmp_path, monkeypatch, name):
    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)
    if hasattr(os, "startfile"):
        monkeypatch.delattr(os, "startfile", raising=False)
    status = types.SimpleNamespace(text=None)
    status.configure = lambda **kw: setattr(status, "text", kw.get("text"))
    stub = types.SimpleNamespace(program=prog, project=types.SimpleNamespace(name=name, items=[]),
                                 _flush_editor_to_program=lambda: None, status=status)
    pv.ProgrammingViewer.print_ladder(stub)
    return (tmp_path / "cabinet_studio_ladder_print.html").read_bytes()


def _outputs(tmp_path, monkeypatch, mode):
    """Every printed / exported artefact, rendered with the UI in the given theme."""
    from test_drawings import _small_cabinet

    from cabinet_studio.services.drawings import build_sheets, render_svg
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.services.plcopen_xml import export_program_to_plcopen_xml
    from cabinet_studio.services.ladder_templates import apply_aoi_template
    from cabinet_studio.services.programming import empty_program, program_from_dict, write_ladder_logic

    theme.set_mode(mode, save=False)
    project = _small_cabinet()
    library = load_library()
    prog = program_from_dict(apply_aoi_template(empty_program(), "MotorStarter"))
    project.program = prog
    out = {f"sheet{i}.svg": render_svg(s, project).encode("utf-8") for i, s in enumerate(build_sheets(project, library))}
    folder = tmp_path / mode / "ladder"
    for path in write_ladder_logic(project, folder, program=prog):
        out[path.name] = path.read_bytes()
    out["plcopen.xml"] = export_program_to_plcopen_xml(prog, project_name="Print").encode("utf-8")
    sub = tmp_path / mode / "print"
    sub.mkdir(parents=True)
    out["ladder_print.html"] = _print_html(prog, sub, monkeypatch, "Print")
    return out


def test_prints_and_exports_are_byte_identical_and_white_in_every_theme(tmp_path, monkeypatch):
    light = _outputs(tmp_path, monkeypatch, "light")
    dark = _outputs(tmp_path, monkeypatch, "dark")
    system = _outputs(tmp_path, monkeypatch, "system")
    assert set(light) == set(dark) == set(system) and len(light) >= 5
    for name in light:
        assert light[name] == dark[name] == system[name], f"{name} changes with the UI theme"
    sheets = [k for k in light if k.startswith("sheet")]
    assert len(sheets) >= 3
    for name in sheets:
        svg = light[name].decode("utf-8")
        printed = re.sub(r"<desc>.*?</desc>", "", svg, flags=re.S)  # <desc> is metadata, never printed
        assert printed.count(FOOTER) == 1, f"{name}: footer must appear exactly once per sheet"
        assert re.search(r'fill="(#fff(fff)?|white)"', svg), f"{name}: sheet background is not white"
        for dark_hex in ("#0d0d0f", "#16161a"):
            assert not re.search(rf'fill="{dark_hex}"', svg.lower()), f"{name}: dark UI background leaked into the print"
    html = light["ladder_print.html"].decode("utf-8")
    assert FOOTER in html and SAFETY in html
    for dark_hex in ("#0d0d0f", "#16161a"):
        assert not re.search(rf'(background(-color)?:\s*|fill="){dark_hex}', html.lower()), "dark UI background in print"
    pages = re.split(r'<div class="(?:sheet )?page">', html)[1:]
    assert pages and all(p.count(FOOTER) == 1 for p in pages)


# --------------------------------------------------------------------------- docs / packaging

def test_new_modules_are_in_the_0322_spec():
    from pathlib import Path

    here = Path(__file__).resolve()
    candidates = [p / "builds" / "CabinetStudio-0.3.22.spec" for p in (here.parents[2], here.parents[3])]
    spec = next((p for p in candidates if p.exists()), candidates[0])
    if not spec.exists():
        pytest.skip("spec is created at freeze time")
    text = spec.read_text(encoding="utf-8")
    for mod in ("cabinet_studio.ui.commands", "cabinet_studio.ui.shell", "cabinet_studio.ui.shell.main_shell",
                "cabinet_studio.ui.shell.statusbar", "cabinet_studio.ui.shell.sim_toolbar"):
        assert f"'{mod}'" in text or f'"{mod}"' in text, mod
