# -*- coding: utf-8 -*-
"""Field-level wiring / device suggestions with project carry-forward.

Given a project, the current device, a field name, and prior answers, returns
suggested value(s), a short why (plain English), and a predefined pick list.

Suggestions are a design aid. They never invent Allen-Bradley catalog numbers
and never invent a live plant IP as fact — only placeholders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.models.schema import FieldSpec, Library
from cabinet_studio.services.standards import StandardsProfile

# US industrial color practices (editable; follow project context when set).
US_COLOR_PICKS: dict[str, tuple[str, ...]] = {
    "ungrounded_ac": ("Black", "Red", "Blue", "Brown"),
    "grounded_ac": ("White", "Gray", "White/Gray"),
    "equipment_ground": ("Green", "Green/Yellow", "Green-Yellow"),
    "control_ac": ("Red", "Yellow", "Orange"),
    "control_dc": ("Blue", "Brown", "Dark blue"),
    "dc_positive": ("Blue", "Brown", "Dark blue"),
    "dc_negative": ("White/Blue", "White-Blue", "Gray", "White"),
    "foreign_voltage": ("Yellow", "Orange", "Purple"),
    "interlock": ("Yellow", "Orange"),
}

# US industrial panel AWG defaults (design aid — confirm against load / NEC).
US_GAUGE_PICKS: dict[str, tuple[str, ...]] = {
    "ungrounded_ac": ("14 AWG", "12 AWG", "10 AWG", "8 AWG"),
    "grounded_ac": ("14 AWG", "12 AWG", "10 AWG"),
    "equipment_ground": ("14 AWG", "12 AWG", "10 AWG"),
    "control_ac": ("16 AWG", "14 AWG", "18 AWG"),
    "control_dc": ("18 AWG", "16 AWG", "14 AWG"),
    "dc_positive": ("18 AWG", "16 AWG", "14 AWG"),
    "dc_negative": ("18 AWG", "16 AWG", "14 AWG"),
    "foreign_voltage": ("16 AWG", "14 AWG", "18 AWG"),
    "interlock": ("16 AWG", "18 AWG", "14 AWG"),
    "signal": ("18 AWG", "22 AWG", "16 AWG"),
}

DEFAULT_LANDINGS: dict[str, str] = {
    "plc": "Supply +24 VDC and 0 VDC on the PLC power terminals; PE to the ground bar",
    "hmi": "24 VDC on the HMI power pins; PE to the ground bar when the unit has one",
    "vfd": "L1 L2 L3 from the branch device; T1 T2 T3 to the motor; PE to the ground bar",
    "motor": "T1 T2 T3 from the drive or contactor; PE to the ground bar",
    "contactor": "L1 L2 L3 line side; T1 T2 T3 load side; A1 A2 coil",
    "estop": "NC contact in series with the safety / e-stop circuit",
    "ethernet_switch": "24 VDC on the switch power pins; PE when provided",
    "power_supply": "L1 and N (or L2) on the primary; + and - on the 24 VDC bus; PE to the ground bar",
    "sensor": "BN +24 VDC, BU 0 VDC, BK signal to the PLC input",
    "valve": "Solenoid coil pins to the PLC output and the 0 VDC return",
    "solenoid": "Coil pins to the PLC output and the 0 VDC return",
    "light": "Lamp pins to the PLC output and the return",
    "safety_relay": "A1 A2 supply; safety channel terminals as the catalog shows",
    "transmitter": "Loop + and - to the analog input",
    "io_module": "Field common and points on the module terminals; backplane to the parent PLC",
    "pushbutton": "Contact block to the PLC input and the return",
}

LANDING_PICKS: dict[str, tuple[str, ...]] = {
    "power_supply": (
        "L1 and N on primary; +24 VDC and 0 VDC bus; PE to ground bar",
        "L1 L2 L3 on primary; + and - secondary; PE to ground bar",
    ),
    "contactor": (
        "L1 L2 L3 line; T1 T2 T3 load; A1 A2 coil",
        "L1 line; T1 load; A1 A2 coil (1-pole)",
    ),
    "plc": (
        "Supply +24 VDC and 0 VDC on power terminals; PE to ground bar",
        "Embedded I/O commons on the CPU; PE to ground bar",
    ),
    "sensor": (
        "BN +24 VDC, BU 0 VDC, BK signal to PLC input",
        "Brown +24 VDC, blue 0 VDC, black to Local:x:I",
    ),
    "vfd": (
        "L1 L2 L3 from branch; T1 T2 T3 to motor; PE to ground bar",
        "L1 L2 from branch; T1 T2 to motor; PE to ground bar",
    ),
    "motor": (
        "T1 T2 T3 from drive or contactor; PE to ground bar",
        "U V W from VFD; PE to ground bar",
    ),
}

IO_DIRECTION: dict[str, str] = {
    "sensor": "Input",
    "estop": "Input",
    "pushbutton": "Input",
    "transmitter": "Input",
    "valve": "Output",
    "solenoid": "Output",
    "light": "Output",
    "contactor": "Output",
    "motor": "Output",
    "safety_relay": "Input and Output",
    "io_module": "Input and Output",
    "plc": "Network / no discrete I/O",
    "hmi": "Network / no discrete I/O",
    "vfd": "Network / no discrete I/O",
    "ethernet_switch": "Network / no discrete I/O",
    "power_supply": "Network / no discrete I/O",
}

WIRE_COUNTS: dict[str, int] = {
    "motor": 3,
    "vfd": 3,
    "contactor": 2,
    "power_supply": 2,
    "plc": 2,
}

POWER_TYPES = {"motor", "vfd", "power_supply", "contactor"}
ETHERNET_TYPES = {"plc", "hmi", "ethernet_switch", "vfd"}

ASSIST_FIELDS = (
    "wire_color",
    "wire_gauge",
    "wire_numbers",
    "terminal_landings",
    "io_direction",
    "io_address",
    "ip_address",
    "parent_tag",
    "slot",
    "slot_count",
    "protocol",
)


@dataclass(frozen=True)
class FieldAssist:
    """One field suggestion for the UI."""

    field: str
    value: str
    why: str
    picks: tuple[str, ...] = ()
    extras: dict[str, str] = field(default_factory=dict)  # e.hrs. io_address_description


def empty_wiring_context() -> dict:
    return {
        "wire_colors": {},
        "wire_gauges": {},
        "numbering_prefix": "W",
        "numbering_next": 101,
        "numbering_width": 3,
        "parent_plc_tag": "",
        "next_input_slot": 1,
        "next_input_bit": 0,
        "next_output_slot": 2,
        "next_output_bit": 0,
        "ip_base": "192.168.1",
        "next_ip_host": 10,
        "shared_buses": {},
        "interlock_color": "",
    }


def get_wiring_context(project: Project) -> dict:
    raw = getattr(project, "wiring_context", None) or {}
    ctx = empty_wiring_context()
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in ctx:
                ctx[key] = value
        if isinstance(raw.get("wire_colors"), dict):
            ctx["wire_colors"] = {
                str(k): str(v) for k, v in raw["wire_colors"].items() if str(v).strip()
            }
        if isinstance(raw.get("wire_gauges"), dict):
            ctx["wire_gauges"] = {
                str(k): str(v) for k, v in raw["wire_gauges"].items() if str(v).strip()
            }
        if isinstance(raw.get("shared_buses"), dict):
            ctx["shared_buses"] = {
                str(k): str(v) for k, v in raw["shared_buses"].items() if str(v).strip()
            }
    # Seed from items already on the panel when context is empty.
    if not ctx["parent_plc_tag"]:
        plc = _first_plc_tag(project)
        if plc:
            ctx["parent_plc_tag"] = plc
    if not ctx["wire_colors"]:
        ctx["wire_colors"] = _colors_from_items(project)
    highest = _highest_wire_on_project(project, ctx["numbering_prefix"])
    if highest >= int(ctx.get("numbering_next") or 101):
        ctx["numbering_next"] = highest + 1
    return ctx


def set_wiring_context(project: Project, ctx: dict) -> None:
    project.wiring_context = dict(ctx)


def color_role(type_id: str, interview: dict[str, str], *, field_hint: str = "") -> str:
    control = (interview.get("control_voltage") or "").lower()
    control_is_dc = "vdc" in control or ("dc" in control and "vac" not in control)
    hint = (field_hint or "").lower()
    if "interlock" in hint or "safety" in hint:
        return "interlock"
    if "ground" in hint or hint in {"pe", "egc"}:
        return "equipment_ground"
    if "neutral" in hint or hint in {"n", "grounded"}:
        return "grounded_ac"
    if type_id in {"motor", "vfd"}:
        return "ungrounded_ac"
    if type_id == "power_supply":
        return "ungrounded_ac"
    if type_id == "contactor":
        return "control_dc" if control_is_dc else "control_ac"
    if type_id in {"estop", "pushbutton", "safety_relay", "light"}:
        return "control_dc" if control_is_dc else "control_ac"
    if type_id in {
        "sensor",
        "transmitter",
        "solenoid",
        "valve",
        "plc",
        "hmi",
        "ethernet_switch",
        "io_module",
    }:
        return "dc_positive" if control_is_dc or not control else "control_ac"
    return "ungrounded_ac"


def suggest_field(
    project: Project,
    library: Library,
    profile: StandardsProfile,
    *,
    type_id: str,
    field_key: str,
    item: PlacedItem | None = None,
    prior: dict[str, str] | None = None,
    interview: dict[str, str] | None = None,
) -> FieldAssist:
    """Suggest one field. Uses wiring_context + prior answers for continuity."""
    interview = interview if interview is not None else dict(project.interview or {})
    prior = dict(prior or {})
    if item is not None:
        for key, value in item.fields.items():
            prior.setdefault(key, value)
    ctx = get_wiring_context(project)
    tag = (prior.get("tag") or (item.fields.get("tag") if item else "") or type_id.upper()).strip()

    if field_key == "wire_color":
        return _suggest_wire_color(type_id, interview, ctx, profile)
    if field_key == "wire_gauge":
        return _suggest_wire_gauge(type_id, interview, ctx)
    if field_key == "wire_numbers":
        return _suggest_wire_numbers(project, profile, type_id, prior, ctx, item)
    if field_key == "terminal_landings":
        return _suggest_landings(type_id, tag)
    if field_key == "io_direction":
        direction = IO_DIRECTION.get(type_id, "Network / no discrete I/O")
        return FieldAssist(
            field="io_direction",
            value=direction,
            why=_why_direction(type_id, direction),
            picks=("Input", "Output", "Input and Output", "Network / no discrete I/O"),
        )
    if field_key == "io_address":
        return _suggest_io_address(type_id, prior, ctx)
    if field_key == "ip_address":
        return _suggest_ip(type_id, ctx)
    if field_key == "parent_tag":
        return _suggest_parent_tag(project, ctx)
    if field_key == "slot":
        return _suggest_slot(type_id, prior, ctx)
    if field_key == "slot_count":
        return FieldAssist(
            field="slot_count",
            value="8",
            why="Most compact PLCs start with a small local rack. Eight slots is a common starter size — change it to match the real chassis.",
            picks=("4", "8", "10", "16", "Embedded I/O only"),
        )
    if field_key == "protocol":
        return FieldAssist(
            field="protocol",
            value="EtherNet/IP",
            why="Allen-Bradley style cabinets usually talk EtherNet/IP. Pick PROFINET or Modbus TCP only when the plant network needs it.",
            picks=("EtherNet/IP", "PROFINET", "Modbus TCP"),
        )

    # Spec / identity fallbacks with predefined picks when the schema has options.
    equipment = library.types.get(type_id)
    if equipment is not None:
        for spec in equipment.fields:
            if spec.key == field_key:
                return _suggest_from_spec(spec, type_id, interview, prior, ctx)
    return FieldAssist(field=field_key, value="", why="Type what the print or plant standard asks for.", picks=())


def suggest_all_fields(
    project: Project,
    library: Library,
    profile: StandardsProfile,
    type_id: str,
    *,
    item: PlacedItem | None = None,
    prior: dict[str, str] | None = None,
    interview: dict[str, str] | None = None,
) -> dict[str, FieldAssist]:
    equipment = library.types.get(type_id)
    keys = [spec.key for spec in equipment.fields] if equipment else []
    # Always offer core wiring / I/O continuity fields.
    for key in (
        "wire_color",
        "wire_gauge",
        "wire_numbers",
        "terminal_landings",
        "io_direction",
        "io_address",
    ):
        if key not in keys:
            keys.append(key)
    if type_id in ETHERNET_TYPES and "ip_address" not in keys:
        keys.append("ip_address")
    if type_id == "io_module":
        for key in ("parent_tag", "slot"):
            if key not in keys:
                keys.append(key)
    if type_id == "plc":
        for key in ("slot_count", "protocol", "ip_address"):
            if key not in keys:
                keys.append(key)
    out: dict[str, FieldAssist] = {}
    rolling = dict(prior or {})
    if item is not None:
        for key, value in item.fields.items():
            rolling.setdefault(key, value)
    for key in keys:
        assist = suggest_field(
            project,
            library,
            profile,
            type_id=type_id,
            field_key=key,
            item=item,
            prior=rolling,
            interview=interview,
        )
        out[key] = assist
        if assist.value and not str(rolling.get(key, "")).strip():
            rolling[key] = assist.value
    return out



def apply_all_project_suggestions(
    project: Project,
    library: Library,
    profile: StandardsProfile,
    *,
    only_blank: bool = True,
) -> tuple[StandardsProfile, int, int]:
    """Apply wiring_assist suggestions to every device using carry-forward context.

    Walks devices in panel order. Each device gets suggest_all_fields with the
    project context already updated by prior devices (remember_device_fields).
    Returns (updated_profile, devices_changed, fields_filled).
    """
    devices_changed = 0
    fields_filled = 0
    updated = profile
    for item in list(project.items):
        before = dict(item.fields)
        assists = suggest_all_fields(
            project,
            library,
            updated,
            item.type_id,
            item=item,
            prior=item.fields,
            interview=project.interview,
        )
        merged = apply_assist_values(item.fields, assists, only_blank=only_blank)
        filled = sum(
            1
            for key, value in merged.items()
            if str(value).strip() and not str(before.get(key, "")).strip()
        )
        if merged != before:
            item.fields = merged
            devices_changed += 1
            fields_filled += filled
        updated = remember_device_fields(
            project,
            updated,
            type_id=item.type_id,
            fields=item.fields,
            interview=project.interview,
        )
    return updated, devices_changed, fields_filled


def apply_assist_values(
    current: dict[str, str],
    assists: dict[str, FieldAssist],
    *,
    only_blank: bool = True,
) -> dict[str, str]:
    merged = dict(current)
    for key, assist in assists.items():
        if not assist.value:
            continue
        if only_blank and str(merged.get(key, "")).strip():
            continue
        merged[key] = assist.value
    return merged


def remember_field_choice(
    project: Project,
    profile: StandardsProfile,
    *,
    type_id: str,
    field_key: str,
    value: str,
    interview: dict[str, str] | None = None,
) -> tuple[dict, StandardsProfile]:
    """Update wiring_context (and optionally shop colors) after the human accepts a value."""
    from cabinet_studio.services.standards import copy_profile

    interview = interview if interview is not None else dict(project.interview or {})
    ctx = get_wiring_context(project)
    value = (value or "").strip()
    if not value:
        return ctx, profile

    if field_key == "wire_color":
        role = color_role(type_id, interview)
        ctx["wire_colors"][role] = value
        if role == "interlock":
            ctx["interlock_color"] = value
        updated = copy_profile(profile)
        if role in updated.wire_colors or role in US_COLOR_PICKS:
            updated.wire_colors[role if role != "interlock" else "foreign_voltage"] = value
        profile = updated
    elif field_key == "wire_gauge":
        role = color_role(type_id, interview)
        gauges = dict(ctx.get("wire_gauges") or {})
        gauges[role] = value
        ctx["wire_gauges"] = gauges
    elif field_key == "wire_numbers":
        highest = _highest_sequence(ctx["numbering_prefix"], value)
        if highest >= int(ctx["numbering_next"]):
            ctx["numbering_next"] = highest + 1
        # Shared bus: power devices on same supply can reuse later — store first AC set.
        if type_id in POWER_TYPES and "PE" in value.upper():
            bus_key = _bus_key(interview)
            if bus_key and bus_key not in ctx["shared_buses"]:
                # Keep non-PE tokens as the shared feeder hint.
                tokens = [t for t in _tokens_list(value) if t.upper() != "PE"]
                if tokens:
                    ctx["shared_buses"][bus_key] = ", ".join(tokens)
    elif field_key == "parent_tag":
        ctx["parent_plc_tag"] = value
    elif field_key == "ip_address":
        host = _ip_host(value)
        if host is not None and host >= int(ctx["next_ip_host"]):
            ctx["next_ip_host"] = host + 1
        base = _ip_base(value)
        if base:
            ctx["ip_base"] = base
    elif field_key == "io_address":
        parsed = _parse_logix(value)
        if parsed:
            kind, slot, bit = parsed
            if kind == "I":
                ctx["next_input_slot"] = slot
                ctx["next_input_bit"] = bit + 1
                if ctx["next_input_bit"] > 15:
                    ctx["next_input_slot"] = slot + 1
                    ctx["next_input_bit"] = 0
            elif kind == "O":
                ctx["next_output_slot"] = slot
                ctx["next_output_bit"] = bit + 1
                if ctx["next_output_bit"] > 15:
                    ctx["next_output_slot"] = slot + 1
                    ctx["next_output_bit"] = 0
    elif field_key == "slot" and value.isdigit():
        # Next free slot hint for the following I/O module.
        nxt = int(value) + 1
        if nxt > int(ctx.get("next_input_slot") or 1):
            ctx["next_input_slot"] = nxt

    set_wiring_context(project, ctx)
    return ctx, profile


def remember_device_fields(
    project: Project,
    profile: StandardsProfile,
    *,
    type_id: str,
    fields: dict[str, str],
    interview: dict[str, str] | None = None,
) -> StandardsProfile:
    """Carry forward every assist-relevant answer from a finished device."""
    updated = profile
    skip_unless = {
        "slot": {"io_module"},
        "parent_tag": {"io_module"},
        "ip_address": ETHERNET_TYPES,
        "slot_count": {"plc"},
        "protocol": {"plc", "hmi"},
    }
    for key in ASSIST_FIELDS:
        if key in skip_unless and type_id not in skip_unless[key]:
            continue
        if key in fields and str(fields.get(key, "")).strip():
            _ctx, updated = remember_field_choice(
                project,
                updated,
                type_id=type_id,
                field_key=key,
                value=fields[key],
                interview=interview,
            )
    # PLC tag becomes the default parent.
    tag = (fields.get("tag") or "").strip()
    if type_id == "plc" and tag:
        ctx = get_wiring_context(project)
        ctx["parent_plc_tag"] = tag
        set_wiring_context(project, ctx)
    return updated


def why_for_pick(field_key: str, pick: str, type_id: str = "") -> str:
    """Short why text when the user chooses a predefined pick."""
    pick_l = (pick or "").lower()
    if field_key == "wire_color":
        if pick_l in {"green", "green/yellow", "green-yellow"}:
            return "Green (or green/yellow) marks the equipment ground so nobody mistakes it for a power wire."
        if pick_l in {"white", "gray", "white/gray"}:
            return "White or gray is the grounded / neutral conductor in US industrial panels."
        if pick_l in {"black", "red", "blue", "brown"} and type_id in POWER_TYPES:
            return "Black, red, and blue are the usual phase colors for AC power in US industrial cabinets."
        if "white/blue" in pick_l or "white-blue" in pick_l:
            return "White with a blue stripe (or white-blue) marks DC negative / 0 VDC return."
        if pick_l in {"yellow", "orange"}:
            return "Yellow or orange often means a foreign voltage or interlock — keep using the same color once the project picks one."
        return "Keep using the same color for this kind of circuit so the next device matches the panel."
    if field_key == "io_direction":
        return _why_direction(type_id, pick)
    if field_key == "protocol":
        return f"{pick} is how the PLC talks on the network. Match the plant standard."
    if field_key == "wire_numbers":
        return "Wire numbers label each conductor. Matching numbers mean the same electrical point."
    if field_key == "terminal_landings":
        return "Landings say exactly which screw each wire goes under — like a map for the electrician."
    if field_key == "ip_address":
        return "This is only a placeholder. Change it to match the real plant network before anyone downloads."
    if field_key == "parent_tag":
        return "The parent PLC tag ties this I/O module to the controller that owns it."
    if field_key == "slot":
        return "The slot number is where this module sits in the rack — keep them in order."
    if field_key == "io_address":
        return _io_plain_english(pick)
    return "Use this when it matches the print or the plant standard."


# --- internals -----------------------------------------------------------------


def _suggest_wire_color(
    type_id: str,
    interview: dict[str, str],
    ctx: dict,
    profile: StandardsProfile,
) -> FieldAssist:
    role = color_role(type_id, interview)
    if role == "interlock" and ctx.get("interlock_color"):
        value = str(ctx["interlock_color"])
        why = f"This project already used {value} for interlocks. Keep using it so every interlock wire matches."
    elif role in ctx.get("wire_colors", {}):
        value = str(ctx["wire_colors"][role])
        why = f"Earlier devices on this cabinet used {value} for this kind of circuit. Same color keeps the panel consistent."
    elif role in profile.wire_colors:
        value = profile.wire_colors[role]
        why = _default_color_why(role, value)
    else:
        picks = US_COLOR_PICKS.get(role, ("Black",))
        value = picks[0]
        why = _default_color_why(role, value)
    picks = US_COLOR_PICKS.get(role, (value,))
    # Prefer project color first in the list.
    ordered = tuple(dict.fromkeys((value, *picks)))
    return FieldAssist(field="wire_color", value=value, why=why, picks=ordered)


def _default_color_why(role: str, value: str) -> str:
    if role == "equipment_ground":
        return f"{value} marks the safety ground (PE). Never use it for power."
    if role == "grounded_ac":
        return f"{value} is the usual neutral / grounded conductor color in US panels."
    if role == "ungrounded_ac":
        return f"{value} is a standard hot / phase color for AC power. Red and blue are the other phases."
    if role in {"dc_positive", "control_dc"}:
        return f"{value} is a common color for DC+ / control DC so it does not look like AC power."
    if role == "dc_negative":
        return f"{value} marks DC− / 0 VDC return."
    if role == "control_ac":
        return f"{value} is a common control-AC color so it stands apart from power conductors."
    if role in {"foreign_voltage", "interlock"}:
        return f"{value} often flags interlocks or foreign voltage. Once chosen, reuse it on this job."
    return f"Suggested shop color: {value}."


def _suggest_wire_numbers(
    project: Project,
    profile: StandardsProfile,
    type_id: str,
    prior: dict[str, str],
    ctx: dict,
    item: PlacedItem | None,
) -> FieldAssist:
    prefix = str(ctx.get("numbering_prefix") or profile.numbering_prefix or "W")
    width = int(ctx.get("numbering_width") or profile.numbering_width or 3)
    cursor = int(ctx.get("numbering_next") or profile.numbering_next or 101)
    used = _used_wire_tokens(project, skip_item_id=None if item is None else item.id)
    # Reuse shared bus when this device shares the supply circuit.
    bus_key = _bus_key(project.interview)
    shared = ""
    if type_id in POWER_TYPES and bus_key and bus_key in ctx.get("shared_buses", {}):
        # Second power device on same feeder: suggest continuing from bus + new load legs,
        # but never invent device tags — only wire tokens.
        shared = str(ctx["shared_buses"][bus_key])

    count = WIRE_COUNTS.get(type_id, 1)
    numbers = _allocate(prefix, width, cursor, used, count)
    if type_id in POWER_TYPES and "PE" not in {n.upper() for n in numbers}:
        numbers.append("PE")
    value = ", ".join(numbers)
    why = (
        f"Wire numbers count up like {prefix}101, {prefix}102. "
        "PE means the green ground wire. Matching numbers mean the same electrical point."
    )
    if shared:
        why += f" This cabinet already used {shared} on the shared power bus — keep load wires unique."
    picks = (value,)
    # Offer a couple of sequential alternatives.
    alt2 = _allocate(prefix, width, cursor + count + 1, used | {n.upper() for n in numbers}, count)
    if type_id in POWER_TYPES:
        alt2 = [*alt2, "PE"]
    picks = tuple(dict.fromkeys((value, ", ".join(alt2), "PE")))
    return FieldAssist(field="wire_numbers", value=value, why=why, picks=picks)


def _suggest_landings(type_id: str, tag: str) -> FieldAssist:
    base = DEFAULT_LANDINGS.get(
        type_id, "Land each conductor on the device terminals and the ground bar"
    )
    value = f"{tag}: {base}" if tag else base
    extras = LANDING_PICKS.get(type_id, ())
    picks = tuple(dict.fromkeys((value, *[f"{tag}: {p}" if tag else p for p in extras])))
    why = (
        "Terminal landings tell the electrician which screw each wire goes under "
        "(for example L1/N/PE on a power supply, or A1/A2 on a contactor coil)."
    )
    return FieldAssist(field="terminal_landings", value=value, why=why, picks=picks)


def _suggest_io_address(type_id: str, prior: dict[str, str], ctx: dict) -> FieldAssist:
    direction = (prior.get("io_direction") or IO_DIRECTION.get(type_id, "")).strip()
    if direction.startswith("Network") or type_id in {
        "plc",
        "hmi",
        "ethernet_switch",
        "power_supply",
        "vfd",
    }:
        tag = (prior.get("tag") or type_id.upper()).strip()
        value = f"Network / {tag}"
        why = (
            "This device talks on the network, so it does not need a discrete rack bit. "
            "The placeholder reminds programmers to use the tag or IP instead."
        )
        return FieldAssist(
            field="io_address",
            value=value,
            why=why,
            picks=(value, "Network / see IP address"),
            extras={"io_address_description": why},
        )

    if "Output" in direction and "Input" not in direction.split(" and ")[0]:
        # Pure output (or output-first).
        kind = "O"
        slot = int(ctx.get("next_output_slot") or 2)
        bit = int(ctx.get("next_output_bit") or 0)
    elif "Output" in direction and "Input" in direction:
        kind = "I"
        slot = int(ctx.get("next_input_slot") or 1)
        bit = int(ctx.get("next_input_bit") or 0)
    else:
        kind = "I"
        slot = int(ctx.get("next_input_slot") or 1)
        bit = int(ctx.get("next_input_bit") or 0)

    value = f"Local:{slot}:{kind}.Data.{bit}"
    plain = _io_plain_english(value)
    alt = f"Local:{slot}:{kind}.Data.{bit + 1}"
    return FieldAssist(
        field="io_address",
        value=value,
        why=plain,
        picks=(value, alt, f"%{kind}{slot}.{bit}"),
        extras={"io_address_description": plain},
    )


def _suggest_ip(type_id: str, ctx: dict) -> FieldAssist:
    if type_id not in ETHERNET_TYPES:
        return FieldAssist(
            field="ip_address",
            value="",
            why="This device is not an Ethernet node on the starter list, so no IP is suggested.",
            picks=(),
        )
    base = str(ctx.get("ip_base") or "192.168.1")
    host = int(ctx.get("next_ip_host") or 10)
    value = f"{base}.{host}"
    why = (
        f"Placeholder IP {value} — change it to match the real plant network. "
        "Cabinet Studio never invents a live plant address as fact."
    )
    picks = (value, f"{base}.{host + 1}", f"{base}.10", "10.0.0.10")
    return FieldAssist(field="ip_address", value=value, why=why, picks=picks)


def _suggest_parent_tag(project: Project, ctx: dict) -> FieldAssist:
    tags = _plc_tags(project)
    preferred = (ctx.get("parent_plc_tag") or "").strip()
    if preferred and preferred in tags:
        value = preferred
    elif preferred:
        value = preferred
    elif tags:
        value = tags[0]
    else:
        value = "PLC1"
    why = (
        f"Use parent PLC tag {value} so this I/O module belongs to the controller already on the panel. "
        "Do not invent a new PLC tag unless you are adding a second controller."
    )
    picks = tuple(dict.fromkeys((value, *tags, "PLC1")))
    return FieldAssist(field="parent_tag", value=value, why=why, picks=picks)


def _suggest_slot(type_id: str, prior: dict[str, str], ctx: dict) -> FieldAssist:
    if type_id != "io_module":
        value = str(ctx.get("next_input_slot") or 1)
    else:
        value = str(ctx.get("next_input_slot") or 1)
    why = (
        f"Suggest slot {value} — the next free local slot after devices already placed. "
        "Keep modules in order left-to-right on the rack."
    )
    picks = tuple(str(n) for n in range(int(value), int(value) + 5))
    return FieldAssist(field="slot", value=value, why=why, picks=picks)


def _suggest_from_spec(
    spec: FieldSpec,
    type_id: str,
    interview: dict[str, str],
    prior: dict[str, str],
    ctx: dict,
) -> FieldAssist:
    if spec.options:
        # Prefer interview voltage when labels match.
        value = spec.options[0]
        if spec.key in {"voltage", "coil_voltage", "solenoid_voltage", "input_voltage", "output_voltage"}:
            control = interview.get("control_voltage") or ""
            supply = interview.get("supply_voltage") or ""
            for opt in spec.options:
                if control and control.split()[0] in opt:
                    value = opt
                    break
                if supply and supply.split()[0] in opt:
                    value = opt
                    break
            if spec.key == "output_voltage" and control:
                value = control if control in spec.options else (control or value)
            if spec.key in {"voltage", "coil_voltage", "solenoid_voltage"} and control:
                value = control if not spec.options else next(
                    (o for o in spec.options if control[:2] in o or control in o),
                    control if not spec.options else value,
                )
                if control and not spec.options:
                    value = control
                elif control:
                    # For text-like choice mismatch, keep first option but why mentions interview.
                    for opt in spec.options:
                        if any(part in opt for part in control.replace("VDC", "").replace("VAC", "").split() if part):
                            value = opt
                            break
        why = spec.help or f"Pick the {spec.label.lower()} that matches the job."
        return FieldAssist(field=spec.key, value=value, why=why, picks=tuple(spec.options))
    # Text placeholders pulled from interview.
    if spec.key in {"voltage", "coil_voltage", "solenoid_voltage"} and interview.get("control_voltage"):
        return FieldAssist(
            field=spec.key,
            value=interview["control_voltage"],
            why="Matches the control voltage answered in the interview.",
            picks=(interview["control_voltage"], "24 VDC", "120 VAC"),
        )
    if spec.key == "input_voltage" and interview.get("supply_voltage"):
        return FieldAssist(
            field=spec.key,
            value=interview["supply_voltage"],
            why="Matches the supply voltage answered in the interview.",
            picks=(interview["supply_voltage"], "480 VAC", "240 VAC", "120 VAC"),
        )
    if spec.key == "output_voltage" and interview.get("control_voltage"):
        return FieldAssist(
            field=spec.key,
            value=interview["control_voltage"],
            why="Matches the control voltage answered in the interview.",
            picks=(interview["control_voltage"], "24 VDC", "120 VAC"),
        )
    if spec.placeholder:
        return FieldAssist(
            field=spec.key,
            value="",
            why=spec.help or "Fill this from the print or nameplate.",
            picks=(spec.placeholder,) if spec.placeholder else (),
        )
    return FieldAssist(
        field=spec.key,
        value="",
        why=spec.help or "Fill this from the print or nameplate.",
        picks=(),
    )


def _why_direction(type_id: str, direction: str) -> str:
    if direction.startswith("Input"):
        return "Inputs are signals the PLC reads (sensors, buttons, e-stops)."
    if direction.startswith("Output"):
        return "Outputs are signals the PLC turns on (lights, valves, contactor coils)."
    if "Input and Output" in direction:
        return "This device both reads and writes points on the PLC."
    return "Network devices are watched over Ethernet, not a single rack bit."


def _io_plain_english(address: str) -> str:
    parsed = _parse_logix(address)
    if not parsed:
        if address.lower().startswith("network"):
            return "Network device — use the tag or IP, not a discrete rack bit."
        return f"Address {address} is the PLC point for this device."
    kind, slot, bit = parsed
    side = "input" if kind == "I" else "output"
    return (
        f"Local:{slot}:{kind}.Data.{bit} means local rack slot {slot}, "
        f"{side} data bit {bit}. That is the PLC point for this wire."
    )


def _parse_logix(address: str) -> tuple[str, int, int] | None:
    match = re.search(
        r"Local\s*:\s*(\d+)\s*:\s*([IO])\s*\.?\s*Data\s*\.\s*(\d+)",
        address or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(2).upper(), int(match.group(1)), int(match.group(3))


def _allocate(prefix: str, width: int, cursor: int, used: set[str], count: int) -> list[str]:
    numbers: list[str] = []
    guard = 0
    while len(numbers) < count and guard < 10000:
        guard += 1
        label = f"{prefix}{cursor:0{width}d}"
        cursor += 1
        if label.upper() in used or label.upper() == "PE":
            continue
        numbers.append(label)
        used.add(label.upper())
    return numbers


def _used_wire_tokens(project: Project, skip_item_id: str | None) -> set[str]:
    found: set[str] = set()
    for item in project.items:
        if item.id == skip_item_id:
            continue
        found.update(t.upper() for t in _tokens_list(item.fields.get("wire_numbers", "")))
    return found


def _tokens_list(raw: str) -> list[str]:
    return [part for part in re.split(r"[,;\s]+", raw or "") if part.strip()]


def _highest_sequence(prefix: str, raw: str) -> int:
    pattern = re.compile(rf"{re.escape(prefix)}(\d+)", re.IGNORECASE)
    highest = 0
    for match in pattern.finditer(raw or ""):
        highest = max(highest, int(match.group(1)))
    return highest


def _highest_wire_on_project(project: Project, prefix: str) -> int:
    highest = 0
    for item in project.items:
        highest = max(highest, _highest_sequence(prefix, item.fields.get("wire_numbers", "")))
    return highest


def _first_plc_tag(project: Project) -> str:
    tags = _plc_tags(project)
    return tags[0] if tags else ""


def _plc_tags(project: Project) -> list[str]:
    tags: list[str] = []
    for item in project.items:
        if item.type_id != "plc":
            continue
        tag = (item.fields.get("tag") or "").strip()
        if tag:
            tags.append(tag)
    return tags


def _colors_from_items(project: Project) -> dict[str, str]:
    colors: dict[str, str] = {}
    for item in project.items:
        color = (item.fields.get("wire_color") or "").strip()
        if not color:
            continue
        role = color_role(item.type_id, project.interview or {})
        colors.setdefault(role, color)
    return colors


def _bus_key(interview: dict[str, str] | None) -> str:
    interview = interview or {}
    supply = (interview.get("supply_voltage") or "").strip() or "default"
    return f"supply:{supply}"


def _ip_host(value: str) -> int | None:
    parts = (value or "").strip().split(".")
    if len(parts) != 4:
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


def _ip_base(value: str) -> str:
    parts = (value or "").strip().split(".")
    if len(parts) != 4:
        return ""
    return ".".join(parts[:3])


GROUND_TOKENS = {"PE", "GND", "GROUND"}


def role_for_wire(type_id: str, wire: str, interview: dict[str, str] | None = None) -> str:
    """Color/gauge role for one conductor token (buses + device class)."""
    token = (wire or "").strip().upper()
    if token in GROUND_TOKENS:
        return "equipment_ground"
    if token in {"+24V", "+24", "24V", "24VDC", "V+", "DC+"}:
        return "dc_positive"
    if token in {"0V", "0VDC", "V-", "DC-", "COM", "COMMON"}:
        return "dc_negative"
    if token in {"LINE", "L", "HOT"}:
        return "ungrounded_ac"
    if token in {"L1", "L2", "L3"} or (token.startswith("T") and len(token) > 1 and token[1:].isdigit()):
        return "ungrounded_ac"
    if token == "N":
        return "grounded_ac"
    return color_role(type_id or "", interview or {})


def _split_device_colors(raw: str) -> list[str]:
    text = " ".join((raw or "").replace(",", "/").split())
    if not text:
        return []
    return [p.strip() for p in text.split("/") if p.strip()] or [text]


def _color_from_device_field(fields: dict[str, str], wire: str) -> str:
    raw = (fields.get("wire_color") or "").strip()
    if not raw:
        return ""
    token = (wire or "").strip().upper()
    parts = _split_device_colors(raw)
    if not parts:
        return ""
    if token in GROUND_TOKENS:
        for part in parts:
            if "green" in part.lower() or "yellow" in part.lower():
                return part
        return parts[-1] if len(parts) > 1 else parts[0]
    non_ground = [p for p in parts if "green" not in p.lower()]
    return (non_ground or parts)[0]


def resolve_wire_color(
    *,
    project: Project | None = None,
    type_id: str = "",
    fields: dict[str, str] | None = None,
    wire: str = "",
    interview: dict[str, str] | None = None,
    profile: StandardsProfile | None = None,
) -> str:
    fields = fields or {}
    from_field = _color_from_device_field(fields, wire)
    if from_field:
        return from_field
    interview = interview or (project.interview if project else {}) or {}
    role = role_for_wire(type_id, wire, interview)
    if project is not None:
        ctx = get_wiring_context(project)
        colors = ctx.get("wire_colors") or {}
        if role in colors and str(colors[role]).strip():
            return str(colors[role]).strip()
        if role == "interlock" and ctx.get("interlock_color"):
            return str(ctx["interlock_color"]).strip()
    if profile is not None and str(profile.wire_colors.get(role if role != "interlock" else "foreign_voltage", "")).strip():
        key = role if role != "interlock" else "foreign_voltage"
        return str(profile.wire_colors[key]).strip()
    picks = US_COLOR_PICKS.get(role) or US_COLOR_PICKS.get("ungrounded_ac") or ("Black",)
    return picks[0]


def resolve_wire_gauge(
    *,
    project: Project | None = None,
    type_id: str = "",
    fields: dict[str, str] | None = None,
    wire: str = "",
    interview: dict[str, str] | None = None,
) -> str:
    fields = fields or {}
    from_field = (fields.get("wire_gauge") or fields.get("wire_size") or "").strip()
    if from_field:
        return from_field
    interview = interview or (project.interview if project else {}) or {}
    role = role_for_wire(type_id, wire, interview)
    if project is not None:
        ctx = get_wiring_context(project)
        gauges = ctx.get("wire_gauges") or {}
        if role in gauges and str(gauges[role]).strip():
            return str(gauges[role]).strip()
    picks = US_GAUGE_PICKS.get(role) or US_GAUGE_PICKS.get("control_dc") or ("18 AWG",)
    return picks[0]


def conductor_spec(
    project: Project,
    *,
    type_id: str,
    fields: dict[str, str],
    wire: str,
    profile: StandardsProfile | None = None,
) -> dict[str, str]:
    return {
        "wire": (wire or "").strip(),
        "color": resolve_wire_color(
            project=project, type_id=type_id, fields=fields, wire=wire, profile=profile
        ),
        "gauge": resolve_wire_gauge(
            project=project, type_id=type_id, fields=fields, wire=wire
        ),
    }


def _suggest_wire_gauge(type_id: str, interview: dict[str, str], ctx: dict) -> FieldAssist:
    role = color_role(type_id, interview)
    gauges = ctx.get("wire_gauges") or {}
    if role in gauges and str(gauges[role]).strip():
        value = str(gauges[role]).strip()
        why = f"Earlier devices on this cabinet used {value} for this kind of circuit."
    else:
        picks = US_GAUGE_PICKS.get(role) or ("18 AWG",)
        value = picks[0]
        why = (
            f"{value} is a common US industrial panel size for this circuit class. "
            "Confirm against the load and plant standard — this is a design aid, not an ampacity calc."
        )
    picks = US_GAUGE_PICKS.get(role, (value,))
    ordered = (value,) + tuple(p for p in picks if p != value)
    return FieldAssist(field="wire_gauge", value=value, why=why, picks=ordered)

