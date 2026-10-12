"""Theme-aware ttk.Treeview for the Controller Organizer and Project explorer.

CustomTkinter has no tree widget; ttk's "clam" theme is the only built-in theme
that honours background colours on Windows. No other ttk widgets are used.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from cabinet_studio.ui.theme import BORDER, HOVER, MUTED, PANEL, TEXT, bind_theme_redraw, c

STYLE = "CS.Treeview"


def apply_tree_style(master) -> str:
    style = ttk.Style(master)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    style.configure(
        STYLE, background=c(PANEL), fieldbackground=c(PANEL), foreground=c(TEXT), bordercolor=c(BORDER),
        borderwidth=0, rowheight=24, font=("Segoe UI", 10),
    )
    style.map(STYLE, background=[("selected", c(HOVER))], foreground=[("selected", c(TEXT))])
    style.layout(STYLE, [("Treeview.treearea", {"sticky": "nswe"})])
    return STYLE


def themed_tree(parent, *, height: int = 10) -> ttk.Treeview:
    apply_tree_style(parent)
    tree = ttk.Treeview(parent, style=STYLE, show="tree", selectmode="browse", height=height)
    tree.tag_configure("muted", foreground=c(MUTED))
    tree.tag_configure("folder", font=("Segoe UI", 10, "bold"))

    def on_theme() -> None:
        apply_tree_style(tree)
        tree.tag_configure("muted", foreground=c(MUTED))

    bind_theme_redraw(tree, on_theme)
    return tree


def scrolled_tree(parent, *, height: int = 10) -> tuple[tk.Frame, ttk.Treeview]:
    """Tree plus a CTk scrollbar in a transparent frame (caller packs the frame)."""
    import customtkinter as ctk

    frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
    tree = themed_tree(frame, height=height)
    bar = ctk.CTkScrollbar(frame, command=tree.yview, width=12)
    tree.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    return frame, tree


def node_kind(tree: ttk.Treeview, iid: str) -> str:
    tags = tree.item(iid, "tags") or ()
    for t in tags:
        if str(t).startswith("k:"):
            return str(t)[2:]
    return ""


def node_value(tree: ttk.Treeview, iid: str) -> str:
    values = tree.item(iid, "values") or ()
    return str(values[0]) if values else ""


def all_nodes(tree: ttk.Treeview, parent: str = "") -> list[str]:
    out: list[str] = []
    for iid in tree.get_children(parent):
        out.append(iid)
        out.extend(all_nodes(tree, iid))
    return out
