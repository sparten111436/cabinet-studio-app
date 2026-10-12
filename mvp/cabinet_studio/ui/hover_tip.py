"""Hover popups: rest the mouse on a widget and a short plain-English explanation appears."""

from __future__ import annotations

import tkinter as tk

DELAY_MS = 450


class HoverTip:
    def __init__(self, widget, text: str, title: str = "", wrap: int = 380) -> None:
        self.widget = widget
        self.text = text
        self.title = title
        self.wrap = wrap
        self.tip: tk.Toplevel | None = None
        self._after: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        try:
            self._after = self.widget.after(DELAY_MS, self.show)
        except tk.TclError:
            pass

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def show(self) -> None:
        self._after = None
        if self.tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 8
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        frame = tk.Frame(tip, bg="#fffbe6", highlightthickness=1, highlightbackground="#b59a3a")
        frame.pack()
        if self.title:
            tk.Label(frame, text=self.title, bg="#fffbe6", fg="#1b1b1b", font=("Segoe UI", 10, "bold"),
                     justify="left", anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(frame, text=self.text, bg="#fffbe6", fg="#1b1b1b", font=("Segoe UI", 9), justify="left",
                 anchor="w", wraplength=self.wrap).pack(fill="x", padx=8, pady=(2, 6))
        tip.update_idletasks()
        sw = tip.winfo_screenwidth()
        x = min(x, sw - tip.winfo_reqwidth() - 8)
        tip.geometry(f"+{max(x, 0)}+{y}")
        self.tip = tip

    def hide(self, _event=None) -> None:
        self._cancel()
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


def attach(widget, text: str, title: str = "") -> HoverTip:
    tip = HoverTip(widget, text, title)
    widget._cs_hover_tip = tip
    return tip
