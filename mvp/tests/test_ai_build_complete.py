"""AI build places a complete, drawable, programmable cabinet."""

from cabinet_studio.services.ai_build import (
    apply_recommendations,
    interview_from_ai_answers,
    project_name_from_answers,
    recommend_devices,
)
from cabinet_studio.services.completeness import missing_specs
from cabinet_studio.services.drawings import build_sheets
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.programming import build_starter_program
from cabinet_studio.services.standards import default_profile


def test_ai_build_cabinet_is_complete_with_schematics_and_ladder():
    library = load_library()
    profile = default_profile()
    answers = {
        "duty": "conveyor that moves boxes",
        "supply_voltage": "480 VAC",
        "control_voltage": "24 VDC",
        "has_motor": "Yes",
        "start_stop": "Both",
        "has_estop": "Yes",
        "has_hmi": "Yes",
        "project_name": "Complete line",
    }
    recs = recommend_devices(library, profile, answers)
    project = new_blank_project(project_name_from_answers(answers))
    project.interview = interview_from_ai_answers(answers)
    apply_recommendations(library, project, recs, profile=profile)
    assert len(project.items) >= 5
    for item in project.items:
        missing = missing_specs(item.fields, library.types[item.type_id].fields)
        assert not missing, f"{item.type_id} still open: {[s.key for s in missing]}"
        assert item.fields.get("wire_numbers")
        assert item.fields.get("terminal_landings")
        assert item.fields.get("io_address")
    # Sequential inputs and distinct Ethernet placeholders.
    ips = [item.fields.get("ip_address") for item in project.items if item.fields.get("ip_address")]
    assert len(ips) == len(set(ips))
    sheets = build_sheets(project, library)
    kinds = {sheet.kind for sheet in sheets}
    assert {"layout", "power", "control"} <= kinds
    program = build_starter_program(
        project,
        {
            "on_start": "Start runs the motor",
            "on_stop": "Stop opens the rung",
            "on_estop": "E-stop must stop the motor",
            "direction": "Forward only",
            "hmi_show": "Start, Stop, and Running",
        },
    )
    assert program["rungs"]
    assert project.wiring_context.get("parent_plc_tag") == "PLC1"
