"""In-app viewer for generated drawing sheets.

Tk cannot render SVG natively. This viewer redraws the same Sheet model
onto a Canvas (prev/next, scrollable). Hover popups match Programming:
device type, tag, wires, color, gauge, FROM-TO, I/O, callout. On-canvas
text stays sparse (tags / rails); dense callout and wire-ref details live
in the popup. Shop-print SVGs still carry full text via Open in browser.
"""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path

import customtkinter as ctk
import tkinter as tk

from cabinet_studio.models.project import Project
from cabinet_studio.services import drawings as _dw
from cabinet_studio.services.drawings import (
    PAGE_H,
    PAGE_W,
    Sheet,
    box_hover_detail,
    build_sheets,
    render_svg,
)
from cabinet_studio.models.schema import Library
from cabinet_studio.ui.theme import (
    BG,
    BORDER,
    CYAN,
    HOVER,
    MUTED,
    ORANGE,
    PANEL,
    TEXT,
    TIP_BG,
    TIP_BORDER,
    TIP_TEXT,
    bind_theme_redraw,
    c,
    ghost_button,
    primary_button,
    section_label,
)
from cabinet_studio.ui.util import (
    apply_saved_geometry,
    bind_geometry_autosave,
    center_on_parent,
    remember_window_geometry,
)

_DRAW_CANVAS_GEOM_KEY = "drawings_canvas"
_DRAW_CANVAS_MIN = (960, 700)
_DRAW_CANVAS_DEFAULT = (1100, 820)


# Text classes kept on the in-app canvas (shop SVG still has everything).
_SPARSE_SKIP = {
    "fp-label",
    "callout",
    "io-addr",
    "wire-ref",
    "wire-ref-header",
    "outline-callout",
}


class DrawingViewer(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        fonts,
        project: Project,
        library: Library,
        paths: list[Path] | None = None,
        sheets: list[Sheet] | None = None,
        edit_hook=None,
    ) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.project = project
        self.library = library
        # edit_hook(apply_fn, message): the owner snapshots undo, runs apply_fn, marks the project changed.
        self.edit_hook = edit_hook
        self._drag: dict | None = None
        self.selected_key: str | None = None
        self.paths = [Path(p) for p in (paths or [])]
        self.sheets = list(sheets) if sheets else build_sheets(project, library)
        self.index = 0
        self._hover_targets: list[tuple[float, float, float, float, str]] = []
        self._hover_tip: ctk.CTkToplevel | None = None
        self._hover_after: str | None = None
        self._hover_key: str | None = None
        self._draw_scale = 1.0
        self._draw_ox = 0.0
        self._draw_oy = 0.0
        self.title("View drawings")
        self.minsize(960, 720)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.close)
        center_on_parent(self, 1080, 820, master)

        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        header.pack(fill="x", padx=14, pady=(12, 4))
        section_label(header, "DRAWINGS", fonts.tiny).pack(side="left")
        self.meta = ctk.CTkLabel(header, text="", font=fonts.small, text_color=CYAN, anchor="e")
        self.meta.pack(side="right")

        self.hint = ctk.CTkLabel(
            self,
            text="Tags on sheet · hover near a device (large hit area) for type / wires / color / gauge / FROM–TO / I/O / callout. "
            "Shop-print SVG (Open in browser) keeps full labels. NOT A CERTIFIED UL 508A DRAWING.",
            font=fonts.tiny,
            text_color=ORANGE,
            anchor="w",
            justify="left",
            wraplength=1000,
        )
        self.hint.pack(fill="x", padx=14, pady=(0, 6))

        body = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Sheet title list so Power / Control schematics are obvious.
        side = ctk.CTkFrame(body, width=220, fg_color=PANEL, corner_radius=0)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        section_label(side, "SHEETS", fonts.tiny).pack(anchor="w", padx=10, pady=(10, 4))
        self.sheet_list = ctk.CTkScrollableFrame(side, fg_color=PANEL)
        self.sheet_list.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self._sheet_buttons: list = []

        self._body = body
        self._canvas_popout: ctk.CTkToplevel | None = None
        self._canvas_geom_flush = None
        self._canvas_placeholder = ctk.CTkLabel(
            body,
            text="Drawing view popped out — drag that window to another monitor.\n"
            "Sheet list / Previous / Next here still change the sheet. Dock view to return.",
            font=fonts.small,
            text_color=MUTED,
            anchor="center",
            justify="center",
        )
        self._mount_sheet_canvas(body)
        self.canvas_host.pack(side="left", fill="both", expand=True)

        nav = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        nav.pack(fill="x", padx=12, pady=(0, 12))
        ghost_button(nav, "Previous", self.prev_sheet, fonts.body, width=110).pack(side="left", padx=4)
        ghost_button(nav, "Next", self.next_sheet, fonts.body, width=110).pack(side="left", padx=4)
        ghost_button(nav, "Open in browser", self.open_browser, fonts.body, width=140).pack(side="left", padx=8)
        self._popout_btn = ghost_button(
            nav, "Pop out view", self._toggle_canvas_popout, fonts.body, width=120
        )
        self._popout_btn.pack(side="left", padx=8)
        self.hmi_btn = ghost_button(nav, "HMI editor", self.open_hmi_editor, fonts.body, width=110)
        self.hmi_btn.pack(side="left", padx=4)
        from cabinet_studio.ui.hover_tip import attach as _attach_tip

        _attach_tip(self.hmi_btn, "Design the operator touch screen (HMI): answer a few questions or drag buttons, "
                                  "lights and numbers onto the screen. After Save, the HMI screen layout, door cutout "
                                  "and HMI wiring sheets are added to these drawings.", "HMI editor")
        self._hmi_editor = None
        primary_button(nav, "Close", self.close, fonts.body, width=100).pack(side="right", padx=4)
        self.reset_btn = ghost_button(nav, "Reset layout", self.reset_layout, fonts.body, width=120)
        self.reset_btn.pack(side="right", padx=4)
        self.add_btn = ghost_button(nav, "Add part", self._add_part_button, fonts.body, width=100)
        self.add_btn.pack(side="right", padx=4)
        self._clip: dict | None = None
        self.edit_status = ctk.CTkLabel(self, text="", font=fonts.small, text_color=CYAN, anchor="w")
        self.edit_status.pack(fill="x", padx=16, pady=(0, 6), before=nav)
        self.sheet_label = ctk.CTkLabel(nav, text="", font=fonts.body, text_color=TEXT, anchor="w")
        self.sheet_label.pack(side="left", padx=12)

        self.bind("<Left>", lambda _e: self.prev_sheet())
        self.bind("<Right>", lambda _e: self.next_sheet())
        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Control-c>", lambda _e: self.copy_part())
        self.bind("<Control-v>", lambda _e: self.paste_part())
        self.bind("<Delete>", lambda _e: self.delete_part())
        self.after(30, self._arm)
        self._draw()
        bind_theme_redraw(self, self._on_theme)

    def _on_theme(self) -> None:
        self.canvas.configure(background=c("DESK"))
        self._draw()

    def _arm(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            return

    def close(self) -> None:
        self._hide_hover_tip()
        if self._canvas_popout is not None:
            self._dock_sheet_canvas()
        self.destroy()


    def _mount_sheet_canvas(self, parent) -> None:
        """Create sheet canvas + scrollbars under parent (home body or pop-out)."""
        self.canvas_host = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        self.canvas = tk.Canvas(self.canvas_host, background=c("DESK"), highlightthickness=0)
        self.vbar = ctk.CTkScrollbar(self.canvas_host, orientation="vertical", command=self.canvas.yview)
        self.hbar = ctk.CTkScrollbar(self.canvas_host, orientation="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.vbar.pack(side="right", fill="y")
        self.hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._hide_hover_tip)
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", self._context_click)

    def _toggle_canvas_popout(self) -> None:
        if self._canvas_popout is not None:
            self._dock_sheet_canvas()
        else:
            self._pop_out_sheet_canvas()

    def _pop_out_sheet_canvas(self) -> None:
        if self._canvas_popout is not None:
            return
        self._hide_hover_tip()
        try:
            self.canvas_host.pack_forget()
        except Exception:
            pass
        try:
            self.canvas_host.destroy()
        except Exception:
            pass

        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title("Drawing view")
        win.minsize(*_DRAW_CANVAS_MIN)
        # Free-float canvas window — not transient (multi-monitor).
        apply_saved_geometry(
            win,
            _DRAW_CANVAS_GEOM_KEY,
            default_w=_DRAW_CANVAS_DEFAULT[0],
            default_h=_DRAW_CANVAS_DEFAULT[1],
            min_w=_DRAW_CANVAS_MIN[0],
            min_h=_DRAW_CANVAS_MIN[1],
            parent=self,
            center_fallback=True,
        )
        win.protocol("WM_DELETE_WINDOW", self._dock_sheet_canvas)
        self._canvas_popout = win
        self._canvas_geom_flush = bind_geometry_autosave(
            win, _DRAW_CANVAS_GEOM_KEY, min_w=_DRAW_CANVAS_MIN[0], min_h=_DRAW_CANVAS_MIN[1]
        )
        self._mount_sheet_canvas(win)
        self.canvas_host.pack(fill="both", expand=True, padx=8, pady=8)
        try:
            self._canvas_placeholder.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        except Exception:
            pass
        try:
            self._popout_btn.configure(text="Dock view")
        except Exception:
            pass
        self._draw()
        try:
            win.lift()
        except Exception:
            pass

    def _dock_sheet_canvas(self) -> None:
        """Return sheet canvas to the home Drawings window."""
        win = self._canvas_popout
        if win is None:
            return
        self._hide_hover_tip()
        if self._canvas_geom_flush:
            try:
                self._canvas_geom_flush()
            except Exception:
                pass
            self._canvas_geom_flush = None
        else:
            remember_window_geometry(
                win, _DRAW_CANVAS_GEOM_KEY, min_w=_DRAW_CANVAS_MIN[0], min_h=_DRAW_CANVAS_MIN[1]
            )
        self._canvas_popout = None
        try:
            win.destroy()
        except Exception:
            pass
        try:
            self._canvas_placeholder.pack_forget()
        except Exception:
            pass
        self._mount_sheet_canvas(self._body)
        self.canvas_host.pack(side="left", fill="both", expand=True)
        try:
            self._popout_btn.configure(text="Pop out view")
        except Exception:
            pass
        self._draw()

    def prev_sheet(self) -> None:
        if not self.sheets:
            return
        self.index = (self.index - 1) % len(self.sheets)
        self._draw()

    def next_sheet(self) -> None:
        if not self.sheets:
            return
        self.index = (self.index + 1) % len(self.sheets)
        self._draw()

    def open_browser(self) -> None:
        if self.paths:
            target = self.paths[min(self.index, len(self.paths) - 1)]
            webbrowser.open(target.resolve().as_uri())
            return
        if not self.sheets:
            return
        # Write a temp SVG for the current sheet next to any known folder, else cwd.
        folder = self.paths[0].parent if self.paths else Path.cwd() / "drawings-preview"
        folder.mkdir(parents=True, exist_ok=True)
        sheet = self.sheets[self.index]
        path = folder / f"preview-sheet-{sheet.number:02d}.svg"
        path.write_text(render_svg(sheet, self.project), encoding="utf-8")
        webbrowser.open(path.resolve().as_uri())

    def _wheel(self, event) -> None:
        step = -1 if getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step, "units")

    def _rebuild_sheet_list(self) -> None:
        for child in self.sheet_list.winfo_children():
            child.destroy()
        self._sheet_buttons = []
        for i, sheet in enumerate(self.sheets):
            label = f"{sheet.number}. {sheet.title}"
            btn = ghost_button(
                self.sheet_list,
                label,
                lambda idx=i: self._goto(idx),
                self.fonts.tiny,
                width=200,
            )
            if i == self.index:
                btn.configure(fg_color=HOVER, text_color=CYAN)
            btn.pack(fill="x", pady=2)
            self._sheet_buttons.append(btn)

    def _goto(self, index: int) -> None:
        if not self.sheets:
            return
        self.index = max(0, min(index, len(self.sheets) - 1))
        self._draw()

    def _draw(self) -> None:
        self.canvas.delete("all")
        self._hide_hover_tip()
        self._hover_targets = []
        if not self.sheets:
            self.sheet_label.configure(text="No sheets")
            self.meta.configure(text="")
            return
        self._rebuild_sheet_list()
        sheet = self.sheets[self.index]
        self.sheet_label.configure(text=f"{sheet.title}   ·   Sheet {sheet.number} of {sheet.total}")
        self.meta.configure(text=self.project.name)

        width = max(self.canvas.winfo_width(), 100)
        height = max(self.canvas.winfo_height(), 100)
        scale = min((width - 24) / PAGE_W, (height - 24) / PAGE_H, 1.0)
        if scale <= 0:
            scale = 1.0
        pad_x = max(12, (width - PAGE_W * scale) / 2)
        pad_y = 12
        self._draw_scale = scale
        self._draw_ox = pad_x
        self._draw_oy = pad_y

        # White page
        self.canvas.create_rectangle(
            pad_x,
            pad_y,
            pad_x + PAGE_W * scale,
            pad_y + PAGE_H * scale,
            fill="#ffffff",
            outline="#000000",
            width=2,
        )

        svg = render_svg(sheet, self.project)
        self._paint_svg_subset(svg, pad_x, pad_y, scale)
        self._register_hover_targets(sheet, pad_x, pad_y, scale)
        editable = self._editable(sheet)
        if "edit_status" not in self.__dict__:
            return
        schematic = self._schematic_editable(sheet)
        self.reset_btn.configure(state="normal" if editable or schematic else "disabled")
        self.add_btn.configure(state="normal" if editable else "disabled")
        current = self.edit_status.cget("text")
        if not current or current in (self._LAYOUT_HINT, self._SCHEMATIC_HINT):
            hint = self._LAYOUT_HINT if editable else self._SCHEMATIC_HINT if schematic else ""
            self.edit_status.configure(text=hint)
        for box in sheet.boxes:
            if box.key == self.selected_key and editable:
                self.canvas.create_rectangle(pad_x + box.x * scale - 3, pad_y + box.y * scale - 3,
                                             pad_x + (box.x + box.w) * scale + 3,
                                             pad_y + (box.y + box.h) * scale + 3,
                                             outline="#e0301e", width=2, dash=(5, 3))
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    # ------------------------------------------------ v0.3.26 drag parts on layout sheets
    _LAYOUT_HINT = ("Layout sheet: drag any part to move it on the plate. Right-click for "
                    "Copy / Paste here / Delete / Add part. Your spot is saved; "
                    "Reset layout returns to the automatic zones.")
    _SCHEMATIC_HINT = ("Schematic: drag a device up or down to move it to another rung, or "
                       "sideways along its rung; drag rail / voltage text to move it. Wires "
                       "reconnect by themselves. Reset layout puts everything back.")

    def _item(self, key: str):
        return next((i for i in self.project.items if i.id == key), None)

    def _editable(self, sheet: Sheet) -> bool:
        return sheet.kind == "layout" and sheet.panel is not None and any(
            self._item(b.key) is not None for b in sheet.boxes)

    def _schematic_editable(self, sheet: Sheet) -> bool:
        return sheet.kind in {"power", "control"} and any(
            self._item(_dw.schematic_item_id(b)) is not None for b in sheet.boxes)

    def _box_at(self, cx: float, cy: float):
        sheet = self.sheets[self.index] if self.sheets else None
        if sheet is None:
            return None
        schematic = self._schematic_editable(sheet)
        if not schematic and not self._editable(sheet):
            return None
        s, ox, oy = self._draw_scale, self._draw_ox, self._draw_oy
        x, y = (cx - ox) / s, (cy - oy) / s
        for box in reversed(sheet.boxes):
            key = _dw.schematic_item_id(box) if schematic else box.key
            if box.x <= x <= box.x + box.w and box.y <= y <= box.y + box.h and self._item(key) is not None:
                return box
        return None

    def _label_at(self, cx: float, cy: float) -> int | None:
        """Index of the visible rail / voltage text under the pointer on a schematic sheet."""
        sheet = self.sheets[self.index] if self.sheets else None
        if sheet is None or not self._schematic_editable(sheet):
            return None
        s, ox, oy = self._draw_scale, self._draw_ox, self._draw_oy
        x, y = (cx - ox) / s, (cy - oy) / s
        for n, (lx, ly, text) in enumerate(sheet.labels):
            if not _dw._is_structural_run_label(text):
                continue
            if lx - 4 <= x <= lx + len(text) * _dw.FONT_LABEL * 0.6 + 4 and ly - _dw.FONT_LABEL - 2 <= y <= ly + 4:
                return n
        return None

    def _drag_start(self, event) -> None:
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        box = self._box_at(cx, cy)
        self._drag = None
        if box is None:
            label = self._label_at(cx, cy)
            if label is None:
                return
            self._hide_hover_tip()
            lx, ly, text = self.sheets[self.index].labels[label]
            s, ox, oy = self._draw_scale, self._draw_ox, self._draw_oy
            w = len(text) * _dw.FONT_LABEL * 0.6
            ghost = self.canvas.create_rectangle(ox + lx * s, oy + (ly - _dw.FONT_LABEL) * s, ox + (lx + w) * s,
                                                 oy + (ly + 3) * s, outline="#2f6bff", width=2, dash=(4, 3))
            self._drag = {"label": label, "x": cx, "y": cy, "ghost": ghost, "dx": 0.0, "dy": 0.0}
            return
        self._hide_hover_tip()
        self.selected_key = box.key
        s, ox, oy = self._draw_scale, self._draw_ox, self._draw_oy
        ghost = self.canvas.create_rectangle(ox + box.x * s, oy + box.y * s, ox + (box.x + box.w) * s,
                                             oy + (box.y + box.h) * s, outline="#2f6bff", width=2, dash=(4, 3))
        self._drag = {"box": box, "x": cx, "y": cy, "ghost": ghost, "dx": 0.0, "dy": 0.0}

    def _drag_move(self, event) -> None:
        d = self._drag
        if d is None:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.move(d["ghost"], cx - d["x"] - d["dx"], cy - d["y"] - d["dy"])
        d["dx"], d["dy"] = cx - d["x"], cy - d["y"]

    def _drag_end(self, event) -> None:
        d, self._drag = self._drag, None
        if d is None:
            return
        self._drag_move(event)
        if "label" in d:
            self.drop_label(d["label"], d["dx"] / self._draw_scale, d["dy"] / self._draw_scale)
            return
        self.drop(d["box"].key, d["dx"] / self._draw_scale, d["dy"] / self._draw_scale)

    # ------------------------------------------------ v0.3.29 drag devices / text on schematics
    def _sheet_page(self, sheet: Sheet) -> int:
        import re

        m = re.search(r"\((\d+)/\d+\)\s*$", sheet.title)
        return int(m.group(1)) if m else 1

    def drop_label(self, index: int, dx_svg: float, dy_svg: float) -> bool:
        sheet = self.sheets[self.index] if self.sheets else None
        if sheet is None or not self._schematic_editable(sheet) or not (0 <= index < len(sheet.labels)):
            return False
        if abs(dx_svg) < 2 and abs(dy_svg) < 2:
            self._draw()
            return False
        text = sheet.labels[index][2]
        nth = sum(1 for _x, _y, t in sheet.labels[:index] if t == text)
        key = _dw.schematic_label_key(sheet.kind, self._sheet_page(sheet), text, nth)

        def apply() -> None:
            offsets = _dw.schematic_label_offsets(self.project)
            ox, oy = offsets.get(key, [0.0, 0.0])
            offsets[key] = [round(ox + dx_svg, 1), round(oy + dy_svg, 1)]
            self.project.interview[_dw.SCHEMATIC_LABEL_KEY] = json.dumps(offsets)

        self._edit(apply, f"Moved the text '{text}'.")
        return True

    def _drop_schematic(self, sheet: Sheet, box, dx_svg: float, dy_svg: float) -> bool:
        """Slide a device along its rung, or move it to the rung it was dropped on.
        Wires are re-routed from the new box position when the sheets rebuild."""
        kind = sheet.kind
        item = self._item(_dw.schematic_item_id(box))
        if item is None:
            return False
        if abs(dx_svg) < 2 and abs(dy_svg) < 2:
            self.selected_key = box.key
            self.edit_status.configure(text=f"{box.tag} selected - drag it to another rung or along its rung.")
            self._draw()
            return False
        order = [b for s in self.sheets if s.kind == kind for b in s.boxes]
        here = [b for b in sheet.boxes]
        new_y = box.y + dy_svg + box.h / 2.0
        target = min(here, key=lambda b: abs((b.y + b.h / 2.0) - new_y))
        if target.role in {"disconnect", "ground"}:
            target = box
        try:
            old_dx = float(item.fields.get(f"sch_dx_{kind}") or 0.0)
        except (TypeError, ValueError):
            old_dx = 0.0
        low, high = _dw.schematic_dx_limits(box.w)
        new_dx = round(max(low, min(high, old_dx + dx_svg)), 1)
        moves_rung = target is not box
        slides = abs(new_dx - old_dx) >= 2

        def apply() -> None:
            if moves_rung:
                ranked = [b for b in order if b is not box]
                at = ranked.index(target)
                ranked.insert(at + (1 if order.index(box) < order.index(target) else 0), box)
                for n, b in enumerate(ranked):
                    it = self._item(_dw.schematic_item_id(b))
                    if it is not None:
                        it.fields[f"sch_slot_{kind}"] = str(n)
            if slides:
                item.fields[f"sch_dx_{kind}"] = f"{new_dx:g}"

        if not moves_rung and not slides:
            self._draw()
            return False
        what = f"to {target.tag}'s rung" if moves_rung else "along its rung"
        self._edit(apply, f"Moved {box.tag} {what} - the wires reconnected by themselves.")
        return True

    def _reset_schematic(self, sheet: Sheet) -> None:
        kind = sheet.kind
        keys = (f"sch_slot_{kind}", f"sch_dx_{kind}")
        items = [i for i in self.project.items if any(k in i.fields for k in keys)]
        offsets = _dw.schematic_label_offsets(self.project)
        labels = [k for k in offsets if k.startswith(f"{kind}|")]
        if not items and not labels:
            self.edit_status.configure(text="Nothing to reset - this schematic is in its automatic layout.")
            return

        def apply() -> None:
            for i in items:
                for k in keys:
                    i.fields.pop(k, None)
            kept = {k: v for k, v in offsets.items() if k not in labels}
            self.project.interview[_dw.SCHEMATIC_LABEL_KEY] = json.dumps(kept) if kept else ""

        self._edit(apply, f"Schematic reset - {len(items)} device(s) and {len(labels)} text label(s) back in place.")

    def drop(self, key: str, dx_svg: float, dy_svg: float) -> bool:
        """Move a part by (dx, dy) sheet units; snap to the grid, keep it on the plate, refuse overlaps."""
        from cabinet_studio.services.panel_zones import PIN_GRID_IN

        sheet = self.sheets[self.index]
        if self._schematic_editable(sheet):
            box = next((b for b in sheet.boxes if b.key == key), None)
            return box is not None and self._drop_schematic(sheet, box, dx_svg, dy_svg)
        box = next((b for b in sheet.boxes if b.key == key), None)
        item = self._item(key)
        if box is None or item is None or sheet.panel is None:
            return False
        if abs(dx_svg) < 2 and abs(dy_svg) < 2:
            self.edit_status.configure(text=f"{box.tag} selected - drag it to a new spot on the plate.")
            self._draw()
            return False
        px, py, pw, ph = sheet.panel
        bp_w = float(self.project.backplate_width_in or 1)
        f = pw / bp_w
        w_in, h_in = box.w / f, box.h / f
        x_in = round(((box.x + dx_svg) - px) / f / PIN_GRID_IN) * PIN_GRID_IN
        y_in = round(((box.y + dy_svg) - py) / f / PIN_GRID_IN) * PIN_GRID_IN
        x_in = min(max(x_in, 0.0), max(pw / f - w_in, 0.0))
        y_in = min(max(y_in, 0.0), max(ph / f - h_in, 0.0))
        nx, ny = px + x_in * f, py + y_in * f
        for other in sheet.boxes:
            if other.key == key:
                continue
            if not (nx + box.w <= other.x or other.x + other.w <= nx or ny + box.h <= other.y or other.y + other.h <= ny):
                self.edit_status.configure(text=f"Can't drop {box.tag} there - it would overlap {other.tag}.")
                self._draw()
                return False

        def apply() -> None:
            item.fields["layout_x_in"] = f"{x_in:g}"
            item.fields["layout_y_in"] = f"{y_in:g}"

        self._edit(apply, f"Moved {box.tag} to {x_in:g} in, {y_in:g} in from the plate's top-left corner.")
        return True

    def reset_layout(self) -> None:
        sheet = self.sheets[self.index] if self.sheets else None
        if sheet is not None and self._schematic_editable(sheet):
            self._reset_schematic(sheet)
            return
        if sheet is None or not self._editable(sheet):
            return
        items = [self._item(b.key) for b in sheet.boxes]
        items = [i for i in items if i is not None and "layout_x_in" in i.fields]
        if not items:
            self.edit_status.configure(text="Nothing to reset - every part on this sheet is in its automatic spot.")
            return

        def apply() -> None:
            for i in items:
                i.fields.pop("layout_x_in", None)
                i.fields.pop("layout_y_in", None)

        self._edit(apply, f"Layout reset - {len(items)} part(s) back in their automatic zones.")

    # ------------------------------------------------ v0.3.27 copy / paste / delete / add parts
    _NO_COPY_FIELDS = ("layout_x_in", "layout_y_in", "wire_numbers", "io_address", "ip_address")

    def _sheet(self) -> Sheet | None:
        sheet = self.sheets[self.index] if self.sheets else None
        return sheet if sheet is not None and self._editable(sheet) else None

    def _door_sheet(self) -> bool:
        from cabinet_studio.services.drawings import _layout_sheet_is_door_only

        sheet = self._sheet()
        return sheet is not None and ("DOOR" in sheet.title or _layout_sheet_is_door_only(sheet))

    def _plate_spot(self, cx: float, cy: float) -> tuple[float, float] | None:
        """Canvas point -> inches from the plate's top-left corner, or None off the plate."""
        sheet = self._sheet()
        if sheet is None:
            return None
        px, py, pw, ph = sheet.panel
        f = pw / float(self.project.backplate_width_in or 1)
        x = ((cx - self._draw_ox) / self._draw_scale - px) / f
        y = ((cy - self._draw_oy) / self._draw_scale - py) / f
        return (x, y) if 0 <= x <= pw / f and 0 <= y <= ph / f else None

    def _new_tag(self, like: str) -> str:
        import re

        prefix = re.sub(r"\d+$", "", (like or "").strip()) or "DEV"
        taken = {(i.fields.get("tag", "") or "").strip().upper() for i in self.project.items}
        n = 1
        while f"{prefix}{n}".upper() in taken:
            n += 1
        return f"{prefix}{n}"

    def _pin_if_free(self, item, x_in: float | None, y_in: float | None) -> bool:
        """Pin the new part at the clicked spot when it fits there; otherwise it takes a free automatic spot."""
        from cabinet_studio.services.panel_zones import PIN_GRID_IN, item_inches

        sheet = self._sheet()
        if sheet is None or x_in is None or y_in is None:
            return False
        px, py, pw, ph = sheet.panel
        f = pw / float(self.project.backplate_width_in or 1)
        w_in, h_in = item_inches(self.library, item)
        x_in = min(max(round(x_in / PIN_GRID_IN) * PIN_GRID_IN, 0.0), max(pw / f - w_in, 0.0))
        y_in = min(max(round(y_in / PIN_GRID_IN) * PIN_GRID_IN, 0.0), max(ph / f - h_in, 0.0))
        nx, ny, nw, nh = px + x_in * f, py + y_in * f, w_in * f, h_in * f
        for b in sheet.boxes:
            if not (nx + nw <= b.x or b.x + b.w <= nx or ny + nh <= b.y or b.y + b.h <= ny):
                return False
        item.fields["layout_x_in"] = f"{x_in:g}"
        item.fields["layout_y_in"] = f"{y_in:g}"
        return True

    def _add_item(self, item, verb: str, pinned: bool) -> str | None:
        tag = item.fields.get("tag", "")
        before = sum(1 for s in self.sheets if s.kind == "layout")
        self.project.items.append(item)
        try:
            after = sum(1 for s in build_sheets(self.project, self.library) if s.kind == "layout")
        finally:
            self.project.items.remove(item)
        if after > before:
            self.edit_status.configure(text=f"No room on the plate for {tag} - move or delete parts, "
                                            "or choose a larger enclosure.")
            return None

        def apply() -> None:
            self.project.items.append(item)

        where = "where you clicked" if pinned else "in the first free spot"
        self._edit(apply, f"{verb} {tag} {where}. Fill in its wiring on the main screen.")
        self.selected_key = item.id
        if not any(b.key == item.id for s in self.sheets for b in s.boxes):
            self.edit_status.configure(text=f"{verb} {tag}, but it is not drawn on a layout sheet "
                                            "(field device or no room) - check the device list.")
        else:
            self._draw()
        return item.id

    def copy_part(self, key: str | None = None) -> bool:
        sheet = self._sheet()
        key = key or self.selected_key
        item = self._item(key) if key else None
        if sheet is None or item is None or not any(b.key == key for b in sheet.boxes):
            if sheet is not None:
                self.edit_status.configure(text="Click a part first, then Copy.")
            return False
        self._clip = {"library_id": item.library_id, "type_id": item.type_id, "fields": dict(item.fields)}
        self.edit_status.configure(text=f"Copied {item.fields.get('tag', 'part')} - right-click the plate and "
                                        "choose Paste here, or press Ctrl+V.")
        return True

    def paste_part(self, x_in: float | None = None, y_in: float | None = None) -> str | None:
        from cabinet_studio.models.project import PlacedItem
        from cabinet_studio.services.layouts import new_id
        from cabinet_studio.services.placement import next_free_position

        if self._sheet() is None:
            return None
        if not self._clip:
            self.edit_status.configure(text="Nothing copied yet - right-click a part and choose Copy.")
            return None
        clip = self._clip
        fields = {k: v for k, v in clip["fields"].items() if k not in self._NO_COPY_FIELDS}
        fields["tag"] = self._new_tag(fields.get("tag", ""))
        x, y = next_free_position(self.project, self.library, clip["type_id"])
        item = PlacedItem(id=new_id(), library_id=clip["library_id"], type_id=clip["type_id"], x=x, y=y, fields=fields)
        pinned = self._pin_if_free(item, x_in, y_in)
        return self._add_item(item, "Pasted", pinned)

    def delete_part(self, key: str | None = None) -> bool:
        sheet = self._sheet()
        key = key or self.selected_key
        item = self._item(key) if key else None
        if sheet is None or item is None or not any(b.key == key for b in sheet.boxes):
            return False
        tag = item.fields.get("tag", "") or "part"

        def apply() -> None:
            self.project.items = [i for i in self.project.items if i.id != key]

        self.selected_key = None
        self._edit(apply, f"Deleted {tag} from the cabinet (Undo on the main screen brings it back).")
        return True

    def part_choices(self) -> list[tuple[str, str, str, str]]:
        """(maker, type label, catalog id, catalog label) for parts that mount on the plate or door."""
        from cabinet_studio.services.panel_zones import DUCT_TYPES, FIELD_TYPES, SHELL_TYPES

        skip = FIELD_TYPES | SHELL_TYPES | DUCT_TYPES
        rank = {"Allen-Bradley": 0, "Siemens": 1, "Omron": 2}
        out = []
        for c in self.library.catalog:
            if c.type_id in skip or c.type_id not in self.library.types:
                continue
            if c.default_map().get("mounting") == "Field device":
                continue
            out.append((c.vendor, self.library.types[c.type_id].label, c.id, f"{c.catalog} - {c.name}"))
        return sorted(out, key=lambda r: (rank.get(r[0], 9), r[0], r[1], r[3]))

    def add_part(self, catalog_id: str, x_in: float | None = None, y_in: float | None = None) -> str | None:
        from cabinet_studio.models.project import PlacedItem
        from cabinet_studio.services.drawings import _item_is_door_mount
        from cabinet_studio.services.layouts import new_id
        from cabinet_studio.services.placement import next_free_position
        from cabinet_studio.services.suggestions import TAG_PREFIX

        cat = self.library.catalog_by_id.get(catalog_id)
        if cat is None or self._sheet() is None:
            return None
        fields = cat.default_map()
        fields["tag"] = self._new_tag(TAG_PREFIX.get(cat.type_id, cat.type_id[:3].upper()))
        x, y = next_free_position(self.project, self.library, cat.type_id)
        item = PlacedItem(id=new_id(), library_id=cat.id, type_id=cat.type_id, x=x, y=y, fields=fields)
        door = self._door_sheet()
        if door != _item_is_door_mount(item):
            item.fields["mounting"] = "On door" if door else "In cabinet"
        pinned = self._pin_if_free(item, x_in, y_in)
        return self._add_item(item, "Added", pinned)

    def _part_menu(self, x_in: float | None, y_in: float | None) -> tk.Menu:
        menu = tk.Menu(self, tearoff=False)
        makers: dict[str, tk.Menu] = {}
        groups: dict[tuple[str, str], tk.Menu] = {}
        for maker, type_label, cid, label in self.part_choices():
            top = makers.get(maker)
            if top is None:
                top = makers[maker] = tk.Menu(menu, tearoff=False)
                menu.add_cascade(label=maker, menu=top)
            sub = groups.get((maker, type_label))
            if sub is None:
                sub = groups[(maker, type_label)] = tk.Menu(top, tearoff=False)
                top.add_cascade(label=type_label, menu=sub)
            sub.add_command(label=label, command=lambda c=cid: self.add_part(c, x_in, y_in))
        return menu

    def _context_menu(self, key: str | None, x_in: float | None, y_in: float | None) -> tk.Menu:
        menu = tk.Menu(self, tearoff=False)
        item = self._item(key) if key else None
        tag = item.fields.get("tag", "part") if item else ""
        menu.add_command(label=f"Copy {tag}".strip(), command=lambda: self.copy_part(key),
                         state="normal" if item else "disabled")
        menu.add_command(label="Paste here", command=lambda: self.paste_part(x_in, y_in),
                         state="normal" if self._clip else "disabled")
        menu.add_command(label=f"Delete {tag}".strip(), command=lambda: self.delete_part(key),
                         state="normal" if item else "disabled")
        menu.add_separator()
        menu.add_cascade(label="Add part here", menu=self._part_menu(x_in, y_in))
        return menu

    def _context_click(self, event) -> None:
        if self._sheet() is None:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        box = self._box_at(cx, cy)
        if box is not None:
            self.selected_key = box.key
            self._draw()
        spot = self._plate_spot(cx, cy)
        menu = self._context_menu(box.key if box else None, *(spot or (None, None)))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_part_button(self) -> None:
        if self._sheet() is None:
            return
        menu = self._part_menu(None, None)
        menu.tk_popup(self.add_btn.winfo_rootx(), self.add_btn.winfo_rooty() - 4)

    def open_hmi_editor(self) -> None:
        from cabinet_studio.ui.hmi_editor import open_hmi_editor

        def hook(apply, message: str) -> None:
            try:
                alive = bool(self.winfo_exists())
            except Exception:
                alive = False
            if alive:
                self._edit(apply, message)
            elif self.edit_hook is not None:
                self.edit_hook(apply, message)
            else:
                apply()

        # Parented to the main window so it stays open if the drawings window closes.
        self._hmi_editor = open_hmi_editor(self.master, self.fonts, self.project, edit_hook=hook,
                                           existing=self._hmi_editor)

    def _edit(self, apply, message: str) -> None:
        if self.edit_hook is not None:
            self.edit_hook(apply, message)
        else:
            apply()
        title = self.sheets[self.index].title
        self.sheets = build_sheets(self.project, self.library)
        self.index = next((n for n, s in enumerate(self.sheets) if s.title == title), min(self.index, len(self.sheets) - 1))
        self.edit_status.configure(text=message)
        self._draw()

    def _register_hover_targets(self, sheet: Sheet, ox: float, oy: float, scale: float) -> None:
        # Generous invisible hit pads — tags on canvas are sparse; hover must be easy.
        pad = 36 * scale
        for box in sheet.boxes:
            tip = box_hover_detail(box)
            x0 = ox + box.x * scale - pad
            y0 = oy + box.y * scale - pad
            x1 = ox + (box.x + box.w) * scale + pad
            y1 = oy + (box.y + box.h) * scale + pad
            if sheet.kind in {"power", "control"}:
                # Callout band + under-rung wire-ref strip + far-right From·To band.
                x1 = ox + max(box.x + box.w + 320, PAGE_W - 40) * scale + pad
                y1 = oy + (box.y + box.h + 96) * scale + pad
            elif sheet.kind == "layout":
                # Whole footprint plus spacing around outlined component.
                x0 = ox + box.x * scale - pad * 1.2
                y0 = oy + box.y * scale - pad * 1.2
                x1 = ox + (box.x + box.w) * scale + pad * 1.2
                y1 = oy + (box.y + box.h) * scale + pad * 1.2
            self._hover_targets.append((x0, y0, x1, y1, tip))

    def _on_canvas_motion(self, event) -> None:
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        tip = None
        for x0, y0, x1, y1, text in reversed(self._hover_targets):
            if x0 <= x <= x1 and y0 <= y <= y1:
                tip = text
                break
        key = tip or ""
        if key == (self._hover_key or ""):
            return
        self._hover_key = key
        if self._hover_after is not None:
            try:
                self.after_cancel(self._hover_after)
            except Exception:
                pass
            self._hover_after = None
        if not tip:
            self._hide_hover_tip()
            return
        self._hover_after = self.after(
            90, lambda t=tip, ex=event.x_root, ey=event.y_root: self._show_hover_tip(t, ex, ey)
        )

    def _show_hover_tip(self, text: str, root_x: int, root_y: int) -> None:
        self._hover_after = None
        self._hide_hover_tip(clear_key=False)
        tip = ctk.CTkToplevel(self)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        frame = ctk.CTkFrame(tip, fg_color=TIP_BG, corner_radius=6, border_width=1, border_color=TIP_BORDER)
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(
            frame,
            text=text,
            font=self.fonts.tiny,
            text_color=TIP_TEXT,
            justify="left",
            anchor="w",
            wraplength=420,
        ).pack(padx=10, pady=8)
        tip.update_idletasks()
        tip.geometry(f"+{root_x + 16}+{root_y + 16}")
        tip.deiconify()
        self._hover_tip = tip

    def _hide_hover_tip(self, _event=None, *, clear_key: bool = True) -> None:
        if self._hover_after is not None:
            try:
                self.after_cancel(self._hover_after)
            except Exception:
                pass
            self._hover_after = None
        if clear_key:
            self._hover_key = None
        if self._hover_tip is not None:
            try:
                self._hover_tip.destroy()
            except Exception:
                pass
            self._hover_tip = None

    def _paint_svg_subset(self, svg: str, ox: float, oy: float, scale: float) -> None:
        """Draw the SVG subset we emit (rect, line, circle, polygon, text, polyline).

        Sparse mode: skip dense callout / wire-ref / io-addr text — details are on hover.
        """
        import xml.etree.ElementTree as ET

        root = ET.fromstring(svg)

        def local(tag: str) -> str:
            return tag.split("}", 1)[-1]

        def num(value: str | None, default: float = 0.0) -> float:
            if value is None or value == "":
                return default
            try:
                return float(value)
            except ValueError:
                return default

        def sx(x: float) -> float:
            return ox + x * scale

        def sy(y: float) -> float:
            return oy + y * scale

        def walk(node) -> None:
            tag = local(node.tag)
            if tag == "rect":
                x = num(node.get("x"))
                y = num(node.get("y"))
                w = num(node.get("width"))
                h = num(node.get("height"))
                fill = node.get("fill") or ""
                stroke = node.get("stroke") or ""
                sw = max(1, int(round(num(node.get("stroke-width"), 1) * scale)))
                if fill in {"none", ""}:
                    fill = ""
                if stroke in {"none", ""}:
                    stroke = ""
                self.canvas.create_rectangle(
                    sx(x), sy(y), sx(x + w), sy(y + h),
                    fill=fill or "",
                    outline=stroke or (fill if not stroke else stroke),
                    width=sw if stroke else 0,
                )
            elif tag == "line":
                self.canvas.create_line(
                    sx(num(node.get("x1"))),
                    sy(num(node.get("y1"))),
                    sx(num(node.get("x2"))),
                    sy(num(node.get("y2"))),
                    fill=node.get("stroke") or "#000000",
                    width=max(1, int(round(num(node.get("stroke-width"), 1.4) * scale))),
                )
            elif tag == "circle":
                cx = num(node.get("cx"))
                cy = num(node.get("cy"))
                r = num(node.get("r"))
                fill = node.get("fill") or ""
                if fill in {"none", ""}:
                    fill = ""
                stroke = node.get("stroke") or "#000000"
                sw = max(1, int(round(num(node.get("stroke-width"), 1.4) * scale)))
                self.canvas.create_oval(
                    sx(cx - r), sy(cy - r), sx(cx + r), sy(cy + r),
                    fill=fill or "",
                    outline=stroke,
                    width=sw,
                )
            elif tag == "polygon":
                pts = []
                for pair in (node.get("points") or "").split():
                    if "," in pair:
                        a, b = pair.split(",", 1)
                        pts.extend([sx(num(a)), sy(num(b))])
                if len(pts) >= 6:
                    self.canvas.create_polygon(*pts, fill=node.get("fill") or "#000000", outline="")
            elif tag == "polyline":
                pts = []
                for pair in (node.get("points") or "").split():
                    if "," in pair:
                        a, b = pair.split(",", 1)
                        pts.extend([sx(num(a)), sy(num(b))])
                if len(pts) >= 4:
                    self.canvas.create_line(
                        *pts,
                        fill=node.get("stroke") or "#000000",
                        width=max(1, int(round(num(node.get("stroke-width"), 1.4) * scale))),
                    )
            elif tag == "text":
                cls = (node.get("class") or "").strip()
                if cls in _SPARSE_SKIP:
                    return
                text = "".join(node.itertext()).strip()
                if not text:
                    return
                x = num(node.get("x"))
                y = num(node.get("y"))
                fill = node.get("fill") or "#000000"
                size = max(7, int(round(num(node.get("font-size"), 11) * scale)))
                weight = "bold" if "700" in (node.get("font-weight") or "") else "normal"
                family = "Consolas" if "Consolas" in (node.get("font-family") or "") else "Segoe UI"
                anchor = "w"
                if node.get("text-anchor") == "middle":
                    anchor = "center"
                # SVG text y is baseline; Canvas anchor n/s approximates.
                self.canvas.create_text(
                    sx(x),
                    sy(y),
                    text=text,
                    fill=fill,
                    font=(family, size, weight),
                    anchor=anchor if anchor != "center" else "center",
                )
            for child in list(node):
                # Skip clipPath definitions; still walk clipped content as best-effort.
                if local(child.tag) == "clipPath":
                    continue
                walk(child)

        walk(root)
