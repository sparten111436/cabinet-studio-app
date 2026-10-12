"""Drawing hover popups + educational ladder simulation helpers."""
from __future__ import annotations

from cabinet_studio.services.drawings import (
    CALLOUT_AFTER_SYMBOL,
    ConnectionRow,
    Box,
    box_hover_detail,
    build_sheets,
    render_svg,
)
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.programming import simulation_rung_tags
from cabinet_studio.models.project import PlacedItem, Project


def _tiny_project() -> Project:
    items = [
        PlacedItem(
            id="1",
            library_id="pushbutton",
            type_id="pushbutton",
            x=10,
            y=10,
            fields={
                "tag": "HS_START",
                "description": "Cycle start",
                "wire_numbers": "W108",
                "terminal_landings": "HS_START: +24V NO to DI1",
                "io_address": "Local:1:I.Data.2",
                "io_direction": "DI",
            },
        ),
        PlacedItem(
            id="2",
            library_id="relay",
            type_id="contactor",
            x=40,
            y=10,
            fields={
                "tag": "Place_Relay",
                "description": "ONE shared place output",
                "wire_numbers": "W113",
                "io_address": "Local:2:O.Data.0",
                "io_direction": "DO",
            },
        ),
    ]
    return Project(
        name="Hover Sim",
        template_id="freestyle",
        cabinet_width=1200,
        cabinet_height=900,
        cabinet_label="HOVER",
        items=items,
    )


def test_box_hover_detail_lists_wires_color_gauge_io():
    box = Box(
        key="a",
        tag="Welder_Relay",
        role="device",
        callout="Welder fire / enable relay.",
        lines=[],
        type_id="contactor",
        io_address="Local:2:O.Data.1",
        wires=["W114"],
        landing="coil from DO1",
        connections=[
            ConnectionRow(
                wire="W114",
                from_label="Welder_Relay",
                to_label="DO1",
                color="Blue",
                gauge="18 AWG",
            )
        ],
    )
    tip = box_hover_detail(box)
    assert "Welder_Relay" in tip
    assert "Type:" in tip
    assert "Callout:" in tip
    assert "I/O:" in tip
    assert "W114" in tip
    assert "Blue" in tip
    assert "18 AWG" in tip
    assert "FROM - TO" in tip or "FROM" in tip


def test_schematic_callout_x_uses_after_symbol_gutter():
    library = load_library()
    project = _tiny_project()
    sheets = [s for s in build_sheets(project, library) if s.kind in {"power", "control"}]
    assert sheets
    assert CALLOUT_AFTER_SYMBOL >= 36
    for sheet in sheets:
        svg = render_svg(sheet, project)
        for box in sheet.boxes:
            needle = f'data-tag="{box.tag}"'
            assert needle in svg
            # Sparse shop: coil tags on canvas; other device text is hover-only.
            assert (
                'class="callout"' in svg
                or 'class="device-tag"' in svg
                or 'class="coil-desc"' in svg
                or 'class="hit-target"' in svg
            )


def test_simulation_rung_tags_pulses_place_and_welder():
    rung = {
        "id": "r1",
        "comment": "place",
        "series": [{"tag": "HS_START", "normally_closed": False}],
        "parallel": [],
        "coil_tag": "Place_Relay",
        "coil_negated": False,
    }
    active, pulse = simulation_rung_tags(rung)
    assert "HS_START" in active
    assert "Place_Relay" in active
    assert "Place_Relay" in pulse

    rung2 = {
        "id": "r2",
        "comment": "weld",
        "series": [{"tag": "Arm_Deployed", "normally_closed": False}],
        "parallel": [],
        "coil_tag": "Welder_Relay",
        "coil_negated": False,
    }
    active2, pulse2 = simulation_rung_tags(rung2)
    assert "Welder_Relay" in active2
    assert "Welder_Relay" in pulse2


def test_simulation_status_mentions_place_welder_on():
    """Status strip wording used by ProgrammingViewer._sim_apply_rung."""
    _, pulse = simulation_rung_tags(
        {
            "id": "r",
            "comment": "Place part",
            "series": [{"tag": "HS_START", "normally_closed": False}],
            "parallel": [],
            "coil_tag": "Place_Relay",
            "coil_negated": False,
        }
    )
    assert "Place_Relay" in pulse
    # Mirror viewer ON strip rules
    on_bits = []
    for tag in sorted(pulse):
        upper = tag.upper().replace("-", "_")
        if upper in {"PLACE_RELAY", "PLACE"} or upper.startswith("PLACE_"):
            on_bits.append("Place ON")
        elif upper in {"WELDER_RELAY", "WELDER"} or "WELDER" in upper:
            on_bits.append("Welder ON")
    assert on_bits == ["Place ON"]

    _, pulse2 = simulation_rung_tags(
        {
            "id": "r2",
            "comment": "Weld fire",
            "series": [{"tag": "Arm_Deployed", "normally_closed": False}],
            "parallel": [],
            "coil_tag": "Welder_Relay",
            "coil_negated": False,
        }
    )
    on2 = []
    for tag in sorted(pulse2):
        upper = tag.upper().replace("-", "_")
        if upper in {"PLACE_RELAY", "PLACE"} or upper.startswith("PLACE_"):
            on2.append("Place ON")
        elif upper in {"WELDER_RELAY", "WELDER"} or "WELDER" in upper:
            on2.append("Welder ON")
    assert on2 == ["Welder ON"]
