"""Application interview: what the cabinet has to do before parts are locked in."""

from __future__ import annotations

INTERVIEW_FIELDS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("duty", "What the system must do", "text", ()),
    (
        "supply_voltage",
        "Supply voltage",
        "choice",
        ("480 VAC", "240 VAC", "240 VAC 3-phase", "220 VAC", "208 VAC", "120 VAC", "24 VDC", "Other"),
    ),
    (
        "control_voltage",
        "Control voltage",
        "choice",
        ("120 VAC", "24 VDC", "24 VAC", "Other"),
    ),
    (
        "environment",
        "Environment",
        "choice",
        ("Indoor dry", "Indoor dusty", "Outdoor", "Washdown", "Hazardous (unspecified)"),
    ),
    (
        "enclosure_type",
        "Enclosure type",
        "choice",
        ("NEMA 1", "NEMA 12", "NEMA 4", "NEMA 4X", "NEMA 3R", "Unspecified"),
    ),
    (
        "enclosure_selection",
        "Enclosure brand and size",
        "choice",
        (
            "Hoffman 36×30×12 (A363012LP + A36P30)",
            "Hoffman 30×24×12 (A302412LP + A30P24)",
            "Hoffman 24×24×8 (A242408LP + A24P24)",
            "Saginaw 36×30×12 (SCE-36X30X12 + SCE-36P30)",
            "Saginaw 30×24×12 (SCE-30X24X12 + SCE-30P24)",
            "Hammond Eclipse 36×30×12 (EN4SD363012 + EP3630)",
            "Hammond Eclipse 30×24×12 (EN4SD302412 + EP3024)",
            "Other / not decided",
        ),
    ),
    ("grounding", "Grounding / bonding notes", "text", ()),
    ("sccr", "SCCR / short-circuit documentation", "text", ()),
    (
        "disconnect",
        "Disconnecting means",
        "choice",
        ("Yes", "No", "Not decided"),
    ),
    (
        "branch_protection",
        "Branch-circuit protection",
        "choice",
        ("Yes", "No", "Not decided"),
    ),
    (
        "power_control_separation",
        "Power and control separation",
        "choice",
        ("Separated in the enclosure", "Not separated", "Not decided"),
    ),
    (
        "field_wiring",
        "Field wiring terminals",
        "choice",
        ("Identified on a terminal block", "Not identified", "Not decided"),
    ),
)


def blank_interview() -> dict[str, str]:
    return {key: "" for key, _label, _kind, _options in INTERVIEW_FIELDS}
