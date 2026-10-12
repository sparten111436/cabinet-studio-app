"""Blank cabinets and layout templates."""

from __future__ import annotations

import uuid

from cabinet_studio.models.project import (
    DEFAULT_CABINET_HEIGHT,
    DEFAULT_CABINET_WIDTH,
    PlacedItem,
    Project,
)
from cabinet_studio.models.schema import LayoutTemplate, Library


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def new_blank_project(name: str = "Untitled cabinet") -> Project:
    return Project(
        name=name,
        template_id=None,
        cabinet_width=DEFAULT_CABINET_WIDTH,
        cabinet_height=DEFAULT_CABINET_HEIGHT,
        cabinet_label="PNL1",
        subtitle="Blank panel. Add every device the PLC will supervise, then fill the open fields.",
        notes="",
        items=[],
    )


def _blank_fields(library: Library, type_id: str) -> dict[str, str]:
    equipment = library.types[type_id]
    return {spec.key: "" for spec in equipment.fields}


def instantiate_layout(layout: LayoutTemplate, library: Library, name: str | None = None) -> Project:
    items: list[PlacedItem] = []
    for placement in layout.placements:
        catalog = library.catalog_by_id[placement.library_id]
        fields = _blank_fields(library, catalog.type_id)
        fields.update(catalog.default_map())
        fields.update(placement.field_map())
        fields["vendor"] = catalog.vendor
        fields["catalog"] = catalog.catalog
        fields["tag"] = placement.tag
        fields["description"] = placement.description
        items.append(
            PlacedItem(
                id=new_id(),
                library_id=catalog.id,
                type_id=catalog.type_id,
                x=placement.x,
                y=placement.y,
                fields=fields,
            )
        )
    return Project(
        name=name or layout.name,
        template_id=layout.id,
        cabinet_width=layout.cabinet_width,
        cabinet_height=layout.cabinet_height,
        cabinet_label=layout.cabinet_label,
        subtitle=layout.description,
        notes="",
        items=items,
    )
