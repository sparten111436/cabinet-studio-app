"""Short lines drawn on a cabinet tile."""

from __future__ import annotations

from cabinet_studio.models.project import PlacedItem
from cabinet_studio.models.schema import EquipmentType


def tile_text(item: PlacedItem, equipment: EquipmentType) -> tuple[str, str, str]:
    tag = item.fields.get("tag", "").strip() or "UNTAGGED"
    parts: list[str] = []
    for key in equipment.descriptor_keys:
        value = str(item.fields.get(key, "")).strip()
        if value:
            parts.append(value)
    detail = " · ".join(parts[:3]) if parts else "Specs not set"
    return tag, equipment.label, detail
