"""The window is one CustomTkinter root. Splash, if shown, is its Toplevel."""

import os

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from cabinet_studio.services.completeness import is_complete
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display available for the CustomTkinter window",
)


def test_window_layout_wizard_and_splash_toplevel():
    os.environ["CABINET_STUDIO_NO_SPLASH"] = "1"
    from cabinet_studio.ui.main_window import CabinetStudioApp

    library = load_library()
    app = CabinetStudioApp(library)
    app.update()
    app.apply_layout("compact-machine-station")
    app.update()
    assert app.project.template_id == "compact-machine-station"
    assert len(app.project.items) >= 8
    assert any(
        not is_complete(item.fields, library.types[item.type_id].fields) for item in app.project.items
    )
    app.select_item(app.project.items[0].id)
    app.update()
    assert app.canvas_view.canvas.find_all()

    app._open_splash()
    app.update()
    splash = app._splash
    assert isinstance(splash, ctk.CTkToplevel)
    assert not isinstance(splash, ctk.CTk)
    assert splash.master is app
    splash.dismiss()
    app.update()

    app._replace_project(new_blank_project("Wizard check"), None, False, "reset")
    app.add_from_catalog("ab-prox-871c")
    app.update()
    assert app._wizard_window is not None
    assert isinstance(app._wizard_window, ctk.CTkToplevel)
    assert app._wizard_window.master is app
    app._wizard_window._finish()
    app.update()
    app._wizard_window._finish()
    app.update()
    assert len(app.project.items) == 1
    sensor = app.project.items[0]
    assert sensor.type_id == "sensor"
    assert not is_complete(sensor.fields, library.types["sensor"].fields)
    app.destroy()
