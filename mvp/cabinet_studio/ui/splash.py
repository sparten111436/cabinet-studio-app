"""Startup splash. Always a Toplevel owned by the main CTk window."""

from __future__ import annotations

import customtkinter as ctk

from cabinet_studio import __version__
from cabinet_studio.ui.theme import BG, CYAN, MUTED, ORANGE, TEXT
from cabinet_studio.ui.util import bind_deep, center_on_parent


class Splash(ctk.CTkToplevel):
    def __init__(self, master, fonts, on_done=None) -> None:
        super().__init__(master, fg_color=BG)
        self.on_done = on_done
        self._closed = False
        self.title("Cabinet Studio")
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.dismiss)
        center_on_parent(self, 520, 300, master)
        self._build(fonts)
        self.bind("<Escape>", lambda _event: self.dismiss())
        bind_deep(self, "<Button-1>", lambda _event: self.dismiss())
        self.after(80, self._arm)
        self.after(1100, self.dismiss)

    def _build(self, fonts) -> None:
        mark = ctk.CTkFrame(self, width=18, height=18, fg_color=ORANGE, corner_radius=2)
        mark.pack(pady=(54, 16))
        mark.pack_propagate(False)
        ctk.CTkLabel(
            self,
            text="CABINET STUDIO",
            font=fonts.title,
            text_color=TEXT,
        ).pack()
        ctk.CTkLabel(
            self,
            text="WARREN WILLIAMS  ·  ERMCO",
            font=fonts.small,
            text_color=MUTED,
        ).pack(pady=(4, 16))
        rule = ctk.CTkFrame(self, width=180, height=2, fg_color=ORANGE, corner_radius=0)
        rule.pack(pady=(0, 16))
        rule.pack_propagate(False)
        ctk.CTkLabel(
            self,
            text="Cabinet, PLC, HMI, and network design.",
            font=fonts.body,
            text_color=TEXT,
        ).pack()
        ctk.CTkLabel(
            self,
            text="Define every device the PLC will supervise.",
            font=fonts.small,
            text_color=CYAN,
        ).pack(pady=(6, 0))
        ctk.CTkLabel(
            self,
            text=f"MVP {__version__}  ·  click to continue",
            font=fonts.tiny,
            text_color=MUTED,
        ).pack(pady=(22, 0))

    def _arm(self) -> None:
        if self._closed:
            return
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            return

    def dismiss(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        if self.on_done is not None:
            self.on_done()
