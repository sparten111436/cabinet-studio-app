"""Controller Organizer: Tasks / routines, tags and the cabinet I/O as a tree.

Read-only view of the program and cabinet JSON. Every action routes through an
existing ProgrammingViewer method (open routine, tag list, cross-reference).
"""

from __future__ import annotations

import customtkinter as ctk

from cabinet_studio.services.ladder_tools import list_routines, tag_table
from cabinet_studio.services.programming import cabinet_device_tags
from cabinet_studio.ui.shell.treeview import all_nodes, node_kind, node_value, scrolled_tree
from cabinet_studio.ui.theme import MUTED, PANEL, ghost_button, section_label

# Node kinds (stored as a "k:<kind>" tag on every tree item).
KINDS = ("controller", "folder", "routine", "tags", "tag", "io_folder", "io_point")


def _io_group(device: dict) -> str:
    direction = (device.get("io_direction") or "").strip().lower()
    if direction.startswith(("in", "di", "ai")):
        return "in"
    if direction.startswith(("out", "do", "ao")):
        return "out"
    return "other"


class ControllerOrganizer(ctk.CTkFrame):
    def __init__(self, master, viewer) -> None:
        super().__init__(master, fg_color=PANEL, corner_radius=0)
        self.viewer = viewer
        fonts = viewer.fonts
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=6, pady=(6, 2))
        section_label(head, "CONTROLLER ORGANIZER", fonts.tiny).pack(side="left", padx=4)
        self.collapse_btn = ghost_button(head, "◀", lambda: viewer._set_pane_visible("organizer", False),
                                         fonts.tiny, width=28)
        self.collapse_btn.pack(side="right")
        frame, self.tree = scrolled_tree(self, height=18)
        frame.pack(fill="both", expand=True, padx=(4, 0), pady=(0, 4))
        self.hint = ctk.CTkLabel(self, text="Click a routine or tag; double-click an I/O point.",
                                 font=fonts.tiny, text_color=MUTED, anchor="w", justify="left", wraplength=200)
        self.hint.pack(fill="x", padx=8, pady=(0, 6))
        self._sig = None
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Double-1>", lambda _e: self._on_double())
        self.refresh()

    # -- content -------------------------------------------------------------

    def _signature(self):
        program = self.viewer.program
        devices = cabinet_device_tags(self.viewer.project)
        return (
            self.viewer.project.name,
            tuple(list_routines(program)),
            tuple(sorted(r["name"] for r in tag_table(program, devices))),
            tuple((d["tag"], d.get("io_direction", ""), d.get("io_address", "")) for d in devices),
        )

    def refresh(self, force: bool = False) -> None:
        try:
            sig = self._signature()
        except Exception:
            return
        if sig == self._sig and not force:
            return
        self._sig = sig
        tree = self.tree
        opened = {iid for iid in all_nodes(tree) if tree.item(iid, "open")}
        selected = tree.selection()
        tree.delete(*tree.get_children())
        program = self.viewer.program
        devices = cabinet_device_tags(self.viewer.project)
        device_tags = {d["tag"] for d in devices}

        def add(parent, iid, text, kind, value="", open_=None, tags=()):
            is_open = (iid in opened) if open_ is None else (open_ or iid in opened)
            tree.insert(parent, "end", iid=iid, text=text, values=(value,), open=is_open,
                        tags=(f"k:{kind}", *tags))

        add("", "ctrl", f"Controller  {self.viewer.project.name or 'Cabinet'}", "controller", open_=True,
            tags=("folder",))
        add("ctrl", "tasks", "Tasks", "folder", open_=True, tags=("folder",))
        add("tasks", "maintask", "MainTask", "folder", open_=True)
        add("maintask", "mainprog", "MainProgram", "folder", open_=True)
        add("mainprog", "r:Main", "MainRoutine", "routine", "Main")
        for name in list_routines(program):
            if name != "Main":
                add("mainprog", f"r:{name}", name, "routine", name)
        add("ctrl", "ctags", "Controller Tags", "tags", "controller", tags=("folder",))
        for tag in sorted(device_tags, key=str.lower):
            add("ctags", f"ct:{tag}", tag, "tag", tag)
        add("ctrl", "ptags", "Program Tags", "tags", "program", tags=("folder",))
        rows = tag_table(program, devices)
        for name in sorted({r["name"] for r in rows} - device_tags, key=str.lower):
            add("ptags", f"pt:{name}", name, "tag", name)
        add("ctrl", "io", "I/O Configuration", "io_folder", open_=True, tags=("folder",))
        groups = {"in": "Inputs", "out": "Outputs", "other": "Other devices"}
        for key, label in groups.items():
            add("io", f"io:{key}", label, "io_folder", open_=True)
        for d in sorted(devices, key=lambda d: d["tag"].lower()):
            addr = d.get("io_address") or ""
            text = d["tag"] + (f"   {addr}" if addr else "")
            add(f"io:{_io_group(d)}", f"iop:{d['tag']}", text, "io_point", d["tag"],
                tags=() if addr else ("muted",))
        for iid in selected:
            if tree.exists(iid):
                tree.selection_set(iid)

    # -- actions -------------------------------------------------------------

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if sel:
            self.open_node(sel[0])

    def _on_double(self) -> None:
        iid = self.tree.focus() or (self.tree.selection() or ("",))[0]
        if iid:
            self.open_node(iid, double=True)

    def open_node(self, iid: str, *, double: bool = False) -> str:
        """Run the node's action (same as clicking it); returns the node kind."""
        v = self.viewer
        kind = node_kind(self.tree, iid)
        value = node_value(self.tree, iid)
        if kind == "routine":
            v.open_routine(value)
        elif kind == "tags":
            v._open_tag_list()
            v.status.configure(text=f"{'Controller' if value == 'controller' else 'Program'} tags — "
                                    "edit descriptions in the tag view.")
        elif kind == "tag":
            v.show_tag(value)
        elif kind == "io_point":
            if double:
                v.show_tag(value)
            else:
                v.status.configure(text=v.io_point_text(value))
        elif double and self.tree.get_children(iid):
            self.tree.item(iid, open=not self.tree.item(iid, "open"))
        return kind

    def nodes_by_kind(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for iid in all_nodes(self.tree):
            out.setdefault(node_kind(self.tree, iid), []).append(iid)
        return out
