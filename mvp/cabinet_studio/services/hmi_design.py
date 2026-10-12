"""HMI screens for one cabinet: the model, the creator interview, and checks.

The design is stored as JSON text in ``project.interview["hmi_design"]`` so it
round-trips through the existing project save/load without a format change.
Objects sit on a grid (``grid_size``) whose shape follows the chosen panel's
pixel shape from the HMI library. Tags come from the cabinet devices and the
ladder program. HMI-owned memory bits start with ``HMI_`` and must be added to
the PLC program. An E-stop object only SHOWS status; the HMI never stops the
machine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cabinet_studio.services.hmi_symbols import ANIMATIONS, GRAPHICS, NUMERIC_ANIMS
from cabinet_studio.services.hmi_library import (
    hmi_by_id,
    hmi_choices,
    hmi_id_from_label,
    hmi_label,
    hmi_sizes,
    normalize_maker,
    project_maker_preference,
    project_plc_families,
    recommend_hmi,
)

STORE_KEY = "hmi_design"
GRID_COLS = 24
HMI_TAG_PREFIX = "HMI_"
SAFETY_NOTE = (
    "E-stop and safety functions must be hardwired or use rated safety relays "
    "(NFPA 79 / ISO 13849). The HMI is never the safety function."
)

# kind -> name, access (W = HMI writes the tag, R = reads, "" = no tag), size (cols, rows), color, help
OBJECT_KINDS: dict[str, dict] = {
    "momentary": {"name": "Push button (momentary)", "access": "W", "size": (4, 2), "color": "Green",
                  "help": "On only while a finger is on it, like a doorbell. Use for Start, Stop request, Reset, Jog."},
    "toggle": {"name": "On/Off button (toggle)", "access": "W", "size": (4, 2), "color": "Blue",
               "help": "Press once for on, press again for off. Use for modes like Manual / Auto."},
    "lamp": {"name": "Indicator lamp", "access": "R", "size": (3, 2), "color": "Green",
             "help": "A light on the screen that shows if a PLC bit is on, e.g. Motor running or Fault."},
    "numeric_display": {"name": "Number display", "access": "R", "size": (4, 2), "color": "White",
                        "help": "Shows a number from the PLC, e.g. motor speed or a part count."},
    "numeric_entry": {"name": "Number entry", "access": "W", "size": (4, 2), "color": "White",
                      "help": "Lets the operator type a number into the PLC, e.g. a speed setpoint."},
    "text": {"name": "Text label", "access": "", "size": (6, 1), "color": "White",
             "help": "Plain words on the screen, like a title. Not tied to the PLC."},
    "alarm_banner": {"name": "Alarm banner", "access": "R", "size": (GRID_COLS, 1), "color": "Red",
                     "help": "A strip across the screen that shows the newest alarm message."},
    "nav": {"name": "Go-to-screen button", "access": "", "size": (4, 2), "color": "Gray",
            "help": "Jumps to another screen, e.g. from Main to Alarms."},
    "estop_status": {"name": "E-stop status (display only)", "access": "R", "size": (4, 2), "color": "Red",
                     "help": "Shows whether the E-stop is pressed. Display only - the real E-stop is hardwired. "
                             "The HMI can never stop or reset the machine safely."},
    "trend": {"name": "Trend chart", "access": "R", "size": (8, 4), "color": "Blue",
              "help": "Draws a line of a number over time, e.g. drive speed for the last few minutes."},
}
for _gid, _g in GRAPHICS.items():
    OBJECT_KINDS[_gid] = {"name": _g["name"], "access": "R", "size": _g["size"], "color": "Gray", "help": _g["help"],
                          "graphic": True}
TAGGED_KINDS = {"momentary", "toggle", "lamp", "numeric_display", "numeric_entry", "estop_status", "trend"}
COLORS = {"Green": "#2e9d43", "Red": "#d23a2a", "Amber": "#e0a100", "Blue": "#2f6bff",
          "Gray": "#7a7f8c", "White": "#f2f2f2"}
# Screen look. ISA-101 "high performance": gray screen, color only for abnormal states.
THEMES: dict[str, dict] = {
    "ISA-101 gray (high performance)": {"screen": "#d4d4d4", "fill": "#e6e6e6", "outline": "#6b6b6b",
                                        "ink": "#000000", "keep": {"Red", "Amber"}},
    "Classic bright": {"screen": "#ffffff", "fill": "", "outline": "", "ink": "", "keep": set(COLORS)},
    "Dark": {"screen": "#1f2126", "fill": "#2e3038", "outline": "#8a8f9c", "ink": "#ffffff",
             "keep": {"Red", "Amber", "Green", "Blue"}},
}
DEFAULT_THEME = "ISA-101 gray (high performance)"


def theme_colors(theme: str, color: str) -> tuple[str, str, str]:
    """(fill, outline, text) for one object color under a theme."""
    t = THEMES.get(theme, THEMES[DEFAULT_THEME])
    hexcol = COLORS.get(color, COLORS["Gray"])
    if not t["fill"]:
        light = color in {"White", "Amber"}
        return hexcol, "#000000", "#000000" if light else "#ffffff"
    if color in t["keep"]:
        return hexcol, "#000000", "#000000" if color == "Amber" else "#ffffff"
    return t["fill"], t["outline"], t["ink"]
SCREEN_SETS = {
    "Main only": ["Main"],
    "Main + Manual": ["Main", "Manual"],
    "Main + Manual + Alarms": ["Main", "Manual", "Alarms"],
    "Main + Manual + Alarms + Settings": ["Main", "Manual", "Alarms", "Settings"],
    "Main + Manual + Alarms + Trends + Settings": ["Main", "Manual", "Alarms", "Trends", "Settings"],
}
START_HARDWIRED = "Hardwired buttons only (HMI shows status)"
START_ON_HMI = "On the HMI too"
CONNECT_PLC = "Straight to the PLC"
CONNECT_SWITCH = "Through the Ethernet switch"
_SAFETY_WORDS = ("estop", "e-stop", "e_stop", "emergency", "safety", "light curtain", "guard")


@dataclass
class HmiObject:
    id: str
    kind: str
    x: int
    y: int
    w: int
    h: int
    label: str = ""
    tag: str = ""
    color: str = ""
    target: str = ""
    group: str = ""
    anim: str = ""

    @property
    def access(self) -> str:
        return OBJECT_KINDS.get(self.kind, {}).get("access", "")

    @property
    def tags(self) -> list[str]:
        """Bound tags; a stack light picture may list green,amber,red tags separated by commas."""
        return [t.strip() for t in self.tag.split(",") if t.strip()]


def is_graphic(kind: str) -> bool:
    return kind in GRAPHICS


@dataclass
class HmiScreen:
    name: str
    objects: list[HmiObject] = field(default_factory=list)


@dataclass
class HmiDesign:
    model_id: str
    screens: list[HmiScreen] = field(default_factory=list)
    connect_to: str = CONNECT_PLC
    answers: dict[str, str] = field(default_factory=dict)
    theme: str = DEFAULT_THEME

    def screen(self, name: str) -> HmiScreen | None:
        return next((s for s in self.screens if s.name == name), None)


# ----------------------------------------------------------------------------- model helpers

def grid_size(model_id: str) -> tuple[int, int]:
    entry = hmi_by_id(model_id)
    w, h = entry["resolution_px"] if entry else (800, 480)
    return GRID_COLS, max(8, round(GRID_COLS * h / w))


def new_object_id(design: HmiDesign) -> str:
    used = {o.id for s in design.screens for o in s.objects}
    n = len(used) + 1
    while f"o{n}" in used:
        n += 1
    return f"o{n}"


def overlaps(a: HmiObject, b: HmiObject) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def clamp_object(design: HmiDesign, obj: HmiObject) -> None:
    cols, rows = grid_size(design.model_id)
    obj.w = max(1, min(int(obj.w), cols))
    obj.h = max(1, min(int(obj.h), rows))
    obj.x = max(0, min(int(obj.x), cols - obj.w))
    obj.y = max(0, min(int(obj.y), rows - obj.h))


def free_spot(design: HmiDesign, screen: HmiScreen, w: int, h: int, max_row: int | None = None,
              skip: HmiObject | None = None) -> tuple[int, int] | None:
    cols, rows = grid_size(design.model_id)
    last = (max_row if max_row is not None else rows) - h
    for y in range(0, last + 1):
        for x in range(0, cols - w + 1):
            probe = HmiObject("probe", "text", x, y, w, h)
            if not any(overlaps(probe, o) for o in screen.objects if o is not skip):
                return x, y
    return None


def add_object(design: HmiDesign, screen: HmiScreen, kind: str, *, x: int | None = None, y: int | None = None,
               w: int | None = None, h: int | None = None, label: str = "", tag: str = "", color: str = "",
               target: str = "", max_row: int | None = None) -> HmiObject | None:
    """Add one object; with no x/y it goes in the first free grid spot (None when the screen is full)."""
    spec = OBJECT_KINDS[kind]
    cols, _rows = grid_size(design.model_id)
    w = w or min(spec["size"][0], cols)
    h = h or spec["size"][1]
    if x is None or y is None:
        spot = free_spot(design, screen, w, h, max_row=max_row)
        if spot is None:
            return None
        x, y = spot
    obj = HmiObject(new_object_id(design), kind, x, y, w, h, label or spec["name"], tag,
                    color or spec["color"], target, "", GRAPHICS[kind]["anim"] if kind in GRAPHICS else "")
    clamp_object(design, obj)
    screen.objects.append(obj)
    return obj


def rescale_to_model(design: HmiDesign, model_id: str) -> None:
    """Switch panel model; every object keeps its place and size in proportion."""
    c0, r0 = grid_size(design.model_id)
    c1, r1 = grid_size(model_id)
    design.model_id = model_id
    for screen in design.screens:
        for obj in screen.objects:
            obj.x = round(obj.x * c1 / c0)
            obj.w = max(1, round(obj.w * c1 / c0))
            obj.y = round(obj.y * r1 / r0)
            obj.h = max(1, round(obj.h * r1 / r0))
            clamp_object(design, obj)


# ----------------------------------------------------------------------------- JSON / project

def design_to_dict(design: HmiDesign) -> dict:
    return {
        "format": "cabinet-studio-hmi",
        "version": 1,
        "model_id": design.model_id,
        "connect_to": design.connect_to,
        "answers": dict(design.answers),
        "theme": design.theme,
        "screens": [
            {"name": s.name, "objects": [
                {"id": o.id, "kind": o.kind, "x": o.x, "y": o.y, "w": o.w, "h": o.h, "label": o.label,
                 "tag": o.tag, "color": o.color, "target": o.target, "group": o.group, "anim": o.anim}
                for o in s.objects]}
            for s in design.screens
        ],
    }


def design_from_dict(data: dict) -> HmiDesign:
    if not isinstance(data, dict) or data.get("format") != "cabinet-studio-hmi":
        raise ValueError("Not an HMI design.")
    screens = []
    for raw in data.get("screens") or []:
        objects = []
        for o in raw.get("objects") or []:
            if o.get("kind") not in OBJECT_KINDS:
                raise ValueError(f"Unknown HMI object kind {o.get('kind')!r}.")
            objects.append(HmiObject(str(o["id"]), o["kind"], int(o["x"]), int(o["y"]), int(o["w"]), int(o["h"]),
                                     str(o.get("label", "")), str(o.get("tag", "")), str(o.get("color", "")),
                                     str(o.get("target", "")), str(o.get("group", "")),
                                     str(o.get("anim", "")) if o.get("anim", "") in ANIMATIONS else ""))
        screens.append(HmiScreen(str(raw.get("name", "Screen")), objects))
    theme = str(data.get("theme") or DEFAULT_THEME)
    return HmiDesign(str(data.get("model_id", "")), screens, str(data.get("connect_to") or CONNECT_PLC),
                     {str(k): str(v) for k, v in (data.get("answers") or {}).items()},
                     theme if theme in THEMES else DEFAULT_THEME)


def design_to_json(design: HmiDesign) -> str:
    return json.dumps(design_to_dict(design), separators=(",", ":"))


def design_from_json(text: str) -> HmiDesign:
    return design_from_dict(json.loads(text))


def load_design(project) -> HmiDesign | None:
    """The saved HMI design, or None when there is none (or it cannot be read)."""
    text = (getattr(project, "interview", {}) or {}).get(STORE_KEY, "")
    if not text.strip():
        return None
    try:
        return design_from_json(text)
    except (ValueError, KeyError, TypeError):
        return None


def save_design(project, design: HmiDesign | None) -> None:
    if design is None:
        project.interview.pop(STORE_KEY, None)
    else:
        project.interview[STORE_KEY] = design_to_json(design)


# ----------------------------------------------------------------------------- tags

def project_tags(project) -> list[dict[str, str]]:
    """Tags the HMI may bind to: cabinet device tags first, then ladder program tags."""
    from cabinet_studio.services.programming import cabinet_device_tags, flatten_contacts, program_from_dict

    out: dict[str, dict[str, str]] = {}
    for d in cabinet_device_tags(project):
        out[d["tag"]] = {"tag": d["tag"], "source": "device", "type_id": d["type_id"],
                         "direction": d["io_direction"], "address": d["io_address"],
                         "description": d["description"] or d["function"]}
    try:
        program = program_from_dict(project.program or {})
    except ValueError:
        program = {"rungs": []}
    for rung in program.get("rungs") or []:
        names = [(c.get("tag") or "").strip() for c in flatten_contacts(rung)]
        names.append((rung.get("coil_tag") or "").strip())
        for extra in ("timer", "counter"):
            if isinstance(rung.get(extra), dict):
                names.append(str(rung[extra].get("tag") or "").strip())
        for name in names:
            if name and name not in out:
                out[name] = {"tag": name, "source": "ladder", "type_id": "", "direction": "",
                             "address": "", "description": ""}
    return list(out.values())


def _is_safety_tag(info: dict[str, str] | None, tag: str) -> bool:
    if info and info.get("type_id") in {"estop", "safety_relay", "light_curtain"}:
        return True
    hay = f"{tag} {(info or {}).get('description', '')}".lower()
    return any(word in hay for word in _SAFETY_WORDS)


def write_refusal(tag: str, project, tags: dict[str, dict] | None = None) -> str:
    """Why an HMI may NOT write ``tag`` ('' = allowed). Safety tags are never writable."""
    tags = tags if tags is not None else {t["tag"]: t for t in project_tags(project)}
    if _is_safety_tag(tags.get(tag), tag):
        return f"Refused: {tag} is a safety tag. Safety stays hardwired - the HMI never writes it."
    return ""


def validate_design(design: HmiDesign, project) -> list[str]:
    """Plain-words problems. Empty list = nothing found."""
    issues: list[str] = []
    if hmi_by_id(design.model_id) is None:
        issues.append(f"HMI model {design.model_id or '(none)'} is not in the HMI library.")
    if not design.screens:
        issues.append("The HMI has no screens.")
    cols, rows = grid_size(design.model_id)
    tags = {t["tag"]: t for t in project_tags(project)}
    names = {s.name for s in design.screens}
    for screen in design.screens:
        for i, obj in enumerate(screen.objects):
            where = f"{screen.name}: '{obj.label or obj.kind}'"
            if obj.x < 0 or obj.y < 0 or obj.x + obj.w > cols or obj.y + obj.h > rows:
                issues.append(f"{where} hangs off the screen.")
            for other in screen.objects[i + 1:]:
                if overlaps(obj, other):
                    issues.append(f"{where} overlaps '{other.label or other.kind}'.")
            tag = obj.tag.strip()
            if obj.kind in TAGGED_KINDS and not tag:
                issues.append(f"{where} has no PLC tag.")
            if obj.anim and obj.anim != "none" and is_graphic(obj.kind) and not tag:
                issues.append(f"{where} is animated but has no tag (it will stay still).")
            for one in obj.tags:
                if one not in tags and not one.startswith(HMI_TAG_PREFIX):
                    issues.append(f"{where} uses unknown tag {one} (not on the cabinet or in the ladder).")
            if tag and obj.access == "W":
                info = tags.get(tag)
                if _is_safety_tag(info, tag):
                    issues.append(f"{where} WRITES safety tag {tag}. Not allowed - safety stays hardwired.")
                elif info and (info["direction"].lower().startswith("in")
                               or info["type_id"] in {"pushbutton", "sensor", "selector", "estop"}):
                    issues.append(f"{where} writes physical input {tag}. Use an {HMI_TAG_PREFIX} memory tag instead.")
            if obj.kind == "nav" and obj.target and obj.target not in names:
                issues.append(f"{where} goes to missing screen {obj.target}.")
    return issues


def write_tags(design: HmiDesign) -> list[tuple[str, str, str]]:
    """(screen, object label, tag) for every object that writes into the PLC."""
    return [(s.name, o.label, o.tag) for s in design.screens for o in s.objects if o.access == "W" and o.tag]


def tag_table(design: HmiDesign, project) -> list[dict[str, str]]:
    tags = {t["tag"]: t for t in project_tags(project)}
    rows = []
    for screen in design.screens:
        for obj in screen.objects:
            for one in obj.tags:
                info = tags.get(one)
                if info and info["address"]:
                    address = info["address"]
                elif one.startswith(HMI_TAG_PREFIX):
                    address = "PLC memory - add to program"
                else:
                    address = "not assigned"
                rows.append({"screen": screen.name, "object": obj.label, "kind": OBJECT_KINDS[obj.kind]["name"],
                             "tag": one, "access": {"W": "Write", "R": "Read"}.get(obj.access, ""),
                             "address": address})
    return rows


# ----------------------------------------------------------------------------- faceplates (one-click groups)

# id -> name, help. Objects come from _faceplate_parts.
FACEPLATES: dict[str, dict[str, str]] = {
    "motor": {"name": "Motor", "help": "Run and Fault lamps, plus Start / Stop buttons when the HMI may start it."},
    "motor_vfd": {"name": "Motor with drive (VFD)",
                  "help": "Motor faceplate plus drive speed display and speed setpoint."},
    "valve": {"name": "Valve / solenoid", "help": "Open lamp and an Open / Close button."},
    "stack": {"name": "Stack light", "help": "Green, amber and red lamps that copy the stack light."},
    "counter": {"name": "Counter / timer readout", "help": "Shows the count or time, with a Reset button."},
}
_FAULT_WORDS = ("fault", "overload", "trip")


def _digits(tag: str) -> str:
    return "".join(ch for ch in tag if ch.isdigit())


def equipment(project) -> list[dict[str, str]]:
    """Machine parts found on the cabinet / ladder, each with a suggested faceplate."""
    from cabinet_studio.services.programming import (
        find_output_coil_tags,
        find_stack_light_tags,
        program_from_dict,
    )

    devices = _devices(project)
    types = {d["tag"]: d["type_id"] for d in devices}
    faults = [d["tag"] for d in devices
              if any(w in f"{d['tag']} {d['function']} {d['description']}".lower() for w in _FAULT_WORDS)]
    vfds = [d["tag"] for d in devices if d["type_id"] == "vfd"]
    out: list[dict[str, str]] = []
    used_vfd: set[str] = set()
    for i, coil in enumerate(t for t in find_output_coil_tags(devices)
                             if types.get(t) not in {"solenoid", "valve", "light"}):
        vfd = next((v for v in vfds if v not in used_vfd and _digits(v) == _digits(coil)), "")
        if not vfd and types.get(coil) == "vfd":
            vfd = coil
        if not vfd and i < len(vfds) and vfds[i] not in used_vfd:
            vfd = vfds[i]
        used_vfd.add(vfd)
        fault = next((f for f in faults if _digits(f) and _digits(f) == _digits(coil)), "")
        if not fault and len(faults) == 1:
            fault = faults[0]
        out.append({"tag": coil, "faceplate": "motor_vfd" if vfd else "motor", "vfd": vfd, "fault": fault})
    for v in vfds:
        if v not in used_vfd:
            out.append({"tag": v, "faceplate": "motor_vfd", "vfd": v, "fault": ""})
    for d in devices:
        if d["type_id"] in {"solenoid", "valve"}:
            out.append({"tag": d["tag"], "faceplate": "valve", "vfd": "", "fault": ""})
    stack = find_stack_light_tags(devices)
    if stack:
        out.append({"tag": "Stack light", "faceplate": "stack", "vfd": "", "fault": "", **stack})
    try:
        rungs = program_from_dict(project.program or {}).get("rungs") or []
    except ValueError:
        rungs = []
    for rung in rungs:
        for extra in ("counter", "timer"):
            tag = str((rung.get(extra) or {}).get("tag") or "").strip() if isinstance(rung.get(extra), dict) else ""
            if tag and all(e["tag"] != tag for e in out):
                out.append({"tag": tag, "faceplate": "counter", "vfd": "", "fault": ""})
    return out


def _faceplate_parts(fp: str, eq: dict[str, str], controls: bool) -> list[tuple]:
    """(dx, dy, w, h, kind, label, tag, color) for one faceplate."""
    tag = eq.get("tag", "")
    parts: list[tuple] = [(0, 0, 6, 1, "text", tag, "", "White")]
    if fp in ("motor", "motor_vfd"):
        parts += [(0, 1, 3, 2, "lamp", "Running", tag, "Green"),
                  (3, 1, 3, 2, "lamp", "Fault", eq.get("fault") or f"HMI_{tag}_Fault", "Red")]
        row = 3
        if controls:
            parts += [(0, 3, 3, 2, "momentary", "Start", f"HMI_{tag}_Start", "Green"),
                      (3, 3, 3, 2, "momentary", "Stop", f"HMI_{tag}_Stop", "Red")]
            row = 5
        if fp == "motor_vfd":
            vfd = eq.get("vfd") or tag
            parts += [(0, row, 3, 2, "numeric_display", "Speed Hz", f"HMI_{vfd}_Speed", "White"),
                      (3, row, 3, 2, "numeric_entry", "Set Hz", f"HMI_{vfd}_SpeedSP", "White")]
    elif fp == "valve":
        parts += [(0, 1, 3, 2, "lamp", "Open", tag, "Green")]
        if controls:
            parts += [(3, 1, 3, 2, "toggle", "Open/Close", f"HMI_{tag}_Cmd", "Blue")]
    elif fp == "stack":
        parts += [(0, 1, 2, 2, "lamp", "Green", eq.get("green", ""), "Green"),
                  (2, 1, 2, 2, "lamp", "Amber", eq.get("amber", ""), "Amber"),
                  (4, 1, 2, 2, "lamp", "Red", eq.get("red", ""), "Red")]
        parts = [p for p in parts if p[4] == "text" or p[6]]
    elif fp == "counter":
        parts += [(0, 1, 4, 2, "numeric_display", "Value", tag, "White"),
                  (4, 1, 2, 2, "momentary", "Reset", f"HMI_{tag}_Reset", "Amber")]
    return parts


def add_faceplate(design: HmiDesign, screen: HmiScreen, fp: str, eq: dict[str, str], *, controls: bool = True,
                  max_row: int | None = None) -> list[HmiObject] | None:
    """Drop a whole faceplate as one group in the first free spot (None when it does not fit)."""
    parts = _faceplate_parts(fp, eq, controls)
    w = max(p[0] + p[2] for p in parts)
    h = max(p[1] + p[3] for p in parts)
    spot = free_spot(design, screen, w, h, max_row=max_row)
    if spot is None:
        return None
    group = f"{fp}:{eq.get('tag', '')}"
    placed = []
    for dx, dy, pw, ph, kind, label, tag, color in parts:
        obj = HmiObject(new_object_id(design), kind, spot[0] + dx, spot[1] + dy, pw, ph, label, tag, color, "", group)
        screen.objects.append(obj)
        placed.append(obj)
    return placed


def group_objects(screen: HmiScreen, group: str) -> list[HmiObject]:
    return [o for o in screen.objects if group and o.group == group]


# ----------------------------------------------------------------------------- tag wizard

def _camel(label: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in "".join(ch if ch.isalnum() else " " for ch in label).split())


def suggest_tag(obj: HmiObject, project) -> tuple[str, str]:
    """Best tag for an object from its words and type, with the reason. ('', reason) when none fits."""
    if is_graphic(obj.kind):
        return _suggest_graphic_tag(obj, project)
    if obj.kind not in TAGGED_KINDS:
        return "", "This object does not use a PLC tag."
    from cabinet_studio.services.programming import find_estop_tag

    tags = project_tags(project)
    if obj.kind == "estop_status":
        tag = find_estop_tag(_devices(project)) or ""
        return tag, (f"{tag} is the E-stop on this cabinet (shown as status only)." if tag
                     else "No E-stop on this cabinet.")
    words = [w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in obj.label).split() if len(w) >= 2]
    if obj.access == "W":
        name = HMI_TAG_PREFIX + (_camel(obj.label) or obj.id)
        return name, f"Buttons and entries write an HMI memory bit ({name}); add it to the PLC program."

    def score(t: dict[str, str]) -> int:
        hay = f"{t['tag']} {t['description']}".lower()
        s = sum(3 for w in words if w in hay)
        if obj.kind in {"lamp"} and (t["direction"].lower().startswith("out") or t["source"] == "ladder"
                                     or t["type_id"] in {"contactor", "relay", "light", "motor"}):
            s += 1
        if _is_safety_tag(t, t["tag"]):
            s -= 1
        return s

    best = max(tags, key=score, default=None)
    if best is not None and score(best) >= 3:
        return best["tag"], f"{best['tag']} matches the words '{obj.label}'."
    if obj.kind in {"numeric_display", "trend"}:
        name = HMI_TAG_PREFIX + (_camel(obj.label) or obj.id)
        return name, f"No matching number on the cabinet; use PLC tag {name}."
    return "", f"No tag on the cabinet or ladder matches '{obj.label}'. Pick one from the list."


def _suggest_graphic_tag(obj: HmiObject, project) -> tuple[str, str]:
    """Machine graphics: match the run / sensor / level tag from cabinet device types and name words."""
    spec = GRAPHICS[obj.kind]
    tags = project_tags(project)
    if obj.kind == "g_stack_light":
        picked = []
        for colour in ("green", "amber", "red"):
            alt = {"amber": ("amber", "yellow")}.get(colour, (colour,))
            hit = next((t["tag"] for t in tags if t["type_id"] in {"light", ""}
                        and any(a in f"{t['tag']} {t['description']}".lower() for a in alt)), "")
            picked.append(hit)
        if any(picked):
            return ",".join(picked), "Stack light tiers matched by colour (green,amber,red)."
    custom = obj.label if obj.label != spec["name"] else ""
    label_words = [w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in custom).split() if len(w) >= 2]
    wants_output = spec["anim"] in ("run", "open", "extend", "travel")

    def score(t: dict[str, str]) -> int:
        hay = f"{t['tag']} {t['description']}".lower()
        s = 4 if t["type_id"] in spec["types"] else 0
        if wants_output and t["direction"].lower().startswith("out"):
            s += 2
        s += sum(2 for w in spec["words"] if len(w) > 1 and w in hay)
        s += sum(3 for w in label_words if w in hay and w not in {"pipe", "picture"})
        if obj.kind != "g_light_curtain" and _is_safety_tag(t, t["tag"]):
            s -= 10
        return s

    if not spec.get("numeric"):
        best = max(tags, key=score, default=None)
        if best is not None and score(best) >= 3:
            return best["tag"], f"{best['tag']} matches a {spec['name'].lower()} ({spec['anim']} animation)."
        return "", f"No cabinet or ladder tag looks like a {spec['name'].lower()}. Pick one from the list."
    name = HMI_TAG_PREFIX + (_camel(obj.label) or obj.id)
    return name, f"{spec['name']} reads a 0-100 number; use PLC tag {name}."


def bind_all(design: HmiDesign, project) -> int:
    """Fill every empty tag the wizard can; returns how many objects got a tag."""
    count = 0
    for screen in design.screens:
        for obj in screen.objects:
            if (obj.kind in TAGGED_KINDS or is_graphic(obj.kind)) and not obj.tag.strip():
                tag, _why = suggest_tag(obj, project)
                if tag:
                    obj.tag = tag
                    count += 1
    return count


# ----------------------------------------------------------------------------- alarms, navigation, CSV

PRIORITIES = ("1 - High", "2 - Medium", "3 - Low")


def alarm_rows(design: HmiDesign, project) -> list[dict[str, str]]:
    """Alarm list from E-stop / safety / fault / OL tags with a priority. E-stop alarms are status only."""
    rows: dict[str, dict[str, str]] = {}

    def add(tag: str, message: str, priority: str, klass: str) -> None:
        if tag and tag not in rows:
            rows[tag] = {"tag": tag, "message": message, "priority": priority, "class": klass}

    for d in _devices(project):
        hay = f"{d['tag']} {d['function']} {d['description']}".lower()
        name = d["description"] or d["tag"]
        if d["type_id"] == "estop" or any(w in hay for w in ("e-stop", "estop", "emergency")):
            add(d["tag"], f"E-stop pressed ({name})", PRIORITIES[0], "Safety - status only")
        elif d["type_id"] in {"safety_relay", "light_curtain"} or "curtain" in hay or "guard" in hay:
            add(d["tag"], f"Safety circuit open ({name})", PRIORITIES[0], "Safety - status only")
        elif any(w in hay for w in _FAULT_WORDS):
            add(d["tag"], f"{name} fault", PRIORITIES[1], "Equipment fault")
        elif any(w in hay for w in ("low level", "door", "warning", "high temp")):
            add(d["tag"], f"{name} warning", PRIORITIES[2], "Warning")
    for screen in design.screens:
        for obj in screen.objects:
            if obj.kind == "lamp" and obj.color == "Red" and obj.tag:
                add(obj.tag, f"{obj.group.split(':')[-1] + ' ' if obj.group else ''}{obj.label}".strip(),
                    PRIORITIES[1], "Equipment fault")
    return sorted(rows.values(), key=lambda r: (r["priority"], r["tag"]))


def rebuild_nav(design: HmiDesign) -> None:
    """Replace the bottom go-to buttons on every screen with one button per other screen."""
    cols, rows = grid_size(design.model_id)
    for screen in design.screens:
        screen.objects = [o for o in screen.objects if not (o.kind == "nav" and o.y >= rows - 2)]
        others = [s.name for s in design.screens if s.name != screen.name]
        w = max(2, cols // max(len(others), 1))
        for i, other in enumerate(others[: cols // 2]):
            screen.objects.append(HmiObject(new_object_id(design), "nav", min(i * w, cols - w), rows - 2, w, 2,
                                            f"Go to {other}", "", "Gray", other, "nav"))


def is_numeric(obj: HmiObject) -> bool:
    return obj.kind in {"numeric_display", "numeric_entry", "trend"} or obj.anim in NUMERIC_ANIMS


def hmi_tag_rows(design: HmiDesign, project) -> list[dict]:
    """One merged row per HMI tag: tag, type (BOOL/REAL), access (Read or Read/Write), address, description,
    screens, objects. Sorted by tag."""
    info = {t["tag"]: t for t in project_tags(project)}
    merged: dict[str, dict] = {}
    for screen in design.screens:
        for obj in screen.objects:
            for tag in obj.tags:
                row = merged.setdefault(tag, {"tag": tag, "type": "BOOL", "access": "Read", "screens": [],
                                              "objects": []})
                if is_numeric(obj):
                    row["type"] = "REAL"
                if obj.access == "W":
                    row["access"] = "Read/Write"
                if screen.name not in row["screens"]:
                    row["screens"].append(screen.name)
                row["objects"].append(obj.label)
    for tag, row in merged.items():
        t = info.get(tag, {})
        row["address"] = t.get("address") or ("HMI memory - add to PLC program" if tag.startswith(HMI_TAG_PREFIX)
                                              else "")
        row["description"] = t.get("description", "") or "; ".join(row["objects"])
    return [merged[k] for k in sorted(merged)]


def export_tag_csv(design: HmiDesign, project, path) -> int:
    """One row per HMI tag (name, type, read/write, address, description, screens). Returns the row count."""
    import csv

    info = {t["tag"]: t for t in project_tags(project)}
    rows = hmi_tag_rows(design, project)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Tag Name", "Data Type", "Access", "PLC Address", "Description", "Screens", "Objects"])
        for row in rows:
            writer.writerow([row["tag"], row["type"], row["access"], row["address"],
                             info.get(row["tag"], {}).get("description", ""),
                             "; ".join(row["screens"]), "; ".join(row["objects"])])
    return len(rows)


# ----------------------------------------------------------------------------- creator interview

QUESTION_KEYS = ("hmi_maker", "hmi_size", "hmi_model", "hmi_screens", "hmi_group", "hmi_overview",
                 "hmi_start_stop", "hmi_alarms", "hmi_numbers", "hmi_connect")
OVERVIEW_YES = "Yes - add a Machine screen"
GROUP_OVERVIEW = "One overview screen with every machine part"
GROUP_EACH = "Overview plus one screen per machine part"


def _devices(project) -> list[dict[str, str]]:
    from cabinet_studio.services.programming import cabinet_device_tags

    return cabinet_device_tags(project)


def hmi_question(project, answers: dict[str, str], key: str) -> dict:
    """One interview question: prompt, help, choices and the suggested default (with a reason)."""
    from cabinet_studio.services.programming import find_start_tag

    devices = _devices(project)
    if key == "hmi_maker":
        pref = project_maker_preference(project)
        fams = project_plc_families(project)
        reason = (f"Matches the {pref} parts on this cabinet." if pref else "Allen-Bradley is the shop default.")
        if fams:
            reason += f" PLC found: {', '.join(fams)}."
        return {"key": key, "prompt": "Which maker should the HMI touch screen be?",
                "help": "Pick the same maker as your PLC so they talk to each other easily.",
                "choices": ["Allen-Bradley", "Siemens", "Omron"], "default": pref or "Allen-Bradley", "reason": reason}
    maker = normalize_maker(answers.get("hmi_maker", "")) or project_maker_preference(project)
    if key == "hmi_size":
        sizes = [f"{s:g} in" for s in hmi_sizes(maker)]
        model_id, _why = _recommend(project, answers, None)
        size = f"{hmi_by_id(model_id)['screen_in']:g} in"
        return {"key": key, "prompt": "How big should the screen be?",
                "help": "Measured corner to corner. 7 in suits a few buttons and lights; 10-12 in suits a busy machine.",
                "choices": sizes, "default": size if size in sizes else sizes[0],
                "reason": f"Suggested for {len(devices)} tagged devices on this cabinet."}
    if key == "hmi_model":
        size = _inches(answers.get("hmi_size", ""))
        pool = hmi_choices(maker, size - 0.8, size + 0.8) if size else hmi_choices(maker)
        pool = pool or hmi_choices(maker)
        model_id, why = _recommend(project, answers, size)
        if model_id not in {e["id"] for e in pool}:
            model_id = pool[0]["id"]
            why = f"{hmi_label(pool[0])}. Closest library match."
        return {"key": key, "prompt": "Which HMI model?",
                "help": "All of these come from the HMI library. Hover the reason to see why one is suggested.",
                "choices": [hmi_label(e) for e in pool], "default": hmi_label(hmi_by_id(model_id)), "reason": why}
    if key == "hmi_screens":
        return {"key": key, "prompt": "Which screens do you want?",
                "help": "Main shows the machine. Manual lets you jog things. Alarms lists faults. Settings holds numbers.",
                "choices": list(SCREEN_SETS), "default": "Main + Manual + Alarms",
                "reason": "Main, Manual and Alarms cover most small machines."}
    if key == "hmi_group":
        parts = equipment(project)
        many = len(parts) > 3
        return {"key": key, "prompt": "How should machine parts be grouped?",
                "help": "Each motor, valve or stack light gets a ready-made faceplate (lamps, buttons, numbers).",
                "choices": [GROUP_OVERVIEW, GROUP_EACH], "default": GROUP_EACH if many else GROUP_OVERVIEW,
                "reason": f"Found {len(parts)} machine part(s): "
                          f"{', '.join(p['tag'] for p in parts[:5]) or 'none yet'}."}
    if key == "hmi_overview":
        parts = equipment(project)
        return {"key": key, "prompt": "Add a Machine picture screen (conveyors, motors, sensors, stack light)?",
                "help": "A simple animated picture of the machine built from the cabinet parts. "
                        "Great for prototypes; it moves in Run with simulator.",
                "choices": [OVERVIEW_YES, "No"], "default": OVERVIEW_YES if parts else "No",
                "reason": f"Found {len(parts)} machine part(s) to draw." if parts
                else "No motors, valves or lights on this cabinet yet."}
    if key == "hmi_start_stop":
        hard = bool(find_start_tag(devices))
        return {"key": key, "prompt": "Start / Stop buttons: hardwired on the door, or on the HMI too?",
                "help": "Hardwired buttons work even if the screen breaks. The E-stop is ALWAYS hardwired.",
                "choices": [START_HARDWIRED, START_ON_HMI], "default": START_HARDWIRED if hard else START_ON_HMI,
                "reason": "This cabinet already has a Start push button." if hard
                else "No Start push button on this cabinet, so the HMI gets Start / Stop."}
    if key == "hmi_alarms":
        return {"key": key, "prompt": "Show alarms on the HMI?",
                "help": "An alarm banner tells the operator what went wrong.",
                "choices": ["Yes", "No"], "default": "Yes", "reason": "Alarms help the operator fix stops fast."}
    if key == "hmi_numbers":
        vfds = [d["tag"] for d in devices if d["type_id"] == "vfd"]
        return {"key": key, "prompt": "Show speeds / numbers (like drive speed)?",
                "help": "Adds number displays (and setpoints on Settings) for each drive.",
                "choices": ["Yes", "No"], "default": "Yes" if vfds else "No",
                "reason": f"Drives found: {', '.join(vfds)}." if vfds else "No drives on this cabinet."}
    if key == "hmi_connect":
        switch = any(d["type_id"] == "ethernet_switch" for d in devices)
        return {"key": key, "prompt": "How does the HMI cable reach the PLC?",
                "help": "One Ethernet cable. Through a switch if the cabinet has one.",
                "choices": [CONNECT_PLC, CONNECT_SWITCH], "default": CONNECT_SWITCH if switch else CONNECT_PLC,
                "reason": "This cabinet has an Ethernet switch." if switch else "No Ethernet switch on this cabinet."}
    raise KeyError(key)


def _inches(text: str) -> float | None:
    try:
        return float(str(text).replace("in", "").strip())
    except ValueError:
        return None


def _recommend(project, answers: dict[str, str], size: float | None) -> tuple[str, str]:
    saved = dict(project.interview)
    try:
        project.interview.update({k: v for k, v in answers.items() if k == "hmi_maker"})
        return recommend_hmi(project, size_in=size)
    finally:
        project.interview.clear()
        project.interview.update(saved)


def default_answers(project, answers: dict[str, str] | None = None) -> dict[str, str]:
    """'Accept all': every unanswered question takes its suggested default."""
    out = dict(answers or {})
    for key in QUESTION_KEYS:
        if not out.get(key):
            out[key] = hmi_question(project, out, key)["default"]
    return out


def build_machine_screen(design: HmiDesign, screen: HmiScreen, project, parts: list[dict], body_rows: int) -> None:
    """Animated machine picture: one conveyor line per motor (motor + belt + part + photo-eye), then valves,
    a stack light and a status-only light curtain from the cabinet devices."""
    cols, _rows = grid_size(design.model_id)
    devices = _devices(project)
    motors = [eq for eq in parts if eq["faceplate"] in ("motor", "motor_vfd")][:2]
    sensors = [d["tag"] for d in devices if d["type_id"] == "sensor"]
    belt_w = max(4, min(10, cols - 9))
    for i, eq in enumerate(motors):
        y0 = 1 + i * 5
        if y0 + 4 > body_rows:
            break
        add_object(design, screen, "g_part", x=3, y=y0, w=belt_w, h=1, label=f"{eq['tag']} part", tag=eq["tag"])
        add_object(design, screen, "g_motor", x=0, y=y0 + 1, label=eq["tag"], tag=eq["tag"])
        add_object(design, screen, "g_conveyor", x=3, y=y0 + 1, w=belt_w, label=f"{eq['tag']} conveyor",
                   tag=eq["tag"])
        if i < len(sensors):
            add_object(design, screen, "g_photo_eye", x=3 + belt_w, y=y0 + 1, label=sensors[i], tag=sensors[i])
    extra = [("g_valve", eq["tag"], eq["tag"]) for eq in parts if eq["faceplate"] == "valve"][:3]
    if any(eq["faceplate"] == "stack" for eq in parts) or any(d["type_id"] == "light" for d in devices):
        extra.append(("g_stack_light", "Stack light", ""))
    extra += [("g_light_curtain", d["tag"], d["tag"]) for d in devices if d["type_id"] == "light_curtain"][:1]
    for kind, label, tag in extra:
        obj = add_object(design, screen, kind, label=label, tag=tag, max_row=body_rows)
        if obj is not None and not obj.tag:
            obj.tag = suggest_tag(obj, project)[0]


def generate_design(project, answers: dict[str, str] | None = None, theme: str = DEFAULT_THEME) -> HmiDesign:
    """Build a first HMI from the cabinet devices, the ladder tags and the interview answers.

    Every machine part gets a faceplate; alarms, trends and the go-to bar are added automatically.
    """
    from cabinet_studio.services.programming import find_estop_tag, find_reset_tag

    a = default_answers(project, answers)
    model_id = hmi_id_from_label(a["hmi_model"]) or recommend_hmi(project)[0]
    design = HmiDesign(model_id, [], CONNECT_SWITCH if a["hmi_connect"] == CONNECT_SWITCH else CONNECT_PLC, a,
                       theme if theme in THEMES else DEFAULT_THEME)
    names = list(SCREEN_SETS.get(a["hmi_screens"], ["Main"]))
    devices = _devices(project)
    estop = find_estop_tag(devices)
    numbers = a["hmi_numbers"] == "Yes"
    parts = equipment(project)
    for eq in parts:
        if eq["faceplate"] == "motor_vfd" and not numbers:
            eq["faceplate"] = "motor"
    vfds = [eq["vfd"] for eq in parts if eq["faceplate"] == "motor_vfd" and eq["vfd"]][:4]
    faults = [r["tag"] for r in alarm_rows(design, project) if r["priority"] != PRIORITIES[0]][:6]
    alarms = a["hmi_alarms"] == "Yes"
    on_hmi = a["hmi_start_stop"] == START_ON_HMI
    each = a["hmi_group"] == GROUP_EACH
    cols, rows = grid_size(model_id)
    body_rows = rows - 2
    part_screens = [eq for eq in parts if eq["faceplate"] != "stack"][:6] if each else []
    if part_screens:
        names[1:1] = [eq["tag"] for eq in part_screens]
    if a.get("hmi_overview") == OVERVIEW_YES and parts:
        names.insert(1, "Machine")

    for name in names:
        screen = HmiScreen(name)
        design.screens.append(screen)
        add_object(design, screen, "text", x=0, y=0, w=cols, h=1, label=f"{project.name} - {name}")

        def put(kind, **kw):
            add_object(design, screen, kind, max_row=body_rows, **kw)

        if name == "Main":
            if alarms:
                add_object(design, screen, "alarm_banner", x=0, y=1, w=cols, h=1, label="Newest alarm",
                           tag="HMI_AlarmActive")
            if estop:
                put("estop_status", label="E-stop status", tag=estop)
            for eq in parts:
                if each and eq in part_screens:
                    put("lamp", label=f"{eq['tag']} running", tag=eq["tag"], color="Green")
                elif add_faceplate(design, screen, eq["faceplate"], eq, controls=on_hmi, max_row=body_rows) is None:
                    put("lamp", label=f"{eq['tag']} on", tag=eq["tag"] if eq["faceplate"] != "stack" else "",
                        color="Green")
            if on_hmi:
                put("momentary", label="Start all", tag="HMI_Start", color="Green")
                put("momentary", label="Stop all", tag="HMI_Stop", color="Red")
            if on_hmi or faults or estop or find_reset_tag(devices):
                put("momentary", label="Reset", tag="HMI_Reset", color="Amber")
            screen.objects = [o for o in screen.objects if not (o.kind == "lamp" and not o.tag)]
        elif name == "Machine":
            build_machine_screen(design, screen, project, parts, body_rows)
        elif any(eq["tag"] == name for eq in part_screens):
            eq = next(e for e in part_screens if e["tag"] == name)
            add_faceplate(design, screen, eq["faceplate"], eq, controls=on_hmi, max_row=body_rows)
            if eq["faceplate"] == "motor_vfd" and eq["vfd"]:
                put("trend", label=f"{eq['vfd']} speed", tag=f"HMI_{eq['vfd']}_Speed", w=min(12, cols))
        elif name == "Manual":
            put("toggle", label="Manual mode", tag="HMI_ManualMode", color="Blue")
            for eq in parts:
                if eq["faceplate"] in ("motor", "motor_vfd", "valve"):
                    put("momentary", label=f"Jog {eq['tag']}", tag=f"HMI_Jog_{eq['tag']}", color="Blue")
                    put("lamp", label=f"{eq['tag']} on", tag=eq["tag"], color="Green")
            put("text", label="Jogs only run when the PLC program allows them.", w=cols, h=1)
        elif name == "Alarms":
            add_object(design, screen, "alarm_banner", x=0, y=1, w=cols, h=2, label="Alarm list",
                       tag="HMI_AlarmActive")
            if estop:
                put("estop_status", label="E-stop status", tag=estop)
            for tag in faults:
                put("lamp", label=f"{tag} fault", tag=tag, color="Red")
            put("momentary", label="Acknowledge", tag="HMI_AlarmAck", color="Amber")
        elif name == "Trends":
            for vfd in vfds:
                put("trend", label=f"{vfd} speed (Hz)", tag=f"HMI_{vfd}_Speed", w=min(12, cols))
            if not vfds:
                put("text", label="No numbers to trend yet - add a drive first.", w=cols, h=1)
        elif name == "Settings":
            for vfd in vfds:
                put("numeric_entry", label=f"{vfd} speed setpoint (Hz)", tag=f"HMI_{vfd}_SpeedSP")
            if not vfds:
                put("text", label="Nothing to set yet - add a drive to get speed setpoints.", w=cols, h=1)
    rebuild_nav(design)
    return design

