"""Gate: the bundled user manual exists and every 'User manual' entry opens it headlessly."""

from __future__ import annotations

import os
import traceback
from pathlib import Path

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)

FOOTER = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."
SAFETY = "E-stop and safety functions must be hardwired or use rated safety relays (NFPA 79 / ISO 13849)."


def _opened(monkeypatch) -> list[str]:
    opened: list[str] = []
    monkeypatch.setattr("cabinet_studio.ui.manual.webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    return opened


def test_manual_file_is_in_the_package():
    import cabinet_studio
    from cabinet_studio.ui.manual import MANUAL_NAME, manual_path

    path = manual_path()
    assert path == Path(cabinet_studio.__file__).resolve().parent / "docs" / MANUAL_NAME
    assert path.is_file() and path.stat().st_size > 50_000
    text = path.read_text(encoding="utf-8")
    assert 'id="contents"' in text and FOOTER in text and SAFETY in text
    for heading in ("Installing Cabinet Studio", "New build with AI, step by step", "The simulator",
                    "The HMI editor", "The PLC / Device window", "Glossary: words you will see"):
        assert heading in text, heading


def test_manual_button_and_help_menu_open_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("CABINET_STUDIO_NO_SPLASH", "1")
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui import theme
    from cabinet_studio.ui.main_window import CabinetStudioApp
    from cabinet_studio.ui.manual import manual_path

    opened = _opened(monkeypatch)
    errors: list[str] = []
    app = CabinetStudioApp(load_library())
    app.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb)))
    try:
        app.update()
        btn = app.manual_button
        assert isinstance(btn, ctk.CTkButton) and btn.cget("text") == "? Manual"
        assert btn.winfo_toplevel() is app and btn.master is app.main_toolbar
        btn.invoke()
        app.update()
        assert opened == [manual_path().as_uri()]
        path, idx = app.commands.menu_index["main.manual"]
        assert path == "Help" and app.commands.menus[path].entrycget(idx, "label") == "User manual"
        app.commands.menus[path].invoke(idx)
        app.update()
        assert opened == [manual_path().as_uri()] * 2
        assert not errors, "\n\n".join(errors)
    finally:
        app.destroy()
        theme.set_mode("dark", save=False)


def test_manual_hover_help_attached(tmp_path, monkeypatch):
    monkeypatch.setenv("CABINET_STUDIO_NO_SPLASH", "1")
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui import hover_tip, theme
    from cabinet_studio.ui.main_window import CabinetStudioApp
    from cabinet_studio.ui.manual import MANUAL_TIP

    seen: list[tuple] = []
    real = hover_tip.attach
    monkeypatch.setattr("cabinet_studio.ui.shell.main_shell.attach_tip",
                        lambda w, text, *a, **k: seen.append((w, text)) or real(w, text, *a, **k))
    app = CabinetStudioApp(load_library())
    try:
        app.update()
        assert (app.manual_button, MANUAL_TIP) in seen
    finally:
        app.destroy()
        theme.set_mode("dark", save=False)


def test_programming_help_menu_opens_manual(tmp_path, monkeypatch):
    from cabinet_studio.models.project import Project
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui import theme
    from cabinet_studio.ui.manual import manual_path
    from cabinet_studio.ui.theme import Fonts, choose_families

    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    opened = _opened(monkeypatch)
    root = ctk.CTk()
    root.withdraw()
    project = Project(name="Gate", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1")
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *_: None)
    try:
        v.update()
        path, idx = v.commands.menu_index["help.manual"]
        assert path == "Help" and v.commands.menus[path].entrycget(idx, "label") == "User manual"
        v.commands.menus[path].invoke(idx)
        v.update()
        assert opened == [manual_path().as_uri()]
        assert "User manual opened" in v.status.cget("text")
    finally:
        try:
            v.close()
            root.update()
        except Exception:
            pass
        root.destroy()
        theme.set_mode("dark", save=False)
