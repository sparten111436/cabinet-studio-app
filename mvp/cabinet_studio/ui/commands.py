"""Command registry (v0.3.22).

Every menu entry and toolbar button is a registered ``Command``. Menus are built
from ``menu_path`` ("Simulate" or "View/Theme"); toolbar buttons carry
``_cs_command_id`` so the UI gate can find and click them. ``invoke(id)`` runs a
command exactly like its menu entry or button does.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable

import customtkinter as ctk


@dataclass
class Command:
    id: str
    label: str
    callback: Callable[[], object]
    menu_path: str | None = None
    shortcut: str = ""
    tooltip: str = ""
    enabled_fn: Callable[[], bool] | None = None
    kind: str = "command"  # "command" | "check" | "radio"
    variable: tk.Variable | None = None
    value: object = None

    def enabled(self) -> bool:
        if self.enabled_fn is None:
            return True
        try:
            return bool(self.enabled_fn())
        except Exception:
            return False


@dataclass
class _MenuItem:
    kind: str  # "command" | "separator" | "submenu"
    command_id: str = ""
    name: str = ""


@dataclass
class CommandRegistry:
    commands: dict[str, Command] = field(default_factory=dict)
    _layout: dict[str, list[_MenuItem]] = field(default_factory=dict)
    _top_order: list[str] = field(default_factory=list)
    menus: dict[str, tk.Menu] = field(default_factory=dict)
    menu_index: dict[str, tuple[str, int]] = field(default_factory=dict)
    buttons: list = field(default_factory=list)

    # --- registration ---------------------------------------------------

    def _path(self, path: str) -> None:
        parts = path.split("/")
        for depth in range(len(parts)):
            key = "/".join(parts[: depth + 1])
            if key not in self._layout:
                self._layout[key] = []
                if depth == 0:
                    self._top_order.append(key)
                else:
                    self._layout["/".join(parts[:depth])].append(_MenuItem("submenu", name=key))

    def add(self, cmd_id: str, label: str, callback, *, menu: str | None = None, **kw) -> Command:
        if cmd_id in self.commands:
            raise ValueError(f"duplicate command id {cmd_id!r}")
        cmd = Command(cmd_id, label, callback, menu_path=menu, **kw)
        self.commands[cmd_id] = cmd
        if menu:
            self._path(menu)
            self._layout[menu].append(_MenuItem("command", command_id=cmd_id))
        return cmd

    def separator(self, menu: str) -> None:
        self._path(menu)
        self._layout[menu].append(_MenuItem("separator"))

    def get(self, cmd_id: str) -> Command:
        return self.commands[cmd_id]

    def ids(self) -> list[str]:
        return list(self.commands)

    # --- running ----------------------------------------------------------

    def invoke(self, cmd_id: str):
        """Run a command as its menu entry / button would (check/radio flip their variable)."""
        cmd = self.commands[cmd_id]
        if not cmd.enabled():
            return None
        if cmd.kind == "check" and cmd.variable is not None:
            cmd.variable.set(not bool(cmd.variable.get()))
        elif cmd.kind == "radio" and cmd.variable is not None:
            cmd.variable.set(cmd.value)
        return cmd.callback()

    # --- menus --------------------------------------------------------------

    def build_menubar(self, window) -> tk.Menu:
        """Native tk.Menu bar for window (Windows draws it in the title area)."""
        bar = tk.Menu(window, tearoff=0)
        self.menus = {"": bar}
        self.menu_index = {}
        for top in self._top_order:
            sub = self._build_menu(bar, top)
            bar.add_cascade(label=top, menu=sub, underline=0)
        # Plain Tk configure: CustomTkinter's own configure() does not pass menu= through.
        tk.Misc.configure(window, menu=bar)
        self.refresh()
        return bar

    def _build_menu(self, parent: tk.Menu, path: str) -> tk.Menu:
        menu = tk.Menu(parent, tearoff=0)
        self.menus[path] = menu
        for item in self._layout.get(path, []):
            if item.kind == "separator":
                menu.add_separator()
            elif item.kind == "submenu":
                sub = self._build_menu(menu, item.name)
                menu.add_cascade(label=item.name.split("/")[-1], menu=sub)
            else:
                cmd = self.commands[item.command_id]
                opts = {"label": cmd.label, "command": lambda i=cmd.id: self._from_menu(i)}
                if cmd.shortcut:
                    opts["accelerator"] = cmd.shortcut
                if cmd.kind == "check" and cmd.variable is not None:
                    menu.add_checkbutton(variable=cmd.variable, **opts)
                elif cmd.kind == "radio" and cmd.variable is not None:
                    menu.add_radiobutton(variable=cmd.variable, value=cmd.value, **opts)
                else:
                    menu.add_command(**opts)
                self.menu_index[cmd.id] = (path, menu.index("end"))
        return menu

    def _from_menu(self, cmd_id: str):
        # The menu already flipped a check / radio variable; only run the callback.
        cmd = self.commands[cmd_id]
        if not cmd.enabled():
            return None
        return cmd.callback()

    def menu_entries(self) -> list[tuple[str, int, str]]:
        """(menu path, entry index, command id) for every command entry in every menu."""
        return [(path, idx, cid) for cid, (path, idx) in self.menu_index.items()]

    # --- toolbar buttons -----------------------------------------------------

    def button(self, parent, cmd_id: str, *, text: str | None = None, width: int = 80, primary: bool = False,
               font=None, height: int = 28):
        from cabinet_studio.ui.theme import BLUE, BLUE_HOVER, BORDER, GHOST, GHOST_HOVER, TEXT

        cmd = self.commands[cmd_id]
        btn = ctk.CTkButton(
            parent, text=text or cmd.label, command=lambda i=cmd_id: self.invoke(i), width=width, height=height,
            corner_radius=4, font=font,
            fg_color=BLUE if primary else GHOST, hover_color=BLUE_HOVER if primary else GHOST_HOVER,
            text_color="#ffffff" if primary else TEXT, border_width=0 if primary else 1, border_color=BORDER,
        )
        btn._cs_command_id = cmd_id
        self.buttons.append(btn)
        return btn

    def refresh(self) -> None:
        """Grey out menu entries and buttons whose enabled_fn is False."""
        for cid, (path, idx) in list(self.menu_index.items()):
            menu = self.menus.get(path)
            try:
                menu.entryconfigure(idx, state="normal" if self.commands[cid].enabled() else "disabled")
            except Exception:
                pass
        live = []
        for btn in self.buttons:
            try:
                if not btn.winfo_exists():
                    continue
                cmd = self.commands[btn._cs_command_id]
                btn.configure(state="normal" if cmd.enabled() else "disabled")
                live.append(btn)
            except Exception:
                continue
        self.buttons = live
