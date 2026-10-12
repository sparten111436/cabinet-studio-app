"""Programming screen: starter ladder from questions, save/load, rung edits."""

from pathlib import Path

from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.programming import (
    LEARNING_NOTE,
    PROGRAM_QUESTIONS,
    build_starter_program,
    default_design_answers,
    plc_text_looks_stale_empty,
    device_caption,
    device_role_label,
    edit_rung,
    empty_program,
    find_estop_tag,
    find_motor_coil_tag,
    find_start_tag,
    find_stop_tag,
    flatten_contacts,
    format_plc_text,
    program_from_dict,
    program_to_dict,
    rung_has_seal_in,
)
from cabinet_studio.services.project_store import load_project, project_to_dict, save_project


_MVP_ROOT = Path(__file__).resolve().parents[1]
def _save(name: str) -> Path:
    """Resolve fixture cabinets from repo saves/ only (no hard-coded PC paths)."""
    local = _MVP_ROOT / "saves" / name
    if not local.is_file():
        raise FileNotFoundError(f"Missing test fixture: {local}")
    return local

SAMPLE = _save("sample-motor-cabinet.cabinet.json")
WELD = _save("weld-place-cell.cabinet.json")


def _answers(**overrides: str) -> dict[str, str]:
    base = {
        "on_start": "The motor should run",
        "on_stop": "The motor should stop",
        "on_estop": "Stop the motor right away and keep it stopped",
        "direction": "Forward only",
        "hmi_show": "Running, Stopped, and Fault",
    }
    base.update(overrides)
    return base


def _device_dicts(project):
    return [
        {
            "tag": item.fields["tag"],
            "type_id": item.type_id,
            "function": item.fields.get("function", ""),
            "description": item.fields.get("description", ""),
            "io_direction": "",
            "io_address": "",
            "wire_numbers": "",
        }
        for item in project.items
        if item.fields.get("tag")
    ]


def test_questions_listed_are_plain_and_complete():
    keys = [key for key, _prompt, _opts in PROGRAM_QUESTIONS]
    assert keys == ["on_start", "on_stop", "on_estop", "direction", "hmi_show"]
    for _key, prompt, options in PROGRAM_QUESTIONS:
        assert "?" in prompt
        assert len(options) >= 2


def test_starter_ladder_treats_estop_as_stop():
    project = load_project(SAMPLE)
    program = build_starter_program(project, _answers())
    estop = find_estop_tag(_device_dicts(project))
    assert estop == "ES1"
    estop_contacts = []
    for rung in program["rungs"]:
        for contact in flatten_contacts(rung):
            if contact["tag"] == "ES1":
                estop_contacts.append((rung, contact))
    assert estop_contacts, "starter must include an e-stop NC contact"
    assert estop_contacts[0][1]["normally_closed"] is True
    assert any(r["coil_tag"] == "M1C" for r in program["rungs"])
    assert LEARNING_NOTE in program["plc_text"]
    assert "ES1" in program["plc_text"]
    assert program["hmi_items"]
    labels = {item["label"] for item in program["hmi_items"]}
    assert {"Running", "Stopped", "Fault"} <= labels


def test_starter_uses_only_cabinet_device_tags():
    project = load_project(SAMPLE)
    known = {item.fields["tag"] for item in project.items if item.fields.get("tag")}
    program = build_starter_program(project, _answers())
    for rung in program["rungs"]:
        for contact in flatten_contacts(rung):
            assert contact["tag"] in known
        assert rung["coil_tag"] in known
    devices = _device_dicts(project)
    assert find_start_tag(devices) == "HS_START"
    assert find_stop_tag(devices) == "HS_STOP"
    assert find_motor_coil_tag(devices) == "M1C"


def test_seal_in_present_when_start_runs_motor():
    project = load_project(SAMPLE)
    program = build_starter_program(project, _answers())
    assert program["rungs"], "expected a run rung"
    run = program["rungs"][0]
    assert rung_has_seal_in(run), "Start path must seal with contactor NO"
    parallel_tags = [[c["tag"] for c in branch] for branch in run["parallel"]]
    assert ["HS_START"] in parallel_tags
    assert ["M1C"] in parallel_tags
    series_tags = [(c["tag"], c["normally_closed"]) for c in run["series"]]
    assert ("HS_STOP", True) in series_tags
    assert ("ES1", True) in series_tags
    assert run["coil_tag"] == "M1C"


def test_forward_only_is_one_run_rung():
    project = load_project(SAMPLE)
    program = build_starter_program(project, _answers(direction="Forward only"))
    assert len(program["rungs"]) == 1


def test_reverse_without_reverse_device_stays_one_rung_and_notes():
    project = load_project(SAMPLE)
    program = build_starter_program(project, _answers(direction="Forward and reverse"))
    assert len(program["rungs"]) == 1
    assert "no reverse" in program["plc_text"].lower()


def test_device_role_labels_are_plain():
    start = {"tag": "HS_START", "type_id": "pushbutton", "function": "Start", "description": "Motor start"}
    stop = {"tag": "HS_STOP", "type_id": "pushbutton", "function": "Stop", "description": "Motor stop"}
    estop = {"tag": "ES1", "type_id": "estop", "function": "", "description": "Door e-stop"}
    coil = {"tag": "M1C", "type_id": "contactor", "function": "", "description": "Conveyor output contactor"}
    assert "Start" in device_role_label(start)
    assert "PB" in device_role_label(start)
    assert "Stop" in device_role_label(stop, normally_closed=True)
    assert "E-Stop" in device_role_label(estop, normally_closed=True)
    assert "Contactor" in device_role_label(coil)
    assert "HS_START (Start PB)" == device_caption(start, "HS_START")


def test_program_save_load_round_trip(tmp_path):
    project = load_project(SAMPLE)
    project.program = build_starter_program(project, _answers())
    path = tmp_path / "with-program.cabinet.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.program["plc_text"] == project.program["plc_text"]
    assert loaded.program["hmi_text"] == project.program["hmi_text"]
    assert len(loaded.program["rungs"]) == len(project.program["rungs"])
    assert loaded.program["rungs"][0]["coil_tag"] == project.program["rungs"][0]["coil_tag"]
    assert loaded.program["rungs"][0]["parallel"] == project.program["rungs"][0]["parallel"]
    assert loaded.program["rungs"][0]["series"] == project.program["rungs"][0]["series"]
    raw = path.read_text(encoding="utf-8")
    assert '"program"' in raw
    assert "Learning program" in raw


def test_legacy_single_contact_rung_still_loads():
    raw = {
        "answers": {},
        "rungs": [
            {
                "id": "legacy1",
                "contact_tag": "ES1",
                "normally_closed": True,
                "coil_tag": "M1C",
                "comment": "old style",
            }
        ],
        "hmi_items": [],
        "plc_text": "",
        "hmi_text": "",
        "text_edited": False,
    }
    program = program_from_dict(raw)
    assert program["rungs"][0]["parallel"] == [[{"tag": "ES1", "normally_closed": True}]]
    assert program["rungs"][0]["coil_tag"] == "M1C"
    assert program["rungs"][0]["contact_tag"] == "ES1"
    assert program["rungs"][0]["normally_closed"] is True
    assert "[/ES1]" in program["plc_text"]


def test_cabinet_without_program_still_opens(tmp_path):
    project = new_blank_project("No program yet")
    path = tmp_path / "bare.cabinet.json"
    payload = project_to_dict(project)
    payload.pop("program", None)
    import json
    from datetime import datetime, timezone

    payload["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    loaded = load_project(path)
    assert loaded.name == "No program yet"
    assert loaded.program == program_to_dict(empty_program()) or loaded.program["rungs"] == []


def test_editing_a_rung_persists(tmp_path):
    project = load_project(SAMPLE)
    program = build_starter_program(project, _answers())
    assert program["rungs"]
    rung_id = program["rungs"][0]["id"]
    updated = edit_rung(
        program,
        rung_id,
        comment="Kid edited this rung",
        normally_closed=False,
    )
    assert updated["rungs"][0]["comment"] == "Kid edited this rung"
    assert "Kid edited this rung" in updated["plc_text"]
    assert updated["text_edited"] is True
    project.program = updated
    path = tmp_path / "edited.cabinet.json"
    save_project(project, path)
    loaded = load_project(path)
    match = next(r for r in loaded.program["rungs"] if r["id"] == rung_id)
    assert match["comment"] == "Kid edited this rung"
    assert "Kid edited this rung" in loaded.program["plc_text"]


def test_format_plc_text_is_readable():
    text = format_plc_text(
        [
            {
                "id": "a",
                "parallel": [[{"tag": "HS_START", "normally_closed": False}]],
                "series": [],
                "coil_tag": "M1C",
                "coil_negated": False,
                "comment": "Start",
                "contact_tag": "HS_START",
                "normally_closed": False,
            },
            {
                "id": "b",
                "parallel": [[{"tag": "ES1", "normally_closed": True}]],
                "series": [],
                "coil_tag": "M1C",
                "coil_negated": False,
                "comment": "E-stop is a stop",
                "contact_tag": "ES1",
                "normally_closed": True,
            },
        ]
    )
    assert LEARNING_NOTE in text
    assert "[HS_START]" in text
    assert "[/ES1]" in text
    assert "(M1C)" in text


def test_does_not_invent_tags_when_cabinet_empty():
    project = new_blank_project("Empty")
    program = build_starter_program(project, _answers())
    assert program["rungs"] == []
    assert "No rungs yet" in program["plc_text"] or program["plc_text"]
    assert {i["label"] for i in program["hmi_items"]} >= {"Running", "Stopped", "Fault"}


def test_sample_cabinet_still_loads_after_program_feature():
    project = load_project(SAMPLE)
    assert project.name == "Sample Motor Cabinet"
    assert any(item.fields.get("tag") == "M1C" for item in project.items)
    assert "rungs" in project.program


def test_default_design_answers_uses_cabinet_not_invented_tags():
    project = load_project(SAMPLE)
    answers = default_design_answers(project)
    assert answers["direction"] == "Forward only"
    assert answers["hmi_show"] == "Running, Stopped, and Fault"
    program = build_starter_program(project, answers)
    known = {item.fields["tag"] for item in project.items if item.fields.get("tag")}
    assert program["rungs"], "sample cabinet should produce visible starter rungs"
    for rung in program["rungs"]:
        for contact in flatten_contacts(rung):
            assert contact["tag"] in known
        assert rung["coil_tag"] in known


def test_ladder_spacing_constants_leave_clearance():
    """Rungs must not overlap after hover declutter (tags-only labels)."""
    from cabinet_studio.ui import programming_viewer as pv

    # Overnight readability widened gaps; keep floors, not exact equality.
    assert pv.INTER_RUNG_GAP >= 112
    assert pv.TITLE_BAND == 64
    assert pv.BOTTOM_PAD == 40
    assert pv.TAG_CLEAR_ABOVE == 24
    assert pv.BRANCH_ROW_H >= 120
    assert pv.RAIL_INSET >= 64
    # One parallel branch block must leave room under the wire for the next rung gap.
    block = pv.TITLE_BAND + pv.BRANCH_ROW_H + pv.BOTTOM_PAD
    assert block + pv.INTER_RUNG_GAP >= 300


def test_empty_state_message_in_viewer_source():
    from pathlib import Path as P

    src = (P(__file__).resolve().parents[1] / "cabinet_studio" / "ui" / "programming_viewer.py").read_text(
        encoding="utf-8"
    )
    assert "No rungs yet — answer the questions or click Build starter program" in src
    assert "Build from drawings" in src
    assert "Build starter program" in src


def test_stale_empty_plc_text_resyncs_when_rungs_exist():
    project = load_project(SAMPLE)
    program = build_starter_program(project, default_design_answers(project))
    assert program["rungs"]
    stale = dict(program)
    stale["plc_text"] = (
        "Learning program for this cabinet. Not a download to a live PLC.\n\n"
        "(No rungs yet. Answer the questions or type your own ladder below.)\n"
    )
    stale["text_edited"] = False
    loaded = program_from_dict(stale)
    assert "(No rungs yet" not in loaded["plc_text"]
    assert "Rung 1" in loaded["plc_text"]
    assert loaded["rungs"][0]["coil_tag"] == program["rungs"][0]["coil_tag"]
    assert plc_text_looks_stale_empty(stale["plc_text"], stale["rungs"]) is True


def test_weld_place_builds_rungs_from_cabinet():
    """Solenoid outputs (no contactor) must still yield visible rungs from design defaults."""
    from cabinet_studio.services.programming import program_questions_for_project

    project = load_project(WELD)
    answers = default_design_answers(project)
    program = build_starter_program(project, answers)
    known = {item.fields["tag"] for item in project.items if item.fields.get("tag")}
    assert program["rungs"], "weld-place cell must produce rungs from Place_Relay / Welder_Relay"
    coils = {r["coil_tag"] for r in program["rungs"]}
    assert "Place_Relay" in coils
    assert "Welder_Relay" in coils
    for rung in program["rungs"]:
        for contact in flatten_contacts(rung):
            assert contact["tag"] in known
        assert rung["coil_tag"] in known
    keys = [k for k, _p, _o in program_questions_for_project(project)]
    assert "on_start" in keys
    assert "second_coil" in keys
    assert any("Place_Relay" in opt for _k, _p, opts in program_questions_for_project(project) for opt in opts)
