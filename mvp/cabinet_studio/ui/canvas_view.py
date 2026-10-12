"""Cabinet elevation. Devices are tiles with a short descriptor."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk

from cabinet_studio.models.project import Project
from cabinet_studio.models.schema import Library
from cabinet_studio.services.completeness import is_complete
from cabinet_studio.services.descriptors import tile_text
from cabinet_studio.services.placement import clamp_position, tile_size
from cabinet_studio.ui.theme import BG, CYAN, MUTED, ORANGE, TEXT, bind_theme_redraw, c
from cabinet_studio.ui.util import fit_text


class LayoutCanvas(ctk.CTkFrame):
    def __init__(self, master, fonts, on_select, on_edit, on_drag_start, on_drag_end) -> None:
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.fonts = fonts
        self.on_select = on_select
        self.on_edit = on_edit
        self.on_drag_start = on_drag_start
        self.on_drag_end = on_drag_end
        self.project: Project | None = None
        self.library: Library | None = None
        self.selected_id: str | None = None
        self._hover: str | None = None
        self._drag: dict | None = None
        self._boxes: list[tuple[str, float, float, float, float]] = []
        self._scale = 1.0
        self._origin = (16.0, 16.0)
        self._last_size = (0, 0)
        self._in_redraw = False
        self.scroll = ctk.CTkScrollbar(self, orientation="vertical", command=self._yview)
        self.scroll.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self.canvas = tk.Canvas(self, bg=c(BG), highlightthickness=0, bd=0, yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self._font_tag = tkfont.Font(family=fonts.mono_family, size=-12, weight="bold")
        self._font_body = tkfont.Font(family=fonts.ui_family, size=-10)
        self._font_small = tkfont.Font(family=fonts.ui_family, size=-9)
        self._font_plate = tkfont.Font(family=fonts.ui_family, size=-12, weight="bold")
        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Motion>", self._on_hover)
        self.canvas.bind("<Button-4>", lambda _event: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda _event: self.canvas.yview_scroll(1, "units"))
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        bind_theme_redraw(self, self._on_theme)

    def _on_theme(self) -> None:
        self.canvas.configure(bg=c(BG))
        self.redraw()

    def _yview(self, *args) -> None:
        self.canvas.yview(*args)

    def set_state(self, project: Project, library: Library, selected_id: str | None) -> None:
        self.project = project
        self.library = library
        self.selected_id = selected_id
        self.redraw()

    def _on_configure(self, event) -> None:
        size = (event.width, event.height)
        if size == self._last_size:
            return
        self._last_size = size
        self.redraw()

    def _on_wheel(self, event) -> None:
        step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")

    def redraw(self) -> None:
        if self._in_redraw or self.project is None or self.library is None:
            return
        self._in_redraw = True
        try:
            self._paint()
        finally:
            self._in_redraw = False

    def _paint(self) -> None:
        canvas = self.canvas
        view = canvas.yview()[0]
        canvas.delete("all")
        self._boxes.clear()
        width = max(canvas.winfo_width(), 10)
        height = max(canvas.winfo_height(), 10)
        project = self.project
        library = self.library
        pad = 20
        scale = (width - pad * 2) / project.cabinet_width
        scale = max(0.42, min(scale, 1.15))
        drawn_w = project.cabinet_width * scale
        drawn_h = project.cabinet_height * scale
        origin_x = max(pad, (width - drawn_w) / 2)
        origin_y = 18
        self._scale = scale
        self._origin = (origin_x, origin_y)
        font_px = max(10, min(13, int(12 * min(scale, 1))))
        self._font_tag.configure(size=-font_px)
        self._font_body.configure(size=-max(9, font_px - 2))
        self._font_small.configure(size=-max(8, font_px - 3))
        self._font_plate.configure(size=-font_px)

        shadow = 8 * min(scale, 1)
        x1, y1 = origin_x, origin_y
        x2, y2 = origin_x + drawn_w, origin_y + drawn_h
        canvas.create_rectangle(x1 + shadow, y1 + shadow, x2 + shadow, y2 + shadow, fill=c("SHADOW"), outline="")
        canvas.create_rectangle(x1, y1, x2, y2, fill=c("PLATE"), outline=c("PLATE_EDGE"), width=2)
        self._screws(x1, y1, x2, y2, scale)
        plate_h = 40 * scale
        canvas.create_rectangle(x1, y1, x2, y1 + plate_h, fill=c("PLATE_HEAD"), outline="")
        canvas.create_rectangle(x1, y1, x1 + 6 * scale, y1 + plate_h, fill=c(ORANGE), outline="")
        canvas.create_line(x1, y1 + plate_h, x2, y1 + plate_h, fill=c(CYAN), width=1)
        canvas.create_text(
            x1 + 16 * scale,
            y1 + plate_h / 2,
            text=project.cabinet_label,
            fill=c(TEXT),
            font=self._font_plate,
            anchor="w",
        )
        canvas.create_text(
            x2 - 14 * scale,
            y1 + plate_h / 2,
            text="ERMCO",
            fill=c(ORANGE),
            font=self._font_plate,
            anchor="e",
        )
        self._rails(x1, y1, x2, y2, scale)
        if not project.items:
            canvas.create_text(
                (x1 + x2) / 2,
                (y1 + y2) / 2,
                text="Choose a layout, or add a device from the library.\nEach one stays flagged until its required fields are filled.",
                fill=c(MUTED),
                font=self._font_body,
                justify="center",
            )
        for item in project.items:
            self._draw_tile(item, scale)
        if self.selected_id:
            self._outline_selected(scale)
        footer_y = y2 + 16
        subtitle = project.subtitle or "Drag a tile. Double-click it to define the device."
        canvas.create_text(
            origin_x,
            footer_y,
            text=subtitle,
            fill=c(MUTED),
            font=self._font_small,
            anchor="nw",
            width=max(120, drawn_w),
        )
        canvas.create_text(
            origin_x,
            footer_y + 28,
            text="Orange corner  =  required fields still open",
            fill=c("LEGEND"),
            font=self._font_small,
            anchor="nw",
        )
        content_h = footer_y + 52
        content_w = max(width, x2 + pad)
        canvas.configure(scrollregion=(0, 0, content_w, content_h))
        canvas.yview_moveto(view)

    def _screws(self, x1, y1, x2, y2, scale) -> None:
        radius = max(3, 4 * scale)
        inset = 12 * scale
        for cx, cy in (
            (x1 + inset, y1 + inset),
            (x2 - inset, y1 + inset),
            (x1 + inset, y2 - inset),
            (x2 - inset, y2 - inset),
        ):
            self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=c("PLATE_EDGE"), fill=c("SCREW"))

    def _rails(self, x1, y1, x2, y2, scale) -> None:
        top = y1 + 56 * scale
        bottom = y2 - 18 * scale
        for index in range(4):
            rail_y = top + (bottom - top) * (index + 1) / 5
            self.canvas.create_line(x1 + 18 * scale, rail_y, x2 - 18 * scale, rail_y, fill=c("DIN_RAIL"), width=max(1, int(2 * scale)))
            cap = 5 * scale
            self.canvas.create_line(x1 + 18 * scale, rail_y - cap, x1 + 18 * scale, rail_y + cap, fill=c("PLATE_EDGE"))
            self.canvas.create_line(x2 - 18 * scale, rail_y - cap, x2 - 18 * scale, rail_y + cap, fill=c("PLATE_EDGE"))

    def _draw_tile(self, item, scale: float) -> None:
        equipment = self.library.types.get(item.type_id)
        tile_w, tile_h = tile_size(self.library, item.type_id)
        x1, y1 = self._to_canvas(item.x, item.y)
        x2, y2 = self._to_canvas(item.x + tile_w, item.y + tile_h)
        complete = bool(equipment and is_complete(item.fields, equipment.fields))
        selected = item.id == self.selected_id
        hover = item.id == self._hover and not selected
        if selected:
            fill = c("TILE_SELECTED")
        elif hover:
            fill = c("TILE_HOVER")
        else:
            fill = c("TILE_FILL")
        accent = equipment.accent if equipment else "#6b7280"
        outline = c(CYAN) if selected else (c(ORANGE) if not complete else accent)
        width = 2 if selected else 1
        self.canvas.create_rectangle(x1 + 2, y1 + 3, x2 + 2, y2 + 3, fill=c("SHADOW"), outline="")
        self.canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width)
        bar = max(4, 5 * scale)
        self.canvas.create_rectangle(x1, y1, x1 + bar, y2, fill=accent, outline="")
        if equipment is None:
            tag, kind, detail = item.fields.get("tag", "") or "UNTAGGED", item.type_id, "Unknown type"
        else:
            tag, kind, detail = tile_text(item, equipment)
        inner = x2 - x1 - bar - 12
        left = x1 + bar + 8
        if not item.fields.get("tag", "").strip():
            tag_color = c(ORANGE)
        else:
            tag_color = c(TEXT)
        screen_h = y2 - y1
        if screen_h < 56:
            self.canvas.create_text(left, y1 + 6, text=fit_text(tag, self._font_tag, int(inner)), fill=tag_color, font=self._font_tag, anchor="nw")
            self.canvas.create_text(left, y1 + 6 + max(14, screen_h * 0.42), text=fit_text(detail, self._font_small, int(inner)), fill=c(MUTED), font=self._font_small, anchor="nw")
        else:
            self.canvas.create_text(left, y1 + 8, text=fit_text(tag, self._font_tag, int(inner)), fill=tag_color, font=self._font_tag, anchor="nw")
            self.canvas.create_text(left, y1 + 26, text=fit_text(kind.upper(), self._font_small, int(inner)), fill=accent, font=self._font_small, anchor="nw")
            self.canvas.create_text(left, y1 + 42, text=fit_text(detail, self._font_body, int(inner)), fill=c("TILE_DETAIL"), font=self._font_body, anchor="nw")
        if not complete:
            self.canvas.create_polygon(x2 - 14, y1, x2, y1, x2, y1 + 14, fill=c(ORANGE), outline="")
        self._boxes.append((item.id, x1, y1, x2, y2))

    def _outline_selected(self, scale: float) -> None:
        item = self.project.find(self.selected_id)
        if item is None:
            return
        tile_w, tile_h = tile_size(self.library, item.type_id)
        x1, y1 = self._to_canvas(item.x, item.y)
        x2, y2 = self._to_canvas(item.x + tile_w, item.y + tile_h)
        self.canvas.create_rectangle(x1 - 2, y1 - 2, x2 + 2, y2 + 2, outline=c(CYAN), width=2)

    def _to_canvas(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y = self._origin
        return origin_x + x * self._scale, origin_y + y * self._scale

    def _to_cabinet(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y = self._origin
        scale = self._scale or 1
        return (x - origin_x) / scale, (y - origin_y) / scale

    def _pointer(self, event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _hit(self, x: float, y: float):
        for item_id, x1, y1, x2, y2 in reversed(self._boxes):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return self.project.find(item_id)
        return None

    def _on_press(self, event) -> None:
        if self.project is None:
            return
        x, y = self._pointer(event)
        item = self._hit(x, y)
        if item is None:
            self._drag = None
            self.on_select(None)
            return
        self.on_select(item.id)
        cab_x, cab_y = self._to_cabinet(x, y)
        self._drag = {"id": item.id, "dx": cab_x - item.x, "dy": cab_y - item.y, "moved": False}
        self.on_drag_start(item.id)

    def _on_drag(self, event) -> None:
        if not self._drag or self.project is None or self.library is None:
            return
        item = self.project.find(self._drag["id"])
        if item is None:
            return
        x, y = self._pointer(event)
        cab_x, cab_y = self._to_cabinet(x, y)
        tile_w, tile_h = tile_size(self.library, item.type_id)
        next_x, next_y = clamp_position(
            cab_x - self._drag["dx"],
            cab_y - self._drag["dy"],
            tile_w,
            tile_h,
            self.project.cabinet_width,
            self.project.cabinet_height,
        )
        if abs(next_x - item.x) >= 0.5 or abs(next_y - item.y) >= 0.5:
            self._drag["moved"] = True
            item.x = next_x
            item.y = next_y
            self.redraw()

    def _on_release(self, _event) -> None:
        if not self._drag:
            return
        moved = self._drag["moved"]
        self._drag = None
        self.on_drag_end(moved)

    def _on_double(self, event) -> None:
        if self.project is None:
            return
        item = self._hit(*self._pointer(event))
        if item is not None:
            self.on_edit(item.id)

    def _on_hover(self, event) -> None:
        if self._drag or self.project is None:
            return
        item = self._hit(*self._pointer(event))
        hover = item.id if item is not None else None
        self.canvas.configure(cursor="hand2" if hover else "arrow")
        if hover != self._hover:
            self._hover = hover
            self.redraw()
