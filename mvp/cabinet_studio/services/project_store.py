"""Save and load a cabinet project as JSON."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cabinet_studio.models.project import (
    DEFAULT_BACKPLATE_HEIGHT_IN,
    DEFAULT_BACKPLATE_WIDTH_IN,
    DEFAULT_ENCLOSURE_HEIGHT_IN,
    DEFAULT_ENCLOSURE_WIDTH_IN,
    PlacedItem,
    Project,
)

FORMAT = "cabinet-studio-project"
VERSION = 1


class ProjectError(Exception):
    """The file is not a Cabinet Studio project this build can read."""


def project_to_dict(project: Project) -> dict:
    return project.to_dict()


def project_from_dict(data: dict) -> Project:
    if not isinstance(data, dict):
        raise ProjectError("Project file must be a JSON object.")
    if data.get("format") != FORMAT:
        raise ProjectError("This file is not a Cabinet Studio project.")
    if data.get("version") != VERSION:
        raise ProjectError(
            f"Unsupported project version {data.get('version')!r}. This build reads version {VERSION}."
        )
    cabinet = data.get("cabinet")
    if not isinstance(cabinet, dict):
        raise ProjectError("Project is missing the cabinet block.")
    try:
        width = float(cabinet["width"])
        height = float(cabinet["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectError("Cabinet width and height must be numbers.") from exc
    label = cabinet.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ProjectError("Cabinet label is missing.")
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        raise ProjectError("Project items must be a list.")
    items: list[PlacedItem] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items, start=1):
        items.append(_item_from_dict(raw, index, seen))
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProjectError("Project name is missing.")
    template_id = data.get("template_id")
    if template_id is not None and not isinstance(template_id, str):
        raise ProjectError("template_id must be a string or null.")
    subtitle = data.get("subtitle", "")
    notes = data.get("notes", "")
    if not isinstance(subtitle, str) or not isinstance(notes, str):
        raise ProjectError("Subtitle and notes must be strings.")
    try:
        from cabinet_studio.services.programming import program_from_dict

        program = program_from_dict(data.get("program"))
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc
    wiring_context = data.get("wiring_context") or {}
    if wiring_context is None:
        wiring_context = {}
    if not isinstance(wiring_context, dict):
        raise ProjectError("wiring_context must be an object.")
    # Also accept legacy carry-forward parked inside program.
    if not wiring_context and isinstance(program, dict):
        legacy = program.get("wiring_context")
        if isinstance(legacy, dict):
            wiring_context = legacy
    def _inch(key: str, default: float) -> float:
        raw = cabinet.get(key, default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    enclosure_width_in = _inch("enclosure_width_in", DEFAULT_ENCLOSURE_WIDTH_IN)
    enclosure_height_in = _inch("enclosure_height_in", DEFAULT_ENCLOSURE_HEIGHT_IN)
    backplate_width_in = _inch("backplate_width_in", DEFAULT_BACKPLATE_WIDTH_IN)
    backplate_height_in = _inch("backplate_height_in", DEFAULT_BACKPLATE_HEIGHT_IN)
    maker = cabinet.get("enclosure_maker", "")
    catalog = cabinet.get("enclosure_catalog", "")
    if not isinstance(maker, str):
        maker = ""
    if not isinstance(catalog, str):
        catalog = ""

    return Project(
        name=name.strip(),
        template_id=template_id,
        cabinet_width=width,
        cabinet_height=height,
        cabinet_label=label.strip(),
        subtitle=subtitle,
        notes=notes,
        interview=_interview_from_dict(data.get("interview")),
        program=program,
        wiring_context=wiring_context,
        items=items,
        enclosure_width_in=enclosure_width_in,
        enclosure_height_in=enclosure_height_in,
        backplate_width_in=backplate_width_in,
        backplate_height_in=backplate_height_in,
        enclosure_maker=maker.strip(),
        enclosure_catalog=catalog.strip(),
    )


def _interview_from_dict(raw: object) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProjectError("Interview answers must be an object.")
    interview: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ProjectError("Interview field names must be text.")
        if isinstance(value, (dict, list)):
            raise ProjectError(f"Interview field {key} must be a single value.")
        interview[key] = "" if value is None else str(value)
    return interview


def _item_from_dict(raw: object, index: int, seen: set[str]) -> PlacedItem:
    if not isinstance(raw, dict):
        raise ProjectError(f"Item {index} is not an object.")
    item_id = raw.get("id")
    type_id = raw.get("type_id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ProjectError(f"Item {index} is missing an id.")
    if item_id in seen:
        raise ProjectError(f"Duplicate item id {item_id}.")
    seen.add(item_id)
    if not isinstance(type_id, str) or not type_id.strip():
        raise ProjectError(f"Item {index} is missing a type_id.")
    library_id = raw.get("library_id")
    if library_id is not None and not isinstance(library_id, str):
        raise ProjectError(f"Item {item_id} has an invalid library_id.")
    try:
        x = float(raw["x"])
        y = float(raw["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectError(f"Item {item_id} is missing a numeric position.") from exc
    fields_raw = raw.get("fields", {})
    if not isinstance(fields_raw, dict):
        raise ProjectError(f"Item {item_id} fields must be an object.")
    fields: dict[str, str] = {}
    for key, value in fields_raw.items():
        if not isinstance(key, str):
            raise ProjectError(f"Item {item_id} has a non-text field name.")
        if isinstance(value, (dict, list)):
            raise ProjectError(f"Item {item_id} field {key} must be a single value.")
        fields[key] = "" if value is None else str(value)
    return PlacedItem(
        id=item_id,
        library_id=library_id,
        type_id=type_id,
        x=x,
        y=y,
        fields=fields,
    )


def save_project(project: Project, path: Path | str) -> None:
    target = Path(path)
    payload = project_to_dict(project)
    payload["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_project(path: Path | str) -> Project:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectError(f"Project file not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{target.name} is not valid JSON.") from exc
    return project_from_dict(data)
