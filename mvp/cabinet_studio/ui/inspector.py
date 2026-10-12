"""Right-hand inspector. Shows the project, or the selected device."""

from __future__ import annotations

import customtkinter as ctk

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.models.schema import Library
from cabinet_studio.services.completeness import missing_specs, project_definition_status
from cabinet_studio.services.ul508a import DESIGN_AID_DISCLAIMER
from cabinet_studio.services.descriptors import tile_text
from cabinet_studio.ui.theme import (
    BORDER,
    CYAN,
    ENTRY,
    INSPECTOR_WIDTH,
    MUTED,
    OK_BG,
    ORANGE,
    PANEL,
    TEXT,
    WARN_BG,
    danger_button,
    ghost_button,
    primary_button,
    scroll_frame,
    section_label,
)


class Inspector(ctk.CTkFrame):
    def __init__(self, master, fonts, callbacks: dict) -> None:
        super().__init__(
            master,
            width=INSPECTOR_WIDTH,
            height=640,
            fg_color=PANEL,
            corner_radius=0,
        )
        self.pack_propagate(False)
        self.fonts = fonts
        self.callbacks = callbacks
        self.project: Project | None = None
        self.library: Library | None = None
        self.selected: PlacedItem | None = None
        self._rendering = False
        section_label(self, "INSPECTOR", fonts.tiny).pack(anchor="w", padx=16, pady=(14, 4))
        # Actions stay pinned. Pack them before the scrolling body.
        self.actions = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        self.actions.pack(side="bottom", fill="x", padx=12, pady=12)
        self.edit_btn = primary_button(self.actions, "Continue definition", self._edit, fonts.body, width=300)
        self.remove_btn = danger_button(self.actions, "Remove from layout", self._remove, fonts.body, width=300)
        self.body = scroll_frame(self)
        self.body.pack(side="top", fill="both", expand=True, padx=0, pady=(0, 4))

    def render(self, project: Project, library: Library, selected: PlacedItem | None, saves_dir=None) -> None:
        self.saves_dir = saves_dir
        self._rendering = True
        self.project = project
        self.library = library
        self.selected = selected
        try:
            for child in self.body.winfo_children():
                child.destroy()
            self.edit_btn.pack_forget()
            self.remove_btn.pack_forget()
            if selected is None:
                self._render_project()
            else:
                self._render_item(selected)
        finally:
            self._rendering = False

    def _render_project(self) -> None:
        project = self.project
        library = self.library
        total, open_count = project_definition_status(project, library)
        self._banner(
            "No device selected",
            project.subtitle or "Select a tile, or add one from the library.",
            ORANGE if open_count else CYAN,
            WARN_BG if open_count else OK_BG,
        )
        duty = (project.interview.get("duty") or "").strip()
        if duty:
            self._label("APPLICATION")
            ctk.CTkLabel(
                self.body,
                text=duty,
                font=self.fonts.small,
                text_color=TEXT,
                anchor="w",
                justify="left",
                wraplength=290,
            ).pack(fill="x", padx=12, pady=(0, 8))
        if getattr(self, "saves_dir", None):
            self._label("SAVED CABINETS")
            ctk.CTkLabel(
                self.body,
                text=str(self.saves_dir),
                font=self.fonts.tiny,
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=290,
            ).pack(fill="x", padx=12, pady=(0, 8))
        self._label("PANEL LABEL")
        box = ctk.CTkEntry(
            self.body,
            font=self.fonts.body,
            height=34,
            fg_color=ENTRY,
            border_color=BORDER,
            text_color=TEXT,
        )
        box.insert(0, project.cabinet_label)
        box.pack(fill="x", padx=12, pady=(0, 8))
        box.bind("<FocusOut>", lambda _event, widget=box: self._commit_label(widget))
        box.bind("<Return>", lambda _event, widget=box: self._commit_label(widget))
        self._label("PROJECT NOTES")
        notes = ctk.CTkTextbox(
            self.body,
            height=90,
            font=self.fonts.small,
            fg_color=ENTRY,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT,
            corner_radius=4,
        )
        notes.pack(fill="x", padx=12, pady=(0, 8))
        if project.notes:
            notes.insert("1.0", project.notes)
        notes.bind("<FocusOut>", lambda _event, widget=notes: self._commit_notes(widget))
        if total == 0:
            ctk.CTkLabel(
                self.body,
                text="Nothing on the panel yet.",
                font=self.fonts.body,
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=290,
            ).pack(fill="x", padx=12, pady=8)
            self._disclaimer()
            return
        defined = total - open_count
        self._label(f"DEFINED  {defined} / {total}")
        open_items = []
        done_items = []
        for item in project.items:
            equipment = library.types.get(item.type_id)
            missing = [] if equipment is None else missing_specs(item.fields, equipment.fields)
            if equipment is None or missing:
                open_items.append((item, equipment, missing))
            else:
                done_items.append((item, equipment))
        if open_items:
            self._label("STILL OPEN")
            for item, equipment, missing in open_items:
                tag = item.fields.get("tag", "").strip() or "UNTAGGED"
                kind = equipment.label if equipment else item.type_id
                ghost_button(
                    self.body,
                    f"{tag}   ·   {kind}   ·   {len(missing)} open",
                    lambda item_id=item.id: self.callbacks["select"](item_id),
                    self.fonts.small,
                    width=296,
                ).pack(fill="x", padx=12, pady=3)
        if done_items:
            self._label("COMPLETE")
            for item, equipment in done_items:
                tag = item.fields.get("tag", "").strip() or "UNTAGGED"
                ctk.CTkLabel(
                    self.body,
                    text=f"{tag}   ·   {equipment.label}",
                    font=self.fonts.small,
                    text_color=CYAN,
                    anchor="w",
                ).pack(fill="x", padx=12, pady=1)
        self._disclaimer()

    def _disclaimer(self) -> None:
        ctk.CTkLabel(
            self.body,
            text=DESIGN_AID_DISCLAIMER,
            font=self.fonts.tiny,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=290,
        ).pack(fill="x", padx=12, pady=(12, 4))

    def _render_item(self, item: PlacedItem) -> None:
        equipment = self.library.types.get(item.type_id)
        if equipment is None:
            self._banner("Unknown device", "This type is not in the current library.", ORANGE, WARN_BG)
            self.remove_btn.pack(fill="x", pady=4)
            return
        missing = missing_specs(item.fields, equipment.fields)
        tag, _kind, detail = tile_text(item, equipment)
        special = item.fields.get("nonstandard", "").strip().lower() in {"yes", "y", "true", "special"}
        if missing:
            self._banner(
                f"{len(missing)} required field{'s' if len(missing) != 1 else ''} open",
                "Marked special. Shop standards will not learn this device."
                if special
                else "Continue the definition before this device is released.",
                ORANGE,
                WARN_BG,
            )
        else:
            self._banner(
                "Special / nonstandard" if special else "Definition complete",
                "Shop standards will not learn this device."
                if special
                else "Required fields for this device are filled.",
                ORANGE if special else CYAN,
                WARN_BG if special else OK_BG,
            )
        ctk.CTkLabel(self.body, text=tag, font=self.fonts.tag, text_color=TEXT, anchor="w").pack(
            fill="x", padx=12, pady=(8, 0)
        )
        ctk.CTkLabel(
            self.body,
            text=equipment.label.upper(),
            font=self.fonts.tiny,
            text_color=equipment.accent,
            anchor="w",
        ).pack(fill="x", padx=12)
        ctk.CTkLabel(
            self.body,
            text=detail,
            font=self.fonts.small,
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=290,
        ).pack(fill="x", padx=12, pady=(0, 6))
        ghost_button(
            self.body,
            "Project overview",
            lambda: self.callbacks["select"](None),
            self.fonts.small,
            width=296,
        ).pack(fill="x", padx=12, pady=(0, 8))
        missing_keys = {spec.key for spec in missing}
        for group in self.library.groups:
            fields = [spec for spec in equipment.fields if spec.group == group.id]
            visible = [spec for spec in fields if spec.key in missing_keys or item.fields.get(spec.key, "").strip()]
            if not visible:
                continue
            self._label(group.title.upper())
            for spec in visible:
                value = item.fields.get(spec.key, "").strip()
                if spec.key in missing_keys:
                    ctk.CTkLabel(
                        self.body,
                        text=f"{spec.label}    required",
                        font=self.fonts.small,
                        text_color=ORANGE,
                        anchor="w",
                    ).pack(fill="x", padx=12, pady=1)
                else:
                    ctk.CTkLabel(
                        self.body,
                        text=spec.label,
                        font=self.fonts.tiny,
                        text_color=MUTED,
                        anchor="w",
                    ).pack(fill="x", padx=12, pady=(4, 0))
                    ctk.CTkLabel(
                        self.body,
                        text=value,
                        font=self.fonts.small,
                        text_color=TEXT,
                        anchor="w",
                        justify="left",
                        wraplength=290,
                    ).pack(fill="x", padx=12, pady=(0, 2))
        self.edit_btn.configure(text="Continue definition" if missing else "Edit definition")
        self.edit_btn.pack(fill="x", pady=(0, 6))
        self.remove_btn.pack(fill="x")

    def _banner(self, title: str, body: str, color: str, fill: str) -> None:
        frame = ctk.CTkFrame(self.body, fg_color=fill, corner_radius=4)
        frame.pack(fill="x", padx=12, pady=(4, 8))
        ctk.CTkLabel(frame, text=title, font=self.fonts.heading, text_color=color, anchor="w").pack(
            fill="x", padx=10, pady=(8, 0)
        )
        ctk.CTkLabel(
            frame,
            text=body,
            font=self.fonts.small,
            text_color=TEXT,
            anchor="w",
            justify="left",
            wraplength=280,
        ).pack(fill="x", padx=10, pady=(2, 8))

    def _label(self, text: str) -> None:
        section_label(self.body, text, self.fonts.tiny).pack(anchor="w", padx=12, pady=(10, 4))

    def _commit_label(self, widget) -> None:
        if self._rendering or self.project is None:
            return
        self.callbacks["cabinet_label"](widget.get())

    def _commit_notes(self, widget) -> None:
        if self._rendering or self.project is None:
            return
        self.callbacks["notes"](widget.get("1.0", "end").strip())

    def _edit(self) -> None:
        if self.selected is not None:
            self.callbacks["edit"](self.selected.id)

    def _remove(self) -> None:
        if self.selected is not None:
            self.callbacks["delete"](self.selected.id)
