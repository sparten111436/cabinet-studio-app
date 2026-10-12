"""UL 508A design review (advisory).

Rule-of-thumb checks for an industrial control panel. This is not a
certification, a listing, or a substitute for a qualified engineer.
"""

from __future__ import annotations

from dataclasses import dataclass

from cabinet_studio.models.project import Project
from cabinet_studio.models.schema import Library
from cabinet_studio.services.standards import StandardsProfile
from cabinet_studio.services.suggestions import POWER_TYPES, color_role, is_special

DESIGN_AID_DISCLAIMER = (
    "Suggestions and the UL 508A review are design aids, not a substitute "
    "for a qualified engineer or a formal UL evaluation."
)

REVIEW_TITLE = "UL 508A design review (advisory)"


@dataclass(frozen=True)
class Finding:
    check_id: str
    status: str
    title: str
    detail: str
    advisory: bool

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "title": self.title,
            "detail": self.detail,
            "advisory": self.advisory,
        }


def review_ul508a(project: Project, library: Library, profile: StandardsProfile) -> list[Finding]:
    interview = project.interview
    return [
        _disconnect(interview),
        _branch(interview, project),
        _separation(interview),
        _wire_colors(project, profile),
        _grounding(project, interview),
        _enclosure(interview),
        _sccr(interview),
        _motor_overload(project, library),
        _field_wiring(project, interview),
    ]


def _finding(check_id: str, status: str, title: str, detail: str, advisory: bool) -> Finding:
    return Finding(check_id=check_id, status=status, title=title, detail=detail, advisory=advisory)


def _choice(interview: dict[str, str], key: str) -> str:
    return (interview.get(key) or "").strip()


def _disconnect(interview: dict[str, str]) -> Finding:
    value = _choice(interview, "disconnect")
    if value == "Yes":
        return _finding(
            "UL508A-DISC-01",
            "pass",
            "Disconnecting means noted",
            "The interview says a disconnecting means is part of this panel. Confirm the device and its marking on the schematic.",
            True,
        )
    if value == "No":
        return _finding(
            "UL508A-DISC-01",
            "warn",
            "No disconnecting means recorded",
            "UL 508A industrial control panels need a supply disconnect within sight of the panel unless a documented exception applies. This check only reads the interview.",
            True,
        )
    return _finding(
        "UL508A-DISC-01",
        "missing",
        "Disconnecting means not recorded",
        "Say whether the panel includes a supply disconnect. This review does not inspect a drawing.",
        True,
    )


def _branch(interview: dict[str, str], project: Project) -> Finding:
    value = _choice(interview, "branch_protection")
    has_load = any(item.type_id in {"motor", "vfd", "power_supply", "contactor"} for item in project.items)
    if value == "Yes":
        return _finding(
            "UL508A-BCP-01",
            "pass",
            "Branch-circuit protection noted",
            "The interview says branch-circuit protection is provided. Size and SCCR still have to be documented for the real devices.",
            True,
        )
    if value == "No":
        extra = " Power loads are already on the layout." if has_load else ""
        return _finding(
            "UL508A-BCP-01",
            "warn",
            "Branch-circuit protection marked absent",
            "Each branch that feeds a load needs protection sized for the conductors and the load." + extra,
            True,
        )
    return _finding(
        "UL508A-BCP-01",
        "missing",
        "Branch-circuit protection not recorded",
        "Record whether each load branch has a breaker or fuses. This is a reminder, not a calculation.",
        True,
    )


def _separation(interview: dict[str, str]) -> Finding:
    value = _choice(interview, "power_control_separation")
    if value == "Separated in the enclosure":
        return _finding(
            "UL508A-SEP-01",
            "pass",
            "Power and control separation noted",
            "The interview says power and control are separated in the enclosure. Keep that visible in the layout notes.",
            True,
        )
    if value == "Not separated":
        return _finding(
            "UL508A-SEP-01",
            "warn",
            "Power and control are not separated",
            "Power and control conductors that share a wireway need the spacing or barrier the standard calls for. Review the routing before release.",
            True,
        )
    return _finding(
        "UL508A-SEP-01",
        "missing",
        "Power and control separation not recorded",
        "Note whether power and control wiring are separated or share a wireway with a barrier.",
        True,
    )


def _wire_colors(project: Project, profile: StandardsProfile) -> Finding:
    if not project.items:
        return _finding(
            "UL508A-WCLR-01",
            "missing",
            "No conductors to check",
            "Add devices before the color convention can be compared. Grounded conductors stay white or gray. Equipment grounding stays green.",
            False,
        )
    mismatches: list[str] = []
    blanks: list[str] = []
    specials: list[str] = []
    for item in project.items:
        tag = item.fields.get("tag", "").strip() or item.id
        if is_special(item.fields):
            specials.append(tag)
            continue
        role = color_role(item.type_id, project.interview)
        expected = profile.wire_colors.get(role, "").strip()
        actual = item.fields.get("wire_color", "").strip()
        if not actual:
            blanks.append(tag)
            continue
        if expected and expected.lower() not in actual.lower():
            mismatches.append(f"{tag} is {actual}; shop {role.replace('_', ' ')} is {expected}")
        if _ground_color_misuse(actual, role):
            mismatches.append(f"{tag} uses {actual} on a {role.replace('_', ' ')} circuit")
    if blanks or mismatches:
        parts = []
        if blanks:
            parts.append("Missing color: " + ", ".join(blanks) + ".")
        if mismatches:
            parts.append("Off convention: " + "; ".join(mismatches) + ".")
        if specials:
            parts.append("Marked special and skipped: " + ", ".join(specials) + ".")
        status = "missing" if blanks and not mismatches else "warn"
        return _finding(
            "UL508A-WCLR-01",
            status,
            "Wire colors do not follow the shop convention",
            " ".join(parts)
            + " The convention is configurable. Green identifies the equipment ground. White or gray identifies the grounded conductor.",
            False,
        )
    note = "Colors on standard devices match the saved convention."
    if specials:
        note += " Special devices were left out of the comparison: " + ", ".join(specials) + "."
    return _finding("UL508A-WCLR-01", "pass", "Wire colors match the shop convention", note, False)


def _ground_color_misuse(actual: str, role: str) -> bool:
    text = actual.lower()
    if role in {"equipment_ground", "grounded_ac", "dc_negative"}:
        return False
    if text.startswith("green") or text.startswith("white") or text.startswith("gray") or text.startswith("grey"):
        return True
    return False


def _grounding(project: Project, interview: dict[str, str]) -> Finding:
    note = _choice(interview, "grounding")
    weak: list[str] = []
    for item in project.items:
        if item.type_id not in POWER_TYPES | {"plc"}:
            continue
        landings = item.fields.get("terminal_landings", "").strip().lower()
        if not landings:
            continue
        if "pe" not in landings and "ground" not in landings:
            weak.append(item.fields.get("tag", "").strip() or item.id)
    if not note and not weak:
        return _finding(
            "UL508A-GND-01",
            "missing",
            "Grounding and bonding not recorded",
            "Write where the equipment grounding conductor and the panel ground bar bond. This field is a reminder, not a ground-fault study.",
            True,
        )
    if weak:
        return _finding(
            "UL508A-GND-01",
            "warn",
            "Power landings do not mention ground",
            "These devices have landings with no PE or ground reference: " + ", ".join(weak) + ".",
            True,
        )
    return _finding(
        "UL508A-GND-01",
        "pass",
        "Grounding note is present",
        note or "Power landings mention a ground or PE conductor.",
        True,
    )


def _enclosure(interview: dict[str, str]) -> Finding:
    environment = _choice(interview, "environment")
    enclosure = _choice(interview, "enclosure_type")
    if not environment or not enclosure:
        return _finding(
            "UL508A-ENC-01",
            "missing",
            "Enclosure or environment is blank",
            "Record the environment and the enclosure type so the panel matches where it will sit.",
            True,
        )
    if enclosure == "Unspecified":
        return _finding(
            "UL508A-ENC-01",
            "warn",
            "Enclosure type is unspecified",
            f"Environment is {environment}. Pick a NEMA or UL enclosure type before release.",
            True,
        )
    return _finding(
        "UL508A-ENC-01",
        "pass",
        "Enclosure and environment are filled",
        f"{enclosure} for {environment}. Confirm the rating against the real installation.",
        True,
    )


def _sccr(interview: dict[str, str]) -> Finding:
    value = _choice(interview, "sccr")
    if not value:
        return _finding(
            "UL508A-SCCR-01",
            "missing",
            "SCCR documentation is blank",
            "Record the available fault current and the panel SCCR. A placeholder is enough to keep the question from being dropped. This app does not calculate SCCR.",
            True,
        )
    return _finding(
        "UL508A-SCCR-01",
        "pass",
        "SCCR note is present",
        f"Recorded: {value}. This is a documentation field, not a calculated short-circuit rating.",
        True,
    )


def _motor_overload(project: Project, library: Library) -> Finding:
    motors = [item for item in project.items if item.type_id == "motor"]
    if not motors:
        return _finding(
            "UL508A-OVL-01",
            "pass",
            "No motors on this panel",
            "Overload protection is checked when a motor is placed.",
            True,
        )
    missing_fla = [
        item.fields.get("tag", "").strip() or item.id
        for item in motors
        if not item.fields.get("fla", "").strip()
    ]
    if missing_fla:
        return _finding(
            "UL508A-OVL-01",
            "missing",
            "Motor FLA is still open",
            "Overload and branch sizing need the full-load current. Still blank: " + ", ".join(missing_fla) + ".",
            True,
        )
    has_controller = any(item.type_id in {"vfd", "contactor"} for item in project.items)
    if not has_controller:
        return _finding(
            "UL508A-OVL-01",
            "warn",
            "Motor has no drive or contactor on the layout",
            "A motor needs an overload path. Place the VFD or the contactor that carries the overload, or note an external one.",
            True,
        )
    del library
    return _finding(
        "UL508A-OVL-01",
        "pass",
        "Motor FLA and a controller are present",
        "FLA is filled and a VFD or contactor is on the layout. Confirm the overload setting against the nameplate. This is not a trip-curve check.",
        True,
    )


def _field_wiring(project: Project, interview: dict[str, str]) -> Finding:
    value = _choice(interview, "field_wiring")
    field_devices = [
        item
        for item in project.items
        if item.fields.get("mounting", "").strip() == "Field device"
    ]
    unlabeled = [
        item.fields.get("tag", "").strip() or item.id
        for item in field_devices
        if not item.fields.get("terminal_landings", "").strip()
    ]
    if unlabeled:
        return _finding(
            "UL508A-FLD-01",
            "missing",
            "Field devices have no terminal landings",
            "Identify the field-wiring terminals. Still blank: " + ", ".join(unlabeled) + ".",
            False,
        )
    if value == "Identified on a terminal block":
        return _finding(
            "UL508A-FLD-01",
            "pass",
            "Field wiring terminals are identified",
            "The interview says field wiring lands on an identified terminal block.",
            True,
        )
    if value == "Not identified":
        return _finding(
            "UL508A-FLD-01",
            "warn",
            "Field wiring terminals are not identified",
            "Field conductors need identified terminals before the panel is released.",
            True,
        )
    return _finding(
        "UL508A-FLD-01",
        "missing",
        "Field wiring identification not recorded",
        "Say whether incoming field wiring lands on identified terminals.",
        True,
    )
