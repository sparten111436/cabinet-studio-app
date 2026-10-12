"""New build with AI: one question at a time, then confirm recommended devices."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.models.schema import Library
from cabinet_studio.services.ai_build import (
    AI_BUILD_DISCLAIMER,
    AI_BUILD_QUESTIONS,
    CATALOG_NOT_IDENTIFIED,
    RecommendedDevice,
    blank_ai_answers,
    interview_default,
    interview_suggestion,
    recommend_devices,
)
from cabinet_studio.services.standards import StandardsProfile
from cabinet_studio.ui.ai_interview_hooks import attach_interview_ai, refresh_interview_ai_tip
from cabinet_studio.ui.theme import (
    BG,
    BORDER,
    CYAN,
    ENTRY,
    HOVER,
    MUTED,
    ORANGE,
    PANEL,
    TEXT,
    TRACK,
    ghost_button,
    primary_button,
    section_label,
)
from cabinet_studio.ui.util import center_on_parent

SELECT = "Select…"


class AiBuildDialog(ctk.CTkToplevel):
    """Interview → device list → confirm. Returns answers + selected recommendations."""

    def __init__(self, master, fonts, library: Library, profile: StandardsProfile) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.library = library
        self.profile = profile
        self.result: dict | None = None
        self.done = tk.IntVar(master=self, value=0)
        self.answers = blank_ai_answers()
        self.index = 0
        self._phase = "interview"  # interview | devices
        self._recommendations: list[RecommendedDevice] = []
        self._checks: dict[str, tk.BooleanVar] = {}
        self._multi_vars: dict[str, tk.BooleanVar] = {}
        self._choice_var: tk.StringVar | None = None
        self._text_widget = None
        self.title("New build with AI")
        self.minsize(560, 560)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build_shell()
        self.withdraw()

    def _build_shell(self) -> None:
        accent = ctk.CTkFrame(self, height=4, fg_color=ORANGE, corner_radius=0)
        accent.pack(fill="x")
        accent.pack_propagate(False)
        self.nav = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.nav.pack(side="bottom", fill="x")
        self.cancel_btn = ghost_button(self.nav, "Cancel", self._cancel, self.fonts.body, width=110)
        self.cancel_btn.pack(side="left", padx=16, pady=12)
        self.back_btn = ghost_button(self.nav, "Back", self._back, self.fonts.body, width=100)
        self.back_btn.pack(side="left", padx=6, pady=12)
        self.next_btn = primary_button(self.nav, "Next", self._next, self.fonts.body, width=140)
        self.next_btn.pack(side="right", padx=16, pady=12)
        ctk.CTkLabel(
            self,
            text=AI_BUILD_DISCLAIMER,
            font=self.fonts.tiny,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(side="bottom", fill="x", padx=20, pady=(0, 4))
        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        header.pack(fill="x", padx=20, pady=(14, 4))
        self.heading = ctk.CTkLabel(
            header, text="New build with AI", font=self.fonts.title, text_color=TEXT, anchor="w"
        )
        self.heading.pack(fill="x")
        self.step_label = ctk.CTkLabel(
            header, text="", font=self.fonts.heading, text_color=CYAN, anchor="w"
        )
        self.step_label.pack(fill="x", pady=(6, 0))
        self.prompt = ctk.CTkLabel(
            header,
            text="",
            font=self.fonts.body,
            text_color=TEXT,
            anchor="w",
            justify="left",
            wraplength=520,
        )
        self.prompt.pack(fill="x", pady=(8, 0))
        self.help = ctk.CTkLabel(
            header,
            text="Answer one question at a time. You can change your mind with Back.",
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=520,
        )
        self.help.pack(fill="x", pady=(4, 0))
        self.ai_tip = ctk.CTkLabel(
            header,
            text="",
            font=self.fonts.small,
            text_color=ORANGE,
            anchor="w",
            justify="left",
            wraplength=520,
        )
        self.ai_tip.pack(fill="x", pady=(6, 0))
        ai_row = ctk.CTkFrame(header, fg_color="transparent")
        ai_row.pack(fill="x", pady=(6, 0))
        self.use_ai_btn = ghost_button(ai_row, "Use AI answer", self._use_ai_answer, self.fonts.small, width=130)
        self.use_ai_btn.pack(side="left")
        self.accept_all_btn = ghost_button(ai_row, "Accept all AI answers", self._accept_all_ai, self.fonts.small,
                                           width=180)
        self.accept_all_btn.pack(side="left", padx=8)
        self.progress = ctk.CTkProgressBar(
            self, height=6, corner_radius=2, fg_color=TRACK, progress_color=CYAN
        )
        self.progress.pack(fill="x", padx=20, pady=(10, 6))
        self.progress.set(0)
        host = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        host.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.scroller = ctk.CTkScrollableFrame(host, fg_color=BG, corner_radius=0)
        self.scroller.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._next())
        attach_interview_ai(self)

    def present(self, initial: dict[str, str] | None = None) -> None:
        self.result = None
        self.done.set(0)
        self.answers = blank_ai_answers()
        if initial:
            for key, value in initial.items():
                if key in self.answers:
                    self.answers[key] = str(value or "")
        self.index = 0
        self._phase = "interview"
        self._recommendations = []
        self._checks.clear()
        self._multi_vars.clear()
        center_on_parent(self, 620, 700, self.master)
        self._show_question()
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

    def _clear_body(self) -> None:
        for child in self.scroller.winfo_children():
            child.destroy()
        self._choice_var = None
        self._text_widget = None
        self._multi_vars.clear()

    def _show_question(self) -> None:
        self._phase = "interview"
        self._clear_body()
        total = len(AI_BUILD_QUESTIONS)
        key, label, kind, options = AI_BUILD_QUESTIONS[self.index]
        self.heading.configure(text="New build with AI")
        self.step_label.configure(text=f"Question {self.index + 1} of {total}")
        self.prompt.configure(text=label)
        self.help.configure(text="Use plain words. There is no wrong answer — you can edit later.")
        self.ai_tip.configure(text="AI tip: " + interview_suggestion(self.answers, key))
        refresh_interview_ai_tip(self)
        self.progress.set((self.index + 1) / (total + 1))
        self.back_btn.configure(state="normal" if self.index else "disabled")
        self.next_btn.configure(text="Next")
        self.use_ai_btn.configure(state="normal")
        self.accept_all_btn.configure(state="normal", text="Accept all AI answers")
        current = self.answers.get(key, "")
        if kind == "choice":
            self._choice_var = tk.StringVar(
                master=self, value=current if current in options else SELECT
            )
            menu = ctk.CTkOptionMenu(
                self.scroller,
                values=[SELECT, *options],
                variable=self._choice_var,
                font=self.fonts.body,
                dropdown_font=self.fonts.small,
                fg_color=ENTRY,
                button_color="#2f6bff",
                button_hover_color="#2457d6",
                dropdown_fg_color=PANEL,
                dropdown_hover_color=HOVER,
                dropdown_text_color=TEXT,
                text_color=TEXT,
                width=520,
                height=36,
                dynamic_resizing=False,
            )
            menu.pack(fill="x", padx=8, pady=12)
        elif kind == "multi":
            selected = {part.strip() for part in current.split("|") if part.strip()}
            if not selected and key == "operator_devices":
                # Seed AI suggestions for buttons when start/stop is pushbutton-ish.
                start_stop = (self.answers.get("start_stop") or "").lower()
                if "push" in start_stop or start_stop == "both" or start_stop == "not sure" or not start_stop:
                    selected = {"Start pushbutton", "Stop pushbutton"}
                if (self.answers.get("has_motor") or "").lower().startswith("y"):
                    selected.add("Run indicator light")
            section_label(self.scroller, "SELECT FROM LIBRARY CLASSES", self.fonts.tiny).pack(
                anchor="w", padx=8, pady=(4, 6)
            )
            for option in options:
                variable = tk.BooleanVar(master=self, value=option in selected)
                self._multi_vars[option] = variable
                ctk.CTkCheckBox(
                    self.scroller,
                    text=option,
                    variable=variable,
                    font=self.fonts.body,
                    text_color=TEXT,
                    fg_color="#2f6bff",
                    hover_color="#2457d6",
                    border_color=BORDER,
                ).pack(anchor="w", padx=12, pady=4)
        else:
            height = 100 if key == "duty" else 40
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
            box.pack(fill="x", padx=8, pady=12)
            if current:
                box.insert("1.0", current)
            self._text_widget = box
            try:
                box.focus_set()
            except Exception:
                pass

    def _use_ai_answer(self) -> bool:
        """Fill the current question with the AI's recommended answer (still editable)."""
        if self._phase != "interview":
            return False
        key, _label, kind, options = AI_BUILD_QUESTIONS[self.index]
        value = interview_default(self.answers, key)
        if not value:
            self.ai_tip.configure(text="AI tip: please type this one yourself - the AI builds its other "
                                       "answers from it.")
            return False
        if kind == "choice" and self._choice_var is not None and value in options:
            self._choice_var.set(value)
        elif kind == "multi":
            picks = set(value.split("|"))
            for name, variable in self._multi_vars.items():
                variable.set(name in picks)
        elif self._text_widget is not None:
            self._text_widget.delete("1.0", "end")
            self._text_widget.insert("1.0", value)
        return True

    def _accept_all_ai(self) -> None:
        """Keep the answers given so far, fill every blank one with the AI answer, show the devices.
        On the device screen: tick every AI pick and confirm."""
        if self._phase == "devices":
            for variable in self._checks.values():
                variable.set(True)
            self._next()
            return
        if self._phase != "interview":
            return
        if not self._store_question() and not (self._use_ai_answer() and self._store_question()):
            return
        for key, _label, _kind, _options in AI_BUILD_QUESTIONS[self.index + 1:]:
            if not (self.answers.get(key) or "").strip():
                self.answers[key] = interview_default(self.answers, key)
        self.index = len(AI_BUILD_QUESTIONS) - 1
        self._show_devices()

    def _store_question(self) -> bool:
        key, _label, kind, _options = AI_BUILD_QUESTIONS[self.index]
        if kind == "choice":
            selected = self._choice_var.get() if self._choice_var is not None else SELECT
            if selected == SELECT:
                return False
            self.answers[key] = selected
        elif kind == "multi":
            picked = [name for name, variable in self._multi_vars.items() if variable.get()]
            # Allow empty only if user explicitly unchecked all — still store empty.
            self.answers[key] = "|".join(picked)
        else:
            text = self._text_widget.get("1.0", "end").strip() if self._text_widget is not None else ""
            if key == "project_name" and not text:
                text = "AI cabinet build"
            if key == "duty" and not text:
                return False
            self.answers[key] = text
        return True

    def _show_devices(self) -> None:
        self._phase = "devices"
        self._clear_body()
        self._recommendations = recommend_devices(self.library, self.profile, self.answers)
        self.heading.configure(text="Recommended devices")
        self.step_label.configure(text="Check the list, then confirm")
        self.prompt.configure(
            text="These parts come from your library, from the maker you picked when it has one. "
            "Press Accept all AI picks to take them all, or untick any you do not want and press "
            "Confirm devices. You can change every part afterwards."
        )
        self.help.configure(
            text=f"Uncheck anything you do not want. Missing numbers say “{CATALOG_NOT_IDENTIFIED}”."
        )
        self.ai_tip.configure(
            text="AI tip: Confirming creates a NEW cabinet. Programming will use these tags next."
        )
        self.progress.set(1.0)
        self.back_btn.configure(state="normal")
        self.next_btn.configure(text="Confirm devices")
        self.use_ai_btn.configure(state="disabled")
        self.accept_all_btn.configure(state="normal" if self._recommendations else "disabled",
                                      text="Accept all AI picks")
        self._checks.clear()
        if not self._recommendations:
            ctk.CTkLabel(
                self.scroller,
                text="No devices to recommend yet. Go back and answer the questions.",
                font=self.fonts.small,
                text_color=MUTED,
                anchor="w",
            ).pack(fill="x", padx=8, pady=12)
            return
        section_label(self.scroller, "LIBRARY PARTS", self.fonts.tiny).pack(
            anchor="w", padx=8, pady=(4, 6)
        )
        for rec in self._recommendations:
            row = ctk.CTkFrame(
                self.scroller, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER
            )
            row.pack(fill="x", padx=8, pady=4)
            variable = tk.BooleanVar(master=self, value=True)
            self._checks[rec.key] = variable
            catalog_color = CYAN if rec.catalog_number != CATALOG_NOT_IDENTIFIED else ORANGE
            ctk.CTkCheckBox(
                row,
                text=f"{rec.label}   ·   {rec.name}",
                variable=variable,
                font=self.fonts.small,
                text_color=TEXT,
                fg_color="#2f6bff",
                hover_color="#2457d6",
                border_color=BORDER,
            ).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(
                row,
                text=f"Catalog: {rec.catalog_number}"
                + (f"   ·   {rec.vendor}" if rec.vendor else ""),
                font=self.fonts.tiny,
                text_color=catalog_color,
                anchor="w",
            ).pack(fill="x", padx=32, pady=(0, 2))
            ctk.CTkLabel(
                row,
                text=rec.reason,
                font=self.fonts.tiny,
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=480,
            ).pack(fill="x", padx=32, pady=(0, 8))

    def _back(self) -> None:
        if self._phase == "devices":
            self.index = len(AI_BUILD_QUESTIONS) - 1
            self._show_question()
            return
        if self.index:
            self.index -= 1
            self._show_question()

    def _next(self) -> None:
        if self._phase == "devices":
            selected = {
                key for key, variable in self._checks.items() if variable.get()
            }
            chosen = [rec for rec in self._recommendations if rec.key in selected]
            if not chosen:
                return
            self.result = {
                "answers": dict(self.answers),
                "recommendations": chosen,
            }
            self._finish()
            return
        if not self._store_question():
            return
        if self.index < len(AI_BUILD_QUESTIONS) - 1:
            self.index += 1
            self._show_question()
            return
        self._show_devices()

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
