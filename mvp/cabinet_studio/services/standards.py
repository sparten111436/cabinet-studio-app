"""Shop standards memory. Accepted parts and colors stick until marked special."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = "cabinet-studio-standards"
VERSION = 1

# Shop colors aligned with common UL 508A conductor identification.
# Green or green/yellow is the equipment ground. White or gray is the
# grounded AC conductor. These defaults are editable and are not a listing.
DEFAULT_WIRE_COLORS: dict[str, str] = {
    "equipment_ground": "Green",
    "grounded_ac": "White",
    "ungrounded_ac": "Black",
    "control_ac": "Red",
    "control_dc": "Blue",
    "dc_positive": "Blue",
    "dc_negative": "White/Blue",
    "foreign_voltage": "Yellow",
}

# Starter parts the shop reaches for first. Order is the preference order.
DEFAULT_STOCK: tuple[str, ...] = (
    "ab-compactlogix-5380",
    "ab-panelview-5310",
    "ab-powerflex-525",
    "motor-nema-5hp",
    "motor-nema-1hp",
    "motor-iec-4kw",
    "ab-contactor-100c",
    "ab-estop-800t",
    "ab-stratix-2000",
    "ab-1606-xls",
    "ab-prox-871c",
    "valve-2way-24v",
    "solenoid-24vdc",
    "ab-stack-855e",
    "ab-guardmaster-msr127",
    "tx-pressure-4-20",
    "ab-5069-ib16",
    "ab-pb-green-start",
)


class StandardsError(Exception):
    """The standards profile on disk cannot be read."""


@dataclass
class StandardsProfile:
    wire_colors: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_WIRE_COLORS))
    numbering_prefix: str = "W"
    numbering_next: int = 101
    numbering_width: int = 3
    preferred_catalog: dict[str, str] = field(default_factory=dict)
    stock_catalog_ids: tuple[str, ...] = DEFAULT_STOCK

    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "version": VERSION,
            "wire_colors": dict(self.wire_colors),
            "numbering": {
                "prefix": self.numbering_prefix,
                "next": self.numbering_next,
                "width": self.numbering_width,
            },
            "preferred_catalog": dict(self.preferred_catalog),
            "stock_catalog_ids": list(self.stock_catalog_ids),
        }


def default_profile() -> StandardsProfile:
    return StandardsProfile()


def copy_profile(profile: StandardsProfile) -> StandardsProfile:
    return StandardsProfile(
        wire_colors=dict(profile.wire_colors),
        numbering_prefix=profile.numbering_prefix,
        numbering_next=profile.numbering_next,
        numbering_width=profile.numbering_width,
        preferred_catalog=dict(profile.preferred_catalog),
        stock_catalog_ids=tuple(profile.stock_catalog_ids),
    )


def profile_from_dict(data: dict) -> StandardsProfile:
    if not isinstance(data, dict):
        raise StandardsError("Standards profile must be a JSON object.")
    if data.get("format") != FORMAT:
        raise StandardsError("This file is not a Cabinet Studio standards profile.")
    if data.get("version") != VERSION:
        raise StandardsError(f"Unsupported standards profile version {data.get('version')!r}.")
    colors = dict(DEFAULT_WIRE_COLORS)
    raw_colors = data.get("wire_colors") or {}
    if not isinstance(raw_colors, dict):
        raise StandardsError("wire_colors must be an object.")
    for key, value in raw_colors.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            colors[key] = value.strip()
    numbering = data.get("numbering") or {}
    if not isinstance(numbering, dict):
        raise StandardsError("numbering must be an object.")
    prefix = numbering.get("prefix", "W")
    if not isinstance(prefix, str) or not prefix.strip():
        raise StandardsError("Wire number prefix must be text.")
    try:
        nxt = int(numbering.get("next", 101))
        width = int(numbering.get("width", 3))
    except (TypeError, ValueError) as exc:
        raise StandardsError("Wire numbering next and width must be integers.") from exc
    preferred: dict[str, str] = {}
    raw_preferred = data.get("preferred_catalog") or {}
    if not isinstance(raw_preferred, dict):
        raise StandardsError("preferred_catalog must be an object.")
    for key, value in raw_preferred.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            preferred[key] = value.strip()
    raw_stock = data.get("stock_catalog_ids", list(DEFAULT_STOCK))
    if not isinstance(raw_stock, list) or not all(isinstance(item, str) for item in raw_stock):
        raise StandardsError("stock_catalog_ids must be a list of ids.")
    stock = tuple(raw_stock) if raw_stock else DEFAULT_STOCK
    return StandardsProfile(
        wire_colors=colors,
        numbering_prefix=prefix.strip(),
        numbering_next=max(1, nxt),
        numbering_width=max(1, width),
        preferred_catalog=preferred,
        stock_catalog_ids=stock,
    )


def load_standards(path: Path | str) -> StandardsProfile:
    target = Path(path)
    if not target.is_file():
        return default_profile()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StandardsError(f"{target.name} is not valid JSON.") from exc
    return profile_from_dict(data)


def save_standards(profile: StandardsProfile, path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")
