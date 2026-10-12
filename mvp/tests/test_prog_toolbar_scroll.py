"""Programming toolbars stay horizontally scrollable (no clipped buttons)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("customtkinter")

import customtkinter as ctk

from cabinet_studio.ui.programming_viewer import _hscroll_strip
from cabinet_studio.ui.theme import BG, PANEL, BORDER

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)


def test_hscroll_strip_is_horizontal():
    root = ctk.CTk()
    root.withdraw()
    try:
        shell, inner = _hscroll_strip(root, fg_color=BG, height=40)
        shell.pack(fill="x")
        inner.pack(side="left", fill="both", expand=True)
        assert getattr(inner, "_orientation", None) == "horizontal"
        for i in range(12):
            ctk.CTkButton(inner, text=f"Btn{i}", width=120).pack(side="left", padx=4)
        root.update_idletasks()
        # Content wider than a narrow shell should still exist as children
        assert len(inner.winfo_children()) == 12
        shell2, inner2 = _hscroll_strip(
            root, fg_color=PANEL, height=36, corner_radius=4, border_width=1, border_color=BORDER
        )
        assert shell2.cget("border_width") == 1
        assert getattr(inner2, "_orientation", None) == "horizontal"
    finally:
        root.destroy()
