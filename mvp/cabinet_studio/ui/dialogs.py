"""Small modal dialogs. Each one is a Toplevel of the main window."""

from __future__ import annotations

import customtkinter as ctk

from cabinet_studio.models.schema import Library
from cabinet_studio.ui.theme import (
    BG,
    BLUE,
    BLUE_HOVER,
    BORDER,
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
from cabinet_studio.ui.util import bind_deep, center_on_parent


class ChoiceDialog(ctk.CTkToplevel):
    def __init__(self, master, fonts, title: str, message: str, choices: list[tuple[str, str, str]]) -> None:
        super().__init__(master, fg_color=BG)
        self.result: str | None = None
        self.title(title)
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        center_on_parent(self, 460, 220, master)
        ctk.CTkLabel(self, text=title, font=fonts.heading, text_color=ORANGE, anchor="w").pack(
            fill="x", padx=20, pady=(18, 8)
        )
        ctk.CTkLabel(
            self,
            text=message,
            font=fonts.body,
            text_color=TEXT,
            wraplength=410,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 16))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 16))
        for value, label, kind in choices:
            button = primary_button if kind == "primary" else ghost_button
            button(row, label, lambda chosen=value: self._choose(chosen), fonts.body, width=120).pack(
                side="right", padx=6
            )
        self.bind("<Escape>", lambda _event: self._cancel())
        self.after(20, self._arm)

    def _arm(self) -> None:
        try:
            self.lift()
            self.grab_set()
            self.focus_force()
        except Exception:
            return

    def _choose(self, value: str) -> None:
        self.result = value
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def ask_choice(master, fonts, title: str, message: str, choices: list[tuple[str, str, str]]) -> str | None:
    dialog = ChoiceDialog(master, fonts, title, message, choices)
    master.wait_window(dialog)
    return dialog.result


class NewProjectDialog(ctk.CTkToplevel):
    def __init__(self, master, fonts, library: Library, on_create) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.library = library
        self.on_create = on_create
        self._by_name = {layout.name: layout for layout in library.layouts}
        self.title("New cabinet")
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._close)
        center_on_parent(self, 520, 350, master)
        section_label(self, "NEW CABINET", fonts.tiny).pack(anchor="w", padx=20, pady=(18, 6))
        ctk.CTkLabel(self, text="Project name", font=fonts.small, text_color=MUTED, anchor="w").pack(
            fill="x", padx=20
        )
        self.name = ctk.CTkEntry(
            self,
            font=fonts.body,
            height=34,
            fg_color=PANEL,
            border_color=BORDER,
            text_color=TEXT,
        )
        self.name.insert(0, "Untitled cabinet")
        self.name.pack(fill="x", padx=20, pady=(4, 12))
        ctk.CTkLabel(self, text="Starting layout", font=fonts.small, text_color=MUTED, anchor="w").pack(
            fill="x", padx=20
        )
        names = ["Blank panel", *[layout.name for layout in library.layouts]]
        self.choice = ctk.StringVar(value=names[1] if len(names) > 1 else names[0])
        ctk.CTkOptionMenu(
            self,
            values=names,
            variable=self.choice,
            command=self._show_blurb,
            font=fonts.body,
            dropdown_font=fonts.small,
            fg_color=PANEL,
            button_color=BLUE,
            button_hover_color=BLUE_HOVER,
            dropdown_fg_color=PANEL,
            dropdown_hover_color=HOVER,
            dropdown_text_color=TEXT,
            text_color=TEXT,
            width=440,
            height=34,
        ).pack(fill="x", padx=20, pady=(4, 8))
        self.blurb = ctk.CTkLabel(
            self,
            text="",
            font=fonts.small,
            text_color=MUTED,
            wraplength=430,
            justify="left",
            anchor="w",
        )
        self.blurb.pack(fill="x", padx=20, pady=(0, 12))
        self._show_blurb(self.choice.get())
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(4, 16))
        primary_button(row, "Create", self._create, fonts.body, width=120).pack(side="right", padx=6)
        ghost_button(row, "Cancel", self._close, fonts.body, width=100).pack(side="right", padx=6)
        self.template_button = ghost_button(row, "Start from a template…", self._from_template, fonts.small,
                                            width=170)
        self.template_button.pack(side="left", padx=6)
        from cabinet_studio.ui.hover_tip import attach as attach_tip

        attach_tip(self.template_button, "Open the template gallery: complete starter cabinets with parts, wiring, "
                   "PLC I/O, a working ladder and an HMI.", "Start from a template")
        self.bind("<Escape>", lambda _event: self._close())
        self.after(20, self._arm)

    def _from_template(self) -> None:
        from cabinet_studio.ui.starter_gallery import open_starter_gallery

        master = self.master
        self.destroy()
        open_starter_gallery(master, confirmed=True)

    def _show_blurb(self, name: str) -> None:
        layout = self._by_name.get(name)
        text = (
            layout.description
            if layout is not None
            else "Empty elevation. Add devices from the library and define each one."
        )
        self.blurb.configure(text=text)

    def _create(self) -> None:
        name = self.name.get().strip() or "Untitled cabinet"
        layout = self._by_name.get(self.choice.get())
        layout_id = None if layout is None else layout.id
        self.on_create(name, layout_id)
        self.destroy()

    def _close(self) -> None:
        self.destroy()

    def _arm(self) -> None:
        try:
            self.lift()
            self.grab_set()
            self.name.focus_set()
        except Exception:
            return


class TypePicker(ctk.CTkToplevel):
    """Pick an equipment class, then the wizard asks the questions for that class."""

    def __init__(self, master, fonts, library: Library, on_pick) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.on_pick = on_pick
        self.title("Device class")
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        center_on_parent(self, 420, 640, master)
        section_label(self, "DEVICE CLASS", fonts.tiny).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            self,
            text="Anything the PLC supervises gets a definition.",
            font=fonts.small,
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 8))
        host = ctk.CTkScrollableFrame(
            self,
            fg_color=BG,
            scrollbar_button_color=TRACK,
            scrollbar_button_hover_color=ORANGE,
            corner_radius=0,
            width=390,
            height=520,
        )
        host.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        current = None
        for equipment in library.type_list():
            if equipment.category != current:
                current = equipment.category
                ctk.CTkLabel(
                    host,
                    text=current.upper(),
                    font=fonts.tiny,
                    text_color=ORANGE,
                    anchor="w",
                ).pack(fill="x", padx=8, pady=(10, 2))
            row = ctk.CTkFrame(host, fg_color=PANEL, corner_radius=4)
            row.pack(fill="x", padx=8, pady=3)
            bar = ctk.CTkFrame(row, width=4, height=28, fg_color=equipment.accent, corner_radius=0)
            bar.pack(side="left", fill="y", padx=(0, 8))
            bar.pack_propagate(False)
            label = ctk.CTkLabel(
                row,
                text=equipment.label,
                font=fonts.body,
                text_color=TEXT,
                anchor="w",
            )
            label.pack(side="left", fill="x", expand=True, pady=6)
            bind_deep(row, "<Button-1>", lambda _event, type_id=equipment.id: self._pick(type_id))
        self.withdraw()

    def _pick(self, type_id: str) -> None:
        self.on_pick(type_id)
        self.close()

    def close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.withdraw()

    def open(self) -> None:
        self.deiconify()
        self.lift()
        self.after(20, self._arm)

    def _arm(self) -> None:
        try:
            if not self.winfo_viewable():
                return
            self.lift()
            self.grab_set()
        except Exception:
            return
