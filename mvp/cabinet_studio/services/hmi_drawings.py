"""HMI drawing sheets, made only when the cabinet has a saved HMI design.

Sheets (appended after the Wire Schedule by drawings.build_sheets):
- hmi-layout: one per screen, the panel bezel and screen to scale with every
  object labelled with its tag.
- hmi-cutout: door cutout detail from the HMI library dimensions.
- hmi-wiring: +24 V / 0 V / PE from the control power supply and the Ethernet
  cable to the PLC or switch, a conductor list, and the HMI tag table.
- hmi-tags: tag table continuation when it does not fit on the wiring sheet.
The title block (drawings._title_markup) adds the disclaimer once per sheet.
"""

from __future__ import annotations

from html import escape

from cabinet_studio.services.drawings import (
    PAGE_W,
    Box,
    ConnectionRow,
    Segment,
    Sheet,
    _clip,
    _num,
    _wrap,
)
from cabinet_studio.services.hmi_design import (
    COLORS,
    CONNECT_SWITCH,
    DEFAULT_THEME,
    OBJECT_KINDS,
    SAFETY_NOTE,
    THEMES,
    alarm_rows,
    grid_size,
    load_design,
    tag_table,
    theme_colors,
)
from cabinet_studio.services.hmi_library import MM_PER_IN, hmi_by_id, hmi_door_outline, hmi_label, screen_area_in
from cabinet_studio.services.hmi_symbols import GRAPHICS, svg_from_shapes, symbol_shapes

HMI_KINDS = ("hmi-layout", "hmi-cutout", "hmi-wiring", "hmi-tags", "hmi-alarms")
ALARM_ROWS = 40
FONT = "Segoe UI, Liberation Sans, sans-serif"
MONO = "Consolas, Liberation Mono, monospace"
BODY_TOP = 60.0
BODY_BOTTOM = 905.0
WIRING_TAG_ROWS = 40
CONT_TAG_ROWS = 44
TAG_PITCH = 18.0
_HMI_TAG = "HMI1"


def _text(x: float, y: float, text: str, size: float = 11, *, bold: bool = False, mono: bool = False,
          fill: str = "#000000", anchor: str = "start") -> str:
    weight = ' font-weight="700"' if bold else ""
    return (f'<text x="{_num(x)}" y="{_num(y)}" font-family="{MONO if mono else FONT}" font-size="{_num(size)}"'
            f'{weight} fill="{fill}" text-anchor="{anchor}">{escape(text)}</text>')


def _rect(x: float, y: float, w: float, h: float, *, stroke: str = "#000000", fill: str = "none",
          sw: float = 1.2) -> str:
    return (f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{_num(sw)}"/>')


def _line(x1: float, y1: float, x2: float, y2: float, sw: float = 1.0, stroke: str = "#000000") -> str:
    return (f'<line x1="{_num(x1)}" y1="{_num(y1)}" x2="{_num(x2)}" y2="{_num(y2)}" '
            f'stroke="{stroke}" stroke-width="{_num(sw)}"/>')


def _notes(entry: dict) -> list[str]:
    return [SAFETY_NOTE, f"HMI sizes are {entry['verify']}."]


# ----------------------------------------------------------------------------- sheet list

def hmi_sheets(project) -> list[Sheet]:
    design = load_design(project)
    if design is None or not design.screens:
        return []
    entry = hmi_by_id(design.model_id)
    if entry is None:
        return []
    sheets: list[Sheet] = []
    for index, screen in enumerate(design.screens, start=1):
        sheet = Sheet(kind="hmi-layout", title=_clip(f"HMI SCREEN LAYOUT - {screen.name.upper()}", 48),
                      notes=_notes(entry))
        sheet.schedule_page = index
        geom = _screen_geom(entry, design)
        rows = {r["tag"]: r for r in tag_table(design, project)}
        for obj in screen.objects:
            x, y, w, h = _cell_rect(geom, obj)
            row = rows.get(obj.tag, {})
            sheet.boxes.append(Box(
                key=f"hmi-{screen.name}-{obj.id}", tag=obj.tag or obj.label, role="hmi",
                callout=f"{OBJECT_KINDS[obj.kind]['name']}: {obj.label}",
                lines=[obj.label], x=x, y=y, w=w, h=h, type_id=f"HMI {OBJECT_KINDS[obj.kind]['name']}",
                io_address=row.get("address", "")))
        sheets.append(sheet)
    sheets.append(Sheet(kind="hmi-cutout", title="HMI DOOR CUTOUT DETAIL", notes=_notes(entry)))
    wiring = Sheet(kind="hmi-wiring", title="HMI WIRING + TAG TABLE", notes=_notes(entry))
    _build_wiring(project, design, entry, wiring)
    sheets.append(wiring)
    rows = tag_table(design, project)
    extra = rows[WIRING_TAG_ROWS:]
    page = 1
    while extra:
        cont = Sheet(kind="hmi-tags", title=f"HMI TAG TABLE (CONT. {page})", notes=_notes(entry))
        cont.schedule_page = page
        sheets.append(cont)
        extra = extra[CONT_TAG_ROWS:]
        page += 1
    if alarm_rows(design, project):
        sheets.append(Sheet(kind="hmi-alarms", title="HMI ALARM LIST", notes=_notes(entry)))
    return sheets


def hmi_sheet_markup(sheet: Sheet, project) -> str:
    design = load_design(project)
    entry = hmi_by_id(design.model_id) if design else None
    if design is None or entry is None:
        return _text(60, 100, "No HMI design saved on this cabinet.", 14, bold=True)
    if sheet.kind == "hmi-layout":
        return _layout_markup(sheet, project, design, entry)
    if sheet.kind == "hmi-cutout":
        return _cutout_markup(entry)
    if sheet.kind == "hmi-wiring":
        return _wiring_markup(sheet, project, design, entry)
    if sheet.kind == "hmi-alarms":
        return _alarm_markup(design, project)
    rows = tag_table(design, project)
    start = WIRING_TAG_ROWS + (sheet.schedule_page - 1) * CONT_TAG_ROWS
    return _tag_table_markup(rows[start:start + CONT_TAG_ROWS], 60.0, BODY_TOP + 20, wide=True)


# ----------------------------------------------------------------------------- screen layout

def _screen_geom(entry: dict, design) -> dict:
    bw, bh = entry["bezel_w_mm"], entry["bezel_h_mm"]
    area_x, area_y, area_w, area_h = 50.0, BODY_TOP + 30, 1060.0, 790.0
    scale = min(area_w / bw, area_h / bh) * 0.94
    bx = area_x + (area_w - bw * scale) / 2
    by = area_y + (area_h - bh * scale) / 2
    sw_in, sh_in = screen_area_in(entry)
    sw, sh = sw_in * MM_PER_IN * scale, sh_in * MM_PER_IN * scale
    sx = bx + (bw * scale - sw) / 2
    sy = by + (bh * scale - sh) / 2
    if entry["function_keys"]:
        sy = by + max(6.0, (bh * scale - sh) / 2 - 14)
    cols, rows = grid_size(design.model_id)
    return {"scale": scale, "bezel": (bx, by, bw * scale, bh * scale), "screen": (sx, sy, sw, sh),
            "cols": cols, "rows": rows, "cw": sw / cols, "ch": sh / rows}


def _cell_rect(geom: dict, obj) -> tuple[float, float, float, float]:
    sx, sy, _sw, _sh = geom["screen"]
    pad = 1.5
    return (sx + obj.x * geom["cw"] + pad, sy + obj.y * geom["ch"] + pad,
            obj.w * geom["cw"] - 2 * pad, obj.h * geom["ch"] - 2 * pad)


def _layout_markup(sheet: Sheet, project, design, entry: dict) -> str:
    screen = design.screens[min(max(sheet.schedule_page, 1), len(design.screens)) - 1]
    geom = _screen_geom(entry, design)
    bx, by, bw, bh = geom["bezel"]
    sx, sy, sw, sh = geom["screen"]
    parts = [
        _text(50, BODY_TOP + 12, f"SCREEN: {screen.name}  -  {hmi_label(entry)}", 13, bold=True),
        _rect(bx, by, bw, bh, stroke="#000000", fill="#d9dbe0", sw=2.0),
        _rect(sx, sy, sw, sh, stroke="#000000", fill=THEMES.get(design.theme, THEMES[DEFAULT_THEME])["screen"],
              sw=1.4),
    ]
    for c in range(1, geom["cols"]):
        x = sx + c * geom["cw"]
        parts.append(_line(x, sy, x, sy + sh, 0.3, "#c8ccd4"))
    for r in range(1, geom["rows"]):
        y = sy + r * geom["ch"]
        parts.append(_line(sx, y, sx + sw, y, 0.3, "#c8ccd4"))
    keys = int(entry["function_keys"] or 0)
    if keys:
        gap = sw / keys
        ky = sy + sh + max(4.0, (by + bh - sy - sh) / 2 - 8)
        for k in range(keys):
            parts.append(_rect(sx + k * gap + gap * 0.2, ky, gap * 0.6, 12, fill="#ffffff", sw=0.8))
            parts.append(_text(sx + k * gap + gap / 2, ky + 9.5, f"F{k + 1}", 8, anchor="middle"))
    for obj in screen.objects:
        x, y, w, h = _cell_rect(geom, obj)
        if obj.kind in GRAPHICS:
            parts.append(svg_from_shapes(symbol_shapes(obj.kind, x, y, w, h, None, design.theme), _num))
            if obj.tag and h >= 14:
                parts.append(_text(x + 2, y + h - 3, _clip(obj.tag, max(4, int(w / 5.5))), 7.5, mono=True))
            continue
        color = COLORS.get(obj.color, "#7a7f8c")
        fill, outline, ink = theme_colors(design.theme, obj.color)
        light = obj.kind in {"text", "numeric_display", "numeric_entry", "trend"}
        parts.append(_rect(x, y, w, h, stroke=outline if not light else "#555555",
                           fill="#ffffff" if light else fill, sw=1.6))
        if obj.kind == "lamp":
            parts.append(_rect(x, y, w, min(5.0, h / 3), stroke=color, fill=color, sw=0.5))
        ink = "#000000" if light else ink
        if obj.kind == "trend" and w > 40 and h > 40:
            parts.append(_line(x + 8, y + h - 10, x + w - 8, y + h - 10, 0.8, "#555555"))
            parts.append(_line(x + 8, y + 22, x + 8, y + h - 10, 0.8, "#555555"))
            pts = " ".join(f"{_num(x + 8 + (w - 16) * i / 8)},{_num(y + h - 14 - (h - 40) * ((i * 37) % 9) / 9)}"
                           for i in range(9))
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.4"/>')
        chars = max(4, int((w - 6) / 6.2))
        lines = _wrap(obj.label or OBJECT_KINDS[obj.kind]["name"], chars)
        if obj.tag:
            lines = lines[:max(1, int((h - 8) / 12) - 1)] + [_clip(obj.tag, chars)]
        lines = lines[:max(1, int((h - 6) / 12))]
        for i, line in enumerate(lines):
            last_is_tag = bool(obj.tag) and i == len(lines) - 1
            parts.append(_text(x + 3, y + 16 + i * 12, _clip(line, chars), 9.5 if last_is_tag else 10,
                               mono=last_is_tag, bold=not last_is_tag, fill=ink))
    ratio = geom["scale"] * 0.254
    parts.append(_text(50, BODY_BOTTOM - 4,
                       f"Bezel {entry['bezel_w_mm']} x {entry['bezel_h_mm']} mm, screen {entry['resolution_px'][0]}"
                       f"x{entry['resolution_px'][1]} px, grid {geom['cols']} x {geom['rows']}. "
                       f"Printed about {ratio:.2f}:1 on 11x17.", 10, fill="#444444"))
    parts.extend(_object_list_markup(screen, entry))
    return "".join(parts)


def _object_list_markup(screen, entry: dict) -> list[str]:
    x0 = 1135.0
    parts = [
        _text(x0, BODY_TOP + 12, "HMI", 9, fill="#444444"),
        _text(x0, BODY_TOP + 28, _clip(hmi_label(entry), 86), 11, bold=True),
        _text(x0, BODY_TOP + 44, _clip(f"Software: {entry['software']}", 86), 10),
        _text(x0, BODY_TOP + 60, _clip(f"Comms: {', '.join(entry['comms'])}", 86), 10),
        _text(x0, BODY_TOP + 90, "OBJECTS ON THIS SCREEN  (label | tag | read/write)", 10, bold=True),
    ]
    y = BODY_TOP + 108
    limit = 760.0
    shown = 0
    for obj in screen.objects:
        if y > limit:
            break
        rw = {"W": "W", "R": "R"}.get(obj.access, "-")
        parts.append(_text(x0, y, _clip(f"{obj.label} | {obj.tag or '-'} | {rw}", 88), 9.5, mono=True))
        y += 15
        shown += 1
    if shown < len(screen.objects):
        parts.append(_text(x0, y, f"+ {len(screen.objects) - shown} more (see tag table)", 9.5, fill="#444444"))
    y = 790.0
    for line in _wrap(SAFETY_NOTE, 80):
        parts.append(_text(x0, y, line, 10, bold=True, fill="#8a1c1c"))
        y += 14
    parts.append(_text(x0, y + 6, "E-stop objects on the HMI show status only.", 10, fill="#8a1c1c"))
    return parts


# ----------------------------------------------------------------------------- door cutout

def _clamp_count(entry: dict) -> tuple[int, int]:
    long_side = 2 if entry["bezel_w_mm"] < 250 else 3
    short_side = 1 if entry["bezel_h_mm"] < 200 else 2
    return long_side, short_side


def _cutout_markup(entry: dict) -> str:
    bw, bh = entry["bezel_w_mm"], entry["bezel_h_mm"]
    cw, ch = entry["cutout_w_mm"], entry["cutout_h_mm"]
    scale = min(820.0 / bw, 620.0 / bh)
    ox = 130.0 + (900.0 - bw * scale) / 2
    oy = BODY_TOP + 90 + (660.0 - bh * scale) / 2
    cx = ox + (bw - cw) * scale / 2
    cy = oy + (bh - ch) * scale / 2
    parts = [
        _text(50, BODY_TOP + 12, f"DOOR CUTOUT  -  {hmi_label(entry)}", 13, bold=True),
        _rect(ox, oy, bw * scale, bh * scale, stroke="#777777", sw=1.0),
        _text(ox + 4, oy - 6, "Bezel outline (front of door)", 9, fill="#555555"),
        _rect(cx, cy, cw * scale, ch * scale, stroke="#000000", fill="#f2f2f2", sw=2.4),
        _text(cx + cw * scale / 2, cy + ch * scale / 2, "CUT OUT", 16, bold=True, anchor="middle"),
    ]
    # Width dimension under the bezel, height dimension left of the bezel.
    dy = oy + bh * scale + 34
    parts += [_line(cx, cy + ch * scale, cx, dy + 6, 0.6), _line(cx + cw * scale, cy + ch * scale,
                                                                  cx + cw * scale, dy + 6, 0.6),
              _line(cx, dy, cx + cw * scale, dy, 1.0),
              _text(cx + cw * scale / 2, dy - 6, f"{cw} mm  ({cw / MM_PER_IN:.2f} in)", 12, bold=True,
                    anchor="middle")]
    dx = ox - 40
    parts += [_line(cx, cy, dx - 6, cy, 0.6), _line(cx, cy + ch * scale, dx - 6, cy + ch * scale, 0.6),
              _line(dx, cy, dx, cy + ch * scale, 1.0),
              _text(dx - 8, cy + ch * scale / 2, f"{ch} mm", 12, bold=True, anchor="end"),
              _text(dx - 8, cy + ch * scale / 2 + 15, f"({ch / MM_PER_IN:.2f} in)", 11, anchor="end")]
    long_side, short_side = _clamp_count(entry)
    clamp = 10.0
    for i in range(long_side):
        x = cx + cw * scale * (i + 1) / (long_side + 1)
        parts.append(_rect(x - clamp, cy - 4, clamp * 2, 8, fill="#000000"))
        parts.append(_rect(x - clamp, cy + ch * scale - 4, clamp * 2, 8, fill="#000000"))
    for i in range(short_side):
        y = cy + ch * scale * (i + 1) / (short_side + 1)
        parts.append(_rect(cx - 4, y - clamp, 8, clamp * 2, fill="#000000"))
        parts.append(_rect(cx + cw * scale - 4, y - clamp, 8, clamp * 2, fill="#000000"))
    w_in, h_in = hmi_door_outline(entry["id"])
    x0 = 1135.0
    info = [
        ("CUTOUT", f"{cw} x {ch} mm  ({cw / MM_PER_IN:.2f} x {ch / MM_PER_IN:.2f} in)"),
        ("BEZEL", f"{bw} x {bh} mm  ({w_in:.2f} x {h_in:.2f} in)"),
        ("DEPTH BEHIND DOOR", f"{entry['depth_mm']} mm - keep backplate parts clear"),
        ("MOUNTING", f"{entry['mounting']} ({2 * (long_side + short_side)} clamps, black marks)"),
        ("FRONT RATING", entry["ip_rating"]),
        ("CATALOG", entry["catalog_number"]),
        ("SOURCE", entry["source_url"] or "not recorded - use the maker's installation sheet"),
    ]
    y = BODY_TOP + 40
    for head, value in info:
        parts.append(_text(x0, y, head, 9, fill="#444444"))
        for line in _wrap(value, 78)[:2]:
            y += 14
            parts.append(_text(x0, y, line, 11))
        y += 22
    for line in _wrap(f"Dimensions are {entry['verify']}. Check the door thickness against the clamp range.", 78):
        parts.append(_text(x0, y, line, 10, bold=True, fill="#8a1c1c"))
        y += 14
    parts.append(_text(50, BODY_BOTTOM - 4, f"Drawn to fit; dimensions in mm govern. Scale about "
                                            f"{scale * 0.254:.2f}:1 on 11x17.", 10, fill="#444444"))
    return "".join(parts)


# ----------------------------------------------------------------------------- wiring + tag table

def _device_tag(project, type_id: str) -> str:
    for item in project.items:
        if item.type_id == type_id and (item.fields.get("tag") or "").strip():
            return item.fields["tag"].strip()
    return ""


def _endpoints(project, design) -> tuple[str, str, str]:
    psu = _device_tag(project, "power_supply")
    switch = _device_tag(project, "ethernet_switch")
    plc = _device_tag(project, "plc")
    if design.connect_to == CONNECT_SWITCH and switch:
        peer = switch
    else:
        peer = plc or switch
    return psu, peer, plc


def _conductors(project, design, entry: dict) -> list[ConnectionRow]:
    psu, peer, _plc = _endpoints(project, design)
    psu = psu or "24VDC PSU"
    peer = peer or "PLC"
    port = entry["comms"][0]
    return [
        ConnectionRow("HMI+24", f"{psu}:+24V", f"{_HMI_TAG}:+24V", "Blue", "18 AWG"),
        ConnectionRow("HMI0V", f"{psu}:0V", f"{_HMI_TAG}:0V", "White/Blue", "18 AWG"),
        ConnectionRow("HMI-PE", f"{_HMI_TAG}:PE", "PE BAR", "Green/Yellow", "14 AWG"),
        ConnectionRow("HMI-ETH", f"{_HMI_TAG}:{port}", f"{peer}:Ethernet", "Teal (shielded Cat 5e/6)",
                      "24 AWG"),
    ]


def _build_wiring(project, design, entry: dict, sheet: Sheet) -> None:
    psu, peer, _plc = _endpoints(project, design)
    rows = _conductors(project, design, entry)
    by_wire = {r.wire: r for r in rows}
    sheet.boxes = [
        Box(key="hmi-psu", tag=psu or "24 VDC SUPPLY", role="hmi", callout="Control power supply",
            lines=[], x=80, y=120, w=220, h=150, type_id="power_supply", connections=rows[:2]),
        Box(key="hmi-panel", tag=_HMI_TAG, role="hmi", callout=hmi_label(entry), lines=[], x=520, y=120, w=260,
            h=200, type_id="HMI", connections=rows),
        Box(key="hmi-pe", tag="PE BAR", role="ground", callout="Protective earth bar", lines=[], x=80, y=480,
            w=240, h=28, type_id="ground", connections=[rows[2]]),
        Box(key="hmi-peer", tag=peer or "PLC", role="hmi", callout="Ethernet peer (PLC or switch)", lines=[],
            x=520, y=480, w=260, h=120, type_id="plc", connections=[rows[3]]),
    ]

    def seg(x1, y1, x2, y2, wire):
        r = by_wire[wire]
        sheet.segments.append(Segment(x1, y1, x2, y2, wire, r.color, r.gauge))

    seg(300, 150, 520, 150, "HMI+24")
    seg(300, 200, 520, 200, "HMI0V")
    seg(520, 280, 190, 280, "HMI-PE")
    seg(190, 280, 190, 480, "HMI-PE")
    seg(650, 320, 650, 480, "HMI-ETH")


def _wiring_markup(sheet: Sheet, project, design, entry: dict) -> str:
    psu, peer, _plc = _endpoints(project, design)
    parts = [_text(50, BODY_TOP + 12, "HMI POWER AND NETWORK", 13, bold=True)]
    for segment in sheet.segments:
        tip = escape(" · ".join(b for b in (segment.wire, segment.color, segment.gauge) if b))
        parts.append(f"<g><title>{tip}</title>" + _line(segment.x1, segment.y1, segment.x2, segment.y2, 1.6)
                     + "</g>")
    for box in sheet.boxes:
        parts.append(_rect(box.x, box.y, box.w, box.h, sw=1.6, fill="#ffffff"))
        parts.append(_text(box.x + 8, box.y + 18 if box.h > 30 else box.y + 19, box.tag, 12, bold=True))
        if box.h > 30:
            for i, line in enumerate(_wrap(box.callout, int((box.w - 16) / 6.2))[:2]):
                parts.append(_text(box.x + 8, box.y + 36 + i * 13, line, 10))
    amps = entry["power_w"] / 24.0
    hmi_lines = [f"24 VDC, about {entry['power_w']} W ({amps:.2f} A)", f"Port: {entry['comms'][0]}",
                 f"Catalog {entry['catalog_number']}"]
    for i, line in enumerate(hmi_lines):
        parts.append(_text(528, 196 + i * 14 + 40, _clip(line, 40), 10))
    parts += [_text(306, 144, "+24V", 10, mono=True), _text(306, 194, "0V", 10, mono=True),
              _text(196, 300, "PE", 10, mono=True), _text(656, 400, "ETHERNET", 10, mono=True)]
    if not psu:
        parts.append(_text(88, 252, "Not on cabinet yet - add one", 10, fill="#8a1c1c"))
    if not peer:
        parts.append(_text(528, 585, "No PLC / switch on cabinet yet", 10, fill="#8a1c1c"))
    parts.append(_text(80, 545, _clip(f"Size the 24 VDC supply and its fuse for this HMI plus everything else on "
                                      f"the 24 V rail ({entry['power_w']} W here).", 110), 10, fill="#444444"))
    # Conductor list (every conductor: wire #, from - to, color, gauge).
    y = 650.0
    parts.append(_text(60, y, "HMI CONDUCTORS", 11, bold=True))
    cols = ((60, "Wire #", 10), (160, "From", 20), (330, "To", 22), (520, "Color", 26), (750, "Gauge", 10))
    y += 20
    for x, head, _n in cols:
        parts.append(_text(x, y, head, 10, bold=True))
    parts.append(_line(60, y + 5, 900, y + 5, 0.8))
    for r in _conductors(project, design, entry):
        y += 20
        for (x, _head, n), value in zip(cols, (r.wire, r.from_label, r.to_label, r.color, r.gauge)):
            parts.append(_text(x, y, _clip(value, n + 6), 10, mono=True))
    y += 30
    for line in _wrap("Colors follow NFPA 79 practice (DC control blue, DC common white/blue, PE green/yellow). "
                      "Ground the Ethernet shield at one end only unless the maker says otherwise.", 140)[:2]:
        parts.append(_text(60, y, line, 9.5, fill="#444444"))
        y += 13
    for line in _wrap(SAFETY_NOTE, 140):
        parts.append(_text(60, y + 6, line, 10, bold=True, fill="#8a1c1c"))
        y += 14
    rows = tag_table(design, project)
    parts.append(_tag_table_markup(rows[:WIRING_TAG_ROWS], 930.0, BODY_TOP + 12, wide=False))
    if len(rows) > WIRING_TAG_ROWS:
        parts.append(_text(930, BODY_BOTTOM - 4, f"+ {len(rows) - WIRING_TAG_ROWS} more rows on the next sheet",
                           10, fill="#444444"))
    return "".join(parts)


def _alarm_markup(design, project) -> str:
    rows = alarm_rows(design, project)
    x0, y = 60.0, BODY_TOP + 12
    cols = ((0, "Priority", 12), (140, "Tag", 30), (380, "Message", 80), (1040, "Class", 40))
    parts = [_text(x0, y, "HMI ALARM LIST  (1 = High, 2 = Medium, 3 = Low)", 13, bold=True)]
    y += 26
    for dx, head, _n in cols:
        parts.append(_text(x0 + dx, y, head, 10, bold=True))
    parts.append(_line(x0, y + 5, PAGE_W - 60, y + 5, 0.8))
    for r in rows[:ALARM_ROWS]:
        y += TAG_PITCH
        fill = "#8a1c1c" if r["priority"].startswith("1") else "#000000"
        for (dx, _head, n), value in zip(cols, (r["priority"], r["tag"], r["message"], r["class"])):
            parts.append(_text(x0 + dx, y, _clip(value, n), 9.5, mono=True, fill=fill))
    if len(rows) > ALARM_ROWS:
        y += TAG_PITCH
        parts.append(_text(x0, y, f"+ {len(rows) - ALARM_ROWS} more - see the HMI tag CSV export.", 10,
                           fill="#444444"))
    y = max(y + 30, 820.0)
    parts.append(_text(x0, y, "Safety alarms only REPORT the state of hardwired safety devices.", 11, bold=True,
                       fill="#8a1c1c"))
    parts.append(_text(x0, y + 16, SAFETY_NOTE, 10, bold=True, fill="#8a1c1c"))
    return "".join(parts)


def _tag_table_markup(rows: list[dict], x0: float, y0: float, *, wide: bool) -> str:
    if wide:
        cols = ((0, "Screen", 18), (150, "Object", 40), (480, "Tag", 36), (780, "R/W", 5), (840, "PLC address", 60))
        right = PAGE_W - 60
    else:
        cols = ((0, "Screen", 14), (95, "Object", 28), (275, "Tag", 26), (445, "R/W", 5), (495, "PLC address", 34))
        right = x0 + 740
    parts = [_text(x0, y0, "HMI TAG TABLE", 11, bold=True)]
    y = y0 + 20
    for dx, head, _n in cols:
        parts.append(_text(x0 + dx, y, head, 10, bold=True))
    parts.append(_line(x0, y + 5, right, y + 5, 0.8))
    if not rows:
        parts.append(_text(x0, y + 22, "No tagged objects yet.", 10))
    for r in rows:
        y += TAG_PITCH
        values = (r["screen"], r["object"], r["tag"], r["access"][:1], r["address"])
        for (dx, _head, n), value in zip(cols, values):
            parts.append(_text(x0 + dx, y, _clip(value, n), 9.5, mono=True))
    return "".join(parts)
