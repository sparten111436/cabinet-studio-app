"""Deterministic part, landing, wire-number, and color suggestions.

Nothing here writes to a device. The human accepts or edits every value.
A device marked special does not update the shop profile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cabinet_studio.models.project import Project
from cabinet_studio.models.schema import CatalogItem, Library
from cabinet_studio.services.standards import StandardsProfile, copy_profile

POWER_TYPES = {"motor", "vfd", "power_supply", "contactor"}
WIRE_COUNTS = {
    "motor": 3,
    "vfd": 3,
    "contactor": 2,
    "relay": 2,
    "power_supply": 2,
    "plc": 2,
}
LANDINGS = {
    "plc": "Supply + and 0 V on the power terminals; PE to the ground bar",
    "hmi": "24 VDC on the HMI power pins; PE to the ground bar when the unit has one",
    "vfd": "L1 L2 L3 from the branch device; T1 T2 T3 to the motor; PE to the ground bar",
    "motor": "T1 T2 T3 from the drive or contactor; PE to the ground bar",
    "contactor": "L1 L2 L3 line; T1 T2 T3 load; A1 A2 coil",
    "relay": "A1 A2 coil; dry contacts to the controlled circuit",
    "estop": "Contact block to the safety-circuit terminals",
    "ethernet_switch": "24 VDC on the switch power pins",
    "power_supply": "Line L and N on the primary; + and − to the 24 VDC bus; PE to the ground bar",
    "sensor": "BN +24 VDC, BU 0 VDC, BK signal to the PLC input",
    "valve": "Solenoid coil pins to the output and the return",
    "solenoid": "Coil pins to the output and the return",
    "light": "Lamp pins to the output and the return",
    "safety_relay": "A1 A2 supply; safety channel terminals as the catalog shows",
    "transmitter": "Loop + and − to the analog input",
    "io_module": "Field common and points on the module terminals",
    "pushbutton": "Contact block to the PLC input and the return",
    "enclosure": "Shell only — no field landings on the enclosure catalog row",
    "backplate": "Mounting plate inside the enclosure — devices land on this plate",
}
IO_DIRECTION = {
    "sensor": "Input",
    "estop": "Input",
    "pushbutton": "Input",
    "transmitter": "Input",
    "valve": "Output",
    "solenoid": "Output",
    "light": "Output",
    "contactor": "Output",
    "relay": "Output",
    "motor": "Output",
    "safety_relay": "Input and Output",
    "io_module": "Input and Output",
    "plc": "Network / no discrete I/O",
    "hmi": "Network / no discrete I/O",
    "vfd": "Network / no discrete I/O",
    "ethernet_switch": "Network / no discrete I/O",
    "power_supply": "Network / no discrete I/O",
    "enclosure": "Network / no discrete I/O",
    "backplate": "Network / no discrete I/O",
}
TAG_PREFIX = {
    "plc": "PLC",
    "hmi": "HMI",
    "vfd": "VFD",
    "motor": "MTR",
    "contactor": "CON",
    "relay": "CR",
    "estop": "ES",
    "ethernet_switch": "ESW",
    "power_supply": "PSU",
    "sensor": "PX",
    "valve": "XV",
    "solenoid": "SOL",
    "light": "LT",
    "safety_relay": "SR",
    "transmitter": "TT",
    "io_module": "IO",
    "pushbutton": "PB",
    "enclosure": "ENC",
    "backplate": "BP",
    "light_curtain": "LC",
    "breaker": "CB",
    "disconnect": "DS",
    "motor_protector": "MP",
    "fuse_holder": "FU",
    "terminal_block": "TB",
    "transformer": "TR",
}
MOTOR_BY_SUPPLY = (
    (("230", "240"), "motor-nema-1hp"),
    (("400", "380"), "motor-iec-4kw"),
)


@dataclass(frozen=True)
class DeviceSuggestion:
    type_id: str
    catalog_id: str | None
    stock: bool
    reason: str
    wire_role: str
    fields: dict[str, str]


@dataclass(frozen=True)
class LayoutSuggestion:
    layout_id: str
    reason: str


def is_special(fields: dict[str, str]) -> bool:
    return fields.get("nonstandard", "").strip().lower() in {"yes", "y", "true", "special"}


def suggest_layout(interview: dict[str, str]) -> LayoutSuggestion:
    duty = (interview.get("duty") or "").lower()
    if any(word in duty for word in ("skid", "process", "valve", "transmitter", "analog")):
        return LayoutSuggestion("process-skid-panel", "The duty mentions a process skid or field instruments.")
    if any(word in duty for word in ("motor", "conveyor", "drive", "pump", "vfd")):
        return LayoutSuggestion("small-motor-cabinet", "The duty mentions a motor or a drive.")
    return LayoutSuggestion("compact-machine-station", "A compact machine station fits until the duty says otherwise.")


def suggest_part_types(interview: dict[str, str]) -> list[str]:
    duty = (interview.get("duty") or "").lower()
    types = ["enclosure", "backplate", "plc", "power_supply", "estop"]
    if any(word in duty for word in ("motor", "conveyor", "pump", "drive", "vfd")):
        types.extend(["vfd", "motor"])
    if any(word in duty for word in ("valve", "solenoid")):
        types.append("valve")
    if any(word in duty for word in ("sensor", "prox", "photo", "detect")):
        types.append("sensor")
    if any(word in duty for word in ("hmi", "screen", "operator")):
        types.append("hmi")
    if any(word in duty for word in ("safety", "guard", "light curtain")):
        types.append("safety_relay")
    if any(word in duty for word in ("ethernet", "network")):
        types.append("ethernet_switch")
    if "start" in duty:
        types.append("pushbutton")
    seen: set[str] = set()
    ordered: list[str] = []
    for type_id in types:
        if type_id not in seen:
            seen.add(type_id)
            ordered.append(type_id)
    return ordered


def color_role(type_id: str, interview: dict[str, str]) -> str:
    control = (interview.get("control_voltage") or "").lower()
    control_is_dc = "vdc" in control or "dc" in control
    if type_id in {"motor", "vfd", "power_supply"}:
        return "ungrounded_ac"
    if type_id == "contactor":
        return "control_dc" if control_is_dc else "control_ac"
    if type_id in {"estop", "pushbutton", "safety_relay", "light", "relay"}:
        return "control_dc" if control_is_dc else "control_ac"
    if type_id in {"sensor", "transmitter", "solenoid", "valve", "plc", "hmi", "ethernet_switch", "io_module"}:
        return "dc_positive" if control_is_dc or not control else "control_ac"
    return "ungrounded_ac"


def used_wire_numbers(project: Project, *, skip_item_id: str | None = None) -> set[str]:
    found: set[str] = set()
    for item in project.items:
        if item.id == skip_item_id:
            continue
        found.update(_tokens(item.fields.get("wire_numbers", "")))
    return found


def suggest_device(
    library: Library,
    profile: StandardsProfile,
    project: Project,
    type_id: str,
    interview: dict[str, str],
    *,
    tag: str | None = None,
    used: set[str] | None = None,
    skip_item_id: str | None = None,
) -> DeviceSuggestion:
    catalog, stock, reason = _choose_catalog(library, profile, type_id, interview)
    equipment = library.types[type_id]
    fields = {spec.key: "" for spec in equipment.fields}
    if catalog is not None:
        fields.update(catalog.default_map())
        fields["vendor"] = catalog.vendor
        fields["catalog"] = catalog.catalog
        fields["description"] = catalog.summary
    else:
        fields["description"] = equipment.label
    chosen_tag = (tag or "").strip() or _next_tag(project, type_id)
    fields["tag"] = chosen_tag
    role = color_role(type_id, interview)
    fields["wire_color"] = profile.wire_colors.get(role, "")
    landing = LANDINGS.get(type_id, "Land each conductor on the device terminals and the ground bar")
    fields["terminal_landings"] = f"{chosen_tag}: {landing}"
    pool = set(used) if used is not None else used_wire_numbers(project, skip_item_id=skip_item_id)
    numbers = _allocate_numbers(profile, pool, WIRE_COUNTS.get(type_id, 1))
    if type_id in POWER_TYPES:
        numbers = [*numbers, "PE"]
    fields["wire_numbers"] = ", ".join(numbers)
    direction = IO_DIRECTION.get(type_id, "")
    if direction:
        fields["io_direction"] = direction
    fields["nonstandard"] = "No"
    # Keep wire numbers from the shared pool above. Assist fills PLC/IP continuity.
    from cabinet_studio.services.wiring_assist import apply_assist_values, suggest_all_fields

    assists = suggest_all_fields(
        project,
        library,
        profile,
        type_id,
        prior=fields,
        interview=interview,
    )
    if assists.get("wire_color") and assists["wire_color"].value:
        fields["wire_color"] = assists["wire_color"].value
    if assists.get("terminal_landings") and assists["terminal_landings"].value:
        if not str(fields.get("terminal_landings", "")).strip():
            fields["terminal_landings"] = assists["terminal_landings"].value
    continuity = {
        k: assists[k]
        for k in ("io_address", "ip_address", "parent_tag", "slot", "slot_count", "protocol")
        if k in assists
    }
    fields = apply_assist_values(fields, continuity, only_blank=True)
    if used is not None:
        used.update(_tokens(fields.get("wire_numbers", "")))
    return DeviceSuggestion(
        type_id=type_id,
        catalog_id=None if catalog is None else catalog.id,
        stock=stock,
        reason=reason,
        wire_role=role,
        fields=fields,
    )


def fill_blanks(current: dict[str, str], suggestion: DeviceSuggestion) -> dict[str, str]:
    """Keep answers the human already typed. Fill only empty fields."""
    merged = dict(current)
    for key, value in suggestion.fields.items():
        if not str(merged.get(key, "")).strip() and str(value).strip():
            merged[key] = value
    return merged


def remember_acceptance(
    profile: StandardsProfile,
    *,
    type_id: str,
    library_id: str | None,
    fields: dict[str, str],
    suggestion: DeviceSuggestion | None,
) -> StandardsProfile:
    """Learn a choice the human kept. A special device does not change the shop profile."""
    if is_special(fields):
        return profile
    updated = copy_profile(profile)
    if suggestion is not None and library_id:
        suggested_catalog = suggestion.fields.get("catalog", "").strip()
        if suggested_catalog and fields.get("catalog", "").strip() == suggested_catalog:
            updated.preferred_catalog[type_id] = library_id
    color = fields.get("wire_color", "").strip()
    role = suggestion.wire_role if suggestion is not None else ""
    if color and role:
        updated.wire_colors[role] = color
    highest = _highest_sequence(updated, fields.get("wire_numbers", ""))
    if highest >= updated.numbering_next:
        updated.numbering_next = highest + 1
    return updated


def _choose_catalog(
    library: Library,
    profile: StandardsProfile,
    type_id: str,
    interview: dict[str, str],
) -> tuple[CatalogItem | None, bool, str]:
    preferred_id = profile.preferred_catalog.get(type_id, "")
    preferred = library.catalog_by_id.get(preferred_id) if preferred_id else None
    if preferred is not None and preferred.type_id == type_id:
        return preferred, preferred.id in profile.stock_catalog_ids, "Previously accepted shop part."
    heuristic_id = _heuristic_catalog_id(type_id, interview)
    if heuristic_id:
        item = library.catalog_by_id.get(heuristic_id)
        if item is not None and item.type_id == type_id:
            return item, True, "Shop stock part chosen for this supply."
    for catalog_id in profile.stock_catalog_ids:
        item = library.catalog_by_id.get(catalog_id)
        if item is not None and item.type_id == type_id:
            return item, True, "Shop stock part from the starter library."
    for item in library.catalog:
        if item.type_id == type_id:
            return item, False, "First starter-library part. Not marked as shop stock."
    return None, False, "No starter part for this class. Fill the catalog by hand."


def _heuristic_catalog_id(type_id: str, interview: dict[str, str]) -> str | None:

    if type_id == "enclosure":
        sel = (interview.get("enclosure_selection") or "").lower()
        if "saginaw" in sel and "30" in sel:
            return "saginaw-sce-30x24x12"
        if "saginaw" in sel:
            return "saginaw-sce-36x30x12"
        if "hammond" in sel and "30" in sel:
            return "hammond-en4sd302412"
        if "hammond" in sel:
            return "hammond-en4sd363012"
        if "30×24" in sel or "30x24" in sel:
            return "hoffman-a302412lp"
        return "hoffman-a363012lp"
    if type_id == "backplate":
        sel = (interview.get("enclosure_selection") or "").lower()
        if "saginaw" in sel and "30" in sel:
            return "saginaw-sce-30p24"
        if "saginaw" in sel:
            return "saginaw-sce-36p30"
        if "hammond" in sel and "30" in sel:
            return "hammond-ep3024"
        if "hammond" in sel:
            return "hammond-ep3630"
        if "30×24" in sel or "30x24" in sel:
            return "hoffman-a30p24"
        return "hoffman-a36p30"
    if type_id != "motor":
        return None
    supply = interview.get("supply_voltage", "")
    for needles, catalog_id in MOTOR_BY_SUPPLY:
        if any(needle in supply for needle in needles):
            return catalog_id
    return "motor-nema-5hp"


def _next_tag(project: Project, type_id: str) -> str:
    prefix = TAG_PREFIX.get(type_id, type_id[:3].upper())
    taken = {
        item.fields.get("tag", "").strip().upper()
        for item in project.items
        if item.type_id == type_id
    }
    number = 1
    while f"{prefix}{number}".upper() in taken:
        number += 1
    return f"{prefix}{number}"


def _allocate_numbers(profile: StandardsProfile, used: set[str], count: int) -> list[str]:
    numbers: list[str] = []
    cursor = profile.numbering_next
    guard = 0
    while len(numbers) < count and guard < 10000:
        guard += 1
        label = f"{profile.numbering_prefix}{cursor:0{profile.numbering_width}d}"
        cursor += 1
        if label.upper() in used or label.upper() == "PE":
            continue
        numbers.append(label)
    return numbers


def _tokens(raw: str) -> set[str]:
    return {part.upper() for part in re.split(r"[,;\s]+", raw) if part.strip()}


def _highest_sequence(profile: StandardsProfile, raw: str) -> int:
    pattern = re.compile(rf"{re.escape(profile.numbering_prefix)}(\d+)", re.IGNORECASE)
    highest = 0
    for match in pattern.finditer(raw or ""):
        highest = max(highest, int(match.group(1)))
    return highest


def enrich_with_wiring_assist(
    library: Library,
    profile: StandardsProfile,
    project: Project,
    type_id: str,
    fields: dict[str, str],
    *,
    interview: dict[str, str] | None = None,
) -> dict[str, str]:
    """Fill blank wiring / PLC fields from the shared assist engine."""
    from cabinet_studio.services.wiring_assist import apply_assist_values, suggest_all_fields

    assists = suggest_all_fields(
        project,
        library,
        profile,
        type_id,
        prior=fields,
        interview=interview or project.interview,
    )
    return apply_assist_values(fields, assists, only_blank=True)

