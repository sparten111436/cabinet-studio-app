"""Layout and schematic sheets drawn from one cabinet project.

The open cabinet is the only source of truth. A device keeps the tag,
position, catalog, wire numbers, landings, and PLC address already stored
on it. Nothing in here invents a part number or a conductor.

Schematic lines are orthogonal and stay in the gutters. A shared wire
number is drawn only when that route does not cross another line or a
block. Anything else becomes an on-page connector, or an off-page arrow
when the other end is on a different sheet. Every stored wire number keeps
from/to (color/gauge) on the device for hover popups. On schematic sheets,
only coil tag/name text stays on the canvas; wire numbers, FROM-TO, color,
gauge, landings, and device callouts are hover-only. Printable Wire
Schedule sheet(s) carry Wire# · Color · Gauge · From → To for every
Power/Control conductor (including PE). This is a design aid, not a
certified UL 508A drawing.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from cabinet_studio.models.project import (
    DEFAULT_BACKPLATE_HEIGHT_IN,
    DEFAULT_BACKPLATE_WIDTH_IN,
    DEFAULT_ENCLOSURE_HEIGHT_IN,
    DEFAULT_ENCLOSURE_WIDTH_IN,
    PlacedItem,
    Project,
)
from cabinet_studio.models.schema import Library
from cabinet_studio.services.paths import saves_directory
from cabinet_studio.services.placement import tile_size
from cabinet_studio.services.wiring_assist import conductor_spec, resolve_wire_color, resolve_wire_gauge
from cabinet_studio.services.enclosure_select import apply_enclosure_selection

DISCLAIMER = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."

# Printable sheets: ANSI B / tabloid 11×17 landscape (17" wide × 11" tall).
# User units ≈ 100 dpi so viewBox 1700×1100 maps cleanly to inches.
PAGE_W = 1700
PAGE_H = 1100
TITLE_TOP = 940
ROW_Y = 200
BLOCK_W = 520
BLOCK_H = 168
ORIGIN_X = 48
COL_GAP = 120
# Ladder schematics: multiple device rungs per sheet (classic look).
MAX_COLS = 4  # kept name for tests; means max rungs per schematic sheet
MAX_RUNGS = MAX_COLS
MAX_CONNECTORS = 6
MAX_WIRE_ROWS = 3
CHANNEL_PITCH = 24
# Compact schematic symbols on a ladder (not layout cards).
SCHEM_W = 136.0
SCHEM_H = 56.0
RAIL_X = 48.0
RUNG_X = 130.0
# Draftsman spacing: expand DOWN; pitch = symbol height + inter-rung gap.
# Extra 11×17 height gives more clearance so wire refs never kiss the glyph.
INTER_RUNG_GAP = 168.0
RUNG_PITCH = SCHEM_H + INTER_RUNG_GAP  # ≈224; readable on 11×17
SCHEM_TOP = 72.0
# Return rail x. Ladder trunk sits past the callout band (see _ladder_trunk_x).
RIGHT_BUS_X = 1180.0
# Callout ends at trunk_x − CALLOUT_TRUNK_GAP; trunk = box.right + TRUNK_OFFSET.
# Wider offset = room for wrapped callout before connectors (no text through trunk).
TRUNK_OFFSET = 280.0
CALLOUT_TRUNK_GAP = 18.0
PE_BUS_GAP = 32.0  # dedicated PE bar offset below power return foot
SELECTED_STRIP_TOP = 36
SELECTED_STRIP_HEIGHT = 96
CALLOUT_GAP = 44
MIN_LAYOUT_EDGE = 72.0
LAYOUT_LABEL_PAD = 18.0
FONT_TAG = 17
FONT_LINE = 13
FONT_CALLOUT = 12
FONT_WIRE = 11
FONT_CONNECTOR = 11
FONT_LABEL = 12
# Clear gap so glyphs sit to the RIGHT of vertical strokes and AFTER arrow tips.
LABEL_LINE_GAP = 12
ARROW_TIP_GAP = 8
ARROW_SHAFT = 18
ARROW_HEAD = 10
PAGE_RIGHT = PAGE_W - 28.0  # keep glyphs inside white sheet / inner border
# Symbol → callout gutter (shop print: text never starts on the glyph).
# Must sit RIGHT of T-lead risers (t_lead_stub) by >= LABEL_LINE_GAP.
CALLOUT_AFTER_SYMBOL = 64.0
# Horizontal offset from device right edge to post-DISC load tee (must match _route_ladder).
LOAD_TEE_STUB = 14.0

# Printable Wire Schedule (Draftsman SPEC): table sheets, schematics stay sparse.
WIRE_SCHEDULE_KIND = "wire-schedule"
WIRE_SCHEDULE_ROWS = 30          # ~28–32 rows/sheet
WIRE_SCHEDULE_ROW_PITCH = 24.0  # ≥22pt
WIRE_SCHEDULE_TOP = 56.0
SIGNAL_TYPES = {"sensor", "transmitter", "ethernet_switch"}

POWER_TYPES = {"motor", "vfd", "power_supply", "contactor"}
POWER_RANK = {"power_supply": 0, "vfd": 1, "contactor": 2, "motor": 3}
CONTROL_RANK = {
    "plc": 0,
    "io_module": 1,
    "ethernet_switch": 2,
    "hmi": 3,
    "safety_relay": 4,
    "estop": 5,
    "pushbutton": 6,
    "light": 7,
    "sensor": 8,
    "transmitter": 9,
    "valve": 10,
    "solenoid": 11,
}
GROUND_TOKENS = {"PE", "GND", "GROUND"}
GLUE_TOKENS = {"AND", "OR", "TO", "THE", "FROM", "ON", "WITH", "A"}
FALLBACK_CALLOUT = {
    "seal_in": "Seal-in control rung for the coil and pushbuttons stored here.",
    "plc": "Runs the logic for the I/O stored on this panel.",
    "hmi": "Operator display for this cabinet. It does not switch power.",
    "vfd": "Feeds the motor at the voltage stored on this drive.",
    "motor": "Motor load. Leads are only the ones stored here.",
    "contactor": "Switches the load at the coil voltage stored here.",
    "estop": "Opens the safety circuit stored on this device.",
    "ethernet_switch": "Ties together the network devices stored here.",
    "power_supply": "Makes the control voltage stored on this supply.",
    "sensor": "Field sensor at the PLC address stored on this device.",
    "valve": "Valve moved by the coil voltage stored here.",
    "solenoid": "Solenoid coil at the voltage stored on this device.",
    "light": "Indicator lit by the output stored on this device.",
    "safety_relay": "Safety relay for the function stored on this device.",
    "transmitter": "Transmitter loop at the signal stored on this device.",
    "io_module": "I/O module for the points stored on this device.",
    "pushbutton": "Operator button landed on the input stored here.",
}
DISCONNECT_CALLOUT = "Recorded disconnect. No catalog number is stored."
GROUND_CALLOUT = "Ground or PE already stored on this cabinet."
ROUTING_NOTE = (
    "Every stored wire number is labeled with from/to. A conductor is drawn "
    "only for a shared wire number that routes without crossing. Other shared "
    "numbers use connectors. Unmatched numbers stay labeled; the far end is "
    "not identified. Landings are quoted, not expanded into pins."
)
NOT_IDENTIFIED = "not identified"
CATALOG_NOT_IDENTIFIED = "catalog not identified"
OUTLINE_W = 220.0
OUTLINE_H = 168.0
OUTLINE_GAP = 24.0
OUTLINE_PLAIN = {
    "power_supply": "DIN-rail control power supply",
    "plc": "programmable logic controller",
    "io_module": "discrete I/O module",
    "vfd": "variable-frequency drive",
    "contactor": "IEC power contactor",
    "motor": "three-phase motor",
    "safety_relay": "safety monitoring relay",
    "estop": "emergency-stop operator",
    "pushbutton": "panel pushbutton operator",
    "sensor": "field sensor",
    "disconnect": "disconnecting means",
    "ground": "ground / PE reference",
    "hmi": "operator interface panel",
    "ethernet_switch": "industrial Ethernet switch",
    "light": "indicator / stack light",
    "valve": "solenoid valve",
    "solenoid": "solenoid coil",
    "transmitter": "process transmitter",
}


class DrawingError(Exception):
    """The cabinet cannot be drawn, or the sheets could not be written."""


@dataclass
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float
    wire: str = ""
    color: str = ""
    gauge: str = ""


@dataclass
class Connector:
    box_key: str
    kind: str
    wire: str
    label: str
    x: float = 0
    y: float = 0
    # Right-pointing keep labels after the tip and clear of the shaft.
    arrow_dir: str = "right"


@dataclass
class ConnectionRow:
    wire: str
    from_label: str
    to_label: str
    color: str = ""
    gauge: str = ""


@dataclass
class WireScheduleRow:
    """One printable From→To hop on a Wire Schedule sheet."""
    wire: str
    color: str
    gauge: str
    from_label: str
    to_label: str
    circuit: str
    notes: str = ""


@dataclass
class Box:
    key: str
    tag: str
    role: str
    callout: str
    lines: list[str]
    x: float = 0
    y: float = 0
    w: float = BLOCK_W
    h: float = BLOCK_H
    wires: list[str] = field(default_factory=list)
    landing: str = ""
    connections: list[ConnectionRow] = field(default_factory=list)
    io_address: str = ""
    model_x: float | None = None
    model_y: float | None = None
    type_id: str = ""
    # Suggested hardware outline (catalog from verified library source_url only).
    outline_maker: str = ""
    outline_catalog: str = ""
    outline_plain: str = ""
    outline_source_url: str = ""
    outline_x: float | None = None
    outline_y: float | None = None
    library_id: str | None = None
    # Layout mounting hint from item.fields["mounting"] (door vs backplate).
    mounting: str = ""
    # Owning PLC tag when the device stores parent_tag (multi-PLC cabinets).
    parent_tag: str = ""
    # Stored contact type: True => NC glyph (from contact_config / function, not tag alone).
    contact_nc: bool = False
    # Seal-in composite: [STOP_tag, START_tag, COIL_tag]
    members: list[str] = field(default_factory=list)
    # Panel-layout outline facts (poles, terminal_count, color, function, ...); layout sheets only.
    layout_spec: dict[str, str] = field(default_factory=dict)


@dataclass
class Sheet:
    kind: str
    title: str
    boxes: list[Box] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    connectors: list[Connector] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    labels: list[tuple[float, float, str]] = field(default_factory=list)
    drawn_wires: set[str] = field(default_factory=set)
    panel: tuple[float, float, float, float] | None = None
    plate: tuple[float, float] | None = None
    number: int = 0
    total: int = 0
    selected_tag: str = ""
    selected_connections: list[ConnectionRow] = field(default_factory=list)
    # When True this sheet only carries the engineered hardware outline.
    outline_only: bool = False
    # Wire Schedule table rows (kind == wire-schedule only).
    schedule_rows: list[WireScheduleRow] = field(default_factory=list)
    schedule_page: int = 0  # 1-based index within the wire-schedule set
    schedule_pages: int = 0
    # Layout-only power reference: {"in": supply text, "out": field power text, "out_tag": strip tag}.
    power_io: dict[str, str] = field(default_factory=dict)


@dataclass
class _Net:
    token: str
    indices: list[int]
    channel: int = 0

    @property
    def span(self) -> tuple[int, int]:
        return self.indices[0], self.indices[-1]


def slugify(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip().lower())
    slug = "-".join(part for part in cleaned.split("-") if part)
    return slug or "cabinet"


def default_drawings_folder(project: Project, save_path: Path | str | None = None) -> Path:
    """Drawings sit next to a saved cabinet, or in the saves area when it is new."""
    slug = slugify(project.name)
    if save_path:
        return Path(save_path).expanduser().resolve().parent / "drawings" / slug
    return saves_directory() / "drawings" / slug


def wire_tokens(raw: str) -> list[str]:
    found: list[str] = []
    for part in re.split(r"[,;\s]+", raw or ""):
        token = part.strip().strip(".").upper()
        if not token or token in GLUE_TOKENS or token in found:
            continue
        found.append(token)
    return found




def _ladder_trunk_x(box: Box) -> float:
    """Vertical connector trunk: past callout band, left of return rail."""
    return min(box.x + box.w + TRUNK_OFFSET, float(RIGHT_BUS_X) - 40)


def _ladder_callout_right(box: Box) -> float:
    """Right clip edge for one-line ladder callouts (never through the trunk)."""
    return _ladder_trunk_x(box) - CALLOUT_TRUNK_GAP

def device_tag(item: PlacedItem) -> str:
    tag = item.fields.get("tag", "").strip()
    return tag or item.id



def box_hover_detail(box: Box) -> str:
    """Multi-line popup text for drawing hover (type, tag, wires, color/gauge, FROM-TO, I/O, callout)."""
    type_label = (box.type_id or box.role or "device").replace("_", " ").strip().title() or "Device"
    if box.role == "disconnect":
        type_label = "Disconnect"
    elif box.role == "ground":
        type_label = "Ground / PE"
    elif box.role == "seal_in":
        type_label = "Seal-in rung"
    lines = [f"Device: {box.tag or '(no tag)'}", f"Type: {type_label}"]
    if box.callout:
        lines.append(f"Callout: {box.callout}")
    if box.io_address and _usable_address(box.io_address):
        lines.append(f"I/O: {box.io_address}")
    if box.parent_tag:
        lines.append(f"Parent: {box.parent_tag}")
    if box.landing:
        lines.append(f"Landings: {box.landing}")
    if box.wires:
        lines.append("Wires: " + ", ".join(box.wires[:12]))
    if box.connections:
        lines.append("FROM - TO:")
        for row in box.connections[:8]:
            color = (row.color or "—").strip() or "—"
            gauge = (row.gauge or "—").strip() or "—"
            lines.append(
                f"  {row.wire}  {color}  {gauge}  {row.from_label} -> {row.to_label}"
            )
    return "\n".join(lines)


# Coil symbols keep tag/name on the sheet; everything else is hover-only.
COIL_TYPE_IDS = frozenset({"contactor", "solenoid", "seal_in", "safety_relay", "valve"})
_STRUCTURAL_RUN_LABELS = frozenset({
    "LINE", "RETURN", "PE BAR", "PE", "FU", "L1", "L2", "L3", "N",
    "+24V", "+24", "0V", "CTL+", "CTL-", "GND", "GROUND",
})


def _is_coil_box(box: Box) -> bool:
    """True when the on-sheet coil description (tag/name) should stay visible."""
    if (box.role or "").lower() == "seal_in":
        return True
    return (box.type_id or "").lower() in COIL_TYPE_IDS


def _is_structural_run_label(text: str) -> bool:
    """Rail / fuse / voltage headers stay on the ladder; wire# / landing / peer text do not."""
    raw = (text or "").strip()
    if not raw:
        return False
    if raw in _STRUCTURAL_RUN_LABELS or raw.upper() in _STRUCTURAL_RUN_LABELS:
        return True
    # e.g. "480 VAC  (L1/L2/L3)" or bare control voltage "24 VDC"
    if "L1/L2/L3" in raw or raw.startswith("POWER IN"):
        return True
    if re.search(r"^\d+\s*V(AC|DC)?\b", raw, re.I):
        return True
    # Never treat wire numbers (W10, W10 · BLK · 14 AWG) as structural.
    if re.match(r"^W\d+", raw, re.I):
        return False
    return False



def build_sheets(
    project: Project,
    library: Library,
    selected_id: str | None = None,
) -> list[Sheet]:
    """Return the layout and schematic sheets for this cabinet. Empty if it has no devices."""
    if not project.items:
        return []
    apply_enclosure_selection(project)
    selected_item = project.find(selected_id) if selected_id else None
    selected_tag = device_tag(selected_item) if selected_item is not None else ""
    sheets = _layout_sheets(project, library)
    sheets.extend(_schematic_sheets(project, library, "power", selected_tag))
    sheets.extend(_schematic_sheets(project, library, "control", selected_tag))
    # Provisional numbers so Wire Schedule Notes can say See SH{n}; appends below
    # keep these power/control indices stable.
    for index, sheet in enumerate(sheets, start=1):
        sheet.number = index
        sheet.total = len(sheets)
    _link_layout_sheets([sheet for sheet in sheets if sheet.kind == "layout"])
    _annotate_connections(project, sheets)
    _apply_conductor_specs(project, sheets)
    # Snapshot full From→To rows BEFORE place_wire_rows truncates hover lists.
    schedule_rows = _collect_wire_schedule_rows(project, sheets)
    sheets.extend(_wire_schedule_sheets(project, schedule_rows))
    sheets.extend(_outline_overflow_sheets(sheets))
    total = len(sheets)
    for index, sheet in enumerate(sheets, start=1):
        sheet.number = index
        sheet.total = total
    for sheet in sheets:
        if sheet.kind == "layout" or sheet.outline_only or sheet.kind == WIRE_SCHEDULE_KIND:
            sheet.selected_tag = ""
            sheet.selected_connections = []
            continue
        if selected_tag and any(box.tag == selected_tag for box in sheet.boxes):
            selected_box = next(box for box in sheet.boxes if box.tag == selected_tag)
            sheet.selected_tag = selected_tag
            sheet.selected_connections = list(selected_box.connections)
    _link_wires(sheets)
    _link_io(sheets)
    for sheet in sheets:
        _place_wire_rows(sheet)
        _position_connectors(sheet)
    from cabinet_studio.services.hmi_drawings import hmi_sheets

    hmi = hmi_sheets(project)
    if hmi:
        sheets.extend(hmi)
        for index, sheet in enumerate(sheets, start=1):
            sheet.number = index
            sheet.total = len(sheets)
    from cabinet_studio.services.io_drawings import io_list_sheets

    io_list = io_list_sheets(project)
    if io_list:
        at = max((i + 1 for i, s in enumerate(sheets) if s.kind == WIRE_SCHEDULE_KIND), default=len(sheets))
        sheets[at:at] = io_list
        for index, sheet in enumerate(sheets, start=1):
            sheet.number = index
            sheet.total = len(sheets)
    return sheets


def render_svg(sheet: Sheet, project: Project) -> str:
    """Emit one printable SVG. All sheets are 11×17 landscape (17in × 11in)."""
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="17in" height="11in" '
        f'viewBox="0 0 {PAGE_W} {PAGE_H}">',
        f"<title>{escape(project.name)} - Sheet {sheet.number} of {sheet.total} - {escape(sheet.title)}</title>",
        f"<desc>{escape(DISCLAIMER)}</desc>",
        "<defs><style type=\"text/css\"><![CDATA["
        "@page { size: 17in 11in; margin: 0; } "
        "svg { width: 17in; height: 11in; }"
        "]]></style></defs>",
        f'<rect x="0" y="0" width="{PAGE_W}" height="{PAGE_H}" fill="#ffffff"/>',
        _border_markup(),
    ]
    if sheet.kind.startswith("hmi-"):
        from cabinet_studio.services.hmi_drawings import hmi_sheet_markup

        parts.append(hmi_sheet_markup(sheet, project))
        parts.append(_title_markup(sheet, project))
        parts.append("</svg>")
        parts.append("")
        return "\n".join(parts)
    if sheet.kind == "io-list":
        from cabinet_studio.services.io_drawings import io_list_markup

        parts.append(io_list_markup(sheet, project))
        parts.append(_title_markup(sheet, project))
        parts.append("</svg>")
        parts.append("")
        return "\n".join(parts)
    if sheet.kind == WIRE_SCHEDULE_KIND:
        parts.append(_wire_schedule_markup(sheet, project))
        parts.append(_title_markup(sheet, project))
        parts.append("</svg>")
        parts.append("")
        return "\n".join(parts)
    layout = sheet.kind == "layout"
    if layout:
        parts.append(_panel_markup(project, sheet))
        # Wire ducts and DIN rail strips sit behind device footprints (z-order).
        parts.append(_layout_wire_ducts_markup(project, sheet))
        parts.append(_layout_din_rails_markup(sheet, project))
    # Selected FROM-TO strip is hover-only (box.connections / box_hover_detail).
    # Layout sheets keep only gutter off-page stems (empty wire), not schematic trunks.
    for segment in sheet.segments:
        if layout and (segment.wire or "").strip():
            continue
        tip_bits = [segment.wire or "conductor"]
        if segment.color:
            tip_bits.append(segment.color)
        if segment.gauge:
            tip_bits.append(segment.gauge)
        wire_tip = escape(" · ".join(tip_bits))
        color_attr = f' data-color="{escape(segment.color)}"' if segment.color else ""
        gauge_attr = f' data-gauge="{escape(segment.gauge)}"' if segment.gauge else ""
        parts.append(
            "<g>"
            f"<title>{wire_tip}</title>"
            "<line "
            f'x1="{_num(segment.x1)}" y1="{_num(segment.y1)}" '
            f'x2="{_num(segment.x2)}" y2="{_num(segment.y2)}" '
            f'stroke="#000000" stroke-width="1.6" data-wire="{escape(segment.wire)}"'
            f"{color_attr}{gauge_attr}/>"
            "</g>"
        )
    door_boxes: list[Box] = []
    for box in sheet.boxes:
        if sheet.outline_only:
            parts.append(_outline_markup(box))
        elif layout:
            if _layout_is_door_mount(box):
                door_boxes.append(box)
            else:
                parts.append(_layout_device_markup(box))
        else:
            parts.append(_box_markup(sheet, box))
            # Wire · Color · Gauge · From · To is hover-only (see box_hover_detail).
    if layout:
        parts.append(_layout_door_region_markup(sheet, door_boxes))
        parts.append(_layout_power_io_markup(project, sheet))
        parts.append(_layout_scale_markup(project, sheet))
    for connector in sheet.connectors:
        parts.append(_connector_markup(connector))
    for x, y, label in sheet.labels:
        # Schematics: only rail/fuse/voltage headers on canvas; wire# / landing / peer → hover.
        if sheet.kind in {"power", "control"} and not _is_structural_run_label(label):
            continue
        parts.append(
            f'<text class="run-label" x="{_num(x)}" y="{_num(y)}" font-family="Consolas, Liberation Mono, monospace" '
            f'font-size="{FONT_LABEL}" fill="#000000">{escape(label)}</text>'
        )
    parts.append(_title_markup(sheet, project))
    parts.append("</svg>")
    parts.append("")
    return "\n".join(parts)




def _circuit_label(wire: str, sheet_kind: str, type_id: str, role: str) -> str:
    """Circuit column value: LINE / +24V / 0V / PE / signal / control / …"""
    token = (wire or "").strip().upper()
    if token in GROUND_TOKENS:
        return "PE"
    if token in {"L1", "L2", "L3", "LINE", "L", "HOT"}:
        return "LINE"
    if token == "N":
        return "N"
    if token.startswith("T") and len(token) > 1 and token[1:].isdigit():
        return "LINE"
    if token in {"+24V", "+24", "24V", "24VDC", "V+", "DC+"}:
        return "+24V"
    if token in {"0V", "0VDC", "V-", "DC-", "COM", "COMMON"}:
        return "0V"
    tid = (type_id or role or "").lower()
    if tid in SIGNAL_TYPES or token.startswith("ETH") or "SIG" in token:
        return "signal"
    if tid == "ground":
        return "PE"
    if sheet_kind == "power" or tid in POWER_TYPES or tid == "disconnect":
        return "LINE"
    return "control"


def _circuit_group(circuit: str) -> int:
    """Sort groups: Power → PE → Control → Signal."""
    c = (circuit or "").strip()
    if c in {"LINE", "N", "L1", "L2", "L3"}:
        return 0
    if c == "PE":
        return 1
    if c == "signal":
        return 3
    return 2  # +24V / 0V / control


def _wire_sort_key(row: WireScheduleRow) -> tuple:
    group = _circuit_group(row.circuit)
    text = (row.wire or "").strip()
    match = re.match(r"^([A-Za-z]*)(\d+)(.*)$", text)
    if match:
        prefix, digits, suffix = match.group(1), int(match.group(2)), match.group(3)
        return (group, prefix.upper(), digits, suffix.upper(), row.from_label, row.to_label)
    return (group, text.upper(), 0, "", row.from_label, row.to_label)


# Terminal tokens for Wire Schedule TAG-TERM (shop-print short form).
# Use non-word lookarounds (not \b) so L+/+24V/V- match next to spaces and punctuation.
_TERM_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"L[1-3]|N|PE|GND|EGC|"
    r"T[1-3]|[UVW]|"
    r"A[12]|B[12]|S\d{1,2}|CH\d{1,2}|"
    r"\+24V|\+24|0V|24V|V\+|V-|"
    r"L\+|L-|COM|COMMON|NO|NC|"
    r"DI\d+|DO\d+|AI\d+|AO\d+|BKPL"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
# Explicit "TERM (W###)" in a landing clause.
_TERM_FOR_WIRE_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z+][A-Za-z0-9+]{0,6})\s*\(\s*(W\d+|PE|GND|GROUND|L[1-3]|N)\s*\)",
    re.IGNORECASE,
)
_TAG_TERM_RE = re.compile(r"^[A-Za-z0-9_]+-[A-Za-z0-9+]+$")
_PE_COLOR_OK = {"green", "green-yellow", "green/yellow", "green yellow", "gn/ye", "gn-ye"}
_SOURCE_ROLE_RANK = {
    "disconnect": 0,
    "ground": 1,
    "power_supply": 2,
    "plc": 4,
    "io_module": 5,
    "safety_relay": 6,
    "estop": 6,
    "contactor": 7,
    "vfd": 7,
    "motor": 8,
    "solenoid": 8,
    "valve": 8,
    "sensor": 8,
    "transmitter": 8,
    "pushbutton": 7,
    "light": 8,
    "hmi": 5,
    "ethernet_switch": 5,
}


def _endpoint_tag(label: str) -> str:
    """Tag portion of 'TAG / terminal' or 'TAG-TERM' (or whole label)."""
    raw = (label or "").strip()
    if not raw or raw == NOT_IDENTIFIED:
        return ""
    if " / " in raw:
        return raw.split(" / ", 1)[0].strip()
    if "/" in raw and " " not in raw.split("/", 1)[0]:
        return raw.split("/", 1)[0].strip()
    # TAG-TERM short form
    if "-" in raw and " " not in raw:
        return raw.split("-", 1)[0].strip()
    return raw.split()[0].strip() if raw else ""


def _split_to_peers(to_label: str) -> list[str]:
    """Split multi-peer to_label into one peer string each."""
    raw = (to_label or "").strip()
    if not raw or raw == NOT_IDENTIFIED:
        return [raw or NOT_IDENTIFIED]
    parts = re.split(r",\s*(?=[A-Za-z0-9_][A-Za-z0-9_\-./]*\s*(?:/|$))", raw)
    cleaned = [part.strip() for part in parts if part.strip()]
    return cleaned or [raw]


def _normalize_term_token(val: str) -> str:
    """Canonical shop-print terminal spelling."""
    raw = (val or "").strip()
    if not raw:
        return ""
    upper = raw.upper().replace("＋", "+")
    if upper in GROUND_TOKENS or upper in {"PE", "GND", "EGC", "GROUND"}:
        return "PE"
    if upper in {"+24", "+24V"}:
        return "+24V"
    if upper == "24V":
        return "24V"
    if upper == "COMMON":
        return "COM"
    if upper == "V+":
        return "V+"
    if upper == "V-":
        return "V-"
    return upper


def _term_preference_score(term: str, tag: str, type_hint: str = "") -> int:
    """Higher = better TERM for this TAG (PSU wants +24V; PLC wants L+/24V/BKPL)."""
    t = _normalize_term_token(term)
    if not t:
        return -100
    tag_u = (tag or "").upper()
    hint = (type_hint or "").lower()
    score = 1
    is_psu = tag_u.startswith("PSU") or hint == "power_supply"
    is_plc = tag_u.startswith("PLC") or hint == "plc"
    is_io = hint == "io_module" or tag_u.startswith(("DI", "DO", "AI", "AO"))
    is_pb = hint in {"pushbutton", "estop"} or "RESET" in tag_u
    if is_psu:
        if t in {"+24V", "0V"}:
            score += 12
        elif t in {"L1", "L2", "L3", "N"}:
            score += 8
        elif t in {"L+", "L-", "24V"}:
            score -= 4  # PLC-side pins on a shared landing
    if is_plc:
        if t in {"L+", "L-", "COM", "BKPL", "24V", "0V"}:
            score += 12
        elif t == "+24V":
            score += 4
    if is_io:
        if t.startswith(("DI", "DO", "AI", "AO")) or t in {"COM", "24V", "0V", "BKPL"}:
            score += 10
    if is_pb:
        if t in {"NO", "NC", "COM", "24V", "0V"}:
            score += 10
    if hint == "safety_relay" and t in {"A1", "A2", "S11", "S12", "S21", "S22", "13", "14"}:
        score += 10
    if hint == "disconnect" or tag_u.startswith("DISC"):
        if t in {"L1", "L2", "L3", "N", "T1", "T2", "T3", "LOAD"}:
            score += 10
    return score


def _infer_default_term(tag: str, landing: str, wire: str, type_hint: str = "") -> str:
    """Last-resort TERM so schedule never emits a bare TAG."""
    text = " ".join((landing or "").split()).lower()
    tag_u = (tag or "").upper()
    hint = (type_hint or "").lower()
    token = (wire or "").strip().upper()
    if token in GROUND_TOKENS or tag_u.startswith("GND") or hint == "ground":
        return "PE"
    if "backplane" in text or "back plane" in text or "backplane" in hint:
        return "BKPL"
    if "reset" in text or "reset" in tag.lower():
        return "NO"
    if re.search(r"\bDISC\s+load\b|\bload\s+feeder\b", text, re.IGNORECASE):
        return "LOAD"
    if any(k in text for k in ("+24", "24v", "l+", "v+")):
        if tag_u.startswith("PSU") or hint == "power_supply":
            return "+24V"
        if tag_u.startswith("PLC") or hint == "plc":
            return "L+"
        return "+24V"
    if any(k in text for k in ("0v", "l-", "v-", "return", "common")):
        if tag_u.startswith("PSU") or hint == "power_supply":
            return "0V"
        if tag_u.startswith("PLC") or hint == "plc":
            return "L-"
        return "COM"
    if tag_u.startswith("PSU") or hint == "power_supply":
        return "+24V"
    if tag_u.startswith("PLC") or hint == "plc":
        return "L+"
    if hint == "pushbutton" or hint == "estop":
        return "NO"
    if hint == "io_module":
        if tag_u.startswith("DO"):
            return "DO1"
        if tag_u.startswith("DI"):
            return "DI1"
        return "COM"
    if hint == "safety_relay":
        return "A1"
    if hint == "contactor" or hint == "relay":
        return "A1"
    if tag_u.startswith("DISC") or hint == "disconnect":
        return "LOAD"
    return "COM"


def _term_from_landing(landing: str, wire: str, tag: str = "", type_hint: str = "") -> str:
    """Extract a short terminal token from landing prose for this wire/tag."""
    text = " ".join((landing or "").split())
    token = (wire or "").strip().upper()
    if token in GROUND_TOKENS:
        return "PE"
    if not text:
        return ""
    # Collect "L1 (W101)" hits for this wire plus all TERM tokens; score by tag.
    candidates: list[str] = []
    for match in _TERM_FOR_WIRE_RE.finditer(text):
        term_candidate, wire_ref = match.group(1), match.group(2).upper()
        if wire_ref == token or (token in GROUND_TOKENS and wire_ref in GROUND_TOKENS):
            candidates.append(_normalize_term_token(term_candidate))
    clauses = [part for part in re.split(r"[,;]", text) if part.strip()]
    if token and token in text.upper():
        prefer = [part for part in clauses if token in part.upper()] or clauses
    else:
        prefer = clauses or [text]
    for part in prefer:
        for hit in _TERM_TOKEN_RE.finditer(part):
            candidates.append(_normalize_term_token(hit.group(1)))
    if not candidates:
        for hit in _TERM_TOKEN_RE.finditer(text):
            candidates.append(_normalize_term_token(hit.group(1)))
    # Drop tokens that are just the tag name repeating (DI1 from "DI1: …" is ok if scored).
    if candidates:
        candidates.sort(key=lambda t: _term_preference_score(t, tag, type_hint), reverse=True)
        best = candidates[0]
        if best:
            return best
    # Phrase inference before empty.
    inferred = _infer_default_term(tag, text, wire, type_hint)
    # Only accept phrase-driven inference here when landing has a clue; role defaults
    # apply later in _schedule_tag_term so bare landings still get a TERM.
    text_l = text.lower()
    if any(
        k in text_l
        for k in (
            "backplane",
            "reset",
            "+24",
            "24v",
            "0v",
            "l+",
            "l-",
            "load feeder",
            "disc load",
            "common",
            "return",
        )
    ):
        return inferred
    if re.search(r"\bDISC\s+load\b|\bload\s+feeder\b", text, re.IGNORECASE):
        return "LOAD"
    return ""


def _schedule_tag_term(
    tag: str,
    landing_or_label: str,
    wire: str,
    type_hint: str = "",
) -> str:
    """Shop-print endpoint: TAG-TERM (never bare TAG / never truncated callout prose)."""
    tag = (tag or "").strip()
    if not tag or tag == NOT_IDENTIFIED:
        return NOT_IDENTIFIED
    # Label may already be "TAG / prose" or "TAG-TERM".
    raw = (landing_or_label or "").strip()
    landing = raw
    hint = (type_hint or "").strip()
    if " / " in raw:
        maybe_tag, landing = raw.split(" / ", 1)
        if maybe_tag.strip():
            tag = maybe_tag.strip()
    elif _TAG_TERM_RE.match(raw):
        return raw  # already TAG-TERM
    term = _term_from_landing(landing, wire, tag=tag, type_hint=hint)
    if not term and raw and raw != tag:
        term = _term_from_landing(raw, wire, tag=tag, type_hint=hint)
    if not term:
        term = _infer_default_term(tag, landing or raw, wire, hint)
    if term:
        return f"{tag}-{term}"
    # Absolute last resort — still never bare TAG.
    return f"{tag}-COM"


def _pe_schedule_color(color: str, project: Project) -> str:
    """PE must be Green or Green-Yellow only (never Blue/Black)."""
    raw = (color or "").strip()
    norm = raw.lower().replace("_", " ").replace("—", "")
    if norm in _PE_COLOR_OK or (norm.startswith("green") and "yellow" in norm):
        if "yellow" in norm:
            return "Green-Yellow" if "green-yellow" in norm.replace("/", "-").replace(" ", "-") or "/" in raw else (
                "Green/Yellow" if "/" in raw else "Green-Yellow"
            )
        if norm == "green" or norm.startswith("green"):
            return "Green" if norm == "green" else raw
    # Resolve from standards with empty device fields so Black/Blue device paints cannot win.
    resolved = resolve_wire_color(project=project, type_id="", fields={}, wire="PE")
    res_norm = (resolved or "").strip().lower()
    if res_norm in _PE_COLOR_OK or res_norm.startswith("green"):
        return resolved.strip()
    return "Green"


def _endpoint_source_rank(tag: str, role: str) -> tuple[int, str]:
    """Lower rank = preferred Wire Schedule From (source side)."""
    role_l = (role or "").lower()
    rank = _SOURCE_ROLE_RANK.get(role_l, 9)
    # Virtual GND / DISC tags without role still sort early by name.
    tag_u = (tag or "").upper()
    if tag_u.startswith("GND") or tag_u in GROUND_TOKENS:
        rank = min(rank, 1)
    if tag_u.startswith("DISC"):
        rank = min(rank, 0)
    if tag_u.startswith("PSU"):
        rank = min(rank, 2)
    return (rank, tag_u)


def _collect_wire_schedule_rows(project: Project, sheets: list[Sheet]) -> list[WireScheduleRow]:
    """One Wire Schedule row per Wire# (canonical From→To), Power/Control incl. PE."""
    # wire -> aggregate
    agg: dict[str, dict] = {}
    role_by_tag: dict[str, str] = {}
    type_by_tag: dict[str, str] = {}
    for sheet in sheets:
        if sheet.kind not in {"power", "control"}:
            continue
        note = f"See SH{sheet.number}" if sheet.number else ""
        for box in sheet.boxes:
            if box.tag:
                # type_id drives TERM inference; role_by_tag keeps prior From/To ranking.
                type_by_tag[box.tag] = (box.type_id or box.role or "").strip()
                role_by_tag[box.tag] = box.role or box.type_id or ""
            for conn in box.connections:
                wire = (conn.wire or "").strip()
                if not wire:
                    continue
                bucket = agg.setdefault(
                    wire,
                    {
                        "endpoints": {},  # tag -> term
                        "color": "",
                        "gauge": "",
                        "circuit": "",
                        "notes": set(),
                        "sheet_kind": sheet.kind,
                        "type_id": box.type_id,
                        "role": box.role,
                    },
                )
                hint = type_by_tag.get(box.tag, box.type_id or box.role or "")
                # From side
                from_tt = _schedule_tag_term(box.tag, conn.from_label, wire, type_hint=hint)
                from_tag = _endpoint_tag(from_tt) or box.tag
                from_term = ""
                if "-" in from_tt and from_tt != NOT_IDENTIFIED:
                    from_term = from_tt.split("-", 1)[1]
                if from_tag and from_tag != NOT_IDENTIFIED:
                    prev = bucket["endpoints"].get(from_tag, "")
                    if from_term and (not prev or _term_preference_score(from_term, from_tag, hint) >= _term_preference_score(prev, from_tag, hint)):
                        bucket["endpoints"][from_tag] = from_term
                    else:
                        bucket["endpoints"].setdefault(from_tag, from_term)
                # Peer sides
                for peer in _split_to_peers(conn.to_label):
                    peer_tag_guess = _endpoint_tag(peer)
                    peer_hint = type_by_tag.get(peer_tag_guess, "")
                    peer_tt = _schedule_tag_term(peer_tag_guess, peer, wire, type_hint=peer_hint)
                    peer_tag = _endpoint_tag(peer_tt)
                    if not peer_tag or peer_tag == NOT_IDENTIFIED:
                        continue
                    if peer_tag not in type_by_tag and peer_hint:
                        type_by_tag[peer_tag] = peer_hint
                    peer_term = peer_tt.split("-", 1)[1] if "-" in peer_tt else ""
                    prev = bucket["endpoints"].get(peer_tag, "")
                    if peer_term and (
                        not prev
                        or _term_preference_score(peer_term, peer_tag, type_by_tag.get(peer_tag, ""))
                        >= _term_preference_score(prev, peer_tag, type_by_tag.get(peer_tag, ""))
                    ):
                        bucket["endpoints"][peer_tag] = peer_term
                    else:
                        bucket["endpoints"].setdefault(peer_tag, peer_term)
                if conn.color and not bucket["color"]:
                    bucket["color"] = conn.color
                if conn.gauge and not bucket["gauge"]:
                    bucket["gauge"] = conn.gauge
                if not bucket["circuit"]:
                    bucket["circuit"] = _circuit_label(wire, sheet.kind, box.type_id, box.role)
                if note:
                    bucket["notes"].add(note)

    rows: list[WireScheduleRow] = []
    for wire, bucket in agg.items():
        endpoints = dict(bucket["endpoints"])
        # Propagate a known term onto DISC/GND when peers share the phase (DISC-L1).
        # Prefer real terminal tokens (L1, T1, …) over placeholder LOAD.
        real_terms = [t for t in endpoints.values() if t and t.upper() != "LOAD"]
        shared_terms = real_terms or [t for t in endpoints.values() if t]
        if shared_terms or wire.upper() in GROUND_TOKENS:
            dominant = shared_terms[0] if shared_terms else "PE"
            for tag, term in list(endpoints.items()):
                role = role_by_tag.get(tag, "")
                tag_u = tag.upper()
                is_disc = role == "disconnect" or tag_u.startswith("DISC")
                is_gnd = role == "ground" or tag_u.startswith("GND") or tag_u in GROUND_TOKENS
                if not (is_disc or is_gnd):
                    continue
                if wire.upper() in GROUND_TOKENS:
                    endpoints[tag] = "PE"
                elif is_disc and (not term or term.upper() == "LOAD"):
                    endpoints[tag] = dominant if dominant.upper() != "PE" else (term or "LOAD")
                elif is_gnd and not term:
                    endpoints[tag] = "PE"

        # Fill any remaining bare tags with role/type defaults (engine-wide).
        for tag, term in list(endpoints.items()):
            if not term:
                endpoints[tag] = _infer_default_term(
                    tag, "", wire, type_by_tag.get(tag, role_by_tag.get(tag, ""))
                )

        ranked = sorted(
            endpoints.items(),
            key=lambda kv: _endpoint_source_rank(kv[0], role_by_tag.get(kv[0], "")),
        )
        if not ranked:
            continue
        if len(ranked) == 1:
            from_tag, from_term = ranked[0]
            to_label = NOT_IDENTIFIED
            from_label = f"{from_tag}-{from_term}" if from_term else from_tag
            via: list[str] = []
        else:
            from_tag, from_term = ranked[0]
            to_tag, to_term = ranked[-1]
            from_label = f"{from_tag}-{from_term}" if from_term else from_tag
            to_label = f"{to_tag}-{to_term}" if to_term else to_tag
            via = [
                f"{tag}-{term}" if term else tag
                for tag, term in ranked[1:-1]
            ]

        circuit = bucket["circuit"] or _circuit_label(wire, bucket["sheet_kind"], bucket["type_id"], bucket["role"])
        color = bucket["color"] or ""
        gauge = bucket["gauge"] or ""
        if circuit == "PE" or wire.upper() in GROUND_TOKENS:
            color = _pe_schedule_color(color, project)
            circuit = "PE"
        notes_parts = sorted(bucket["notes"])
        if via:
            notes_parts.append("via " + ", ".join(via))
        rows.append(
            WireScheduleRow(
                wire=wire,
                color=color,
                gauge=gauge,
                from_label=from_label,
                to_label=to_label,
                circuit=circuit,
                notes="; ".join(notes_parts),
            )
        )
    rows.sort(key=_wire_sort_key)
    return rows


def _wire_schedule_sheets(project: Project, rows: list[WireScheduleRow]) -> list[Sheet]:
    """Paginate schedule rows into 11×17 Wire Schedule sheets."""
    if not rows:
        return []
    pages: list[list[WireScheduleRow]] = []
    for index in range(0, len(rows), WIRE_SCHEDULE_ROWS):
        pages.append(rows[index : index + WIRE_SCHEDULE_ROWS])
    total_pages = len(pages)
    out: list[Sheet] = []
    cabinet = (project.name or "Cabinet").strip() or "Cabinet"
    for page_index, chunk in enumerate(pages, start=1):
        if total_pages > 1:
            title = f"WIRE SCHEDULE — {cabinet}  ·  WIRE {page_index}/{total_pages}"
        else:
            title = f"WIRE SCHEDULE — {cabinet}"
        sheet = Sheet(
            kind=WIRE_SCHEDULE_KIND,
            title=title,
            schedule_rows=list(chunk),
            schedule_page=page_index,
            schedule_pages=total_pages,
            notes=[
                "Printable conductor list for Power and Control schematics. "
                "Schematic canvases stay sparse (symbols + coil tags only)."
            ],
        )
        out.append(sheet)
    return out


def _wire_schedule_markup(sheet: Sheet, project: Project) -> str:
    """SVG table: Wire# Color Gauge From To Circuit Notes (printable text)."""
    cabinet = (project.name or "Cabinet").strip() or "Cabinet"
    page = sheet.schedule_page or 1
    pages = sheet.schedule_pages or 1
    header = f"WIRE SCHEDULE — {cabinet}"
    if pages > 1:
        header = f"{header}    WIRE {page}/{pages}"
    columns = [
        ("Wire#", 36.0, 90.0),
        ("Color", 126.0, 110.0),
        ("Gauge", 236.0, 100.0),
        ("From", 336.0, 300.0),
        ("To", 636.0, 300.0),
        ("Circuit", 936.0, 110.0),
        ("Notes", 1046.0, 610.0),
    ]
    top = WIRE_SCHEDULE_TOP
    pitch = WIRE_SCHEDULE_ROW_PITCH
    table_bottom = TITLE_TOP - 12.0
    parts: list[str] = [
        f'<g class="wire-schedule" data-page="{page}" data-pages="{pages}">',
        f'<text class="wire-schedule-title" x="36" y="{_num(top)}" '
        f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="18" font-weight="700" fill="#000000">'
        f"{escape(header)}</text>",
    ]
    supply = _interview_value(project, "supply_voltage")
    control = _interview_value(project, "control_voltage")
    if supply and control:
        systems = f"{supply} / {control}"
    else:
        systems = supply or control or "—"
    parts.append(
        f'<text class="wire-schedule-systems" x="36" y="{_num(top + 22)}" '
        f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="11" fill="#333333">'
        f"Systems covered: {escape(systems)}</text>"
    )
    header_y = top + 48.0
    row0 = header_y + pitch
    parts.append(
        f'<rect x="28" y="{_num(header_y - 16)}" width="{_num(PAGE_W - 56)}" height="{_num(pitch)}" '
        f'fill="#f0f0f0" stroke="#000000" stroke-width="0.8"/>'
    )
    for label, x, _width in columns:
        parts.append(
            f'<text class="wire-schedule-colhead" x="{_num(x)}" y="{_num(header_y)}" '
            f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="12" font-weight="700" fill="#000000">'
            f"{escape(label)}</text>"
        )
    frame_h = min(table_bottom, row0 + WIRE_SCHEDULE_ROWS * pitch) - (header_y - 16)
    parts.append(
        f'<rect x="28" y="{_num(header_y - 16)}" width="{_num(PAGE_W - 56)}" height="{_num(frame_h)}" '
        f'fill="none" stroke="#000000" stroke-width="1.1"/>'
    )
    for index, row in enumerate(sheet.schedule_rows):
        y = row0 + index * pitch
        if y > table_bottom:
            break
        parts.append(
            f'<line x1="28" y1="{_num(y + 6)}" x2="{_num(PAGE_W - 28)}" y2="{_num(y + 6)}" '
            f'stroke="#cccccc" stroke-width="0.6"/>'
        )
        values = [
            row.wire,
            row.color or "—",
            row.gauge or "—",
            row.from_label,
            row.to_label,
            row.circuit,
            row.notes,
        ]
        for (label, x, width), value in zip(columns, values):
            if label == "Notes":
                note_lines = _wrap(str(value or ""), max(12, int(width / 7)))[:2]
                for line_i, line in enumerate(note_lines or [""]):
                    parts.append(
                        f'<text class="wire-schedule-cell" data-col="Notes" x="{_num(x)}" '
                        f'y="{_num(y - 4 + line_i * 11)}" '
                        f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="10" fill="#000000">'
                        f"{escape(line)}</text>"
                    )
            else:
                clipped = _clip(str(value or ""), max(6, int(width / 7)))
                mono = label in {"Wire#", "Gauge", "Circuit"}
                font = (
                    "Consolas, Liberation Mono, monospace"
                    if mono
                    else "Segoe UI, Liberation Sans, sans-serif"
                )
                parts.append(
                    f'<text class="wire-schedule-cell" data-col="{escape(label)}" '
                    f'data-wire="{escape(row.wire)}" '
                    f'x="{_num(x)}" y="{_num(y)}" '
                    f'font-family="{font}" font-size="11" fill="#000000">'
                    f"{escape(clipped)}</text>"
                )
    parts.append("</g>")
    return "".join(parts)


def write_drawings(
    project: Project,
    library: Library,
    folder: Path | str,
    selected_id: str | None = None,
) -> list[Path]:
    """Write one SVG per sheet. Raises DrawingError when the cabinet has no devices."""
    if not project.items:
        raise DrawingError("This cabinet has no devices. Add devices before generating drawings.")
    sheets = build_sheets(project, library, selected_id=selected_id)
    if not sheets:
        raise DrawingError("This cabinet has no devices. Add devices before generating drawings.")
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    slug = slugify(project.name)
    stale = list(target.glob(f"{slug}-sheet-*.svg"))
    written: list[Path] = []
    for sheet in sheets:
        path = target / f"{slug}-sheet-{sheet.number:02d}-{sheet.kind}.svg"
        path.write_text(render_svg(sheet, project), encoding="utf-8")
        written.append(path)
    keep = {path.resolve() for path in written}
    for old in stale:
        if old.resolve() not in keep:
            old.unlink()
    # Ladder is a separate document — never mixed into schematic SVGs / return list.
    try:
        from cabinet_studio.services.programming import write_ladder_logic

        write_ladder_logic(project, target)
    except Exception:
        pass
    return written


def drawing_issues(sheet: Sheet) -> list[str]:
    """Crossed lines, overlapping collinear lines, or a line through a block."""
    issues: list[str] = []
    segments = sheet.segments
    for index, first in enumerate(segments):
        for second in segments[index + 1 :]:
            same_net = bool(first.wire) and first.wire == second.wire
            if segments_cross(first, second):
                if same_net:
                    continue  # intentional T-junction on a shared feeder
                issues.append(f"Lines cross ({first.wire or 'ref'} and {second.wire or 'ref'}).")
            elif _collinear_overlap(first, second):
                if same_net:
                    continue
                issues.append(f"Lines overlap ({first.wire or 'ref'} and {second.wire or 'ref'}).")
    for segment in segments:
        for box in sheet.boxes:
            if segment_hits_box(segment, box):
                issues.append(f"A line runs through {box.tag}.")
    return issues


def segments_cross(first: Segment, second: Segment, eps: float = 0.6) -> bool:
    o1 = _orient(first.x1, first.y1, first.x2, first.y2, second.x1, second.y1)
    o2 = _orient(first.x1, first.y1, first.x2, first.y2, second.x2, second.y2)
    o3 = _orient(second.x1, second.y1, second.x2, second.y2, first.x1, first.y1)
    o4 = _orient(second.x1, second.y1, second.x2, second.y2, first.x2, first.y2)
    if abs(o1) <= eps or abs(o2) <= eps or abs(o3) <= eps or abs(o4) <= eps:
        return False
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


def segment_hits_box(segment: Segment, box: Box, eps: float = 0.6) -> bool:
    left = box.x + eps
    right = box.x + box.w - eps
    top = box.y + eps
    bottom = box.y + box.h - eps
    if abs(segment.y1 - segment.y2) <= eps:
        y = segment.y1
        if not (top < y < bottom):
            return False
        lo, hi = sorted((segment.x1, segment.x2))
        return hi > left and lo < right
    if abs(segment.x1 - segment.x2) <= eps:
        x = segment.x1
        if not (left < x < right):
            return False
        lo, hi = sorted((segment.y1, segment.y2))
        return hi > top and lo < bottom
    return False


def _layout_sheets(project: Project, library: Library) -> list[Sheet]:
    """One or more elevation sheets. Split and zoom when devices or labels collide.

    Door-mounted devices (PB / ES / HMI) get their own sheet(s) whenever any exist,
    so the DOOR region never mixes with In-cabinet or Field footprints.
    """
    zoned = _zone_layout_sheets(project, library)
    if zoned is not None:
        return zoned
    groups = _partition_layout_items(project, library)
    if not groups:
        return []
    multi = len(groups) > 1
    has_door = any(_item_is_door_mount(i) for i in project.items)
    has_plate = any(not _item_is_door_mount(i) for i in project.items)
    sheets: list[Sheet] = []
    for index, items in enumerate(groups, start=1):
        boxes = [_layout_box(project, library, item) for item in items]
        bp_w, bp_h = _backplate_inches(project)
        is_door = bool(items) and all(_item_is_door_mount(i) for i in items)
        notes = [
            f"Backing plate {bp_w:g} in × {bp_h:g} in scaled onto this 11×17 sheet. "
            "Outlined devices only — wiring lives on the schematic sheets."
        ]
        if is_door:
            notes.append(
                "DOOR elevation — On-door devices only (pushbuttons / e-stops / HMI). "
                "In-cabinet and Field devices are on backplate layout sheets."
            )
        if multi:
            notes.append(
                f"Layout elevation {index} of {len(groups)}. "
                "Devices on other layout sheets continue with off-page arrows."
            )
        if project.notes.strip() and index == 1:
            notes.append("Notes: " + " ".join(project.notes.split()))
        cabinet_name = (project.cabinet_label or project.name or "Cabinet").strip()
        if has_door and has_plate:
            region = "DOOR" if is_door else "BACKPLATE"
            if multi:
                layout_title = f"PANEL LAYOUT — {cabinet_name}  ·  {region} {index}/{len(groups)}"
            else:
                layout_title = f"PANEL LAYOUT — {cabinet_name}  ·  {region}"
        elif multi:
            layout_title = f"PANEL LAYOUT — {cabinet_name}  ·  LAYOUT {index}/{len(groups)}"
        else:
            layout_title = f"PANEL LAYOUT — {cabinet_name}"
        sheet = Sheet(kind="layout", title=layout_title, boxes=boxes, notes=notes)
        _place_layout(project, sheet, zoom_to_content=multi)
        if not is_door and not any(s.power_io for s in sheets):
            from cabinet_studio.services.panel_zones import zone_of

            field_items = [i for i in project.items
                           if zone_of(i.type_id, device_tag(i), i.fields.get("mounting", "")) == "field"]
            _power_entry_marker(project, sheet, False)
            _power_out_marker(sheet, field_items)
        sheets.append(sheet)
    return sheets


def _zone_layout_sheets(project: Project, library: Library) -> list[Sheet] | None:
    """v0.3.25 default: every backplate device on ONE plate, in power zones top to bottom
    (high, mid, low-voltage control, drives with the largest at the very bottom), rows
    spaced for wire duct. Field devices are listed, not drawn on the plate. The DOOR
    sheet is drawn only when the interview did not answer No to a door drawing.
    interview["layout_mode"] = "manual" keeps the hand-placed positions (legacy path)."""
    from cabinet_studio.services.panel_zones import (
        ZONE_TITLES, ZONES, arrange, item_inches, place_with_pins, zone_of,
    )

    interview = project.interview if isinstance(getattr(project, "interview", None), dict) else {}
    if str(interview.get("layout_mode", "")).strip().lower() == "manual":
        return None
    door_off = str(interview.get("door_drawing", "")).strip().lower().startswith("no")
    plate: list[PlacedItem] = []
    door: list[PlacedItem] = []
    field: list[PlacedItem] = []
    zone_by_id: dict[str, str] = {}
    for item in project.items:
        zone = zone_of(item.type_id, device_tag(item), item.fields.get("mounting", ""))
        if zone in {"shell", "duct"}:
            continue
        if _item_is_door_mount(item):
            door.append(item)
        elif zone == "field":
            field.append(item)
        else:
            plate.append(item)
            zone_by_id[item.id] = zone
    if not plate and not door:
        return None
    bp_w, bp_h = _backplate_inches(project)
    cabinet_name = (project.cabinet_label or project.name or "Cabinet").strip()
    show_door = bool(door) and not door_off
    base_note = (f"Backing plate {bp_w:g} in × {bp_h:g} in scaled onto this 11×17 sheet. "
                 "Outlined devices only — wiring lives on the schematic sheets.")
    extra: list[str] = []
    if field:
        extra.append("Field devices (off the plate, wired through terminals): "
                     + ", ".join(device_tag(i) for i in field) + ".")
    if door and door_off:
        extra.append("No door drawing (interview): operator devices "
                     + ", ".join(device_tag(i) for i in door) + " are not drawn.")
    if project.notes.strip():
        extra.append("Notes: " + " ".join(project.notes.split()))
    sheets: list[Sheet] = []

    def title(region: str, index: int = 0, count: int = 1) -> str:
        suffix = f"  ·  {region}" if show_door and plate else ""
        if count > 1:
            suffix = f"  ·  {region} {index}/{count}" if show_door and plate else f"  ·  LAYOUT {index}/{count}"
        return f"PANEL LAYOUT — {cabinet_name}{suffix}"

    def packed_sheet(items: list[PlacedItem], zones: dict[str, str], ttl: str, notes: list[str],
                     backplate: bool = False) -> Sheet | None:
        devices = [(i.id, zones[i.id], *item_inches(library, i)) for i in items]
        pins = {}
        for i in items:
            try:
                pins[i.id] = (float(i.fields["layout_x_in"]), float(i.fields["layout_y_in"]))
            except (KeyError, TypeError, ValueError):
                pass
        bar = backplate and not any(_is_ground_item(i) for i in project.items)
        placed = None
        if bar:
            with_bar = devices + [(PE_BAR_KEY, "low", *PE_BAR_IN)]
            placed = place_with_pins(with_bar, pins, bp_w, bp_h) if pins else arrange(with_bar, bp_w, bp_h)
            bar = placed is not None
        if placed is None:
            placed = place_with_pins(devices, pins, bp_w, bp_h) if pins else arrange(devices, bp_w, bp_h)
        if placed is None:
            return None
        tb_out = None
        if backplate and field and not any(_is_terminal_item(i) for i in items):
            count, what = _field_out_terminals(field)
            tb_dev = (TB_OUT_KEY, "vfd", (count * 5.1 + 19.0) / 25.4, 45.0 / 25.4)
            base = devices + ([(PE_BAR_KEY, "low", *PE_BAR_IN)] if bar else [])
            trial = (place_with_pins(base + [tb_dev], pins, bp_w, bp_h) if pins
                     else arrange(base + [tb_dev], bp_w, bp_h))
            drives = {k for k, z, *_ in devices if z == "vfd"}
            if trial is not None and all(
                    trial.get(k) == placed[k] or (k in drives and trial[k][1:] == placed[k][1:])
                    for k in placed):
                placed, tb_out = trial, (count, what)
        sheet = Sheet(kind="layout", title=ttl, boxes=[_layout_box(project, library, i) for i in items], notes=notes)
        if bar:
            sheet.boxes.append(Box(key=PE_BAR_KEY, tag="PE BAR", role="ground", callout="PE",
                                   lines=["Ground bar (PE)", "Plate, door strap, incoming PE"],
                                   type_id="ground_bar"))
        if tb_out is not None:
            sheet.boxes.append(Box(key=TB_OUT_KEY, tag="TB-OUT", role="terminal", callout="TB-OUT",
                                   lines=["Field terminal strip (TB-OUT)", f"POWER OUT: {tb_out[1]}"],
                                   type_id="terminal_block",
                                   layout_spec={"terminal_count": str(tb_out[0]), "function": tb_out[1]}))
        _place_layout(project, sheet)
        px, py, pw, _ph = sheet.panel
        f = pw / bp_w
        for box in sheet.boxes:
            x, y, w, h = placed[box.key]
            box.x, box.y, box.w, box.h = px + x * f, py + y * f, w * f, h * f
        if backplate:
            _power_entry_marker(project, sheet, bar)
            _power_out_marker(sheet, field)
        return sheet

    if plate:
        order = {z: n for n, z in enumerate(ZONES)}
        plate.sort(key=lambda i: (order[zone_by_id[i.id]], device_tag(i).upper()))
        used = [ZONE_TITLES[z] for z in ZONES if any(zone_by_id[i.id] == z for i in plate)]
        zone_note = ("Power zones top to bottom: " + " · ".join(used)
                     + ". Rows leave room for 40 mm wire duct with 12 mm clearance (UL 508A practice); "
                     "follow each maker's clearance data.")
        sheet = packed_sheet(plate, zone_by_id, title("BACKPLATE"), [base_note, zone_note, *extra], backplate=True)
        if sheet is not None:
            sheets.append(sheet)
        else:
            groups = _split_layout_group(project, library, plate)
            for index, items in enumerate(groups, start=1):
                notes = [base_note, f"These devices do not fit one {bp_w:g}×{bp_h:g} in plate with duct "
                         "spacing - choose a larger enclosure. Hand positions are used.", *extra]
                sheet = Sheet(kind="layout", title=title("BACKPLATE", index, len(groups)),
                              boxes=[_layout_box(project, library, i) for i in items], notes=notes)
                _place_layout(project, sheet, zoom_to_content=len(groups) > 1)
                if index == 1:
                    _power_entry_marker(project, sheet, False)
                    _power_out_marker(sheet, field)
                sheets.append(sheet)
    if show_door:
        ordered = sorted(door, key=lambda item: (item.y, item.x, device_tag(item).upper()))
        door_note = ("DOOR elevation — On-door devices only (pushbuttons / e-stops / HMI). "
                     "In-cabinet and Field devices are on backplate layout sheets. "
                     "Bond the door to the PE ground bar with a ground strap.")
        sheet = packed_sheet(ordered, {i.id: "low" for i in ordered}, title("DOOR"),
                             [base_note, door_note, *([] if plate else extra)])
        groups = [] if sheet is not None else _split_layout_group(project, library, ordered)
        if sheet is not None:
            sheets.append(sheet)
        for index, items in enumerate(groups, start=1):
            sheet = Sheet(kind="layout", title=title("DOOR", index, len(groups)),
                          boxes=[_layout_box(project, library, i) for i in items],
                          notes=[base_note, door_note, *([] if plate else extra)])
            _place_layout(project, sheet, zoom_to_content=len(groups) > 1)
            sheets.append(sheet)
    if len(sheets) > 1:
        for sheet in sheets:
            sheet.notes.append("Devices on other layout sheets continue with off-page arrows.")
    return sheets


PE_BAR_KEY = "virtual-pe-bar"
PE_BAR_IN = (6.0, 0.75)


def _is_ground_item(item: PlacedItem) -> bool:
    tid = (item.type_id or "").lower()
    tag = device_tag(item).upper()
    return tid in {"ground_bar", "ground", "pe_bar"} or tag.startswith(("PE", "GND"))


def _power_entry_marker(project: Project, sheet: Sheet, bar: bool) -> None:
    """Cable entry arrow at the plate top over the disconnect (or the top-left corner)."""
    if sheet.panel is None:
        return
    px, py, _pw, _ph = sheet.panel
    disc = next((b for b in sheet.boxes
                 if b.role == "disconnect" or (b.type_id or "").lower() == "disconnect"), None)
    x = disc.x + disc.w / 2.0 if disc is not None else px + 40.0
    supply = _interview_value(project, "supply_voltage") or "supply"
    _phase, conductors = supply_conductors(project)
    sheet.segments.append(Segment(x, max(20.0, py - 26.0), x, py, "POWER IN"))
    text = f"POWER IN {supply} ({conductors})"
    lx = max(40.0, min(x + 24.0, PAGE_RIGHT - 8.0 - len(text) * FONT_LABEL * 0.6))
    sheet.labels.append((lx, max(30.0, py - 12.0), text))
    sheet.power_io["in"] = f"{supply} ({conductors})"
    sheet.power_io["in_x"] = f"{x:.1f}"
    where = f"over {disc.tag}" if disc is not None else "top left"
    note = (f"POWER IN: cable entry at the top of the enclosure {where}; {conductors} land on the "
            f"disconnect, then the fuses / breakers, then the loads.")
    if bar:
        note += " PE lands on the ground bar (PE BAR), bonded to the plate and the door strap."
    sheet.notes.append(note)


TB_OUT_KEY = "virtual-tb-out"


def _is_terminal_item(item: PlacedItem) -> bool:
    tid = (item.type_id or "").lower()
    return tid in {"terminal_block", "terminal", "tb"} or device_tag(item).upper().startswith("TB")


def _field_out_terminals(field_items: list[PlacedItem]) -> tuple[int, str]:
    """Outgoing field terminals: 3 per motor (T1 T2 T3), 2 per other field device, +2 spare."""
    motors = [i for i in field_items if (i.type_id or "").lower() == "motor"]
    others = [i for i in field_items if i not in motors]
    count = max(6, min(48, 3 * len(motors) + 2 * len(others) + 2))
    what = []
    if motors:
        what.append("motor T1 T2 T3 (" + ", ".join(device_tag(i) for i in motors[:4])
                    + (" ..." if len(motors) > 4 else "") + ")")
    if others:
        what.append("24V field I/O")
    return count, " / ".join(what) or "field wiring"


def _power_out_marker(sheet: Sheet, field_items: list[PlacedItem]) -> None:
    """POWER OUT: field strip (TB-OUT or the lowest terminal strip) and an exit gland at the plate bottom."""
    strips = [b for b in sheet.boxes if b.key == TB_OUT_KEY or _layout_shape_key(b) == "terminal_block"]
    strip = max(strips, key=lambda b: b.y + b.h) if strips else None
    if strip is None and not field_items:
        return
    what = (strip.layout_spec.get("function") if strip is not None and strip.key == TB_OUT_KEY
            else _field_out_terminals(field_items)[1] if field_items else "outgoing field wiring")
    sheet.power_io["out"] = what
    sheet.power_io["out_tag"] = strip.tag if strip is not None else ""
    where = f"field terminal strip {strip.tag}" if strip is not None else "the field terminals"
    sheet.notes.append(f"POWER OUT: {what} land on {where}, then leave through the exit gland at the "
                       "enclosure bottom.")


def _item_is_door_mount(item: PlacedItem) -> bool:
    """True when the placed item belongs on the door elevation (PB / ES / HMI)."""
    mount = (item.fields.get("mounting", "") or "").strip().lower()
    tid = (item.type_id or "").lower().strip()
    if tid in {"wire_duct", "wireway", "duct", "wiring_duct"}:
        return "door" in mount
    if "door" in mount:
        return True
    if "cabinet" in mount or "field" in mount:
        return False
    tag = device_tag(item).upper()
    if tid in {"pushbutton", "estop", "light", "hmi"}:
        return True
    if tag.startswith("ES") or tag.startswith("HS_") or tag.endswith("_PB") or "PILOT" in tag:
        return True
    return False


def _partition_layout_items(project: Project, library: Library) -> list[list]:
    """Partition layout devices: backplate/field first, then door-only sheet(s)."""
    items = list(project.items)
    if not items:
        return []
    plate = [i for i in items if not _item_is_door_mount(i)]
    door = [i for i in items if _item_is_door_mount(i)]
    groups: list[list] = []
    for bucket in (plate, door):
        if not bucket:
            continue
        ordered = sorted(bucket, key=lambda item: (item.y, item.x, device_tag(item).upper()))
        groups.extend(_split_layout_group(project, library, ordered))
    return groups


def _split_layout_group(project: Project, library: Library, items: list) -> list[list]:
    if len(items) <= 1:
        return [items]
    if not _layout_group_crowded(project, library, items):
        return [items]
    mid = max(1, len(items) // 2)
    return _split_layout_group(project, library, items[:mid]) + _split_layout_group(
        project, library, items[mid:]
    )


def _layout_group_crowded(project: Project, library: Library, items: list) -> bool:
    boxes = [_layout_box(project, library, item) for item in items]
    sheet = Sheet(kind="layout", title="trial", boxes=boxes)
    zoom = len(items) < len(project.items)
    _place_layout(project, sheet, zoom_to_content=zoom)
    return _layout_sheet_crowded(sheet)


def _layout_sheet_crowded(sheet: Sheet) -> bool:
    for box in sheet.boxes:
        if min(box.w, box.h) < MIN_LAYOUT_EDGE * 0.55 or box.w < MIN_LAYOUT_EDGE:
            return True
    for index, first in enumerate(sheet.boxes):
        for second in sheet.boxes[index + 1 :]:
            if _boxes_collide(first, second, LAYOUT_LABEL_PAD):
                return True
    return False


def _boxes_collide(first: Box, second: Box, pad: float) -> bool:
    return not (
        first.x + first.w + pad <= second.x
        or second.x + second.w + pad <= first.x
        or first.y + first.h + pad <= second.y
        or second.y + second.h + pad <= first.y
    )


def _link_layout_sheets(sheets: list[Sheet]) -> None:
    """Off-page arrows so the reader can follow devices across layout sheets."""
    if len(sheets) < 2:
        return
    for sheet in sheets:
        for other in sheets:
            if other.number == sheet.number:
                continue
            tags = [box.tag for box in other.boxes]
            if not tags:
                continue
            label_tags = ", ".join(tags[:4]) + ("..." if len(tags) > 4 else "")
            if other.number > sheet.number:
                label = f"TO SH {other.number} {label_tags}"
            else:
                label = f"FROM SH {other.number} {label_tags}"
            connector = Connector(
                box_key=sheet.boxes[0].key if sheet.boxes else f"layout-{sheet.number}",
                kind="off-page",
                wire="",
                label=label,
            )
            # Park at the right gutter above the title block; final x/y set below.
            connector.x = PAGE_W - 210
            connector.y = 48 + 22 * len([c for c in sheet.connectors if c.kind == "off-page"])
            if connector.y < TITLE_TOP - 40:
                connector.arrow_dir = "right"
                sheet.connectors.append(connector)
                # Horizontal stem ending at the arrow base; label is drawn past the tip.
                sheet.segments.append(
                    Segment(connector.x - ARROW_SHAFT, connector.y, connector.x + ARROW_SHAFT, connector.y, "")
                )


def _layout_box(project: Project, library: Library, item: PlacedItem) -> Box:
    tile_w, tile_h = tile_size(library, item.type_id)
    tag = device_tag(item)
    equipment = library.types.get(item.type_id)
    label = equipment.label if equipment is not None else item.type_id
    lines = [label]
    catalog = item.fields.get("catalog", "").strip()
    if catalog:
        lines.append(catalog)
    mounting = item.fields.get("mounting", "").strip()
    if mounting:
        lines.append(mounting)
    # Optional catalog/device outline or footprint hints (first-hit in _layout_shape_key).
    outline_hint = item.fields.get("outline", "")
    footprint_hint = item.fields.get("footprint", "")
    if (not outline_hint or not footprint_hint) and item.library_id:
        cat = library.catalog_by_id.get(item.library_id) if getattr(library, "catalog_by_id", None) else None
        if cat is not None:
            raw_defaults = getattr(cat, "defaults", None)
            if isinstance(raw_defaults, dict):
                defaults = raw_defaults
            elif isinstance(raw_defaults, (list, tuple)):
                defaults = {str(k): v for k, v in raw_defaults}
            else:
                defaults = {}
            outline_hint = outline_hint or defaults.get("outline", "") or ""
            footprint_hint = footprint_hint or defaults.get("footprint", "") or ""
    if isinstance(outline_hint, dict):
        outline_hint = outline_hint.get("id") or outline_hint.get("path") or outline_hint.get("shape") or ""
    if isinstance(footprint_hint, dict):
        shape = footprint_hint.get("shape") or ""
        if shape:
            lines.append(f"footprint:{shape}")
        footprint_hint = ""
    if outline_hint:
        lines.append(f"outline:{outline_hint}")
    if footprint_hint:
        lines.append(f"footprint:{footprint_hint}")
    landing = " ".join(item.fields.get("terminal_landings", "").split())
    maker, catalog_out, plain, source_url = _resolve_outline(item, library)
    cat_item = (getattr(library, "catalog_by_id", None) or {}).get(item.library_id or "")
    spec = dict(cat_item.default_map()) if cat_item is not None else {}
    spec.update({k: str(v) for k, v in item.fields.items() if k in _LAYOUT_SPEC_KEYS and str(v).strip()})
    spec = {k: v for k, v in spec.items() if k in _LAYOUT_SPEC_KEYS}
    spec["name"] = " ".join(x for x in (cat_item.name if cat_item is not None else "", label) if x)
    return Box(
        key=item.id,
        tag=tag,
        role="device",
        callout=_callout(item),
        lines=lines,
        w=tile_w,
        h=tile_h,
        wires=wire_tokens(item.fields.get("wire_numbers", "")),
        landing=landing,
        io_address=item.fields.get("io_address", "").strip(),
        model_x=item.x,
        model_y=item.y,
        type_id=item.type_id,
        outline_maker=maker,
        outline_catalog=catalog_out,
        outline_plain=plain,
        outline_source_url=source_url,
        library_id=item.library_id,
        mounting=mounting,
        layout_spec=spec,
    )


_LAYOUT_SPEC_KEYS = frozenset({
    "poles", "terminal_count", "color", "function", "point_count", "io_kind", "port_count",
    "contact_config", "catalog", "outline_w_mm", "outline_h_mm", "outline_d_mm",
})


def _enclosure_inches(project: Project) -> tuple[float, float]:
    w = float(getattr(project, "enclosure_width_in", 0) or DEFAULT_ENCLOSURE_WIDTH_IN)
    h = float(getattr(project, "enclosure_height_in", 0) or DEFAULT_ENCLOSURE_HEIGHT_IN)
    return max(w, 1.0), max(h, 1.0)


def _backplate_inches(project: Project) -> tuple[float, float]:
    w = float(getattr(project, "backplate_width_in", 0) or DEFAULT_BACKPLATE_WIDTH_IN)
    h = float(getattr(project, "backplate_height_in", 0) or DEFAULT_BACKPLATE_HEIGHT_IN)
    return max(w, 1.0), max(h, 1.0)


def _place_layout(project: Project, sheet: Sheet, zoom_to_content: bool = False) -> None:
    """Scale the physical backing plate onto the 11×17 sheet; map device footprints to it.

    Canvas coordinates (cabinet_width × cabinet_height) span the full backplate.
    When zoom_to_content is set (multi-sheet split), devices still sit on the same
    plate outline so the sheet continues to simulate the UL 508A backplate size.
    """
    bp_w_in, bp_h_in = _backplate_inches(project)
    frame_x, frame_y = 56.0, 44.0
    # Bottom strip under the plate holds the dimension, scale bar, size reference and POWER OUT text.
    frame_w, frame_h = PAGE_W - 112.0, TITLE_TOP - 150.0
    # Fit backplate aspect into the drawing frame (inches → SVG).
    fit = min(frame_w / bp_w_in, frame_h / bp_h_in)
    panel_w = bp_w_in * fit
    panel_h = bp_h_in * fit
    panel_x = frame_x + (frame_w - panel_w) / 2.0
    panel_y = frame_y + (frame_h - panel_h) / 2.0
    sheet.panel = (panel_x, panel_y, panel_w, panel_h)
    sheet.plate = (panel_x + 10.0, panel_y + 20.0)

    if not sheet.boxes:
        return

    # Uniform scale: canvas units → SVG on the plate (preserve footprint aspect).
    cab_w = max(float(project.cabinet_width), 1.0)
    cab_h = max(float(project.cabinet_height), 1.0)
    s = min(panel_w / cab_w, panel_h / cab_h)
    # Letterbox canvas inside plate when aspects differ.
    used_w = cab_w * s
    used_h = cab_h * s
    origin_x = panel_x + (panel_w - used_w) / 2.0
    origin_y = panel_y + (panel_h - used_h) / 2.0

    if zoom_to_content and sheet.boxes:
        # Keep full plate drawn; nudge origin so the dense cluster sits near center.
        min_x = min((box.model_x or 0) for box in sheet.boxes)
        min_y = min((box.model_y or 0) for box in sheet.boxes)
        max_x = max((box.model_x or 0) + box.w for box in sheet.boxes)
        max_y = max((box.model_y or 0) + box.h for box in sheet.boxes)
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        # Mild zoom toward content while never exceeding plate bounds.
        zoom = min(used_w / span_x, used_h / span_y, s * 1.35)
        zoom = max(zoom, s)
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        for box in sheet.boxes:
            box.x = panel_x + panel_w / 2.0 + ((box.model_x or 0) - cx) * zoom
            box.y = panel_y + panel_h / 2.0 + ((box.model_y or 0) - cy) * zoom
            box.w = max(box.w * zoom, 28.0)
            box.h = max(box.h * zoom, 22.0)
            # Clamp into plate with a small pad so outlines stay on the sheet.
            pad = 6.0
            box.x = min(max(box.x, panel_x + pad), panel_x + panel_w - box.w - pad)
            box.y = min(max(box.y, panel_y + pad), panel_y + panel_h - box.h - pad)
        return

    for box in sheet.boxes:
        box.x = origin_x + (box.model_x or 0) * s
        box.y = origin_y + (box.model_y or 0) * s
        box.w = max(box.w * s, 28.0)
        box.h = max(box.h * s, 22.0)


def _panel_markup(project: Project, sheet: Sheet) -> str:
    if sheet.panel is None or sheet.plate is None:
        return ""
    x, y, w, h = sheet.panel
    plate_x, plate_y = sheet.plate
    bp_w, bp_h = _backplate_inches(project)
    enc_w, enc_h = _enclosure_inches(project)
    maker = (getattr(project, "enclosure_maker", "") or "").strip()
    catalog = (getattr(project, "enclosure_catalog", "") or "").strip()
    nema = ""
    interview = getattr(project, "interview", None) or {}
    if isinstance(interview, dict):
        nema = (interview.get("enclosure_type") or "").strip()
    dim = f"BACKING PLATE {bp_w:g} in W × {bp_h:g} in H"
    enc_bits = [f"ENCLOSURE {enc_w:g}×{enc_h:g} in"]
    if maker:
        enc_bits.insert(0, maker)
    if catalog:
        enc_bits.append(catalog)
    if nema:
        enc_bits.append(nema)
    enc_line = " · ".join(enc_bits)
    # Dimension ticks along bottom and right edges (design-aid scale).
    tick = 10.0
    parts = [
        f'<g class="backplate" data-backplate-w-in="{bp_w:g}" data-backplate-h-in="{bp_h:g}" '
        f'data-enclosure-w-in="{enc_w:g}" data-enclosure-h-in="{enc_h:g}">',
        f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
        'fill="#fffdf8" stroke="#000000" stroke-width="2.0"/>',
        # Inner mounting edge hint
        f'<rect x="{_num(x + 8)}" y="{_num(y + 8)}" width="{_num(max(w - 16, 4))}" height="{_num(max(h - 16, 4))}" '
        'fill="none" stroke="#888888" stroke-width="0.8" stroke-dasharray="6 4"/>',
        f'<text x="{_num(plate_x)}" y="{_num(plate_y)}" '
        'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="15" font-weight="700" fill="#000000">'
        f"{escape(project.cabinet_label)}</text>",
        f'<text x="{_num(plate_x)}" y="{_num(plate_y + 18)}" '
        'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="12" font-weight="700" fill="#000000">'
        f"{escape(dim)}</text>",
        f'<text x="{_num(plate_x)}" y="{_num(plate_y + 34)}" '
        'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="11" fill="#333333">'
        f"{escape(enc_line)}</text>",
        # Width dimension under plate
        f'<line x1="{_num(x)}" y1="{_num(y + h + 18)}" x2="{_num(x + w)}" y2="{_num(y + h + 18)}" '
        'stroke="#000000" stroke-width="1.0"/>',
        f'<line x1="{_num(x)}" y1="{_num(y + h + 18 - tick / 2)}" x2="{_num(x)}" y2="{_num(y + h + 18 + tick / 2)}" '
        'stroke="#000000" stroke-width="1.0"/>',
        f'<line x1="{_num(x + w)}" y1="{_num(y + h + 18 - tick / 2)}" x2="{_num(x + w)}" y2="{_num(y + h + 18 + tick / 2)}" '
        'stroke="#000000" stroke-width="1.0"/>',
        f'<text x="{_num(x + w / 2)}" y="{_num(y + h + 34)}" text-anchor="middle" '
        'font-family="Consolas, Liberation Mono, monospace" font-size="11" fill="#000000">'
        f"{bp_w:g} in</text>",
        # Height dimension to the right of plate
        f'<line x1="{_num(x + w + 18)}" y1="{_num(y)}" x2="{_num(x + w + 18)}" y2="{_num(y + h)}" '
        'stroke="#000000" stroke-width="1.0"/>',
        f'<line x1="{_num(x + w + 18 - tick / 2)}" y1="{_num(y)}" x2="{_num(x + w + 18 + tick / 2)}" y2="{_num(y)}" '
        'stroke="#000000" stroke-width="1.0"/>',
        f'<line x1="{_num(x + w + 18 - tick / 2)}" y1="{_num(y + h)}" x2="{_num(x + w + 18 + tick / 2)}" y2="{_num(y + h)}" '
        'stroke="#000000" stroke-width="1.0"/>',
        (f'<text x="{_num(x + w + 30)}" y="{_num(y + h / 2)}" '
         if x + w + 30 + 7 * len(f"{bp_h:g} in") <= PAGE_RIGHT else
         f'<text x="{_num(x + w + 12)}" y="{_num(y + h / 2)}" text-anchor="end" ')
        + 'font-family="Consolas, Liberation Mono, monospace" font-size="11" fill="#000000">'
        f"{bp_h:g} in</text>",
        "</g>",
    ]
    return "".join(parts)


def _layout_device_markup(box: Box) -> str:
    """Catalog-style plan-view footprint on the backing plate — TAG only; details on hover.

    Placement origin is the existing layout convention: box.x/box.y is the
    top-left of the device footprint after canvas→SVG scale in _place_layout
    (JSON item.x/item.y is top-left on the cabinet canvas). Scale is unchanged.
    """
    tip = box_hover_detail(box).replace("\n", " | ")
    kind = (box.type_id or box.role or "device").lower()
    shape = _layout_shape_key(box)
    cx = box.x + box.w / 2.0
    cy = box.y + box.h / 2.0
    tag_size = 13 if box.w >= 70 else 11
    mount = (box.mounting or "").strip()
    mount_attr = f' data-mounting="{escape(mount)}"' if mount else ""
    parts = [
        f'<g class="layout-device" data-tag="{escape(box.tag)}" data-role="{escape(box.role)}" '
        f'data-type="{escape(kind)}" data-footprint="{escape(shape)}"{mount_attr}>',
        f"<title>{escape(tip)}</title>",
        f"<desc>{escape(box.callout)}</desc>",
        f'<rect class="hit-target" x="{_num(box.x - 14)}" y="{_num(box.y - 14)}" '
        f'width="{_num(box.w + 28)}" height="{_num(box.h + 28)}" fill="#ffffff" fill-opacity="0.01" stroke="none"/>',
        _layout_footprint_body(shape, box.x, box.y, box.w, box.h, box.layout_spec),
        _layout_nameplate(box, cx, cy, tag_size),
        f'<text class="device-tag" x="{_num(cx)}" y="{_num(cy - 2)}" text-anchor="middle" '
        f'font-family="Consolas, Liberation Mono, monospace" font-size="{tag_size}" font-weight="700" fill="#000000">'
        f"{escape(box.tag)}</text>",
    ]
    if box.h >= 36:
        parts.append(
            f'<text x="{_num(cx)}" y="{_num(cy + 14)}" text-anchor="middle" '
            f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#555555">'
            f"{escape(kind.replace('_', ' '))}</text>"
        )
    parts.append("</g>")
    return "".join(parts)


def _layout_shape_key(box: Box) -> str:
    """Resolve plan-view shape: outline → footprint → type/role/tag map → DIN brick."""
    for line in box.lines:
        raw = (line or "").strip()
        low = raw.lower()
        if low.startswith("outline:"):
            key = raw.split(":", 1)[1].strip().lower().replace(" ", "_")
            if key:
                return _normalize_shape_key(key)
        if low.startswith("footprint:"):
            key = raw.split(":", 1)[1].strip().lower().replace(" ", "_")
            if key:
                return _normalize_shape_key(key)
        # JSON-ish footprint blob: footprint={shape:din,...} — take shape= if present
        if "shape=" in low and "footprint" in low:
            import re as _re
            m = _re.search(r"shape\s*[:=]\s*([A-Za-z0-9_\-]+)", raw, _re.I)
            if m:
                return _normalize_shape_key(m.group(1).lower())
    tid = (box.type_id or "").lower().strip()
    role = (box.role or "").lower().strip()
    tag = (box.tag or "").upper().strip()
    plain = (box.outline_plain or "").lower()
    spec = box.layout_spec or {}
    if "light curtain" in plain or "light_curtain" in tid or "CURTAIN" in tag:
        return "light_curtain"
    if tid == "light" or "PILOT" in tag:
        if "stack" in (spec.get("function", "") + " " + spec.get("color", "") + " " + spec.get("name", "")).lower():
            return "stack_light"
        return "pilot_light"
    if tid == "pushbutton" or tag.startswith("HS_") or tag.endswith("_PB"):
        hay = (spec.get("function", "") + " " + spec.get("name", "") + " " + " ".join(box.lines)).lower()
        return "selector" if ("selector" in hay or "hoa" in hay or tag.startswith("SS")) else "pushbutton"
    if tag.startswith("ES") or role == "estop" or tid == "estop":
        return "estop"
    if role == "disconnect" or tid == "disconnect" or tag.startswith("DISC"):
        return "disconnect"
    if role == "ground" or tid == "ground" or tag.startswith("GND") or tag in {"PE", "PE_BAR"}:
        return "ground_bar"
    if tid in {"terminal_block", "terminal", "tb"} or tag.startswith("TB"):
        return "terminal_block"
    type_map = {
        "disconnect": "disconnect",
        "power_supply": "power_supply",
        "plc": "plc",
        "io_module": "io_module",
        "di_module": "io_module",
        "do_module": "io_module",
        "safety_relay": "safety_relay",
        "contactor": "contactor",
        "vfd": "vfd",
        "pushbutton": "pushbutton",
        "light": "pushbutton",
        "estop": "estop",
        "sensor": "sensor",
        "transmitter": "sensor",
        "motor": "motor",
        "hmi": "hmi",
        "solenoid": "contactor",
        "valve": "contactor",
        "ethernet_switch": "ethernet_switch",
        "breaker": "breaker",
        "circuit_breaker": "breaker",
        "main_breaker": "breaker",
        "mcb": "breaker",
        "fuse": "fuse_holder",
        "fuse_holder": "fuse_holder",
        "fuse_block": "fuse_holder",
        "motor_protector": "motor_protector",
        "overload": "motor_protector",
        "motor_starter": "contactor",
        "starter": "contactor",
        "relay": "relay",
        "transformer": "transformer",
        "enclosure": "enclosure",
        "backplate": "enclosure",
        "ground": "ground_bar",
        "wire_duct": "wire_duct",
        "wireway": "wire_duct",
        "duct": "wire_duct",
        "wiring_duct": "wire_duct",
    }
    if tid in type_map:
        return type_map[tid]
    if role in type_map:
        return type_map[role]
    return "din_brick"


def _normalize_shape_key(key: str) -> str:
    aliases = {
        "disc": "disconnect",
        "psu": "power_supply",
        "ps": "power_supply",
        "di": "io_module",
        "do": "io_module",
        "di_module": "io_module",
        "do_module": "io_module",
        "io": "io_module",
        "sr": "safety_relay",
        "m1c": "contactor",
        "drive": "vfd",
        "pb": "pushbutton",
        "pilot": "pushbutton",
        "e_stop": "estop",
        "e-stop": "estop",
        "es": "estop",
        "prox": "sensor",
        "proximity": "sensor",
        "tb": "terminal_block",
        "pe": "ground_bar",
        "pe_bar": "ground_bar",
        "gnd": "ground_bar",
        "panel": "enclosure",
        "din": "din_brick",
        "din_brick": "din_brick",
        "wireway": "wire_duct",
        "duct": "wire_duct",
        "wiring_duct": "wire_duct",
        "wd": "wire_duct",
        "cb": "breaker",
        "mcb": "breaker",
        "fuse": "fuse_holder",
        "fb": "fuse_holder",
        "mpcb": "motor_protector",
        "ol": "motor_protector",
        "cr": "relay",
        "xfmr": "transformer",
        "tr": "transformer",
        "switch": "ethernet_switch",
        "selector_switch": "selector",
        "stack": "stack_light",
    }
    return aliases.get(key, key)


def _layout_is_din_shape(shape: str) -> bool:
    return shape in {
        "power_supply",
        "plc",
        "io_module",
        "safety_relay",
        "contactor",
        "vfd",
        "terminal_block",
        "din_brick",
        "breaker",
        "fuse_holder",
        "motor_protector",
        "relay",
        "ethernet_switch",
    }


def _layout_is_door_mount(box: Box) -> bool:
    mount = (box.mounting or "").lower()
    if "door" in mount:
        return True
    shape = _layout_shape_key(box)
    if shape == "wire_duct":
        return False
    if shape in LAYOUT_DOOR_SHAPES and "cabinet" not in mount and "field" not in mount:
        return True
    return False


def _layout_footprint_body(shape: str, x: float, y: float, w: float, h: float,
                           spec: dict[str, str] | None = None) -> str:
    """Plan-view (front, as mounted) SVG outline drawn to scale inside the layout box."""
    ink = "#000000"
    cx = x + w / 2.0
    cy = y + h / 2.0
    parts = [f'<g class="layout-footprint" data-shape="{escape(shape)}">']
    drawer = _LAYOUT_PART_DRAWERS.get(shape)
    if drawer is not None:
        parts.extend(drawer(x, y, w, h, spec or {}))
    elif shape == "vfd":
        # Drive body + vertical heatsink fins + keypad/display pad (plan view).
        pad = min(w, h) * 0.05
        parts.append(
            f'<rect x="{_num(x + pad)}" y="{_num(y + pad)}" width="{_num(w - 2 * pad)}" '
            f'height="{_num(h - 2 * pad)}" fill="#ffffff" stroke="{ink}" stroke-width="1.5"/>'
        )
        fin_w = max(w * 0.20, 12.0)
        fin_x0 = x + w - pad - fin_w
        # Fin block outline
        parts.append(
            f'<rect x="{_num(fin_x0)}" y="{_num(y + pad + 3)}" width="{_num(fin_w - 2)}" '
            f'height="{_num(h - 2 * pad - 6)}" fill="none" stroke="{ink}" stroke-width="1.0"/>'
        )
        n_fins = 7
        for i in range(n_fins):
            fx = fin_x0 + 2 + i * ((fin_w - 6) / max(n_fins - 1, 1))
            parts.append(
                f'<line x1="{_num(fx)}" y1="{_num(y + pad + 5)}" x2="{_num(fx)}" '
                f'y2="{_num(y + h - pad - 5)}" stroke="{ink}" stroke-width="1.0"/>'
            )
        # Keypad / display pad on the operator face (left of fins)
        face_right = fin_x0 - 4
        disp_w = max((face_right - (x + pad) - 8) * 0.85, w * 0.28)
        disp_h = max(h * 0.28, 14.0)
        disp_x = x + pad + 6
        disp_y = y + pad + 6
        parts.append(
            f'<rect x="{_num(disp_x)}" y="{_num(disp_y)}" width="{_num(disp_w)}" '
            f'height="{_num(disp_h)}" fill="#f4f7fb" stroke="{ink}" stroke-width="1.2"/>'
        )
        # Inner display screen
        parts.append(
            f'<rect x="{_num(disp_x + 3)}" y="{_num(disp_y + 3)}" width="{_num(max(disp_w - 6, 4))}" '
            f'height="{_num(max(disp_h * 0.55, 6))}" fill="none" stroke="{ink}" stroke-width="1.0"/>'
        )
        # Keypad button row under the screen
        btn_y = disp_y + disp_h * 0.68
        btn_r = max(min(disp_w, disp_h) * 0.08, 2.2)
        for i in range(3):
            bx = disp_x + disp_w * (0.22 + i * 0.28)
            parts.append(
                f'<circle cx="{_num(bx)}" cy="{_num(btn_y)}" r="{_num(btn_r)}" fill="none" '
                f'stroke="{ink}" stroke-width="1.0"/>'
            )
        # Power terminal ticks along bottom edge of body (behind the terminal cover line)
        cover_y = y + h - pad - max(h * 0.16, 8.0)
        parts.append(_lp_line(x + pad, cover_y, fin_x0 - 2, cover_y, 0.8, dash="3 2"))
        for i in range(5):
            tx = x + pad + 8 + i * ((w - 2 * pad - fin_w - 16) / 4.0)
            parts.append(
                f'<line x1="{_num(tx)}" y1="{_num(y + h - pad)}" x2="{_num(tx)}" '
                f'y2="{_num(y + h - pad - 6)}" stroke="{ink}" stroke-width="1.1"/>'
            )
        fs = _lp_font(w - fin_w, 0.07)
        parts.append(_lp_text(x + pad + 3, cover_y + fs + 1, "L1 L2 L3", fs, anchor="start"))
        parts.append(_lp_text(fin_x0 - 4, cover_y + fs + 1, "T1 T2 T3", fs, anchor="end"))
    elif shape == "wire_duct":
        parts.extend(_wire_duct_parts(x, y, w, h, ink))
    elif shape == "light_curtain":
        pad = min(w, h) * 0.08
        bar_w = max(w * 0.22, 10)
        parts.append(
            f'<rect x="{_num(x + pad)}" y="{_num(y + pad)}" width="{_num(bar_w)}" '
            f'height="{_num(h - 2 * pad)}" fill="#ffffff" stroke="{ink}" stroke-width="1.4"/>'
        )
        for i in range(5):
            yy = y + pad + 6 + i * ((h - 2 * pad - 12) / 4.0)
            parts.append(
                f'<line x1="{_num(x + pad + bar_w)}" y1="{_num(yy)}" '
                f'x2="{_num(x + w - pad)}" y2="{_num(yy)}" stroke="{ink}" stroke-width="1.0" '
                f'stroke-dasharray="3 2"/>'
            )
        parts.append(
            f'<rect x="{_num(x + w - pad - bar_w)}" y="{_num(y + pad)}" width="{_num(bar_w)}" '
            f'height="{_num(h - 2 * pad)}" fill="#ffffff" stroke="{ink}" stroke-width="1.4"/>'
        )
    elif shape == "sensor":
        pad = min(w, h) * 0.12
        bw = w - 2 * pad
        bh = min(h * 0.45, w * 0.35)
        parts.append(
            f'<rect x="{_num(x + pad)}" y="{_num(cy - bh / 2)}" width="{_num(bw * 0.72)}" '
            f'height="{_num(bh)}" rx="{_num(bh * 0.35)}" fill="#ffffff" stroke="{ink}" stroke-width="1.4"/>'
        )
        parts.append(
            f'<rect x="{_num(x + pad + bw * 0.72)}" y="{_num(cy - bh * 0.35)}" width="{_num(bw * 0.22)}" '
            f'height="{_num(bh * 0.7)}" fill="none" stroke="{ink}" stroke-width="1.2"/>'
        )
    elif shape == "motor":
        rx = w * 0.32
        ry = h * 0.32
        parts.append(
            f'<ellipse cx="{_num(cx)}" cy="{_num(cy)}" rx="{_num(rx)}" ry="{_num(ry)}" '
            f'fill="#ffffff" stroke="{ink}" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{_num(cx)}" y="{_num(cy + 4)}" text-anchor="middle" '
            f'font-family="Consolas, Liberation Mono, monospace" font-size="11" font-weight="700" '
            f'fill="{ink}">M</text>'
        )
    elif shape == "enclosure":
        pad = 4
        parts.append(
            f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
            f'fill="#fffdf8" stroke="{ink}" stroke-width="1.6"/>'
        )
        parts.append(
            f'<rect x="{_num(x + pad)}" y="{_num(y + pad)}" width="{_num(max(w - 2 * pad, 4))}" '
            f'height="{_num(max(h - 2 * pad, 4))}" fill="none" stroke="#666666" stroke-width="0.9" '
            f'stroke-dasharray="4 3"/>'
        )
    else:
        parts.extend(_din_brick_parts(x, y, w, h, ink, ticks=None, wide=False, side_ticks=5))
    parts.append("</g>")
    return "".join(parts)


LAYOUT_DOOR_SHAPES = frozenset({"pushbutton", "estop", "hmi", "pilot_light", "selector", "stack_light"})
_LP_TINT = {
    "green": "#a5d6a7", "red": "#ef9a9a", "amber": "#ffe082", "yellow": "#fff59d",
    "blue": "#90caf9", "white": "#ffffff", "black": "#9e9e9e", "clear": "#ffffff",
}
_LP_PANEL = "#f2f2f2"


def _lp_rect(x: float, y: float, w: float, h: float, fill: str = "#ffffff", sw: float = 1.0,
             stroke: str = "#000000", dash: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(max(w, 0.4))}" height="{_num(max(h, 0.4))}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{_num(sw)}"{d}/>')


def _lp_line(x1: float, y1: float, x2: float, y2: float, sw: float = 0.7, stroke: str = "#000000",
             dash: str = "") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{_num(x1)}" y1="{_num(y1)}" x2="{_num(x2)}" y2="{_num(y2)}" '
            f'stroke="{stroke}" stroke-width="{_num(sw)}"{d}/>')


def _lp_circle(cx: float, cy: float, r: float, fill: str = "none", sw: float = 0.7,
               stroke: str = "#000000") -> str:
    return (f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(max(r, 0.3))}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{_num(sw)}"/>')


def _lp_font(span: float, k: float = 0.11) -> float:
    return max(0.0, min(8.0, span * k))


def _lp_text(x: float, y: float, text: str, size: float, anchor: str = "middle", weight: str = "400") -> str:
    """Tiny print label on a part (terminal names); skipped when too small to read."""
    if size < 3.5 or not text:
        return ""
    return (f'<text class="fp-label" x="{_num(x)}" y="{_num(y)}" text-anchor="{anchor}" '
            f'font-family="Consolas, Liberation Mono, monospace" font-size="{_num(size)}" '
            f'font-weight="{weight}" fill="#000000">{escape(text)}</text>')


def _lp_screw(cx: float, cy: float, r: float) -> list[str]:
    return [_lp_circle(cx, cy, r, "#ffffff", 0.6), _lp_line(cx - r * 0.7, cy + r * 0.7, cx + r * 0.7, cy - r * 0.7, 0.5)]


def _lp_terminal_band(x: float, y: float, w: float, band: float, xs: list[float],
                      labels: tuple[str, ...] = (), label_below: bool = True) -> list[str]:
    """Terminal row: shaded band, one screw per x, optional terminal names on the body side."""
    parts = [_lp_rect(x, y, w, band, _LP_PANEL, 0.6)]
    pitch = (xs[1] - xs[0]) if len(xs) > 1 else w
    r = max(min(band * 0.32, pitch * 0.32), 0.5)
    for sx in xs:
        parts.extend(_lp_screw(sx, y + band / 2.0, r))
    fs = min(_lp_font(pitch, 0.42), band * 0.9)
    if labels and fs >= 3.5:
        ty = y + band + fs + 0.5 if label_below else y - 1.0
        for sx, lab in zip(xs, labels):
            parts.append(_lp_text(sx, ty, lab, fs))
    return parts


def _lp_spread(x0: float, x1: float, n: int) -> list[float]:
    if n <= 1:
        return [(x0 + x1) / 2.0]
    step = (x1 - x0) / n
    return [x0 + step * (i + 0.5) for i in range(n)]


def _lp_int(spec: dict[str, str], key: str, default: int) -> int:
    try:
        return max(1, int(float(str(spec.get(key, "")).split()[0])))
    except (TypeError, ValueError, IndexError):
        return default


def _lp_tint(spec: dict[str, str], default: str = "#ffffff") -> str:
    hay = (spec.get("color", "") + " " + spec.get("function", "")).lower()
    for word, tint in _LP_TINT.items():
        if word in hay:
            return tint
    if "start" in hay or "run" in hay:
        return _LP_TINT["green"]
    if "stop" in hay or "fault" in hay:
        return _LP_TINT["red"]
    if "reset" in hay:
        return _LP_TINT["blue"]
    return default


def _lp_plc(x, y, w, h, spec):
    parts = [_lp_rect(x, y, w, h, "#ffffff", 1.4)]
    if w > h * 1.15:  # brick controller: terminal rows top and bottom, LEDs, port
        band = h * 0.16
        n = max(4, min(24, int(w / max(h * 0.075, 3.0))))
        xs = _lp_spread(x + 2, x + w - 2, n)
        parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, xs)
        parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, xs)
        for i in range(4):
            parts.append(_lp_circle(x + w * 0.06, y + band + h * 0.1 + i * h * 0.1, min(h * 0.025, 2.0), "#ffffff", 0.5))
        parts.append(_lp_rect(x + w * 0.22, y + band + h * 0.08, w * 0.42, h * 0.24, "none", 0.6))
        parts.append(_lp_rect(x + w * 0.76, y + h * 0.42, w * 0.08, h * 0.16, "#ffffff", 0.7))
        return parts
    slices = max(1, round(w / max(h * 0.3, 1.0)))
    sw_ = w / slices
    band = h * 0.1
    for i in range(1, slices):
        parts.append(_lp_line(x + i * sw_, y, x + i * sw_, y + h, 0.9))
    xs = [x + i * sw_ + sw_ * f for i in range(slices) for f in (0.3, 0.7)]
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, xs)
    parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, xs)
    parts.append(_lp_rect(x + sw_ * 0.15, y + h * 0.15, sw_ * 0.7, h * 0.1, "#f4f7fb", 0.6))
    for i in range(3):
        parts.append(_lp_circle(x + sw_ * (0.25 + i * 0.25), y + h * 0.3, min(sw_ * 0.06, 1.8), "#ffffff", 0.5))
    for i in range(2):
        parts.append(_lp_rect(x + sw_ * 0.2 + i * sw_ * 0.34, y + h * 0.7, sw_ * 0.26, h * 0.07, "#ffffff", 0.6))
    parts.append(_lp_circle(x + sw_ * 0.5, y + h * 0.5, min(sw_ * 0.12, h * 0.04), "#ffffff", 0.6))
    return parts


def _lp_io_module(x, y, w, h, spec):
    parts = [_lp_rect(x, y, w, h, "#ffffff", 1.2)]
    points = _lp_int(spec, "point_count", 16)
    kind = (spec.get("io_kind") or "").upper()[:3]
    if w > h * 0.6:  # expansion brick (S7-1200 SM): terminal rows top / bottom + LED row
        band = h * 0.15
        n = max(4, min(18, points // 2 + 1))
        xs = _lp_spread(x + 2, x + w - 2, n)
        parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, xs)
        parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, xs)
        for i, lx in enumerate(_lp_spread(x + w * 0.1, x + w * 0.9, min(points, 16))):
            parts.append(_lp_circle(lx, y + band + h * 0.1, min(h * 0.018, 1.4), "#ffffff", 0.4))
        parts.append(_lp_text(x + w / 2.0, y + h * 0.72, kind, _lp_font(w, 0.08)))
        return parts
    parts.append(_lp_rect(x + 0.5, y + 0.5, w - 1, h * 0.1, _LP_PANEL, 0.5))
    parts.append(_lp_text(x + w / 2.0, y + h * 0.08, kind, _lp_font(w, 0.3)))
    for i in range(min(8, max(points // 2, 4))):
        parts.append(_lp_circle(x + w * 0.5, y + h * 0.14 + i * h * 0.022, min(w * 0.08, 1.2), "#ffffff", 0.4))
    rows = min(10, max(4, points // 2))
    r = max(min(w * 0.13, h * 0.5 / rows * 0.3), 0.5)
    for i in range(rows):
        yy = y + h * 0.36 + (i + 0.5) * (h * 0.6 / rows)
        for fx in (0.3, 0.7):
            parts.extend(_lp_screw(x + w * fx, yy, r))
    return parts


def _lp_power_supply(x, y, w, h, spec):
    band = h * 0.13
    parts = [_lp_rect(x, y, w, h, "#ffffff", 1.3)]
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, _lp_spread(x + 2, x + w - 2, 3), ("L", "N", "PE"))
    parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, _lp_spread(x + 2, x + w - 2, 4),
                               ("+", "+", "-", "-"), label_below=False)
    for i in range(7):
        yy = y + h * 0.3 + i * h * 0.045
        parts.append(_lp_line(x + w * 0.15, yy, x + w * 0.85, yy, 0.9, "#555555"))
    parts.append(_lp_circle(x + w * 0.22, y + h * 0.7, min(w, h) * 0.035, "#ffffff", 0.6))
    parts.extend(_lp_screw(x + w * 0.78, y + h * 0.7, min(w, h) * 0.05))
    parts.append(_lp_text(x + w * 0.22, y + h * 0.7 - min(w, h) * 0.06, "DC OK", _lp_font(w, 0.07)))
    return parts


def _lp_contactor(x, y, w, h, spec):
    band = h * 0.15
    parts = [_lp_rect(x, y, w, h, "#ffffff", 1.4)]
    poles = [x + w * f for f in (0.36, 0.58, 0.8)]
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, [x + w * 0.13] + poles, ("A1", "L1", "L2", "L3"))
    parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, [x + w * 0.13] + poles,
                               ("A2", "T1", "T2", "T3"), label_below=False)
    parts.append(_lp_rect(x + w * 0.3, y + h * 0.4, w * 0.4, h * 0.18, _LP_PANEL, 0.7))
    parts.append(_lp_line(x + w * 0.04, y + h * 0.3, x + w * 0.96, y + h * 0.3, 0.5, dash="2 2"))
    return parts


def _lp_motor_protector(x, y, w, h, spec):
    band = h * 0.14
    parts = [_lp_rect(x, y, w, h, "#ffffff", 1.4)]
    poles = _lp_spread(x + 2, x + w - 2, 3)
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, poles, ("L1", "L2", "L3"))
    parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, poles, ("T1", "T2", "T3"), label_below=False)
    r = min(w, h) * 0.22
    dx, dy = x + w / 2.0, y + h * 0.42
    parts.append(_lp_circle(dx, dy, r, "#ffffff", 1.1))
    parts.append(_lp_line(dx, dy, dx + r * 0.6, dy - r * 0.6, 1.4))
    for f in (-0.8, 0.0, 0.8):
        parts.append(_lp_line(dx + r * 1.1 * f, dy - r * 1.05, dx + r * 1.25 * f, dy - r * 1.25, 0.6))
    parts.append(_lp_rect(dx - w * 0.12, y + h * 0.66, w * 0.24, h * 0.08, _LP_PANEL, 0.7))
    return parts


def _lp_breaker(x, y, w, h, spec):
    p = _lp_int(spec, "poles", max(1, min(4, round(w / max(h * 0.15, 1.0)))))
    pw_ = w / p
    parts: list[str] = []
    r = max(min(pw_ * 0.28, h * 0.045), 0.5)
    for i in range(p):
        x0 = x + i * pw_
        pcx = x0 + pw_ / 2.0
        parts.append(_lp_rect(x0, y, pw_, h, "#ffffff", 1.1))
        parts.extend(_lp_screw(pcx, y + h * 0.08, r))
        parts.extend(_lp_screw(pcx, y + h * 0.92, r))
        parts.append(_lp_rect(x0 + pw_ * 0.2, y + h * 0.18, pw_ * 0.6, h * 0.12, "none", 0.5))
        parts.append(_lp_rect(x0 + pw_ * 0.28, y + h * 0.42, pw_ * 0.44, h * 0.16, "#d9d9d9", 0.8))
    if p > 1:
        parts.append(_lp_line(x + pw_ * 0.28, y + h * 0.5, x + w - pw_ * 0.28, y + h * 0.5, 1.4))
    return parts


def _lp_fuse_holder(x, y, w, h, spec):
    p = _lp_int(spec, "poles", max(1, min(4, round(w / max(h * 0.22, 1.0)))))
    pw_ = w / p
    parts: list[str] = []
    r = max(min(pw_ * 0.22, h * 0.045), 0.5)
    for i in range(p):
        x0 = x + i * pw_
        pcx = x0 + pw_ / 2.0
        parts.append(_lp_rect(x0, y, pw_, h, "#ffffff", 1.1))
        parts.extend(_lp_screw(pcx, y + h * 0.08, r))
        parts.extend(_lp_screw(pcx, y + h * 0.92, r))
        parts.append(_lp_line(x0 + pw_ * 0.1, y + h * 0.18, x0 + pw_ * 0.9, y + h * 0.18, 0.6))
        parts.append(_lp_rect(x0 + pw_ * 0.27, y + h * 0.25, pw_ * 0.46, h * 0.52, _LP_PANEL, 0.8))
        for fy in (0.3, 0.72):
            parts.append(_lp_line(x0 + pw_ * 0.27, y + h * fy, x0 + pw_ * 0.73, y + h * fy, 0.5))
    return parts


def _lp_disconnect(x, y, w, h, spec):
    band = h * 0.12
    parts = [_lp_rect(x, y, w, h, "#fff8f0", 1.5)]
    poles = _lp_spread(x + 2, x + w - 2, _lp_int(spec, "poles", 3))
    names = ("L1", "L2", "L3", "N")
    loads = ("T1", "T2", "T3", "N")
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, poles, names[:len(poles)])
    parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, poles, loads[:len(poles)], label_below=False)
    r = min(w, h * 0.7) * 0.32
    hx, hy = x + w / 2.0, y + h * 0.5
    parts.append(_lp_circle(hx, hy, r, "#ffffff", 1.3))
    parts.append(_lp_line(hx - r * 0.9, hy + r * 0.35, hx + r * 0.9, hy - r * 0.35, max(r * 0.32, 1.5)))
    fs = _lp_font(r, 0.4)
    parts.append(_lp_text(hx - r * 0.75, hy - r * 0.55, "O", fs))
    parts.append(_lp_text(hx + r * 0.75, hy + r * 0.85, "I", fs))
    return parts


def _lp_terminal_block(x, y, w, h, spec):
    n = _lp_int(spec, "terminal_count", max(4, int(w / max(h * 0.113, 3.0))))
    end = min(w * 0.08, h * 0.2)
    x0, x1 = x + end, x + w - end
    pitch = (x1 - x0) / n
    parts = [_lp_rect(x, y + h * 0.08, end * 0.9, h * 0.84, "#d9d9d9", 0.8),
             _lp_rect(x + w - end * 0.9, y + h * 0.08, end * 0.9, h * 0.84, "#d9d9d9", 0.8)]
    if pitch < 1.6:
        parts.append(_lp_rect(x0, y, x1 - x0, h, "#ffffff", 0.9))
        xx = x0
        while xx < x1:
            parts.append(_lp_line(xx, y, xx, y + h, 0.3))
            xx += max(pitch * 2, 1.6)
        return parts
    r = max(min(pitch * 0.32, h * 0.06), 0.4)
    fs = min(_lp_font(pitch, 0.8), 6.0)
    for i in range(n):
        sx = x0 + i * pitch
        parts.append(_lp_rect(sx, y, pitch, h, "#ffffff", 0.5))
        parts.extend(_lp_screw(sx + pitch / 2.0, y + h * 0.12, r))
        parts.extend(_lp_screw(sx + pitch / 2.0, y + h * 0.88, r))
        parts.append(_lp_text(sx + pitch / 2.0, y + h * 0.3, str(i + 1), fs))
    parts.append(_lp_line(x1, y, x1, y + h, 1.4))
    return parts


def _lp_relay(x, y, w, h, spec):
    if w < h * 0.15:  # slim interface relay
        r = max(w * 0.3, 0.5)
        parts = [_lp_rect(x, y, w, h, "#ffffff", 1.1)]
        for fy in (0.05, 0.12, 0.88, 0.95):
            parts.extend(_lp_screw(x + w / 2.0, y + h * fy, r))
        parts.append(_lp_rect(x + w * 0.12, y + h * 0.3, w * 0.76, h * 0.34, _LP_PANEL, 0.6))
        parts.append(_lp_circle(x + w / 2.0, y + h * 0.72, r * 0.8, "#ffffff", 0.5))
        return parts
    band = h * 0.12
    parts = [_lp_rect(x, y, w, h, _LP_PANEL, 1.2)]
    xs = _lp_spread(x + 1, x + w - 1, 3)
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, xs, ("A1", "11", "21"))
    parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, xs, ("A2", "14", "24"), label_below=False)
    parts.append(_lp_rect(x + w * 0.12, y + h * 0.22, w * 0.76, h * 0.56, "#ffffff", 1.2))
    parts.append(_lp_line(x + w * 0.2, y + h * 0.2, x + w * 0.8, y + h * 0.2, 1.0))
    parts.append(_lp_line(x + w * 0.2, y + h * 0.8, x + w * 0.8, y + h * 0.8, 1.0))
    parts.append(_lp_circle(x + w * 0.3, y + h * 0.3, min(w, h) * 0.04, "#ffffff", 0.5))
    parts.append(_lp_rect(x + w * 0.6, y + h * 0.66, w * 0.16, h * 0.06, "#d9d9d9", 0.5))
    return parts


def _lp_safety_relay(x, y, w, h, spec):
    band = h * 0.12
    parts = [_lp_rect(x, y, w, h, "#fffbe6", 1.4)]
    n = max(2, min(6, int(w / 6.0)))
    xs = _lp_spread(x + 1, x + w - 1, n)
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, xs, ("A1", "S11", "S12", "S21", "S22", "S34")[:n])
    parts += _lp_terminal_band(x + 1, y + h - band - 1, w - 2, band, xs,
                               ("A2", "13", "14", "23", "24", "Y32")[:n], label_below=False)
    for i in range(4):
        parts.append(_lp_circle(x + w * 0.22, y + h * (0.24 + i * 0.07), min(w * 0.06, 1.8), "#ffffff", 0.5))
    parts.append(_lp_circle(x + w * 0.66, y + h * 0.62, min(w * 0.16, h * 0.06), "#ffffff", 0.8))
    parts.append(_lp_line(x + w * 0.66, y + h * 0.62, x + w * 0.66, y + h * 0.62 - min(w * 0.16, h * 0.06), 0.8))
    return parts


def _lp_transformer(x, y, w, h, spec):
    parts = [_lp_rect(x, y + h * 0.86, w, h * 0.14, "#d9d9d9", 1.0)]
    for fx in (0.08, 0.86):
        parts.append(_lp_rect(x + w * fx, y + h * 0.9, w * 0.06, h * 0.05, "#ffffff", 0.5))
    parts.append(_lp_rect(x + w * 0.06, y + h * 0.14, w * 0.88, h * 0.72, "#ffffff", 1.3))
    for i in range(4):
        yy = y + h * (0.17 + i * 0.022)
        parts.append(_lp_line(x + w * 0.06, yy, x + w * 0.94, yy, 0.4))
        yy = y + h * (0.83 - i * 0.022)
        parts.append(_lp_line(x + w * 0.06, yy, x + w * 0.94, yy, 0.4))
    parts.append(_lp_rect(x + w * 0.2, y + h * 0.26, w * 0.6, h * 0.48, _LP_PANEL, 1.1))
    for i in range(6):
        yy = y + h * (0.3 + i * 0.075)
        parts.append(_lp_line(x + w * 0.2, yy, x + w * 0.8, yy, 0.4))
    xs = _lp_spread(x + w * 0.06, x + w * 0.94, 6)
    parts += _lp_terminal_band(x + w * 0.06, y, w * 0.88, h * 0.12, xs,
                               ("H1", "H2", "H3", "H4", "X1", "X2"), label_below=True)
    return parts


def _lp_ground_bar(x, y, w, h, spec):
    parts = [_lp_rect(x + w * 0.05, y + h * 0.2, w * 0.9, h * 0.6, "#f2f7f3", 1.3)]
    for fx in (0.0, 0.95):
        parts.append(_lp_rect(x + w * fx, y, w * 0.05, h, "#d9d9d9", 0.8))
    n = max(3, min(24, int(w * 0.8 / max(h * 0.9, 4.0))))
    r = max(min(h * 0.2, w * 0.8 / n * 0.3), 0.6)
    for sx in _lp_spread(x + w * 0.12, x + w * 0.88, n):
        parts.append(_lp_circle(sx, y + h / 2.0, r, "#ffffff", 0.7))
        parts.append(_lp_line(sx - r * 0.7, y + h / 2.0, sx + r * 0.7, y + h / 2.0, 0.5))
        parts.append(_lp_line(sx, y + h / 2.0 - r * 0.7, sx, y + h / 2.0 + r * 0.7, 0.5))
    parts.append(_lp_text(x + w * 0.08, y + h * 0.65, "PE", min(h * 0.4, 9.0), anchor="start", weight="700"))
    return parts


def _lp_ethernet_switch(x, y, w, h, spec):
    band = h * 0.1
    parts = [_lp_rect(x, y, w, h, "#ffffff", 1.3)]
    parts += _lp_terminal_band(x + 1, y + 1, w - 2, band, _lp_spread(x + 2, x + w - 2, 3), ("+", "-", "PE"))
    n = _lp_int(spec, "port_count", 5)
    cols = 1 if n <= 5 else 2
    rows = -(-n // cols)
    cell_h = h * 0.62 / rows
    pw_ = min(w * (0.5 if cols == 1 else 0.36), cell_h * 1.1)
    ph_ = cell_h * 0.7
    for i in range(n):
        c, rr = divmod(i, rows)
        px_ = x + w * (0.5 if cols == 1 else (0.3 if c == 0 else 0.7)) - pw_ / 2.0
        py_ = y + h * 0.32 + rr * cell_h
        parts.append(_lp_rect(px_, py_, pw_, ph_, "#ffffff", 0.7))
        parts.append(_lp_rect(px_ + pw_ * 0.35, py_ + ph_, pw_ * 0.3, cell_h * 0.12, "#ffffff", 0.5))
    for i in range(3):
        parts.append(_lp_circle(x + w * (0.3 + i * 0.2), y + h * 0.2, min(w * 0.04, 1.5), "#ffffff", 0.5))
    return parts


def _lp_door_head(x, y, w, h):
    """22 mm operator: head centre and bezel radius; a legend plate fills the rest below."""
    r = min(w, h) / 2.0 * 0.96
    return x + w / 2.0, y + min(w, h) / 2.0, r


def _lp_legend(x, y, w, h, text):
    top = y + min(w, h) * 1.0
    if h - (top - y) < 4:
        return []
    lh = y + h - top - 1
    parts = [_lp_rect(x + w * 0.08, top, w * 0.84, lh, "#ffffff", 0.7)]
    parts.append(_lp_text(x + w / 2.0, top + lh * 0.72, text.upper()[:10], min(lh * 0.6, _lp_font(w, 0.16))))
    return parts


def _lp_pushbutton(x, y, w, h, spec):
    cx, cy, r = _lp_door_head(x, y, w, h)
    parts = [_lp_circle(cx, cy, r, "#ffffff", 1.4), _lp_circle(cx, cy, r * 0.8, "none", 0.8),
             _lp_circle(cx, cy, r * 0.62, _lp_tint(spec), 1.1)]
    return parts + _lp_legend(x, y, w, h, spec.get("function", ""))


def _lp_pilot_light(x, y, w, h, spec):
    cx, cy, r = _lp_door_head(x, y, w, h)
    parts = [_lp_circle(cx, cy, r, "#ffffff", 1.4), _lp_circle(cx, cy, r * 0.8, "none", 0.8),
             _lp_circle(cx, cy, r * 0.6, _lp_tint(spec), 1.0)]
    k = r * 0.3
    parts += [_lp_line(cx - k, cy - k, cx + k, cy + k, 0.7), _lp_line(cx - k, cy + k, cx + k, cy - k, 0.7)]
    return parts + _lp_legend(x, y, w, h, spec.get("function", "") or spec.get("color", ""))


def _lp_selector(x, y, w, h, spec):
    cx, cy, r = _lp_door_head(x, y, w, h)
    parts = [_lp_circle(cx, cy, r, "#ffffff", 1.4), _lp_circle(cx, cy, r * 0.72, "#f2f2f2", 0.9),
             _lp_line(cx, cy - r * 0.62, cx, cy + r * 0.62, max(r * 0.28, 1.2), "#444444")]
    for ang in (-0.7, 0.0, 0.7):
        dx, dy = r * 0.9 * math.sin(ang), -r * 0.9 * math.cos(ang)
        parts.append(_lp_line(cx + dx, cy + dy, cx + dx * 1.08, cy + dy * 1.08, 0.8))
    return parts + _lp_legend(x, y, w, h, "H  O  A" if "hoa" in spec.get("name", "").lower() else "SEL")


def _lp_estop(x, y, w, h, spec):
    cx, cy = x + w / 2.0, y + h / 2.0
    ring = min(w, h) * 0.49
    head = ring * 0.667
    parts = [_lp_circle(cx, cy, ring, "#ffd54f", 1.2), _lp_circle(cx, cy, head, "#e53935", 1.5),
             _lp_circle(cx, cy, head * 0.7, "none", 0.6)]
    parts.append(_lp_text(cx, cy + (ring + head) / 2.0 + 1.5, "E-STOP", _lp_font(ring - head, 0.55), weight="700"))
    return parts


def _lp_hmi(x, y, w, h, spec):
    parts = [_lp_rect(x, y, w, h, "#e8e8e8", 1.5)]
    sx, sy, sw_, sh = x + w * 0.08, y + h * 0.08, w * 0.84, h * 0.76
    parts.append(_lp_rect(sx, sy, sw_, sh, "#eef3f8", 1.0))
    parts.append(_lp_line(sx, sy + sh * 0.12, sx + sw_, sy + sh * 0.12, 0.5))
    for i in range(3):
        parts.append(_lp_rect(sx + sw_ * (0.08 + i * 0.31), sy + sh * 0.74, sw_ * 0.24, sh * 0.16, "#ffffff", 0.5))
    parts.append(_lp_circle(x + w * 0.9, y + h * 0.92, min(w, h) * 0.02, "#ffffff", 0.5))
    return parts


def _lp_stack_light(x, y, w, h, spec):
    if h < w * 1.5:  # single stack module
        parts = [_lp_rect(x + w * 0.1, y, w * 0.8, h, _lp_tint(spec, _LP_TINT["amber"]), 1.2)]
        for i in range(1, 4):
            parts.append(_lp_line(x + w * 0.1, y + h * i / 4.0, x + w * 0.9, y + h * i / 4.0, 0.5))
        return parts
    base_h, cap_h = h * 0.16, h * 0.06
    parts = [_lp_rect(x + w * 0.15, y + h - base_h, w * 0.7, base_h, "#d9d9d9", 1.0),
             _lp_rect(x + w * 0.12, y, w * 0.76, cap_h, "#ffffff", 1.0)]
    tints = (_LP_TINT["red"], _LP_TINT["amber"], _LP_TINT["green"])
    seg = (h - base_h - cap_h) / len(tints)
    for i, tint in enumerate(tints):
        parts.append(_lp_rect(x + w * 0.1, y + cap_h + i * seg, w * 0.8, seg, tint, 1.1))
    return parts


_LAYOUT_PART_DRAWERS = {
    "plc": _lp_plc,
    "io_module": _lp_io_module,
    "power_supply": _lp_power_supply,
    "contactor": _lp_contactor,
    "motor_protector": _lp_motor_protector,
    "breaker": _lp_breaker,
    "fuse_holder": _lp_fuse_holder,
    "disconnect": _lp_disconnect,
    "terminal_block": _lp_terminal_block,
    "relay": _lp_relay,
    "safety_relay": _lp_safety_relay,
    "transformer": _lp_transformer,
    "ground_bar": _lp_ground_bar,
    "ethernet_switch": _lp_ethernet_switch,
    "pushbutton": _lp_pushbutton,
    "pilot_light": _lp_pilot_light,
    "selector": _lp_selector,
    "estop": _lp_estop,
    "hmi": _lp_hmi,
    "stack_light": _lp_stack_light,
}


def _layout_nameplate(box: Box, cx: float, cy: float, size: float) -> str:
    """White tag plate behind the device tag (and type line) so it reads over the part detail."""
    tw = len(box.tag) * size * 0.62 + 6.0
    top = cy - 2.0 - size * 0.85 - 2.0
    th = size + 4.0
    if box.h >= 36:
        kind_w = len((box.type_id or box.role or "device").replace("_", " ")) * 9 * 0.55 + 6.0
        if max(tw, kind_w) <= box.w - 2 and th + 14 <= box.h - 2:
            tw, th = max(tw, kind_w), th + 14.0
    if tw > box.w - 2 or th > box.h - 2:
        return ""
    return (f'<rect class="nameplate" x="{_num(cx - tw / 2.0)}" y="{_num(top)}" width="{_num(tw)}" '
            f'height="{_num(th)}" fill="#ffffff" stroke="#000000" stroke-width="0.4"/>')


def _din_brick_parts(
    x: float,
    y: float,
    w: float,
    h: float,
    ink: str,
    ticks: tuple[str, ...] | None = None,
    wide: bool = False,
    slim: bool = False,
    leds: bool = False,
    side_ticks: int = 0,
) -> list[str]:
    """DIN-rail brick: body, rail notch, optional terminal ticks / LED dots."""
    parts: list[str] = []
    inset = 0.04 if wide else (0.12 if slim else 0.07)
    pad_x = w * inset
    pad_y = h * 0.08
    bx, by = x + pad_x, y + pad_y
    bw, bh = w - 2 * pad_x, h - 2 * pad_y
    parts.append(
        f'<rect x="{_num(bx)}" y="{_num(by)}" width="{_num(bw)}" height="{_num(bh)}" '
        f'fill="#ffffff" stroke="{ink}" stroke-width="1.4"/>'
    )
    ny = by + bh * 0.55
    notch = min(7.0, bw * 0.08)
    parts.append(
        f'<path d="M {_num(bx)} {_num(ny - 5)} L {_num(bx + notch)} {_num(ny - 5)} '
        f'L {_num(bx + notch)} {_num(ny + 5)} L {_num(bx)} {_num(ny + 5)}" '
        f'fill="#fffdf8" stroke="{ink}" stroke-width="1.2"/>'
    )
    parts.append(
        f'<path d="M {_num(bx + bw)} {_num(ny - 5)} L {_num(bx + bw - notch)} {_num(ny - 5)} '
        f'L {_num(bx + bw - notch)} {_num(ny + 5)} L {_num(bx + bw)} {_num(ny + 5)}" '
        f'fill="#fffdf8" stroke="{ink}" stroke-width="1.2"/>'
    )
    parts.append(
        f'<line x1="{_num(bx + notch + 2)}" y1="{_num(ny)}" x2="{_num(bx + bw - notch - 2)}" '
        f'y2="{_num(ny)}" stroke="{ink}" stroke-width="1.0" stroke-dasharray="4 3"/>'
    )
    if ticks:
        n = len(ticks)
        for i, lab in enumerate(ticks):
            tx = bx + 8 + i * ((bw - 16) / max(n - 1, 1))
            parts.append(
                f'<line x1="{_num(tx)}" y1="{_num(by + bh)}" x2="{_num(tx)}" '
                f'y2="{_num(by + bh - 6)}" stroke="{ink}" stroke-width="1.1"/>'
            )
            parts.append(
                f'<text x="{_num(tx)}" y="{_num(by + bh - 8)}" text-anchor="middle" '
                f'font-family="Consolas, Liberation Mono, monospace" font-size="7" fill="{ink}">{lab}</text>'
            )
    if leds:
        for i in range(4):
            parts.append(
                f'<circle cx="{_num(bx + 12 + i * 12)}" cy="{_num(by + 10)}" r="2.4" '
                f'fill="none" stroke="{ink}" stroke-width="1.0"/>'
            )
    if side_ticks > 0:
        for i in range(side_ticks):
            yy = by + 8 + i * ((bh - 16) / max(side_ticks - 1, 1))
            parts.append(
                f'<line x1="{_num(bx)}" y1="{_num(yy)}" x2="{_num(bx - 5)}" y2="{_num(yy)}" '
                f'stroke="{ink}" stroke-width="1.0"/>'
            )
            parts.append(
                f'<line x1="{_num(bx + bw)}" y1="{_num(yy)}" x2="{_num(bx + bw + 5)}" y2="{_num(yy)}" '
                f'stroke="{ink}" stroke-width="1.0"/>'
            )
    return parts


def _layout_din_rails_markup(sheet: Sheet, project: Project | None = None) -> str:
    """35 mm top-hat DIN rail strips (slotted, to scale) behind each row of DIN-mounted parts."""
    din_boxes = [b for b in sheet.boxes
                 if _layout_is_din_shape(_layout_shape_key(b)) and not _layout_is_door_mount(b)]
    if not din_boxes:
        return ""
    clusters: list[list[Box]] = []
    for box in sorted(din_boxes, key=lambda b: b.y):
        for cluster in clusters:
            top = min(b.y for b in cluster)
            bot = max(b.y + b.h for b in cluster)
            overlap = min(bot, box.y + box.h) - max(top, box.y)
            if overlap >= 0.5 * min(box.h, bot - top):
                cluster.append(box)
                break
        else:
            clusters.append([box])
    mm = _layout_mm_to_svg(project, sheet, 1.0) if project is not None and sheet.panel else 0.3
    rail_h = max(35.0 * mm, 6.0)
    parts = ['<g class="din-rails">']
    for cluster in clusters:
        centres = sorted(b.y + b.h / 2.0 for b in cluster)
        rail_y = centres[len(centres) // 2]
        x1 = min(b.x for b in cluster) - max(10.0 * mm, 4.0)
        x2 = max(b.x + b.w for b in cluster) + max(10.0 * mm, 4.0)
        top = rail_y - rail_h / 2.0
        parts.append(
            f'<rect class="din-rail" x="{_num(x1)}" y="{_num(top)}" width="{_num(x2 - x1)}" '
            f'height="{_num(rail_h)}" fill="#e3e3e3" stroke="#666666" stroke-width="0.8"/>'
        )
        for k in (0.2, 0.8):
            parts.append(_lp_line(x1, top + rail_h * k, x2, top + rail_h * k, 0.5, "#888888"))
        pitch = max(25.0 * mm, 6.0)
        slot_w, slot_h = max(15.0 * mm, 3.0), max(5.2 * mm, 1.5)
        sx = x1 + pitch / 2.0
        while sx + slot_w <= x2 - 2:
            parts.append(_lp_rect(sx, rail_y - slot_h / 2.0, slot_w, slot_h, "#ffffff", 0.4, "#888888"))
            sx += pitch
    parts.append("</g>")
    return "".join(parts)



def _layout_is_wire_duct(box: Box) -> bool:
    return _layout_shape_key(box) == "wire_duct"


def _wire_duct_parts(x: float, y: float, w: float, h: float, ink: str) -> list[str]:
    """Snap-on cover style duct: outer body, inner cavity, cover lip on long walls."""
    parts: list[str] = []
    pad = min(w, h) * 0.06
    parts.append(
        f'<rect x="{_num(x + pad)}" y="{_num(y + pad)}" width="{_num(max(w - 2 * pad, 2))}" '
        f'height="{_num(max(h - 2 * pad, 2))}" fill="#e2e2e2" stroke="{ink}" stroke-width="1.3"/>'
    )
    inset = max(min(w, h) * 0.22, 3.0)
    parts.append(
        f'<rect x="{_num(x + inset)}" y="{_num(y + inset)}" width="{_num(max(w - 2 * inset, 1))}" '
        f'height="{_num(max(h - 2 * inset, 1))}" fill="#f4f4f4" stroke="{ink}" stroke-width="1.0"/>'
    )
    horizontal = w >= h
    # Finger slots (hatch) along both side walls, ~12 mm pitch at the 40 mm duct scale.
    pitch = max(min(w, h) * 0.3, 4.0)
    start, stop = (x + inset, x + w - inset) if horizontal else (y + inset, y + h - inset)
    pos = start + pitch / 2.0
    while pos < stop:
        if horizontal:
            parts.append(_lp_line(pos, y + pad, pos, y + inset, 0.5, "#777777"))
            parts.append(_lp_line(pos, y + h - inset, pos, y + h - pad, 0.5, "#777777"))
        else:
            parts.append(_lp_line(x + pad, pos, x + inset, pos, 0.5, "#777777"))
            parts.append(_lp_line(x + w - inset, pos, x + w - pad, pos, 0.5, "#777777"))
        pos += pitch
    if horizontal:
        lip = max(h * 0.12, 2.0)
        for yy in (y + pad + lip, y + h - pad - lip):
            parts.append(
                f'<line x1="{_num(x + inset)}" y1="{_num(yy)}" x2="{_num(x + w - inset)}" '
                f'y2="{_num(yy)}" stroke="{ink}" stroke-width="1.0"/>'
            )
        for xx in (x + pad + 2, x + w - pad - 2):
            parts.append(
                f'<line x1="{_num(xx)}" y1="{_num(y + pad)}" x2="{_num(xx)}" '
                f'y2="{_num(y + h - pad)}" stroke="{ink}" stroke-width="1.1"/>'
            )
    else:
        lip = max(w * 0.12, 2.0)
        for xx in (x + pad + lip, x + w - pad - lip):
            parts.append(
                f'<line x1="{_num(xx)}" y1="{_num(y + inset)}" x2="{_num(xx)}" '
                f'y2="{_num(y + h - inset)}" stroke="{ink}" stroke-width="1.0"/>'
            )
        for yy in (y + pad + 2, y + h - pad - 2):
            parts.append(
                f'<line x1="{_num(x + pad)}" y1="{_num(yy)}" x2="{_num(x + w - pad)}" '
                f'y2="{_num(yy)}" stroke="{ink}" stroke-width="1.1"/>'
            )
    return parts


def _layout_sheet_is_door_only(sheet: Sheet) -> bool:
    """True when every non-duct device on the sheet is On-door."""
    devices = [b for b in sheet.boxes if not _layout_is_wire_duct(b)]
    return bool(devices) and all(_layout_is_door_mount(b) for b in devices)


def _layout_mm_to_svg(project: Project, sheet: Sheet, mm: float) -> float:
    """Map physical mm onto the scaled backplate SVG."""
    if sheet.panel is None:
        return mm * 1.2
    _px, _py, pw, _ph = sheet.panel
    bp_w, _bp_h = _backplate_inches(project)
    return (pw / max(bp_w, 0.1)) * (mm / 25.4)


def _layout_duct_width_svg(project: Project, sheet: Sheet, item=None) -> float:
    """Duct channel width in SVG units: JSON width_mm / width_in, else 40 mm."""
    if item is not None:
        fields = item.fields or {}
        for key in ("width_mm", "duct_width_mm", "wireway_width_mm"):
            raw = fields.get(key, "")
            try:
                mm = float(str(raw).strip())
                if mm > 0:
                    return _layout_mm_to_svg(project, sheet, mm)
            except (TypeError, ValueError):
                pass
        for key in ("width_in", "duct_width_in"):
            raw = fields.get(key, "")
            try:
                inches = float(str(raw).strip())
                if inches > 0:
                    return _layout_mm_to_svg(project, sheet, inches * 25.4)
            except (TypeError, ValueError):
                pass
    return _layout_mm_to_svg(project, sheet, 40.0)


def _layout_auto_duct_rects(project: Project, sheet: Sheet):
    """Minimal H/V duct skeleton around backplate devices (SVG coords)."""
    if sheet.panel is None:
        return []
    devices = [
        b
        for b in sheet.boxes
        if not _layout_is_wire_duct(b) and not _layout_is_door_mount(b)
    ]
    if not devices:
        return []
    px, py, pw, ph = sheet.panel
    duct_w = _layout_duct_width_svg(project, sheet)
    gap = _layout_mm_to_svg(project, sheet, 12.0)
    margin = max(_layout_mm_to_svg(project, sheet, 10.0), 8.0)

    din = [b for b in devices if _layout_is_din_shape(_layout_shape_key(b))]
    cluster_src = din or devices
    rows = []
    for box in sorted(cluster_src, key=lambda b: b.y + b.h / 2.0):
        cy = box.y + box.h / 2.0
        placed = False
        for row in rows:
            ref = row[0].y + row[0].h / 2.0
            if abs(cy - ref) <= max(18.0, box.h * 0.45):
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])

    min_x = min(b.x for b in devices)
    max_x = max(b.x + b.w for b in devices)
    min_y = min(b.y for b in devices)
    max_y = max(b.y + b.h for b in devices)

    rects = []
    v_top = max(min_y - gap, py + margin)
    v_bot = min(max_y + gap, py + ph - margin)
    v_h = max(v_bot - v_top, duct_w)
    left_x = max(min_x - gap - duct_w, px + margin)
    right_x = min(max_x + gap, px + pw - margin - duct_w)
    if left_x + duct_w <= min_x - gap * 0.5:
        rects.append((left_x, v_top, duct_w, v_h, "WD1"))
    if right_x >= max_x + gap * 0.5:
        rects.append((right_x, v_top, duct_w, v_h, "WD2"))

    h_left = max(min_x - gap, px + margin)
    h_right = min(max_x + gap, px + pw - margin)
    h_span = max(h_right - h_left, duct_w)
    tag_i = 3
    for upper, lower in zip(rows, rows[1:]):
        upper_bot = max(b.y + b.h for b in upper)
        lower_top = min(b.y for b in lower)
        space = lower_top - upper_bot
        if space < duct_w + 2 * gap:
            continue
        mid = (upper_bot + lower_top) / 2.0
        hy = mid - duct_w / 2.0
        if hy < upper_bot + gap:
            hy = upper_bot + gap
        if hy + duct_w > lower_top - gap:
            hy = lower_top - gap - duct_w
        if hy < upper_bot + gap * 0.5 or hy + duct_w > lower_top - gap * 0.5:
            continue
        rects.append((h_left, hy, h_span, duct_w, f"WD{tag_i}"))
        tag_i += 1

    top_room = min_y - (py + margin)
    if top_room >= duct_w + gap:
        rects.append((h_left, min_y - gap - duct_w, h_span, duct_w, f"WD{tag_i}"))
        tag_i += 1
    bot_room = (py + ph - margin) - max_y
    if bot_room >= duct_w + gap:
        rects.append((h_left, max_y + gap, h_span, duct_w, f"WD{tag_i}"))
        tag_i += 1

    cleaned = []
    for x, y, w, h, tag in rects:
        overlap = False
        for b in devices:
            if not (
                x + w <= b.x - gap * 0.35
                or b.x + b.w + gap * 0.35 <= x
                or y + h <= b.y - gap * 0.35
                or b.y + b.h + gap * 0.35 <= y
            ):
                overlap = True
                break
        if not overlap and w >= 4 and h >= 4:
            cleaned.append((x, y, w, h, tag))
    return cleaned


def _layout_wire_ducts_markup(project: Project, sheet: Sheet) -> str:
    """Draw plastic wire-duct channels on panel layout sheets.

    JSON wire_duct / wireway items render as normal layout-device footprints.
    When none exist, auto-suggest a minimal H/V routing skeleton on backplate
    sheets (design aid). Door-only sheets get no auto ducts.
    """
    if _layout_sheet_is_door_only(sheet):
        return ""
    if any(_layout_is_wire_duct(b) for b in sheet.boxes):
        return ""
    if any(
        (i.type_id or "").lower() in {"wire_duct", "wireway", "duct", "wiring_duct"}
        for i in project.items
    ):
        return ""
    rects = _layout_auto_duct_rects(project, sheet)
    if not rects:
        return ""
    parts = [
        '<g class="wire-ducts" data-design-aid="routing-guide">',
        "<title>Wire duct routing guide (design aid)</title>",
    ]
    for x, y, w, h, tag in rects:
        cx = x + w / 2.0
        cy = y + h / 2.0
        label = tag if min(w, h) >= 14 and max(w, h) >= 40 else ("DUCT" if max(w, h) >= 36 else "")
        parts.append(
            f'<g class="layout-duct" data-tag="{escape(tag)}" data-footprint="wire_duct" '
            f'data-type="wire_duct">'
        )
        parts.append(_layout_footprint_body("wire_duct", x, y, w, h))
        if label:
            parts.append(
                f'<text class="device-tag" x="{_num(cx)}" y="{_num(cy + 3)}" text-anchor="middle" '
                f'font-family="Consolas, Liberation Mono, monospace" font-size="9" '
                f'font-weight="700" fill="#555555">{escape(label)}</text>'
            )
        parts.append("</g>")
    parts.append("</g>")
    return "".join(parts)



def _layout_door_region_markup(sheet: Sheet, door_boxes: list[Box] | None = None) -> str:
    """Dashed DOOR region; optionally nests On-door device markup inside the group.

    Only door-mounted footprints contribute to the bbox — In-cabinet / Field devices
    must never sit inside this region (they live on separate backplate sheets).
    """
    door = list(door_boxes) if door_boxes is not None else [b for b in sheet.boxes if _layout_is_door_mount(b)]
    if not door:
        return ""
    pad = 10.0
    x1 = min(b.x for b in door) - pad
    y1 = min(b.y for b in door) - pad
    x2 = max(b.x + b.w for b in door) + pad
    y2 = max(b.y + b.h for b in door) + pad
    parts = [
        f'<g class="door-region">',
        f'<rect x="{_num(x1)}" y="{_num(y1)}" width="{_num(x2 - x1)}" height="{_num(y2 - y1)}" '
        f'fill="none" stroke="#666666" stroke-width="1.0" stroke-dasharray="5 4"/>',
        f'<text x="{_num(x1 + 4)}" y="{_num(y1 - 4)}" '
        f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="10" fill="#555555">DOOR</text>',
    ]
    for box in door:
        parts.append(_layout_device_markup(box))
    parts.append("</g>")
    return "".join(parts)


_PROTECTION_ORDER = {"disconnect": 0, "fuse_holder": 1, "breaker": 2, "motor_protector": 3}


def _lp_gland(gx: float, edge_y: float, r: float, up: bool) -> list[str]:
    """Cable gland on the enclosure wall at edge_y (body outside the wall, locknut on the wall)."""
    body_y = edge_y - r * 0.9 if up else edge_y
    return [_lp_rect(gx - r, body_y, 2 * r, r * 0.9, "#d9d9d9", 1.0),
            _lp_rect(gx - r * 1.25, edge_y - r * 0.22, 2.5 * r, r * 0.44, "#ffffff", 1.0),
            _lp_line(gx - r * 0.5, body_y, gx - r * 0.5, body_y + r * 0.9, 0.5),
            _lp_line(gx + r * 0.5, body_y, gx + r * 0.5, body_y + r * 0.9, 0.5)]


def _lp_arrow_down(x: float, y: float, size: float) -> str:
    return (f'<polygon points="{_num(x - size / 2)},{_num(y - size)} {_num(x + size / 2)},{_num(y - size)} '
            f'{_num(x)},{_num(y)}" fill="#000000"/>')


def _layout_power_io_markup(project: Project, sheet: Sheet) -> str:
    """POWER IN gland + feed path to the disconnect / fuses / breakers; POWER OUT strip + exit gland."""
    io = sheet.power_io
    if sheet.panel is None or not io:
        return ""
    px, py, pw, ph = sheet.panel
    mm = _layout_mm_to_svg(project, sheet, 1.0)
    r = max(14.0 * mm, 6.0)  # ~28 mm knockout (3/4 in trade size)
    parts = ['<g class="power-io">']
    plate_boxes = [b for b in sheet.boxes if not _layout_is_door_mount(b)]
    if "in" in io:
        gx = float(io.get("in_x") or px + 40.0)
        parts.append(f'<g class="power-in" data-supply="{escape(io["in"])}">')
        parts.append(f"<title>{escape('POWER IN ' + io['in'])}</title>")
        parts.extend(_lp_gland(gx, py, r, up=True))
        prot = sorted((b for b in plate_boxes if _layout_shape_key(b) in _PROTECTION_ORDER),
                      key=lambda b: (_PROTECTION_ORDER[_layout_shape_key(b)], b.x))
        if prot:
            path_y = max(min(b.y for b in prot) - max(6.0 * mm, 4.0), py + r * 0.4)
            first = prot[0]
            fx = first.x + first.w / 2.0
            parts.append(f'<polyline class="power-path" points="{_num(gx)},{_num(py)} {_num(gx)},{_num(path_y)} '
                         f'{_num(fx)},{_num(path_y)}" fill="none" stroke="#000000" stroke-width="2.2"/>')
            xs = [b.x + b.w / 2.0 for b in prot]
            parts.append(_lp_line(min(xs + [gx]), path_y, max(xs + [gx]), path_y, 1.2, dash="6 3"))
            for n, b in enumerate(prot, start=1):
                bx = b.x + b.w / 2.0
                parts.append(_lp_line(bx, path_y, bx, b.y - 3.0, 1.2))
                parts.append(_lp_arrow_down(bx, b.y, 5.0))
                parts.append(f'<text class="power-step" x="{_num(bx + 3)}" y="{_num(path_y - 2)}" '
                             f'font-family="Consolas, Liberation Mono, monospace" font-size="9" '
                             f'font-weight="700" fill="#000000">{n}</text>')
        else:
            parts.append(_lp_arrow_down(gx, py + r * 1.4, 6.0))
        parts.append("</g>")
    if "out" in io:
        strip = next((b for b in plate_boxes if b.tag == io.get("out_tag") and io.get("out_tag")), None)
        gx = strip.x + strip.w / 2.0 if strip is not None else px + pw * 0.5
        bottom = py + ph
        parts.append(f'<g class="power-out" data-field="{escape(io["out"])}">')
        parts.append(f"<title>{escape('POWER OUT ' + io['out'])}</title>")
        exit_x = gx
        if strip is not None:
            sy = strip.y + strip.h
            below = [b for b in plate_boxes if b is not strip and b.y >= sy - 1
                     and b.x < gx + 2 and b.x + b.w > gx - 2]
            if below:  # drop into the duct under the strip, run to the side duct, then down
                exit_x = px + max(30.0 * mm, 10.0)
                mid = sy + max(26.0 * mm, 6.0)
                pts = (f"{_num(gx)},{_num(sy)} {_num(gx)},{_num(mid)} {_num(exit_x)},{_num(mid)} "
                       f"{_num(exit_x)},{_num(bottom)}")
            else:
                pts = f"{_num(gx)},{_num(sy)} {_num(gx)},{_num(bottom)}"
            parts.append(f'<polyline class="power-out-path" points="{pts}" fill="none" stroke="#000000" '
                         f'stroke-width="2.2"/>')
        parts.extend(_lp_gland(exit_x, bottom, r, up=False))
        text = f"POWER OUT {io['out']} - via {io.get('out_tag') or 'field terminals'} and the exit gland (bottom)"
        right = px + pw
        chars = max(20, int((pw / 2.0 - 40.0) / 6.6))
        lines = _wrap(text, chars)[:2]
        base = bottom + 34.0
        for i, line in enumerate(lines):
            parts.append(f'<text class="power-out-label" x="{_num(right)}" y="{_num(base + i * 13)}" '
                         f'text-anchor="end" font-family="Consolas, Liberation Mono, monospace" font-size="11" '
                         f'font-weight="700" fill="#000000">{escape(line)}</text>')
        parts.append("</g>")
    parts.append("</g>")
    return "".join(parts)


def _layout_scale_markup(project: Project, sheet: Sheet) -> str:
    """Graphic scale bar (inches over millimetres) + plate / enclosure size reference under the plate."""
    if sheet.panel is None:
        return ""
    px, py, pw, ph = sheet.panel
    bp_w, bp_h = _backplate_inches(project)
    enc_w, enc_h = _enclosure_inches(project)
    f = pw / bp_w
    inches = next((n for n in (12, 6, 4, 2, 1) if n * f <= 0.35 * pw), 1)
    bar_y = min(py + ph + 46.0, TITLE_TOP - 60.0)
    seg_h = 6.0
    parts = [f'<g class="scale-bar" data-inches="{inches}" data-svg-per-inch="{_num(f)}">',
             f'<text x="{_num(px)}" y="{_num(bar_y - 6)}" font-family="Segoe UI, Liberation Sans, sans-serif" '
             f'font-size="10" font-weight="700" fill="#000000">SCALE</text>']
    for i in range(inches):
        parts.append(_lp_rect(px + 44 + i * f, bar_y, f, seg_h, "#000000" if i % 2 == 0 else "#ffffff", 0.8))
    every = 1 if f >= 18 else (2 if f >= 9 else inches)
    for i in range(0, inches + 1):
        if i % every == 0 or i == inches:
            lab = f"{i} in" if i == inches else str(i)
            parts.append(f'<text x="{_num(px + 44 + i * f)}" y="{_num(bar_y - 3)}" text-anchor="middle" '
                         f'font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="#000000">{lab}</text>')
    total_mm = inches * 25.4
    step = next(s for s in (50, 25, 10, 5) if total_mm / s >= 2)
    k = 0
    while k * step <= total_mm + 0.01:
        tx = px + 44 + k * step * f / 25.4
        parts.append(_lp_line(tx, bar_y + seg_h, tx, bar_y + seg_h + 4, 0.8))
        lab = f"{k * step} mm" if (k + 1) * step > total_mm + 0.01 else str(k * step)
        parts.append(f'<text x="{_num(tx)}" y="{_num(bar_y + seg_h + 14)}" text-anchor="middle" '
                     f'font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="#000000">{lab}</text>')
        k += 1
    ratio = 100.0 / f if f > 0 else 0
    ref = (f"PLATE {bp_w:g} x {bp_h:g} in ({bp_w * 25.4:.0f} x {bp_h * 25.4:.0f} mm)  ·  ENCLOSURE "
           f"{enc_w:g} x {enc_h:g} in  ·  printed 11x17 approx. 1:{ratio:.1f}")
    room = max(int((PAGE_RIGHT - 8 - px) / 6.0), 20)
    for i, line in enumerate(_wrap(ref, room)[:2]):
        parts.append(f'<text class="size-ref" x="{_num(px)}" y="{_num(bar_y + 34 + i * 12)}" '
                     f'font-family="Consolas, Liberation Mono, monospace" font-size="10" fill="#000000">'
                     f'{escape(line)}</text>')
    parts.append("</g>")
    return "".join(parts)



def _schematic_sheets(
    project: Project,
    library: Library,
    kind: str,
    selected_tag: str = "",
) -> list[Sheet]:
    """Classic ladder / rail schematics: vertical supply rails + device rungs."""
    nodes = _schematic_nodes(project, library, kind)
    if not nodes:
        return []
    if kind == "power":
        supply = _interview_value(project, "supply_voltage") or "LINE"
        base_title = f"Power schematic — {supply}"
    else:
        control = _interview_value(project, "control_voltage") or "24 VDC"
        base_title = f"Control schematic — {control}"
    nodes = _schematic_order(project, nodes, kind)
    chunks = _chunks(nodes, MAX_RUNGS)
    sheets: list[Sheet] = []
    for page_i, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            title = f"{base_title} ({page_i}/{len(chunks)})"
        else:
            title = base_title
        sheet = Sheet(kind=kind, title=title, notes=[ROUTING_NOTE])
        if selected_tag and any(node.tag == selected_tag for node in chunk):
            sheet.selected_tag = selected_tag
        _extra_notes(project, kind, sheet)
        top = SCHEM_TOP
        if sheet.selected_tag:
            top = SELECTED_STRIP_TOP + SELECTED_STRIP_HEIGHT + 16
        for index, node in enumerate(chunk):
            node.w = 280.0 if node.role == "seal_in" else SCHEM_W
            node.h = SCHEM_H
            node.x = RUNG_X + _schematic_dx(project, node, kind)
            node.y = top + index * RUNG_PITCH
            # Outlines never sit on schematic sheets — dedicated outline sheets only.
            node.outline_x = None
            node.outline_y = None
            # Keep short identity lines; always retain a SHORT I/O address line when present.
            kept = list(node.lines[:2])
            if node.io_address:
                short_io = _clip(f"I/O: {node.io_address}", 28)
                if not any(node.io_address in ln for ln in kept):
                    if len(kept) < 2:
                        kept.append(short_io)
                    else:
                        # Prefer readable I/O over a long second identity line.
                        kept[1] = short_io
                else:
                    kept = [short_io if node.io_address in ln else ln for ln in kept]
                    # Ensure the I/O line itself is the short form.
                    kept = [
                        short_io if (ln.startswith("I/O:") or node.io_address in ln) else ln
                        for ln in kept
                    ]
            else:
                kept = kept[:2]
            node.lines = kept[:2]
            sheet.boxes.append(node)
        _ladder_rails(project, sheet, kind)
        _route_ladder(sheet, project, kind)
        if kind == "power" and page_i == 1:
            _supply_stub(project, sheet)
        _apply_label_offsets(project, sheet, page_i)
        sheets.append(sheet)
    return sheets


SCHEMATIC_LABEL_KEY = "schematic_label_offsets"


def schematic_item_id(box: Box) -> str:
    """Project item id behind a schematic box (seal-in composites belong to their coil)."""
    return box.key[5:] if box.key.startswith("seal-") else box.key


def _schematic_order(project: Project, nodes: list[Box], kind: str) -> list[Box]:
    """Designer rung order (item field sch_slot_<kind>); disconnect stays first, ground last."""
    items = {item.id: item for item in project.items}
    keyed: list[tuple[float, int, Box]] = []
    for index, node in enumerate(nodes):
        if node.role == "disconnect":
            key = -1e9
        elif node.role == "ground":
            key = 1e9
        else:
            item = items.get(schematic_item_id(node))
            raw = item.fields.get(f"sch_slot_{kind}") if item is not None else None
            try:
                key = float(raw) if raw not in (None, "") else float(index)
            except (TypeError, ValueError):
                key = float(index)
        keyed.append((key, index, node))
    return [node for _key, _index, node in sorted(keyed, key=lambda row: (row[0], row[1]))]


def schematic_dx_limits(node_w: float) -> tuple[float, float]:
    """How far a rung device may slide and still sit between the rails."""
    return RAIL_X + 24.0 - RUNG_X, RIGHT_BUS_X - 24.0 - node_w - RUNG_X


def _schematic_dx(project: Project, node: Box, kind: str) -> float:
    item = next((it for it in project.items if it.id == schematic_item_id(node)), None)
    if item is None:
        return 0.0
    try:
        dx = float(item.fields.get(f"sch_dx_{kind}") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    low, high = schematic_dx_limits(node.w)
    return max(low, min(high, dx))


def schematic_label_key(kind: str, page: int, text: str, nth: int) -> str:
    return f"{kind}|{page}|{text}|{nth}"


def schematic_label_offsets(project: Project) -> dict[str, list[float]]:
    raw = (project.interview or {}).get(SCHEMATIC_LABEL_KEY) or ""
    if isinstance(raw, dict):
        return dict(raw)
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _apply_label_offsets(project: Project, sheet: Sheet, page: int) -> None:
    offsets = schematic_label_offsets(project)
    if not offsets:
        return
    seen: dict[str, int] = {}
    moved: list[tuple[float, float, str]] = []
    for x, y, text in sheet.labels:
        nth = seen.get(text, 0)
        seen[text] = nth + 1
        off = offsets.get(schematic_label_key(sheet.kind, page, text, nth))
        if isinstance(off, (list, tuple)) and len(off) == 2:
            try:
                x = min(PAGE_RIGHT - 20.0, max(20.0, x + float(off[0])))
                y = min(PAGE_H - 60.0, max(20.0, y + float(off[1])))
            except (TypeError, ValueError):
                pass
        moved.append((x, y, text))
    sheet.labels = moved


def _ladder_rails(project: Project, sheet: Sheet, kind: str) -> None:
    """Classic 2-rail ladder: left hot + right RETURN. PE is a separate ground bar.

    Power topology (SH03):
    - DISC left = LINE; DISC right = post-DISC load bus (e.g. W10).
    - Devices fed from DISC load take hot from that bus only — never from LINE through FU.
    - VFD: left = line wire (W10), right = T-lead/load wire (W20) short stub only.
    - Motor: T-leads only — no LINE feed, no landing on L2/L3 return.

    PE-only overflow (no power devices): omit LINE/L2/L3 rails; keep PE bar + GND drop.
    Stub-only control overflow: omit empty +24/0V rails; keep stubs + connectors only.
    Control default: primary on the hot stub only; return rail is CTL-/0V (never primary on both).
    Signal / inter-device nets: short stub + connectors — never rail-to-rail into 0V.
    """
    if not sheet.boxes:
        return
    top = min(box.y for box in sheet.boxes) - 18
    bot = max(box.y + box.h for box in sheet.boxes) + 18
    if top < 36:
        top = 36
    if bot > TITLE_TOP - 8:
        bot = TITLE_TOP - 8
    left_x = RAIL_X
    right_x = float(RIGHT_BUS_X)
    show_fuse = kind == "power" and _branch_protection_recorded(project)
    disc_loads = set(_disconnect_load_wires(project)) if kind == "power" else set()
    has_disconnect = any(box.role == "disconnect" for box in sheet.boxes)
    non_ground = [box for box in sheet.boxes if box.role != "ground"]
    pe_only = kind == "power" and not non_ground and any(box.role == "ground" for box in sheet.boxes)
    # Control overflow with only stub / inter-device nets: omit empty +24/0V rails
    # (same idea as PE-only omitting LINE/L2/L3).
    stub_only = (
        kind == "control"
        and bool(sheet.boxes)
        and all(_rung_is_stub(box, project) for box in sheet.boxes)
    )
    left_name = "LINE"
    right_name = "RETURN"
    if kind == "power":
        supply = _interview_value(project, "supply_voltage") or "LINE"
        left_name = "LINE"
        right_name = _power_return_name(project)
        if not pe_only:
            sheet.labels.append((left_x + LABEL_LINE_GAP, top - 8, f"{supply}  ({supply_conductors(project)[1]})"))
    else:
        control = _interview_value(project, "control_voltage") or "24 VDC"
        left_name, right_name = _control_rail_names(control)
        if not stub_only:
            sheet.labels.append((left_x + LABEL_LINE_GAP, top - 8, control))
    # PE bar under power ladders — not the rung return rail.
    pe_y = bot + max(12.0, PE_BUS_GAP - 16.0)
    pe_bar = kind == "power" and pe_y <= TITLE_TOP - 16
    ground_boxes = [box for box in sheet.boxes if box.role == "ground"]
    pe_x0 = right_x - 140.0
    pe_x1 = right_x
    if ground_boxes:
        pe_x0 = min(pe_x0, min(box.x + box.w / 2.0 for box in ground_boxes) - 12.0)
    if pe_only:
        # Overflow PE sheet: no empty LINE / L2/L3 — PE conductor only.
        if pe_bar:
            sheet.segments.append(Segment(pe_x0, pe_y, pe_x1, pe_y, "PE"))
            sheet.labels.append((pe_x0 + LABEL_LINE_GAP, pe_y - LABEL_LINE_GAP, "PE BAR"))
    elif stub_only:
        # Stub-only control overflow: no empty +24V / 0V rails — stubs + connectors only.
        pass
    else:
        sheet.segments.append(Segment(left_x, top, left_x, bot, left_name))
        sheet.segments.append(Segment(right_x, top, right_x, bot, right_name))
        sheet.labels.append((left_x + LABEL_LINE_GAP, top + 12, left_name))
        sheet.labels.append((right_x - 36, top + 12, right_name))
        if pe_bar:
            sheet.segments.append(Segment(pe_x0, pe_y, pe_x1, pe_y, "PE"))
            sheet.segments.append(Segment(right_x, bot, right_x, pe_y, "PE"))
            sheet.labels.append((left_x + LABEL_LINE_GAP, pe_y - LABEL_LINE_GAP, "PE BAR"))

    def _power_wires(box: Box) -> list[str]:
        return [w for w in box.wires if w not in GROUND_TOKENS]

    def _add_fuse_branch(mid: float, wire: str, x0: float, x1: float) -> None:
        """Inline FU on a hot stub that does not attach to the LINE rail."""
        fuse_x = x0 + (x1 - x0) * 0.45
        sheet.segments.append(Segment(x0, mid, fuse_x - 8.0, mid, wire))
        sheet.labels.append((fuse_x - 6.0, mid - 14.0, "FU"))
        sheet.segments.append(Segment(fuse_x - 8.0, mid - 6.0, fuse_x - 8.0, mid + 6.0, wire))
        sheet.segments.append(Segment(fuse_x + 8.0, mid - 6.0, fuse_x + 8.0, mid + 6.0, wire))
        sheet.segments.append(Segment(fuse_x - 8.0, mid - 6.0, fuse_x + 8.0, mid + 6.0, wire))
        sheet.segments.append(Segment(fuse_x + 8.0, mid, x1, mid, wire))

    # Gutter x where post-DISC load risers meet device hot stubs (past LINE, past FU zone).
    load_gutter_x = RAIL_X + 52.0
    # Load-side (T-lead) stub length past the device right edge.
    t_lead_stub = 22.0
    signal_stub = 40.0

    for box in sheet.boxes:
        mid = box.y + box.h / 2.0
        power_wires = _power_wires(box)
        primary = power_wires[0] if power_wires else ""
        if box.role == "ground":
            # Ground is lowest power rung: short drop to the PE bar only (not the return rail).
            if pe_bar:
                drop_x = box.x + box.w / 2.0
                sheet.segments.append(Segment(drop_x, box.y + box.h, drop_x, pe_y, "PE"))
                sheet.labels.append((drop_x + LABEL_LINE_GAP, (box.y + box.h + pe_y) / 2.0, "PE"))
                # Tie drop into the PE bar conductor (extend bar left if needed).
                if drop_x < pe_x0:
                    sheet.segments.append(Segment(drop_x, pe_y, pe_x0, pe_y, "PE"))
                    pe_x0 = drop_x
            if box.landing:
                sheet.labels.append(
                (box.x + box.w + CALLOUT_AFTER_SYMBOL, box.y - 2, _clip(box.landing, 28))
            )
            continue

        if pe_only:
            continue

        if box.role == "disconnect":
            left_wire = left_name
            right_wire = primary or left_name
            sheet.segments.append(Segment(left_x, mid, box.x, mid, left_wire))
            sheet.segments.append(Segment(box.x + box.w, mid, right_x, mid, right_wire))
            sheet.labels.append((left_x + LABEL_LINE_GAP, mid - 8, left_name))
            if primary:
                # Past the load-tee riser (LOAD_TEE_STUB) so color/gauge text is not on the vertical.
                wire_lbl_x = box.x + box.w + LOAD_TEE_STUB + LABEL_LINE_GAP
                sheet.labels.append((wire_lbl_x, mid - 8, primary))
                extras = [w for w in power_wires[1:] if w]
                if extras:
                    sheet.labels.append(
                        (wire_lbl_x, mid + 10, ", ".join(extras[:2]))
                    )
            if box.landing:
                # Schematic: park landing RIGHT of symbol (never through the glyph).
                sheet.labels.append(
                    (box.x + box.w + CALLOUT_AFTER_SYMBOL, box.y - 2, _clip(box.landing, 28))
                )
            continue

        # Motor: T-leads end at the motor — no LINE feed, no L2/L3 landing.
        if kind == "power" and box.type_id == "motor":
            load_w = primary
            if load_w:
                stub_x = box.x + box.w + t_lead_stub
                sheet.segments.append(Segment(box.x + box.w, mid, stub_x, mid, load_w))
                sheet.labels.append((box.x + box.w + LABEL_LINE_GAP, mid - 8, load_w))
            if box.landing:
                sheet.labels.append(
                (box.x + box.w + CALLOUT_AFTER_SYMBOL, box.y - 2, _clip(box.landing, 28))
            )
            continue

        # VFD: line wire on left (from DISC load bus), T-leads on right — not to return.
        if kind == "power" and box.type_id == "vfd" and len(power_wires) >= 2:
            line_w, load_w = power_wires[0], power_wires[1]
            fed = line_w in disc_loads and has_disconnect
            if fed:
                if show_fuse:
                    _add_fuse_branch(mid, line_w, load_gutter_x, box.x)
                else:
                    sheet.segments.append(Segment(load_gutter_x, mid, box.x, mid, line_w))
                sheet.labels.append((load_gutter_x + LABEL_LINE_GAP, mid - 8, line_w))
            else:
                fuse_gap = 36.0 if show_fuse else 0.0
                if fuse_gap:
                    fuse_x = left_x + 28.0
                    sheet.segments.append(Segment(left_x, mid, fuse_x - 8.0, mid, line_w))
                    sheet.labels.append((fuse_x - 6.0, mid - 14.0, "FU"))
                    sheet.segments.append(Segment(fuse_x - 8.0, mid - 6.0, fuse_x - 8.0, mid + 6.0, line_w))
                    sheet.segments.append(Segment(fuse_x + 8.0, mid - 6.0, fuse_x + 8.0, mid + 6.0, line_w))
                    sheet.segments.append(Segment(fuse_x - 8.0, mid - 6.0, fuse_x + 8.0, mid + 6.0, line_w))
                    sheet.segments.append(Segment(fuse_x + 8.0, mid, box.x, mid, line_w))
                else:
                    sheet.segments.append(Segment(left_x, mid, box.x, mid, line_w))
                sheet.labels.append((left_x + LABEL_LINE_GAP + (fuse_gap and 40.0 or 0.0), mid - 8, line_w))
            stub_x = box.x + box.w + t_lead_stub
            sheet.segments.append(Segment(box.x + box.w, mid, stub_x, mid, load_w))
            sheet.labels.append((box.x + box.w + LABEL_LINE_GAP, mid - 8, load_w))
            if box.landing:
                sheet.labels.append(
                (box.x + box.w + CALLOUT_AFTER_SYMBOL, box.y - 2, _clip(box.landing, 28))
            )
            continue

        # DISC-load-fed power devices (e.g. PSU on W10): hot from load bus, return on right.
        fed_from_disc = (
            kind == "power"
            and bool(primary)
            and primary in disc_loads
            and has_disconnect
            and box.role not in {"disconnect", "seal_in"}
        )
        if fed_from_disc:
            left_wire = primary
            right_wire = right_name
            if show_fuse:
                _add_fuse_branch(mid, left_wire, load_gutter_x, box.x)
            else:
                sheet.segments.append(Segment(load_gutter_x, mid, box.x, mid, left_wire))
            sheet.segments.append(Segment(box.x + box.w, mid, right_x, mid, right_wire))
            sheet.labels.append((load_gutter_x + LABEL_LINE_GAP, mid - 8, left_wire))
            if box.landing:
                sheet.labels.append(
                (box.x + box.w + CALLOUT_AFTER_SYMBOL, box.y - 2, _clip(box.landing, 28))
            )
            continue

        # Signal / inter-device: stub + connector only (not +24 -> device -> 0V).
        if _rung_is_stub(box, project):
            if primary:
                stub_x = box.x - signal_stub
                sheet.segments.append(Segment(stub_x, mid, box.x, mid, primary))
                sheet.labels.append((stub_x + LABEL_LINE_GAP, mid - 8, primary))
            if box.landing:
                sheet.labels.append(
                (box.x + box.w + CALLOUT_AFTER_SYMBOL, box.y - 2, _clip(box.landing, 28))
            )
            continue

        # Default ladder: rail -> (fuse when recorded) -> device -> RETURN rail.
        # Primary wire is on the hot side only — never labeled on both rails.
        left_wire = primary or left_name
        right_wire = right_name
        fuse_gap = 36.0 if (show_fuse and box.role not in {"disconnect", "seal_in"} and kind == "power") else 0.0
        if fuse_gap:
            fuse_x = left_x + 28.0
            sheet.segments.append(Segment(left_x, mid, fuse_x - 8.0, mid, left_wire))
            sheet.labels.append((fuse_x - 6.0, mid - 14.0, "FU"))
            sheet.segments.append(Segment(fuse_x - 8.0, mid - 6.0, fuse_x - 8.0, mid + 6.0, left_wire))
            sheet.segments.append(Segment(fuse_x + 8.0, mid - 6.0, fuse_x + 8.0, mid + 6.0, left_wire))
            sheet.segments.append(Segment(fuse_x - 8.0, mid - 6.0, fuse_x + 8.0, mid + 6.0, left_wire))
            sheet.segments.append(Segment(fuse_x + 8.0, mid, box.x, mid, left_wire))
        else:
            sheet.segments.append(Segment(left_x, mid, box.x, mid, left_wire))
        sheet.segments.append(Segment(box.x + box.w, mid, right_x, mid, right_wire))
        if primary:
            sheet.labels.append((left_x + LABEL_LINE_GAP + (fuse_gap and 40.0 or 0.0), mid - 8, primary))
            # Extra power wires (e.g. W102 with W101) stay labeled on the hot stub.
            extras = [w for w in power_wires[1:] if w]
            if extras:
                sheet.labels.append(
                    (left_x + LABEL_LINE_GAP + (fuse_gap and 40.0 or 0.0), mid + 10, ", ".join(extras[:2]))
                )
        if box.landing:
            sheet.labels.append(
                (box.x + box.w + CALLOUT_AFTER_SYMBOL, box.y - 2, _clip(box.landing, 28))
            )


def _route_ladder(sheet: Sheet, project: Project | None = None, kind: str = "") -> None:
    """Draw shared wire numbers as orthogonal risers without false multi-wire junctions.

    Post-DISC load nets (e.g. W10): tee into the DISC load bus only, then drop in the
    left gutter to device hot stubs — never onto the LINE stub.

    VFD→motor T-lead nets (e.g. W20): riser on the load/T-lead side only — do not meet
    the line-side (W10) stubs.
    """
    grouped: dict[str, list[Box]] = {}
    for box in sheet.boxes:
        for token in box.wires:
            if token in GROUND_TOKENS:
                continue
            grouped.setdefault(token, []).append(box)
    nets: list[tuple[str, list[Box]]] = []
    for token, boxes in grouped.items():
        uniq: list[Box] = []
        seen: set[str] = set()
        for box in boxes:
            if box.key in seen:
                continue
            seen.add(box.key)
            uniq.append(box)
        if len(uniq) >= 2:
            nets.append((token, uniq))
    nets.sort(
        key=lambda item: (
            max(b.y for b in item[1]) - min(b.y for b in item[1]),
            item[0],
        )
    )
    disc_loads = set(_disconnect_load_wires(project)) if project is not None else set()
    if not disc_loads:
        # Fall back to wires parked on the disconnect box itself.
        for box in sheet.boxes:
            if box.role == "disconnect":
                disc_loads.update(w for w in box.wires if w not in GROUND_TOKENS)
    load_gutter_x = RAIL_X + 52.0
    t_lead_stub = 22.0
    channel = 0
    for token, boxes in nets:
        ordered = sorted(boxes, key=lambda b: (b.y, b.tag))
        disc = next((b for b in ordered if b.role == "disconnect"), None)
        vfd = next((b for b in ordered if b.type_id == "vfd"), None)
        motor = next((b for b in ordered if b.type_id == "motor"), None)
        is_disc_load_net = token in disc_loads and disc is not None
        # T-lead net: on VFD as non-primary power wire, shared with motor.
        vfd_pw = [w for w in (vfd.wires if vfd else []) if w not in GROUND_TOKENS]
        is_t_lead_net = (
            vfd is not None
            and motor is not None
            and token in vfd_pw[1:]
            and token in [w for w in motor.wires if w not in GROUND_TOKENS]
        )

        if is_t_lead_net:
            # Load/T-lead side only — right of VFD/MTR stubs; never the left W10 gutter.
            vx = max(vfd.x + vfd.w, motor.x + motor.w) + t_lead_stub
            y0 = vfd.y + vfd.h / 2.0
            y1 = motor.y + motor.h / 2.0
            trial = Segment(vx, y0, vx, y1, token)
            conflict = False
            for existing in sheet.segments:
                if existing.wire == token:
                    continue
                if segments_cross(trial, existing) or _collinear_overlap(trial, existing):
                    conflict = True
                    break
            if conflict:
                continue
            for box in sheet.boxes:
                if segment_hits_box(trial, box):
                    conflict = True
                    break
            if conflict:
                continue
            sheet.segments.append(trial)
            peer = " → ".join(b.tag for b in (vfd, motor) if b)
            sheet.labels.append((vx + LABEL_LINE_GAP, (y0 + y1) / 2.0 - 6, token))
            sheet.labels.append((vx + LABEL_LINE_GAP, (y0 + y1) / 2.0 + 8, _clip(peer, 22)))
            sheet.drawn_wires.add(token)
            continue

        if is_disc_load_net:
            # Tee into post-DISC load bus (right of DISC), elbow down/across to gutter,
            # then drop to device hot stubs — never T onto the LINE left stub.
            load_tee_x = disc.x + disc.w + LOAD_TEE_STUB
            y_disc = disc.y + disc.h / 2.0
            load_boxes = [b for b in ordered if b.role != "disconnect"]
            if not load_boxes:
                continue
            y_first = load_boxes[0].y + load_boxes[0].h / 2.0
            y_last = load_boxes[-1].y + load_boxes[-1].h / 2.0
            # Cross in the inter-rung gap between DISC and the first load device.
            y_gap = (y_disc + y_first) / 2.0
            gutter_x = load_gutter_x + channel * 14.0
            if gutter_x >= RUNG_X - 10:
                break
            parts = [
                Segment(load_tee_x, y_disc, load_tee_x, y_gap, token),
                Segment(load_tee_x, y_gap, gutter_x, y_gap, token),
                Segment(gutter_x, y_gap, gutter_x, y_last, token),
            ]
            conflict = False
            for trial in parts:
                for existing in sheet.segments:
                    if existing.wire == token:
                        continue
                    if segments_cross(trial, existing) or _collinear_overlap(trial, existing):
                        conflict = True
                        break
                if conflict:
                    break
                for box in sheet.boxes:
                    if segment_hits_box(trial, box):
                        conflict = True
                        break
                if conflict:
                    break
            if conflict:
                continue
            for trial in parts:
                sheet.segments.append(trial)
            peer = " → ".join(b.tag for b in ordered[:3])
            sheet.labels.append((gutter_x + LABEL_LINE_GAP, (y_first + y_last) / 2.0 - 6, token))
            sheet.labels.append((gutter_x + LABEL_LINE_GAP, (y_first + y_last) / 2.0 + 8, _clip(peer, 22)))
            sheet.drawn_wires.add(token)
            channel += 1
            continue

        # Generic shared riser in the left gutter (control nets, etc.).
        vx = RAIL_X + 52.0 + channel * 14.0
        if vx >= RUNG_X - 10:
            break
        y0 = ordered[0].y + ordered[0].h / 2.0
        y1 = ordered[-1].y + ordered[-1].h / 2.0
        if abs(y1 - y0) < 1.0:
            continue
        trial = Segment(vx, y0, vx, y1, token)
        conflict = False
        for existing in sheet.segments:
            # Same-net T-junctions (feeder tapping a rung stub) are connections, not faults.
            if existing.wire == token:
                continue
            if segments_cross(trial, existing) or _collinear_overlap(trial, existing):
                conflict = True
                break
        if conflict:
            continue
        for box in sheet.boxes:
            if segment_hits_box(trial, box):
                conflict = True
                break
        if conflict:
            continue
        sheet.segments.append(trial)
        peer = " → ".join(b.tag for b in ordered[:3])
        sheet.labels.append((vx + LABEL_LINE_GAP, (y0 + y1) / 2.0 - 6, token))
        sheet.labels.append((vx + LABEL_LINE_GAP, (y0 + y1) / 2.0 + 8, _clip(peer, 22)))
        sheet.drawn_wires.add(token)
        channel += 1


def _seal_in_box(stop: PlacedItem, start: PlacedItem, coil: PlacedItem, wire: str, library: Library) -> Box:
    """One series seal-in rung: +24 → NC STOP → NO START/seal → coil → 0V."""
    coil_box = _device_box(coil, library)
    stop_tag = device_tag(stop)
    start_tag = device_tag(start)
    coil_tag = device_tag(coil)
    callout = (
        f"Seal-in: NC {stop_tag} then NO {start_tag}/{coil_tag} aux hold "
        f"energize {coil_tag} coil on {wire}."
    )
    return Box(
        key=f"seal-{coil.id}",
        tag=coil_tag,
        role="seal_in",
        callout=_sentence(callout),
        lines=[
            f"STOP {stop_tag} (NC)",
            f"START {start_tag} (NO) + seal",
            f"COIL {coil_tag}",
            f"Wire {wire}",
        ],
        wires=[wire] + [w for w in coil_box.wires if w != wire and w not in GROUND_TOKENS][:1],
        landing=coil_box.landing or f"A1 coil via {wire}",
        io_address=coil_box.io_address,
        model_x=coil.x,
        model_y=coil.y,
        type_id="seal_in",
        outline_maker=coil_box.outline_maker,
        outline_catalog=coil_box.outline_catalog,
        outline_plain=coil_box.outline_plain or OUTLINE_PLAIN.get("contactor", ""),
        outline_source_url=coil_box.outline_source_url,
        library_id=coil.library_id,
        members=[stop_tag, start_tag, coil_tag],
    )


def _extract_seal_in(
    items: list[PlacedItem], library: Library
) -> tuple[list[Box], list[PlacedItem]]:
    """Collapse STOP+START+coil that share a wire into one series seal-in rung.

    Prefer function/role/contact fields over STOP/START characters in the tag alone.
    """
    by_wire: dict[str, list[PlacedItem]] = {}
    for item in items:
        for token in wire_tokens(item.fields.get("wire_numbers", "")):
            if token in GROUND_TOKENS:
                continue
            by_wire.setdefault(token, []).append(item)
    used: set[str] = set()
    groups: list[Box] = []
    for wire, group in sorted(by_wire.items()):
        uniq: list[PlacedItem] = []
        seen: set[str] = set()
        for item in group:
            if item.id in seen or item.id in used:
                continue
            seen.add(item.id)
            uniq.append(item)
        stops = [i for i in uniq if i.type_id == "pushbutton" and _pushbutton_kind(i) == "stop"]
        starts = [i for i in uniq if i.type_id == "pushbutton" and _pushbutton_kind(i) == "start"]
        coils = [i for i in uniq if i.type_id == "contactor"]
        if not (stops and starts and coils):
            continue
        stop, start, coil = stops[0], starts[0], coils[0]
        groups.append(_seal_in_box(stop, start, coil, wire, library))
        used.update({stop.id, start.id, coil.id})
    remaining = [item for item in items if item.id not in used]
    return groups, remaining


def _schematic_nodes(project: Project, library: Library, kind: str) -> list[Box]:
    taken = {device_tag(item).upper() for item in project.items}
    nodes: list[Box] = []
    ground_box = None
    if kind == "power":
        if _disconnect_recorded(project):
            nodes.append(_disconnect_box(project, taken))
        show_ground, note, tokens = _ground_info(project)
        if show_ground:
            # Place last so the PE drop is short and never crosses load rungs.
            ground_box = _ground_box(note, tokens, taken)
    devices = [item for item in project.items if _kind_for(item.type_id, item) == kind]
    devices.sort(key=lambda item: (_rank(item.type_id, kind), device_tag(item).upper()))
    if kind == "control":
        seal_boxes, devices = _extract_seal_in(devices, library)
        nodes.extend(seal_boxes)
    nodes.extend(_device_box(item, library) for item in devices)
    if ground_box is not None:
        nodes.append(ground_box)
    return nodes


def _device_box(item: PlacedItem, library: Library) -> Box:
    equipment = library.types.get(item.type_id)
    label = equipment.label if equipment is not None else item.type_id
    fields = item.fields
    identity = [label]
    vendor = fields.get("vendor", "").strip()
    catalog = fields.get("catalog", "").strip()
    if vendor:
        identity.append(vendor)
    if catalog:
        identity.append(catalog)
    candidates = ["·".join(identity)]
    wires = fields.get("wire_numbers", "").strip()
    wire_list = wire_tokens(wires)
    if wire_list:
        candidates.append("Wires: " + ", ".join(wire_list))
    io_bits = [fields.get("io_direction", "").strip(), fields.get("io_address", "").strip()]
    io_line = " / ".join(bit for bit in io_bits if bit)
    if io_line:
        candidates.append("I/O: " + io_line)
    landing = " ".join(fields.get("terminal_landings", "").split())
    if landing:
        candidates.append("Lands: " + landing)
    parent = fields.get("parent_tag", "").strip()
    if parent:
        candidates.append("Parent: " + parent)
    for key, caption in (
        ("voltage", "Voltage"),
        ("input_voltage", "Input"),
        ("output_voltage", "Output"),
        ("coil_voltage", "Coil"),
        ("solenoid_voltage", "Coil"),
        ("horsepower", "Power"),
        ("protocol", "Protocol"),
        ("signal", "Signal"),
        ("contact_config", "Contacts"),
        ("wire_color", "Color"),
        ("wire_gauge", "Gauge"),
        ("sensor_kind", "Sensor"),
        ("function", "Function"),
    ):
        value = fields.get(key, "").strip()
        if value:
            candidates.append(f"{caption}: {value}")
    maker, catalog, plain, source_url = _resolve_outline(item, library)
    return Box(
        key=item.id,
        tag=device_tag(item),
        role="plc" if item.type_id == "plc" else "device",
        callout=_callout(item),
        lines=[_clip(line, 56) for line in candidates[:4]],
        wires=wire_list,
        landing=landing,
        io_address=fields.get("io_address", "").strip(),
        model_x=item.x,
        model_y=item.y,
        type_id=item.type_id,
        outline_maker=maker,
        outline_catalog=catalog,
        outline_plain=plain,
        outline_source_url=source_url,
        library_id=item.library_id,
        parent_tag=parent,
        contact_nc=_stored_contact_is_nc(item),
    )


def _disconnect_box(project: Project, taken: set[str]) -> Box:
    tag = _spare_tag(taken, "DISC")
    lines = ["Disconnecting means"]
    supply = _interview_value(project, "supply_voltage")
    if supply:
        lines.append("Supply: " + supply)
    load_wires = _disconnect_load_wires(project)
    if load_wires:
        lines.append("Load: " + ", ".join(load_wires))
    else:
        lines.append("No device is placed for this.")
    disc_landing = (
        f"DISC load: {', '.join(load_wires)} to cabinet loads"
        if load_wires
        else "Disconnect load feeder (provisional — catalog not identified)"
    )
    return Box(
        key="virtual-disconnect",
        tag=tag,
        role="disconnect",
        callout=DISCONNECT_CALLOUT,
        lines=lines,
        wires=list(load_wires),
        landing=disc_landing,
        type_id="disconnect",
        outline_maker="",
        outline_catalog=CATALOG_NOT_IDENTIFIED,
        outline_plain=OUTLINE_PLAIN["disconnect"],
    )


def _ground_box(note: str, tokens: list[str], taken: set[str]) -> Box:
    tag = _spare_tag(taken, "GND")
    lines = ["Ground reference"]
    if tokens:
        lines.append("Wires: " + ", ".join(tokens))
    else:
        lines.append("No PE wire number is stored.")
    callout = _sentence(note) if note and len(note) <= 80 else GROUND_CALLOUT
    if note and callout == GROUND_CALLOUT:
        lines.append(_clip(note, 42))
    return Box(
        key="virtual-ground",
        tag=tag,
        role="ground",
        callout=callout,
        lines=lines[:4],
        wires=list(tokens),
        landing=note,
        type_id="ground",
        outline_maker="",
        outline_catalog=CATALOG_NOT_IDENTIFIED,
        outline_plain=OUTLINE_PLAIN["ground"],
    )


def _extra_notes(project: Project, kind: str, sheet: Sheet) -> None:
    if kind == "power":
        branch = (project.interview.get("branch_protection") or "").strip().lower()
        if branch == "yes":
            sheet.notes.append(
                "Branch-circuit protection is recorded in the interview, but no breaker is placed, so none is drawn."
            )
        show_ground, _note, tokens = _ground_info(project)
        if show_ground and not tokens:
            sheet.notes.append(
                "Ground is mentioned in the cabinet data, but no PE wire number is stored, so no ground conductor is drawn."
            )
    else:
        control = _interview_value(project, "control_voltage")
        if control:
            sheet.notes.append(f"Control voltage recorded on the cabinet: {control}.")


def _cabinet_tags(project: Project) -> dict[str, str]:
    """Map upper tag -> display tag for every placed device."""
    found: dict[str, str] = {}
    for item in project.items:
        tag = device_tag(item)
        found[tag.upper()] = tag
    return found


def _peers_from_landing(landing: str, self_tag: str, known: dict[str, str]) -> list[tuple[str, str]]:
    """When a wire has no peer wire#, recover TO from landing text if the tag exists."""
    text = " ".join((landing or "").split())
    if not text:
        return []
    upper = text.upper()
    hits: list[tuple[str, str]] = []
    for key, display in sorted(known.items(), key=lambda kv: -len(kv[0])):
        if key == self_tag.upper():
            continue
        if key in upper:
            bit = _landing_for_wire(text, key)
            hits.append((display, bit or text))
    return hits


def _item_fields_by_tag(project: Project) -> dict[str, tuple[str, dict[str, str]]]:
    """Map device tag -> (type_id, fields)."""
    found: dict[str, tuple[str, dict[str, str]]] = {}
    for item in project.items:
        tag = device_tag(item)
        if tag:
            found[tag] = (item.type_id, dict(item.fields))
    return found


def _spec_for_box_wire(
    project: Project,
    box: Box,
    wire: str,
    by_tag: dict[str, tuple[str, dict[str, str]]],
) -> tuple[str, str]:
    type_id = box.type_id
    fields: dict[str, str] = {}
    if box.tag in by_tag:
        type_id, fields = by_tag[box.tag]
    elif box.role == "seal_in" and box.members:
        # Prefer coil member fields for seal-in composite.
        for member in reversed(box.members):
            if member in by_tag:
                type_id, fields = by_tag[member]
                break
    spec = conductor_spec(project, type_id=type_id or box.type_id, fields=fields, wire=wire)
    color = spec["color"]
    gauge = spec["gauge"]
    if not color:
        color = resolve_wire_color(project=project, type_id=type_id, fields=fields, wire=wire)
    if not gauge:
        gauge = resolve_wire_gauge(project=project, type_id=type_id, fields=fields, wire=wire)
    return color, gauge


def _apply_conductor_specs(project: Project, sheets: list[Sheet]) -> None:
    """Attach COLOR and GAUGE to wire-ref rows and drawn conductors (design aid)."""
    by_tag = _item_fields_by_tag(project)
    # Wire-token -> first resolved spec (cabinet-wide consistency for shared nets).
    by_wire: dict[str, tuple[str, str]] = {}
    for sheet in sheets:
        for box in sheet.boxes:
            for row in box.connections:
                color, gauge = _spec_for_box_wire(project, box, row.wire, by_tag)
                # PE / ground tokens: never inherit device Black/Blue paints.
                if (row.wire or "").strip().upper() in GROUND_TOKENS:
                    color = _pe_schedule_color(color, project)
                row.color = color
                row.gauge = gauge
                if row.wire and row.wire not in by_wire and (color or gauge):
                    by_wire[row.wire] = (color, gauge)
            for token in box.wires:
                if token not in by_wire:
                    by_wire[token] = _spec_for_box_wire(project, box, token, by_tag)
    bus_tokens = {"PE", "GND", "GROUND", "+24V", "+24", "24V", "0V", "LINE", "L1", "L2", "L3", "N"}
    for sheet in sheets:
        for segment in sheet.segments:
            if not segment.wire:
                continue
            token_u = segment.wire.strip().upper()
            if token_u in bus_tokens or segment.wire not in by_wire:
                color = resolve_wire_color(project=project, type_id="", fields={}, wire=segment.wire)
                gauge = resolve_wire_gauge(project=project, type_id="", fields={}, wire=segment.wire)
            else:
                color, gauge = by_wire[segment.wire]
            segment.color = color
            segment.gauge = gauge
        # Annotate conductor labels that are bare wire numbers with color/gauge.
        new_labels: list[tuple[float, float, str]] = []
        for x, y, label in sheet.labels:
            text = (label or "").strip()
            if text in by_wire:
                color, gauge = by_wire[text]
                bits = [text]
                if color:
                    bits.append(color)
                if gauge:
                    bits.append(gauge)
                new_labels.append((x, y, " · ".join(bits)))
            else:
                new_labels.append((x, y, label))
        sheet.labels = new_labels


def _annotate_connections(project: Project, sheets: list[Sheet]) -> None:
    """Attach from/to rows for every stored wire number on every schematic box."""
    peers: dict[str, list[tuple[str, str]]] = {}
    known = _cabinet_tags(project)
    for item in project.items:
        tag = device_tag(item)
        landing = " ".join(item.fields.get("terminal_landings", "").split())
        for token in wire_tokens(item.fields.get("wire_numbers", "")):
            peers.setdefault(token, []).append((tag, landing))
    # Virtual ground may also carry PE tokens that already appear on devices.
    for sheet in sheets:
        if sheet.kind == "layout":
            continue
        for box in sheet.boxes:
            if box.role in {"ground", "disconnect"}:
                for token in box.wires:
                    peers.setdefault(token, [])
                    if not any(tag == box.tag for tag, _landing in peers[token]):
                        peers[token].append((box.tag, box.landing))
            # Seal-in members share the coil wire for from/to peers.
            if box.role == "seal_in":
                for token in box.wires:
                    peers.setdefault(token, [])
                    if not any(tag == box.tag for tag, _landing in peers[token]):
                        peers[token].append((box.tag, box.landing))
    for sheet in sheets:
        if sheet.kind == "layout":
            continue
        for box in sheet.boxes:
            rows: list[ConnectionRow] = []
            for token in box.wires:
                local_landing = _landing_for_wire(box.landing, token)
                from_label = f"{box.tag} / {local_landing}" if local_landing else box.tag
                others = [
                    (tag, landing)
                    for tag, landing in peers.get(token, [])
                    if tag != box.tag
                ]
                if not others and token not in GROUND_TOKENS:
                    others = _peers_from_landing(box.landing, box.tag, known)
                if others:
                    to_parts = []
                    for tag, landing in others:
                        bit = _landing_for_wire(landing, token)
                        to_parts.append(f"{tag} / {bit}" if bit else tag)
                    to_label = ", ".join(to_parts)
                else:
                    to_label = NOT_IDENTIFIED
                rows.append(ConnectionRow(wire=token, from_label=from_label, to_label=to_label))
            box.connections = rows


def _landing_for_wire(landing: str, token: str) -> str:
    """Prefer the landing clause that mentions this wire; otherwise a short clip."""
    text = " ".join((landing or "").split())
    if not text:
        return ""
    upper = text.upper()
    needle = token.upper()
    if needle in upper:
        parts = re.split(r"[,;]", text)
        for part in parts:
            if needle in part.upper():
                return _clip(" ".join(part.split()), 36)
    return _clip(text, 36)


def _route(sheet: Sheet) -> None:
    grouped: dict[str, list[int]] = {}
    for index, box in enumerate(sheet.boxes):
        for token in box.wires:
            grouped.setdefault(token, []).append(index)
    nets = [_Net(token, sorted(set(indices))) for token, indices in grouped.items() if len(set(indices)) >= 2]
    nets.sort(key=lambda net: (0 if net.token in GROUND_TOKENS else 1, net.span[1] - net.span[0], net.span[0], net.token))
    chosen: list[_Net] = []
    used: set[int] = set()
    for net in nets:
        if any(index in used for index in net.indices):
            continue
        if any(_intervals_cross(net.span, other.span) for other in chosen):
            continue
        chosen.append(net)
        used.update(net.indices)
    chosen.sort(key=lambda net: (net.span[1] - net.span[0], net.span[0], net.token))
    groups: list[list[_Net]] = []
    for net in chosen:
        placed = False
        for index, group in enumerate(groups):
            if all(not _intervals_overlap(net.span, other.span) for other in group):
                net.channel = index
                group.append(net)
                placed = True
                break
        if not placed:
            net.channel = len(groups)
            groups.append([net])
    strip_bottom = SELECTED_STRIP_TOP + SELECTED_STRIP_HEIGHT + 8 if sheet.selected_tag else 40
    for net in chosen:
        y = ROW_Y - 28 - net.channel * CHANNEL_PITCH
        if y < strip_bottom:
            continue
        boxes = [sheet.boxes[index] for index in net.indices]
        xs = [box.x + box.w / 2 for box in boxes]
        left, right = min(xs), max(xs)
        sheet.segments.append(Segment(left, y, right, y, net.token))
        for x_pos, box in zip(xs, boxes):
            sheet.segments.append(Segment(x_pos, y, x_pos, box.y, net.token))
        if abs(right - left) < 1.0:
            # Vertical-only run (one column): wire tag to the RIGHT of the stem.
            mid_y = (y + min(box.y for box in boxes)) / 2.0
            sheet.labels.append((left + LABEL_LINE_GAP, mid_y, net.token))
        else:
            # Horizontal bus: keep the tag above the stroke, never on it.
            sheet.labels.append(((left + right) / 2.0, y - LABEL_LINE_GAP, net.token))
        sheet.drawn_wires.add(net.token)


def supply_conductors(project: Project) -> tuple[str, str]:
    """(phase text, conductors) for the incoming supply: 480 VAC -> ('3-phase', 'L1 L2 L3 + PE')."""
    supply = (_interview_value(project, "supply_voltage") or "").upper()
    phase = (_interview_value(project, "supply_phase") or "").lower()
    if "DC" in supply:
        return "DC", "+ / 0V + PE"
    if "120" in supply or "110" in supply:
        return "1-phase", "L1 N + PE"
    if any(v in supply for v in ("220", "230", "240")) and not phase.startswith("3") and "3-PHASE" not in supply:
        return "1-phase", "L1 L2 + PE"
    if not supply:
        return "", "L1/L2/L3"
    return "3-phase", "L1 L2 L3 + PE"


def _supply_stub(project: Project, sheet: Sheet) -> None:
    """POWER IN: the field supply enters top-left and lands on the disconnect line side
    (or the LINE rail when no disconnect is drawn). PE lands on the separate ground bar."""
    if not any(box.role != "ground" for box in sheet.boxes):
        return
    disconnect = next((box for box in sheet.boxes if box.role == "disconnect"), None)
    first = disconnect or min(sheet.boxes, key=lambda b: b.y)
    y = first.y + (36 if disconnect is not None else first.h / 2.0)
    supply = _interview_value(project, "supply_voltage")
    phase, conductors = supply_conductors(project)
    # Keep the supply arrow in the left margin — never through the rung-gutter risers.
    sheet.segments.append(Segment(RAIL_X - 34.0, y, RAIL_X, y, "LINE"))
    sheet.labels.append((RAIL_X - 17.0, y - LABEL_LINE_GAP, supply or "LINE"))
    sheet.labels.append((RAIL_X - 17.0, y + 14.0, "POWER IN"))
    where = "the disconnect line side" if disconnect is not None else "the LINE rail"
    sheet.notes.append(f"POWER IN: {supply or 'supply'} {phase} - {conductors} enter at the top cable entry and land "
                       f"on {where}; the PE conductor lands on the ground bar.".replace("  ", " "))


def _link_wires(sheets: list[Sheet]) -> None:
    hits: dict[str, list[tuple[Sheet, Box]]] = {}
    for sheet in sheets:
        if sheet.kind == "layout":
            continue
        for box in sheet.boxes:
            for token in box.wires:
                hits.setdefault(token, []).append((sheet, box))
    for token, places in hits.items():
        by_sheet: dict[int, list[tuple[Sheet, Box]]] = {}
        for sheet, box in places:
            by_sheet.setdefault(sheet.number, []).append((sheet, box))
        if len(by_sheet) == 1 and len(places) < 2:
            continue
        # On-page refs when a shared wire cannot be drawn as a line on this sheet.
        for sheet_no, members in by_sheet.items():
            sheet = members[0][0]
            local = [box for _sheet, box in members]
            if token not in sheet.drawn_wires and len(local) >= 2:
                for box in local:
                    others = [other.tag for other in local if other.key != box.key]
                    _add_connector(sheet, box, "on-page", token, "SEE " + ", ".join(others))
        # Off-page carry-over: same wire number and peer tag on both ends (TO / FROM).
        sheet_numbers = sorted(by_sheet)
        if len(sheet_numbers) < 2:
            continue
        # Chain adjacent sheets only so the reader follows TO / FROM without a mesh of arrows.
        for left_no, right_no in zip(sheet_numbers, sheet_numbers[1:]):
            left_sheet = by_sheet[left_no][0][0]
            left_box = max((box for _s, box in by_sheet[left_no]), key=lambda box: box.x)
            right_sheet = by_sheet[right_no][0][0]
            right_box = min((box for _s, box in by_sheet[right_no]), key=lambda box: box.x)
            _add_connector(
                left_sheet,
                left_box,
                "off-page",
                token,
                f"TO SH {right_no} {right_box.tag}",
            )
            _add_connector(
                right_sheet,
                right_box,
                "off-page",
                token,
                f"FROM SH {left_no} {left_box.tag}",
            )


def _link_io(sheets: list[Sheet]) -> None:
    """Off-page I/O arrows to the owning PLC (parent_tag), not always the first PLC."""
    # Prefer control schematic placements — outline copies must not steal ownership.
    plc_places = [
        (sheet, box)
        for sheet in sheets
        for box in sheet.boxes
        if box.role == "plc" and sheet.kind == "control" and not sheet.outline_only
    ]
    if not plc_places:
        plc_places = [
            (sheet, box)
            for sheet in sheets
            for box in sheet.boxes
            if box.role == "plc" and sheet.kind != "layout" and not sheet.outline_only
        ]
    if not plc_places:
        return
    plc_by_tag = {box.tag.upper(): (sheet, box) for sheet, box in plc_places}

    def _owning_plc(box: Box) -> tuple[Sheet, Box]:
        parent = (box.parent_tag or "").strip().upper()
        if parent and parent in plc_by_tag:
            return plc_by_tag[parent]
        land = (box.landing or "").upper()
        for tag, place in plc_by_tag.items():
            if tag and tag in land:
                return place
        if len(plc_places) == 1:
            return plc_places[0]
        # Same-sheet PLC if present; else first listed.
        for sheet, plc_box in plc_places:
            if any(b.key == box.key for b in sheet.boxes):
                return sheet, plc_box
        return plc_places[0]

    for sheet in sheets:
        if sheet.kind == "layout":
            continue
        for box in sheet.boxes:
            if box.role != "device" or not _usable_address(box.io_address):
                continue
            plc_sheet, plc_box = _owning_plc(box)
            if sheet.number == plc_sheet.number:
                continue
            _add_connector(
                sheet,
                box,
                "off-page",
                "I/O",
                f"TO SH {plc_sheet.number} {plc_box.tag} {box.io_address}",
            )
            _add_connector(
                plc_sheet,
                plc_box,
                "off-page",
                "I/O",
                f"FROM SH {sheet.number} {box.tag} {box.io_address}",
            )


def _add_connector(sheet: Sheet, box: Box, kind: str, wire: str, label: str) -> None:
    sheet.connectors.append(Connector(box_key=box.key, kind=kind, wire=wire, label=label))


def _place_wire_rows(sheet: Sheet) -> None:
    """Keep from/to rows readable. Ladder puts them beside the rung; never shrink type."""
    if sheet.kind == "layout" or sheet.outline_only or sheet.kind == WIRE_SCHEDULE_KIND:
        return
    if sheet.kind in {"power", "control"}:
        # Under the rung (INTER_RUNG_GAP) — short list so the ladder stays clear.
        for box in sheet.boxes:
            rows = list(box.connections[:MAX_WIRE_ROWS])
            if len(box.connections) > len(rows):
                sheet.notes.append(
                    f"{box.tag} wire list continues via off-page connectors; "
                    f"all stored numbers remain on the connection strip when selected."
                )
            box.connections = rows
        return
    row_pitch = 32
    limit = TITLE_TOP - 16
    for box in sheet.boxes:
        rows = list(box.connections[:MAX_WIRE_ROWS])
        start = box.y + box.h + CALLOUT_GAP + 16
        needed = start + 16 + len(rows) * row_pitch
        if needed > limit and rows:
            room = max(0, int((limit - start - 16) / row_pitch))
            if room < len(rows):
                sheet.notes.append(
                    f"{box.tag} wire list continues via off-page connectors; "
                    f"all stored numbers remain on the connection strip when selected."
                )
            box.connections = rows[:room] if room else rows[:1]
        else:
            box.connections = rows


def _position_connectors(sheet: Sheet) -> None:
    if sheet.kind == "layout" or sheet.outline_only or sheet.kind == WIRE_SCHEDULE_KIND:
        # Layout off-page arrows are already parked in the gutter.
        return
    grouped: dict[str, list[Connector]] = {}
    for connector in sheet.connectors:
        grouped.setdefault(connector.box_key, []).append(connector)
    boxes = {box.key: box for box in sheet.boxes}
    visible: list[Connector] = []
    ladder = sheet.kind in {"power", "control"}
    for key, connectors in grouped.items():
        box = boxes.get(key)
        if box is None:
            continue
        if ladder:
            # Trunk past the callout band, left of the return rail; arrow tip gap >= 8.
            trunk_x = _ladder_trunk_x(box)
            base = box.y + 6
            room = max(1, int((box.h + 20) / 16))
            pe_y = _sheet_pe_bar_y(sheet)
            shown = connectors[: min(MAX_CONNECTORS, room)]
            # Only the ground / PE-only overflow sheet parks PE stubs on the PE bar
            # (same conductor as GND→PE drop). Device PE refs on mixed ladders stay
            # at the trunk so a PE riser does not cross return rungs.
            tie_pe_to_bar = pe_y is not None and box.role == "ground"
            if tie_pe_to_bar:
                pe_shown = [c for c in shown if (c.wire or "").upper() in GROUND_TOKENS]
                other_shown = [c for c in shown if (c.wire or "").upper() not in GROUND_TOKENS]
            else:
                pe_shown = []
                other_shown = list(shown)
            if pe_shown:
                # Drop from ground trunk into the PE bar; arrows sit on that PE conductor.
                sheet.segments.append(Segment(trunk_x, base, trunk_x, pe_y, "PE"))
                sheet.segments.append(
                    Segment(
                        min(trunk_x, _sheet_pe_bar_x0(sheet)),
                        pe_y,
                        max(trunk_x + ARROW_SHAFT + 24.0 * len(pe_shown), _sheet_pe_bar_x1(sheet)),
                        pe_y,
                        "PE",
                    )
                )
                for pe_i, connector in enumerate(pe_shown):
                    connector.x = trunk_x + pe_i * 22.0
                    connector.y = pe_y
                    connector.arrow_dir = "right"
                    sheet.segments.append(
                        Segment(connector.x, pe_y, connector.x + ARROW_SHAFT, pe_y, connector.wire)
                    )
            for index, connector in enumerate(other_shown):
                connector.x = trunk_x
                connector.y = base + index * 18
                connector.arrow_dir = "right"
                if connector.kind == "off-page":
                    sheet.segments.append(
                        Segment(connector.x, connector.y, connector.x + ARROW_SHAFT, connector.y, connector.wire)
                    )
            shown = pe_shown + other_shown
            visible.extend(shown)
            if len(connectors) > len(shown):
                sheet.notes.append(
                    f"{box.tag} has more references than fit beside the rung. Wire numbers stay on the from/to list."
                )
            continue
        wire_rows = min(len(box.connections), MAX_WIRE_ROWS)
        base = box.y + box.h + CALLOUT_GAP + 16 + wire_rows * 32 + 12
        if base > TITLE_TOP - 40:
            if connectors:
                sheet.notes.append(
                    f"{box.tag} has more references than fit under the block. Wire numbers stay on the from/to list."
                )
            continue
        room = max(0, int((TITLE_TOP - 16 - base) / 20))
        shown = connectors[: min(MAX_CONNECTORS, room)]
        visible.extend(shown)
        if len(connectors) > len(shown):
            sheet.notes.append(
                f"{box.tag} has more references than fit under the block. Wire numbers stay on the from/to list."
            )
        trunk_x = box.x
        for index, connector in enumerate(shown):
            connector.x = trunk_x
            connector.y = base + index * 20
            connector.arrow_dir = "right"
        if not shown:
            continue
        last_y = shown[-1].y
        sheet.segments.append(Segment(trunk_x, box.y + box.h, trunk_x, last_y, ""))
        for connector in shown:
            if connector.kind == "off-page":
                sheet.segments.append(
                    Segment(connector.x, connector.y, connector.x + ARROW_SHAFT, connector.y, connector.wire)
                )
    sheet.connectors = visible


def _box_markup(sheet: Sheet, box: Box) -> str:
    """Layout cards keep rectangles; power/control use ladder symbols only (no card)."""
    fill = "#ffffff"
    if box.role == "disconnect":
        fill = "#fff8f0"
    elif box.role == "ground":
        fill = "#f2f7f3"
    clip = f"s{sheet.number}-{_safe_id(box.key)}"
    symbol_kind = box.type_id or box.role
    schematic = sheet.kind in {"power", "control"}
    tip = box_hover_detail(box).replace("\n", " | ")
    lines = [
        f'<g class="block" data-tag="{escape(box.tag)}" data-role="{escape(box.role)}" data-type="{escape(symbol_kind)}">',
        f"<title>{escape(tip)}</title>",
        f"<desc>{escape(box.callout)}</desc>",
    ]
    if schematic:
        # Shop schematic: symbol always; coil tag/name only on canvas.
        # Wire numbers, FROM-TO, color, gauge, landings, callouts, I/O → hover (title + viewer).
        lines.append(
            f'<rect class="hit-target" x="{_num(box.x - 20)}" y="{_num(box.y - 20)}" '
            f'width="{_num(box.w + 40)}" height="{_num(box.h + 40)}" '
            f'fill="#ffffff" fill-opacity="0.01" stroke="none"/>'
        )
        lines.append(_symbol_markup(box, symbol_kind))
        if _is_coil_box(box):
            tag_x = box.x + box.w / 2.0
            lines.append(
                f'<text class="device-tag coil-desc" x="{_num(tag_x)}" y="{_num(box.y + 12)}" text-anchor="middle" '
                f'font-family="Consolas, Liberation Mono, monospace" font-size="12" font-weight="700" fill="#000000">'
                f"{escape(box.tag)}</text>"
            )
    else:
        lines.extend(
            [
                f'<clipPath id="{clip}"><rect x="{_num(box.x)}" y="{_num(box.y)}" width="{_num(box.w)}" height="{_num(box.h)}"/></clipPath>',
                f'<rect x="{_num(box.x)}" y="{_num(box.y)}" width="{_num(box.w)}" height="{_num(box.h)}" fill="{fill}" stroke="#000000" stroke-width="1.5"/>',
                f'<g clip-path="url(#{clip})">',
            ]
        )
        if sheet.kind != "layout":
            lines.append(_symbol_markup(box, symbol_kind))
        text_left = box.x + (56 if sheet.kind != "layout" else 8)
        lines.append(
            f'<text x="{_num(text_left)}" y="{_num(box.y + 20)}" font-family="Consolas, Liberation Mono, monospace" '
            f'font-size="{FONT_TAG}" font-weight="700" fill="#000000">{escape(box.tag)}</text>'
        )
        for index, line in enumerate(box.lines[:4]):
            lines.append(
                f'<text x="{_num(text_left)}" y="{_num(box.y + 42 + index * 14)}" '
                f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="{FONT_LINE}" fill="#000000">'
                f"{escape(_clip(line, 56))}</text>"
            )
        lines.append("</g>")
        if sheet.kind != "layout":
            text_x = box.x + LABEL_LINE_GAP
            width = _chars_fit(text_x, FONT_CALLOUT, mono=False)
            callout_lines = _wrap_two(box.callout, width)
            callout_y = box.y + box.h + 12
            for index, line in enumerate(callout_lines):
                y = callout_y + index * 14
                if y >= TITLE_TOP - 4:
                    break
                lines.append(
                    f'<text class="callout" x="{_num(text_x)}" y="{_num(y)}" '
                    f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="{FONT_CALLOUT}" fill="#333333">'
                    f"{escape(line)}</text>"
                )
        else:
            # Layout cards: tag + lines inside; callout BELOW the card so it never covers tile text.
            width = _chars_fit(box.x + 8, FONT_CALLOUT, mono=False, right=min(PAGE_RIGHT, box.x + box.w + 8))
            callout_lines = _wrap_two(box.callout, max(20, min(width, 48))) or [box.callout]
            base = box.y + box.h + 14
            for index, line in enumerate(callout_lines[:2]):
                y = base + index * 14
                if y >= TITLE_TOP - 4:
                    break
                lines.append(
                    f'<text class="callout" x="{_num(box.x + 8)}" y="{_num(y)}" '
                    f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="{FONT_CALLOUT}" fill="#333333">'
                    f"{escape(line)}</text>"
                )
    lines.append("</g>")
    return "".join(lines)


def _wire_rows_markup(box: Box) -> str:
    if not box.connections:
        return ""
    # Ladder: Wire·From·To sits PAST the return rail (split band — not under callouts).
    schematic_style = box.w <= SCHEM_W + 1 or box.role == "seal_in"
    if schematic_style:
        text_x = float(RIGHT_BUS_X) + LABEL_LINE_GAP
        # Under-rung band: leave a clear gap below the symbol so refs never kiss the glyph.
        start_y = box.y + SCHEM_H + 22
        # Bottom rung: From·To would hit the title block — park beside the device,
        # still clear of the symbol (never through the glyph).
        row_budget = 16 + 16 * max(1, min(len(box.connections), MAX_WIRE_ROWS))
        if start_y + row_budget > TITLE_TOP - 4:
            start_y = max(box.y + 22.0, min(box.y + SCHEM_H - 4.0, TITLE_TOP - 4 - row_budget))
            # Prefer the far-right band so parked rows stay off the callout/trunk.
            text_x = float(RIGHT_BUS_X) + LABEL_LINE_GAP + 4.0
        right_limit = PAGE_RIGHT - 4
    else:
        text_x = box.x + LABEL_LINE_GAP
        start_y = box.y + box.h + CALLOUT_GAP + 16
        right_limit = None
    parts = [f'<g class="wire-refs" data-tag="{escape(box.tag)}">']
    header_y = start_y
    if header_y >= TITLE_TOP - 4:
        return ""
    width = _chars_fit(text_x, FONT_WIRE, mono=True, right=right_limit)
    parts.append(
        f'<text class="wire-ref-header" x="{_num(text_x)}" y="{_num(header_y)}" '
        f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="{FONT_WIRE}" font-weight="700" fill="#444444">'
        "Wire · Color · Gauge · From · To</text>"
    )
    y = start_y + 16
    for row in box.connections[:MAX_WIRE_ROWS]:
        if y >= TITLE_TOP - 4:
            break
        color = (row.color or "—").strip() or "—"
        gauge = (row.gauge or "—").strip() or "—"
        raw = f"{row.wire}  {color}  {gauge}  {row.from_label}  →  {row.to_label}"
        wrapped = _wrap_two(raw, width)
        for line in wrapped:
            if y >= TITLE_TOP - 4:
                break
            color_attr = f' data-color="{escape(row.color)}"' if row.color else ""
            gauge_attr = f' data-gauge="{escape(row.gauge)}"' if row.gauge else ""
            parts.append(
                f'<text class="wire-ref" data-wire="{escape(row.wire)}"'
                f"{color_attr}{gauge_attr} "
                f'x="{_num(text_x)}" y="{_num(y)}" '
                f'font-family="Consolas, Liberation Mono, monospace" font-size="{FONT_WIRE}" fill="#000000">'
                f"{escape(line)}</text>"
            )
            y += 14
        y += 4  # small gap between wire rows
    parts.append("</g>")
    return "".join(parts)


def _selected_strip_markup(sheet: Sheet) -> str:
    if not sheet.selected_tag:
        return ""
    x0, y0 = 28.0, float(SELECTED_STRIP_TOP)
    width = PAGE_W - 56.0
    height = float(SELECTED_STRIP_HEIGHT)
    parts = [
        f'<g class="selected-connections" data-tag="{escape(sheet.selected_tag)}">',
        f'<rect x="{_num(x0)}" y="{_num(y0)}" width="{_num(width)}" height="{_num(height)}" '
        'fill="#f7fafc" stroke="#000000" stroke-width="1.2"/>',
        f'<text x="{_num(x0 + 10)}" y="{_num(y0 + 18)}" '
        'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="13" font-weight="700" fill="#000000">'
        f"Selected device {escape(sheet.selected_tag)} - wire connections</text>",
        f'<text x="{_num(x0 + 10)}" y="{_num(y0 + 36)}" '
        'font-family="Consolas, Liberation Mono, monospace" font-size="11" font-weight="700" fill="#444444">'
        "Wire    Color      Gauge   From                          To</text>",
    ]
    rows = sheet.selected_connections[:5]
    if not rows:
        parts.append(
            f'<text x="{_num(x0 + 10)}" y="{_num(y0 + 54)}" '
            'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="12" fill="#000000">'
            "No wire numbers are stored on this device.</text>"
        )
    for index, row in enumerate(rows):
        y = y0 + 54 + index * 14
        line = (
            f"{row.wire:<8}  {_clip(row.color or '—', 10):<10}  {_clip(row.gauge or '—', 8):<8}  "
            f"{_clip(row.from_label, 24):<24}  {_clip(row.to_label, 28)}"
        )
        parts.append(
            f'<text class="selected-row" data-wire="{escape(row.wire)}" '
            f'x="{_num(x0 + 10)}" y="{_num(y)}" '
            'font-family="Consolas, Liberation Mono, monospace" font-size="11" fill="#000000">'
            f"{escape(line)}</text>"
        )
    parts.append("</g>")
    return "".join(parts)



def verified_catalogs(library: Library) -> dict[str, str]:
    """Map catalog number -> source_url for library items that were verified."""
    found: dict[str, str] = {}
    for item in library.catalog:
        catalog = (item.catalog or "").strip()
        url = (getattr(item, "source_url", None) or "").strip()
        if catalog and url:
            found[catalog] = url
    return found


def _resolve_outline(item: PlacedItem, library: Library) -> tuple[str, str, str, str]:
    """Return maker, catalog-or-not-identified, plain English role, source_url.

    Never invents a catalog. Only a library entry with a non-empty source_url
    may print its catalog on the engineered outline callout.
    Sensor plain text comes from stored description / sensor_kind / library summary,
    not a hard-coded "inductive proximity" for every sensor.
    """
    type_id = item.type_id
    plain = _outline_plain_for(item, library)
    vendor = item.fields.get("vendor", "").strip()
    catalog = item.fields.get("catalog", "").strip()
    verified = verified_catalogs(library)
    # Prefer the library row for this placement when it carries a source_url.
    if item.library_id:
        row = library.catalog_by_id.get(item.library_id)
        if row is not None and (getattr(row, "source_url", None) or "").strip():
            use_catalog = (row.catalog or "").strip()
            if use_catalog and use_catalog in verified:
                maker = (row.vendor or vendor or "Allen-Bradley").strip()
                return maker, use_catalog, plain, verified[use_catalog]
    if catalog and catalog in verified:
        maker = vendor or "Allen-Bradley"
        return maker, catalog, plain, verified[catalog]
    return vendor, CATALOG_NOT_IDENTIFIED, plain, ""


def _try_place_outline_beside(box: Box) -> bool:
    """Park the outline to the right of the schematic block when it fits."""
    ox = box.x + box.w + OUTLINE_GAP
    oy = box.y
    if ox + OUTLINE_W > PAGE_W - 28:
        box.outline_x = None
        box.outline_y = None
        return False
    if oy + OUTLINE_H > TITLE_TOP - 8:
        box.outline_x = None
        box.outline_y = None
        return False
    box.outline_x = ox
    box.outline_y = oy
    if not box.outline_catalog:
        box.outline_catalog = CATALOG_NOT_IDENTIFIED
    if not box.outline_plain:
        box.outline_plain = OUTLINE_PLAIN.get(box.type_id, "suggested installable component")
    return True


def _outline_overflow_sheets(sheets: list[Sheet]) -> list[Sheet]:
    """Dedicated component-outline sheets when the outline would crowd the schematic."""
    extras: list[Sheet] = []
    seen: set[str] = set()

    def emit(box: Box) -> None:
        if box.outline_x is not None:
            return
        tag_key = box.tag.upper()
        if tag_key in seen:
            return
        seen.add(tag_key)
        clone = Box(
            key=f"{box.key}-outline",
            tag=box.tag,
            role=box.role,
            callout=box.callout,
            lines=list(box.lines[:2]),
            type_id=box.type_id,
            outline_maker=box.outline_maker,
            outline_catalog=box.outline_catalog or CATALOG_NOT_IDENTIFIED,
            outline_plain=box.outline_plain or OUTLINE_PLAIN.get(box.type_id, "suggested installable component"),
            outline_source_url=box.outline_source_url,
            library_id=box.library_id,
        )
        clone.x = (PAGE_W - OUTLINE_W) / 2
        clone.y = 120.0
        clone.w = OUTLINE_W
        clone.h = OUTLINE_H
        clone.outline_x = clone.x
        clone.outline_y = clone.y
        extras.append(
            Sheet(
                kind="outline",
                title=f"Component outline - {box.tag}",
                boxes=[clone],
                notes=[
                    "Engineered outline of the suggested installable hardware. "
                    "Catalog numbers appear only when verified on a public maker page."
                ],
                outline_only=True,
            )
        )

    # Prefer schematic boxes (verified catalogs from _device_box), then layout leftovers
    # such as seal-in members that only appear on the elevation.
    for sheet in sheets:
        if sheet.outline_only or sheet.kind == "layout":
            continue
        for box in sheet.boxes:
            emit(box)
    for sheet in sheets:
        if sheet.kind != "layout":
            continue
        for box in sheet.boxes:
            emit(box)
    return extras



def _outline_callout_text(box: Box) -> str:
    maker = (box.outline_maker or "").strip()
    catalog = (box.outline_catalog or CATALOG_NOT_IDENTIFIED).strip() or CATALOG_NOT_IDENTIFIED
    plain = (box.outline_plain or OUTLINE_PLAIN.get(box.type_id, "suggested installable component")).strip()
    if catalog == CATALOG_NOT_IDENTIFIED:
        if maker:
            return f"{maker} / {CATALOG_NOT_IDENTIFIED} - {plain}"
        return f"{CATALOG_NOT_IDENTIFIED} - {plain}"
    if maker:
        return f"{maker} {catalog} - {plain}"
    return f"{catalog} - {plain}"


def _outline_markup(box: Box) -> str:
    if box.outline_x is None or box.outline_y is None:
        return ""
    x = float(box.outline_x)
    y = float(box.outline_y)
    w = OUTLINE_W
    h = OUTLINE_H
    kind = (box.type_id or box.role or "").lower()
    callout = _outline_callout_text(box)
    caption_lines = _wrap_two(callout, _chars_fit(x + 8, FONT_CALLOUT, mono=False, right=x + w - 8))
    parts = [
        f'<g class="component-outline" data-tag="{escape(box.tag)}" data-type="{escape(kind)}" '
        f'data-catalog="{escape(box.outline_catalog or CATALOG_NOT_IDENTIFIED)}">',
        f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
        'fill="#fbfbfb" stroke="#000000" stroke-width="1.2"/>',
        f'<text x="{_num(x + 8)}" y="{_num(y + 16)}" '
        'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="11" font-weight="700" fill="#000000">'
        f"OUTLINE / {escape(box.tag)}</text>",
        _outline_body(kind, x + 16, y + 28, w - 32, h - 56),
    ]
    for index, line in enumerate(caption_lines):
        parts.append(
            f'<text class="outline-callout" x="{_num(x + 8)}" y="{_num(y + h - 24 + index * 14)}" '
            f'font-family="Segoe UI, Liberation Sans, sans-serif" font-size="{FONT_CALLOUT}" fill="#222222">'
            f"{escape(line)}</text>"
        )
    parts.append("</g>")
    return "".join(parts)


def _outline_body(kind: str, x: float, y: float, w: float, h: float) -> str:
    """Simple SVG engineering view: enclosure, terminals, nameplate - not a logo."""
    ink = "#000000"
    cx = x + w / 2
    cy = y + h / 2
    parts = [f'<g class="outline-body" data-outline="{escape(kind)}">']
    if kind == "power_supply":
        parts.append(f'<rect x="{_num(x + 20)}" y="{_num(y + 8)}" width="{_num(w - 40)}" height="{_num(h - 24)}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(x + 34)}" y="{_num(y + 20)}" width="{_num(w - 68)}" height="22" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(y + 36)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="{ink}">NAMEPLATE</text>')
        for i, label in enumerate(("L", "N", "PE", "+", "-")):
            tx = x + 30 + i * ((w - 60) / 4.5)
            parts.append(f'<rect x="{_num(tx)}" y="{_num(y + h - 28)}" width="12" height="10" fill="none" stroke="{ink}" stroke-width="1.1"/>')
            parts.append(f'<text x="{_num(tx + 6)}" y="{_num(y + h - 30)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">{label}</text>')
        # DIN-rail hint
        parts.append(f'<line x1="{_num(x + 24)}" y1="{_num(cy + 18)}" x2="{_num(x + w - 24)}" y2="{_num(cy + 18)}" stroke="{ink}" stroke-width="1.2" stroke-dasharray="4 3"/>')
    elif kind == "plc":
        parts.append(f'<rect x="{_num(x + 10)}" y="{_num(y + 6)}" width="{_num(w - 20)}" height="{_num(h - 18)}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(x + 22)}" y="{_num(y + 18)}" width="{_num(w - 44)}" height="18" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(y + 31)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="{ink}">STATUS / KEYPAD</text>')
        for i in range(4):
            parts.append(f'<circle cx="{_num(x + 28 + i * 16)}" cy="{_num(y + 52)}" r="3.2" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<rect x="{_num(x + 18)}" y="{_num(y + h - 36)}" width="28" height="14" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<rect x="{_num(x + 52)}" y="{_num(y + h - 36)}" width="28" height="14" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<text x="{_num(x + 32)}" y="{_num(y + h - 40)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">ETH</text>')
        parts.append(f'<text x="{_num(x + 66)}" y="{_num(y + h - 40)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">ETH</text>')
        for i in range(5):
            parts.append(f'<line x1="{_num(x + 10)}" y1="{_num(y + 60 + i * 8)}" x2="{_num(x + 4)}" y2="{_num(y + 60 + i * 8)}" stroke="{ink}" stroke-width="1.1"/>')
            parts.append(f'<line x1="{_num(x + w - 10)}" y1="{_num(y + 60 + i * 8)}" x2="{_num(x + w - 4)}" y2="{_num(y + 60 + i * 8)}" stroke="{ink}" stroke-width="1.1"/>')
    elif kind == "io_module":
        parts.append(f'<rect x="{_num(x + 40)}" y="{_num(y + 6)}" width="{_num(w - 80)}" height="{_num(h - 16)}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(x + 48)}" y="{_num(y + 16)}" width="{_num(w - 96)}" height="14" fill="none" stroke="{ink}" stroke-width="1.0"/>')
        for i in range(8):
            yy = y + 40 + i * 8
            parts.append(f'<line x1="{_num(x + 40)}" y1="{_num(yy)}" x2="{_num(x + 28)}" y2="{_num(yy)}" stroke="{ink}" stroke-width="1.0"/>')
            parts.append(f'<line x1="{_num(x + w - 40)}" y1="{_num(yy)}" x2="{_num(x + w - 28)}" y2="{_num(yy)}" stroke="{ink}" stroke-width="1.0"/>')
    elif kind == "vfd":
        parts.append(f'<rect x="{_num(x + 24)}" y="{_num(y + 4)}" width="{_num(w - 48)}" height="{_num(h - 14)}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(x + 40)}" y="{_num(y + 16)}" width="{_num(w - 80)}" height="28" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(y + 34)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="{ink}">KEYPAD</text>')
        for i in range(5):
            parts.append(f'<line x1="{_num(x + w - 34)}" y1="{_num(y + 52 + i * 8)}" x2="{_num(x + w - 24)}" y2="{_num(y + 52 + i * 8)}" stroke="{ink}" stroke-width="1.0"/>')
        for i, lab in enumerate(("L1", "L2", "L3", "T1", "T2", "T3")):
            tx = x + 36 + i * 22
            parts.append(f'<rect x="{_num(tx)}" y="{_num(y + h - 28)}" width="14" height="10" fill="none" stroke="{ink}" stroke-width="1.0"/>')
            parts.append(f'<text x="{_num(tx + 7)}" y="{_num(y + h - 30)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="7" fill="{ink}">{lab}</text>')
    elif kind == "contactor":
        parts.append(f'<rect x="{_num(x + 36)}" y="{_num(y + 10)}" width="{_num(w - 72)}" height="{_num(h - 28)}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(x + 50)}" y="{_num(y + 22)}" width="{_num(w - 100)}" height="20" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(y + 36)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="{ink}">ARC BOX</text>')
        for i, lab in enumerate(("1", "3", "5", "A1")):
            tx = x + 48 + i * 28
            parts.append(f'<rect x="{_num(tx)}" y="{_num(y + 14)}" width="12" height="8" fill="none" stroke="{ink}" stroke-width="1.0"/>')
        for i, lab in enumerate(("2", "4", "6", "A2")):
            tx = x + 48 + i * 28
            parts.append(f'<rect x="{_num(tx)}" y="{_num(y + h - 30)}" width="12" height="8" fill="none" stroke="{ink}" stroke-width="1.0"/>')
        parts.append(f'<circle cx="{_num(x + 28)}" cy="{_num(cy)}" r="4" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<circle cx="{_num(x + w - 28)}" cy="{_num(cy)}" r="4" fill="none" stroke="{ink}" stroke-width="1.1"/>')
    elif kind == "motor":
        # Generic motor outline - no HP/frame invented.
        parts.append(f'<ellipse cx="{_num(cx - 10)}" cy="{_num(cy)}" rx="{_num(w * 0.28)}" ry="{_num(h * 0.32)}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(cx + 20)}" y="{_num(cy - 18)}" width="36" height="36" fill="none" stroke="{ink}" stroke-width="1.3"/>')
        parts.append(f'<text x="{_num(cx + 38)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">JB</text>')
        parts.append(f'<line x1="{_num(x + 18)}" y1="{_num(cy)}" x2="{_num(cx - 10 - w * 0.28)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="2.0"/>')
        parts.append(f'<circle cx="{_num(x + 18)}" cy="{_num(cy)}" r="5" fill="none" stroke="{ink}" stroke-width="1.3"/>')
        parts.append(f'<text x="{_num(cx - 10)}" y="{_num(y + h - 8)}" text-anchor="middle" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="{ink}">generic motor outline</text>')
    elif kind == "safety_relay":
        parts.append(f'<rect x="{_num(x + 50)}" y="{_num(y + 6)}" width="{_num(w - 100)}" height="{_num(h - 16)}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(x + 58)}" y="{_num(y + 16)}" width="{_num(w - 116)}" height="16" fill="none" stroke="{ink}" stroke-width="1.0"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(y + 28)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">RESET</text>')
        for i in range(6):
            yy = y + 42 + i * 10
            parts.append(f'<line x1="{_num(x + 50)}" y1="{_num(yy)}" x2="{_num(x + 38)}" y2="{_num(yy)}" stroke="{ink}" stroke-width="1.0"/>')
            parts.append(f'<line x1="{_num(x + w - 50)}" y1="{_num(yy)}" x2="{_num(x + w - 38)}" y2="{_num(yy)}" stroke="{ink}" stroke-width="1.0"/>')
    elif kind == "estop":
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy - 8)}" r="28" fill="none" stroke="{ink}" stroke-width="2.2"/>')
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy - 8)}" r="18" fill="none" stroke="{ink}" stroke-width="1.4"/>')
        parts.append(f'<rect x="{_num(cx - 22)}" y="{_num(cy + 24)}" width="44" height="14" fill="none" stroke="{ink}" stroke-width="1.2"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 35)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">PANEL</text>')
    elif kind == "pushbutton":
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy - 6)}" r="22" fill="none" stroke="{ink}" stroke-width="1.8"/>')
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy - 6)}" r="12" fill="none" stroke="{ink}" stroke-width="1.3"/>')
        parts.append(f'<rect x="{_num(cx - 30)}" y="{_num(cy + 24)}" width="60" height="16" fill="none" stroke="{ink}" stroke-width="1.1"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 36)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">LEGEND</text>')
    elif kind == "sensor":
        parts.append(f'<rect x="{_num(x + 30)}" y="{_num(cy - 14)}" width="{_num(w - 90)}" height="28" rx="10" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(x + w - 58)}" y="{_num(cy - 10)}" width="28" height="20" fill="none" stroke="{ink}" stroke-width="1.2"/>')
        parts.append(f'<text x="{_num(x + w - 44)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">M12</text>')
        parts.append(f'<circle cx="{_num(x + 30)}" cy="{_num(cy)}" r="8" fill="none" stroke="{ink}" stroke-width="1.3"/>')
    elif kind == "disconnect":
        parts.append(f'<rect x="{_num(x + 30)}" y="{_num(y + 12)}" width="{_num(w - 60)}" height="{_num(h - 30)}" fill="none" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{_num(cx - 20)}" y1="{_num(cy)}" x2="{_num(cx + 20)}" y2="{_num(cy - 18)}" stroke="{ink}" stroke-width="1.8"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(y + h - 18)}" text-anchor="middle" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="{ink}">no catalog stored</text>')
    elif kind == "ground":
        parts.append(f'<line x1="{_num(cx)}" y1="{_num(y + 16)}" x2="{_num(cx)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.8"/>')
        parts.append(f'<line x1="{_num(cx - 28)}" y1="{_num(cy)}" x2="{_num(cx + 28)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="2.0"/>')
        parts.append(f'<line x1="{_num(cx - 18)}" y1="{_num(cy + 10)}" x2="{_num(cx + 18)}" y2="{_num(cy + 10)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx - 8)}" y1="{_num(cy + 20)}" x2="{_num(cx + 8)}" y2="{_num(cy + 20)}" stroke="{ink}" stroke-width="1.4"/>')
    else:
        parts.append(f'<rect x="{_num(x + 24)}" y="{_num(y + 10)}" width="{_num(w - 48)}" height="{_num(h - 28)}" fill="none" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<rect x="{_num(x + 40)}" y="{_num(y + 24)}" width="{_num(w - 80)}" height="20" fill="none" stroke="{ink}" stroke-width="1.0"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(y + 38)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="{ink}">NAMEPLATE</text>')
    parts.append("</g>")
    return "".join(parts)


def _symbol_markup(box: Box, kind: str) -> str:
    """ANSI/IEC ladder glyphs centered on the rung. Control = NO/NC/coil; power = device."""
    compact = box.w <= SCHEM_W + 1 or box.role == "seal_in" or (kind or "").lower() == "seal_in"
    cx = box.x + box.w / 2.0 if compact else box.x + 26
    cy = box.y + box.h / 2.0 if compact else box.y + 48
    ink = "#000000"
    k = (kind or "").lower()
    tag_u = (box.tag or "").upper()
    parts = [f'<g class="symbol" data-symbol="{escape(k)}">']
    if k in {"disconnect"}:
        parts.append(f'<line x1="{_num(cx - 14)}" y1="{_num(cy)}" x2="{_num(cx - 4)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx + 4)}" y1="{_num(cy)}" x2="{_num(cx + 14)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx - 4)}" y1="{_num(cy)}" x2="{_num(cx + 10)}" y2="{_num(cy - 14)}" stroke="{ink}" stroke-width="1.8"/>')
        parts.append(f'<circle cx="{_num(cx - 4)}" cy="{_num(cy)}" r="2.0" fill="{ink}"/>')
        parts.append(f'<circle cx="{_num(cx + 4)}" cy="{_num(cy)}" r="2.0" fill="{ink}"/>')
    elif k in {"power_supply"}:
        parts.append(f'<rect x="{_num(cx - 16)}" y="{_num(cy - 14)}" width="32" height="28" fill="none" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{_num(cx - 6)}" y1="{_num(cy - 2)}" x2="{_num(cx + 6)}" y2="{_num(cy - 2)}" stroke="{ink}" stroke-width="1.4"/>')
        parts.append(f'<line x1="{_num(cx)}" y1="{_num(cy - 8)}" x2="{_num(cx)}" y2="{_num(cy + 4)}" stroke="{ink}" stroke-width="1.4"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 12)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">PS</text>')
    elif k in {"plc"}:
        # Ladder PLC block with rail ticks — not a layout card.
        parts.append(f'<line x1="{_num(cx - 22)}" y1="{_num(cy)}" x2="{_num(cx - 14)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx + 14)}" y1="{_num(cy)}" x2="{_num(cx + 22)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<rect x="{_num(cx - 14)}" y="{_num(cy - 12)}" width="28" height="24" fill="#ffffff" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx - 14)}" y1="{_num(cy - 4)}" x2="{_num(cx - 10)}" y2="{_num(cy - 4)}" stroke="{ink}" stroke-width="1.2"/>')
        parts.append(f'<line x1="{_num(cx - 14)}" y1="{_num(cy + 4)}" x2="{_num(cx - 10)}" y2="{_num(cy + 4)}" stroke="{ink}" stroke-width="1.2"/>')
        parts.append(f'<line x1="{_num(cx + 10)}" y1="{_num(cy - 4)}" x2="{_num(cx + 14)}" y2="{_num(cy - 4)}" stroke="{ink}" stroke-width="1.2"/>')
        parts.append(f'<line x1="{_num(cx + 10)}" y1="{_num(cy + 4)}" x2="{_num(cx + 14)}" y2="{_num(cy + 4)}" stroke="{ink}" stroke-width="1.2"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="9" font-weight="700" fill="{ink}">PLC</text>')
    elif k in {"io_module"}:
        # Discrete I/O module as terminal ladder block (DI vs DO from tag).
        parts.append(f'<line x1="{_num(cx - 20)}" y1="{_num(cy)}" x2="{_num(cx - 12)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{_num(cx + 12)}" y1="{_num(cy)}" x2="{_num(cx + 20)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<rect x="{_num(cx - 12)}" y="{_num(cy - 11)}" width="24" height="22" fill="#ffffff" stroke="{ink}" stroke-width="1.5"/>')
        for dy in (-6, 0, 6):
            parts.append(f'<line x1="{_num(cx - 8)}" y1="{_num(cy + dy)}" x2="{_num(cx + 8)}" y2="{_num(cy + dy)}" stroke="{ink}" stroke-width="1.1"/>')
        io_glyph = "DO" if tag_u.startswith("DO") else "DI"
        parts.append(
            f'<text x="{_num(cx)}" y="{_num(cy + 18)}" text-anchor="middle" '
            f'font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">{io_glyph}</text>'
        )
    elif k in {"vfd"}:
        parts.append(f'<rect x="{_num(cx - 18)}" y="{_num(cy - 14)}" width="36" height="28" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<polyline points="{_num(cx - 10)},{_num(cy + 6)} {_num(cx - 4)},{_num(cy - 8)} {_num(cx + 2)},{_num(cy + 6)} {_num(cx + 8)},{_num(cy - 8)}" fill="none" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 12)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">VFD</text>')
    elif k in {"motor"}:
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="14" fill="none" stroke="{ink}" stroke-width="1.7"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="12" font-weight="700" fill="{ink}">M</text>')
    elif k in {"contactor"}:
        # Power power-pole or control coil: circle coil glyph on the rung.
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="12" fill="none" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="9" fill="{ink}">CR</text>')
    elif k in {"estop"}:
        # NC contact + mushroom cue (safety open).
        parts.append(f'<line x1="{_num(cx - 16)}" y1="{_num(cy)}" x2="{_num(cx - 6)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx + 6)}" y1="{_num(cy)}" x2="{_num(cx + 16)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx - 6)}" y1="{_num(cy - 8)}" x2="{_num(cx + 6)}" y2="{_num(cy - 8)}" stroke="{ink}" stroke-width="1.8"/>')
        parts.append(f'<line x1="{_num(cx - 6)}" y1="{_num(cy - 8)}" x2="{_num(cx - 6)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx + 6)}" y1="{_num(cy - 8)}" x2="{_num(cx + 6)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy - 16)}" r="5" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    elif k in {"pushbutton"}:
        # NC from stored contact_config / function (box.contact_nc); tag is last resort only.
        nc = bool(box.contact_nc) or "STOP" in tag_u or "NC" in tag_u or "ESTOP" in tag_u
        parts.append(f'<line x1="{_num(cx - 16)}" y1="{_num(cy)}" x2="{_num(cx - 6)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx + 6)}" y1="{_num(cy)}" x2="{_num(cx + 16)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        if nc:
            parts.append(f'<line x1="{_num(cx - 6)}" y1="{_num(cy - 8)}" x2="{_num(cx + 6)}" y2="{_num(cy - 8)}" stroke="{ink}" stroke-width="1.8"/>')
            parts.append(f'<line x1="{_num(cx - 6)}" y1="{_num(cy - 8)}" x2="{_num(cx - 6)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
            parts.append(f'<line x1="{_num(cx + 6)}" y1="{_num(cy - 8)}" x2="{_num(cx + 6)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
            parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 16)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">NC</text>')
        else:
            parts.append(f'<line x1="{_num(cx - 5)}" y1="{_num(cy + 8)}" x2="{_num(cx + 5)}" y2="{_num(cy - 8)}" stroke="{ink}" stroke-width="1.8"/>')
            parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 16)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">NO</text>')
    elif k in {"safety_relay"}:
        # Safety relay as coil + guided contact cue on the rung.
        parts.append(f'<line x1="{_num(cx - 22)}" y1="{_num(cy)}" x2="{_num(cx - 12)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="11" fill="#ffffff" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">SR</text>')
        parts.append(f'<line x1="{_num(cx + 12)}" y1="{_num(cy)}" x2="{_num(cx + 22)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
    elif k in {"seal_in"}:
        # Series: NC STOP — NO START (seal branch) — coil.
        stop_t = box.members[0] if len(box.members) > 0 else "STOP"
        start_t = box.members[1] if len(box.members) > 1 else "START"
        coil_t = box.members[2] if len(box.members) > 2 else box.tag
        x0 = box.x + 18
        # NC STOP
        parts.append(f'<line x1="{_num(x0)}" y1="{_num(cy)}" x2="{_num(x0 + 10)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{_num(x0 + 10)}" y1="{_num(cy - 8)}" x2="{_num(x0 + 28)}" y2="{_num(cy - 8)}" stroke="{ink}" stroke-width="1.7"/>')
        parts.append(f'<line x1="{_num(x0 + 10)}" y1="{_num(cy - 8)}" x2="{_num(x0 + 10)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.4"/>')
        parts.append(f'<line x1="{_num(x0 + 28)}" y1="{_num(cy - 8)}" x2="{_num(x0 + 28)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.4"/>')
        parts.append(f'<line x1="{_num(x0 + 28)}" y1="{_num(cy)}" x2="{_num(x0 + 40)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<text x="{_num(x0 + 19)}" y="{_num(cy + 16)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="7" fill="{ink}">{escape(stop_t)}</text>')
        # NO START with seal-in parallel above
        sx = x0 + 40
        parts.append(f'<line x1="{_num(sx)}" y1="{_num(cy)}" x2="{_num(sx + 10)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{_num(sx + 12)}" y1="{_num(cy + 8)}" x2="{_num(sx + 26)}" y2="{_num(cy - 8)}" stroke="{ink}" stroke-width="1.7"/>')
        parts.append(f'<line x1="{_num(sx + 28)}" y1="{_num(cy)}" x2="{_num(sx + 48)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        # seal branch
        parts.append(f'<path d="M {_num(sx + 10)} {_num(cy)} L {_num(sx + 10)} {_num(cy - 16)} L {_num(sx + 38)} {_num(cy - 16)} L {_num(sx + 38)} {_num(cy)}" fill="none" stroke="{ink}" stroke-width="1.3"/>')
        parts.append(f'<line x1="{_num(sx + 16)}" y1="{_num(cy - 12)}" x2="{_num(sx + 32)}" y2="{_num(cy - 20)}" stroke="{ink}" stroke-width="1.4"/>')
        parts.append(f'<text x="{_num(sx + 24)}" y="{_num(cy + 16)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="7" fill="{ink}">{escape(start_t)}</text>')
        # Coil
        cx2 = sx + 64
        parts.append(f'<line x1="{_num(sx + 48)}" y1="{_num(cy)}" x2="{_num(cx2 - 12)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<circle cx="{_num(cx2)}" cy="{_num(cy)}" r="12" fill="#ffffff" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<text x="{_num(cx2)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">{escape(coil_t[:4])}</text>')
        parts.append(f'<line x1="{_num(cx2 + 12)}" y1="{_num(cy)}" x2="{_num(box.x + box.w - 8)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
    elif k in {"sensor"}:
        parts.append(f'<line x1="{_num(cx - 16)}" y1="{_num(cy)}" x2="{_num(cx - 4)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{_num(cx + 4)}" y1="{_num(cy)}" x2="{_num(cx + 16)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<polygon points="{_num(cx - 4)},{_num(cy)} {_num(cx)},{_num(cy - 10)} {_num(cx + 4)},{_num(cy)}" fill="none" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 14)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">PX</text>')
    elif k in {"ground"}:
        parts.append(f'<line x1="{_num(cx)}" y1="{_num(cy - 16)}" x2="{_num(cx)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx - 12)}" y1="{_num(cy)}" x2="{_num(cx + 12)}" y2="{_num(cy)}" stroke="{ink}" stroke-width="1.8"/>')
        parts.append(f'<line x1="{_num(cx - 8)}" y1="{_num(cy + 5)}" x2="{_num(cx + 8)}" y2="{_num(cy + 5)}" stroke="{ink}" stroke-width="1.6"/>')
        parts.append(f'<line x1="{_num(cx - 4)}" y1="{_num(cy + 10)}" x2="{_num(cx + 4)}" y2="{_num(cy + 10)}" stroke="{ink}" stroke-width="1.4"/>')
    elif k in {"light"}:
        parts.append(f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="10" fill="none" stroke="{ink}" stroke-width="1.5"/>')
        parts.append(f'<line x1="{_num(cx - 7)}" y1="{_num(cy - 7)}" x2="{_num(cx + 7)}" y2="{_num(cy + 7)}" stroke="{ink}" stroke-width="1.3"/>')
        parts.append(f'<line x1="{_num(cx + 7)}" y1="{_num(cy - 7)}" x2="{_num(cx - 7)}" y2="{_num(cy + 7)}" stroke="{ink}" stroke-width="1.3"/>')
    else:
        parts.append(f'<rect x="{_num(cx - 12)}" y="{_num(cy - 10)}" width="24" height="20" fill="none" stroke="{ink}" stroke-width="1.4"/>')
        parts.append(f'<text x="{_num(cx)}" y="{_num(cy + 4)}" text-anchor="middle" font-family="Consolas, Liberation Mono, monospace" font-size="8" fill="{ink}">DEV</text>')
    parts.append("</g>")
    return "".join(parts)


def _connector_markup(connector: Connector) -> str:
    text = connector.label if not connector.wire or connector.wire in connector.label else f"{connector.wire}  {connector.label}"
    direction = (connector.arrow_dir or "right").lower()
    if connector.kind == "off-page":
        # Prefer right-pointing so the label starts AFTER the tip, clear of the shaft.
        if direction != "right":
            direction = "right"
        base = connector.x + ARROW_SHAFT
        tip = base + ARROW_HEAD
        head = (
            f'<polygon points="{_num(base)},{_num(connector.y - 4)} '
            f'{_num(tip)},{_num(connector.y)} {_num(base)},{_num(connector.y + 4)}" fill="#000000"/>'
        )
        text_x = tip + ARROW_TIP_GAP
        tip_attr = f' data-tip-x="{_num(tip)}" data-arrow-dir="right"'
    else:
        head = (
            f'<circle cx="{_num(connector.x)}" cy="{_num(connector.y)}" r="6" fill="#ffffff" stroke="#000000" stroke-width="1.2"/>'
        )
        # On-page SEE label to the RIGHT of the stem/bubble.
        text_x = connector.x + 6 + LABEL_LINE_GAP
        tip_attr = f' data-tip-x="{_num(connector.x + 6)}" data-arrow-dir="right"'
    # Connector sheet/wire text is hover-only (title); keep arrow/bubble clear of trunks.
    return (
        f'<g class="connector" data-kind="{escape(connector.kind)}" data-wire="{escape(connector.wire)}" '
        f'data-label="{escape(text)}"{tip_attr}>'
        f"<title>{escape(text)}</title>{head}"
        f'<rect class="hit-target" x="{_num(min(connector.x, text_x) - 8)}" y="{_num(connector.y - 14)}" '
        f'width="{_num(abs(text_x - connector.x) + 48)}" height="28" '
        f'fill="#ffffff" fill-opacity="0.01" stroke="none"/>'
        "</g>"
    )


def _title_markup(sheet: Sheet, project: Project) -> str:
    note_lines: list[str] = []
    for note in sheet.notes:
        note_lines.extend(_wrap(note, 140))
    note_lines = note_lines[:3]
    supply = _interview_value(project, "supply_voltage")
    control = _interview_value(project, "control_voltage")
    if supply and control:
        voltage = f"{supply} / {control}"
    else:
        voltage = supply or control or "—"
    drawn = date.today().isoformat()
    y0 = TITLE_TOP
    x0 = 20.0
    x1 = PAGE_W - 20.0
    y1 = PAGE_H - 20.0
    mid = 280.0
    col2 = 980.0
    rows = [
        f'<g class="title-block" data-sheet="{sheet.number}" data-total="{sheet.total}">',
        f'<rect x="{_num(x0)}" y="{_num(y0)}" width="{_num(x1 - x0)}" height="{_num(y1 - y0)}" fill="#ffffff" stroke="#000000" stroke-width="1.4"/>',
        f'<line x1="{_num(mid)}" y1="{_num(y0)}" x2="{_num(mid)}" y2="{_num(y1)}" stroke="#000000" stroke-width="1.1"/>',
        f'<line x1="{_num(col2)}" y1="{_num(y0)}" x2="{_num(col2)}" y2="{_num(y1 - 28)}" stroke="#000000" stroke-width="1.1"/>',
        f'<line x1="{_num(x0)}" y1="{_num(y1 - 28)}" x2="{_num(x1)}" y2="{_num(y1 - 28)}" stroke="#000000" stroke-width="1.1"/>',
        f'<line x1="{_num(mid)}" y1="{_num(y0 + 36)}" x2="{_num(x1)}" y2="{_num(y0 + 36)}" stroke="#000000" stroke-width="0.9"/>',
        f'<line x1="{_num(mid)}" y1="{_num(y0 + 72)}" x2="{_num(x1)}" y2="{_num(y0 + 72)}" stroke="#000000" stroke-width="0.9"/>',
        f'<line x1="{_num(mid)}" y1="{_num(y0 + 108)}" x2="{_num(col2)}" y2="{_num(y0 + 108)}" stroke="#000000" stroke-width="0.9"/>',
        f'<text x="{_num(x0 + 12)}" y="{_num(y0 + 28)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="14" font-weight="700" fill="#000000">CABINET STUDIO</text>',
        f'<text x="{_num(x0 + 12)}" y="{_num(y0 + 48)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="11" fill="#000000">Industrial control drawings</text>',
        f'<text x="{_num(x0 + 12)}" y="{_num(y0 + 68)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="10" fill="#444444">Design aid - not a listing</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 16)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#444444">CABINET / PROJECT</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 30)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="13" font-weight="700" fill="#000000">{escape(project.name)}</text>',
        f'<text x="{_num(col2 + 10)}" y="{_num(y0 + 16)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#444444">SHEET TITLE</text>',
        f'<text x="{_num(col2 + 10)}" y="{_num(y0 + 30)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="13" font-weight="700" fill="#000000">{escape(sheet.title)}</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 52)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#444444">PANEL</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 66)}" font-family="Consolas, Liberation Mono, monospace" font-size="12" font-weight="700" fill="#000000">{escape(project.cabinet_label)}</text>',
        f'<text x="{_num(col2 + 10)}" y="{_num(y0 + 52)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#444444">SHEET</text>',
        f'<text x="{_num(col2 + 10)}" y="{_num(y0 + 66)}" font-family="Consolas, Liberation Mono, monospace" font-size="12" font-weight="700" fill="#000000">Sheet {sheet.number} of {sheet.total}</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 88)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#444444">VOLTAGE</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 102)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="12" fill="#000000">{escape(voltage)}</text>',
        f'<text x="{_num(col2 + 10)}" y="{_num(y0 + 88)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#444444">DATE</text>',
        f'<text x="{_num(col2 + 10)}" y="{_num(y0 + 102)}" font-family="Consolas, Liberation Mono, monospace" font-size="12" fill="#000000">{escape(drawn)}</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 124)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="9" fill="#444444">DRAWN BY</text>',
        f'<text x="{_num(mid + 10)}" y="{_num(y0 + 138)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="12" fill="#000000">Cabinet Studio</text>',
        f'<text class="disclaimer" x="{_num(x0 + 12)}" y="{_num(y1 - 10)}" font-family="Segoe UI, Liberation Sans, sans-serif" font-size="11" font-weight="700" fill="#8a1c1c">{escape(DISCLAIMER)}</text>',
    ]
    for index, line in enumerate(note_lines):
        rows.append(
            f'<text x="{_num(col2 + 10)}" y="{_num(y0 + 122 + index * 12)}" font-family="Segoe UI, Liberation Sans, sans-serif" '
            f'font-size="9" fill="#444444">{escape(line)}</text>'
        )
    rows.append("</g>")
    return "".join(rows)


def _border_markup() -> str:
    """ANSI-style double sheet border with corner ticks."""
    outer = 14
    inner = 20
    ow, oh = PAGE_W - 2 * outer, PAGE_H - 2 * outer
    iw, ih = PAGE_W - 2 * inner, PAGE_H - 2 * inner
    parts = [
        f'<rect x="{outer}" y="{outer}" width="{ow}" height="{oh}" fill="none" stroke="#000000" stroke-width="2.2"/>',
        f'<rect x="{inner}" y="{inner}" width="{iw}" height="{ih}" fill="none" stroke="#000000" stroke-width="0.9"/>',
    ]
    tick = 10
    for x, y, dx, dy in (
        (inner, inner, tick, 0),
        (inner, inner, 0, tick),
        (PAGE_W - inner, inner, -tick, 0),
        (PAGE_W - inner, inner, 0, tick),
        (inner, PAGE_H - inner, tick, 0),
        (inner, PAGE_H - inner, 0, -tick),
        (PAGE_W - inner, PAGE_H - inner, -tick, 0),
        (PAGE_W - inner, PAGE_H - inner, 0, -tick),
    ):
        parts.append(
            f'<line x1="{x}" y1="{y}" x2="{x + dx}" y2="{y + dy}" stroke="#000000" stroke-width="1.2"/>'
        )
    return "".join(parts)


def _callout(item: PlacedItem) -> str:
    description = " ".join(item.fields.get("description", "").split())
    if description:
        return _sentence(description)
    return FALLBACK_CALLOUT.get(item.type_id, "Device stored on this cabinet.")


def _sentence(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return cleaned
    if cleaned[-1] in ".!?":
        return cleaned
    return cleaned + "."



def _voltage_has_nominal(raw: str, volts: int) -> bool:
    """True when a numeric voltage token equals volts exactly (240 != 24)."""
    for match in re.finditer(r"\d+", raw or ""):
        try:
            if int(match.group(0)) == volts:
                return True
        except ValueError:
            continue
    return False


def _control_rail_names(control: str) -> tuple[str, str]:
    """Left/right control rail labels from tokenized control voltage.

    Do not treat "240 VDC" as +24V via a substring check on "24".
    """
    text = (control or "").strip() or "24 VDC"
    upper = text.upper()
    if _voltage_has_nominal(text, 24) and ("VDC" in upper or "DC" in upper or "VAC" not in upper):
        return "+24V", "0V"
    if _voltage_has_nominal(text, 24):
        return "+24V", "0V"
    if "VAC" in upper or _voltage_has_nominal(text, 120) or _voltage_has_nominal(text, 240):
        return "CTL+", "N"
    return "CTL+", "CTL-"


def _rung_is_stub(box: Box, project: Project | None) -> bool:
    """Signal / inter-device nets get a stub + connector, not rail-to-rail into 0V."""
    if box.role in {"disconnect", "ground", "seal_in", "plc"}:
        return False
    # Power consumers, module power, and coils stay on the rails.
    if box.type_id in {"motor", "vfd", "power_supply", "io_module", "contactor", "light", "solenoid"}:
        return False
    power = [w for w in box.wires if w not in GROUND_TOKENS]
    if not power:
        return False
    land_u = (box.landing or "").upper()
    rail_hints = (
        "L+",
        "L-",
        "+24",
        "24 V",
        "24V",
        "0V",
        "MODULE POWER",
        "FROM PSU",
        "COIL",
        " A1",
        "A1 ",
        "A1/",
        "CONTROL RAIL",
        "CTL+",
        "CTL-",
        "RETURN",
    )
    # Explicit rail / power wording => rail→device→return (even with a peer tag).
    if any(h in land_u for h in rail_hints):
        return False
    if "SIGNAL" in land_u:
        return True
    # Peer device named in the landing without rail-power wording => inter-device.
    if project is not None:
        known = _cabinet_tags(project)
        has_peer = any(
            key != (box.tag or "").upper() and key in land_u for key in known
        )
        if has_peer:
            return True
    # Field / safety devices default to stub unless they clearly land on rails.
    if box.type_id in {"sensor", "transmitter", "estop", "safety_relay"}:
        return True
    return False


def _pushbutton_kind(item: PlacedItem) -> str:
    """Classify pushbutton as stop/start from function/role/contact, then tag."""
    func = (item.fields.get("function") or item.fields.get("role") or "").strip().upper()
    if func:
        if any(tok in func for tok in ("STOP", "E-STOP", "ESTOP", "E STOP")):
            return "stop"
        if any(tok in func for tok in ("START", "RUN", "JOG")):
            return "start"
    cc = (item.fields.get("contact_config") or "").strip().upper()
    desc = (item.fields.get("description") or "").strip().upper()
    blob = f"{cc} {desc}".strip()
    if blob:
        if any(tok in blob for tok in ("STOP", "E-STOP", "ESTOP")):
            return "stop"
        if "START" in blob or "RUN" in blob:
            return "start"
    tag = device_tag(item).upper()
    if "STOP" in tag or "ESTOP" in tag:
        return "stop"
    if "START" in tag:
        return "start"
    return ""


def _stored_contact_is_nc(item: PlacedItem) -> bool:
    """NC from stored contact_config / function — not only STOP/NC/ESTOP in the tag."""
    cc = (item.fields.get("contact_config") or "").upper()
    if re.search(r"\bNC\b", cc) or "2NC" in cc or "1NC" in cc or "N.C" in cc:
        return True
    if re.search(r"\bNO\b", cc) and "NC" not in cc:
        return False
    func = (item.fields.get("function") or item.fields.get("role") or "").upper()
    if any(tok in func for tok in ("STOP", "E-STOP", "ESTOP")):
        return True
    if func in {"NC", "NORMALLY CLOSED", "NORMALLY-CLOSED"}:
        return True
    tag = device_tag(item).upper()
    if "STOP" in tag or "ESTOP" in tag or re.search(r"\bNC\b", tag):
        return True
    return False


def _outline_plain_for(item: PlacedItem, library: Library) -> str:
    """Plain English outline role from stored description / kind / library — not sample hardcodes."""
    desc = " ".join((item.fields.get("description") or "").split())
    if desc:
        return desc if len(desc) <= 72 else desc[:69] + "..."
    kind = (item.fields.get("sensor_kind") or "").strip()
    if kind:
        return f"{kind} sensor".lower() if "sensor" not in kind.lower() else kind.lower()
    if item.library_id:
        row = library.catalog_by_id.get(item.library_id)
        if row is not None:
            summary = " ".join((row.summary or "").split())
            if summary:
                return summary if len(summary) <= 72 else summary[:69] + "..."
            name = " ".join((row.name or "").split())
            if name:
                return name.lower()
    equipment = library.types.get(item.type_id)
    if equipment is not None and (equipment.label or "").strip():
        return equipment.label.strip().lower()
    return OUTLINE_PLAIN.get(item.type_id, "suggested installable component")


def _sheet_pe_bar_y(sheet: Sheet) -> float | None:
    """Y of the dedicated PE bar on a power sheet, if drawn."""
    horiz = [
        seg
        for seg in sheet.segments
        if (seg.wire or "").upper() in GROUND_TOKENS and abs(seg.y1 - seg.y2) < 0.6
    ]
    if not horiz:
        return None
    return horiz[0].y1


def _sheet_pe_bar_x0(sheet: Sheet) -> float:
    horiz = [
        seg
        for seg in sheet.segments
        if (seg.wire or "").upper() in GROUND_TOKENS and abs(seg.y1 - seg.y2) < 0.6
    ]
    if not horiz:
        return RAIL_X
    return min(min(seg.x1, seg.x2) for seg in horiz)


def _sheet_pe_bar_x1(sheet: Sheet) -> float:
    horiz = [
        seg
        for seg in sheet.segments
        if (seg.wire or "").upper() in GROUND_TOKENS and abs(seg.y1 - seg.y2) < 0.6
    ]
    if not horiz:
        return float(RIGHT_BUS_X)
    return max(max(seg.x1, seg.x2) for seg in horiz)


def _power_return_name(project: Project) -> str:
    """Right power rail is RETURN (N or L2/L3), never PE."""
    supply = (_interview_value(project, "supply_voltage") or "").upper()
    # Tokenize nominals so "2400" / embedded digits are not false matches.
    if (
        _voltage_has_nominal(supply, 480)
        or "L3" in supply
        or "3PH" in supply
        or "3-PH" in supply
    ):
        return "L2/L3"
    if (
        _voltage_has_nominal(supply, 120)
        or _voltage_has_nominal(supply, 240)
        or "SINGLE" in supply
    ):
        return "N"
    if "VAC" in supply or "VDC" in supply:
        return "L2/L3" if "3" in supply else "N"
    return "RETURN"


def _branch_protection_recorded(project: Project) -> bool:
    return (project.interview.get("branch_protection") or "").strip().lower() == "yes"


def _disconnect_load_wires(project: Project) -> list[str]:
    """Wire numbers on the disconnect load side from cabinet landings / wire_numbers.

    Prefer explicit W# named with DISC/disconnect. Otherwise accept other conductor
    tokens (BUS#, L1/L2/L3, T#). If the landing names the disconnect but omits
    conductors, use that device's stored wire_numbers (minus PE). Never treat prose
    tokens (SUPPLY, DISCONNECT, tag:) as conductors.
    """
    found: list[str] = []

    def _accept(token: str) -> bool:
        t = (token or "").strip().upper().rstrip(":")
        if not t or t in GROUND_TOKENS or t in GLUE_TOKENS:
            return False
        if t.startswith("W") and len(t) > 1 and t[1:].isdigit():
            return True
        if t in {"L1", "L2", "L3", "N"}:
            return True
        if re.fullmatch(r"BUS\d+", t) or re.fullmatch(r"T\d+", t):
            return True
        return False

    for item in project.items:
        land = item.fields.get("terminal_landings") or ""
        land_u = land.upper()
        if "DISC" not in land_u and "DISCONNECT" not in land_u:
            continue
        landing_wires: list[str] = []
        for m in re.finditer(r"\bW\d+\b", land, flags=re.IGNORECASE):
            tok = m.group(0).upper()
            if tok not in landing_wires:
                landing_wires.append(tok)
        # When no W# is named, keep other conductor tokens from the landing (e.g. BUS1).
        if not landing_wires:
            for m in re.finditer(r"\b(?:BUS\d+|L[123]|T\d+|N)\b", land, flags=re.IGNORECASE):
                tok = m.group(0).upper()
                if tok not in landing_wires:
                    landing_wires.append(tok)
        if not landing_wires:
            for token in wire_tokens(item.fields.get("wire_numbers", "")):
                if _accept(token) and token.upper() not in landing_wires:
                    landing_wires.append(token.upper())
        for token in landing_wires:
            if token not in found:
                found.append(token)
    return found



def _contactor_coil_is_control(item: PlacedItem) -> bool:
    """24 VDC / coil landings belong on the control ladder, not 480 V LINE/PE."""
    coil = (item.fields.get("coil_voltage") or "").upper()
    land = (item.fields.get("terminal_landings") or "").upper()
    # Tokenize so "240 VAC" is not treated as 24 V control via substring "24".
    if _voltage_has_nominal(coil, 24) or "VDC" in coil:
        return True
    if "A1" in land or "COIL" in land:
        return True
    if any(_voltage_has_nominal(coil, v) for v in (120, 208, 240, 480)) or "VAC" in coil:
        return False
    return False


def _kind_for(type_id: str, item: PlacedItem | None = None) -> str:
    if type_id == "contactor" and item is not None and _contactor_coil_is_control(item):
        return "control"
    if type_id in POWER_TYPES:
        return "power"
    return "control"


def _rank(type_id: str, kind: str) -> tuple[int, str]:
    table = POWER_RANK if kind == "power" else CONTROL_RANK
    return table.get(type_id, 50), type_id


def _disconnect_recorded(project: Project) -> bool:
    return (project.interview.get("disconnect") or "").strip().lower() == "yes"


def _ground_info(project: Project) -> tuple[bool, str, list[str]]:
    note = " ".join((project.interview.get("grounding") or "").split())
    tokens: list[str] = []
    landing = False
    for item in project.items:
        for token in wire_tokens(item.fields.get("wire_numbers", "")):
            if token in GROUND_TOKENS and token not in tokens:
                tokens.append(token)
        text = item.fields.get("terminal_landings", "").lower()
        if "ground" in text or re.search(r"\bpe\b", text):
            landing = True
    return bool(note or tokens or landing), note, tokens


def _interview_value(project: Project, key: str) -> str:
    value = (project.interview.get(key) or "").strip()
    if value.lower() in {"", "other", "not decided", "unspecified"}:
        return ""
    return value


def _usable_address(address: str) -> bool:
    return address.strip().lower() not in {"", "n/a", "na", "none"}


def _spare_tag(taken: set[str], wanted: str) -> str:
    if wanted.upper() not in taken:
        taken.add(wanted.upper())
        return wanted
    number = 2
    while f"{wanted}{number}".upper() in taken:
        number += 1
    tag = f"{wanted}{number}"
    taken.add(tag.upper())
    return tag


def _chunks(items: list[Box], size: int) -> list[list[Box]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _intervals_cross(first: tuple[int, int], second: tuple[int, int]) -> bool:
    a0, a1 = first
    b0, b1 = second
    return (a0 < b0 < a1 < b1) or (b0 < a0 < b1 < a1)


def _intervals_overlap(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return first[0] < second[1] and second[0] < first[1]



def _chars_fit(start_x: float, font_size: float, *, mono: bool = False, right: float | None = None) -> int:
    """Approximate characters that fit from start_x to the right edge (or page)."""
    edge = PAGE_RIGHT if right is None else right
    span = float(edge) - float(start_x)
    em = float(font_size) * (0.62 if mono else 0.55)
    # Explicit right edge (ladder callout vs trunk): honour the real span, no 12-char floor.
    if right is not None:
        avail = max(8.0, span)
        return max(4, int(avail / em))
    avail = max(48.0, span)
    return max(12, int(avail / em))


def _wrap_two(text: str, width: int) -> list[str]:
    """Wrap to at most TWO lines; clip the second line rather than shrinking type."""
    lines = _wrap(text, max(8, width))
    if not lines:
        return []
    if len(lines) == 1:
        return lines
    if len(lines) == 2:
        return lines
    first = lines[0]
    rest = " ".join(lines[1:])
    return [first, _clip(rest, max(8, width))]


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _wrap(text: str, width: int) -> list[str]:
    words = " ".join(text.split()).split(" ")
    if not words or words == [""]:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if len(trial) > width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in value)
    return cleaned or "box"


def _num(value: float) -> str:
    return f"{value:.1f}"


def _orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _collinear_overlap(first: Segment, second: Segment, eps: float = 0.8) -> bool:
    if abs(first.y1 - first.y2) <= eps and abs(second.y1 - second.y2) <= eps and abs(first.y1 - second.y1) <= eps:
        a0, a1 = sorted((first.x1, first.x2))
        b0, b1 = sorted((second.x1, second.x2))
        return min(a1, b1) - max(a0, b0) > eps
    if abs(first.x1 - first.x2) <= eps and abs(second.x1 - second.x2) <= eps and abs(first.x1 - second.x1) <= eps:
        a0, a1 = sorted((first.y1, first.y2))
        b0, b1 = sorted((second.y1, second.y2))
        return min(a1, b1) - max(a0, b0) > eps
    return False
