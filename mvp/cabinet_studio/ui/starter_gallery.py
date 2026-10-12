"""Start from a template (v0.3.35): a gallery of starter cabinets.

Each card shows a small drawing, the name, what it is for, a maker and supply choice,
and a Use this template button. Using one builds a NEW unsaved project; the caller
decides how it replaces the open one (after the usual save prompt).
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.models.schema import Library
from cabinet_studio.services.starter_templates import MAKERS, TEMPLATES, StarterTemplate, build_template_project
from cabinet_studio.ui.hover_tip import attach as attach_tip
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
    bind_theme_redraw,
    c,
    ghost_button,
    primary_button,
    section_label,
)
from cabinet_studio.ui.util import center_on_parent

COLUMNS = 3
CARD_WIDTH = 300
USE_TIP = ("Build a new cabinet from this template: parts, wiring, PLC I/O, a working ladder and (where it fits) "
           "an HMI. Your open cabinet is not changed until you save the new one. Everything stays editable.")
MAKER_TIP = "Pick the parts maker. Parts the library has from this maker are swapped in; the rest stay as listed."
SUPPLY_TIP = "The voltage that feeds the cabinet. Motor and power parts follow this choice."
NAME_TIP = "Name for the new cabinet. Leave blank to use the template name."
CLOSE_TIP = "Close the gallery without making a new cabinet."


def _menu(parent, values, variable, fonts, width=136):
    return ctk.CTkOptionMenu(
        parent, values=list(values), variable=variable, font=fonts.small, dropdown_font=fonts.small,
        fg_color=PANEL, button_color=BLUE, button_hover_color=BLUE_HOVER, dropdown_fg_color=PANEL,
        dropdown_hover_color=HOVER, dropdown_text_color=TEXT, text_color=TEXT, width=width, height=28,
    )


def draw_glyph(canvas: tk.Canvas, glyph: str) -> None:
    """A simple cabinet outline with the template's short label (no emoji)."""
    canvas.delete("all")
    canvas.configure(bg=c(PANEL))
    canvas.create_rectangle(4, 4, 60, 52, outline=c(ORANGE), width=2)
    canvas.create_line(10, 14, 54, 14, fill=c(MUTED))
    canvas.create_line(10, 42, 54, 42, fill=c(MUTED))
    canvas.create_text(32, 28, text=glyph, fill=c(TEXT), font=("Segoe UI", 13, "bold"))


class StarterGallery(ctk.CTkToplevel):
    def __init__(self, master, fonts, library: Library, on_use) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.library = library
        self.on_use = on_use
        self.cards: dict[str, dict] = {}
        self.title("Start from a template")
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._close)
        center_on_parent(self, 980, 680, master)
        section_label(self, "START FROM A TEMPLATE", fonts.tiny).pack(anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(
            self, text="Pick a starting cabinet. You get parts, wiring, PLC I/O and a working ladder - then change "
                       "anything. Design aid only, not a certified UL 508A drawing.",
            font=fonts.small, text_color=MUTED, anchor="w", justify="left", wraplength=920,
        ).pack(fill="x", padx=20, pady=(0, 8))
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(top, text="Project name", font=fonts.small, text_color=MUTED).pack(side="left")
        self.name = ctk.CTkEntry(top, font=fonts.body, height=30, width=320, fg_color=PANEL, border_color=BORDER,
                                 text_color=TEXT, placeholder_text="Same as the template")
        self.name.pack(side="left", padx=8)
        attach_tip(self.name, NAME_TIP, "Project name")

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=4)
        for col in range(COLUMNS):
            body.grid_columnconfigure(col, weight=1, uniform="card")
        for index, template in enumerate(TEMPLATES):
            self._card(body, template).grid(row=index // COLUMNS, column=index % COLUMNS, padx=6, pady=6,
                                            sticky="nsew")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(4, 14))
        self.close_button = ghost_button(row, "Close", self._close, fonts.body, width=100)
        self.close_button.pack(side="right", padx=6)
        attach_tip(self.close_button, CLOSE_TIP, "Close")
        self.status = ctk.CTkLabel(row, text="", font=fonts.small, text_color=MUTED, anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=6)
        self.bind("<Escape>", lambda _event: self._close())
        self.after(20, self._arm)

    def _card(self, parent, template: StarterTemplate) -> ctk.CTkFrame:
        fonts = self.fonts
        card = ctk.CTkFrame(parent, fg_color=PANEL, border_color=BORDER, border_width=1, corner_radius=6)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(10, 4))
        canvas = tk.Canvas(head, width=64, height=56, highlightthickness=0)
        canvas.pack(side="left")
        draw_glyph(canvas, template.glyph)
        bind_theme_redraw(canvas, lambda cv=canvas, g=template.glyph: draw_glyph(cv, g))
        ctk.CTkLabel(head, text=template.name, font=fonts.body, text_color=TEXT, anchor="w", justify="left",
                     wraplength=CARD_WIDTH - 90).pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkLabel(card, text=template.summary, font=fonts.small, text_color=TEXT, anchor="w", justify="left",
                     wraplength=CARD_WIDTH - 20).pack(fill="x", padx=10)
        ctk.CTkLabel(card, text="Use it for: " + template.when, font=fonts.small, text_color=MUTED, anchor="w",
                     justify="left", wraplength=CARD_WIDTH - 20).pack(fill="x", padx=10, pady=(4, 6))
        pick = ctk.CTkFrame(card, fg_color="transparent")
        pick.pack(fill="x", padx=10)
        maker_var = tk.StringVar(master=self, value=MAKERS[0])
        supply_var = tk.StringVar(master=self, value=template.default_supply)
        maker = _menu(pick, MAKERS, maker_var, fonts)
        maker.pack(side="left")
        attach_tip(maker, MAKER_TIP, "Maker")
        supply = _menu(pick, template.supplies, supply_var, fonts, width=128)
        supply.pack(side="left", padx=(6, 0))
        attach_tip(supply, SUPPLY_TIP, "Supply voltage")
        button = primary_button(card, "Use this template", lambda tid=template.id: self.use(tid), fonts.small,
                                width=160)
        button.pack(anchor="e", padx=10, pady=(8, 10))
        attach_tip(button, USE_TIP, f"Use {template.name}")
        self.cards[template.id] = {"maker": maker, "supply": supply, "maker_var": maker_var,
                                   "supply_var": supply_var, "button": button, "template": template}
        return card

    def use(self, template_id: str):
        card = self.cards[template_id]
        template = card["template"]
        name = self.name.get().strip() or template.name
        try:
            project = build_template_project(template, self.library, maker=card["maker_var"].get(),
                                             supply=card["supply_var"].get(), name=name)
        except Exception as exc:  # a broken template must never close the app
            self.status.configure(text=f"Could not build {template.name}: {exc}")
            return None
        self.on_use(project, template)
        self._close()
        return project

    def _arm(self) -> None:
        try:
            self.lift()
            self.grab_set()
            self.focus_force()
        except Exception:
            return

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


def open_starter_gallery(app, *, confirmed: bool = False) -> StarterGallery | None:
    """Open the gallery from the main window. Asks to save the open cabinet first (unless already asked)."""
    if not confirmed and not app._confirm_discard():
        return None

    def on_use(project, template) -> None:
        app._replace_project(project, None, True,
                             f"Created {project.name} from the {template.name} starter (not saved yet). "
                             "See Notes for what to change first.")

    app.starter_gallery = StarterGallery(app, app.fonts, app.library, on_use)
    return app.starter_gallery
