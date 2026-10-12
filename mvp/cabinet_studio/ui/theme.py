"""Industrial palette shared by every Cabinet Studio window.

v0.3.22: every colour is a ``(light, dark)`` pair. CustomTkinter widgets take the
pair directly and repaint themselves when the appearance mode changes. Plain Tk
widgets and canvas items need one string: use ``c(name)`` and redraw from an
``on_theme_change`` callback. Printed / exported drawings never read this module.
"""

from __future__ import annotations

import json
import tkinter.font as tkfont
from typing import Callable

import customtkinter as ctk

MODES = ("light", "dark", "system")
_MODE_PREF = "ui_theme_mode"

PALETTE: dict[str, tuple[str, str]] = {
    "BG": ("#f3f3f5", "#0d0d0f"),
    "PANEL": ("#ffffff", "#16161a"),
    "RAISED": ("#eceef2", "#1c1c22"),
    "BORDER": ("#c9cbd3", "#2a2a32"),
    "TEXT": ("#1b1b22", "#e7e7ee"),
    "MUTED": ("#5d5f6b", "#9a9aa8"),
    "ORANGE": ("#b85400", "#ff8a1f"),
    "CYAN": ("#007a73", "#2ee6d6"),
    "BLUE": ("#2f6bff", "#2f6bff"),
    "BLUE_HOVER": ("#2457d6", "#2457d6"),
    "DANGER_BG": ("#fde4e4", "#3a1d1d"),
    "DANGER_HOVER": ("#f8caca", "#5c2424"),
    "DANGER_TEXT": ("#9b1c1c", "#ffb4b4"),
    "DANGER_BORDER": ("#e09a9a", "#7f2d2d"),
    "ENTRY": ("#ffffff", "#0d0d0f"),
    "TILE": ("#f0f1f5", "#1a1a22"),
    "GHOST": ("#f4f5f8", "#22222a"),
    "GHOST_HOVER": ("#e2e5ec", "#2e2e38"),
    "HOVER": ("#dbe6ff", "#243044"),
    "TRACK": ("#d5d7de", "#2a2a32"),
    "TRACK_HOVER": ("#b9bcc6", "#3a3a44"),
    "WARN_BG": ("#fff1e0", "#2a1c10"),
    "OK_BG": ("#e2f6ef", "#10241f"),
    "STATUS_BG": ("#e7e8ec", "#101014"),
    "PILL_BG": ("#fff1e0", "#24180f"),
    "TIP_BG": ("#fffbe6", "#1e2430"),
    "TIP_BORDER": ("#c9b97a", "#3a4558"),
    "TIP_TEXT": ("#1b1b22", "#e8ecf4"),
    "ERROR_ROW": ("#fde4e4", "#5c1a22"),
    "ERROR_ROW_HOVER": ("#f8caca", "#7a2430"),
    "WARNING_ROW": ("#fff4d6", "#5a4614"),
    "WARNING_ROW_HOVER": ("#ffe9ad", "#735a1a"),
    "PLOT_BG": ("#ffffff", "#1a1f2a"),
    "PLOT_GRID": ("#dfe3ea", "#2a3344"),
    "PLOT_TEXT": ("#5d6576", "#7a8499"),
    # Cabinet elevation canvas
    "SHADOW": ("#c4c6ce", "#070708"),
    "PLATE": ("#e6e7eb", "#121216"),
    "PLATE_EDGE": ("#9a9ca6", "#3a3a44"),
    "PLATE_HEAD": ("#ffffff", "#16161a"),
    "SCREW": ("#f7f7f9", "#1a1a20"),
    "DIN_RAIL": ("#b5b7c0", "#2a2a32"),
    "TILE_SELECTED": ("#dce8f7", "#1c2836"),
    "TILE_HOVER": ("#ececf1", "#20202a"),
    "TILE_FILL": ("#fafafc", "#1a1a22"),
    "TILE_DETAIL": ("#3a3b45", "#c8c8d2"),
    "LEGEND": ("#8a5a14", "#6d5330"),
    # Drawing viewer desk around the (always white) sheet
    "DESK": ("#e4e2dc", "#d8d4cc"),
    # Mode badges (status bar)
    "BADGE_PROG": ("#2f6bff", "#2f6bff"),
    "BADGE_RUN": ("#12a150", "#12a150"),
    "BADGE_STEP": ("#c98a00", "#d99a00"),
    "BADGE_TEXT": ("#ffffff", "#ffffff"),
}

BG = PALETTE["BG"]
PANEL = PALETTE["PANEL"]
RAISED = PALETTE["RAISED"]
BORDER = PALETTE["BORDER"]
TEXT = PALETTE["TEXT"]
MUTED = PALETTE["MUTED"]
ORANGE = PALETTE["ORANGE"]
CYAN = PALETTE["CYAN"]
BLUE = PALETTE["BLUE"]
BLUE_HOVER = PALETTE["BLUE_HOVER"]
DANGER_BG = PALETTE["DANGER_BG"]
DANGER_HOVER = PALETTE["DANGER_HOVER"]
DANGER_TEXT = PALETTE["DANGER_TEXT"]
DANGER_BORDER = PALETTE["DANGER_BORDER"]
ENTRY = PALETTE["ENTRY"]
TILE = PALETTE["TILE"]
GHOST = PALETTE["GHOST"]
GHOST_HOVER = PALETTE["GHOST_HOVER"]
HOVER = PALETTE["HOVER"]
TRACK = PALETTE["TRACK"]
TRACK_HOVER = PALETTE["TRACK_HOVER"]
WARN_BG = PALETTE["WARN_BG"]
OK_BG = PALETTE["OK_BG"]
STATUS_BG = PALETTE["STATUS_BG"]
PILL_BG = PALETTE["PILL_BG"]
TIP_BG = PALETTE["TIP_BG"]
TIP_BORDER = PALETTE["TIP_BORDER"]
TIP_TEXT = PALETTE["TIP_TEXT"]

RAIL_WIDTH = 288
INSPECTOR_WIDTH = 332

# The ladder canvas stays a light "paper" in both themes: pure white in Light,
# the classic parchment in Dark. Symbol colours are the same in both.
_LADDER_BG = ("#ffffff", "#d8d4cc")

_listeners: list[Callable[[str], None]] = []


def is_dark() -> bool:
    return ctk.get_appearance_mode().lower() == "dark"


def c(name_or_pair) -> str:
    """One Tk colour string for the active mode (for tk.Canvas / tk widgets)."""
    pair = PALETTE[name_or_pair] if isinstance(name_or_pair, str) and name_or_pair in PALETTE else name_or_pair
    if isinstance(pair, (tuple, list)):
        return pair[1] if is_dark() else pair[0]
    return str(pair)


def ladder_palette() -> dict[str, str]:
    """Colours for the on-screen ladder canvas (never used for prints)."""
    return {"bg": c(_LADDER_BG)}


def _prefs_path():
    from cabinet_studio.ui.util import ui_geometry_path

    return ui_geometry_path().with_name("ui_prefs.json")


def saved_mode() -> str:
    try:
        data = json.loads(_prefs_path().read_text(encoding="utf-8"))
        mode = str(data.get(_MODE_PREF, "dark")).lower() if isinstance(data, dict) else "dark"
    except Exception:
        mode = "dark"
    return mode if mode in MODES else "dark"


def _save_mode(mode: str) -> None:
    path = _prefs_path()
    data: dict = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        data = {}
    data[_MODE_PREF] = mode
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        pass


_state = {"mode": None}


def current_mode() -> str:
    return _state["mode"] or saved_mode()


def load_mode() -> str:
    """Apply the saved Light / Dark / System mode (call before the root window exists)."""
    mode = saved_mode()
    ctk.set_appearance_mode(mode)
    _state["mode"] = mode
    return mode


def set_mode(mode: str, *, save: bool = True) -> str:
    mode = str(mode or "dark").lower()
    if mode not in MODES:
        mode = "dark"
    ctk.set_appearance_mode(mode)
    _state["mode"] = mode
    if save:
        _save_mode(mode)
    for cb in list(_listeners):
        try:
            cb(mode)
        except Exception:
            # A destroyed window's callback is dropped instead of breaking the others.
            remove_theme_listener(cb)
    return mode


def toggle_mode() -> str:
    return set_mode("light" if is_dark() else "dark")


def on_theme_change(cb: Callable[[str], None]) -> Callable[[str], None]:
    if cb not in _listeners:
        _listeners.append(cb)
    return cb


def remove_theme_listener(cb) -> None:
    try:
        _listeners.remove(cb)
    except ValueError:
        pass


def bind_theme_redraw(widget, cb: Callable[[], None]) -> None:
    """Call cb() on theme change while widget lives; unregister when it is destroyed."""

    def listener(_mode: str) -> None:
        if not widget.winfo_exists():
            raise RuntimeError("widget gone")
        cb()

    on_theme_change(listener)

    def _gone(event, _l=listener):
        if event.widget is widget:
            remove_theme_listener(_l)

    try:
        widget.bind("<Destroy>", _gone, add="+")
    except Exception:
        pass


class Fonts:
    def __init__(self, ui: str, mono: str) -> None:
        self.ui_family = ui
        self.mono_family = mono
        self.ui = ui
        self.title = ctk.CTkFont(family=ui, size=18, weight="bold")
        self.heading = ctk.CTkFont(family=ui, size=13, weight="bold")
        self.body = ctk.CTkFont(family=ui, size=13)
        self.small = ctk.CTkFont(family=ui, size=11)
        self.tiny = ctk.CTkFont(family=ui, size=10)
        self.tag = ctk.CTkFont(family=mono, size=14, weight="bold")
        self.mono = ctk.CTkFont(family=mono, size=12, weight="bold")
        self.mono_small = ctk.CTkFont(family=mono, size=11)


def choose_families(root) -> tuple[str, str]:
    families = set(tkfont.families(root))
    ui = next(
        (
            name
            for name in ("Segoe UI", "Inter", "Noto Sans", "Liberation Sans", "DejaVu Sans")
            if name in families
        ),
        "TkDefaultFont",
    )
    mono = next(
        (
            name
            for name in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Liberation Mono")
            if name in families
        ),
        "TkFixedFont",
    )
    return ui, mono


def primary_button(master, text: str, command, font, width: int = 140):
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        font=font,
        width=width,
        height=34,
        corner_radius=4,
        fg_color=BLUE,
        hover_color=BLUE_HOVER,
        text_color="#ffffff",
    )


def ghost_button(master, text: str, command, font, width: int = 120):
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        font=font,
        width=width,
        height=34,
        corner_radius=4,
        fg_color=GHOST,
        hover_color=GHOST_HOVER,
        text_color=TEXT,
        border_width=1,
        border_color=BORDER,
    )


def danger_button(master, text: str, command, font, width: int = 120):
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        font=font,
        width=width,
        height=34,
        corner_radius=4,
        fg_color=DANGER_BG,
        hover_color=DANGER_HOVER,
        text_color=DANGER_TEXT,
        border_width=1,
        border_color=DANGER_BORDER,
    )


def entry(master, font, **kwargs):
    return ctk.CTkEntry(
        master,
        font=font,
        height=34,
        corner_radius=4,
        fg_color=ENTRY,
        border_color=BORDER,
        text_color=TEXT,
        placeholder_text_color=MUTED,
        **kwargs,
    )


def scroll_frame(master):
    return ctk.CTkScrollableFrame(
        master,
        fg_color=PANEL,
        scrollbar_fg_color=PANEL,
        scrollbar_button_color=TRACK,
        scrollbar_button_hover_color=ORANGE,
        corner_radius=0,
    )


def section_label(master, text: str, font):
    return ctk.CTkLabel(
        master,
        text=text,
        font=font,
        text_color=ORANGE,
        anchor="w",
    )
