# -*- coding: utf-8 -*-
"""Wiring assist carry-forward: colors, wire numbers, parent PLC."""

from cabinet_studio.models.project import PlacedItem
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.standards import default_profile
from cabinet_studio.services.suggestions import suggest_device
from cabinet_studio.services.wiring_assist import (
    apply_all_project_suggestions,
    get_wiring_context,
    remember_device_fields,
    remember_field_choice,
    suggest_field,
    suggest_all_fields,
)


def test_wire_color_reused_from_project_context():
    library = load_library()
    profile = default_profile()
    project = new_blank_project("Color continuity")
    project.interview = {"control_voltage": "24 VDC", "supply_voltage": "480 VAC"}
    first = suggest_device(library, profile, project, "sensor", project.interview)
    assert first.fields["wire_color"] == "Blue"
    project.items.append(
        PlacedItem(
            id="s1",
            library_id=first.catalog_id,
            type_id="sensor",
            x=0,
            y=0,
            fields=dict(first.fields),
        )
    )
    remember_device_fields(
        project, profile, type_id="sensor", fields=first.fields, interview=project.interview
    )
    ctx = get_wiring_context(project)
    assert ctx["wire_colors"].get("dc_positive") == "Blue"
    # Human changes color on first device — next sensor should follow.
    first.fields["wire_color"] = "Dark blue"
    project.items[0].fields["wire_color"] = "Dark blue"
    remember_field_choice(
        project,
        profile,
        type_id="sensor",
        field_key="wire_color",
        value="Dark blue",
        interview=project.interview,
    )
    second = suggest_field(
        project,
        library,
        profile,
        type_id="sensor",
        field_key="wire_color",
        interview=project.interview,
    )
    assert second.value == "Dark blue"
    assert "Dark blue" in second.why or "consistent" in second.why.lower() or "Earlier" in second.why


def test_wire_numbers_increment_across_devices():
    library = load_library()
    profile = default_profile()
    project = new_blank_project("Wire numbers")
    project.interview = {"control_voltage": "24 VDC"}
    used: set[str] = set()
    first = suggest_device(library, profile, project, "estop", project.interview, used=used)
    assert first.fields["wire_numbers"] == "W101"
    project.items.append(
        PlacedItem(id="e1", library_id=None, type_id="estop", x=0, y=0, fields=dict(first.fields))
    )
    remember_device_fields(
        project, profile, type_id="estop", fields=first.fields, interview=project.interview
    )
    second = suggest_device(library, profile, project, "pushbutton", project.interview, used=used)
    assert second.fields["wire_numbers"] == "W102"
    # Assist field suggestion also advances from context after remember.
    assist = suggest_field(
        project,
        library,
        profile,
        type_id="pushbutton",
        field_key="wire_numbers",
        interview=project.interview,
    )
    assert "W102" in assist.value or "W103" in assist.value


def test_parent_plc_tag_reused_for_io_module():
    library = load_library()
    profile = default_profile()
    project = new_blank_project("PLC parent")
    project.interview = {"control_voltage": "24 VDC"}
    plc = suggest_device(library, profile, project, "plc", project.interview)
    assert plc.fields["tag"] == "PLC1"
    project.items.append(
        PlacedItem(
            id="p1",
            library_id=plc.catalog_id,
            type_id="plc",
            x=0,
            y=0,
            fields=dict(plc.fields),
        )
    )
    remember_device_fields(
        project, profile, type_id="plc", fields=plc.fields, interview=project.interview
    )
    ctx = get_wiring_context(project)
    assert ctx["parent_plc_tag"] == "PLC1"
    parent = suggest_field(
        project,
        library,
        profile,
        type_id="io_module",
        field_key="parent_tag",
        interview=project.interview,
    )
    assert parent.value == "PLC1"
    assert "PLC1" in parent.picks


def test_io_address_and_ip_placeholders():
    library = load_library()
    profile = default_profile()
    project = new_blank_project("IO IP")
    project.interview = {"control_voltage": "24 VDC"}
    sensor = suggest_device(library, profile, project, "sensor", project.interview)
    assert sensor.fields["io_address"].startswith("Local:")
    assert "I.Data" in sensor.fields["io_address"]
    plc = suggest_device(library, profile, project, "plc", project.interview)
    assert plc.fields["ip_address"].startswith("192.168.")
    ip = suggest_field(
        project, library, profile, type_id="plc", field_key="ip_address", interview=project.interview
    )
    assert "placeholder" in ip.why.lower() or "plant network" in ip.why.lower()


def test_suggest_all_fields_covers_wiring_keys():
    library = load_library()
    profile = default_profile()
    project = new_blank_project("All fields")
    project.interview = {"control_voltage": "24 VDC", "supply_voltage": "480 VAC"}
    assists = suggest_all_fields(project, library, profile, "contactor", interview=project.interview)
    for key in ("wire_color", "wire_numbers", "terminal_landings", "io_direction", "io_address"):
        assert key in assists
        assert assists[key].value
        assert assists[key].why
    assert "A1" in assists["terminal_landings"].value or "coil" in assists["terminal_landings"].value.lower()


def test_wiring_context_round_trips_in_project_json(tmp_path):
    from cabinet_studio.services.project_store import load_project, save_project

    library = load_library()
    profile = default_profile()
    project = new_blank_project("Persist ctx")
    project.interview = {"control_voltage": "24 VDC"}
    sensor = suggest_device(library, profile, project, "sensor", project.interview)
    project.items.append(
        PlacedItem(id="s1", library_id=None, type_id="sensor", x=10, y=10, fields=dict(sensor.fields))
    )
    remember_device_fields(
        project, profile, type_id="sensor", fields=sensor.fields, interview=project.interview
    )
    path = tmp_path / "ctx.cabinet.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.wiring_context.get("wire_colors", {}).get("dc_positive") == sensor.fields["wire_color"]


def test_apply_all_project_suggestions_fills_blanks_with_carry_forward():
    library = load_library()
    profile = default_profile()
    project = new_blank_project("Apply all")
    project.interview = {"control_voltage": "24 VDC", "supply_voltage": "480 VAC"}
    # Bare devices with only tags — assist should fill wiring/I/O blanks.
    project.items = [
        PlacedItem(id="p1", library_id=None, type_id="plc", x=0, y=0, fields={"tag": "PLC1"}),
        PlacedItem(id="s1", library_id=None, type_id="sensor", x=40, y=0, fields={"tag": "PX1"}),
        PlacedItem(id="e1", library_id=None, type_id="estop", x=80, y=0, fields={"tag": "ES1"}),
    ]
    profile, changed, filled = apply_all_project_suggestions(
        project, library, profile, only_blank=True
    )
    assert changed >= 1
    assert filled >= 1
    # Carry-forward: later devices get wire numbers after earlier ones.
    numbers = [item.fields.get("wire_numbers", "") for item in project.items]
    assert any(numbers)
    # Existing values are preserved.
    project.items[0].fields["tag"] = "PLC1"
    before_tag = project.items[0].fields["tag"]
    profile, _c, _f = apply_all_project_suggestions(project, library, profile, only_blank=True)
    assert project.items[0].fields["tag"] == before_tag
