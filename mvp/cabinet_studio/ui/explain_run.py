"""Explain run window (v0.3.25): live, linear narration of the simulator, rung by rung.

Read-only but selectable: drag to select, Ctrl+C / Ctrl+A, right-click menu, Copy all.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.services.ai_assist import SAFETY_NOTE
from cabinet_studio.ui.theme import (
    BG, BORDER, CYAN, MUTED, ORANGE, PANEL, TEXT, bind_theme_redraw, c, ghost_button, section_label,
)

MAX_LINES = 3000
_GREEN = "#2fbf71"


class ExplainRunWindow(ctk.CTkToplevel):
    def __init__(self, master, fonts) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.title("Explain run - step by step")
        self.geometry("760x620")
        self.minsize(520, 360)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        section_label(head, "EXPLAIN RUN - WHAT EACH PART IS WAITING FOR", fonts.tiny).pack(side="left")
        ghost_button(head, "Clear", self.clear, fonts.tiny, width=60).pack(side="right", padx=3)
        ghost_button(head, "Copy all", self.copy_all, fonts.tiny, width=70).pack(side="right", padx=3)

        self.text = ctk.CTkTextbox(self, font=fonts.small, fg_color=PANEL, text_color=TEXT,
                                   border_color=BORDER, border_width=1, wrap="word")
        self.text.pack(fill="both", expand=True, padx=12, pady=4)
        self._colours()
        bind_theme_redraw(self, self._colours)
        self.text.configure(state="disabled")
        inner = self.text._textbox
        inner.bind("<Button-1>", lambda _e: inner.focus_set(), add="+")
        for seq in ("<Control-c>", "<Control-C>"):
            inner.bind(seq, lambda _e: (self.copy_selection(), "break")[1])
        inner.bind("<Control-a>", lambda _e: (self.select_all(), "break")[1])
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Copy", command=self.copy_selection)
        self.menu.add_command(label="Copy all", command=self.copy_all)
        self.menu.add_command(label="Select all", command=self.select_all)
        inner.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))

        self.status = ctk.CTkLabel(self, text="", font=fonts.tiny, text_color=MUTED, anchor="w")
        self.status.pack(fill="x", padx=14)
        ctk.CTkLabel(self, text="Educational only - not a live PLC. " + SAFETY_NOTE, font=fonts.tiny,
                     text_color=MUTED, anchor="w", justify="left", wraplength=700).pack(fill="x", padx=14, pady=(0, 8))
        self.add(["Press Run, Step rung (F6) or Normal run. Each rung is explained here as it runs, part by part, "
                  "left to right: what it needs, what it saw, and where power stops. Tick 'Each part' to see "
                  "the lines arrive in step with the lights."], "note")

    def _colours(self) -> None:
        self.text.tag_config("rung", foreground=c(CYAN))
        self.text.tag_config("wait", foreground=c(ORANGE))
        self.text.tag_config("ok", foreground=_GREEN)
        self.text.tag_config("note", foreground=c(MUTED))
        self.text.tag_config("event", foreground=c(TEXT))

    @staticmethod
    def _style(line: str) -> str:
        s = line.strip()
        if s.startswith("Rung ") or s.startswith("PAUSED") or s.startswith("SIM "):
            return "rung"
        if "WAITING" in s or "NOT energized" in s or "stops at" in s:
            return "wait"
        if "ENERGIZED" in s or "passes power on" in s or "turns ON" in s:
            return "ok"
        return "event"

    def add(self, lines: list[str], style: str | None = None) -> None:
        self.text.configure(state="normal")
        for line in lines:
            self.text.insert("end", line + "\n", style or self._style(line))
        extra = int(self.text.index("end-1c").split(".")[0]) - MAX_LINES
        if extra > 0:
            self.text.delete("1.0", f"{extra + 1}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def text_value(self) -> str:
        return self.text.get("1.0", "end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _to_clipboard(self, value: str) -> None:
        if value:
            self.clipboard_clear()
            self.clipboard_append(value)
            self.status.configure(text="Copied to clipboard.")

    def copy_selection(self) -> None:
        try:
            value = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            value = ""
        self._to_clipboard(value or self.text_value().strip())

    def copy_all(self) -> None:
        self._to_clipboard(self.text_value().strip())

    def select_all(self) -> None:
        self.text._textbox.tag_add("sel", "1.0", "end-1c")
