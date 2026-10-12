"""v0.3.25 backplate power zones, door drawing from the interview, suggested enclosure."""

from __future__ import annotations

from cabinet_studio.models.project import PlacedItem
from cabinet_studio.services import ai_build as ab
from cabinet_studio.services.drawings import _layout_auto_duct_rects, build_sheets
from cabinet_studio.services.enclosure_select import apply_enclosure_selection
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.panel_zones import arrange, suggest_enclosure, zone_of

LIB = load_library()


def _item(n: int, type_id: str, tag: str, **fields: str) -> PlacedItem:
    return PlacedItem(id=f"i{n}", library_id=None, type_id=type_id, x=40.0 * n, y=30.0 * n,
                      fields={"tag": tag, **fields})


def _project(door: str = "", enclosure: str = "Hoffman 36×30×12 (A363012LP + A36P30)"):
    p = new_blank_project("Zones")
    p.cabinet_label = "PNL1"
    p.interview = {"supply_voltage": "480 VAC", "door_drawing": door, "enclosure_selection": enclosure}
    apply_enclosure_selection(p, p.interview)
    p.items = [
        _item(1, "plc", "PLC1"), _item(2, "vfd", "VFD1"), _item(3, "relay", "CR1"),
        _item(4, "contactor", "M1"), _item(5, "power_supply", "PS1"), _item(6, "motor", "MTR1"),
        _item(7, "pushbutton", "START_PB"), _item(8, "estop", "ES1"), _item(9, "io_module", "IO1"),
        _item(10, "breaker", "CB1"), _item(11, "enclosure", "ENC1"),
    ]
    return p


def _layouts(p):
    return [s for s in build_sheets(p, LIB) if s.kind == "layout"]


def test_zone_classes():
    assert zone_of("vfd", "VFD1") == "vfd"
    assert zone_of("contactor", "M1") == "mid" and zone_of("power_supply", "PS1") == "mid"
    assert zone_of("plc", "PLC1") == "low" and zone_of("relay", "CR1") == "low"
    assert zone_of("relay", "CB1") == "high" and zone_of("breaker", "Q1") == "high"
    assert zone_of("motor", "MTR1") == "field" and zone_of("enclosure", "") == "shell"


def test_backplate_is_one_sheet_in_power_zones_with_ducts():
    p = _project()
    sheets = _layouts(p)
    plate = [s for s in sheets if "BACKPLATE" in s.title]
    assert len(plate) == 1, [s.title for s in sheets]
    boxes = {b.tag: b for b in plate[0].boxes}
    assert set(boxes) == {"PLC1", "VFD1", "CR1", "M1", "PS1", "IO1", "CB1", "PE BAR", "TB-OUT"}, \
        "every plate device on the main plate (+ v0.3.32 virtual field strip TB-OUT for MTR1)"
    top = lambda t: boxes[t].y  # noqa: E731
    assert top("CB1") <= top("M1") == top("PS1") < top("PLC1") < top("VFD1")
    if top("CB1") == top("M1"):
        assert boxes["CB1"].x < boxes["M1"].x, "shared row keeps high power left of mid power"
    px, py, pw, ph = plate[0].panel
    for b in boxes.values():
        assert px <= b.x and b.x + b.w <= px + pw and py <= b.y and b.y + b.h <= py + ph
    vfd = boxes["VFD1"]
    from cabinet_studio.services.panel_zones import ROW_GAP_IN

    f = pw / p.backplate_width_in
    assert abs((py + ph) - (vfd.y + vfd.h) - ROW_GAP_IN * f) < 1, "VFD sits at the bottom, above the bottom duct"
    items = list(boxes.values())
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y, (a.tag, b.tag)
    ducts = _layout_auto_duct_rects(p, plate[0])
    horizontal = [d for d in ducts if d[2] > d[3]]
    assert len(horizontal) >= 2, "wire duct between the zones"
    assert any("MTR1" in n for n in plate[0].notes), "field motor listed, not drawn on the plate"
    assert any("Power zones top to bottom" in n for n in plate[0].notes)


def test_door_sheet_only_when_interview_wants_it():
    yes = _layouts(_project(door=ab.DOOR_YES))
    assert any("DOOR" in s.title for s in yes)
    door = next(s for s in yes if "DOOR" in s.title)
    assert {b.tag for b in door.boxes} == {"START_PB", "ES1"}
    no = _layouts(_project(door=ab.DOOR_NO))
    assert not any("DOOR" in s.title for s in no)
    assert any("No door drawing" in n and "START_PB" in n for s in no for n in s.notes)


def test_largest_vfd_goes_to_the_very_bottom():
    devs = [("a", "low", 6, 4), ("small", "vfd", 5, 4), ("big", "vfd", 8, 9)]
    out = arrange(devs, 16, 30)
    assert out["big"][1] > out["small"][1]


def test_pinned_parts_keep_their_spot_and_others_flow_around():
    from cabinet_studio.services.panel_zones import place_with_pins

    devs = [("a", "high", 6, 3), ("b", "mid", 6, 3), ("c", "low", 6, 3)]
    auto = arrange(devs, 27, 21)
    out = place_with_pins(devs, {"c": auto["a"][:2]}, 27, 21)
    assert out["c"][:2] == auto["a"][:2], "pinned part stays where it was dropped"
    rects = list(out.values())
    for i, (x, y, w, h) in enumerate(rects):
        for ox, oy, ow, oh in rects[i + 1:]:
            assert x + w <= ox or ox + ow <= x or y + h <= oy or oy + oh <= y
    assert place_with_pins(devs, {"a": (99.0, 99.0)}, 27, 21)["a"][:2] == (21.0, 18.0), "clamped onto the plate"
    p = _project()
    plc = next(i for i in p.items if i.fields["tag"] == "PLC1")
    plc.fields.update(layout_x_in="1", layout_y_in="1")
    sheet = next(s for s in _layouts(p) if "BACKPLATE" in s.title)
    box = next(b for b in sheet.boxes if b.tag == "PLC1")
    f = sheet.panel[2] / p.backplate_width_in
    assert abs(box.x - (sheet.panel[0] + f)) < 0.01 and abs(box.y - (sheet.panel[1] + f)) < 0.01


def test_suggested_enclosure_is_smallest_that_fits():
    small = [("a", "low", 8, 4), ("b", "mid", 7, 4)]
    assert "24×24" in suggest_enclosure(small)[0]
    big = [(str(n), "low", 8, 4) for n in range(18)] + [("v1", "vfd", 8, 4), ("v2", "vfd", 8, 4)]
    label, fits = suggest_enclosure(big)
    assert "36×30" in label
    p = new_blank_project("AI")
    p.interview = {}
    p.items = [_item(1, "plc", "PLC1"), _item(2, "vfd", "VFD1"), _item(3, "power_supply", "PS1")]
    label = ab.suggest_enclosure_for(LIB, p)
    assert label.startswith("Hoffman") and p.interview["enclosure_selection"] == label
    assert ab.suggest_enclosure_for(LIB, p) == label, "an existing choice is kept"


def test_interview_defaults_and_door_question():
    keys = [q[0] for q in ab.AI_BUILD_QUESTIONS]
    assert "door_drawing" in keys and keys.index("door_drawing") < keys.index("project_name")
    a = {"duty": "conveyor with one motor"}
    assert ab.interview_default(a, "has_motor") == "Yes"
    a.update(has_motor="Yes", supply_voltage="480 VAC")
    assert ab.interview_default(a, "motor_control") == "VFD (variable speed)"
    a["operator_devices"] = ab.interview_default(a, "operator_devices")
    assert ab.interview_default(a, "door_drawing") == ab.DOOR_YES
    assert ab.interview_default({}, "duty") == ""
    assert ab.interview_from_ai_answers({"door_drawing": ab.DOOR_NO})["door_drawing"] == ab.DOOR_NO
