"""Cabinet Studio main window.

Pack order is deliberate. The right inspector is packed before the
expanding center pane so a scaled DPI does not collapse the side rail.
Left rail: OUTPUT (Drawings / View drawings / Programming) is sticky; the rest scrolls.
"""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from cabinet_studio.models.project import PlacedItem
from cabinet_studio.models.schema import Library
from cabinet_studio.services.completeness import is_complete, missing_specs, project_definition_status
from cabinet_studio.services.drawings import DrawingError, build_sheets, default_drawings_folder, write_drawings
from cabinet_studio.services.desktop_shortcut import create_desktop_shortcut
from cabinet_studio.services.layouts import instantiate_layout, new_blank_project, new_id
from cabinet_studio.services.paths import saves_directory, standards_profile_path
from cabinet_studio.services.placement import next_free_position
from cabinet_studio.services.project_store import ProjectError, load_project, project_from_dict, project_to_dict, save_project
from cabinet_studio.services.standards import StandardsError, default_profile, load_standards, save_standards
from cabinet_studio.services.suggestions import (
    DeviceSuggestion,
    enrich_with_wiring_assist,
    fill_blanks,
    is_special,
    remember_acceptance,
    suggest_device,
    suggest_layout,
    suggest_part_types,
    used_wire_numbers,
)
from cabinet_studio.services.wiring_assist import (
    apply_all_project_suggestions,
    remember_device_fields,
    suggest_all_fields,
)
from cabinet_studio.services.ul508a import review_ul508a
from cabinet_studio.services.ai_build import (
    AI_BUILD_DISCLAIMER,
    apply_recommendations,
    interview_from_ai_answers,
    project_name_from_answers,
    recommend_devices,
)
from cabinet_studio.services.programming import build_starter_program, default_design_answers, program_has_content
from cabinet_studio.ui.ai_build import AiBuildDialog
from cabinet_studio.ui.assist import GuidePlanDialog, InterviewDialog, ReviewWindow
from cabinet_studio.ui.canvas_view import LayoutCanvas
from cabinet_studio.ui.drawing_viewer import DrawingViewer
from cabinet_studio.ui.dialogs import NewProjectDialog, TypePicker, ask_choice
from cabinet_studio.ui.inspector import Inspector
from cabinet_studio.ui.library_rail import LibraryRail
from cabinet_studio.ui.program_browser import ProgramBrowser
from cabinet_studio.ui.programming_viewer import ProgrammingViewer
from cabinet_studio.ui.shell.main_shell import install_main_shell
from cabinet_studio.ui.splash import Splash
from cabinet_studio.ui.theme import (
    BG,
    BORDER,
    MUTED,
    ORANGE,
    PANEL,
    TEXT,
    Fonts,
    choose_families,
    entry,
    load_mode,
)
from cabinet_studio.ui.wizard import DefinitionWizard


class CabinetStudioApp(ctk.CTk):
    def __init__(self, library: Library) -> None:
        load_mode()
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=BG)
        self.library = library
        self.project = new_blank_project()
        self.path: Path | None = None
        self.dirty = False
        self.selected_id: str | None = None
        self.undo_stack: list = []
        self._pending_undo = None
        self._wizard_window: DefinitionWizard | None = None
        self._picker: TypePicker | None = None
        self._splash: Splash | None = None
        self._interview: InterviewDialog | None = None
        self._guide_plan: GuidePlanDialog | None = None
        self._review: ReviewWindow | None = None
        self._last_drawing_paths: list = []
        self._drawing_viewer = None
        self._programming_viewer = None
        self._guide_queue: list[dict] = []
        self._ai_build_active = False
        self._ai_build_dialog = None
        try:
            self.standards = load_standards(standards_profile_path())
        except StandardsError:
            self.standards = default_profile()
        self.fonts = Fonts(*choose_families(self))
        self.title("Cabinet Studio")
        self.geometry("1400x860")
        self.minsize(1200, 700)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        install_main_shell(self)
        self._bind_keys()
        self._sync_name()
        self._refresh_all()
        if os.environ.get("CABINET_STUDIO_NO_SPLASH") != "1":
            self.after(150, self._open_splash)

    def _build(self) -> None:
        header = ctk.CTkFrame(self, height=72, fg_color=PANEL, corner_radius=0)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        pill = ctk.CTkFrame(header, fg_color="#24180f", corner_radius=4, border_width=1, border_color=ORANGE)
        pill.pack(side="right", padx=16, pady=18)
        ctk.CTkLabel(pill, text="DRIVERS OFFLINE", font=self.fonts.tiny, text_color=ORANGE).pack(padx=10, pady=4)
        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", padx=16, pady=12)
        mark = ctk.CTkFrame(brand, width=14, height=14, fg_color=ORANGE, corner_radius=2)
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=2)
        mark.grid_propagate(False)
        ctk.CTkLabel(brand, text="CABINET STUDIO", font=self.fonts.title, text_color=TEXT, anchor="w").grid(
            row=0, column=1, sticky="w"
        )
        ctk.CTkLabel(
            brand,
            text="WARREN WILLIAMS  ·  ERMCO",
            font=self.fonts.tiny,
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=1, sticky="w")
        self.name_var = ctk.StringVar(value=self.project.name)
        self.name_entry = entry(header, self.fonts.body, textvariable=self.name_var, width=420)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=18, pady=18)
        self.name_entry.bind("<FocusOut>", self._commit_name)
        self.name_entry.bind("<Return>", self._commit_name)

        rule = ctk.CTkFrame(self, height=3, fg_color=ORANGE, corner_radius=0)
        rule.pack(side="top", fill="x")
        rule.pack_propagate(False)

        status = ctk.CTkFrame(self, height=32, fg_color="#101014", corner_radius=0)
        status.pack(side="bottom", fill="x")
        status.pack_propagate(False)
        self.status_hint = ctk.CTkLabel(
            status,
            text="Ctrl+S save    Ctrl+Z undo    double-click defines    Delete removes",
            font=self.fonts.tiny,
            text_color=MUTED,
        )
        self.status_hint.pack(side="right", padx=12)
        self.status_label = ctk.CTkLabel(status, text="", font=self.fonts.small, text_color=TEXT, anchor="w")
        self.status_label.pack(side="left", padx=12)

        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(side="top", fill="both", expand=True)

        self.rail = LibraryRail(
            body,
            self.fonts,
            self.library,
            {
                "new_build_ai": self.new_build_with_ai,
                "new": self.new_project,
                "open": self.open_project,
                "save": self.save,
                "save_as": self.save_as,
                "drawings": self.generate_drawings,
                "view_drawings": self.view_drawings,
                "programming": self.open_programming,
                "hmi_editor": self.open_hmi_editor,
                "programs": self.open_programs,
                "desktop_shortcut": self.install_desktop_shortcut,
                "guide": self.guide_build,
                "suggest": self.ai_suggest,
                "apply_all_suggestions": self.apply_all_ai_suggestions,
                "ul508a": self.open_ul508a_review,
                "layout": self.apply_layout,
                "add_catalog": self.add_from_catalog,
                "add_type": self.add_blank,
            },
        )
        self.rail.pack(side="left", fill="y")
        sep_left = ctk.CTkFrame(body, width=1, fg_color=BORDER, corner_radius=0)
        sep_left.pack(side="left", fill="y")
        sep_left.pack_propagate(False)

        # Inspector before the expanding center. See the module docstring.
        self.inspector = Inspector(
            body,
            self.fonts,
            {
                "select": self.select_item,
                "edit": self.edit_item,
                "delete": self.delete_selected,
                "cabinet_label": self._set_cabinet_label,
                "notes": self._set_notes,
            },
        )
        self.inspector.pack(side="right", fill="y")
        sep_right = ctk.CTkFrame(body, width=1, fg_color=BORDER, corner_radius=0)
        sep_right.pack(side="right", fill="y")
        sep_right.pack_propagate(False)

        center = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        center.pack(side="left", fill="both", expand=True)
        self.canvas_view = LayoutCanvas(
            center,
            self.fonts,
            on_select=self.select_item,
            on_edit=self.edit_item,
            on_drag_start=self._drag_start,
            on_drag_end=self._drag_end,
        )
        self.canvas_view.pack(fill="both", expand=True, padx=(8, 4), pady=8)

    def _bind_keys(self) -> None:
        self.bind_all("<Control-s>", self._save_shortcut)
        self.bind_all("<Control-S>", self._save_as_shortcut)
        self.bind_all("<Control-o>", self._open_shortcut)
        self.bind_all("<Control-n>", self._new_shortcut)
        self.bind_all("<Control-z>", self._undo_shortcut)
        self.bind_all("<Delete>", self._delete_shortcut)

    def _open_splash(self) -> None:
        if self._splash is not None and self._splash.winfo_exists():
            return
        self._splash = Splash(self, self.fonts)

    def _typing(self) -> bool:
        widget = self.focus_get()
        if widget is None:
            return False
        return widget.winfo_class() in {"Entry", "Text", "TEntry"}

    def _modal(self) -> bool:
        current = self.grab_current()
        return current is not None and current is not self

    def _save_shortcut(self, _event=None):
        if self._modal():
            return "break"
        self.save()
        return "break"

    def _save_as_shortcut(self, _event=None):
        if self._modal():
            return "break"
        self.save_as()
        return "break"

    def _open_shortcut(self, _event=None):
        if self._modal():
            return "break"
        self.open_project()
        return "break"

    def _new_shortcut(self, _event=None):
        if self._modal():
            return "break"
        self.new_project()
        return "break"

    def _undo_shortcut(self, _event=None):
        if self._modal() or self._typing():
            return
        self.undo()
        return "break"

    def _delete_shortcut(self, _event=None):
        if self._modal() or self._typing():
            return
        self.delete_selected()
        return "break"

    def _push_undo(self) -> None:
        self.undo_stack.append(project_from_dict(project_to_dict(self.project)))
        if len(self.undo_stack) > 40:
            del self.undo_stack[0]

    def undo(self) -> None:
        if not self.undo_stack:
            self._set_status("Nothing to undo")
            return
        self.project = self.undo_stack.pop()
        if self.selected_id and self.project.find(self.selected_id) is None:
            self.selected_id = None
        self.dirty = True
        self._sync_name()
        self._refresh_all("Undid the last change")

    def _drag_start(self, _item_id: str) -> None:
        self._pending_undo = project_from_dict(project_to_dict(self.project))

    def _drag_end(self, moved: bool) -> None:
        if moved and self._pending_undo is not None:
            self.undo_stack.append(self._pending_undo)
            if len(self.undo_stack) > 40:
                del self.undo_stack[0]
            self.dirty = True
            self._update_title()
            self._set_status(self._summary())
        self._pending_undo = None

    def _sync_name(self) -> None:
        self.name_var.set(self.project.name)

    def _commit_name(self, _event=None) -> None:
        name = self.name_var.get().strip() or "Untitled cabinet"
        if name == self.project.name:
            self.name_var.set(self.project.name)
            return
        self._push_undo()
        self.project.name = name
        self.name_var.set(name)
        self.dirty = True
        self._refresh_all()

    def _set_cabinet_label(self, value: str) -> None:
        label = value.strip() or "PNL1"
        if label == self.project.cabinet_label:
            return
        self._push_undo()
        self.project.cabinet_label = label
        self.dirty = True
        self.canvas_view.redraw()
        self._update_title()
        self._set_status(self._summary())

    def _set_notes(self, value: str) -> None:
        if value == self.project.notes:
            return
        self._push_undo()
        self.project.notes = value
        self.dirty = True
        self._update_title()
        self._set_status(self._summary())

    def _replace_project(self, project, path: Path | None, dirty: bool, status: str) -> None:
        self.project = project
        self.path = path
        self.dirty = dirty
        self.selected_id = None
        self.undo_stack.clear()
        self._pending_undo = None
        self._sync_name()
        self._refresh_all(status)

    def select_item(self, item_id: str | None) -> None:
        self.selected_id = item_id
        self._refresh_all()

    def _refresh_all(self, status: str | None = None) -> None:
        self.canvas_view.set_state(self.project, self.library, self.selected_id)
        selected = None if self.selected_id is None else self.project.find(self.selected_id)
        self.inspector.render(self.project, self.library, selected, saves_directory())
        self._update_title()
        self._set_status(status or self._summary())

    def _summary(self) -> str:
        total, open_count = project_definition_status(self.project, self.library)
        if total == 0:
            parts = ["No devices on the panel"]
        else:
            noun = "device" if total == 1 else "devices"
            parts = [f"{total} {noun}"]
            parts.append(f"{open_count} still need definition" if open_count else "all defined")
        if self.selected_id:
            item = self.project.find(self.selected_id)
            if item is not None:
                parts.append("selected " + (item.fields.get("tag", "").strip() or "untagged"))
        if self.dirty:
            parts.append("unsaved changes")
        elif self.path is not None:
            parts.append(f"saved {self.path.name}")
        return "   ·   ".join(parts)

    def _set_status(self, text: str) -> None:
        _total, open_count = project_definition_status(self.project, self.library)
        color = ORANGE if open_count else TEXT
        self.status_label.configure(text=text, text_color=color)

    def _update_title(self) -> None:
        star = "*" if self.dirty else ""
        self.title(f"{star}{self.project.name} — Cabinet Studio")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = ask_choice(
            self,
            self.fonts,
            "Save cabinet?",
            "Save changes to this cabinet before continuing?",
            [
                ("save", "Save", "primary"),
                ("discard", "Don't save", "ghost"),
                ("cancel", "Cancel", "ghost"),
            ],
        )
        if answer == "save":
            return self.save()
        return answer == "discard"

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        NewProjectDialog(self, self.fonts, self.library, self._create_project)

    def _create_project(self, name: str, layout_id: str | None) -> None:
        if layout_id:
            project = instantiate_layout(self.library.layout_by_id[layout_id], self.library, name)
            status = f"Created {name} from {project.cabinet_label}. Required wiring and I/O are still open."
        else:
            project = new_blank_project(name)
            status = f"Created {name}."
        self._replace_project(project, None, True, status)

    def apply_layout(self, layout_id: str, *, confirm: bool = True) -> None:
        layout = self.library.layout_by_id[layout_id]
        if confirm and self.project.items:
            answer = ask_choice(
                self,
                self.fonts,
                "Replace layout?",
                f"Replace the devices on this panel with {layout.name}?",
                [("yes", "Replace", "primary"), ("no", "Cancel", "ghost")],
            )
            if answer != "yes":
                return
        fresh = instantiate_layout(layout, self.library, self.project.name)
        fresh.notes = self.project.notes
        fresh.interview = dict(self.project.interview)
        fresh.program = dict(self.project.program)
        self._push_undo()
        self.project = fresh
        self.selected_id = None
        self.dirty = True
        self._refresh_all(f"Loaded {layout.name}. Wiring and PLC addresses are still open.")

    def open_path(self, path: Path) -> None:
        """Open a cabinet JSON by path (CLI / automation)."""
        try:
            project = load_project(path)
        except ProjectError as exc:
            ask_choice(self, self.fonts, "Could not open", str(exc), [("ok", "OK", "primary")])
            return
        self._replace_project(project, Path(path), False, f"Opened {Path(path).name}")

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        chosen = filedialog.askopenfilename(
            parent=self,
            filetypes=[("Cabinet Studio project", "*.cabinet.json"), ("JSON", "*.json"), ("All files", "*.*")],
            initialdir=str(saves_directory()),
        )
        if not chosen:
            return
        try:
            project = load_project(chosen)
        except ProjectError as exc:
            ask_choice(self, self.fonts, "Could not open", str(exc), [("ok", "OK", "primary")])
            return
        self._replace_project(project, Path(chosen), False, f"Opened {Path(chosen).name}")

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        chosen = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".cabinet.json",
            filetypes=[("Cabinet Studio project", "*.cabinet.json"), ("JSON", "*.json")],
            initialdir=str(saves_directory()),
            initialfile=self._slug() + ".cabinet.json",
        )
        if not chosen:
            return False
        return self._write(Path(chosen))

    def _write(self, path: Path) -> bool:
        try:
            save_project(self.project, path)
        except OSError as exc:
            ask_choice(self, self.fonts, "Could not save", str(exc), [("ok", "OK", "primary")])
            return False
        self.path = path
        self.dirty = False
        self._refresh_all(f"Saved {path.name}")
        return True

    def add_from_catalog(self, catalog_id: str) -> None:
        catalog = self.library.catalog_by_id[catalog_id]
        self._open_definition(
            type_id=catalog.type_id,
            library_id=catalog.id,
            heading=f"Define {self.library.types[catalog.type_id].label.lower()}",
            subheading=f"{catalog.name}   ·   {catalog.vendor}   ·   {catalog.catalog}",
            initial=self._initial_from_catalog(catalog_id),
            mode="add",
        )

    def add_blank(self) -> None:
        if self._picker is None or not self._picker.winfo_exists():
            self._picker = TypePicker(self, self.fonts, self.library, self._start_blank)
        self._picker.open()

    def _start_blank(self, type_id: str) -> None:
        equipment = self.library.types[type_id]
        initial = {spec.key: "" for spec in equipment.fields}
        self._open_definition(
            type_id=type_id,
            library_id=None,
            heading=f"Define {equipment.label.lower()}",
            subheading="Not picked from the starter library. The questions are the same.",
            initial=initial,
            mode="add",
        )

    def edit_item(self, item_id: str) -> None:
        item = self.project.find(item_id)
        if item is None:
            return
        equipment = self.library.types.get(item.type_id)
        if equipment is None:
            self._set_status("This device type is not in the library.")
            return
        initial = {spec.key: item.fields.get(spec.key, "") for spec in equipment.fields}
        catalog = self.library.catalog_by_id.get(item.library_id) if item.library_id else None
        subheading = catalog.name if catalog is not None else "Custom device"
        self._open_definition(
            type_id=item.type_id,
            library_id=item.library_id,
            heading=f"Define {equipment.label.lower()}",
            subheading=subheading,
            initial=initial,
            mode="edit",
            existing_id=item.id,
        )

    def _initial_from_catalog(self, catalog_id: str) -> dict[str, str]:
        catalog = self.library.catalog_by_id[catalog_id]
        equipment = self.library.types[catalog.type_id]
        initial = {spec.key: "" for spec in equipment.fields}
        initial.update(catalog.default_map())
        initial["vendor"] = catalog.vendor
        initial["catalog"] = catalog.catalog
        return initial

    def _open_definition(
        self,
        *,
        type_id: str,
        library_id: str | None,
        heading: str,
        subheading: str,
        initial: dict[str, str],
        mode: str,
        existing_id: str | None = None,
        suggestion: DeviceSuggestion | None = None,
        guide: bool = False,
    ) -> None:
        equipment = self.library.types[type_id]
        if existing_id:
            current = self.project.find(existing_id)
            if current is not None and "nonstandard" not in initial:
                initial = dict(initial)
                initial["nonstandard"] = current.fields.get("nonstandard", "")
        if suggestion is not None:
            initial = fill_blanks(initial, suggestion)
        spec_labels = [field.label for field in equipment.fields if field.group == "specifications"]
        if spec_labels:
            subheading = f"{subheading}   ·   {', '.join(spec_labels)}"
        extras = {}
        if existing_id:
            current = self.project.find(existing_id)
            if current is not None:
                extras = {key: value for key, value in current.fields.items() if key not in initial}

        def submit(fields: dict[str, str]) -> None:
            merged = dict(fields)
            for key, value in extras.items():
                merged.setdefault(key, value)
            self._push_undo()
            if existing_id:
                item = self.project.find(existing_id)
                if item is None:
                    return
                item.fields = merged
                self.selected_id = item.id
                tag = merged.get("tag", "").strip() or equipment.label
                verb = "Updated"
            else:
                x, y = next_free_position(self.project, self.library, type_id)
                item = PlacedItem(
                    id=new_id(),
                    library_id=library_id,
                    type_id=type_id,
                    x=x,
                    y=y,
                    fields=merged,
                )
                self.project.items.append(item)
                self.selected_id = item.id
                tag = merged.get("tag", "").strip() or equipment.label
                verb = "Placed"
            self.dirty = True
            self._remember(type_id, item.library_id, merged, suggestion)
            self.standards = remember_device_fields(
                self.project,
                self.standards,
                type_id=type_id,
                fields=merged,
                interview=self.project.interview,
            )
            missing = missing_specs(merged, equipment.fields)
            if missing:
                note = f"{verb} {tag}. {len(missing)} required fields still open."
            else:
                note = f"{verb} {tag}. Definition complete."
            self._refresh_all(note)
            if guide:
                if self._guide_queue:
                    self.after(80, self._guide_next)
                else:
                    self.after(80, self._guide_finished)

        if self._wizard_window is None or not self._wizard_window.winfo_exists():
            self._wizard_window = DefinitionWizard(self, self.fonts)
        assists = suggest_all_fields(
            self.project,
            self.library,
            self.standards,
            type_id,
            prior=initial,
            interview=self.project.interview,
        )
        self._wizard_window.present(
            heading=heading,
            subheading=subheading,
            accent=equipment.accent,
            groups=list(self.library.groups),
            fields=list(equipment.fields),
            initial=initial,
            mode=mode,
            on_submit=submit,
            suggestions=None if suggestion is None else suggestion.fields,
            on_close=self._guide_closed if guide else None,
            project=self.project,
            library=self.library,
            profile=self.standards,
            type_id=type_id,
            field_assists=assists,
        )

    def delete_selected(self) -> None:
        if not self.selected_id:
            return
        item = self.project.find(self.selected_id)
        if item is None:
            return
        tag = item.fields.get("tag", "").strip() or "device"
        self._push_undo()
        self.project.items = [other for other in self.project.items if other.id != item.id]
        self.selected_id = None
        self.dirty = True
        self._refresh_all(f"Removed {tag}")

    def new_build_with_ai(self) -> None:
        """Interview → confirm devices → fill wiring/I/O → save → schematics → programming."""
        if not self._confirm_discard():
            return
        start = ask_choice(
            self,
            self.fonts,
            "New build with AI",
            "This walks interview → confirm recommended devices → fill wiring and PLC fields → "
            "save the cabinet file → generate layout + power + control schematics → "
            "build starter ladder/HMI programming. "
            + AI_BUILD_DISCLAIMER,
            [("go", "Start", "primary"), ("cancel", "Cancel", "")],
        )
        if start != "go":
            return
        self._ai_build_active = True
        self._guide_queue.clear()

        if self._ai_build_dialog is None or not self._ai_build_dialog.winfo_exists():
            self._ai_build_dialog = AiBuildDialog(self, self.fonts, self.library, self.standards)
        dialog = self._ai_build_dialog
        dialog.present(dict(self.project.interview))
        self.wait_variable(dialog.done)
        if not dialog.result:
            self._ai_build_active = False
            self._set_status("AI build cancelled.")
            return

        answers = dialog.result["answers"]
        recommendations = dialog.result["recommendations"]
        name = project_name_from_answers(answers)
        project = new_blank_project(name)
        project.interview = interview_from_ai_answers(answers)
        project.subtitle = "AI build — design aid, not a certified UL listing"
        apply_recommendations(self.library, project, recommendations)
        # Enrich every device with wiring / PLC continuity so the cabinet is usable.
        for item in project.items:
            item.fields = enrich_with_wiring_assist(
                self.library,
                self.standards,
                project,
                item.type_id,
                item.fields,
                interview=project.interview,
            )
            self.standards = remember_device_fields(
                project,
                self.standards,
                type_id=item.type_id,
                fields=item.fields,
                interview=project.interview,
            )
        self._replace_project(project, None, True, f"AI build placed {len(project.items)} devices.")
        self._ai_build_after_devices()

    def _ai_build_after_devices(self) -> None:
        if not self._ai_build_active:
            return

        nxt = ask_choice(
            self,
            self.fonts,
            "Save cabinet file",
            "Devices, wire numbers, landings, and PLC I/O suggestions are on the panel. "
            "Next: save the complete .cabinet.json file.",
            [("go", "Save", "primary"), ("stop", "Stop here", "")],
        )
        if nxt != "go":
            self._ai_build_active = False
            self._set_status("AI build stopped before save.")
            return
        if not self.save():
            again = ask_choice(
                self,
                self.fonts,
                "Save cancelled",
                "The cabinet was not saved. Try again or stop the AI build?",
                [("go", "Save again", "primary"), ("stop", "Stop here", "")],
            )
            if again != "go" or not self.save():
                self._ai_build_active = False
                self._set_status("AI build stopped; cabinet not saved.")
                return

        nxt = ask_choice(
            self,
            self.fonts,
            "Generate drawings (schematics included)",
            "Next: generate the full drawing package — panel layout plus power and control "
            "schematic sheets. This is a design aid, not a certified UL 508A package.",
            [("go", "Generate schematics", "primary"), ("skip", "Skip drawings", "")],
        )
        if nxt == "go":
            self.generate_drawings()
        else:
            # Still offer once more so schematics are not silently dropped.
            retry = ask_choice(
                self,
                self.fonts,
                "Schematics recommended",
                "Without drawings you will not get layout + power + control schematic SVGs. Generate them now?",
                [("go", "Generate schematics", "primary"), ("skip", "Skip anyway", "")],
            )
            if retry == "go":
                self.generate_drawings()

        nxt = ask_choice(
            self,
            self.fonts,
            "Build starter programming",
            "Next: build starter ladder and HMI text from the devices on this cabinet, "
            "then open Programming. This is cut-and-paste help only — not a live PLC download.",
            [("go", "Build + open", "primary"), ("skip", "Skip", "")],
        )
        if nxt == "go":
            answers = default_design_answers(self.project)
            self.project.program = build_starter_program(self.project, answers)
            self.dirty = True
            self.open_programming()

        self._ai_build_active = False
        self._set_status("AI build finished — cabinet, schematics path, and programming ready.")

    def guide_build(self) -> None:
        self._ai_build_active = False
        self._guide_queue.clear()
        interview = self._interview_dialog()
        interview.present(self.project.interview)
        self.wait_variable(interview.done)
        if interview.result is None:
            return
        self.project.interview = interview.result
        self.dirty = True
        self._refresh_all("Interview saved.")
        plan = self._guide_dialog()
        preview = self._preview_parts()
        plan.present(suggest_layout(self.project.interview), preview, has_items=bool(self.project.items))
        self.wait_variable(plan.done)
        if plan.result is None:
            self._set_status("Interview saved. Guide paused.")
            return
        choice = plan.result
        if choice["apply_layout"]:
            self.apply_layout(choice["layout_id"], confirm=False)
        self._queue_guide(choice["type_ids"])
        self._guide_next()

    def apply_all_ai_suggestions(self) -> None:
        """One click: apply wiring_assist suggestions across every device/field."""
        if not self.project.items:
            ask_choice(
                self,
                self.fonts,
                "Nothing to fill",
                "This cabinet has no devices. Add devices before applying AI suggestions.",
                [("ok", "OK", "primary")],
            )
            return
        choice = ask_choice(
            self,
            self.fonts,
            "Apply all AI suggestions",
            "Fill blank wiring / I/O / continuity fields on every device using "
            "carry-forward context (wire colors, numbers, parent PLC, IPs). "
            "Existing answers stay. Continue?",
            [("go", "Apply all", "primary"), ("cancel", "Cancel", "")],
        )
        if choice != "go":
            return
        self._push_undo()
        self.standards, changed, filled = apply_all_project_suggestions(
            self.project,
            self.library,
            self.standards,
            only_blank=True,
        )
        try:
            save_standards(self.standards, standards_profile_path())
        except OSError:
            pass
        self.dirty = True
        if changed or filled:
            self._refresh_all(
                f"Applied AI suggestions on {changed} device(s); filled {filled} blank field(s)."
            )
        else:
            self._refresh_all("No blank fields needed AI suggestions — everything already set.")

    def ai_suggest(self) -> None:
        if self.selected_id:
            item = self.project.find(self.selected_id)
            if item is None:
                return
            suggestion = suggest_device(
                self.library,
                self.standards,
                self.project,
                item.type_id,
                self.project.interview,
                tag=item.fields.get("tag", ""),
                skip_item_id=item.id,
            )
            equipment = self.library.types[item.type_id]
            initial = {spec.key: item.fields.get(spec.key, "") for spec in equipment.fields}
            initial["nonstandard"] = item.fields.get("nonstandard", "")
            self._open_definition(
                type_id=item.type_id,
                library_id=item.library_id or suggestion.catalog_id,
                heading=f"Suggest {equipment.label.lower()}",
                subheading=suggestion.reason,
                initial=initial,
                mode="edit",
                existing_id=item.id,
                suggestion=suggestion,
            )
            return
        if not any(str(value).strip() for value in self.project.interview.values()):
            self.guide_build()
            return
        present = {item.type_id for item in self.project.items}
        missing = [type_id for type_id in suggest_part_types(self.project.interview) if type_id not in present]
        if not missing:
            self._set_status("Suggested classes are already on the panel.")
            return
        suggestion = suggest_device(
            self.library,
            self.standards,
            self.project,
            missing[0],
            self.project.interview,
            used=used_wire_numbers(self.project),
        )
        equipment = self.library.types[missing[0]]
        self._open_definition(
            type_id=missing[0],
            library_id=suggestion.catalog_id,
            heading=f"Suggest {equipment.label.lower()}",
            subheading=suggestion.reason,
            initial=dict(suggestion.fields),
            mode="add",
            suggestion=suggestion,
        )

    def open_ul508a_review(self) -> None:
        findings = review_ul508a(self.project, self.library, self.standards)
        if self._review is None or not self._review.winfo_exists():
            self._review = ReviewWindow(self, self.fonts)
        self._review.present(findings)

    def _interview_dialog(self) -> InterviewDialog:
        if self._interview is None or not self._interview.winfo_exists():
            self._interview = InterviewDialog(self, self.fonts)
        return self._interview

    def _guide_dialog(self) -> GuidePlanDialog:
        if self._guide_plan is None or not self._guide_plan.winfo_exists():
            self._guide_plan = GuidePlanDialog(self, self.fonts, self.library)
        return self._guide_plan

    def _preview_parts(self) -> list[DeviceSuggestion]:
        used = used_wire_numbers(self.project)
        return [
            suggest_device(
                self.library,
                self.standards,
                self.project,
                type_id,
                self.project.interview,
                used=used,
            )
            for type_id in suggest_part_types(self.project.interview)
        ]

    def _queue_guide(self, type_ids: list[str]) -> None:
        self._guide_queue = []
        for item in self.project.items:
            equipment = self.library.types.get(item.type_id)
            if equipment is None or not is_complete(item.fields, equipment.fields):
                self._guide_queue.append({"mode": "edit", "id": item.id})
        present = {item.type_id for item in self.project.items}
        used = used_wire_numbers(self.project)
        for type_id in type_ids:
            if type_id in present:
                continue
            suggestion = suggest_device(
                self.library,
                self.standards,
                self.project,
                type_id,
                self.project.interview,
                used=used,
            )
            self._guide_queue.append({"mode": "add", "suggestion": suggestion})
            present.add(type_id)

    def _guide_next(self) -> None:
        if not self._guide_queue:
            self._guide_finished()
            return
        step = self._guide_queue.pop(0)
        if step["mode"] == "edit":
            item = self.project.find(step["id"])
            if item is None:
                self._guide_next()
                return
            equipment = self.library.types.get(item.type_id)
            if equipment is None:
                self._guide_next()
                return
            suggestion = suggest_device(
                self.library,
                self.standards,
                self.project,
                item.type_id,
                self.project.interview,
                tag=item.fields.get("tag", ""),
                skip_item_id=item.id,
            )
            initial = {spec.key: item.fields.get(spec.key, "") for spec in equipment.fields}
            initial["nonstandard"] = item.fields.get("nonstandard", "")
            self._open_definition(
                type_id=item.type_id,
                library_id=item.library_id or suggestion.catalog_id,
                heading=f"Define {equipment.label.lower()}",
                subheading=suggestion.reason,
                initial=initial,
                mode="edit",
                existing_id=item.id,
                suggestion=suggestion,
                guide=True,
            )
            return
        suggestion = step["suggestion"]
        equipment = self.library.types[suggestion.type_id]
        self._open_definition(
            type_id=suggestion.type_id,
            library_id=suggestion.catalog_id,
            heading=f"Define {equipment.label.lower()}",
            subheading=suggestion.reason,
            initial=dict(suggestion.fields),
            mode="add",
            suggestion=suggestion,
            guide=True,
        )

    def _guide_closed(self, submitted: bool) -> None:
        if submitted:
            return
        if not self._guide_queue:
            return
        self._guide_queue.clear()
        self._ai_build_active = False
        self._set_status("Guide paused. Guide build will pick up devices that are still open.")

    def _guide_finished(self) -> None:
        if self._ai_build_active:
            self.after(80, self._ai_build_after_devices)
            return
        self._set_status("Guide finished. UL 508A review is ready when you want the checklist.")

    def _remember(
        self,
        type_id: str,
        library_id: str | None,
        fields: dict[str, str],
        suggestion: DeviceSuggestion | None,
    ) -> None:
        if is_special(fields):
            return
        if suggestion is None and library_id:
            catalog = self.library.catalog_by_id.get(library_id)
            if catalog is not None:
                suggestion = DeviceSuggestion(
                    type_id=type_id,
                    catalog_id=library_id,
                    stock=library_id in self.standards.stock_catalog_ids,
                    reason="",
                    wire_role="",
                    fields={"catalog": catalog.catalog},
                )
        updated = remember_acceptance(
            self.standards,
            type_id=type_id,
            library_id=library_id,
            fields=fields,
            suggestion=suggestion,
        )
        self.standards = updated
        try:
            save_standards(updated, standards_profile_path())
        except OSError:
            return

    def generate_drawings(self) -> None:
        if not self.project.items:
            ask_choice(
                self,
                self.fonts,
                "Nothing to draw",
                "This cabinet has no devices. Place devices before generating drawings.",
                [("ok", "OK", "primary")],
            )
            self._set_status("No drawings written. The cabinet is empty.")
            return
        folder = default_drawings_folder(self.project, self.path)
        try:
            written = write_drawings(self.project, self.library, folder, selected_id=self.selected_id)
        except DrawingError as exc:
            ask_choice(self, self.fonts, "Drawings", str(exc), [("ok", "OK", "primary")])
            self._set_status(str(exc))
            return
        except OSError as exc:
            ask_choice(self, self.fonts, "Could not write drawings", str(exc), [("ok", "OK", "primary")])
            return
        self._last_drawing_paths = list(written)
        self._set_status(f"Drawings written to {folder}")
        choice = ask_choice(
            self,
            self.fonts,
            "Drawings written",
            f"Wrote the full drawing package (layout + power + control schematics) ({len(written)} SVG files) to {folder}.",
            [("view", "View drawings", "primary"), ("ok", "OK", "")],
        )
        if choice == "view":
            self.view_drawings()

    def view_drawings(self) -> None:
        if not self.project.items:
            ask_choice(
                self,
                self.fonts,
                "Nothing to view",
                "This cabinet has no devices. Add devices and generate drawings first.",
                [("ok", "OK", "primary")],
            )
            self._set_status("No drawings to view. The cabinet is empty.")
            return
        if not (self.project.interview or {}).get("enclosure_selection") and not (
            getattr(self.project, "enclosure_catalog", "") or ""
        ).strip():
            from cabinet_studio.services.ai_build import suggest_enclosure_for

            self._push_undo()
            picked = suggest_enclosure_for(self.library, self.project)
            if picked:
                self._last_drawing_paths = []
                self._set_status(f"AI picked the enclosure: {picked} (Undo to go back).")
            else:
                self.undo_stack.pop()
        sheets = build_sheets(self.project, self.library, selected_id=self.selected_id)
        if not sheets:
            ask_choice(
                self,
                self.fonts,
                "Nothing to view",
                "This cabinet has no devices. Add devices before viewing drawings.",
                [("ok", "OK", "primary")],
            )
            return
        paths = list(self._last_drawing_paths)
        if not paths:
            folder = default_drawings_folder(self.project, self.path)
            try:
                paths = write_drawings(self.project, self.library, folder, selected_id=self.selected_id)
                self._last_drawing_paths = list(paths)
            except (DrawingError, OSError) as exc:
                ask_choice(self, self.fonts, "Drawings", str(exc), [("ok", "OK", "primary")])
                return
        if self._drawing_viewer is not None:
            try:
                if self._drawing_viewer.winfo_exists():
                    self._drawing_viewer.destroy()
            except Exception:
                pass
        self._drawing_viewer = DrawingViewer(
            self,
            self.fonts,
            self.project,
            self.library,
            paths=paths,
            sheets=sheets,
            edit_hook=self._drawing_layout_edit,
        )
        self._set_status(f"Viewing {len(sheets)} drawing sheet(s).")

    def _drawing_layout_edit(self, apply, message: str) -> None:
        """Drawing viewer edits (drag, reset, copy/paste/delete/add): undoable, saved with the project."""
        self._push_undo()
        apply()
        self._last_drawing_paths = []
        if self.selected_id and self.project.find(self.selected_id) is None:
            self.selected_id = None
        self.dirty = True
        self._refresh_all(message + " Save to keep it.")

    def open_hmi_editor(self) -> None:
        from cabinet_studio.ui.hmi_editor import open_hmi_editor

        existing = getattr(self, "_hmi_editor", None)
        if existing is not None and getattr(existing, "project", None) is not self.project:
            existing = None
        self._hmi_editor = open_hmi_editor(self, self.fonts, self.project, edit_hook=self._drawing_layout_edit,
                                           existing=existing)
        self._set_status("HMI editor open for this cabinet.")

    def install_desktop_shortcut(self) -> None:
        try:
            path = create_desktop_shortcut()
        except OSError as exc:
            ask_choice(
                self,
                self.fonts,
                "Desktop shortcut",
                f"Could not create the desktop shortcut.\n{exc}",
                [("ok", "OK", "primary")],
            )
            self._set_status(f"Desktop shortcut failed: {exc}")
            return
        ask_choice(
            self,
            self.fonts,
            "Desktop shortcut",
            f"Shortcut ready:\n{path}",
            [("ok", "OK", "primary")],
        )
        self._set_status(f"Desktop shortcut created at {path}")

    def open_programming(self) -> None:
        if self._programming_viewer is not None:
            try:
                if self._programming_viewer.winfo_exists():
                    self._programming_viewer.destroy()
            except Exception:
                pass

        def on_change(status: str) -> None:
            self.dirty = True
            self._update_title()
            self._set_status(status)

        self._programming_viewer = ProgrammingViewer(self, self.fonts, self.project, on_change)
        self._set_status("Programming open for this cabinet.")

    def open_programs(self) -> None:
        ProgramBrowser(self, self.fonts, self._set_status)

    def _slug(self) -> str:
        cleaned = "".join(
            character if character.isalnum() or character in "-_" else "-"
            for character in self.project.name.strip().lower()
        )
        return cleaned.strip("-") or "cabinet"

    def _on_close(self) -> None:
        if not self._confirm_discard():
            return
        self.destroy()
