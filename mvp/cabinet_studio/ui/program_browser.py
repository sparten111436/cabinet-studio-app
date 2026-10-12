"""Read-only viewer for the cut-and-paste program stubs."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk

from cabinet_studio.ui.theme import BG, BORDER, CYAN, ENTRY, MUTED, ORANGE, PANEL, TEXT, ghost_button, primary_button, section_label
from cabinet_studio.ui.util import center_on_parent

PROGRAMS_DIR = Path(__file__).resolve().parent.parent / "programs"
STUB_SUFFIXES = {".st", ".scl", ".py", ".md"}


def list_program_stubs() -> list[Path]:
    if not PROGRAMS_DIR.is_dir():
        return []
    return sorted(path for path in PROGRAMS_DIR.rglob("*") if path.is_file() and path.suffix.lower() in STUB_SUFFIXES)


class ProgramBrowser(ctk.CTkToplevel):
    def __init__(self, master, fonts, on_status) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.on_status = on_status
        self.files = list_program_stubs()
        self.current: Path | None = None
        self.title("Program stubs")
        self.minsize(760, 480)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        center_on_parent(self, 920, 620, master)
        section_label(self, "PROGRAM STUBS", fonts.tiny).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(
            self,
            text="Cut and paste only. Nothing here is downloaded to a PLC.",
            font=fonts.small,
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 8))
        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        left = ctk.CTkFrame(body, width=260, fg_color=PANEL, corner_radius=4)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        self.preview = ctk.CTkTextbox(
            body,
            font=fonts.mono_small,
            fg_color=ENTRY,
            text_color=TEXT,
            border_color=BORDER,
            border_width=1,
            corner_radius=4,
            wrap="none",
        )
        self.preview.pack(side="left", fill="both", expand=True)
        self.preview.configure(state="disabled")
        for path in self.files:
            label = path.relative_to(PROGRAMS_DIR).as_posix()
            ghost_button(left, label, lambda chosen=path: self._show(chosen), fonts.tiny, width=240).pack(
                fill="x", padx=8, pady=4
            )
        row = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        row.pack(fill="x", padx=12, pady=(0, 12))
        self.path_label = ctk.CTkLabel(row, text="", font=fonts.tiny, text_color=CYAN, anchor="w")
        self.path_label.pack(side="left", fill="x", expand=True, padx=4)
        primary_button(row, "Copy", self._copy, fonts.body, width=100).pack(side="right", padx=4)
        ghost_button(row, "Close", self.close, fonts.body, width=90).pack(side="right", padx=4)
        if self.files:
            self._show(self.files[0])
        self.bind("<Escape>", lambda _event: self.close())

    def _show(self, path: Path) -> None:
        self.current = path
        text = path.read_text(encoding="utf-8")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")
        self.path_label.configure(text=path.relative_to(PROGRAMS_DIR.parent).as_posix())

    def _copy(self) -> None:
        if self.current is None:
            return
        text = self.current.read_text(encoding="utf-8")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.on_status(f"Copied {self.current.name} to the clipboard")

    def close(self) -> None:
        self.destroy()

    def open(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
