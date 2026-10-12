"""Interview, guide plan, and UL 508A review windows. Each is a Toplevel of the main app."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.models.schema import Library
from cabinet_studio.services.interview import INTERVIEW_FIELDS
from cabinet_studio.services.suggestions import DeviceSuggestion, LayoutSuggestion
from cabinet_studio.services.ul508a import DESIGN_AID_DISCLAIMER, REVIEW_TITLE, Finding
from cabinet_studio.ui.theme import (
    BG,
    BLUE,
    BLUE_HOVER,
    BORDER,
    CYAN,
    ENTRY,
    HOVER,
    MUTED,
    ORANGE,
    PANEL,
    TEXT,
    ghost_button,
    primary_button,
    section_label,
)
from cabinet_studio.ui.util import center_on_parent

SELECT = "Select…"


class InterviewDialog(ctk.CTkToplevel):
    def __init__(self, master, fonts) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.result: dict[str, str] | None = None
        self.done = tk.IntVar(master=self, value=0)
        self.title("Application interview")
        self.minsize(560, 640)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._vars: dict[str, tk.StringVar] = {}
        self._boxes: dict[str, ctk.CTkTextbox] = {}
        self._build()
        self.withdraw()

    def _build(self) -> None:
        accent = ctk.CTkFrame(self, height=4, fg_color=ORANGE, corner_radius=0)
        accent.pack(fill="x")
        accent.pack_propagate(False)
        nav = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        nav.pack(side="bottom", fill="x")
        ghost_button(nav, "Cancel", self._cancel, self.fonts.body, width=110).pack(side="left", padx=16, pady=12)
        primary_button(nav, "Save interview", self._save, self.fonts.body, width=160).pack(
            side="right", padx=16, pady=12
        )
        ctk.CTkLabel(
            self,
            text=DESIGN_AID_DISCLAIMER,
            font=self.fonts.tiny,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(side="bottom", fill="x", padx=20, pady=(0, 4))
        section_label(self, "WHAT THIS SYSTEM MUST DO", self.fonts.tiny).pack(anchor="w", padx=20, pady=(14, 4))
        ctk.CTkLabel(
            self,
            text="Answers steer suggestions. They do not lock a part, a color, or a wire number.",
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(fill="x", padx=20, pady=(0, 8))
        host = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        host.pack(fill="both", expand=True, padx=12)
        self.scroller = ctk.CTkScrollableFrame(host, fg_color=BG, corner_radius=0)
        self.scroller.pack(fill="both", expand=True)
        for key, label, kind, options in INTERVIEW_FIELDS:
            ctk.CTkLabel(self.scroller, text=label, font=self.fonts.heading, text_color=TEXT, anchor="w").pack(
                fill="x", padx=8, pady=(8, 2)
            )
            if kind == "choice":
                variable = tk.StringVar(master=self, value=SELECT)
                ctk.CTkOptionMenu(
                    self.scroller,
                    values=[SELECT, *options],
                    variable=variable,
                    font=self.fonts.body,
                    dropdown_font=self.fonts.small,
                    fg_color=ENTRY,
                    button_color=BLUE,
                    button_hover_color=BLUE_HOVER,
                    dropdown_fg_color=PANEL,
                    dropdown_hover_color=HOVER,
                    dropdown_text_color=TEXT,
                    text_color=TEXT,
                    width=500,
                    height=32,
                    dynamic_resizing=False,
                ).pack(fill="x", padx=8, pady=(0, 2))
                self._vars[key] = variable
            else:
                height = 72 if key == "duty" else 36
                box = ctk.CTkTextbox(
                    self.scroller,
                    height=height,
                    font=self.fonts.body,
                    fg_color=ENTRY,
                    border_color=BORDER,
                    border_width=1,
                    text_color=TEXT,
                    corner_radius=4,
                )
                box.pack(fill="x", padx=8, pady=(0, 2))
                self._boxes[key] = box
        self.bind("<Escape>", lambda _event: self._cancel())

    def present(self, initial: dict[str, str]) -> None:
        self.result = None
        self.done.set(0)
        for key, _label, kind, options in INTERVIEW_FIELDS:
            value = (initial.get(key) or "").strip()
            if kind == "choice":
                self._vars[key].set(value if value in options else SELECT)
            else:
                box = self._boxes[key]
                box.delete("1.0", "end")
                if value:
                    box.insert("1.0", value)
        center_on_parent(self, 580, 760, self.master)
        self.deiconify()
        self.lift()
        self.after(30, self._arm)

    def _arm(self) -> None:
        try:
            if self.winfo_viewable():
                self.grab_set()
                self.focus_force()
        except Exception:
            return

    def _answers(self) -> dict[str, str]:
        answers: dict[str, str] = {}
        for key, _label, kind, _options in INTERVIEW_FIELDS:
            if kind == "choice":
                selected = self._vars[key].get()
                answers[key] = "" if selected == SELECT else selected
            else:
                answers[key] = self._boxes[key].get("1.0", "end").strip()
        return answers

    def _save(self) -> None:
        self.result = self._answers()
        self._finish()

    def _cancel(self) -> None:
        self.result = None
        self._finish()

    def _finish(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.withdraw()
        self.done.set(1)


class GuidePlanDialog(ctk.CTkToplevel):
    def __init__(self, master, fonts, library: Library) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.library = library
        self.result: dict | None = None
        self.done = tk.IntVar(master=self, value=0)
        self._checks: dict[str, tk.BooleanVar] = {}
        self._parts: list[DeviceSuggestion] = []
        self.title("Guide build")
        self.minsize(620, 640)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        self.withdraw()

    def _build(self) -> None:
        accent = ctk.CTkFrame(self, height=4, fg_color=CYAN, corner_radius=0)
        accent.pack(fill="x")
        accent.pack_propagate(False)
        nav = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        nav.pack(side="bottom", fill="x")
        ghost_button(nav, "Pause", self._cancel, self.fonts.body, width=110).pack(side="left", padx=16, pady=12)
        primary_button(nav, "Define these devices", self._accept, self.fonts.body, width=190).pack(
            side="right", padx=16, pady=12
        )
        ctk.CTkLabel(
            self,
            text=DESIGN_AID_DISCLAIMER,
            font=self.fonts.tiny,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=580,
        ).pack(side="bottom", fill="x", padx=20, pady=(0, 4))
        section_label(self, "SUGGESTED LAYOUT AND PARTS", self.fonts.tiny).pack(anchor="w", padx=20, pady=(14, 4))
        self.lead = ctk.CTkLabel(
            self,
            text="",
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=580,
        )
        self.lead.pack(fill="x", padx=20, pady=(0, 8))
        self.layout_var = tk.StringVar(master=self, value="")
        names = [layout.name for layout in self.library.layouts] or ["Blank"]
        self.layout_menu = ctk.CTkOptionMenu(
            self,
            values=names,
            variable=self.layout_var,
            font=self.fonts.body,
            dropdown_font=self.fonts.small,
            fg_color=ENTRY,
            button_color=BLUE,
            button_hover_color=BLUE_HOVER,
            dropdown_fg_color=PANEL,
            dropdown_hover_color=HOVER,
            dropdown_text_color=TEXT,
            text_color=TEXT,
            width=540,
            height=32,
            dynamic_resizing=False,
        )
        self.layout_menu.pack(fill="x", padx=20, pady=(0, 6))
        self.use_layout = tk.BooleanVar(master=self, value=True)
        self.use_layout_box = ctk.CTkCheckBox(
            self,
            text="Use this layout",
            variable=self.use_layout,
            font=self.fonts.small,
            text_color=TEXT,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            border_color=BORDER,
        )
        self.use_layout_box.pack(anchor="w", padx=20, pady=(0, 8))
        host = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        host.pack(fill="both", expand=True, padx=12)
        self.scroller = ctk.CTkScrollableFrame(host, fg_color=BG, corner_radius=0)
        self.scroller.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda _event: self._cancel())

    def present(
        self,
        suggestion: LayoutSuggestion,
        parts: list[DeviceSuggestion],
        *,
        has_items: bool,
    ) -> None:
        self.result = None
        self.done.set(0)
        self._parts = list(parts)
        names = [layout.name for layout in self.library.layouts]
        layout = self.library.layout_by_id.get(suggestion.layout_id)
        chosen = layout.name if layout is not None else (names[0] if names else "")
        if names:
            self.layout_menu.configure(values=names)
            self.layout_var.set(chosen)
        self.use_layout.set(not has_items)
        replace = "Replace the devices already on the panel." if has_items else "Start from this layout."
        self.use_layout_box.configure(text=replace)
        self.lead.configure(text=f"Suggestion: {chosen}. {suggestion.reason} Uncheck any part you do not want.")
        for child in self.scroller.winfo_children():
            child.destroy()
        self._checks.clear()
        for part in parts:
            equipment = self.library.types[part.type_id]
            catalog = self.library.catalog_by_id.get(part.catalog_id) if part.catalog_id else None
            row = ctk.CTkFrame(self.scroller, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
            row.pack(fill="x", padx=8, pady=4)
            variable = tk.BooleanVar(master=self, value=True)
            self._checks[part.type_id] = variable
            title = catalog.name if catalog is not None else equipment.label
            stock = "Shop stock" if part.stock else "Starter library"
            ctk.CTkCheckBox(
                row,
                text=f"{title}   ·   {equipment.label}",
                variable=variable,
                font=self.fonts.small,
                text_color=TEXT,
                fg_color=BLUE,
                hover_color=BLUE_HOVER,
                border_color=BORDER,
            ).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(
                row,
                text=f"{stock}. {part.reason} Color suggestion: {part.fields.get('wire_color', '')}.",
                font=self.fonts.tiny,
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=520,
            ).pack(fill="x", padx=32, pady=(0, 8))
        center_on_parent(self, 640, 720, self.master)
        self.deiconify()
        self.lift()
        self.after(30, self._arm)

    def _arm(self) -> None:
        try:
            if self.winfo_viewable():
                self.grab_set()
                self.focus_force()
        except Exception:
            return

    def _accept(self) -> None:
        name = self.layout_var.get()
        layout_id = next((layout.id for layout in self.library.layouts if layout.name == name), "")
        self.result = {
            "apply_layout": bool(self.use_layout.get()) and bool(layout_id),
            "layout_id": layout_id,
            "type_ids": [type_id for type_id, variable in self._checks.items() if variable.get()],
        }
        self._finish()

    def _cancel(self) -> None:
        self.result = None
        self._finish()

    def _finish(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.withdraw()
        self.done.set(1)


class ReviewWindow(ctk.CTkToplevel):
    def __init__(self, master, fonts) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.title(REVIEW_TITLE)
        self.minsize(640, 560)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        accent = ctk.CTkFrame(self, height=4, fg_color=ORANGE, corner_radius=0)
        accent.pack(fill="x")
        accent.pack_propagate(False)
        nav = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        nav.pack(side="bottom", fill="x")
        primary_button(nav, "Close", self.close, self.fonts.body, width=120).pack(side="right", padx=16, pady=12)
        ctk.CTkLabel(self, text=REVIEW_TITLE, font=self.fonts.title, text_color=TEXT, anchor="w").pack(
            fill="x", padx=20, pady=(14, 2)
        )
        ctk.CTkLabel(
            self,
            text=DESIGN_AID_DISCLAIMER,
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=600,
        ).pack(fill="x", padx=20, pady=(0, 8))
        host = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        host.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.scroller = ctk.CTkScrollableFrame(host, fg_color=BG, corner_radius=0)
        self.scroller.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda _event: self.close())
        self.withdraw()

    def present(self, findings: list[Finding]) -> None:
        for child in self.scroller.winfo_children():
            child.destroy()
        for finding in findings:
            color = CYAN if finding.status == "pass" else ORANGE
            card = ctk.CTkFrame(self.scroller, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
            card.pack(fill="x", padx=8, pady=4)
            label = finding.status.upper()
            if finding.advisory:
                label += "  ·  ADVISORY"
            ctk.CTkLabel(
                card,
                text=f"{finding.check_id}   ·   {label}",
                font=self.fonts.tiny,
                text_color=color,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(card, text=finding.title, font=self.fonts.heading, text_color=TEXT, anchor="w").pack(
                fill="x", padx=12, pady=(2, 0)
            )
            ctk.CTkLabel(
                card,
                text=finding.detail,
                font=self.fonts.small,
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=560,
            ).pack(fill="x", padx=12, pady=(2, 8))
        center_on_parent(self, 680, 720, self.master)
        self.deiconify()
        self.lift()
        self.after(30, self._arm)

    def _arm(self) -> None:
        try:
            if self.winfo_viewable():
                self.lift()
                self.focus_force()
        except Exception:
            return

    def close(self) -> None:
        self.withdraw()
