"""New Program / Routine wizard: one clear step-by-step dialog.

Non-modal (no grab, no wait_window). Finish only calls existing viewer actions:
the starter-program questions, Add SBR / JSR, AOI templates and Add rung.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.services.ladder_templates import list_aoi_templates
from cabinet_studio.services.ladder_tools import valid_tag_name
from cabinet_studio.services.programming import PROGRAM_QUESTIONS, default_design_answers
from cabinet_studio.ui.theme import (
    BG, BLUE, BLUE_HOVER, BORDER, ENTRY, HOVER, MUTED, PANEL, TEXT, ghost_button, primary_button, section_label,
)

KINDS = [
    ("program", "Starter program from the cabinet", "Answer the five design questions; the ladder is built "
     "from the devices already on this cabinet (no invented tags)."),
    ("subroutine", "New subroutine (SBR … RET)", "Creates a named routine and, if you like, a JSR call in "
     "MainRoutine."),
    ("aoi", "Insert an AOI template", "Expands a ready-made pattern (seal-in, timers, counters…) into rungs."),
    ("rung", "Single rung (XIC → OTE)", "One contact driving one coil — the simplest start."),
]
STEPS = ("Choose", "Details", "Review")


class ProgramWizard(ctk.CTkToplevel):
    def __init__(self, viewer) -> None:
        super().__init__(viewer, fg_color=BG)
        self.viewer = viewer
        self.fonts = viewer.fonts
        self.title(f"New Program / Routine - {viewer.project.name}")
        self.geometry("640x520")
        self.minsize(560, 460)
        try:
            self.transient(viewer)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _e: self.cancel())
        self.step = 0
        self.result: str | None = None
        self.kind_var = tk.StringVar(master=self, value="program")
        defaults = default_design_answers(viewer.project) or {}
        self.answer_vars = {
            key: tk.StringVar(master=self, value=defaults.get(key) if defaults.get(key) in options else options[0])
            for key, _prompt, options in PROGRAM_QUESTIONS
        }
        self.sub_name = tk.StringVar(master=self, value=self._free_routine_name())
        self.sub_call = tk.BooleanVar(master=self, value=True)
        tags = [t for t in viewer._tag_choices() if not t.startswith("(")] or ["PB_Start"]
        self.tags = tags
        self.contact = tk.StringVar(master=self, value=tags[0])
        self.coil = tk.StringVar(master=self, value=tags[1] if len(tags) > 1 else tags[0])
        self.form = tk.StringVar(master=self, value="NO")
        self.comment = tk.StringVar(master=self, value="")
        self.templates = list_aoi_templates()
        self.aoi = tk.StringVar(master=self, value=self.templates[0]["name"] if self.templates else "MotorStarter")

        head = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        head.pack(fill="x")
        self.step_label = ctk.CTkLabel(head, text="", font=self.fonts.heading, text_color=TEXT, anchor="w")
        self.step_label.pack(side="left", padx=14, pady=10)
        self.ai_btn = ghost_button(head, "Ask AI", lambda: viewer.invoke_command("tools.ask_ai"), self.fonts.small,
                                   width=80)
        self.ai_btn.pack(side="right", padx=10)
        nav = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        nav.pack(side="bottom", fill="x")
        self.cancel_btn = ghost_button(nav, "Cancel", self.cancel, self.fonts.small, width=90)
        self.cancel_btn.pack(side="left", padx=10, pady=8)
        self.finish_btn = primary_button(nav, "Finish", self.finish, self.fonts.small, width=100)
        self.finish_btn.pack(side="right", padx=(4, 10), pady=8)
        self.next_btn = primary_button(nav, "Next ›", self.next, self.fonts.small, width=90)
        self.next_btn.pack(side="right", padx=4, pady=8)
        self.back_btn = ghost_button(nav, "‹ Back", self.back, self.fonts.small, width=90)
        self.back_btn.pack(side="right", padx=4, pady=8)
        self.body = ctk.CTkScrollableFrame(self, fg_color=BG)
        self.body.pack(fill="both", expand=True, padx=8, pady=8)
        self._render()
        try:
            self.lift()
        except Exception:
            pass

    # -- helpers -------------------------------------------------------------

    def _free_routine_name(self) -> str:
        existing = {str(k).lower() for k in (self.viewer.program.get("routines") or {})}
        n = 1
        while f"sub{n}" in existing:
            n += 1
        return f"Sub{n}"

    def _clear(self) -> None:
        for child in list(self.body.winfo_children()):
            child.destroy()

    def _text(self, text: str, *, muted: bool = False, pady=(4, 2)) -> None:
        ctk.CTkLabel(self.body, text=text, font=self.fonts.small, text_color=MUTED if muted else TEXT,
                     anchor="w", justify="left", wraplength=560).pack(fill="x", padx=8, pady=pady)

    def _menu(self, parent, values, var, width=220) -> ctk.CTkOptionMenu:
        return ctk.CTkOptionMenu(
            parent, values=list(values), variable=var, width=width, height=28, font=self.fonts.small,
            dropdown_font=self.fonts.small, fg_color=ENTRY, button_color=BLUE, button_hover_color=BLUE_HOVER,
            dropdown_fg_color=PANEL, dropdown_hover_color=HOVER, dropdown_text_color=TEXT, text_color=TEXT,
            dynamic_resizing=False,
        )

    def _row(self, label: str):
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(row, text=label, width=150, font=self.fonts.small, text_color=MUTED, anchor="w").pack(side="left")
        return row

    # -- steps ---------------------------------------------------------------

    def _render(self) -> None:
        self._clear()
        self.step_label.configure(text=f"Step {self.step + 1} of {len(STEPS)} — {STEPS[self.step]}")
        getattr(self, f"_step_{STEPS[self.step].lower()}")()
        self.back_btn.configure(state="normal" if self.step > 0 else "disabled")
        last = self.step == len(STEPS) - 1
        self.next_btn.configure(state="disabled" if last else "normal")
        self.finish_btn.configure(state="normal" if last else "disabled")

    def _step_choose(self) -> None:
        section_label(self.body, "WHAT DO YOU WANT TO CREATE?", self.fonts.tiny).pack(anchor="w", padx=8, pady=(6, 4))
        self.kind_buttons = {}
        for key, title, blurb in KINDS:
            rb = ctk.CTkRadioButton(self.body, text=title, value=key, variable=self.kind_var, font=self.fonts.body,
                                    text_color=TEXT, fg_color=BLUE, hover_color=BLUE_HOVER, border_color=BORDER)
            rb.pack(anchor="w", padx=10, pady=(8, 0))
            self.kind_buttons[key] = rb
            self._text(blurb, muted=True, pady=(0, 2))

    def _step_details(self) -> None:
        kind = self.kind_var.get()
        if kind == "program":
            self._text("Pick the answer that fits each question (same questions as Ask questions).")
            for key, prompt, options in PROGRAM_QUESTIONS:
                self._text(prompt, pady=(8, 0))
                self._menu(self.body, options, self.answer_vars[key], width=480).pack(anchor="w", padx=10)
        elif kind == "subroutine":
            self.sub_entry = ctk.CTkEntry(self._row("Routine name"), textvariable=self.sub_name, width=220, font=self.fonts.small,
                                          fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            self.sub_entry.pack(side="left")
            ctk.CTkCheckBox(self.body, text="Call it from MainRoutine with a JSR", variable=self.sub_call,
                            font=self.fonts.small, text_color=TEXT).pack(anchor="w", padx=10, pady=8)
            self._menu(self._row("JSR enable contact"), self.tags, self.contact).pack(side="left")
        elif kind == "aoi":
            names = [t["name"] for t in self.templates] or ["MotorStarter"]
            self._menu(self._row("Template"), names, self.aoi).pack(side="left")
            for t in self.templates:
                if t["name"] == self.aoi.get():
                    self._text(t["title"], pady=(8, 0))
                    self._text(t["description"], muted=True)
        else:
            self._menu(self._row("Contact (XIC / XIO)"), self.tags, self.contact).pack(side="left")
            self._menu(self._row("Contact form"), ["NO", "NC"], self.form, width=90).pack(side="left")
            self._menu(self._row("Coil (OTE)"), self.tags, self.coil).pack(side="left")
            ctk.CTkEntry(self._row("Comment"), textvariable=self.comment, width=300, font=self.fonts.small,
                         fg_color=ENTRY, border_color=BORDER, text_color=TEXT).pack(side="left")

    def summary(self) -> str:
        kind = self.kind_var.get()
        if kind == "program":
            lines = [f"• {prompt}  →  {self.answer_vars[key].get()}" for key, prompt, _o in PROGRAM_QUESTIONS]
            return "Build a starter program from the cabinet:\n" + "\n".join(lines) + (
                "\n\nThis replaces the current program (you are asked first if you edited it).")
        if kind == "subroutine":
            call = f"\nAdd JSR {self.sub_name.get()} in MainRoutine, enabled by {self.contact.get()}." \
                if self.sub_call.get() else ""
            return f"Create subroutine {self.sub_name.get()} (SBR … RET).{call}"
        if kind == "aoi":
            return f"Insert AOI template {self.aoi.get()} as rungs at the end of MainRoutine."
        form = "XIO" if self.form.get() == "NC" else "XIC"
        return f"Add rung: {form} {self.contact.get()} → OTE {self.coil.get()}."

    def _step_review(self) -> None:
        section_label(self.body, "REVIEW", self.fonts.tiny).pack(anchor="w", padx=8, pady=(6, 4))
        self._text(self.summary())
        self._text("Educational design aid — not a PLC download. E-stop and safety functions must be hardwired "
                   "or use rated safety relays (NFPA 79 / ISO 13849).", muted=True, pady=(12, 2))

    # -- navigation ----------------------------------------------------------

    def validate(self) -> str:
        if self.step >= 1 and self.kind_var.get() == "subroutine":
            name = self.sub_name.get().strip()
            if not name or name.lower() == "main" or not valid_tag_name(name):
                return "Enter a routine name (letters, digits, _; not Main)."
        return ""

    def next(self) -> None:
        problem = self.validate()
        if problem:
            self.step_label.configure(text=problem)
            return
        if self.step < len(STEPS) - 1:
            self.step += 1
            self._render()

    def back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self._render()

    def cancel(self) -> None:
        self.result = "cancel"
        self.viewer._wizard = None
        try:
            self.destroy()
        except Exception:
            pass

    def finish(self) -> None:
        problem = self.validate()
        if problem:
            self.step_label.configure(text=problem)
            return
        v = self.viewer
        kind = self.kind_var.get()
        if kind == "program":
            if v._confirm_replace_program():
                v._answers = {k: var.get() for k, var in self.answer_vars.items()}
                v._finish_questions()
            else:
                v.status.configure(text="Kept your existing program.")
        elif kind == "subroutine":
            name = self.sub_name.get().strip()
            v._rung_field_vars["sbr_name"].set(name)
            v.invoke_command("rung.add_sbr")
            if self.sub_call.get():
                v._rung_field_vars["jsr_target"].set(name)
                v.contact_var.set(self.contact.get())
                v.nc_var.set("NO")
                v.invoke_command("rung.add_jsr")
        elif kind == "aoi":
            v._rung_field_vars["aoi_name"].set(self.aoi.get())
            v.invoke_command("rung.add_aoi")
        else:
            v.contact_var.set(self.contact.get())
            v.coil_var.set(self.coil.get())
            v.nc_var.set(self.form.get())
            v._rung_field_vars["comment"].set(self.comment.get())
            v.invoke_command("rung.add")
        self.result = kind
        v._wizard = None
        try:
            self.destroy()
        except Exception:
            pass
