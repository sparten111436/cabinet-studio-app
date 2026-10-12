"""Load and validate the starter equipment library."""

from __future__ import annotations

import json
from pathlib import Path

from cabinet_studio.models.project import NAMEPLATE_CLEARANCE
from cabinet_studio.models.schema import (
    CatalogItem,
    EquipmentType,
    FieldGroup,
    FieldSpec,
    LayoutPlacement,
    LayoutTemplate,
    Library,
)
from cabinet_studio.services.placement import rects_overlap

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "library"
FIELD_TYPES = {"text", "multiline", "choice"}
EDGE = 12.0


class LibraryError(Exception):
    """The starter library JSON is missing or inconsistent."""


def load_library(path: Path | None = None) -> Library:
    root = Path(path) if path is not None else LIBRARY_DIR
    schema = _read_json(root / "schema.json")
    catalog = _read_json(root / "catalog.json")
    layouts = _read_json(root / "layouts.json")
    return _assemble(schema, catalog, layouts)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LibraryError(f"Missing library file {path.name}.") from exc
    except json.JSONDecodeError as exc:
        raise LibraryError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LibraryError(f"{path.name} must be a JSON object.")
    return data


def _assemble(schema: dict, catalog: dict, layouts: dict) -> Library:
    if schema.get("version") != 1 or catalog.get("version") != 1 or layouts.get("version") != 1:
        raise LibraryError("Library JSON must be version 1.")
    groups = _groups(schema.get("groups"))
    group_ids = [group.id for group in groups]
    common = [_field(raw, "common field") for raw in _list(schema.get("common_fields"), "common_fields")]
    _unique([field.key for field in common], "common field")
    types = tuple(
        _equipment_type(raw, common, group_ids)
        for raw in _list(schema.get("types"), "types")
    )
    _unique([item.id for item in types], "equipment type")
    type_map = {item.id: item for item in types}
    items = tuple(_catalog_item(raw, type_map) for raw in _list(catalog.get("items"), "items"))
    _unique([item.id for item in items], "catalog item")
    catalog_map = {item.id: item for item in items}
    layout_models = tuple(
        _layout(raw, catalog_map, type_map) for raw in _list(layouts.get("layouts"), "layouts")
    )
    _unique([item.id for item in layout_models], "layout")
    _require_vendor_coverage(items, common)
    _require_type_coverage(types, items)
    return Library(
        version=1,
        groups=groups,
        types=types,
        catalog=items,
        layouts=layout_models,
    )


def _groups(raw: object) -> tuple[FieldGroup, ...]:
    groups = []
    for entry in _list(raw, "groups"):
        group_id = _text(entry, "id", "field group")
        groups.append(
            FieldGroup(
                id=group_id,
                title=_text(entry, "title", group_id),
                prompt=_text(entry, "prompt", group_id),
            )
        )
    _unique([group.id for group in groups], "field group")
    if not groups:
        raise LibraryError("Library schema has no field groups.")
    return tuple(groups)


def _equipment_type(raw: dict, common: list[FieldSpec], group_ids: list[str]) -> EquipmentType:
    type_id = _text(raw, "id", "equipment type")
    overrides = raw.get("field_overrides") or {}
    if not isinstance(overrides, dict):
        raise LibraryError(f"{type_id} field_overrides must be an object.")
    common_keys = {field.key for field in common}
    unknown = sorted(set(overrides) - common_keys)
    if unknown:
        raise LibraryError(f"{type_id} overrides unknown fields: {', '.join(unknown)}.")
    resolved_common = [_apply_override(field, overrides.get(field.key), type_id) for field in common]
    own = [_field(entry, type_id) for entry in _list(raw.get("fields"), f"{type_id} fields")]
    _unique([field.key for field in own], f"{type_id} field")
    overlap = sorted({field.key for field in own} & common_keys)
    if overlap:
        raise LibraryError(f"{type_id} repeats common fields: {', '.join(overlap)}.")
    supervised = raw.get("supervised", True)
    if not isinstance(supervised, bool):
        raise LibraryError(f"{type_id} supervised must be true or false.")
    if not supervised:
        resolved_common = [
            _copy_field(field, required=False) if field.group == "plc_io" else field
            for field in resolved_common
        ]
    fields = _order_fields(resolved_common, own, group_ids, type_id)
    descriptors = raw.get("descriptor_keys")
    if not isinstance(descriptors, list) or not descriptors:
        raise LibraryError(f"{type_id} needs descriptor_keys.")
    field_keys = {field.key for field in fields}
    for key in descriptors:
        if not isinstance(key, str) or key not in field_keys:
            raise LibraryError(f"{type_id} descriptor {key!r} is not a field.")
    try:
        tile_w = float(raw["tile_w"])
        tile_h = float(raw["tile_h"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LibraryError(f"{type_id} needs numeric tile_w and tile_h.") from exc
    if tile_w < 40 or tile_h < 40:
        raise LibraryError(f"{type_id} tile is too small.")
    return EquipmentType(
        id=type_id,
        label=_text(raw, "label", type_id),
        category=_text(raw, "category", type_id),
        accent=_text(raw, "accent", type_id),
        supervised=supervised,
        tile_w=tile_w,
        tile_h=tile_h,
        descriptor_keys=tuple(str(key) for key in descriptors),
        fields=tuple(fields),
    )


def _order_fields(
    common: list[FieldSpec],
    own: list[FieldSpec],
    group_ids: list[str],
    type_id: str,
) -> list[FieldSpec]:
    ordered: list[FieldSpec] = []
    for group_id in group_ids:
        ordered.extend(field for field in own if field.group == group_id)
        ordered.extend(field for field in common if field.group == group_id)
    known = set(group_ids)
    stray = [field.key for field in common + own if field.group not in known]
    if stray:
        raise LibraryError(f"{type_id} uses unknown groups on: {', '.join(stray)}.")
    return ordered


def _apply_override(field: FieldSpec, override: object, type_id: str) -> FieldSpec:
    if override is None:
        return field
    if not isinstance(override, dict):
        raise LibraryError(f"{type_id} override for {field.key} must be an object.")
    allowed = {"required", "help", "label", "placeholder"}
    unknown = sorted(set(override) - allowed)
    if unknown:
        raise LibraryError(f"{type_id} override {field.key} has unsupported keys: {', '.join(unknown)}.")
    required = field.required if "required" not in override else override["required"]
    if not isinstance(required, bool):
        raise LibraryError(f"{type_id} override {field.key} required must be true or false.")
    help_text = field.help if "help" not in override else override["help"]
    label = field.label if "label" not in override else override["label"]
    placeholder = field.placeholder if "placeholder" not in override else override["placeholder"]
    if not isinstance(help_text, str) or not help_text.strip():
        raise LibraryError(f"{type_id} override {field.key} needs help text.")
    if not isinstance(label, str) or not label.strip():
        raise LibraryError(f"{type_id} override {field.key} needs a label.")
    if not isinstance(placeholder, str):
        raise LibraryError(f"{type_id} override {field.key} placeholder must be text.")
    return _copy_field(field, required=required, help=help_text.strip(), label=label.strip(), placeholder=placeholder)


def _copy_field(
    field: FieldSpec,
    *,
    required: bool | None = None,
    help: str | None = None,
    label: str | None = None,
    placeholder: str | None = None,
) -> FieldSpec:
    return FieldSpec(
        key=field.key,
        label=field.label if label is None else label,
        type=field.type,
        required=field.required if required is None else required,
        group=field.group,
        help=field.help if help is None else help,
        placeholder=field.placeholder if placeholder is None else placeholder,
        options=field.options,
    )


def _field(raw: object, owner: str) -> FieldSpec:
    if not isinstance(raw, dict):
        raise LibraryError(f"{owner} field must be an object.")
    key = _text(raw, "key", owner)
    field_type = _text(raw, "type", key)
    if field_type not in FIELD_TYPES:
        raise LibraryError(f"{owner} field {key} has unknown type {field_type}.")
    required = raw.get("required")
    if not isinstance(required, bool):
        raise LibraryError(f"{owner} field {key} must set required true or false.")
    options_raw = raw.get("options", [])
    if not isinstance(options_raw, list) or not all(isinstance(option, str) and option.strip() for option in options_raw):
        raise LibraryError(f"{owner} field {key} options must be a list of text.")
    if field_type == "choice" and not options_raw:
        raise LibraryError(f"{owner} field {key} needs choices.")
    if field_type != "choice" and options_raw:
        raise LibraryError(f"{owner} field {key} is not a choice and cannot have options.")
    placeholder = raw.get("placeholder", "")
    if not isinstance(placeholder, str):
        raise LibraryError(f"{owner} field {key} placeholder must be text.")
    return FieldSpec(
        key=key,
        label=_text(raw, "label", key),
        type=field_type,
        required=required,
        group=_text(raw, "group", key),
        help=_text(raw, "help", key),
        placeholder=placeholder,
        options=tuple(options_raw),
    )


def _catalog_item(raw: object, type_map: dict[str, EquipmentType]) -> CatalogItem:
    if not isinstance(raw, dict):
        raise LibraryError("Catalog item must be an object.")
    item_id = _text(raw, "id", "catalog item")
    type_id = _text(raw, "type_id", item_id)
    equipment = type_map.get(type_id)
    if equipment is None:
        raise LibraryError(f"Catalog item {item_id} uses unknown type {type_id}.")
    defaults_raw = raw.get("defaults", {})
    if not isinstance(defaults_raw, dict):
        raise LibraryError(f"Catalog item {item_id} defaults must be an object.")
    field_map = {field.key: field for field in equipment.fields}
    defaults: list[tuple[str, str]] = []
    for key, value in defaults_raw.items():
        if key not in field_map:
            raise LibraryError(f"Catalog item {item_id} default {key} is not a field on {type_id}.")
        if isinstance(value, (dict, list)) or value is None:
            raise LibraryError(f"Catalog item {item_id} default {key} must be a single value.")
        text_value = str(value).strip()
        spec = field_map[key]
        if spec.type == "choice" and text_value and text_value not in spec.options:
            raise LibraryError(
                f"Catalog item {item_id} default {key}={text_value!r} is not an allowed choice."
            )
        defaults.append((key, text_value))
    vendor = _text(raw, "vendor", item_id)
    vendor_field = field_map.get("vendor")
    if vendor_field and vendor not in vendor_field.options:
        raise LibraryError(f"Catalog item {item_id} vendor {vendor!r} is not an allowed choice.")
    default_map = dict(defaults)
    if "vendor" in default_map and default_map["vendor"] != vendor:
        raise LibraryError(f"Catalog item {item_id} vendor does not match its default.")
    source_url = str(raw.get("source_url", "") or "").strip()
    return CatalogItem(
        id=item_id,
        type_id=type_id,
        vendor=vendor,
        name=_text(raw, "name", item_id),
        catalog=_text(raw, "catalog", item_id),
        summary=_text(raw, "summary", item_id),
        defaults=tuple(defaults),
        source_url=source_url,
    )


def _layout(raw: object, catalog_map: dict[str, CatalogItem], type_map: dict[str, EquipmentType]) -> LayoutTemplate:
    if not isinstance(raw, dict):
        raise LibraryError("Layout must be an object.")
    layout_id = _text(raw, "id", "layout")
    try:
        width = float(raw["cabinet_width"])
        height = float(raw["cabinet_height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LibraryError(f"Layout {layout_id} needs cabinet width and height.") from exc
    placements: list[LayoutPlacement] = []
    rects: list[tuple[tuple[float, float, float, float], str]] = []
    tags: list[str] = []
    for entry in _list(raw.get("placements"), f"{layout_id} placements"):
        library_id = _text(entry, "library_id", layout_id)
        catalog = catalog_map.get(library_id)
        if catalog is None:
            raise LibraryError(f"Layout {layout_id} references unknown device {library_id}.")
        equipment = type_map[catalog.type_id]
        try:
            x = float(entry["x"])
            y = float(entry["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LibraryError(f"Layout {layout_id} placement {library_id} needs x and y.") from exc
        tag = _text(entry, "tag", library_id)
        description = _text(entry, "description", tag)
        extra_raw = entry.get("fields", {})
        if not isinstance(extra_raw, dict):
            raise LibraryError(f"Layout {layout_id} placement {tag} fields must be an object.")
        field_map = {field.key: field for field in equipment.fields}
        extra: list[tuple[str, str]] = []
        for key, value in extra_raw.items():
            if key not in field_map:
                raise LibraryError(f"Layout {layout_id} placement {tag} sets unknown field {key}.")
            if isinstance(value, (dict, list)) or value is None:
                raise LibraryError(f"Layout {layout_id} placement {tag} field {key} must be a single value.")
            text_value = str(value).strip()
            spec = field_map[key]
            if spec.type == "choice" and text_value and text_value not in spec.options:
                raise LibraryError(f"Layout {layout_id} placement {tag} field {key} is not an allowed choice.")
            extra.append((key, text_value))
        if y < NAMEPLATE_CLEARANCE:
            raise LibraryError(f"Layout {layout_id} places {tag} on the nameplate.")
        if x < 16 or x + equipment.tile_w > width - EDGE or y + equipment.tile_h > height - EDGE:
            raise LibraryError(f"Layout {layout_id} places {tag} outside the cabinet.")
        rect = (x, y, equipment.tile_w, equipment.tile_h)
        for other, other_tag in rects:
            if rects_overlap(rect, other, pad=PAD_OVERLAP()):
                raise LibraryError(f"Layout {layout_id} places {tag} on top of {other_tag}.")
        rects.append((rect, tag))
        tags.append(tag)
        placements.append(
            LayoutPlacement(
                library_id=library_id,
                x=x,
                y=y,
                tag=tag,
                description=description,
                fields=tuple(extra),
            )
        )
    if len(tags) != len(set(tags)):
        raise LibraryError(f"Layout {layout_id} reuses a tag.")
    if not placements:
        raise LibraryError(f"Layout {layout_id} has no devices.")
    return LayoutTemplate(
        id=layout_id,
        name=_text(raw, "name", layout_id),
        description=_text(raw, "description", layout_id),
        cabinet_width=width,
        cabinet_height=height,
        cabinet_label=_text(raw, "cabinet_label", layout_id),
        placements=tuple(placements),
    )


def PAD_OVERLAP() -> float:
    return 12.0


def _require_vendor_coverage(items: tuple[CatalogItem, ...], common: list[FieldSpec]) -> None:
    vendor_field = next((field for field in common if field.key == "vendor"), None)
    if vendor_field is None:
        raise LibraryError("Common fields must include vendor.")
    present = {item.vendor for item in items}
    missing = [option for option in vendor_field.options if option not in present]
    if missing:
        raise LibraryError("Catalog is missing vendor entries for: " + ", ".join(missing))


def _require_type_coverage(types: tuple[EquipmentType, ...], items: tuple[CatalogItem, ...]) -> None:
    covered = {item.type_id for item in items}
    missing = [item.id for item in types if item.id not in covered]
    if missing:
        raise LibraryError("Catalog is missing items for: " + ", ".join(missing))


def _list(raw: object, name: str) -> list:
    if not isinstance(raw, list):
        raise LibraryError(f"{name} must be a list.")
    return raw


def _text(raw: dict, key: str, owner: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LibraryError(f"{owner} is missing {key}.")
    return value.strip()


def _unique(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise LibraryError(f"Duplicate {label}: {value}.")
        seen.add(value)
