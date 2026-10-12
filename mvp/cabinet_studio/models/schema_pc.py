"""Equipment schema types loaded from the starter library."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldGroup:
    id: str
    title: str
    prompt: str


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: str
    required: bool
    group: str
    help: str
    placeholder: str = ""
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class EquipmentType:
    id: str
    label: str
    category: str
    accent: str
    supervised: bool
    tile_w: float
    tile_h: float
    descriptor_keys: tuple[str, ...]
    fields: tuple[FieldSpec, ...]


@dataclass(frozen=True)
class CatalogItem:
    id: str
    type_id: str
    vendor: str
    name: str
    catalog: str
    summary: str
    defaults: tuple[tuple[str, str], ...]
    # Public Rockwell/AB (or maker) product page used to verify the catalog number.
    # Empty means this catalog string has not been verified for outline callouts.
    source_url: str = ""

    def default_map(self) -> dict[str, str]:
        return dict(self.defaults)


@dataclass(frozen=True)
class LayoutPlacement:
    library_id: str
    x: float
    y: float
    tag: str
    description: str
    fields: tuple[tuple[str, str], ...] = ()

    def field_map(self) -> dict[str, str]:
        return dict(self.fields)


@dataclass(frozen=True)
class LayoutTemplate:
    id: str
    name: str
    description: str
    cabinet_width: float
    cabinet_height: float
    cabinet_label: str
    placements: tuple[LayoutPlacement, ...]


class Library:
    """In-memory equipment library. Treat the contents as read-only."""

    def __init__(
        self,
        version: int,
        groups: tuple[FieldGroup, ...],
        types: tuple[EquipmentType, ...],
        catalog: tuple[CatalogItem, ...],
        layouts: tuple[LayoutTemplate, ...],
    ) -> None:
        self.version = version
        self.groups = groups
        self.group_by_id = {group.id: group for group in groups}
        self.types = {item.id: item for item in types}
        self.catalog = catalog
        self.catalog_by_id = {item.id: item for item in catalog}
        self.layouts = layouts
        self.layout_by_id = {item.id: item for item in layouts}

    def type_list(self) -> list[EquipmentType]:
        return list(self.types.values())
