"""Required-field checks. Incomplete devices stay flagged on the layout."""

from __future__ import annotations

from collections.abc import Sequence

from cabinet_studio.models.project import Project
from cabinet_studio.models.schema import FieldSpec, Library


def missing_specs(fields: dict[str, str], specs: Sequence[FieldSpec]) -> list[FieldSpec]:
    missing: list[FieldSpec] = []
    for spec in specs:
        if not spec.required:
            continue
        if not str(fields.get(spec.key, "")).strip():
            missing.append(spec)
    return missing


def is_complete(fields: dict[str, str], specs: Sequence[FieldSpec]) -> bool:
    return not missing_specs(fields, specs)


def project_definition_status(project: Project, library: Library) -> tuple[int, int]:
    """Return (placed devices, devices that still have required fields open)."""
    open_count = 0
    for item in project.items:
        equipment = library.types.get(item.type_id)
        if equipment is None or not is_complete(item.fields, equipment.fields):
            open_count += 1
    return len(project.items), open_count
