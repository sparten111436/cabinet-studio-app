"""Main-window Project explorer + compact library rail (v0.3.23).

Installed from ``main_shell.install_main_shell``; adds widgets beside the library
rail and wraps ``_refresh_all`` on the instance. The rail's sticky OUTPUT section
(Drawings / View drawings / Programming) is never hidden: compact mode only
hides the scrolling library body and its add actions.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.services.programming import cabinet_device_tags
from cabinet_studio.ui.prefs import load_pref, load_width, save_pref
from cabinet_studio.ui.shell.treeview import all_nodes, node_kind, node_value, scrolled_tree
from cabinet_studio.ui.theme import (
    BORDER,
    MUTED,
    PANEL,
    RAIL_WIDTH,
    bind_theme_redraw,
    c,
    ghost_button,
    section_label,
)

EXPLORER_VISIBLE = "main_explorer_visible"
EXPLORER_WIDTH = "main_explorer_width"
RAIL_COMPACT = "main_rail_compact"
WIDTH_RANGE = (170, 460)
COMPACT_RAIL_WIDTH = 150


class ProjectExplorer(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        width = load_width(EXPLORER_WIDTH, 230, *WIDTH_RANGE)
        super().__init__(master, width=width, fg_color=PANEL, corner_radius=0)
        self.pack_propagate(False)
        self.app = app
        fonts = app.fonts
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=6, pady=(8, 2))
        section_label(head, "PROJECT EXPLORER", fonts.tiny).pack(side="left", padx=4)
        self.collapse_btn = ghost_button(head, "◀", lambda: set_explorer_visible(app, False), fonts.tiny, width=28)
        self.collapse_btn.pack(side="right")
        frame, self.tree = scrolled_tree(self, height=20)
        frame.pack(fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        ctk.CTkLabel(self, text="Click to select · double-click to open", font=fonts.tiny, text_color=MUTED,
                     anchor="w").pack(fill="x", padx=8, pady=(0, 6))
        self._sig = None
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Double-1>", lambda _e: self._on_double())
        self.refresh()

    def _signature(self):
        p = self.app.project
        return (p.name, tuple((i.id, i.type_id, tuple(sorted(i.fields.items()))) for i in p.items),
                bool(p.program and (p.program.get("rungs") or [])), self.app.selected_id)

    def refresh(self, force: bool = False) -> None:
        sig = self._signature()
        if sig == self._sig and not force:
            return
        self._sig = sig
        tree = self.tree
        opened = {iid for iid in all_nodes(tree) if tree.item(iid, "open")}
        tree.delete(*tree.get_children())
        project = self.app.project

        def add(parent, iid, text, kind, value="", open_=False, tags=()):
            tree.insert(parent, "end", iid=iid, text=text, values=(value,), open=open_ or iid in opened,
                        tags=(f"k:{kind}", *tags))

        add("", "cab", f"Cabinet  {project.name or 'Untitled'}", "cabinet", open_=True, tags=("folder",))
        add("cab", "devices", f"Devices ({len(project.items)})", "folder", open_=True, tags=("folder",))
        library = getattr(self.app, "library", None)
        for item in project.items:
            tag = (item.fields.get("tag") or "").strip() or "untagged"
            label = item.type_id
            try:
                label = library.types[item.type_id].label
            except Exception:
                pass
            add("devices", f"dev:{item.id}", f"{tag}   {label}", "device", item.id)
        io = [d for d in cabinet_device_tags(project) if d.get("io_address") or d.get("io_direction")]
        add("cab", "io", f"I/O ({len(io)})", "folder", tags=("folder",))
        by_tag = {(i.fields.get("tag") or "").strip(): i.id for i in project.items}
        for d in io:
            text = "   ".join(p for p in (d["tag"], d.get("io_direction", ""), d.get("io_address", "")) if p)
            add("io", f"io:{d['tag']}", text, "io_point", by_tag.get(d["tag"], ""))
        add("cab", "drawings", "Drawings", "folder", open_=True, tags=("folder",))
        add("drawings", "act:drawings", "Generate drawings", "action", "generate_drawings")
        add("drawings", "act:view_drawings", "View drawings", "action", "view_drawings")
        add("cab", "programs", "Programs", "folder", open_=True, tags=("folder",))
        has_program = bool(project.program and (project.program.get("rungs") or []))
        add("programs", "act:programming", "Programming (ladder)" + ("" if has_program else "  — empty"),
            "action", "open_programming")
        add("programs", "act:programs", "Program library", "action", "open_programs")
        sel = self.app.selected_id
        if sel and tree.exists(f"dev:{sel}"):
            tree.selection_set(f"dev:{sel}")
            tree.see(f"dev:{sel}")

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if sel:
            self.open_node(sel[0])

    def _on_double(self) -> None:
        iid = self.tree.focus() or (self.tree.selection() or ("",))[0]
        if iid:
            self.open_node(iid, double=True)

    def open_node(self, iid: str, *, double: bool = False) -> str:
        app = self.app
        kind = node_kind(self.tree, iid)
        value = node_value(self.tree, iid)
        if kind in {"device", "io_point"} and value:
            if double:
                app.edit_item(value)
            elif app.selected_id != value:
                app.select_item(value)
        elif kind == "action" and double:
            getattr(app, value)()
        elif kind == "action":
            app._set_status(f"Double-click to {self.tree.item(iid, 'text').lower()}.")
        elif double and self.tree.get_children(iid):
            self.tree.item(iid, open=not self.tree.item(iid, "open"))
        return kind

    def nodes_by_kind(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for iid in all_nodes(self.tree):
            out.setdefault(node_kind(self.tree, iid), []).append(iid)
        return out


def _sash(app, explorer: ProjectExplorer) -> tk.Frame:
    sash = tk.Frame(explorer.master, width=5, background=c(BORDER), cursor="sb_h_double_arrow", bd=0,
                    highlightthickness=0)
    bind_theme_redraw(sash, lambda: sash.configure(background=c(BORDER)))
    state = {"x": 0, "w": 0}

    def press(event) -> None:
        state["x"], state["w"] = event.x_root, explorer.winfo_width()

    def drag(event) -> None:
        width = max(WIDTH_RANGE[0], min(WIDTH_RANGE[1], state["w"] + event.x_root - state["x"]))
        explorer.configure(width=width)

    def release(_event) -> None:
        save_pref(EXPLORER_WIDTH, int(explorer.cget("width")))

    sash.bind("<ButtonPress-1>", press)
    sash.bind("<B1-Motion>", drag)
    sash.bind("<ButtonRelease-1>", release)
    return sash


def set_explorer_visible(app, visible: bool, *, save: bool = True) -> None:
    app._explorer_var.set(bool(visible))
    if save:
        save_pref(EXPLORER_VISIBLE, bool(visible))
    explorer, sash = app.project_explorer, app._explorer_sash
    if visible:
        explorer.pack(side="left", fill="y", before=app.rail)
        sash.pack(side="left", fill="y", before=app.rail)
        explorer.refresh(force=True)
    else:
        explorer.pack_forget()
        sash.pack_forget()


def set_rail_compact(app, compact: bool, *, save: bool = True) -> None:
    """Compact rail = sticky OUTPUT (with icons) + footer only; the library body hides."""
    rail = app.rail
    app._rail_compact_var.set(bool(compact))
    if save:
        save_pref(RAIL_COMPACT, bool(compact))
    if compact:
        rail.body.pack_forget()
        rail.actions.pack_forget()
        rail.configure(width=COMPACT_RAIL_WIDTH)
    else:
        rail.configure(width=RAIL_WIDTH)
        rail.actions.pack(side="bottom", fill="x", padx=12, pady=(0, 4), before=rail.output)
        rail.body.pack(side="top", fill="both", expand=True, after=rail.output)


def output_buttons(rail) -> list:
    return [child for child in rail.output.winfo_children() if isinstance(child, ctk.CTkButton)]


def make_pane_vars(app) -> None:
    app._explorer_var = tk.BooleanVar(master=app, value=bool(load_pref(EXPLORER_VISIBLE, True)))
    app._rail_compact_var = tk.BooleanVar(master=app, value=bool(load_pref(RAIL_COMPACT, False)))


def install_project_explorer(app) -> ProjectExplorer:
    if not hasattr(app, "_explorer_var"):
        make_pane_vars(app)
    explorer = ProjectExplorer(app.rail.master, app)
    app.project_explorer = explorer
    app._explorer_sash = _sash(app, explorer)
    original = app._refresh_all

    def refresh_all(status: str | None = None) -> None:
        original(status)
        if explorer.winfo_exists() and app._explorer_var.get():
            explorer.refresh()

    app._refresh_all = refresh_all
    set_explorer_visible(app, app._explorer_var.get(), save=False)
    set_rail_compact(app, app._rail_compact_var.get(), save=False)
    return explorer
