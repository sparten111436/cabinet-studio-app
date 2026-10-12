"""Main window chrome (v0.3.22): native menu bar, compact toolbar, slimmer header.

Installed by a two-line hook in ``main_window.py`` after its ``_build()``. It only
adds widgets and re-styles the existing header / status bar; the library rail and
its sticky OUTPUT section are not touched.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio import __version__
from cabinet_studio.ui.commands import CommandRegistry
from cabinet_studio.ui.dialogs import ask_choice
from cabinet_studio.ui.hover_tip import attach as attach_tip
from cabinet_studio.ui.manual import MANUAL_TIP, manual_path, open_manual
from cabinet_studio.ui.starter_gallery import open_starter_gallery
from cabinet_studio.ui.shell.project_explorer import (
    install_project_explorer,
    make_pane_vars,
    set_explorer_visible,
    set_rail_compact,
)
from cabinet_studio.ui.theme import (
    BORDER,
    MUTED,
    PANEL,
    PILL_BG,
    STATUS_BG,
    bind_theme_redraw,
    current_mode,
    is_dark,
    set_mode,
    toggle_mode,
)

HEADER_HEIGHT = 44
TEMPLATES_TIP = ("Start a new cabinet from a ready-made template (motor starter, conveyor, pump, press, mixer, "
                 "pick-and-place, fan, lighting, PLC trainer). Asks to save the open cabinet first.")
SHORTCUTS_TEXT = (
    "Ctrl+N  New project\nCtrl+O  Open\nCtrl+S  Save\nCtrl+Shift+S  Save As\n"
    "Ctrl+Z  Undo\nDelete  Remove the selected device\nDouble-click a tile  Define the device"
)


def _call(app, name: str):
    """Late-bound so tests (and future code) can swap the app method."""
    return lambda: getattr(app, name)()


def _register(app, reg: CommandRegistry) -> None:
    add = reg.add
    add("main.new", "New project…", _call(app, "new_project"), menu="File", shortcut="Ctrl+N")
    add("main.new_template", "New from template…", _call(app, "new_from_template"), menu="File")
    add("main.new_ai", "New build with AI…", _call(app, "new_build_with_ai"), menu="File")
    add("main.open", "Open…", _call(app, "open_project"), menu="File", shortcut="Ctrl+O")
    reg.separator("File")
    add("main.save", "Save", _call(app, "save"), menu="File", shortcut="Ctrl+S")
    add("main.save_as", "Save As…", _call(app, "save_as"), menu="File", shortcut="Ctrl+Shift+S")
    reg.separator("File")
    add("main.programs", "Program library…", _call(app, "open_programs"), menu="File")
    add("main.desktop_shortcut", "Install desktop shortcut", _call(app, "install_desktop_shortcut"), menu="File")
    reg.separator("File")
    add("main.exit", "Exit", _call(app, "_on_close"), menu="File")

    add("main.undo", "Undo", _call(app, "undo"), menu="Edit", shortcut="Ctrl+Z")
    add("main.delete", "Delete selected device", _call(app, "delete_selected"), menu="Edit", shortcut="Del")
    reg.separator("Edit")
    add("main.add_blank", "Add device…", _call(app, "add_blank"), menu="Edit")

    for mode, label in (("light", "Light"), ("dark", "Dark"), ("system", "System")):
        add(f"main.theme.{mode}", label, lambda: set_mode(app._theme_var.get()), menu="View/Theme", kind="radio",
            variable=app._theme_var, value=mode)
    add("main.theme_toggle", "Light / Dark", toggle_mode)
    reg.separator("View")
    add("main.view_explorer", "Project explorer", lambda: set_explorer_visible(app, app._explorer_var.get()),
        menu="View", kind="check", variable=app._explorer_var)
    add("main.view_rail_compact", "Compact library rail", lambda: set_rail_compact(app, app._rail_compact_var.get()),
        menu="View", kind="check", variable=app._rail_compact_var)
    reg.separator("View")
    add("main.view_drawings", "View drawings", _call(app, "view_drawings"), menu="View")

    add("main.drawings", "Generate drawings", _call(app, "generate_drawings"), menu="Tools")
    add("main.programming", "Programming", _call(app, "open_programming"), menu="Tools")
    reg.separator("Tools")
    add("main.guide", "Guide build", _call(app, "guide_build"), menu="Tools")
    add("main.suggest", "AI suggest devices", _call(app, "ai_suggest"), menu="Tools")
    add("main.apply_all", "Apply all suggestions", _call(app, "apply_all_ai_suggestions"), menu="Tools")
    add("main.ul508a", "UL 508A review", _call(app, "open_ul508a_review"), menu="Tools")

    add("main.manual", "User manual", lambda: _open_manual(app), menu="Help")
    add("main.shortcuts", "Keyboard shortcuts", lambda: _info(app, "Keyboard shortcuts", SHORTCUTS_TEXT),
        menu="Help")
    add("main.about", "About Cabinet Studio", lambda: _info(
        app, "About Cabinet Studio",
        f"Cabinet Studio v{__version__}\nWarren Williams · ERMCO\n\n"
        "NOT A CERTIFIED UL 508A DRAWING. Design aid only.\n\n"
        "E-stop and safety functions must be hardwired or use rated safety relays "
        "(NFPA 79 / ISO 13849). The software is never the safety function.",
    ), menu="Help")


def _info(app, title: str, text: str) -> None:
    ask_choice(app, app.fonts, title, text, [("ok", "OK", "primary")])


def _open_manual(app) -> bool:
    if open_manual():
        return True
    _info(app, "User manual", f"The user manual was not found:\n{manual_path()}")
    return False


def _find_frames(app):
    header = status = None
    for child in app.winfo_children():
        if not isinstance(child, ctk.CTkFrame):
            continue
        try:
            fg = child.cget("fg_color")
            height = int(child.cget("height"))
        except Exception:
            continue
        if header is None and height == 72:
            header = child
        elif status is None and fg == "#101014":
            status = child
    return header, status


def _slim_header(header) -> None:
    header.configure(height=HEADER_HEIGHT)
    for child in header.winfo_children():
        try:
            if child.winfo_manager() != "pack":
                continue
            if isinstance(child, ctk.CTkEntry):
                child.configure(height=30)
                child.pack_configure(pady=6)
            else:
                child.pack_configure(pady=6)
            if isinstance(child, ctk.CTkFrame) and child.cget("fg_color") == "#24180f":
                child.configure(fg_color=PILL_BG)
        except Exception:
            continue
        for sub in child.winfo_children():
            try:
                if isinstance(sub, ctk.CTkLabel) and "WARREN WILLIAMS" in str(sub.cget("text")):
                    sub.grid_remove()
            except Exception:
                pass


def install_main_shell(app) -> CommandRegistry:
    """Menu bar + compact toolbar + slim header + themed status bar on the main window."""
    app._theme_var = tk.StringVar(master=app, value=current_mode())
    app.new_from_template = lambda: open_starter_gallery(app)
    make_pane_vars(app)
    reg = CommandRegistry()
    app.commands = reg
    _register(app, reg)
    reg.build_menubar(app)
    app.invoke_command = reg.invoke

    header, status = _find_frames(app)
    if header is not None:
        _slim_header(header)
    if status is not None:
        status.configure(fg_color=STATUS_BG)
        app.version_label = ctk.CTkLabel(
            status, text=f"v{__version__}  ·  Warren Williams · ERMCO", font=app.fonts.tiny, text_color=MUTED
        )
        app.version_label.pack(side="right", padx=12)
    app.main_header = header

    bar = ctk.CTkFrame(app, height=36, fg_color=PANEL, corner_radius=0)
    body = app.rail.master
    bar.pack(side="top", fill="x", before=body)
    bar.pack_propagate(False)
    app.main_toolbar = bar
    font = app.fonts.small

    def sep():
        ctk.CTkFrame(bar, width=1, height=20, fg_color=BORDER, corner_radius=0).pack(side="left", padx=6, pady=8)

    for cmd_id, text, width in (("main.new", "New", 56), ("main.new_template", "Templates", 84),
                                ("main.open", "Open", 60), ("main.save", "Save", 60)):
        btn = reg.button(bar, cmd_id, text=text, width=width, font=font)
        btn.pack(side="left", padx=(4, 2), pady=4)
        if cmd_id == "main.new_template":
            app.templates_button = btn
            attach_tip(btn, TEMPLATES_TIP, "Start from a template")
    sep()
    reg.button(bar, "main.undo", text="Undo", width=60, font=font).pack(side="left", padx=2, pady=4)
    sep()
    for cmd_id, text, width in (("main.drawings", "Drawings", 80), ("main.view_drawings", "View drawings", 106),
                                ("main.programming", "Programming", 104)):
        reg.button(bar, cmd_id, text=text, width=width, font=font).pack(side="left", padx=2, pady=4)
    sep()
    reg.button(bar, "main.ul508a", text="UL 508A review", width=112, font=font).pack(side="left", padx=2, pady=4)
    sep()
    reg.button(bar, "main.view_explorer", text="Explorer", width=76, font=font).pack(side="left", padx=2, pady=4)
    reg.button(bar, "main.view_rail_compact", text="Compact rail", width=96, font=font).pack(
        side="left", padx=2, pady=4)
    install_project_explorer(app)
    app.theme_button = reg.button(bar, "main.theme_toggle", text=_toggle_text(), width=92, font=font)
    app.theme_button.pack(side="right", padx=10, pady=4)
    app.manual_button = reg.button(bar, "main.manual", text="? Manual", width=84, font=font)
    app.manual_button.pack(side="right", padx=2, pady=4)
    attach_tip(app.manual_button, MANUAL_TIP, "User manual")

    def on_theme() -> None:
        app._theme_var.set(current_mode())
        app.theme_button.configure(text=_toggle_text())

    bind_theme_redraw(bar, on_theme)
    return reg


def _toggle_text() -> str:
    return "☀ Light" if is_dark() else "☾ Dark"
