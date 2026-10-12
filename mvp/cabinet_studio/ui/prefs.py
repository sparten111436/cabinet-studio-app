"""Small UI preferences (pane widths, collapsed panels) in saves/ui_prefs.json.

Same file the Programming screen already uses for keep-on-top / layout flags.
"""

from __future__ import annotations

import json
from pathlib import Path

from cabinet_studio.ui.util import ui_geometry_path


def ui_prefs_path() -> Path:
    return ui_geometry_path().with_name("ui_prefs.json")


def load_pref(key: str, default=None):
    try:
        data = json.loads(ui_prefs_path().read_text(encoding="utf-8"))
        return data.get(key, default) if isinstance(data, dict) else default
    except Exception:
        return default


def save_pref(key: str, value) -> None:
    path = ui_prefs_path()
    data: dict = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        data = {}
    data[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        pass


def load_width(key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(load_pref(key, default))))
    except (TypeError, ValueError):
        return default
