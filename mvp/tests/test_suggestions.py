"""Suggestions stay deterministic for a fixed shop profile."""

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.standards import copy_profile, default_profile, profile_from_dict, save_standards, load_standards
from cabinet_studio.services.suggestions import (
    fill_blanks,
    is_special,
    remember_acceptance,
    suggest_device,
    suggest_layout,
    suggest_part_types,
    used_wire_numbers,
)


def test_stock_part_and_voltage_heuristic_are_stable():
    library = load_library()
    profile = default_profile()
    project = new_blank_project()
    plc = suggest_device(library, profile, project, "plc", {"control_voltage": "24 VDC"})
    assert plc.catalog_id == "ab-compactlogix-5380"
    assert plc.stock is True
    assert plc.fields["catalog"] == "5069-L306ER"
    assert plc.fields["wire_numbers"] == "W101, W102"
    assert plc.fields["wire_color"] == "Blue"
    assert "PE" in plc.fields["terminal_landings"]

    low = suggest_device(
        library,
        profile,
        project,
        "motor",
        {"supply_voltage": "230 VAC", "control_voltage": "24 VDC"},
    )
    assert low.catalog_id == "motor-nema-1hp"
    assert low.fields["wire_color"] == "Black"
    assert low.fields["wire_numbers"] == "W101, W102, W103, PE"

    high = suggest_device(
        library,
        profile,
        project,
        "motor",
        {"supply_voltage": "480 VAC"},
    )
    assert high.catalog_id == "motor-nema-5hp"

    learned = copy_profile(profile)
    learned.preferred_catalog["motor"] = "motor-iec-4kw"
    chosen = suggest_device(library, learned, project, "motor", {"supply_voltage": "480 VAC"})
    assert chosen.catalog_id == "motor-iec-4kw"
    assert chosen.reason.startswith("Previously accepted")


def test_wire_numbers_skip_numbers_already_on_the_panel():
    library = load_library()
    profile = default_profile()
    project = new_blank_project()
    project.items.append(
        PlacedItem(id="a", library_id=None, type_id="sensor", x=0, y=0, fields={"wire_numbers": "W101, W102"})
    )
    suggestion = suggest_device(
        library,
        profile,
        project,
        "sensor",
        {"control_voltage": "24 VDC"},
    )
    assert suggestion.fields["wire_numbers"] == "W103"
    assert suggestion.fields["wire_color"] == "Blue"
    assert suggestion.catalog_id == "ab-prox-871c"
    assert "BN" in suggestion.fields["terminal_landings"]


def test_shared_pool_does_not_reuse_a_number_inside_one_plan():
    library = load_library()
    profile = default_profile()
    project = new_blank_project()
    used: set[str] = set()
    interview = {"control_voltage": "120 VAC", "duty": "conveyor motor"}
    first = suggest_device(library, profile, project, "estop", interview, used=used)
    second = suggest_device(library, profile, project, "pushbutton", interview, used=used)
    assert first.fields["wire_numbers"] == "W101"
    assert second.fields["wire_numbers"] == "W102"
    assert first.fields["wire_color"] == "Red"
    assert used_wire_numbers(project) == set()


def test_color_override_in_the_profile_is_what_gets_suggested():
    library = load_library()
    profile = default_profile()
    profile.wire_colors["dc_positive"] = "Dark blue"
    project = new_blank_project()
    sensor = suggest_device(library, profile, project, "sensor", {"control_voltage": "24 VDC"})
    assert sensor.fields["wire_color"] == "Dark blue"
    again = suggest_device(library, profile, project, "sensor", {"control_voltage": "24 VDC"})
    assert again.fields == sensor.fields


def test_special_device_does_not_change_the_shop_profile():
    library = load_library()
    profile = default_profile()
    project = new_blank_project()
    suggestion = suggest_device(library, profile, project, "sensor", {"control_voltage": "24 VDC"})
    fields = dict(suggestion.fields)
    fields["nonstandard"] = "Yes"
    fields["wire_color"] = "Orange"
    fields["catalog"] = "SPECIAL-1"
    kept = remember_acceptance(
        profile,
        type_id="sensor",
        library_id=suggestion.catalog_id,
        fields=fields,
        suggestion=suggestion,
    )
    assert kept.preferred_catalog == {}
    assert kept.wire_colors["dc_positive"] == "Blue"
    assert kept.numbering_next == 101
    assert is_special(fields)


def test_accepted_choice_is_remembered():
    library = load_library()
    profile = default_profile()
    project = new_blank_project()
    suggestion = suggest_device(library, profile, project, "sensor", {"control_voltage": "24 VDC"})
    fields = dict(suggestion.fields)
    fields["wire_color"] = "Dark blue"
    updated = remember_acceptance(
        profile,
        type_id="sensor",
        library_id=suggestion.catalog_id,
        fields=fields,
        suggestion=suggestion,
    )
    assert updated.preferred_catalog["sensor"] == "ab-prox-871c"
    assert updated.wire_colors["dc_positive"] == "Dark blue"
    assert updated.numbering_next == 102
    assert profile.preferred_catalog == {}
    edited = dict(fields)
    edited["catalog"] = "CUSTOM-9"
    skipped = remember_acceptance(
        profile,
        type_id="sensor",
        library_id=suggestion.catalog_id,
        fields=edited,
        suggestion=suggestion,
    )
    assert "sensor" not in skipped.preferred_catalog


def test_layout_and_part_list_follow_the_duty():
    motor = suggest_layout({"duty": "Conveyor drive motor"})
    assert motor.layout_id == "small-motor-cabinet"
    skid = suggest_layout({"duty": "Process skid with a valve"})
    assert skid.layout_id == "process-skid-panel"
    plain = suggest_layout({"duty": ""})
    assert plain.layout_id == "compact-machine-station"
    parts = suggest_part_types({"duty": "Detect a part and run a conveyor motor"})
    # Layout part list leads with enclosure + backplate (shell first), then control core.
    assert parts[:3] == ["enclosure", "backplate", "plc"]
    assert "power_supply" in parts and "estop" in parts
    assert "vfd" in parts and "motor" in parts and "sensor" in parts


def test_fill_blanks_keeps_a_human_answer():
    library = load_library()
    suggestion = suggest_device(
        library,
        default_profile(),
        new_blank_project(),
        "valve",
        {"control_voltage": "24 VDC", "duty": "valve"},
    )
    merged = fill_blanks({"tag": "XV9", "wire_color": "", "size": "1/2 in NPT"}, suggestion)
    assert merged["tag"] == "XV9"
    assert merged["wire_color"] == suggestion.fields["wire_color"]
    assert merged["size"] == "1/2 in NPT"
    assert suggestion.catalog_id == "valve-2way-24v"


def test_standards_profile_round_trip(tmp_path):
    profile = default_profile()
    profile.preferred_catalog["plc"] = "ab-micro850"
    profile.numbering_next = 140
    path = tmp_path / "standards_profile.json"
    save_standards(profile, path)
    loaded = load_standards(path)
    assert loaded.preferred_catalog["plc"] == "ab-micro850"
    assert loaded.numbering_next == 140
    assert loaded.wire_colors["equipment_ground"] == "Green"
    assert profile_from_dict(loaded.to_dict()).numbering_prefix == "W"
    assert load_standards(tmp_path / "missing.json").numbering_next == 101
