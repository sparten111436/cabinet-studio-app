"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

from cabinet_studio.services.library_loader import LibraryError, load_library
from cabinet_studio.ui.main_window import CabinetStudioApp
from cabinet_studio.ui.theme import load_mode


def _resolve_app_icon() -> Path | None:
    """Locate cabinet_studio.ico for window chrome (dev + frozen)."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                meipass / "assets" / "cabinet_studio.ico",
                exe_dir / "assets" / "cabinet_studio.ico",
                # live builds\CabinetStudio → CabinetStudio\assets
                exe_dir.parent.parent / "assets" / "cabinet_studio.ico",
            ]
        )
    else:
        # mvp/cabinet_studio/app.py → repo root is parents[2]
        root = Path(__file__).resolve().parents[2]
        candidates.append(root / "assets" / "cabinet_studio.ico")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _apply_window_icon(app: ctk.CTk) -> None:
    icon = _resolve_app_icon()
    if icon is None:
        return
    try:
        # Windows: .ico via iconbitmap; also try iconphoto for title bar consistency
        app.iconbitmap(default=str(icon))
    except Exception:
        try:
            app.iconbitmap(str(icon))
        except Exception:
            pass


def main() -> None:
    try:
        library = load_library()
    except LibraryError as exc:
        raise SystemExit(f"Cabinet Studio could not load the equipment library.\n{exc}") from exc
    load_mode()
    ctk.set_default_color_theme("blue")
    app = CabinetStudioApp(library)
    _apply_window_icon(app)
    app.mainloop()
