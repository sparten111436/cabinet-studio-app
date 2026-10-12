"""Bottom status bar: mode badge, scan #, rung n/N, error count, message, badges, version."""

from __future__ import annotations

import customtkinter as ctk

from cabinet_studio.ui.theme import BORDER, MUTED, PALETTE, STATUS_BG, TEXT

EDU_BADGE = "Educational ladder + scan sim, not a PLC download"
_MODE_COLOURS = {"PROG": "BADGE_PROG", "RUN": "BADGE_RUN", "STEP": "BADGE_STEP"}


class StatusBar(ctk.CTkFrame):
    def __init__(self, master, fonts, *, version: str, badge: str = EDU_BADGE, show_sim: bool = True) -> None:
        super().__init__(master, height=26, fg_color=STATUS_BG, corner_radius=0, border_width=0)
        self.pack_propagate(False)
        self.mode = "PROG"
        self.mode_label = None
        self.scan_label = None
        self.rung_label = None
        self.error_label = None
        if show_sim:
            self.mode_label = ctk.CTkLabel(
                self, text=" PROG ", font=fonts.tiny, width=52, height=18, corner_radius=3,
                fg_color=PALETTE["BADGE_PROG"], text_color=PALETTE["BADGE_TEXT"],
            )
            self.mode_label.pack(side="left", padx=(8, 6), pady=4)
            self.scan_label = ctk.CTkLabel(self, text="scan -", font=fonts.tiny, text_color=MUTED, width=70, anchor="w")
            self.scan_label.pack(side="left", padx=4)
            self.rung_label = ctk.CTkLabel(self, text="rung -", font=fonts.tiny, text_color=MUTED, width=80, anchor="w")
            self.rung_label.pack(side="left", padx=4)
            self.error_label = ctk.CTkLabel(self, text="0 errors", font=fonts.tiny, text_color=MUTED, width=70, anchor="w")
            self.error_label.pack(side="left", padx=4)
            ctk.CTkFrame(self, width=1, fg_color=BORDER, corner_radius=0).pack(side="left", fill="y", pady=4, padx=4)
        self.version_label = ctk.CTkLabel(self, text=f"v{version}", font=fonts.tiny, text_color=MUTED)
        self.version_label.pack(side="right", padx=(6, 10))
        self.badge_label = ctk.CTkLabel(
            self, text=badge, font=fonts.tiny, text_color=PALETTE["ORANGE"], anchor="e",
        )
        self.badge_label.pack(side="right", padx=8)
        self.message = ctk.CTkLabel(self, text="", font=fonts.tiny, text_color=TEXT, anchor="w")
        self.message.pack(side="left", fill="x", expand=True, padx=8)

    def set_mode(self, mode: str) -> None:
        mode = mode if mode in _MODE_COLOURS else "PROG"
        self.mode = mode
        if self.mode_label is not None:
            self.mode_label.configure(text=f" {mode} ", fg_color=PALETTE[_MODE_COLOURS[mode]])

    def set_scan(self, scan: int | None) -> None:
        if self.scan_label is not None:
            self.scan_label.configure(text=f"scan #{scan}" if scan is not None else "scan -")

    def set_rung(self, index: int | None, total: int) -> None:
        if self.rung_label is not None:
            self.rung_label.configure(text=f"rung {index}/{total}" if index else f"rung -/{total}")

    def set_errors(self, errors: int, warnings: int = 0) -> None:
        if self.error_label is None:
            return
        text = f"{errors} error{'s' if errors != 1 else ''}"
        if warnings:
            text += f", {warnings} warn"
        self.error_label.configure(
            text=text, width=110 if warnings else 70,
            text_color=PALETTE["DANGER_TEXT"] if errors else MUTED,
        )
