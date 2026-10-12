"""Capture Cabinet Studio how-to screenshots from the live UI (same code as rebuilt exe)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["CABINET_STUDIO_NO_SPLASH"] = "1"
ROOT = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\mvp")
sys.path.insert(0, str(ROOT))

OUT = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\docs\how-to\images")
OUT.mkdir(parents=True, exist_ok=True)
SAMPLE = Path(r"C:\Users\spart\OneDrive\Desktop\CabinetStudio\saves\sample-motor-cabinet.cabinet.json")

from PIL import ImageGrab  # noqa: E402


def capture(app, name: str, settle: float = 0.7) -> None:
    app.update_idletasks()
    app.update()
    time.sleep(settle)
    try:
        app.lift()
        app.focus_force()
    except Exception:
        pass
    app.update()
    time.sleep(0.2)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    bbox = (max(0, x - 8), max(0, y - 32), x + w + 8, y + h + 8)
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    path = OUT / name
    img.save(path)
    print(f"saved {name} {img.size} {path.stat().st_size}")


def capture_widget(widget, name: str, settle: float = 0.5) -> None:
    widget.update_idletasks()
    widget.update()
    time.sleep(settle)
    try:
        widget.lift()
        widget.focus_force()
    except Exception:
        pass
    widget.update()
    time.sleep(0.2)
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    w, h = max(widget.winfo_width(), 100), max(widget.winfo_height(), 100)
    bbox = (max(0, x - 4), max(0, y - 4), x + w + 4, y + h + 4)
    img = ImageGrab.grab(bbox=bbox, all_screens=True)
    path = OUT / name
    img.save(path)
    print(f"saved {name} {img.size} {path.stat().st_size}")


def main() -> None:
    from cabinet_studio.services.drawings import build_sheets, default_drawings_folder, write_drawings
    from cabinet_studio.services.library_loader import load_library
    from cabinet_studio.ui.drawing_viewer import DrawingViewer
    from cabinet_studio.ui.main_window import CabinetStudioApp

    library = load_library()
    app = CabinetStudioApp(library)
    app.geometry("1400x860+60+40")
    app.update()
    time.sleep(0.9)

    capture(app, "02-main-open.png", 0.6)

    app.open_path(SAMPLE)
    app.update()
    time.sleep(0.5)
    capture(app, "04-sample-loaded.png", 0.8)

    # Left rail: top (project/devices) and scrolled (output/review)
    try:
        canvas = app.rail.body._parent_canvas
        canvas.yview_moveto(0.0)
        app.update()
        capture(app, "05-left-rail-top.png", 0.5)
        canvas.yview_moveto(0.28)
        app.update()
        capture(app, "06-left-rail-output.png", 0.5)
        canvas.yview_moveto(0.0)
    except Exception as exc:
        print("rail scroll:", exc)
        capture(app, "05-left-rail-top.png", 0.4)

    # Device selected + inspector (wire numbers / landings visible in right rail)
    if app.project.items:
        # Prefer a device that has wire_numbers / terminal_landings
        pick = app.project.items[0]
        for item in app.project.items:
            fields = item.fields or {}
            if fields.get("wire_numbers") or fields.get("terminal_landings"):
                pick = item
                break
        app.select_item(pick.id)
        app.update()
        capture(app, "07-inspector-selected.png", 0.7)

        app.edit_item(pick.id)
        app.update()
        time.sleep(0.9)
        wiz = app._wizard_window
        if wiz is not None and wiz.winfo_exists():
            capture_widget(wiz, "08-device-properties-editor.png", 0.8)
            # Advance a couple steps toward wiring if wizard has steps
            try:
                for _ in range(3):
                    if hasattr(wiz, "_next"):
                        wiz._next()
                        app.update()
                        time.sleep(0.35)
                capture_widget(wiz, "08b-device-wiring-fields.png", 0.6)
            except Exception as exc:
                print("wizard next:", exc)
            try:
                wiz.close()
            except Exception:
                pass
        app.update()
        time.sleep(0.3)

    # Drawings without blocking ask_choice
    folder = default_drawings_folder(app.project, app.path)
    paths = write_drawings(app.project, app.library, folder, selected_id=app.selected_id)
    app._last_drawing_paths = list(paths)
    sheets = build_sheets(app.project, app.library, selected_id=app.selected_id)
    capture(app, "09-cabinet-ready-for-drawings.png", 0.5)

    viewer = DrawingViewer(app, app.fonts, app.project, app.library, paths=paths, sheets=sheets)
    app.update()
    time.sleep(0.9)
    capture_widget(viewer, "10-view-drawings-sheet1.png", 0.8)
    try:
        viewer.next_sheet()
        app.update()
        time.sleep(0.5)
        capture_widget(viewer, "11-view-drawings-sheet2.png", 0.7)
    except Exception as exc:
        print("next_sheet:", exc)
    try:
        viewer.close()
    except Exception:
        try:
            viewer.destroy()
        except Exception:
            pass
    app.update()
    time.sleep(0.3)

    # Programming (sample already has a rung)
    app.open_programming()
    app.update()
    time.sleep(1.2)
    pv = app._programming_viewer
    if pv is not None and pv.winfo_exists():
        capture_widget(pv, "12-programming-open.png", 1.0)
        # Ensure ladder tab / detail
        try:
            if hasattr(pv, "_show_tab"):
                pv._show_tab("ladder")
                app.update()
                time.sleep(0.4)
        except Exception:
            pass
        capture_widget(pv, "13-programming-ladder.png", 0.8)
        try:
            pv.close()
        except Exception:
            try:
                pv.destroy()
            except Exception:
                pass
    app.update()
    time.sleep(0.4)
    capture(app, "14-back-to-cabinet.png", 0.5)

    # Show New build with AI at top of rail again
    try:
        app.rail.body._parent_canvas.yview_moveto(0.0)
    except Exception:
        pass
    app.update()
    capture(app, "03-rail-new-build-ai.png", 0.5)

    print("DONE")
    app.after(300, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
