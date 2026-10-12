"""Test-session hardening (not product code).

On Windows, creating a fresh Tk interpreter after many earlier ones were destroyed in the
same process intermittently fails while Tcl / Tk read their own init.tcl / tk.tcl
("couldn't read file ... No error" / "invalid command name tcl_findLibrary"). The app creates
one root, so only the test suite hits it. Retry ONLY that start-up failure; every other
TclError still raises.
"""
from __future__ import annotations

import os
import time
import tkinter
import webbrowser

import pytest

_TCL_STARTUP_FLAKE = ("init.tcl", "tk.tcl", "tcl_findLibrary", "wasn't installed properly")
_orig_tk_init = tkinter.Tk.__init__


def _tk_init_with_retry(self, *args, **kwargs):
    for attempt in range(6):
        try:
            return _orig_tk_init(self, *args, **kwargs)
        except tkinter.TclError as exc:
            if attempt == 5 or not any(s in str(exc) for s in _TCL_STARTUP_FLAKE):
                raise
            time.sleep(0.25 * (attempt + 1))
    return None


tkinter.Tk.__init__ = _tk_init_with_retry


@pytest.fixture(autouse=True)
def _no_real_windows_opened(monkeypatch):
    """Print / View drawings call os.startfile (Windows) or webbrowser.open. Tests must never
    open real browser windows or print dialogs; without os.startfile the app falls back to
    webbrowser.open, which a test may still replace to capture the page."""
    if hasattr(os, "startfile"):
        monkeypatch.delattr(os, "startfile")
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(webbrowser, "open_new", lambda *a, **k: True)
    monkeypatch.setattr(webbrowser, "open_new_tab", lambda *a, **k: True)
