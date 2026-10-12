"""Small window helpers that stay off the equipment model."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from cabinet_studio.services.paths import saves_directory

_GEOM_RE = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")

# Multi-monitor positions can be negative or past the primary screen.
_MAX_DIM = 10000
_MAX_POS = 20000


def bind_deep(widget, sequence: str, callback) -> None:
    try:
        widget.bind(sequence, callback)
    except Exception:
        return
    for child in widget.winfo_children():
        bind_deep(child, sequence, callback)


def center_on_parent(window, width: int, height: int, parent) -> None:
    window.update_idletasks()
    parent_width = parent.winfo_width()
    parent_height = parent.winfo_height()
    if parent_width < 100 or parent_height < 100:
        x = max(0, (window.winfo_screenwidth() - width) // 2)
        y = max(0, (window.winfo_screenheight() - height) // 2)
    else:
        x = parent.winfo_rootx() + max(0, (parent_width - width) // 2)
        y = parent.winfo_rooty() + max(0, (parent_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def fit_text(text: str, font, max_px: int) -> str:
    if max_px <= 8:
        return ""
    if font.measure(text) <= max_px:
        return text
    ellipsis = "…"
    trimmed = text
    while trimmed and font.measure(trimmed + ellipsis) > max_px:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def ui_geometry_path() -> Path:
    """Persisted pop-out canvas geometries (WxH+X+Y) live under saves/."""
    return saves_directory() / "ui_window_geometry.json"


def parse_geometry(geom: str) -> tuple[int, int, int, int] | None:
    if not geom or not isinstance(geom, str):
        return None
    m = _GEOM_RE.match(geom.strip())
    if not m:
        return None
    w, h, x, y = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return w, h, x, y


def format_geometry(w: int, h: int, x: int, y: int) -> str:
    return f"{int(w)}x{int(h)}+{int(x)}+{int(y)}"


def geometry_is_reasonable(
    w: int,
    h: int,
    x: int,
    y: int,
    *,
    min_w: int,
    min_h: int,
) -> bool:
    """Accept multi-monitor coords; only reject tiny or absurd sizes/positions."""
    if w < min_w or h < min_h:
        return False
    if w > _MAX_DIM or h > _MAX_DIM:
        return False
    if abs(x) > _MAX_POS or abs(y) > _MAX_POS:
        return False
    return True


def load_ui_geometry(key: str) -> str | None:
    path = ui_geometry_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    val = data.get(key)
    return val if isinstance(val, str) else None


def save_ui_geometry(key: str, geom: str) -> None:
    parsed = parse_geometry(geom)
    if parsed is None:
        return
    path = ui_geometry_path()
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    data[key] = format_geometry(*parsed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def apply_saved_geometry(
    window,
    key: str,
    *,
    default_w: int,
    default_h: int,
    min_w: int,
    min_h: int,
    parent=None,
    center_fallback: bool = False,
) -> str:
    """Restore saved WxH+X+Y, else usable default (optionally centered on parent)."""
    saved = load_ui_geometry(key)
    if saved:
        parsed = parse_geometry(saved)
        if parsed and geometry_is_reasonable(*parsed, min_w=min_w, min_h=min_h):
            window.geometry(saved)
            return saved
    if center_fallback and parent is not None:
        center_on_parent(window, default_w, default_h, parent)
        return format_geometry(default_w, default_h, 0, 0)
    try:
        x = max(40, (window.winfo_screenwidth() - default_w) // 4)
        y = max(20, (window.winfo_screenheight() - default_h) // 5)
    except Exception:
        x, y = 80, 60
    geom = format_geometry(default_w, default_h, x, y)
    window.geometry(geom)
    return geom


def read_window_geometry(window) -> str | None:
    try:
        # Prefer wm geometry which includes +x+y even when briefly inconsistent.
        g = window.geometry()
        if parse_geometry(g):
            return g
        window.update_idletasks()
        w = int(window.winfo_width())
        h = int(window.winfo_height())
        x = int(window.winfo_rootx())
        y = int(window.winfo_rooty())
        return format_geometry(w, h, x, y)
    except Exception:
        return None


def remember_window_geometry(window, key: str, *, min_w: int, min_h: int) -> None:
    geom = read_window_geometry(window)
    if not geom:
        return
    parsed = parse_geometry(geom)
    if not parsed or not geometry_is_reasonable(*parsed, min_w=min_w, min_h=min_h):
        return
    save_ui_geometry(key, geom)


def bind_geometry_autosave(
    window,
    key: str,
    *,
    min_w: int,
    min_h: int,
    debounce_ms: int = 400,
) -> Callable[[], None]:
    """Debounced Configure → save. Returns a flush() to call on close."""
    state = {"after": None}

    def _save(_event=None) -> None:
        state["after"] = None
        remember_window_geometry(window, key, min_w=min_w, min_h=min_h)

    def _on_configure(_event=None) -> None:
        try:
            if state["after"] is not None:
                window.after_cancel(state["after"])
        except Exception:
            pass
        try:
            state["after"] = window.after(debounce_ms, _save)
        except Exception:
            _save()

    def flush() -> None:
        try:
            if state["after"] is not None:
                window.after_cancel(state["after"])
                state["after"] = None
        except Exception:
            pass
        remember_window_geometry(window, key, min_w=min_w, min_h=min_h)

    try:
        window.bind("<Configure>", _on_configure, add="+")
    except Exception:
        pass
    return flush
