"""v0.3.23 UI phase 2: organizer, palette, properties, wizard, project explorer; prints still byte-identical."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("customtkinter")

from cabinet_studio import __version__
from cabinet_studio.services.ladder_ir import program_to_ladder_ir
from cabinet_studio.services.programming import program_from_dict
from cabinet_studio.services.plcopen_xml import export_program_to_plcopen_xml, import_plcopen_xml_to_program_checked

from tests.test_ui_v0322 import (  # noqa: F401  (re-run the theme-proof print check under this release)
    _prefs,
    test_prints_and_exports_are_byte_identical_and_white_in_every_theme,
)

NEW_MODULES = (
    "cabinet_studio.ui.prefs",
    "cabinet_studio.ui.shell.treeview",
    "cabinet_studio.ui.shell.project_explorer",
    "cabinet_studio.ui.studio",
    "cabinet_studio.ui.studio.organizer",
    "cabinet_studio.ui.studio.palette",
    "cabinet_studio.ui.studio.properties",
    "cabinet_studio.ui.studio.program_wizard",
)


def test_version_is_0323():
    assert tuple(int(p) for p in __version__.split(".")) >= (0, 3, 23)


def test_new_modules_import():
    import importlib

    for mod in NEW_MODULES:
        importlib.import_module(mod)


def test_two_operand_compare_drops_stray_c_and_round_trips():
    prog = {
        "name": "Cmp",
        "rungs": [{"id": "r1", "elements": [
            {"kind": "compare", "op": "EQU", "source_a": "N1", "source_b": "5", "source_c": "9"},
            {"kind": "coil", "tag": "Y1"},
        ]}],
    }
    ir = program_to_ladder_ir(program_from_dict(prog))
    cmp_el = next(e for e in ir["rungs"][0]["elements"] if e.get("kind") == "compare")
    assert "source_c" not in cmp_el
    xml = export_program_to_plcopen_xml(prog, project_name="Cmp")
    back = import_plcopen_xml_to_program_checked(xml)
    back_prog = back[0] if isinstance(back, tuple) else back
    assert program_to_ladder_ir(program_from_dict(back_prog))["rungs"][0]["elements"] == ir["rungs"][0]["elements"]


def test_new_modules_are_in_the_0323_spec():
    here = Path(__file__).resolve()
    candidates = [p / "builds" / "CabinetStudio-0.3.23.spec" for p in (here.parents[2], here.parents[3])]
    spec = next((p for p in candidates if p.exists()), candidates[0])
    if not spec.exists():
        pytest.skip("spec is created at freeze time")
    text = spec.read_text(encoding="utf-8")
    for mod in NEW_MODULES:
        assert f"'{mod}'" in text or f'"{mod}"' in text, mod
