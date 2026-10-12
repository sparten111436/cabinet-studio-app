"""HMI library, HMI design model, creator interview, validation, save/load and HMI drawing sheets."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.services import hmi_design as hd
from cabinet_studio.services import hmi_library as hl
from cabinet_studio.services.drawings import DISCLAIMER, WIRE_SCHEDULE_KIND, build_sheets, drawing_issues, render_svg
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.project_store import load_project, save_project


def _item(type_id, tag, description="", **fields):
    stored = {"tag": tag, "description": description, **fields}
    return PlacedItem(id=tag.lower(), library_id=None, type_id=type_id, x=10, y=10, fields=stored)


def make_project(maker="", plc_vendor="Allen-Bradley", plc_catalog="5069-L306ER") -> Project:
    items = [
        _item("power_supply", "PSU1", "24 VDC supply", wire_numbers="+24V, 0V", io_direction=""),
        _item("plc", "PLC1", "Main PLC", vendor=plc_vendor, catalog=plc_catalog),
        _item("ethernet_switch", "ENET1", "Ethernet switch"),
        _item("pushbutton", "PB_START", "Start PB", io_direction="input", io_address="I:0/0"),
        _item("pushbutton", "PB_STOP", "Stop PB", io_direction="input", io_address="I:0/1"),
        _item("estop", "ES1", "E-stop"),
        _item("contactor", "M1", "Motor contactor", io_direction="output", io_address="O:0/0"),
        _item("vfd", "VFD1", "Conveyor drive"),
        _item("relay", "OL1", "Motor overload fault"),
    ]
    interview = {"supply_voltage": "480 VAC", "control_voltage": "24 VDC"}
    if maker:
        interview["manufacturer"] = maker
    return Project(name="HMI Test", template_id=None, cabinet_width=780, cabinet_height=860,
                   cabinet_label="CP1", interview=interview, items=items)


# ----------------------------------------------------------------------------- library

def test_library_entries_complete_and_sane():
    entries = hl.load_hmi_catalog()
    assert 30 <= len(entries) <= 45
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    for e in entries:
        missing = [k for k in hl.REQUIRED_FIELDS if k not in e]
        assert not missing, (e["id"], missing)
        assert e["maker"] in hl.MAKERS
        for key in ("screen_in", "bezel_w_mm", "bezel_h_mm", "depth_mm", "cutout_w_mm", "cutout_h_mm", "power_w"):
            assert e[key] > 0, (e["id"], key)
        assert e["cutout_w_mm"] < e["bezel_w_mm"] and e["cutout_h_mm"] < e["bezel_h_mm"], e["id"]
        assert len(e["resolution_px"]) == 2 and min(e["resolution_px"]) > 0
        assert e["comms"] and e["plc_families"] and e["software"]
        assert e["source_url"] == ""
        assert "verify" in e["verify"]


def test_library_covers_required_families():
    fams = {e["family"] for e in hl.load_hmi_catalog()}
    for want in ("PanelView 800", "PanelView 5310", "PanelView Plus 7 Standard", "SIMATIC Basic Panel 2nd Gen",
                 "SIMATIC Comfort Panel", "SIMATIC Unified Comfort Panel", "NB Series", "NA5 Series"):
        assert want in fams


def test_filters_and_door_outline():
    sie = hl.hmi_choices("Siemens")
    assert sie and all(e["maker"] == "Siemens" for e in sie)
    mid = hl.hmi_choices(min_in=9, max_in=12.5)
    assert mid and all(9 <= e["screen_in"] <= 12.5 for e in mid)
    s71200 = hl.hmi_choices(plc_family="S7-1200")
    assert s71200 and all("S7-1200" in e["plc_families"] for e in s71200)
    w, h = hl.hmi_door_outline("si-ktp700-basic")
    assert w == pytest.approx(214 / 25.4) and h == pytest.approx(158 / 25.4)
    with pytest.raises(KeyError):
        hl.hmi_door_outline("nope")
    assert hl.hmi_id_from_label(hl.hmi_label(hl.hmi_by_id("om-nb7w"))) == "om-nb7w"


@pytest.mark.parametrize("maker", ["Siemens", "Omron", "Allen-Bradley"])
def test_recommend_respects_maker_preference(maker):
    model_id, reason = hl.recommend_hmi(make_project(maker=maker, plc_vendor="", plc_catalog=""))
    assert hl.hmi_by_id(model_id)["maker"] == maker
    assert maker in reason
    model_id, _ = hl.recommend_hmi({"hmi_maker": maker, "hmi_size": "12 in"})
    entry = hl.hmi_by_id(model_id)
    assert entry["maker"] == maker and abs(entry["screen_in"] - 12) < 1


def test_recommend_pairs_with_plc_family():
    project = make_project(plc_vendor="Siemens", plc_catalog="S7-1200 CPU 1214C")
    assert hl.project_plc_families(project) == ["S7-1200"]
    model_id, reason = hl.recommend_hmi(project)
    entry = hl.hmi_by_id(model_id)
    assert entry["maker"] == "Siemens" and "S7-1200" in entry["plc_families"]
    assert "S7-1200" in reason


# ----------------------------------------------------------------------------- interview + model

def test_interview_defaults_and_generation():
    project = make_project(maker="Allen-Bradley")
    answers = hd.default_answers(project)
    assert set(hd.QUESTION_KEYS) <= set(answers)
    assert answers["hmi_maker"] == "Allen-Bradley"
    assert answers["hmi_start_stop"] == hd.START_HARDWIRED  # cabinet has a Start PB
    assert answers["hmi_numbers"] == "Yes" and answers["hmi_connect"] == hd.CONNECT_SWITCH
    for key in hd.QUESTION_KEYS:
        q = hd.hmi_question(project, answers, key)
        assert q["default"] in q["choices"], key
        assert q["prompt"] and q["help"]
    design = hd.generate_design(project, answers)
    assert hl.hmi_by_id(design.model_id)["maker"] == "Allen-Bradley"
    assert answers["hmi_overview"] == hd.OVERVIEW_YES
    assert [s.name for s in design.screens] == ["Main", "Machine", "Manual", "Alarms"]
    main = design.screen("Main")
    kinds = {o.kind for o in main.objects}
    assert {"text", "alarm_banner", "estop_status", "lamp", "numeric_display", "nav"} <= kinds
    tags = {o.tag for o in main.objects}
    assert {"ES1", "M1", "HMI_VFD1_Speed"} <= tags
    assert hd.validate_design(design, project) == []


def test_estop_is_status_only_and_never_written():
    project = make_project()
    design = hd.generate_design(project, hd.default_answers(project, {"hmi_start_stop": hd.START_ON_HMI}))
    assert "estop_status" not in {k for k, v in hd.OBJECT_KINDS.items() if v["access"] == "W"}
    assert all(tag != "ES1" for _s, _l, tag in hd.write_tags(design))
    writes = {tag for _s, _l, tag in hd.write_tags(design)}
    assert {"HMI_Start", "HMI_Stop"} <= writes
    main = design.screen("Main")
    hd.add_object(design, main, "momentary", label="Bad", tag="ES1")
    assert any("safety tag ES1" in issue for issue in hd.validate_design(design, project))


def test_validation_flags_unknown_overlap_missing_and_input_writes():
    project = make_project()
    design = hd.HmiDesign("si-ktp700-basic", [hd.HmiScreen("Main")])
    s = design.screens[0]
    s.objects.append(hd.HmiObject("a", "lamp", 0, 0, 4, 2, "A", "NOPE"))
    s.objects.append(hd.HmiObject("b", "lamp", 2, 1, 4, 2, "B", ""))
    s.objects.append(hd.HmiObject("c", "momentary", 10, 0, 4, 2, "C", "PB_START"))
    s.objects.append(hd.HmiObject("d", "nav", 16, 0, 4, 2, "D", target="Ghost"))
    issues = " | ".join(hd.validate_design(design, project))
    assert "unknown tag NOPE" in issues
    assert "overlaps" in issues
    assert "has no PLC tag" in issues
    assert "physical input PB_START" in issues
    assert "missing screen Ghost" in issues


def test_free_spot_and_rescale_keep_objects_on_screen():
    design = hd.HmiDesign("ab-2711r-t7t", [hd.HmiScreen("Main")])
    s = design.screens[0]
    for _ in range(10):
        assert hd.add_object(design, s, "lamp") is not None
    assert not any(hd.overlaps(a, b) for i, a in enumerate(s.objects) for b in s.objects[i + 1:])
    hd.rescale_to_model(design, "ab-2713p-t15")  # 5:3 -> 4:3
    cols, rows = hd.grid_size("ab-2713p-t15")
    assert all(o.x + o.w <= cols and o.y + o.h <= rows for o in s.objects)


def test_json_round_trip_through_project_save(tmp_path):
    project = make_project()
    design = hd.generate_design(project)
    hd.save_design(project, design)
    path = tmp_path / "hmi.cabinet.json"
    save_project(project, path)
    loaded = load_project(path)
    again = hd.load_design(loaded)
    assert again is not None
    assert hd.design_to_dict(again) == hd.design_to_dict(design)
    hd.save_design(loaded, None)
    assert hd.load_design(loaded) is None
    loaded.interview[hd.STORE_KEY] = "{broken"
    assert hd.load_design(loaded) is None


# ----------------------------------------------------------------------------- quick-build features

def test_equipment_and_faceplate_groups():
    project = make_project()
    parts = {p["tag"]: p for p in hd.equipment(project)}
    assert parts["M1"]["faceplate"] == "motor_vfd" and parts["M1"]["vfd"] == "VFD1" and parts["M1"]["fault"] == "OL1"
    design = hd.HmiDesign("ab-2713p-t12", [hd.HmiScreen("Main")])
    screen = design.screens[0]
    placed = hd.add_faceplate(design, screen, "motor_vfd", parts["M1"], controls=True)
    assert placed and len({o.group for o in placed}) == 1
    assert {o.kind for o in placed} >= {"lamp", "momentary", "numeric_display", "numeric_entry"}
    assert {o.tag for o in placed} >= {"M1", "OL1", "HMI_VFD1_Speed", "HMI_M1_Start"}
    status_only = hd.add_faceplate(design, screen, "motor", parts["M1"], controls=False)
    assert status_only and not any(o.access == "W" for o in status_only)
    assert hd.validate_design(design, project) == []
    assert hd.group_objects(screen, placed[0].group) == placed


def test_per_part_screens_trends_and_nav_bar():
    project = make_project()
    answers = hd.default_answers(project, {"hmi_group": hd.GROUP_EACH,
                                           "hmi_screens": "Main + Manual + Alarms + Trends + Settings"})
    design = hd.generate_design(project, answers)
    names = [s.name for s in design.screens]
    assert names[:3] == ["Main", "Machine", "M1"] and "Trends" in names
    assert any(o.kind == "trend" for o in design.screen("M1").objects)
    for screen in design.screens:
        targets = {o.target for o in screen.objects if o.kind == "nav"}
        assert targets == set(names) - {screen.name}
    assert hd.validate_design(design, project) == []


def test_tag_wizard_suggests_and_binds():
    project = make_project()
    lamp = hd.HmiObject("a", "lamp", 0, 0, 3, 2, "Motor contactor")
    assert hd.suggest_tag(lamp, project)[0] == "M1"
    assert hd.suggest_tag(hd.HmiObject("b", "estop_status", 0, 0, 3, 2, "E-stop"), project)[0] == "ES1"
    assert hd.suggest_tag(hd.HmiObject("c", "momentary", 0, 0, 3, 2, "Start conveyor"), project)[0] == \
        "HMI_StartConveyor"
    assert hd.suggest_tag(hd.HmiObject("d", "text", 0, 0, 3, 1, "Title"), project)[0] == ""
    design = hd.HmiDesign("ab-2713p-t12", [hd.HmiScreen("Main", [lamp, hd.HmiObject("c", "momentary", 4, 0, 3, 2,
                                                                                   "Start conveyor")])])
    assert hd.bind_all(design, project) == 2
    assert hd.validate_design(design, project) == []


def test_alarm_list_priorities():
    project = make_project()
    rows = {r["tag"]: r for r in hd.alarm_rows(hd.generate_design(project), project)}
    assert rows["ES1"]["priority"].startswith("1") and "status only" in rows["ES1"]["class"]
    assert rows["OL1"]["priority"].startswith("2")


def test_tag_csv_export_has_no_blank_lines(tmp_path):
    import csv

    project = make_project()
    design = hd.generate_design(project, hd.default_answers(project, {"hmi_start_stop": hd.START_ON_HMI}))
    path = tmp_path / "tags.csv"
    count = hd.export_tag_csv(design, project, path)
    raw = path.read_bytes()
    assert b"\r\r\n" not in raw and b"\n\n" not in raw.replace(b"\r\n", b"\n")
    rows = list(csv.reader(path.open(encoding="utf-8", newline="")))
    assert rows[0][:4] == ["Tag Name", "Data Type", "Access", "PLC Address"]
    assert len(rows) == count + 1
    by = {r[0]: r for r in rows[1:]}
    assert by["M1"][3] == "O:0/0" and by["HMI_VFD1_Speed"][1] == "REAL"
    assert by["HMI_M1_Start"][2] == "Read/Write" and "add to PLC" in by["HMI_M1_Start"][3]
    assert by["ES1"][2] == "Read"


def test_themes_round_trip_and_colors():
    project = make_project()
    design = hd.generate_design(project, theme="Dark")
    assert hd.design_from_json(hd.design_to_json(design)).theme == "Dark"
    isa = hd.DEFAULT_THEME
    assert hd.theme_colors(isa, "Green")[0] == hd.THEMES[isa]["fill"]  # normal = gray
    assert hd.theme_colors(isa, "Red")[0] == hd.COLORS["Red"]  # abnormal keeps color
    assert hd.generate_design(project).theme == isa


# ----------------------------------------------------------------------------- drawings

def test_hmi_sheets_only_with_design_and_after_wire_schedule():
    library = load_library()
    project = make_project()
    plain = build_sheets(project, library)
    assert not any(s.kind.startswith("hmi-") for s in plain)
    hd.save_design(project, hd.generate_design(project))
    sheets = build_sheets(project, library)
    kinds = [s.kind for s in sheets]
    hmi_at = [i for i, k in enumerate(kinds) if k.startswith("hmi-")]
    assert hmi_at and hmi_at == list(range(hmi_at[0], len(sheets)))
    assert WIRE_SCHEDULE_KIND in kinds and kinds.index(WIRE_SCHEDULE_KIND) < hmi_at[0]
    assert {"hmi-layout", "hmi-cutout", "hmi-wiring", "hmi-alarms"} <= set(kinds)
    alarm_svg = render_svg(next(s for s in sheets if s.kind == "hmi-alarms"), project)
    assert "ES1" in alarm_svg and "1 - High" in alarm_svg
    assert [s.number for s in sheets] == list(range(1, len(sheets) + 1))
    assert all(s.total == len(sheets) for s in sheets)
    for sheet in sheets[hmi_at[0]:]:
        assert drawing_issues(sheet) == []
        svg = render_svg(sheet, project)
        ET.fromstring(svg)
        assert svg.count(DISCLAIMER) == 2  # <desc> + title block footer, i.e. once on the printed sheet
        assert hd.SAFETY_NOTE in " ".join(sheet.notes)
        for node in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text"):
            x = float(node.get("x"))
            assert 20 <= x <= 1680, (sheet.title, node.text)
    wiring = next(s for s in sheets if s.kind == "hmi-wiring")
    svg = render_svg(wiring, project)
    for wire in ("HMI+24", "HMI0V", "HMI-PE", "HMI-ETH"):
        assert wire in svg
    assert "PSU1" in svg and "ENET1" in svg and "HMI TAG TABLE" in svg
    assert all(seg.wire and seg.color and seg.gauge for seg in wiring.segments)
    cutout = render_svg(next(s for s in sheets if s.kind == "hmi-cutout"), project)
    entry = hl.hmi_by_id(hd.load_design(project).model_id)
    assert f"{entry['cutout_w_mm']} mm" in cutout


def test_tag_table_overflow_sheet():
    library = load_library()
    project = make_project()
    design = hd.HmiDesign("ab-2713p-t19", [hd.HmiScreen(f"S{i}") for i in range(3)])
    for screen in design.screens:
        while hd.add_object(design, screen, "lamp", w=2, h=1, tag="M1") is not None and len(screen.objects) < 20:
            pass
    hd.save_design(project, design)
    sheets = build_sheets(project, library)
    assert any(s.kind == "hmi-tags" for s in sheets)
    for sheet in sheets:
        if sheet.kind.startswith("hmi-"):
            assert drawing_issues(sheet) == []
            ET.fromstring(render_svg(sheet, project))


# ----------------------------------------------------------------------------- machine graphics / runtime / export

def test_every_graphic_draws_static_and_animated():
    from cabinet_studio.services.hmi_symbols import ANIMATIONS, GRAPHICS, svg_from_shapes, symbol_shapes

    for kind, spec in GRAPHICS.items():
        assert spec["anim"] in ANIMATIONS and spec["help"] and kind in hd.OBJECT_KINDS
        for theme in hd.THEMES:
            still = symbol_shapes(kind, 0, 0, 120, 80, None, theme)
            assert still, kind
            ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{svg_from_shapes(still, str)}</svg>')
    run0 = symbol_shapes("g_conveyor", 0, 0, 200, 60, {"on": True, "phase": 1})
    run1 = symbol_shapes("g_conveyor", 0, 0, 200, 60, {"on": True, "phase": 2})
    assert run0 != run1  # belt marks move
    assert symbol_shapes("g_tank", 0, 0, 60, 100, {"level": 0.2}) != symbol_shapes("g_tank", 0, 0, 60, 100,
                                                                                   {"level": 0.9})
    faulted = symbol_shapes("g_motor", 0, 0, 60, 60, {"fault": True})
    assert any("#d23a2a" in op for op in faulted)  # red only when abnormal


def test_machine_screen_graphic_tags_and_round_trip():
    project = make_project()
    project.items.append(_item("sensor", "PE1", "Part present photo-eye", io_direction="input"))
    project.items.append(_item("light", "LT_GRN", "Stack light green"))
    project.items.append(_item("light", "LT_RED", "Stack light red"))
    design = hd.generate_design(project)
    machine = design.screen("Machine")
    kinds = {o.kind: o for o in machine.objects}
    assert {"g_conveyor", "g_motor", "g_part", "g_photo_eye", "g_stack_light"} <= set(kinds)
    assert kinds["g_conveyor"].tag == "M1" and kinds["g_conveyor"].anim == "run"
    assert kinds["g_photo_eye"].tag == "PE1"
    assert kinds["g_stack_light"].tag == "LT_GRN,,LT_RED"  # tiers stay green,amber,red by position
    assert hd.validate_design(design, project) == []
    again = hd.design_from_json(hd.design_to_json(design))
    assert again.screen("Machine").objects[-1].anim == machine.objects[-1].anim
    assert {"LT_GRN", "LT_RED"} <= {r["tag"] for r in hd.tag_table(design, project)}
    tank = hd.add_object(design, machine, "g_tank")
    if tank is not None:
        assert hd.suggest_tag(tank, project)[0].startswith("HMI_") and hd.is_numeric(tank)
    hd.save_design(project, design)
    layout = [s for s in build_sheets(project, load_library()) if s.kind == "hmi-layout"]
    svg = render_svg(layout[1], project)
    ET.fromstring(svg)
    assert "Machine" in svg and "<polyline" in svg and DISCLAIMER in svg


def _sim_project():
    from cabinet_studio.services.programming import add_rung, empty_program

    project = make_project()
    project.program = add_rung(empty_program(), contact_tag="HMI_Start", coil_tag="M1")
    design = hd.HmiDesign("ab-2711r-t7t", [hd.HmiScreen("Main")])
    screen = design.screens[0]
    objs = {
        "start": hd.add_object(design, screen, "momentary", label="Start", tag="HMI_Start"),
        "lamp": hd.add_object(design, screen, "lamp", label="Running", tag="M1"),
        "conv": hd.add_object(design, screen, "g_conveyor", tag="M1"),
        "estop": hd.add_object(design, screen, "momentary", label="Bad", tag="ES1"),
        "level": hd.add_object(design, screen, "numeric_entry", label="Level", tag="HMI_Level"),
        "tank": hd.add_object(design, screen, "g_tank", tag="HMI_Level"),
    }
    return project, design, objs


def test_runtime_momentary_drives_coil_and_refuses_safety():
    from cabinet_studio.services.hmi_runtime import HmiRuntime

    project, design, o = _sim_project()
    rt = HmiRuntime(project, design)
    assert rt.press(o["start"]) == "" and rt.read_bool("HMI_Start")
    rt.tick()
    assert rt.read_bool("M1") and rt.anim_state(o["conv"])["on"]
    rt.tick()
    assert rt.release(o["start"]) == ""
    rt.tick()
    assert not rt.read_bool("M1") and not rt.anim_state(o["lamp"])["on"]
    why = rt.press(o["estop"])
    assert why.startswith("Refused") and "ES1" in why and rt.log
    assert not rt.read_bool("ES1")
    assert rt.enter_number(o["level"], "40") == ""
    assert rt.anim_state(o["tank"])["level"] == pytest.approx(0.4)
    assert rt.enter_number(o["level"], "abc") != ""


def test_runtime_shares_running_programming_sim():
    from cabinet_studio.services.hmi_runtime import HmiRuntime
    from cabinet_studio.services.ladder_sim import ScanSimulator

    project, design, o = _sim_project()
    sim = ScanSimulator.from_program(project.program, project_name=project.name, cycle_ms=100)
    rt = HmiRuntime(project, design, sim_provider=lambda: (sim, True))
    assert rt.sim is sim and rt.shared
    rt.press(o["start"])
    rt.tick()  # Programming page is running the scans, so the HMI does not scan itself
    assert not sim.read("M1")
    sim.scan_once()
    assert sim.read("M1")


@pytest.mark.parametrize("model_id", ["ab-2711r-t7t", "si-tp700-comfort", "om-nb7w"])
def test_export_for_maker_writes_files(tmp_path, model_id):
    from cabinet_studio.services.hmi_export import GENERIC, export_for_maker

    project = make_project()
    design = hd.generate_design(project)
    design.model_id = model_id
    result = export_for_maker(design, project, tmp_path / "hmi")
    names = [p.name for p in result["files"]]
    assert result["format"] == GENERIC
    assert any(n.endswith("_tags_generic.csv") for n in names)
    assert any(n.endswith("_alarms_generic.csv") for n in names)
    assert any(n.endswith("_screens.json") for n in names)
    assert sum(n.endswith(".svg") for n in names) == len(design.screens)
    for path in result["files"]:
        assert path.exists() and path.stat().st_size > 0
        if path.suffix == ".csv":
            assert "\r\r" not in path.read_bytes().decode("utf-8") and "\n\n" not in path.read_text("utf-8")
    readme = next(p for p in result["files"] if p.name.endswith("README.txt")).read_text("utf-8")
    assert "does NOT download" in readme and "NOT A CERTIFIED UL 508A DRAWING" in readme
