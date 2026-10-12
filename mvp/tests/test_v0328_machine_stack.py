"""v0.3.28: maker preference, light curtain + stack light design and rungs, pretend machine, real outlines."""

from __future__ import annotations

from cabinet_studio.services import ai_build as ab
from cabinet_studio.services.drawings import build_sheets
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.panel_zones import item_inches
from cabinet_studio.services.programming import build_starter_program, cabinet_device_tags
from cabinet_studio.services.sim_autorun import normal_run_plan
from cabinet_studio.services.sim_plant import PlantModel
from cabinet_studio.services.standards import default_profile

LIB = load_library()


def _answers(**over):
    answers = ab.blank_ai_answers()
    answers["duty"] = "weld cell with conveyor motor"
    for key, *_ in ab.AI_BUILD_QUESTIONS:
        if key != "duty" and not answers.get(key):
            answers[key] = over.get(key) or ab.interview_default(answers, key)
    answers.update(over)
    return answers


def _project(answers):
    project = new_blank_project("Weld")
    project.interview = ab.interview_from_ai_answers(answers)
    recs = ab.recommend_devices(LIB, default_profile(), answers)
    ab.apply_recommendations(LIB, project, recs)
    return project, recs


def test_library_has_three_makers_and_new_types():
    vendors = {c.vendor for c in LIB.catalog}
    assert {"Allen-Bradley", "Siemens", "Omron"} <= vendors
    for tid in ("light_curtain", "breaker", "disconnect", "motor_protector", "fuse_holder", "terminal_block"):
        assert tid in LIB.types and any(c.type_id == tid for c in LIB.catalog)
    for maker in ("Allen-Bradley", "Siemens", "Omron"):
        assert any(c.type_id == "light_curtain" and c.vendor == maker for c in LIB.catalog)


def test_interview_defaults_pick_maker_curtain_and_stack():
    a = _answers()
    assert a["manufacturer"] == "Allen-Bradley"
    assert a["light_curtain"].startswith("Yes") and a["stack_light"].startswith("Yes")
    assert "light curtain" in ab.interview_suggestion(a, "light_curtain").lower()


def test_ai_design_adds_curtain_safety_relay_stack_and_protection():
    project, recs = _project(_answers())
    tags = {i.fields.get("tag"): i for i in project.items}
    for tag in ("LC1", "SR_LC", "STK_Green", "STK_Amber", "STK_Red", "DS1", "CB1", "TB1"):
        assert tag in tags, tag
    assert tags["LC1"].type_id == "light_curtain"
    assert tags["STK_Amber"].fields.get("function") == "Light curtain broken"


def test_maker_preference_swaps_parts():
    for maker in ("Siemens", "Omron"):
        _project_, recs = _project(_answers(manufacturer=maker))
        plc = next(r for r in recs if r.type_id == "plc")
        assert plc.vendor == maker, (maker, plc.vendor)
        assert sum(1 for r in recs if r.vendor == maker) >= 4


def _sim(project):
    program = build_starter_program(project, {})
    sim = ScanSimulator.from_program(program, devices=cabinet_device_tags(project))
    return program, sim


def _scan(sim, n=3):
    for _ in range(n):
        sim.scan_once()


def test_stack_light_green_amber_red_follow_safety_inputs():
    project, _recs = _project(_answers())
    program, sim = _sim(project)
    coils = {r.get("coil_tag") for r in program["rungs"]}
    assert {"STK_Green", "STK_Amber", "STK_Red"} <= coils
    _scan(sim)
    assert sim.read("STK_Green") and not sim.read("STK_Amber") and not sim.read("STK_Red")
    sim.set_force("LC1", True)
    _scan(sim)
    assert sim.read("STK_Amber") and not sim.read("STK_Green") and not sim.read("STK_Red")
    sim.set_force("ES1", True)
    _scan(sim)
    assert sim.read("STK_Red") and not sim.read("STK_Amber") and not sim.read("STK_Green")
    sim.set_force("ES1", None)
    sim.set_force("LC1", None)
    _scan(sim)
    assert sim.read("STK_Green")


def test_light_curtain_drops_the_running_output():
    project, _recs = _project(_answers())
    program, sim = _sim(project)
    run = next(r for r in program["rungs"] if r.get("parallel"))
    coil = run["coil_tag"]
    start = run["parallel"][0][0]["tag"]
    assert any(s["tag"] == "LC1" and s["normally_closed"] for s in run["series"])
    sim.set_force(start, True)
    _scan(sim)
    sim.set_force(start, None)
    _scan(sim)
    assert sim.read(coil), "seal-in keeps it running"
    sim.set_force("LC1", True)
    _scan(sim)
    assert not sim.read(coil), "breaking the beam stops it"
    sim.set_force("LC1", None)
    _scan(sim)
    assert not sim.read(coil), "needs a new Start after the beam clears"


def test_plant_feedback_follows_outputs_and_parts_pulse():
    plant = PlantModel(["Motor_Running", "Clamp_Extended", "Clamp_Retracted", "Part_Eye", "ES1", "LC1"],
                       ["Motor_Run", "Clamp_Sol", "Conv1_Run"])
    assert ("Motor_Running", "Motor_Run", False) in plant.links
    assert ("Clamp_Retracted", "Clamp_Sol", True) in plant.links
    assert plant.parts == ["Part_Eye"] and "ES1" not in plant.handled and "LC1" not in plant.handled
    outs = {"Motor_Run": False, "Clamp_Sol": False, "Conv1_Run": False}
    plant.step(0.0, outs.get)
    outs["Motor_Run"] = outs["Clamp_Sol"] = outs["Conv1_Run"] = True
    assert not any(t == "Motor_Running" for t, _v, _w in plant.step(0.5, outs.get)), "travel time"
    changes = {t: v for t, v, _w in plant.step(1.6, outs.get)}
    assert changes.get("Motor_Running") is True and changes.get("Clamp_Retracted") is False
    seen = set()
    for i in range(40):
        for t, v, _w in plant.step(2.0 + i * 0.25, outs.get):
            if t == "Part_Eye":
                seen.add(v)
    assert seen == {True, False}, "a part passes the eye while the conveyor runs"


def test_normal_run_plan_never_presses_the_estop_or_breaks_the_curtain():
    rungs = [[{"kind": "contact", "var": "PB_Start"}, {"kind": "contact", "var": "ES1", "form": "NC"},
              {"kind": "contact", "var": "LC1", "form": "NC"}, {"kind": "coil", "var": "CR1"}]]
    plan = normal_run_plan(rungs, ["PB_Start", "ES1", "LC1"])
    assert plan[0] == {"label": "Safety left to you (not touched): ES1, LC1", "set": {}}
    assert not any(t in s["set"] for s in plan for t in ("ES1", "LC1"))
    # Even when the program reads the E-stop NO first (stack light rung), Normal run never forces it.
    rungs = [[{"kind": "contact", "var": "Estop_PB"}, {"kind": "coil", "var": "STK_Red"}],
             [{"kind": "contact", "var": "Light_Curtain_Fault"}, {"kind": "coil", "var": "STK_Amber"}],
             [{"kind": "contact", "var": "PB_Start"}, {"kind": "coil", "var": "CR1"}]]
    plan = normal_run_plan(rungs, ["Estop_PB", "Light_Curtain_Fault", "PB_Start"])
    assert not any(t in s["set"] for s in plan for t in ("Estop_PB", "Light_Curtain_Fault"))


def test_normal_run_plan_leaves_plant_tags_to_the_machine():
    rungs = [[{"kind": "contact", "var": "Start_PB"}, {"kind": "contact", "var": "Motor_Running"},
              {"kind": "coil", "var": "Motor_Run"}]]
    plan = normal_run_plan(rungs, ["Start_PB", "Motor_Running"], skip={"Motor_Running"})
    assert all("Motor_Running" not in s["set"] for s in plan)


def test_real_outlines_size_the_layout():
    project, _recs = _project(_answers())
    cb = next(i for i in project.items if i.fields.get("tag") == "CB1")
    w, h = item_inches(LIB, cb)
    poles = int(cb.fields.get("poles") or 1)
    assert abs(w - 12.7 * poles / 25.4) < 0.01 and abs(h - 90 / 25.4) < 0.01  # 1489-M: 12.7 mm per pole
    sheets = [s for s in build_sheets(project, LIB) if s.kind == "layout"]
    plate = [s for s in sheets if "DOOR" not in s.title]
    assert len(plate) == 1, [s.title for s in sheets]
    assert not any(b.key == next(i.id for i in project.items if i.fields.get("tag") == "LC1") for s in sheets
                   for b in s.boxes), "the light curtain is a field device, not on the plate"
