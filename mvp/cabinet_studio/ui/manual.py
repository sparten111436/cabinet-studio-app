"""Open the bundled user manual (HTML) in the default web browser."""

from __future__ import annotations

import webbrowser
from pathlib import Path

MANUAL_NAME = "Cabinet-Studio-User-Manual.html"
MANUAL_TIP = ("Opens the Cabinet Studio user manual in your web browser: step-by-step help for every page, "
              "a glossary and the safety rules. Press Ctrl+P in the browser to print it.")


def manual_path() -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / MANUAL_NAME


def open_manual() -> bool:
    path = manual_path()
    if not path.is_file():
        return False
    webbrowser.open(path.as_uri())
    return True
