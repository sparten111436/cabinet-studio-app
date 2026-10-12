"""v0.3.32: real plan-view outlines, catalog outline sizes, power IN/OUT and scale on layout sheets."""
from __future__ import annotations

import re

from cabinet_studio.models.project import PlacedItem
from cabinet_studio.services import drawings as dw
from cabinet_studio.services.enclosure_select import apply_enclosure_selection
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.panel_zones import MM, item_inches

LIB = load_library()
SHELL = {"enclosure", "backplate"}


def _from_catalog(n: int, cat_id: str, tag: str, **extra: str) -> PlacedItem:
    cat = LIB.catalog_by_id[cat_id]
    return PlacedItem(id=f"i{n}", library_id=cat_id, type_id=cat.type_id, x=40.0 * n, y=30.0 * n,
                      fields={**cat.default_map(), "tag": tag, **extra})


def _project():
    p = new_blank_project("Outlines")
    p.cabinet_label = "PNL1"
    p.interview = {"supply_voltage": "480 VAC", "enclosure_selection": "Hoffman 36×30×12 (A363012LP + A36P30)"}
    apply_enclosure_selection(p, p.interview)
    p.items = [
        _from_catalog(1, "ab-194e-a40", "DS1"),
        _from_catalog(2, "ab-1492-fb3c30", "FU1"),
        _from_catalog(3, "ab-1489-m3c200", "CB1"),
        _from_catalog(4, "ab-contactor-100c", "M1"),
        _from_catalog(5, "ab-1606-xls", "PS1"),
        _from_catalog(6, "ab-compactlogix-5380", "PLC1"),
        _from_catalog(7, "ab-5069-ib16", "DI1"),
        _from_catalog(8, "ab-powerflex-525-frame-a", "VFD1"),
        _from_catalog(9, "motor-nema-1hp", "MTR1"),
        _from_catalog(10, "ab-pb-green-start", "START_PB", mounting="On door"),
        _from_catalog(11, "ab-estop-800f-40mm", "ES1", mounting="On door"),
    ]
    return p


def test_every_placeable_catalog_item_has_outline_dims():
    missing = []
    for cat in LIB.catalog:
        if cat.type_id in SHELL:
            continue
        d = cat.default_map()
        try:
            ok = float(d["outline_w_mm"]) > 0 and float(d["outline_h_mm"]) > 0 and float(d["outline_d_mm"]) > 0
        except (KeyError, ValueError):
            ok = False
        if not ok:
            missing.append(cat.id)
    assert not missing, missing


def test_pole_width_rule_and_catalog_fallback():
    cb = _from_catalog(1, "ab-1489-m3c200", "CB1")
    w, h = item_inches(LIB, cb)
    assert abs(w - 3 * 12.7 * MM) < 0.01 and abs(h - 90 * MM) < 0.01
    cb.fields["poles"] = "2"
    assert abs(item_inches(LIB, cb)[0] - 2 * 12.7 * MM) < 0.01
    bare = PlacedItem(id="x", library_id="ab-contactor-100c", type_id="contactor", x=0, y=0, fields={"tag": "M9"})
    assert abs(item_inches(LIB, bare)[0] - 45 * MM) < 0.01, "older saves fall back to the catalog outline"


EXPECTED = {
    "ab-compactlogix-5380": "plc", "ab-micro850": "plc", "ab-5069-ib16": "io_module",
    "siemens-sm1223": "io_module", "ab-1606-xls": "power_supply", "ab-contactor-100c": "contactor",
    "ab-140mt-c-b63": "motor_protector", "ab-1489-m1c100": "breaker", "ab-1492-fb3c30": "fuse_holder",
    "ab-194e-a40": "disconnect", "ab-1492-j3-strip": "terminal_block", "ab-relay-700ha": "relay",
    "ab-relay-700hlt": "relay", "ab-guardmaster-msr127": "safety_relay", "ab-1497-250": "transformer",
    "ab-stratix-2000": "ethernet_switch", "ab-powerflex-525-frame-a": "vfd", "ab-panelview-5310": "hmi",
    "ab-estop-800f-40mm": "estop", "ab-pb-green-start": "pushbutton", "ab-selector-hoa": "selector",
    "ab-indicator-green": "pilot_light", "ab-stack-855e": "stack_light",
    "ab-440l-guardshield-640": "light_curtain",
}


def test_shape_key_resolves_to_a_real_outline_per_type():
    project = _project()
    for n, (cat_id, shape) in enumerate(EXPECTED.items()):
        box = dw._layout_box(project, LIB, _from_catalog(100 + n, cat_id, f"X{n}"))
        assert dw._layout_shape_key(box) == shape, cat_id
        body = dw._layout_footprint_body(shape, 0, 0, 90, 140, box.layout_spec)
        assert f'data-shape="{shape}"' in body and body.count("<") >= 6, cat_id
        assert "<path" not in body and "<ellipse" not in body, "viewer paints rect/line/circle/polygon only"


def test_breaker_draws_one_slice_per_pole():
    one = dw._layout_footprint_body("breaker", 0, 0, 13, 90, {"poles": "1"})
    three = dw._layout_footprint_body("breaker", 0, 0, 38, 90, {"poles": "3"})
    assert one.count('fill="#d9d9d9"') == 1 and three.count('fill="#d9d9d9"') == 3


def test_layout_has_scale_bar_power_in_and_out_and_no_issues():
    project = _project()
    sheets = dw.build_sheets(project, LIB)
    layout = [s for s in sheets if s.kind == "layout"]
    plate = next(s for s in layout if "BACKPLATE" in s.title)
    svg = dw.render_svg(plate, project)
    for needle in ('class="scale-bar"', 'class="power-in"', 'class="power-path"', 'class="power-out"',
                   'class="power-out-path"', 'class="din-rail"', "POWER IN 480 VAC", "POWER OUT", "TB-OUT",
                   "PLATE ", "ENCLOSURE ", "mm</text>", dw.DISCLAIMER):
        assert needle in svg, needle
    assert any(b.key == dw.TB_OUT_KEY for b in plate.boxes)
    for s in layout:
        assert dw.drawing_issues(s) == [], s.title
        text = dw.render_svg(s, project)
        assert 'class="scale-bar"' in text
        for m in re.finditer(r'<text([^>]*)>([^<]*)</text>', text):
            attrs, body = m.groups()
            x = float(re.search(r' x="([-0-9.]+)"', attrs).group(1))
            y = float(re.search(r' y="([-0-9.]+)"', attrs).group(1))
            size = float((re.search(r'font-size="([0-9.]+)"', attrs) or [0, "11"])[1])
            assert 0 <= y <= dw.PAGE_H and 0 <= x <= dw.PAGE_W, body
            mine = re.search(r'class="(size-ref|run-label|power-step|fp-label)"', attrs)
            if mine and 'text-anchor' not in attrs:
                assert x + len(body) * size * 0.6 <= dw.PAGE_W, body


def test_sheet_order_and_schematics_carry_no_layout_markup():
    project = _project()
    sheets = dw.build_sheets(project, LIB)
    kinds = [s.kind for s in sheets if s.kind != "outline"]
    first = {k: kinds.index(k) for k in ("layout", "power", "control", dw.WIRE_SCHEDULE_KIND) if k in kinds}
    assert list(first) == sorted(first, key=first.get)
    assert list(first)[:3] == ["layout", "power", "control"]
    for s in sheets:
        if s.kind in {"power", "control"}:
            svg = dw.render_svg(s, project)
            assert not s.power_io
            for needle in ("layout-footprint", "scale-bar", "power-io", "din-rail", "fp-label"):
                assert needle not in svg, (s.title, needle)
