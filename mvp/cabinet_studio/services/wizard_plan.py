"""Group wizard questions by equipment class. Every supervised type is included."""

from __future__ import annotations

from collections.abc import Sequence

from cabinet_studio.models.schema import FieldGroup, FieldSpec


def fields_by_group(
    groups: Sequence[FieldGroup],
    fields: Sequence[FieldSpec],
) -> list[tuple[FieldGroup, list[FieldSpec]]]:
    steps: list[tuple[FieldGroup, list[FieldSpec]]] = []
    for group in groups:
        grouped = [field for field in fields if field.group == group.id]
        if grouped:
            steps.append((group, grouped))
    return steps
