"""New build with AI uses library catalogs only; never invents numbers."""

from cabinet_studio.services.ai_build import (
    CATALOG_NOT_IDENTIFIED,
    ab_catalog_for_type,
    apply_recommendations,
    interview_from_ai_answers,
    interview_suggestion,
    project_name_from_answers,
    recommend_devices,
    recommend_type_ids,
)
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.standards import default_profile


def test_recommend_types_follow_answers():
    answers = {
        "duty": "conveyor that moves boxes",
        "supply_voltage": "480 VAC",
        "control_voltage": "24 VDC",
        "has_motor": "Yes",
        "motor_control": "VFD (variable speed)",
        "start_stop": "Both",
        "operator_devices": "Start pushbutton|Stop pushbutton|Selector switch (HOA)|Run indicator light",
        "has_control_relays": "Yes — add control relays",
        "has_estop": "Yes",
        "has_safety_relay": "Yes",
        "has_hmi": "Yes",
        "project_name": "Line 3 feeder",
    }
    types = recommend_type_ids(answers)
    assert types[0] == "plc"
    assert "motor" in types
    assert "vfd" in types
    assert "estop" in types
    assert "hmi" in types
    assert "pushbutton" in types
    assert "relay" in types
    assert "safety_relay" in types
    assert "light" in types


def test_recommendations_prefer_ab_and_never_invent():
    library = load_library()
    profile = default_profile()
    answers = {
        "duty": "pump skid",
        "supply_voltage": "480 VAC",
        "control_voltage": "24 VDC",
        "has_motor": "Yes",
        "motor_control": "VFD (variable speed)",
        "start_stop": "Pushbuttons",
        "operator_devices": "Start pushbutton|Stop pushbutton",
        "has_control_relays": "Yes — add control relays",
        "has_estop": "Yes",
        "has_safety_relay": "Not sure (AI will suggest)",
        "has_hmi": "No",
        "project_name": "Pump skid A",
    }
    recs = recommend_devices(library, profile, answers)
    by_type = {rec.type_id: rec for rec in recs}
    assert by_type["plc"].catalog_number == "5069-L306ER"
    assert by_type["plc"].catalog_id == "ab-compactlogix-5380"
    assert by_type["estop"].catalog_number == "800T-FXJT6A"
    # Motor has no Allen-Bradley entry in the starter library.
    assert by_type["motor"].catalog_number == CATALOG_NOT_IDENTIFIED
    assert by_type["motor"].catalog_id is None
    assert by_type["motor"].suggestion.fields["catalog"] == CATALOG_NOT_IDENTIFIED
    pb_keys = [rec.key for rec in recs if rec.type_id == "pushbutton"]
    assert "pb_start" in pb_keys
    assert "pb_stop" in pb_keys
    assert any(rec.type_id == "relay" for rec in recs)
    for rec in recs:
        if rec.catalog_id:
            item = library.catalog_by_id[rec.catalog_id]
            assert rec.catalog_number == item.catalog
            assert "allen" in item.vendor.lower()
        else:
            assert rec.catalog_number == CATALOG_NOT_IDENTIFIED


def test_apply_recommendations_places_library_parts():
    library = load_library()
    profile = default_profile()
    answers = {
        "duty": "small station",
        "supply_voltage": "480 VAC",
        "control_voltage": "24 VDC",
        "has_motor": "No",
        "motor_control": "No motor",
        "start_stop": "Pushbuttons",
        "operator_devices": "Start pushbutton|Stop pushbutton",
        "has_control_relays": "No",
        "has_estop": "Yes",
        "has_safety_relay": "Yes",
        "has_hmi": "No",
        "project_name": "Station 1",
    }
    recs = recommend_devices(library, profile, answers)
    project = new_blank_project(project_name_from_answers(answers))
    project.interview = interview_from_ai_answers(answers)
    apply_recommendations(library, project, recs)
    assert project.name == "Station 1"
    assert len(project.items) >= 3
    assert any(item.type_id == "plc" for item in project.items)
    plc = next(item for item in project.items if item.type_id == "plc")
    assert plc.library_id == "ab-compactlogix-5380"
    assert plc.fields["catalog"] == "5069-L306ER"
    starts = [i for i in project.items if i.type_id == "pushbutton" and i.fields.get("function") == "Start"]
    stops = [i for i in project.items if i.type_id == "pushbutton" and i.fields.get("function") == "Stop"]
    assert starts and stops


def test_ab_catalog_helper():
    library = load_library()
    assert ab_catalog_for_type(library, "plc").id == "ab-compactlogix-5380"
    assert ab_catalog_for_type(library, "motor") is None
    # v0.3.28 adds Allen-Bradley 700-H relays; rows without a verified source page stay
    # flagged (empty source_url) so outline callouts never claim a verified number.
    relay = ab_catalog_for_type(library, "relay")
    assert relay is not None and relay.id == "ab-relay-700ha" and relay.source_url == ""


def test_interview_suggestion_mentions_buttons():
    tip = interview_suggestion(
        {"start_stop": "Pushbuttons", "has_motor": "Yes"},
        "operator_devices",
    )
    assert "Start" in tip or "pushbutton" in tip.lower()


def test_library_has_relay_type():
    library = load_library()
    assert "relay" in library.types
    assert any(item.type_id == "relay" for item in library.catalog)
