"""v0.3.6 undo / redo history for ladder edits."""

from __future__ import annotations

from cabinet_studio.services.ladder_history import LadderHistory
from cabinet_studio.services.programming import add_rung, empty_program, program_to_dict


def _p(*coils):
    prog = empty_program()
    for c in coils:
        prog = add_rung(prog, contact_tag="A", coil_tag=c)
    return program_to_dict(prog)


def test_undo_redo_walks_states():
    h = LadderHistory(_p())
    assert not h.can_undo()
    h.record(_p("Y1"), "Add Y1")
    h.record(_p("Y1", "Y2"), "Add Y2")
    assert h.depth() == (2, 0)
    assert h.undo_label() == "Add Y2"
    state = h.undo()
    assert [r["coil_tag"] for r in state["rungs"]] == ["Y1"]
    state = h.undo()
    assert state["rungs"] == []
    assert h.undo() is None
    assert h.redo_label() == "Add Y1"
    state = h.redo()
    assert [r["coil_tag"] for r in state["rungs"]] == ["Y1"]


def test_new_edit_after_undo_drops_redo_branch():
    h = LadderHistory(_p())
    h.record(_p("Y1"))
    h.record(_p("Y1", "Y2"))
    h.undo()
    h.record(_p("Y1", "Y9"), "Add Y9")
    assert not h.can_redo()
    assert [r["coil_tag"] for r in h.current["rungs"]] == ["Y1", "Y9"]


def test_identical_ladder_or_text_only_edits_do_not_add_steps():
    base = _p("Y1")
    h = LadderHistory(base)
    text_edit = dict(base, plc_text="hand typed", text_edited=True)
    assert h.record(text_edit) is False
    assert h.depth() == (0, 0)
    assert h.current["plc_text"] == "hand typed"


def test_history_limit_and_snapshot_isolation():
    h = LadderHistory(_p(), limit=5)
    states = [_p(*[f"Y{i}" for i in range(n)]) for n in range(1, 10)]
    for st in states:
        h.record(st)
    assert h.depth()[0] == 4
    snap = h.current
    snap["rungs"].clear()
    assert h.current["rungs"]  # deep copies, caller mutation does not leak
