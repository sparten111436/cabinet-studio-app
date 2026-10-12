"""Projects round-trip through JSON, and completeness follows the schema."""

import json

import pytest

from cabinet_studio.services.completeness import is_complete, missing_specs, project_definition_status
from cabinet_studio.services.layouts import instantiate_layout, new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.placement import next_free_position, rects_overlap, tile_size
from cabinet_studio.services.project_store import (
    ProjectError,
    load_project,
    project_from_dict,
    project_to_dict,
    save_project,
)


def test_blank_project_round_trip(tmp_path):
    project = new_blank_project("Empty panel")
    project.notes = "Leave room for a second drive."
    project.interview = {"duty": "Index a conveyor", "enclosure_type": "NEMA 12"}
    path = tmp_path / "empty.cabinet.json"
    save_project(project, path)
    loaded = load_project(path)
    assert project_to_dict(loaded) == project_to_dict(project)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format"] == "cabinet-studio-project"
    assert raw["version"] == 1
    assert "saved_at" in raw


def test_template_project_round_trip_keeps_positions_and_answers(tmp_path):
    library = load_library()
    project = instantiate_layout(library.layout_by_id["small-motor-cabinet"], library, "Line 2 MCC")
    project.notes = "Torque on MTR1 is application-specific."
    motor = next(item for item in project.items if item.fields["tag"] == "MTR1")
    motor.x = 40
    motor.y = 320
    motor.fields["torque"] = "22 lb-ft"
    motor.fields["notes"] = "Confirm heater size"
    motor.fields["io_address"] = "Local:2:O.Data.0"
    path = tmp_path / "line2.cabinet.json"
    save_project(project, path)
    loaded = load_project(path)
    assert project_to_dict(loaded) == project_to_dict(project)
    loaded_motor = next(item for item in loaded.items if item.fields["tag"] == "MTR1")
    assert loaded_motor.x == 40
    assert loaded_motor.y == 320
    assert loaded_motor.fields["torque"] == "22 lb-ft"
    assert loaded_motor.library_id == "motor-nema-5hp"
    assert loaded_motor.type_id == "motor"


def test_motor_stays_flagged_until_its_required_fields_are_filled():
    library = load_library()
    project = instantiate_layout(library.layout_by_id["small-motor-cabinet"], library)
    motor = next(item for item in project.items if item.type_id == "motor")
    specs = library.types["motor"].fields
    missing = {spec.key for spec in missing_specs(motor.fields, specs)}
    assert {"torque", "fla", "pinout", "terminal_landings", "wire_numbers", "io_direction", "io_address"} <= missing
    assert not is_complete(motor.fields, specs)
    for spec in specs:
        if spec.required and not motor.fields.get(spec.key, "").strip():
            motor.fields[spec.key] = "set"
    assert is_complete(motor.fields, specs)
    _total, open_count = project_definition_status(project, library)
    assert open_count >= 1
    for item in project.items:
        equipment = library.types[item.type_id]
        for spec in equipment.fields:
            if spec.required and not item.fields.get(spec.key, "").strip():
                item.fields[spec.key] = "set"
    assert project_definition_status(project, library) == (len(project.items), 0)


def test_sensor_valve_and_plc_questions_are_type_specific():
    library = load_library()
    sensor = {field.key for field in library.types["sensor"].fields}
    valve = {field.key for field in library.types["valve"].fields}
    plc = {field.key for field in library.types["plc"].fields}
    assert {"sensor_kind", "signal", "range_span", "wiring_style"} <= sensor
    assert {"size", "solenoid_voltage", "ports"} <= valve
    assert {"ip_address", "slot_count", "protocol"} <= plc
    assert "horsepower" not in sensor
    assert "pinout" not in plc


def test_next_free_position_does_not_cover_a_template_tile():
    library = load_library()
    project = instantiate_layout(library.layout_by_id["compact-machine-station"], library)
    x, y = next_free_position(project, library, "sensor")
    tile_w, tile_h = tile_size(library, "sensor")
    proposed = (x, y, tile_w, tile_h)
    for item in project.items:
        other = tile_size(library, item.type_id)
        assert not rects_overlap(proposed, (item.x, item.y, other[0], other[1]), pad=8)


def test_rejects_a_project_from_a_future_version(tmp_path):
    path = tmp_path / "future.cabinet.json"
    path.write_text(json.dumps({"format": "cabinet-studio-project", "version": 99}), encoding="utf-8")
    with pytest.raises(ProjectError):
        load_project(path)


def test_rejects_a_file_that_is_not_a_project(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(ProjectError):
        load_project(path)


def test_from_dict_ignores_unknown_metadata():
    project = new_blank_project("Meta")
    payload = project_to_dict(project)
    payload["saved_at"] = "2026-09-22T00:00:00+00:00"
    payload["extra"] = {"ignored": True}
    loaded = project_from_dict(payload)
    assert loaded.name == "Meta"
    assert loaded.items == []
