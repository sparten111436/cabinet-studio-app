"""Left rail: project commands, templates, and the equipment library."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio import __version__
from cabinet_studio.models.schema import Library
from cabinet_studio.ui.theme import (
    BORDER,
    CYAN,
    ENTRY,
    HOVER,
    MUTED,
    ORANGE,
    PANEL,
    RAISED,
    RAIL_WIDTH,
    TEXT,
    ghost_button,
    primary_button,
    scroll_frame,
    section_label,
)
from cabinet_studio.ui.util import bind_deep


class LibraryRail(ctk.CTkFrame):
    def __init__(self, master, fonts, library: Library, commands: dict) -> None:
        # No fixed height — pack(fill="y") from main_window owns the rail height.
        # A fixed 640px + pack_propagate(False) clipped sticky OUTPUT buttons.
        super().__init__(master, width=RAIL_WIDTH, fg_color=PANEL, corner_radius=0)
        self.pack_propagate(False)
        self.fonts = fonts
        self.library = library
        self.commands = commands
        self._selected_catalog_id: str | None = None
        footer = ctk.CTkLabel(
            self,
            text=f"v{__version__}   ·   define as you go",
            font=fonts.tiny,
            text_color=MUTED,
            anchor="w",
        )
        footer.pack(side="bottom", fill="x", padx=14, pady=(0, 8))
        # Keep add actions visible while the library list scrolls.
        self.actions = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        self.actions.pack(side="bottom", fill="x", padx=12, pady=(0, 4))
        # Always-visible OUTPUT: Drawings / View drawings / Programming — never scroll away.
        self.output = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        self.output.pack(side="top", fill="x")
        self.body = scroll_frame(self)
        self.body.pack(side="top", fill="both", expand=True)
        self._build()

    def _build(self) -> None:
        # Scrollable: PROJECT / DEVICES / stubs / shortcut / review / templates / catalog.
        # Sticky (self.output): Drawings, View drawings, Programming only.
        host = self.body
        section_label(host, "PROJECT", self.fonts.tiny).pack(anchor="w", padx=12, pady=(12, 6))
        primary_button(
            host, "New build with AI", self.commands["new_build_ai"], self.fonts.small, width=252
        ).pack(fill="x", padx=12, pady=(0, 4))
        row = ctk.CTkFrame(host, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 4))
        ghost_button(row, "Open", self.commands["open"], self.fonts.small, width=120).pack(
            side="left", padx=(0, 6)
        )
        primary_button(row, "Save", self.commands["save"], self.fonts.small, width=120).pack(side="left")
        ghost_button(host, "Save as", self.commands["save_as"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(4, 2)
        )
        ghost_button(host, "New", self.commands["new"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(4, 2)
        )
        section_label(host, "DEVICES", self.fonts.tiny).pack(anchor="w", padx=12, pady=(14, 6))
        primary_button(host, "Guide build", self.commands["guide"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(0, 4)
        )
        ghost_button(host, "AI suggest", self.commands["suggest"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(0, 4)
        )
        ghost_button(
            host,
            "Apply all AI suggestions",
            self.commands["apply_all_suggestions"],
            self.fonts.small,
            width=252,
        ).pack(fill="x", padx=12, pady=(0, 4))
        # Sticky OUTPUT at top of rail — Warren sees Programming with no scroll.
        out = self.output
        section_label(out, "OUTPUT", self.fonts.tiny).pack(anchor="w", padx=12, pady=(10, 6))
        primary_button(out, "Drawings", self.commands["drawings"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(0, 2)
        )
        ghost_button(out, "View drawings", self.commands["view_drawings"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(4, 2)
        )
        primary_button(out, "Programming", self.commands["programming"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(4, 2)
        )
        self.hmi_btn = primary_button(out, "HMI editor", self.commands["hmi_editor"], self.fonts.small, width=252)
        self.hmi_btn.pack(fill="x", padx=12, pady=(4, 8))
        from cabinet_studio.ui.hover_tip import attach as attach_tip

        attach_tip(self.hmi_btn, "Design the operator touch screen (HMI) for this cabinet: buttons, lights and "
                                 "numbers tied to the PLC tags. Changes are saved with the project.", "HMI editor")
        ghost_button(host, "Program stubs", self.commands["programs"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(10, 2)
        )
        ghost_button(
            host, "Desktop shortcut", self.commands["desktop_shortcut"], self.fonts.small, width=252
        ).pack(fill="x", padx=12, pady=(4, 8))
        section_label(self.body, "REVIEW", self.fonts.tiny).pack(anchor="w", padx=12, pady=(14, 6))
        ghost_button(self.body, "UL 508A review", self.commands["ul508a"], self.fonts.small, width=252).pack(
            fill="x", padx=12, pady=(0, 2)
        )
        section_label(self.body, "LAYOUT TEMPLATES", self.fonts.tiny).pack(anchor="w", padx=12, pady=(16, 6))
        for layout in self.library.layouts:
            card = ctk.CTkFrame(self.body, fg_color=RAISED, corner_radius=4, border_width=1, border_color=BORDER)
            card.pack(fill="x", padx=12, pady=4)
            title = ctk.CTkLabel(card, text=layout.name, font=self.fonts.heading, text_color=TEXT, anchor="w")
            title.pack(fill="x", padx=10, pady=(8, 0))
            blurb = ctk.CTkLabel(
                card,
                text=layout.description,
                font=self.fonts.tiny,
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=240,
            )
            blurb.pack(fill="x", padx=10, pady=(2, 8))
            bind_deep(card, "<Button-1>", lambda _event, layout_id=layout.id: self.commands["layout"](layout_id))
        section_label(self.actions, "EQUIPMENT LIBRARY", self.fonts.tiny).pack(anchor="w", pady=(4, 6))
        self.search = ctk.CTkEntry(
            self.actions,
            placeholder_text="Search name, vendor, catalog",
            font=self.fonts.small,
            height=32,
            fg_color=ENTRY,
            border_color=BORDER,
            text_color=TEXT,
            placeholder_text_color=MUTED,
        )
        self.search.pack(fill="x", pady=(0, 6))
        self.search.bind("<KeyRelease>", lambda _event: self._rebuild_catalog())
        type_names = ["All types", *[item.label for item in self.library.type_list()]]
        self.type_var = tk.StringVar(value="All types")
        self._type_ids = {item.label: item.id for item in self.library.type_list()}
        ctk.CTkOptionMenu(
            self.actions,
            values=type_names,
            variable=self.type_var,
            command=lambda _value: self._rebuild_catalog(),
            font=self.fonts.small,
            dropdown_font=self.fonts.small,
            fg_color=ENTRY,
            button_color="#2f6bff",
            button_hover_color="#2457d6",
            dropdown_fg_color=PANEL,
            dropdown_hover_color=HOVER,
            dropdown_text_color=TEXT,
            text_color=TEXT,
            width=252,
            height=32,
            dynamic_resizing=False,
        ).pack(fill="x", pady=(0, 6))
        makers = sorted({item.vendor for item in self.library.catalog},
                        key=lambda v: ({"Allen-Bradley": 0, "Siemens": 1, "Omron": 2}.get(v, 9), v))
        self.maker_var = tk.StringVar(value="All makers")
        self.maker_menu = ctk.CTkOptionMenu(
            self.actions, values=["All makers", *makers], variable=self.maker_var,
            command=lambda _value: self._rebuild_catalog(), font=self.fonts.small, dropdown_font=self.fonts.small,
            fg_color=ENTRY, button_color="#2f6bff", button_hover_color="#2457d6", dropdown_fg_color=PANEL,
            dropdown_hover_color=HOVER, dropdown_text_color=TEXT, text_color=TEXT, width=252, height=32,
            dynamic_resizing=False,
        )
        self.maker_menu.pack(fill="x", pady=(0, 6))
        self.add_btn = primary_button(self.actions, "Add selected", self._add_selected, self.fonts.small, width=252)
        self.add_btn.pack(fill="x", pady=(0, 4))
        ghost_button(
            self.actions,
            "Define a device not listed",
            self.commands["add_type"],
            self.fonts.small,
            width=252,
        ).pack(fill="x", pady=(0, 4))
        section_label(self.body, "STARTER DEVICES", self.fonts.tiny).pack(anchor="w", padx=12, pady=(16, 6))
        self.catalog_host = ctk.CTkFrame(self.body, fg_color="transparent")
        self.catalog_host.pack(fill="x", padx=0, pady=(0, 12))
        self._rebuild_catalog()

    def _add_selected(self) -> None:
        if self._selected_catalog_id:
            self.commands["add_catalog"](self._selected_catalog_id)

    def _rebuild_catalog(self) -> None:
        query = self.search.get().strip().lower()
        type_label = self.type_var.get()
        type_id = None if type_label == "All types" else self._type_ids.get(type_label)
        for child in self.catalog_host.winfo_children():
            child.destroy()
        matches = []
        maker = self.maker_var.get() if "maker_var" in self.__dict__ else "All makers"
        for item in self.library.catalog:
            if type_id and item.type_id != type_id:
                continue
            if maker != "All makers" and item.vendor != maker:
                continue
            equipment = self.library.types[item.type_id]
            haystack = " ".join(
                [item.name, item.vendor, item.catalog, item.summary, item.id, equipment.label, equipment.category]
            ).lower()
            if query and query not in haystack:
                continue
            matches.append((item, equipment))
        visible = {item.id for item, _equipment in matches}
        if self._selected_catalog_id not in visible:
            self._selected_catalog_id = None
        if not matches:
            ctk.CTkLabel(
                self.catalog_host,
                text="No library devices match.",
                font=self.fonts.small,
                text_color=MUTED,
                anchor="w",
            ).pack(fill="x", padx=12, pady=6)
        for item, equipment in matches:
            selected = item.id == self._selected_catalog_id
            card = ctk.CTkFrame(
                self.catalog_host,
                fg_color=HOVER if selected else RAISED,
                corner_radius=4,
                border_width=1,
                border_color=CYAN if selected else BORDER,
            )
            card.pack(fill="x", padx=12, pady=3)
            bar = ctk.CTkFrame(card, width=4, fg_color=equipment.accent, corner_radius=0)
            bar.pack(side="left", fill="y")
            bar.pack_propagate(False)
            text = ctk.CTkFrame(card, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True, padx=8, pady=6)
            name = ctk.CTkLabel(text, text=item.name, font=self.fonts.small, text_color=TEXT, anchor="w")
            name.pack(fill="x")
            meta = ctk.CTkLabel(
                text,
                text=f"{equipment.label}  ·  {item.vendor}",
                font=self.fonts.tiny,
                text_color=MUTED,
                anchor="w",
            )
            meta.pack(fill="x")
            catalog = ctk.CTkLabel(
                text,
                text=item.catalog,
                font=self.fonts.tiny,
                text_color=CYAN,
                anchor="w",
            )
            catalog.pack(fill="x")
            bind_deep(card, "<Button-1>", lambda _event, item_id=item.id: self._select(item_id))
            bind_deep(card, "<Double-Button-1>", lambda _event, item_id=item.id: self._select_and_add(item_id))
        self.add_btn.configure(state="normal" if self._selected_catalog_id else "disabled")

    def _select(self, item_id: str) -> None:
        self._selected_catalog_id = item_id
        self._rebuild_catalog()

    def _select_and_add(self, item_id: str) -> None:
        self._selected_catalog_id = item_id
        self.commands["add_catalog"](item_id)
        self._rebuild_catalog()
