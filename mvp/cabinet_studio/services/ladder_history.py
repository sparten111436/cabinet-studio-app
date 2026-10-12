"""Undo / redo history for Programming ladder edits (v0.3.6).

Session-only snapshot stack (every modern editor has one — Studio 5000, CCW,
TIA, CODESYS). Snapshots are deep copies of ``program_to_dict`` output.
Text-only edits (hand-typed PLC/HMI text) do not create undo steps; only
changes to the ladder itself (rungs / answers / HMI items / tag descriptions) do.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

DEFAULT_LIMIT = 100


def _ladder_key(snapshot: dict[str, Any] | None) -> str:
    data = snapshot or {}
    try:
        return json.dumps(
            {
                "rungs": data.get("rungs") or [],
                "answers": data.get("answers") or {},
                "hmi_items": data.get("hmi_items") or [],
                # v0.3.7: tag description edits are undoable too.
                "tag_descriptions": data.get("tag_descriptions") or {},
            },
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError):
        return repr(data.get("rungs"))


class LadderHistory:
    """Linear undo/redo stack with de-duplication of identical ladder states."""

    def __init__(self, initial: dict[str, Any] | None = None, *, limit: int = DEFAULT_LIMIT) -> None:
        self.limit = max(2, int(limit))
        self._states: list[dict[str, Any]] = []
        self._labels: list[str] = []
        self._pos = -1
        self.reset(initial or {})

    def reset(self, snapshot: dict[str, Any], label: str = "Open") -> None:
        self._states = [deepcopy(snapshot)]
        self._labels = [label]
        self._pos = 0

    @property
    def current(self) -> dict[str, Any]:
        return deepcopy(self._states[self._pos])

    def record(self, snapshot: dict[str, Any], label: str = "Edit") -> bool:
        """Push a new state after an edit. Returns False when the ladder did not change."""
        if _ladder_key(snapshot) == _ladder_key(self._states[self._pos]):
            # Keep latest plc_text etc. without creating a new step.
            self._states[self._pos] = deepcopy(snapshot)
            return False
        del self._states[self._pos + 1 :]
        del self._labels[self._pos + 1 :]
        self._states.append(deepcopy(snapshot))
        self._labels.append(label or "Edit")
        if len(self._states) > self.limit:
            drop = len(self._states) - self.limit
            del self._states[:drop]
            del self._labels[:drop]
        self._pos = len(self._states) - 1
        return True

    def can_undo(self) -> bool:
        return self._pos > 0

    def can_redo(self) -> bool:
        return self._pos < len(self._states) - 1

    def undo(self) -> dict[str, Any] | None:
        if not self.can_undo():
            return None
        self._pos -= 1
        return self.current

    def redo(self) -> dict[str, Any] | None:
        if not self.can_redo():
            return None
        self._pos += 1
        return self.current

    def undo_label(self) -> str:
        return self._labels[self._pos] if self.can_undo() else ""

    def redo_label(self) -> str:
        return self._labels[self._pos + 1] if self.can_redo() else ""

    def depth(self) -> tuple[int, int]:
        """(undo steps available, redo steps available)."""
        return self._pos, len(self._states) - 1 - self._pos
