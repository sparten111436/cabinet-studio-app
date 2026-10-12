"""Backplate power zones (v0.3.25): arrange devices top-to-bottom by power class.

High power (disconnect / breakers / fuses) at the top, mid power (contactors, power
supplies, transformers) in the middle, low-voltage control (PLC, I/O, relays,
terminals) below, drives at the bottom with the largest VFDs at the very bottom.
Rows leave room for a 40 mm wire duct plus 12 mm clearance on each side, and the
sides keep a vertical duct channel - typical UL 508A shop practice for spacing
and segregation. Design aid only; follow the device makers' clearance data.
"""

from __future__ import annotations

from cabinet_studio.models.project import DEFAULT_BACKPLATE_WIDTH_IN, DEFAULT_CABINET_WIDTH

TILE_PX_PER_IN = DEFAULT_CABINET_WIDTH / DEFAULT_BACKPLATE_WIDTH_IN
MM = 1 / 25.4
DUCT_IN = 40 * MM
ROW_GAP_IN = (12 + 40 + 12 + 6) * MM
SIDE_IN = (10 + 40 + 12 + 6) * MM
ITEM_GAP_IN = 0.5
VFD_GAP_IN = 2.0

ZONES = ("high", "mid", "low", "vfd")
ZONE_TITLES = {"high": "High power", "mid": "Mid power", "low": "Low-voltage control", "vfd": "Motor drives (VFD)"}
FIELD_TYPES = {"motor", "sensor", "solenoid", "valve", "transmitter", "light_curtain"}
SHELL_TYPES = {"enclosure", "backplate"}
DUCT_TYPES = {"wire_duct", "wireway", "duct", "wiring_duct"}
_HIGH_TYPES = {"disconnect", "breaker", "circuit_breaker", "fuse", "fuse_holder", "fuse_block", "main_breaker",
               "motor_protector"}
_MID_TYPES = {"contactor", "power_supply", "transformer", "overload", "motor_starter", "starter"}
_HIGH_TAGS = ("DS", "DISC", "CB", "MCB", "FU", "FB", "QF")
_MID_TAGS = ("PS", "TR", "XF", "OL", "MS")


def zone_of(type_id: str, tag: str = "", mounting: str = "") -> str:
    """'high' | 'mid' | 'low' | 'vfd' | 'field' | 'shell' | 'duct'."""
    tid = (type_id or "").lower().strip()
    up = (tag or "").upper().strip()
    if tid in SHELL_TYPES:
        return "shell"
    if tid in DUCT_TYPES:
        return "duct"
    if tid in FIELD_TYPES or "field" in (mounting or "").lower():
        return "field"
    if tid == "vfd":
        return "vfd"
    if tid in _HIGH_TYPES or up.startswith(_HIGH_TAGS):
        return "high"
    if tid in _MID_TYPES or up.startswith(_MID_TAGS):
        return "mid"
    return "low"


def tile_inches(tile_w: float, tile_h: float) -> tuple[float, float]:
    return tile_w / TILE_PX_PER_IN, tile_h / TILE_PX_PER_IN


MIN_OUTLINE_IN = 0.5


def item_inches(library, item) -> tuple[float, float]:
    """Footprint in inches: the part's maker outline (outline_w_mm / outline_h_mm) when known,
    else the notional library tile."""
    from cabinet_studio.services.placement import tile_size

    fields = item.fields
    cat = _catalog_defaults(library, item)
    try:
        w_mm = float(fields.get("outline_w_mm") or cat.get("outline_w_mm", ""))
        h_mm = float(fields.get("outline_h_mm") or cat.get("outline_h_mm", ""))
        if w_mm > 0 and h_mm > 0:
            if str(fields.get("outline_w_mm") or "") in {"", str(cat.get("outline_w_mm", ""))}:
                w_mm = _scaled_width(item.type_id, w_mm, fields, cat)
            return max(w_mm * MM, MIN_OUTLINE_IN), max(h_mm * MM, MIN_OUTLINE_IN)
    except (TypeError, ValueError):
        pass
    return tile_inches(*tile_size(library, item.type_id))


POLED_TYPES = {"breaker", "circuit_breaker", "main_breaker", "fuse_holder", "fuse_block", "fuse", "disconnect"}
TB_END_MM = 19.0


def _catalog_defaults(library, item) -> dict[str, str]:
    cat = (getattr(library, "catalog_by_id", None) or {}).get(getattr(item, "library_id", None) or "")
    return cat.default_map() if cat is not None else {}


def _count(raw: object) -> int:
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return 0


def _scaled_width(type_id: str, w_mm: float, fields: dict, cat: dict) -> float:
    """Catalog width re-scaled when the placed item changed its pole or terminal count."""
    tid = (type_id or "").lower()
    if tid in POLED_TYPES:
        have, base = _count(fields.get("poles")), _count(cat.get("poles"))
        if have > 0 and base > 0 and have != base:
            return w_mm / base * have
    if tid == "terminal_block":
        have, base = _count(fields.get("terminal_count")), _count(cat.get("terminal_count"))
        if have > 0 and base > 0 and have != base and w_mm > TB_END_MM:
            return (w_mm - TB_END_MM) / base * have + TB_END_MM
    return w_mm


def _rows(items: list[tuple[str, float, float]], width: float, gap: float) -> list[list[tuple[str, float, float]]] | None:
    rows: list[list[tuple[str, float, float]]] = []
    row: list[tuple[str, float, float]] = []
    used = 0.0
    for key, w, h in items:
        if w > width:
            return None
        if row and used + gap + w > width:
            rows.append(row)
            row, used = [], 0.0
        used += (gap if row else 0.0) + w
        row.append((key, w, h))
    if row:
        rows.append(row)
    return rows


LEVELS = (
    (("high",), ("mid",), ("low",)),  # every zone on its own rows
    (("high", "mid"), ("low",)),      # power zones share rows, control below
    (("high", "mid", "low"),),        # one flow, still in zone order left to right
)


def arrange(devices: list[tuple[str, str, float, float]], plate_w: float, plate_h: float) -> dict[str, tuple[float, float, float, float]] | None:
    """devices: (key, zone, w_in, h_in). Returns key -> (x, y, w, h) in plate inches, or None if
    it can't fit. Tries strict zone rows first, then lets neighbouring zones share a row."""
    for groups in LEVELS:
        out = _arrange(devices, plate_w, plate_h, groups)
        if out is not None:
            return out
    return None


def _arrange(devices, plate_w: float, plate_h: float, groups) -> dict[str, tuple[float, float, float, float]] | None:
    width = plate_w - 2 * SIDE_IN
    out: dict[str, tuple[float, float, float, float]] = {}
    y = ROW_GAP_IN
    for group in groups:
        rows = _rows([(k, w, h) for zone in group for k, z, w, h in devices if z == zone], width, ITEM_GAP_IN)
        if rows is None:
            return None
        for row in rows:
            x = SIDE_IN
            for key, w, h in row:
                out[key] = (x, y, w, h)
                x += w + ITEM_GAP_IN
            y += max(h for _k, _w, h in row) + ROW_GAP_IN
    drives = sorted(((k, w, h) for k, z, w, h in devices if z == "vfd"), key=lambda d: d[1] * d[2])
    rows = _rows(drives, width, VFD_GAP_IN)
    if rows is None:
        return None
    block = sum(max(h for _k, _w, h in r) for r in rows) + ROW_GAP_IN * max(len(rows) - 1, 0)
    top = plate_h - ROW_GAP_IN - block
    if (rows and top < y) or (not rows and y > plate_h):
        return None
    for row in rows:
        x = SIDE_IN
        row_h = max(h for _k, _w, h in row)
        for key, w, h in row:
            out[key] = (x, top + row_h - h, w, h)
            x += w + VFD_GAP_IN
        top += row_h + ROW_GAP_IN
    return out


PIN_GRID_IN = 0.5
_PIN_PAD_IN = 0.25


def _clash(r: tuple[float, float, float, float], others: list[tuple[float, float, float, float]]) -> bool:
    x, y, w, h = r
    p = _PIN_PAD_IN
    return any(not (x + w + p <= ox or ox + ow + p <= x or y + h + p <= oy or oy + oh + p <= y)
               for ox, oy, ow, oh in others)


def _first_free(w: float, h: float, taken: list, plate_w: float, plate_h: float):
    y = PIN_GRID_IN
    while y + h <= plate_h - PIN_GRID_IN:
        x = PIN_GRID_IN
        while x + w <= plate_w - PIN_GRID_IN:
            if not _clash((x, y, w, h), taken):
                return (x, y, w, h)
            x += PIN_GRID_IN
        y += PIN_GRID_IN
    return None


def place_with_pins(devices: list[tuple[str, str, float, float]], pins: dict[str, tuple[float, float]],
                    plate_w: float, plate_h: float) -> dict[str, tuple[float, float, float, float]] | None:
    """Hand-placed (pinned) devices keep their spot, clamped onto the plate; the rest take their
    zone spot, or the first free grid spot when that collides with a pinned device."""
    out: dict[str, tuple[float, float, float, float]] = {}
    for key, _zone, w, h in devices:
        if key in pins:
            x, y = pins[key]
            out[key] = (min(max(x, 0.0), max(plate_w - w, 0.0)), min(max(y, 0.0), max(plate_h - h, 0.0)), w, h)
    free = [d for d in devices if d[0] not in out]
    auto = arrange(free, plate_w, plate_h) or {}
    taken = list(out.values())
    for key, _zone, w, h in free:
        r = auto.get(key)
        if r is None or _clash(r, taken):
            r = _first_free(w, h, taken, plate_w, plate_h)
        if r is None:
            return None
        out[key] = r
        taken.append(r)
    return out


def suggest_enclosure(devices: list[tuple[str, str, float, float]], maker: str = "Hoffman") -> tuple[str, bool]:
    """Smallest enclosure choice (default Hoffman) whose backplate fits every device: (label, fits)."""
    from cabinet_studio.services.enclosure_select import _ENCLOSURE_CHOICES

    choices = sorted(((label, v) for label, v in _ENCLOSURE_CHOICES.items() if v[0] == maker),
                     key=lambda lv: lv[1][6] * lv[1][7])
    for label, v in choices:
        if arrange(devices, v[6], v[7]) is not None:
            return label, True
    return (choices[-1][0], False) if choices else ("", False)
