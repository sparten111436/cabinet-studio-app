"""Guided definition for every device the PLC will supervise."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.models.project import Project
from cabinet_studio.models.schema import FieldGroup, FieldSpec, Library
from cabinet_studio.services.completeness import missing_specs
from cabinet_studio.services.standards import StandardsProfile, default_profile
from cabinet_studio.services.wizard_plan import fields_by_group
from cabinet_studio.services.ul508a import DESIGN_AID_DISCLAIMER
from cabinet_studio.services.wiring_assist import (
    FieldAssist,
    remember_field_choice,
    suggest_field,
    why_for_pick,
)
from cabinet_studio.ui.theme import (
    BG,
    BLUE,
    BLUE_HOVER,
    BORDER,
    CYAN,
    ENTRY,
    HOVER,
    MUTED,
    OK_BG,
    ORANGE,
    PANEL,
    TEXT,
    TRACK,
    WARN_BG,
    ghost_button,
    primary_button,
)
from cabinet_studio.ui.util import center_on_parent

SELECT = "Select…"


class DefinitionWizard(ctk.CTkToplevel):
    def __init__(self, master, fonts) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.title("Define device")
        self.minsize(620, 640)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.on_submit = None
        self.mode = "add"
        self.fields: list[FieldSpec] = []
        self.groups: list[FieldGroup] = []
        self.values: dict[str, str] = {}
        self.steps: list[tuple] = []
        self.index = 0
        self._widgets: dict[str, object] = {}
        self._vars: dict[str, tk.StringVar] = {}
        self._by_key: dict[str, FieldSpec] = {}
        self.suggestions: dict[str, str] = {}
        self.field_assists: dict[str, FieldAssist] = {}
        self.project: Project | None = None
        self.library: Library | None = None
        self.profile: StandardsProfile | None = None
        self.type_id: str = ""
        self._why_labels: dict[str, object] = {}
        self.on_close = None
        self._submitted = False
        self._build_shell()
        self.withdraw()

    def _build_shell(self) -> None:
        self.accent = ctk.CTkFrame(self, height=4, fg_color=ORANGE, corner_radius=0)
        self.accent.pack(fill="x")
        self.accent.pack_propagate(False)
        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        header.pack(fill="x", padx=20, pady=(14, 4))
        self.heading = ctk.CTkLabel(header, text="Define device", font=self.fonts.title, text_color=TEXT, anchor="w")
        self.heading.pack(fill="x")
        self.subheading = ctk.CTkLabel(
            header,
            text="",
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=680,
        )
        self.subheading.pack(fill="x", pady=(2, 0))
        self.step_label = ctk.CTkLabel(self, text="", font=self.fonts.heading, text_color=CYAN, anchor="w")
        self.step_label.pack(fill="x", padx=20, pady=(10, 2))
        self.prompt = ctk.CTkLabel(
            self,
            text="",
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=660,
        )
        self.prompt.pack(fill="x", padx=20, pady=(0, 6))
        self.progress = ctk.CTkProgressBar(
            self,
            height=6,
            corner_radius=2,
            fg_color=TRACK,
            progress_color=CYAN,
        )
        self.progress.pack(fill="x", padx=20, pady=(0, 8))
        self.progress.set(0)
        # Pack the button row before the expanding question pane.
        self.nav = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.nav.pack(side="bottom", fill="x")
        self.hint = ctk.CTkLabel(
            self,
            text="",
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=660,
        )
        self.hint.pack(side="bottom", fill="x", padx=20, pady=(0, 2))
        self.suggest_row = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.suggest_row.pack(side="bottom", fill="x", padx=16, pady=(0, 4))
        self.special_var = tk.BooleanVar(master=self, value=False)
        self.special_switch = ctk.CTkSwitch(
            self.suggest_row,
            text="Mark as special (nonstandard)",
            variable=self.special_var,
            font=self.fonts.small,
            text_color=TEXT,
            progress_color=ORANGE,
            button_color=TEXT,
            button_hover_color=CYAN,
            fg_color=TRACK,
        )
        self.special_switch.pack(side="left", padx=(4, 8))
        self.accept_btn = ghost_button(
            self.suggest_row,
            "Accept suggestion",
            self._accept_suggestions,
            self.fonts.small,
            width=160,
        )
        self.accept_btn.pack(side="right")
        self.host = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.host.pack(side="top", fill="both", expand=True, padx=12, pady=(0, 4))
        # One scrollable frame for the life of the wizard. Destroying these
        # widgets leaks CustomTkinter's global mouse-wheel binding.
        self.scroller = ctk.CTkScrollableFrame(
            self.host,
            fg_color=BG,
            scrollbar_button_color=TRACK,
            scrollbar_button_hover_color=ORANGE,
            corner_radius=0,
        )
        self.scroller.pack(fill="both", expand=True)
        self.back_btn = ghost_button(self.nav, "Back", self._back, self.fonts.body, width=100)
        self.next_btn = ghost_button(self.nav, "Next", self._next, self.fonts.body, width=100)
        self.finish_btn = primary_button(self.nav, "Place on layout", self._finish, self.fonts.body, width=180)
        self.back_btn.pack(side="left", padx=16, pady=12)
        self.finish_btn.pack(side="right", padx=(6, 16), pady=12)
        self.next_btn.pack(side="right", padx=6, pady=12)
        self.bind("<Escape>", lambda _event: self.close())

    def present(
        self,
        *,
        heading: str,
        subheading: str,
        accent: str,
        groups: list[FieldGroup],
        fields: list[FieldSpec],
        initial: dict[str, str],
        mode: str,
        on_submit,
        suggestions: dict[str, str] | None = None,
        on_close=None,
        project: Project | None = None,
        library: Library | None = None,
        profile: StandardsProfile | None = None,
        type_id: str = "",
        field_assists: dict[str, FieldAssist] | None = None,
    ) -> None:
        self.on_submit = on_submit
        self.on_close = on_close
        self._submitted = False
        self.mode = mode
        self.fields = list(fields)
        self.groups = list(groups)
        self._by_key = {field.key: field for field in fields}
        self.project = project
        self.library = library
        self.profile = profile or default_profile()
        self.type_id = type_id or ""
        self.field_assists = dict(field_assists or {})
        self.suggestions = {
            key: str(value)
            for key, value in (suggestions or {}).items()
            if str(value).strip() and key != "nonstandard"
        }
        # Seed suggestion map from assists when not already provided.
        for key, assist in self.field_assists.items():
            if assist.value and key not in self.suggestions:
                self.suggestions[key] = assist.value
        self.values = {field.key: str(initial.get(field.key, "") or "") for field in fields}
        self.special_var.set(str(initial.get("nonstandard", "")).strip().lower() in {"yes", "y", "true", "special"})
        if self.suggestions:
            self.accept_btn.configure(state="normal")
        else:
            self.accept_btn.configure(state="disabled")
        self.steps = self._make_steps()
        self.index = 0
        self.heading.configure(text=heading)
        self.subheading.configure(text=subheading)
        self.accent.configure(fg_color=accent or ORANGE)
        self.title(heading)
        center_on_parent(self, 740, 780, self.master)
        self._show_step(0)
        self.deiconify()
        self.lift()
        self.after(40, self._arm)

    def _make_steps(self) -> list[tuple]:
        steps = [(group, grouped) for group, grouped in fields_by_group(self.groups, self.fields)]
        steps.append((None, []))
        return steps

    def _arm(self) -> None:
        try:
            if not self.winfo_viewable():
                return
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            return

    def close(self) -> None:
        self._widgets.clear()
        self._vars.clear()
        submitted = self._submitted
        hook = self.on_close
        self.on_close = None
        try:
            self.grab_release()
        except Exception:
            pass
        self.withdraw()
        if hook is not None:
            hook(submitted)

    def _show_step(self, index: int) -> None:
        if self._widgets:
            self._store_current()
        self.index = index
        self._widgets.clear()
        self._vars.clear()
        for child in self.scroller.winfo_children():
            child.destroy()
        group, fields = self.steps[index]
        total = len(self.steps)
        self.progress.set((index + 1) / total)
        if group is None:
            self.step_label.configure(text=f"Step {index + 1} of {total}   ·   Review")
            self.prompt.configure(
                text="Check what is still open. You can place the device now and come back to it."
            )
            self._build_review()
        else:
            self.step_label.configure(text=f"Step {index + 1} of {total}   ·   {group.title}")
            self.prompt.configure(text=group.prompt)
            self._build_fields(fields)
        self._update_nav()

    def _build_fields(self, fields: list[FieldSpec]) -> None:
        scroller = self.scroller
        self._why_labels = {}
        for spec in fields:
            label = ctk.CTkLabel(
                scroller,
                text=f"{spec.label} *" if spec.required else spec.label,
                font=self.fonts.heading,
                text_color=TEXT,
                anchor="w",
            )
            label.pack(fill="x", padx=8, pady=(10, 0))
            ctk.CTkLabel(
                scroller,
                text=spec.help,
                font=self.fonts.small,
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=660,
            ).pack(fill="x", padx=8, pady=(2, 4))
            assist = self._assist_for(spec.key)
            suggested = self.suggestions.get(spec.key, "") or (assist.value if assist else "")
            if suggested:
                current = self.values.get(spec.key, "")
                if current == suggested:
                    note, color = "Suggestion ready — edit anytime. Apply suggestion restores this value.", CYAN
                else:
                    note, color = f"Suggestion: {suggested}", MUTED
                ctk.CTkLabel(
                    scroller,
                    text=note,
                    font=self.fonts.tiny,
                    text_color=color,
                    anchor="w",
                    justify="left",
                    wraplength=640,
                ).pack(fill="x", padx=8, pady=(0, 2))
            value = self.values.get(spec.key, "")
            picks = self._picks_for(spec, assist)
            if spec.type == "choice" or picks:
                options = list(spec.options) if spec.type == "choice" else []
                for pick in picks:
                    if pick and pick not in options:
                        options.append(pick)
                display = value if value in options else (value if value else SELECT)
                if display not in options and display != SELECT:
                    options = [display, *options]
                variable = tk.StringVar(master=self, value=display if display in options or display == SELECT else SELECT)
                if display == SELECT or (value and value not in options):
                    if value:
                        variable.set(value)
                    elif suggested and suggested in options:
                        variable.set(suggested)
                    else:
                        variable.set(SELECT if SELECT in [SELECT, *options] else (options[0] if options else SELECT))
                menu_values = [SELECT, *options] if SELECT not in options else [SELECT, *[o for o in options if o != SELECT]]
                # Ensure unique preserve order
                seen = set()
                ordered = []
                for item in menu_values:
                    if item not in seen:
                        seen.add(item)
                        ordered.append(item)
                menu = ctk.CTkOptionMenu(
                    scroller,
                    values=ordered,
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
                    width=660,
                    height=34,
                    dynamic_resizing=False,
                    command=lambda chosen, key=spec.key: self._on_pick(key, chosen),
                )
                menu.pack(fill="x", padx=8, pady=(0, 4))
                self._vars[spec.key] = variable
                self._widgets[spec.key] = menu
            elif spec.type == "multiline":
                box = ctk.CTkTextbox(
                    scroller,
                    height=78,
                    font=self.fonts.body,
                    fg_color=ENTRY,
                    border_color=BORDER,
                    border_width=1,
                    text_color=TEXT,
                    corner_radius=4,
                )
                box.pack(fill="x", padx=8, pady=(0, 4))
                if value:
                    box.insert("1.0", value)
                self._widgets[spec.key] = box
            else:
                widget = ctk.CTkEntry(
                    scroller,
                    font=self.fonts.body,
                    height=34,
                    corner_radius=4,
                    fg_color=ENTRY,
                    border_color=BORDER,
                    text_color=TEXT,
                    placeholder_text=spec.placeholder,
                    placeholder_text_color=MUTED,
                )
                widget.pack(fill="x", padx=8, pady=(0, 4))
                if value:
                    widget.insert(0, value)
                self._widgets[spec.key] = widget

            # Suggest / Apply / Why row
            row = ctk.CTkFrame(scroller, fg_color=BG, corner_radius=0)
            row.pack(fill="x", padx=8, pady=(0, 2))
            ghost_button(
                row,
                "Suggest",
                lambda key=spec.key: self._suggest_one(key),
                self.fonts.tiny,
                width=90,
            ).pack(side="left", padx=(0, 6))
            ghost_button(
                row,
                "Apply suggestion",
                lambda key=spec.key: self._apply_one(key),
                self.fonts.tiny,
                width=130,
            ).pack(side="left", padx=(0, 6))
            why_text = (assist.why if assist else "") or ""
            why_label = ctk.CTkLabel(
                row,
                text=why_text,
                font=self.fonts.tiny,
                text_color=CYAN if why_text else MUTED,
                anchor="w",
                justify="left",
                wraplength=420,
            )
            why_label.pack(side="left", fill="x", expand=True, padx=(8, 0))
            self._why_labels[spec.key] = why_label

    def _assist_for(self, key: str) -> FieldAssist | None:
        if key in self.field_assists:
            return self.field_assists[key]
        if self.project is None or self.library is None or not self.type_id:
            return None
        try:
            assist = suggest_field(
                self.project,
                self.library,
                self.profile or default_profile(),
                type_id=self.type_id,
                field_key=key,
                prior=self.values,
                interview=self.project.interview,
            )
            self.field_assists[key] = assist
            return assist
        except Exception:
            return None

    def _picks_for(self, spec: FieldSpec, assist: FieldAssist | None) -> list[str]:
        picks: list[str] = []
        if assist is not None:
            picks.extend([p for p in assist.picks if p])
        if spec.options:
            for opt in spec.options:
                if opt not in picks:
                    picks.append(opt)
        return picks

    def _set_why(self, key: str, text: str) -> None:
        label = self._why_labels.get(key)
        if label is None:
            return
        try:
            label.configure(text=text or "", text_color=CYAN if text else MUTED)
        except Exception:
            return

    def _on_pick(self, key: str, chosen: str) -> None:
        if chosen == SELECT:
            return
        self.values[key] = chosen
        why = why_for_pick(key, chosen, self.type_id)
        assist = self.field_assists.get(key)
        if assist and chosen == assist.value and assist.why:
            why = assist.why
        self._set_why(key, why)
        if self.project is not None and self.profile is not None and self.type_id:
            _ctx, self.profile = remember_field_choice(
                self.project,
                self.profile,
                type_id=self.type_id,
                field_key=key,
                value=chosen,
                interview=self.project.interview,
            )

    def _suggest_one(self, key: str) -> None:
        assist = self._assist_for(key)
        if assist is None:
            self._set_why(key, "No suggestion engine for this field yet.")
            return
        self.field_assists[key] = assist
        if assist.value:
            self.suggestions[key] = assist.value
        self._set_why(key, assist.why or "Suggestion ready.")
        # Refresh the step so dropdowns pick up new picks / values display.
        self._store_current()
        self._show_step(self.index)

    def _apply_one(self, key: str) -> None:
        assist = self._assist_for(key)
        value = ""
        if assist and assist.value:
            value = assist.value
        elif key in self.suggestions:
            value = self.suggestions[key]
        if not value:
            self._set_why(key, "Nothing to apply yet — press Suggest first.")
            return
        self.values[key] = value
        self.suggestions[key] = value
        why = assist.why if assist else why_for_pick(key, value, self.type_id)
        self._set_why(key, why)
        if self.project is not None and self.profile is not None and self.type_id:
            _ctx, self.profile = remember_field_choice(
                self.project,
                self.profile,
                type_id=self.type_id,
                field_key=key,
                value=value,
                interview=self.project.interview,
            )
        self._store_current()
        # Push into live widgets without full rebuild when possible.
        widget = self._widgets.get(key)
        if widget is None:
            self._show_step(self.index)
            return
        spec = self._by_key[key]
        if key in self._vars:
            self._vars[key].set(value)
        elif spec.type == "multiline":
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
        else:
            try:
                widget.delete(0, "end")
                widget.insert(0, value)
            except Exception:
                self._show_step(self.index)

    def _build_review(self) -> None:
        missing = missing_specs(self.values, self.fields)
        scroller = self.scroller
        if missing:
            banner = ctk.CTkFrame(scroller, fg_color=WARN_BG, corner_radius=4)
            banner.pack(fill="x", padx=8, pady=(4, 8))
            ctk.CTkLabel(
                banner,
                text=f"{len(missing)} required field{'s' if len(missing) != 1 else ''} still open",
                font=self.fonts.heading,
                text_color=ORANGE,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkLabel(
                banner,
                text="The tile stays flagged until these are filled. You can place it and come back.",
                font=self.fonts.small,
                text_color=TEXT,
                anchor="w",
                justify="left",
                wraplength=620,
            ).pack(fill="x", padx=12, pady=(0, 8))
            for spec in missing:
                ctk.CTkLabel(
                    scroller,
                    text=f"Open   ·   {spec.label}",
                    font=self.fonts.body,
                    text_color=ORANGE,
                    anchor="w",
                ).pack(fill="x", padx=12, pady=1)
        else:
            banner = ctk.CTkFrame(scroller, fg_color=OK_BG, corner_radius=4)
            banner.pack(fill="x", padx=8, pady=(4, 8))
            ctk.CTkLabel(
                banner,
                text="Required fields are filled",
                font=self.fonts.heading,
                text_color=CYAN,
                anchor="w",
            ).pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(
            scroller,
            text="ANSWERED",
            font=self.fonts.tiny,
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(12, 4))
        shown = False
        for spec in self.fields:
            value = self.values.get(spec.key, "").strip()
            if not value:
                continue
            shown = True
            ctk.CTkLabel(
                scroller,
                text=f"{spec.label}    {value}",
                font=self.fonts.small,
                text_color=TEXT,
                anchor="w",
                justify="left",
                wraplength=640,
            ).pack(fill="x", padx=12, pady=1)
        if not shown:
            ctk.CTkLabel(
                scroller,
                text="Nothing answered yet.",
                font=self.fonts.small,
                text_color=MUTED,
                anchor="w",
            ).pack(fill="x", padx=12)

    def _update_nav(self) -> None:
        last = self.index == len(self.steps) - 1
        self.back_btn.configure(state="normal" if self.index else "disabled")
        if last:
            self.next_btn.pack_forget()
            missing = missing_specs(self.values, self.fields)
            if self.mode == "edit":
                label = "Save flagged" if missing else "Save definition"
            else:
                label = "Place flagged" if missing else "Place on layout"
            self.finish_btn.configure(text=label)
            if missing:
                self.hint.configure(
                    text="Empty required fields stay flagged on the cabinet until you fill them.",
                    text_color=ORANGE,
                )
            else:
                self.hint.configure(text="This device will sit on the layout without a flag.", text_color=CYAN)
        else:
            if not self.next_btn.winfo_ismapped():
                self.next_btn.pack(side="right", padx=6, pady=12)
            self.finish_btn.configure(text="Review")
            if self.suggestions:
                self.hint.configure(
                    text="Suggestions are editable. " + DESIGN_AID_DISCLAIMER,
                    text_color=MUTED,
                )
            else:
                self.hint.configure(
                    text="Walk each group. Review is where the device is placed.",
                    text_color=MUTED,
                )

    def _store_current(self) -> None:
        for key, widget in self._widgets.items():
            spec = self._by_key[key]
            if spec.type == "multiline" and key not in self._vars:
                self.values[key] = widget.get("1.0", "end").strip()
            elif key in self._vars:
                selected = self._vars[key].get()
                self.values[key] = "" if selected == SELECT else selected
            else:
                self.values[key] = widget.get().strip()

    def _accept_suggestions(self) -> None:
        if not self.suggestions:
            return
        for key, value in self.suggestions.items():
            if key in self._by_key:
                self.values[key] = value
        self.special_var.set(False)
        self._widgets.clear()
        self._show_step(self.index)

    def _back(self) -> None:
        if self.index:
            self._show_step(self.index - 1)

    def _next(self) -> None:
        if self.index < len(self.steps) - 1:
            self._show_step(self.index + 1)

    def _finish(self) -> None:
        if self.index != len(self.steps) - 1:
            self._show_step(len(self.steps) - 1)
            return
        self._store_current()
        callback = self.on_submit
        self.values["nonstandard"] = "Yes" if self.special_var.get() else "No"
        values = dict(self.values)
        self._submitted = True
        self.close()
        if callback is not None:
            callback(values)
