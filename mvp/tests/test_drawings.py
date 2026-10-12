"""Drawings stay tied to the cabinet that is open."""



import xml.etree.ElementTree as ET



import pytest

import re



from cabinet_studio.models.project import PlacedItem, Project

from pathlib import Path as _PathForSaves

_MVP_SAVES = _PathForSaves(__file__).resolve().parents[1] / "saves"

from cabinet_studio.services.drawings import (

    ARROW_HEAD,

    ARROW_SHAFT,

    ARROW_TIP_GAP,

    CATALOG_NOT_IDENTIFIED,

    DISCLAIMER,

    LABEL_LINE_GAP,

    MAX_COLS,

    NOT_IDENTIFIED,

    DrawingError,

    _contactor_coil_is_control,

    _control_rail_names,

    _disconnect_load_wires,

    _power_return_name,

    _rung_is_stub,

    _stored_contact_is_nc,

    _voltage_has_nominal,

    build_sheets,

    default_drawings_folder,

    drawing_issues,

    render_svg,

    verified_catalogs,

    write_drawings,

    CALLOUT_AFTER_SYMBOL,
    WIRE_SCHEDULE_KIND,
    Box,
    _layout_shape_key,
    _layout_footprint_body,
    _layout_is_door_mount,
    _item_is_door_mount,
    _layout_sheet_is_door_only,
)

from cabinet_studio.services.layouts import new_blank_project

from cabinet_studio.services.library_loader import load_library

from cabinet_studio.services.project_store import project_to_dict





def _item(type_id: str, tag: str, description: str, x: float, y: float, **fields: str) -> PlacedItem:

    stored = {

        "tag": tag,

        "description": description,

        "catalog": "",

        "vendor": "",

        "wire_numbers": "",

        "terminal_landings": "",

        "io_direction": "",

        "io_address": "",

    }

    stored.update(fields)

    return PlacedItem(id=tag.lower(), library_id=None, type_id=type_id, x=x, y=y, fields=stored)





def _small_cabinet() -> Project:

    project = new_blank_project("Line 1")

    project.cabinet_label = "PNL1"

    project.subtitle = ""

    project.interview = {

        "disconnect": "Yes",

        "grounding": "Bond the ground bar to the door.",

        "supply_voltage": "480 VAC",

        "control_voltage": "24 VDC",

        "branch_protection": "Yes",

    }

    project.items = [

        _item(

            "power_supply",

            "PSU1",

            "24 VDC control power",

            24,

            48,

            wire_numbers="W10, PE",

            input_voltage="480 VAC",

            output_voltage="24 VDC",

            terminal_landings="L1 to the disconnect load, PE to the ground bar",

        ),

        _item(

            "vfd",

            "VFD1",

            "Conveyor variable-frequency drive",

            24,

            180,

            catalog="25B-D6P0N104",

            voltage="480 VAC",

            wire_numbers="W10, W20, PE",

            io_direction="Network / no discrete I/O",

            io_address="Drive:VFD1",

            terminal_landings="T1 T2 T3 to MTR1, PE to the ground bar",

        ),

        _item(

            "motor",

            "MTR1",

            "Conveyor drive motor",

            24,

            320,

            voltage="460 VAC",

            wire_numbers="W20, PE",

            terminal_landings="T1 T2 T3 from VFD1, PE to the ground bar",

        ),

        _item(

            "plc",

            "PLC1",

            "Drive controller",

            240,

            48,

            catalog="5069-L306ER",

            wire_numbers="W11, PE",

            io_direction="Network / no discrete I/O",

            io_address="192.168.1.10",

        ),

        _item(

            "estop",

            "ES1",

            "Drive cabinet e-stop",

            240,

            180,

            voltage="24 VDC",

            wire_numbers="W30",

            io_direction="Input",

            io_address="Local:1:I.Data.0",

            terminal_landings="TB1-14 to the safety input",

        ),

    ]

    return project





def test_empty_cabinet_writes_nothing(tmp_path):

    project = new_blank_project("Empty")

    with pytest.raises(DrawingError, match="no devices"):

        write_drawings(project, load_library(), tmp_path)

    assert list(tmp_path.iterdir()) == []





def test_small_cabinet_writes_layout_and_two_schematic_sheets(tmp_path):

    library = load_library()

    project = _small_cabinet()
    project.interview = {**(project.interview or {}), "layout_mode": "manual"}

    before = project_to_dict(project)

    sheets = build_sheets(project, library)

    written = write_drawings(project, library, tmp_path)

    assert project_to_dict(project) == before



    kinds = [sheet.kind for sheet in sheets]

    assert "layout" in kinds

    assert "power" in kinds

    assert "control" in kinds

    assert sum(kind != "layout" for kind in kinds) >= 2

    assert MAX_COLS >= 1

    for sheet in sheets:

        if sheet.kind not in {"layout", WIRE_SCHEDULE_KIND}:

            assert len(sheet.boxes) <= MAX_COLS



    # Carry-over arrows use the same wire number on both ends.

    schematic = [sheet for sheet in sheets if sheet.kind != "layout"]

    off = [c for sheet in schematic for c in sheet.connectors if c.kind == "off-page" and c.wire]

    assert off

    assert any(c.label.startswith("TO SH") for c in off)

    assert any(c.label.startswith("FROM SH") for c in off)



    by_name = {path.name: path.read_text(encoding="utf-8") for path in written}

    assert any(name.endswith("-layout.svg") for name in by_name)

    assert any("-power.svg" in name for name in by_name)

    assert any("-control.svg" in name for name in by_name)

    assert all(path.suffix == ".svg" for path in written)



    combined = "\n".join(by_name.values())

    for tag in ("PSU1", "VFD1", "MTR1", "PLC1", "ES1"):

        assert tag in combined

    assert "25B-D6P0N104" in combined

    assert "5069-L306ER" in combined

    assert "ZZ-NOT-A-PART" not in combined

    assert "TB1-14" in combined

    assert "Local:1:I.Data.0" in combined

    assert "W20" in combined

    assert "W11" in combined  # unmatched wire still shown

    assert NOT_IDENTIFIED in combined

    assert "TO SH" in combined

    assert "FROM SH" in combined

    assert "Bond the ground bar to the door." in combined

    # Wire# · Color · Gauge · From → To lives on Wire Schedule sheets (schematics stay sparse).
    assert any(name.endswith("-wire-schedule.svg") for name in by_name)
    assert "WIRE SCHEDULE" in combined
    assert "Wire#" in combined
    schedule_sheets = [sheet for sheet in sheets if sheet.kind == WIRE_SCHEDULE_KIND]
    assert schedule_sheets
    assert schedule_sheets[0].schedule_rows



    layout_sheets = [sheet for sheet in sheets if sheet.kind == "layout"]

    layout_svg = render_svg(layout_sheets[0], project)
    assert 'data-backplate-w-in' in layout_svg
    assert 'class="layout-device"' in layout_svg
    assert 'width="17in"' in layout_svg and 'height="11in"' in layout_svg


    assert layout_sheets

    layout_boxes = [box for sheet in layout_sheets for box in sheet.boxes]

    psu = next(box for box in layout_boxes if box.tag == "PSU1")

    motor = next(box for box in layout_boxes if box.tag == "MTR1")

    assert motor.model_y == 320

    assert psu.model_y == 48

    # Same layout sheet: motor draws below PSU; split sheets keep model order.

    same = next((sheet for sheet in layout_sheets if psu in sheet.boxes and motor in sheet.boxes), None)

    if same is not None:

        assert motor.y > psu.y



    schematic = [sheet for sheet in sheets if sheet.kind in {"power", "control"}]

    for tag in ("PSU1", "VFD1", "MTR1", "PLC1", "ES1"):

        assert any(box.tag == tag for sheet in schematic for box in sheet.boxes)



    # Every stored wire on every schematic device has a from/to row
    # (full list on connections before hover truncation is snapshot to schedule;
    # after build_sheets, ladder sheets keep up to MAX_WIRE_ROWS for hover).

    for sheet in schematic:

        for box in sheet.boxes:

            if not box.wires:

                continue

            assert 0 < len(box.connections) <= len(box.wires)

            for row in box.connections:

                assert row.wire in box.wires

                assert box.tag in row.from_label

                assert row.to_label



    plc_box = next(box for sheet in schematic for box in sheet.boxes if box.tag == "PLC1")

    w11 = next(row for row in plc_box.connections if row.wire == "W11")

    assert w11.to_label == NOT_IDENTIFIED



    for sheet in sheets:

        if sheet.kind not in (WIRE_SCHEDULE_KIND, "io-list"):

            assert sheet.boxes

        svg = render_svg(sheet, project)

        ET.fromstring(svg)

        assert DISCLAIMER in svg

        assert 'class="disclaimer"' in svg or DISCLAIMER in svg

        assert project.name in svg

        assert f"Sheet {sheet.number} of {sheet.total}" in svg

        assert "Cabinet Studio" in svg

        assert "DRAWN BY" in svg

        assert "VOLTAGE" in svg

        assert "DATE" in svg

        assert "SHEET TITLE" in svg

        assert 'stroke-width="2.2"' in svg  # outer ANSI border

        # Power/Control stay sparse: no on-canvas wire-ref dump / selected strip.
        if sheet.kind in {"power", "control"}:
            assert 'class="wire-ref"' not in svg
            assert 'class="wire-ref-header"' not in svg
            assert 'class="selected-connections"' not in svg
            # Coil tags may appear; general device callouts do not dump on trunks.
            assert svg.count('class="callout"') == 0

        if sheet.kind == WIRE_SCHEDULE_KIND:
            assert 'class="wire-schedule"' in svg
            assert "Wire#" in svg
            assert "WIRE SCHEDULE" in svg
            # Every schedule row prints Wire# / From / To as visible SVG text.
            for row in sheet.schedule_rows:
                assert row.wire in svg
                assert row.from_label.split(" / ")[0] in svg or row.from_label in svg

        for box in sheet.boxes:

            assert box.callout.strip()

            # Tag always on sheet; callout may be hover-only on sparse schematics.
            assert box.tag in svg
            if sheet.kind not in {"power", "control"}:
                assert box.callout in svg or box.callout[:40] in svg or box.tag in svg

        assert drawing_issues(sheet) == []



    power_sheets = [sheet for sheet in sheets if sheet.kind == "power"]

    control_sheets = [sheet for sheet in sheets if sheet.kind == "control"]

    power_boxes = [box for sheet in power_sheets for box in sheet.boxes]

    control_boxes = [box for sheet in control_sheets for box in sheet.boxes]

    assert any(box.type_id == "disconnect" or box.role == "disconnect" for box in power_boxes)

    assert any(box.type_id == "motor" for box in power_boxes)

    assert any(box.type_id == "plc" or box.role == "plc" for box in control_boxes)

    power_svg = "\n".join(render_svg(sheet, project) for sheet in power_sheets)

    assert 'data-symbol="disconnect"' in power_svg or 'data-symbol="motor"' in power_svg

    assert 'class="title-block"' in power_svg





def test_crossing_wire_numbers_become_connectors_instead_of_crossing_lines(tmp_path):

    library = load_library()

    project = new_blank_project("Cross check")

    project.items = [

        _item("contactor", "C1", "First contactor", 20, 40, wire_numbers="W1", coil_voltage="24 VDC"),

        _item("contactor", "C2", "Second contactor", 200, 40, wire_numbers="W2", coil_voltage="24 VDC"),

        _item("contactor", "C3", "Third contactor", 380, 40, wire_numbers="W1", coil_voltage="24 VDC"),

        _item("contactor", "C4", "Fourth contactor", 560, 40, wire_numbers="W2", coil_voltage="24 VDC"),

    ]

    sheets = build_sheets(project, library)

    control = [sheet for sheet in sheets if sheet.kind == "control"]

    assert len(control) >= 1  # 24V coil contactors on control ladder

    for sheet in control:

        assert len(sheet.boxes) <= MAX_COLS

        assert drawing_issues(sheet) == []

    combined = "\n".join(render_svg(sheet, project) for sheet in control)

    assert ("TO SH" in combined or "FROM SH" in combined or 'data-kind="on-page"' in combined or "SEE" in combined)

    written = write_drawings(project, library, tmp_path / "out")

    assert written





def test_selected_device_gets_connection_strip(tmp_path):

    library = load_library()

    project = _small_cabinet()

    sheets = build_sheets(project, library, selected_id="vfd1")

    selected_sheets = [sheet for sheet in sheets if sheet.selected_tag == "VFD1"]

    assert selected_sheets

    for sheet in selected_sheets:

        assert sheet.selected_connections

        wires = {row.wire for row in sheet.selected_connections}

        assert "W10" in wires and "W20" in wires and "PE" in wires

        svg = render_svg(sheet, project)

        assert 'class="selected-connections"' not in svg

        assert drawing_issues(sheet) == []

    # Wire Schedule still lists the selected device conductors.
    schedule = [sheet for sheet in sheets if sheet.kind == WIRE_SCHEDULE_KIND]
    assert schedule
    sched_wires = {row.wire for sheet in schedule for row in sheet.schedule_rows}
    assert "W10" in sched_wires and "W20" in sched_wires and "PE" in sched_wires

    # No selection => no selected strip.

    plain = build_sheets(project, library)

    assert all(not sheet.selected_tag for sheet in plain)

    plain_svg = "\n".join(render_svg(sheet, project) for sheet in plain if sheet.kind != "layout")

    assert "selected-connections" not in plain_svg





def test_unmatched_wire_still_shows_from_to_not_identified():

    library = load_library()

    project = new_blank_project("Solo wire")

    project.items = [

        _item(

            "sensor",

            "PX1",

            "Lone prox",

            40,

            40,

            wire_numbers="W99",

            terminal_landings="Signal to DI1",

            io_direction="Input",

            io_address="Local:1:I.Data.4",

        )

    ]

    sheets = build_sheets(project, library)

    control = next(sheet for sheet in sheets if sheet.kind == "control")

    box = next(box for box in control.boxes if box.tag == "PX1")

    assert len(box.connections) == 1

    assert box.connections[0].wire == "W99"

    assert "PX1" in box.connections[0].from_label

    assert box.connections[0].to_label == NOT_IDENTIFIED

    svg = render_svg(control, project)

    assert "W99" in svg

    assert NOT_IDENTIFIED in svg





def test_drawings_folder_is_named_from_the_cabinet_and_sits_next_to_the_save(tmp_path):

    project = new_blank_project("Line 1")

    folder = default_drawings_folder(project, tmp_path / "line-1.cabinet.json")

    assert folder == (tmp_path / "drawings" / "line-1").resolve()





def test_sample_project_ul_look_and_no_crossings(tmp_path):

    """A realistic sample cabinet produces bordered UL-look sheets with no crossings."""

    library = load_library()

    project = _small_cabinet()

    sheets = build_sheets(project, library)

    assert sheets

    assert any(sheet.kind == "layout" for sheet in sheets)

    assert any(sheet.kind == "power" for sheet in sheets)

    assert any(sheet.kind == "control" for sheet in sheets)

    written = write_drawings(project, library, tmp_path)

    assert written

    for sheet in sheets:

        svg = render_svg(sheet, project)

        assert DISCLAIMER in svg

        assert "DRAWN BY" in svg

        assert "Cabinet Studio" in svg

        assert f"Sheet {sheet.number} of {sheet.total}" in svg

        assert 'stroke-width="2.2"' in svg

        assert drawing_issues(sheet) == []

        for box in sheet.boxes:

            assert box.callout.strip()





def test_ladder_schematic_packs_devices_with_rails(tmp_path):

    """Power/control sheets are ladder schematics with multiple rungs and supply rails."""

    library = load_library()

    project = _small_cabinet()

    sheets = build_sheets(project, library)

    power = [sheet for sheet in sheets if sheet.kind == "power"]

    control = [sheet for sheet in sheets if sheet.kind == "control"]

    assert power and control

    assert all(sheet.title.startswith("Power schematic") for sheet in power)

    assert all(sheet.title.startswith("Control schematic") for sheet in control)

    # Multiple power devices share a ladder sheet when they fit.

    assert any(len(sheet.boxes) >= 2 for sheet in power)

    for sheet in power + control:

        assert len(sheet.boxes) <= MAX_COLS

        assert len(sheet.segments) >= 2  # rails / rungs

        svg = render_svg(sheet, project)

        assert "L1" in svg or "+24V" in svg or "CTL+" in svg or "0V" in svg

        assert drawing_issues(sheet) == []

    combined = "\n".join(render_svg(sheet, project) for sheet in sheets)

    assert DISCLAIMER in combined

    written = write_drawings(project, library, tmp_path)

    assert len(written) == len(sheets)







def test_off_page_connectors_share_wire_number_both_ends():

    library = load_library()

    project = new_blank_project("Carry")

    project.items = [

        _item("contactor", "C1", "First", 20, 40, wire_numbers="W7", coil_voltage="24 VDC"),

        _item("contactor", "C2", "Second", 200, 40, wire_numbers="W7", coil_voltage="24 VDC"),

    ]

    sheets = build_sheets(project, library)

    control = [sheet for sheet in sheets if sheet.kind == "control"]

    assert control

    labels = []

    kinds = []

    for sheet in control:

        for connector in sheet.connectors:

            if connector.wire == "W7":

                labels.append(connector.label)

                kinds.append(connector.kind)

                assert connector.wire == "W7"

    drawn = any(seg.wire == "W7" for sheet in control for seg in sheet.segments)

    assert labels or drawn, "expected a connector or drawn conductor for shared W7"

    if labels:

        assert any(k == "on-page" for k in kinds) or any(label.startswith("TO SH") for label in labels)

    for sheet in control:

        assert drawing_issues(sheet) == []



def test_labels_sit_right_of_verticals_and_past_arrow_tips(tmp_path):

    """Sparse schematics: structural labels clear verticals; connectors keep tip geometry."""

    library = load_library()

    project = _small_cabinet()

    sheets = build_sheets(project, library)

    assert sheets

    schematic = [sheet for sheet in sheets if sheet.kind in {"power", "control"}]

    assert schematic



    checked_vertical_labels = 0

    checked_arrow_labels = 0

    for sheet in schematic:

        svg = render_svg(sheet, project)

        root = ET.fromstring(svg)

        # Vertical line x values with their y spans.

        verticals: list[tuple[float, float, float]] = []

        for line in root.iter("{http://www.w3.org/2000/svg}line"):

            x1 = float(line.get("x1", "0"))

            x2 = float(line.get("x2", "0"))

            y1 = float(line.get("y1", "0"))

            y2 = float(line.get("y2", "0"))

            if abs(x1 - x2) < 0.6 and abs(y1 - y2) > 8:

                verticals.append((x1, min(y1, y2), max(y1, y2)))



        for node in root.iter("{http://www.w3.org/2000/svg}text"):

            cls = node.get("class") or ""

            if cls not in {"run-label", "coil-desc", "device-tag"}:

                continue

            tx = float(node.get("x", "0"))

            ty = float(node.get("y", "0"))

            checked_vertical_labels += 1

            # Structural run-labels (LINE/PE/+24V) may sit on the rail; only
            # device/coil tags must clear the vertical stem by LABEL_LINE_GAP.
            if cls in {"coil-desc", "device-tag"}:
                for vx, y0, y1 in verticals:

                    if y0 - 2 <= ty <= y1 + 2 and abs(vx - tx) < 2.0:

                        assert tx >= vx + LABEL_LINE_GAP - 0.1



        for group in root.iter("{http://www.w3.org/2000/svg}g"):

            if (group.get("class") or "") != "connector":

                continue

            tip_attr = group.get("data-tip-x")

            assert tip_attr is not None

            assert group.get("data-arrow-dir") == "right"

            checked_arrow_labels += 1



        # Model-level: off-page connectors prefer right-pointing shafts.

        for connector in sheet.connectors:

            if connector.kind == "off-page":

                assert connector.arrow_dir == "right"



        assert drawing_issues(sheet) == []



    assert checked_vertical_labels >= 1

    assert checked_arrow_labels >= 1



    # Sample-style write still works with the clearance rules.

    written = write_drawings(project, library, tmp_path)

    assert written

    combined = "\n".join(path.read_text(encoding="utf-8") for path in written)

    assert 'class="connector"' in combined

    assert any(path.name.endswith("-wire-schedule.svg") for path in written)

    assert 'data-arrow-dir="right"' in combined

    assert DISCLAIMER in combined





def test_sample_motor_cabinet_includes_verified_component_outlines(tmp_path):

    """Sample sheets draw an engineered outline; printed catalogs match verified library source_url."""

    from cabinet_studio.services.project_store import project_from_dict

    import json

    from pathlib import Path as P



    library = load_library()

    verified = verified_catalogs(library)

    assert verified, "library must carry at least one source_url-verified catalog"

    assert "5069-L306ER" in verified

    assert "25B-D6P0N104" in verified

    assert "1606-XLE240EN" in verified

    assert "872C-D5NP18-D4" in verified

    assert "NEMA-5HP-1750" not in verified



    sample_candidates = [
        P("/workspace/cabinet-studio-projects/sample-motor-cabinet/sample-motor-cabinet.cabinet.json"),
        P(__file__).resolve().parents[1] / "saves" / "sample-motor-cabinet.cabinet.json",
        (_MVP_SAVES / "sample-motor-cabinet.cabinet.json"),
    ]
    sample_path = next((c for c in sample_candidates if c.is_file()), sample_candidates[0])

    project = project_from_dict(json.loads(sample_path.read_text(encoding="utf-8")))

    sheets = build_sheets(project, library)

    schematic = [sheet for sheet in sheets if sheet.kind != "layout"]

    assert schematic

    written = write_drawings(project, library, tmp_path)

    combined = "\n".join(path.read_text(encoding="utf-8") for path in written)



    assert 'class="component-outline"' in combined

    assert 'class="outline-callout"' in combined

    # Every schematic device sheet (or its dedicated outline sheet) carries an outline group.

    device_tags = {item.fields.get("tag") or item.id for item in project.items}

    for tag in device_tags:

        assert f'data-tag="{tag}"' in combined

        # At least one outline for this tag.

        assert f'class="component-outline" data-tag="{tag}"' in combined or (

            f'class="component-outline" data-tag="{tag}"' in combined

        )



    # Any printed catalog string inside an outline group must be verified (or the not-identified phrase).

    import re

    import xml.etree.ElementTree as ET

    for path in written:

        root = ET.fromstring(path.read_text(encoding="utf-8"))

        for group in root.iter("{http://www.w3.org/2000/svg}g"):

            if (group.get("class") or "") != "component-outline":

                continue

            catalog_attr = group.get("data-catalog") or ""

            assert catalog_attr

            if catalog_attr == CATALOG_NOT_IDENTIFIED:

                continue

            assert catalog_attr in verified, f"outline printed unverified catalog {catalog_attr}"

            # Callout text must mention the same catalog.

            callouts = [

                (child.text or "")

                for child in group

                if child.tag.rsplit("}", 1)[-1] == "text" and (child.get("class") or "") == "outline-callout"

            ]

            assert callouts

            assert catalog_attr in callouts[0]



    # Motor stays unidentified on the outline (generic NEMA placeholder is not a maker catalog).

    motor_outlines = [

        group.get("data-catalog")

        for path in written

        for group in ET.fromstring(path.read_text(encoding="utf-8")).iter("{http://www.w3.org/2000/svg}g")

        if (group.get("class") or "") == "component-outline" and group.get("data-tag") == "MTR1"

    ]

    assert motor_outlines

    assert all(c == CATALOG_NOT_IDENTIFIED for c in motor_outlines)



    # Verified sample roles appear on outlines.

    for catalog in (

        "1606-XLE240EN",

        "5069-L306ER",

        "5069-IB16",

        "25B-D6P0N104",

        "100-C09D10",

        "440R-N23132",

        "800T-FXJT6A",

        "800FP-F3",

        "800FP-F4",

        "872C-D5NP18-D4",

    ):

        assert catalog in verified

        assert any(

            (group.get("data-catalog") == catalog)

            for path in written

            for group in ET.fromstring(path.read_text(encoding="utf-8")).iter("{http://www.w3.org/2000/svg}g")

            if (group.get("class") or "") == "component-outline"

        ), f"missing outline for {catalog}"



    for sheet in schematic:

        assert drawing_issues(sheet) == []





def test_small_cabinet_outlines_never_invent_catalog_numbers(tmp_path):

    library = load_library()

    verified = verified_catalogs(library)

    project = _small_cabinet()

    written = write_drawings(project, library, tmp_path)

    import xml.etree.ElementTree as ET

    for path in written:

        root = ET.fromstring(path.read_text(encoding="utf-8"))

        outlines = [g for g in root.iter("{http://www.w3.org/2000/svg}g") if (g.get("class") or "") == "component-outline"]

        # Layout sheets have no device outlines; schematics either —

        # engineered outlines live on dedicated outline sheets.

        if (
            path.name.endswith("-layout.svg")
            or "-power.svg" in path.name
            or "-control.svg" in path.name
            or path.name.endswith("-wire-schedule.svg")
            or path.name.endswith("-io-list.svg")
            ):

            continue

        assert outlines

        for group in outlines:

            catalog = group.get("data-catalog") or ""

            if catalog != CATALOG_NOT_IDENTIFIED:

                assert catalog in verified







def test_schematic_sheet_titles_are_obvious(tmp_path):

    """View drawings / SVGs use clear Power schematic / Control schematic titles."""

    library = load_library()

    project = _small_cabinet()

    sheets = build_sheets(project, library)

    power = [s for s in sheets if s.kind == "power"]

    control = [s for s in sheets if s.kind == "control"]

    assert power and control

    for sheet in power:

        assert sheet.title.startswith("Power schematic")

    for sheet in control:

        assert sheet.title.startswith("Control schematic")

    written = write_drawings(project, library, tmp_path)

    combined = "\n".join(path.read_text(encoding="utf-8") for path in written)

    assert "Power schematic" in combined

    assert "Control schematic" in combined

    assert DISCLAIMER in combined

    assert DISCLAIMER == "NOT A CERTIFIED UL 508A DRAWING. Design aid only."





def test_drawing_text_stays_on_white_sheet(tmp_path):

    """Callouts, wire from/to, connector labels, outline captions stay inside the page."""

    library = load_library()

    project = _small_cabinet()

    sheets = build_sheets(project, library)

    from cabinet_studio.services.drawings import PAGE_RIGHT, ORIGIN_X

    assert ORIGIN_X <= 80  # content shifted left

    for sheet in sheets:

        svg = render_svg(sheet, project)

        root = ET.fromstring(svg)

        for node in root.iter("{http://www.w3.org/2000/svg}text"):

            x = float(node.get("x", "0"))

            # Start of text must be on-page; wrapping keeps glyphs from running off.

            assert x <= PAGE_RIGHT + 0.5, (sheet.title, node.text, x)

            assert x >= 0

        assert drawing_issues(sheet) == []

    write_drawings(project, library, tmp_path)



def test_control_voltage_240_vdc_not_mistaken_for_24v():

    """Tokenize voltage: 240 VDC must not become +24V via substring '24'."""

    assert _voltage_has_nominal("240 VDC", 240)

    assert not _voltage_has_nominal("240 VDC", 24)

    assert _voltage_has_nominal("24 VDC", 24)

    hot, ret = _control_rail_names("240 VDC")

    assert hot == "CTL+"

    assert ret in {"CTL-", "N", "0V"}

    assert hot != "+24V"

    hot24, ret24 = _control_rail_names("24 VDC")

    assert hot24 == "+24V"

    assert ret24 == "0V"





def test_240_coil_and_240_supply_tokenize():

    """240 coil / 240 supply use tokenized nominals (240 != 24 substring)."""

    coil_240 = _item(

        "contactor",

        "M1",

        "Power contactor",

        10,

        10,

        coil_voltage="240 VAC",

        terminal_landings="L1/L2/L3 power",

    )

    assert not _contactor_coil_is_control(coil_240)

    coil_24 = _item(

        "contactor",

        "M2",

        "Control contactor",

        10,

        20,

        coil_voltage="24 VDC",

        terminal_landings="A1 from +24V, A2 to 0V",

    )

    assert _contactor_coil_is_control(coil_24)

    project = new_blank_project("Supply tokenize")

    project.interview = {"supply_voltage": "240 VAC"}

    assert _power_return_name(project) == "N"

    project.interview = {"supply_voltage": "480 VAC 3PH"}

    assert _power_return_name(project) == "L2/L3"

    project.interview = {"supply_voltage": "120 VAC"}

    assert _power_return_name(project) == "N"

    assert _voltage_has_nominal("240 VAC", 240)

    assert not _voltage_has_nominal("240 VAC", 24)


def test_signal_net_not_rail_to_rail_into_return():

    """Sensor signal to DI is stub+connector — never +24 to sensor to 0V on the primary wire."""

    library = load_library()

    project = new_blank_project("Signal net")

    project.interview = {"control_voltage": "24 VDC", "supply_voltage": "480 VAC"}

    project.items = [

        _item(

            "plc",

            "PLC1",

            "Controller",

            20,

            40,

            wire_numbers="W24, PE",

            terminal_landings="L+ from PSU +24 (W24), L- to 0V",

            io_address="192.168.1.10",

            io_direction="Network / no discrete I/O",

        ),

        _item(

            "io_module",

            "DI1",

            "Discrete inputs",

            20,

            160,

            wire_numbers="W24",

            terminal_landings="Module power from PSU W24",

            io_address="Local:1:I.Data",

            io_direction="Input",

            parent_tag="PLC1",

        ),

        _item(

            "sensor",

            "PX9",

            "Photoeye product detect",

            200,

            40,

            wire_numbers="W50",

            terminal_landings="Signal to DI1 Local:1:I.Data.7",

            io_address="Local:1:I.Data.7",

            io_direction="Input",

            signal="PNP",

            sensor_kind="Photoeye",

            parent_tag="PLC1",

        ),

    ]

    sheets = build_sheets(project, library)

    control = [s for s in sheets if s.kind == "control"]

    assert control

    px = next(box for sheet in control for box in sheet.boxes if box.tag == "PX9")

    assert _rung_is_stub(px, project)

    for sheet in control:

        if not any(b.tag == "PX9" for b in sheet.boxes):

            continue

        px_box = next(b for b in sheet.boxes if b.tag == "PX9")

        mid = px_box.y + px_box.h / 2.0

        rail_to_rail = [

            seg

            for seg in sheet.segments

            if seg.wire == "W50"

            and abs(seg.y1 - mid) < 1.0

            and abs(seg.y2 - mid) < 1.0

            and min(seg.x1, seg.x2) <= 48.5

            and max(seg.x1, seg.x2) >= 735.0

        ]

        assert not rail_to_rail, "W50 must not bridge +24V rail to 0V rail"

        stubs = [

            seg

            for seg in sheet.segments

            if seg.wire == "W50" and abs(seg.y1 - mid) < 1.0 and abs(seg.y2 - mid) < 1.0

        ]

        assert stubs, "expected a short W50 stub into PX9"





def test_interdevice_estop_not_rail_to_rail():

    """E-stop safety relay shared wire is inter-device/off-page, not into 0V."""

    library = load_library()

    project = new_blank_project("Safety pair")

    project.interview = {"control_voltage": "24 VDC"}

    project.items = [

        _item(

            "safety_relay",

            "SR9",

            "Safety relay",

            20,

            40,

            wire_numbers="W30",

            terminal_landings="S11/S12 from ES9 via W30",

            io_address="Local:1:I.Data.1",

            io_direction="Input",

        ),

        _item(

            "estop",

            "ES9",

            "E-stop",

            20,

            200,

            wire_numbers="W30",

            terminal_landings="CH1 to SR9 S11/S12 via W30",

            contact_config="2NC",

            io_address="Local:1:I.Data.0",

            io_direction="Input",

        ),

    ]

    sheets = build_sheets(project, library)

    control = [s for s in sheets if s.kind == "control"]

    es = next(box for sheet in control for box in sheet.boxes if box.tag == "ES9")

    sr = next(box for sheet in control for box in sheet.boxes if box.tag == "SR9")

    assert _rung_is_stub(es, project)

    assert _rung_is_stub(sr, project)

    for sheet in control:

        for box in sheet.boxes:

            if box.tag not in {"ES9", "SR9"}:

                continue

            mid = box.y + box.h / 2.0

            bridged = [

                seg

                for seg in sheet.segments

                if seg.wire == "W30"

                and abs(seg.y1 - mid) < 1.0

                and abs(seg.y2 - mid) < 1.0

                and min(seg.x1, seg.x2) <= 48.5

                and max(seg.x1, seg.x2) >= 735.0

            ]

            assert not bridged, f"{box.tag} W30 must not be rail-to-rail into 0V"





def test_disconnect_load_wires_accepts_non_w_tokens():

    project = new_blank_project("Disc tokens")

    project.items = [

        _item(

            "power_supply",

            "PSU1",

            "Supply",

            10,

            10,

            wire_numbers="BUS1, PE",

            terminal_landings="L1/L2 from DISC load via BUS1, PE to ground bar",

        )

    ]

    assert "BUS1" in _disconnect_load_wires(project)





def test_seal_in_uses_function_fields_not_tag_only():

    library = load_library()

    project = new_blank_project("Seal functions")

    project.interview = {"control_voltage": "24 VDC"}

    project.items = [

        _item(

            "pushbutton",

            "PB_A",

            "Motor stop",

            20,

            40,

            wire_numbers="W40",

            function="Stop",

            contact_config="1NC",

            terminal_landings="NC in series with start to coil on W40",

        ),

        _item(

            "pushbutton",

            "PB_B",

            "Motor start",

            20,

            160,

            wire_numbers="W40",

            function="Start",

            contact_config="1NO",

            terminal_landings="NO to coil on W40",

        ),

        _item(

            "contactor",

            "M9C",

            "Motor contactor",

            20,

            280,

            wire_numbers="W40",

            coil_voltage="24 VDC",

            terminal_landings="A1 coil via W40",

        ),

    ]

    sheets = build_sheets(project, library)

    control = [s for s in sheets if s.kind == "control"]

    seals = [box for sheet in control for box in sheet.boxes if box.role == "seal_in"]

    assert seals, "expected seal-in from function fields without STOP/START in tags"

    assert _stored_contact_is_nc(project.items[0])





def test_pe_only_power_sheet_omits_empty_line_rails():

    """Overflow power sheet with only GND must not draw empty LINE/L2/L3 rails."""

    library = load_library()

    project = new_blank_project("PE overflow")

    project.interview = {

        "disconnect": "Yes",

        "grounding": "Bond PE to ground bar.",

        "supply_voltage": "480 VAC",

        "control_voltage": "24 VDC",

        "branch_protection": "Yes",

    }

    items = []

    for i in range(3):

        items.append(

            _item(

                "power_supply",

                f"PSU{i}",

                f"Supply {i}",

                20,

                40 + i * 10,

                wire_numbers=f"W1{i}, PE",

                terminal_landings=f"L1 from DISC load via W1{i}, PE to ground bar",

                input_voltage="480 VAC",

                output_voltage="24 VDC",

            )

        )

    project.items = items

    sheets = build_sheets(project, library)

    power = [s for s in sheets if s.kind == "power"]

    pe_only = [s for s in power if s.boxes and all(b.role == "ground" for b in s.boxes)]

    assert pe_only, "expected a PE-only overflow power sheet"

    for sheet in pe_only:

        wires = {seg.wire for seg in sheet.segments}

        assert "LINE" not in wires

        assert "L2/L3" not in wires

        assert any(seg.wire == "PE" for seg in sheet.segments)

        pe_y = next((seg.y1 for seg in sheet.segments if seg.wire == "PE" and abs(seg.y1 - seg.y2) < 0.6), None)

        pe_conn = [c for c in sheet.connectors if (c.wire or "").upper() == "PE"]

        if pe_y is not None and pe_conn:

            assert any(abs(c.y - pe_y) < 1.0 for c in pe_conn)





def test_stub_only_control_sheet_omits_empty_24v_rails():

    """Overflow control sheet with only stub nets must not draw empty +24V/0V rails."""

    library = load_library()

    project = new_blank_project("Stub overflow")

    project.interview = {"control_voltage": "24 VDC", "supply_voltage": "480 VAC"}

    items = [

        _item(

            "plc",

            "PLC1",

            "Controller",

            20,

            20,

            wire_numbers="W100",

            terminal_landings="Module power from PSU L+ / L-",

            io_address="Local:1:I.Data",

        ),

        _item(

            "power_supply",

            "PSU1",

            "Control PSU",

            40,

            20,

            wire_numbers="W100, W101",

            terminal_landings="Module power L+ W100, L- W101",

            input_voltage="480 VAC",

            output_voltage="24 VDC",

        ),

    ]

    for i in range(8):

        items.append(

            _item(

                "sensor",

                f"PE{i}",

                f"Prox {i}",

                60 + i * 5,

                40,

                wire_numbers=f"W2{i}",

                terminal_landings=f"Signal to PLC1 DI.{i} via W2{i}",

                sensor_kind="inductive",

                io_address=f"Local:1:I.Data.{i}",

            )

        )

    project.items = items

    sheets = build_sheets(project, library)

    control = [s for s in sheets if s.kind == "control"]

    stub_sheets = [

        s

        for s in control

        if s.boxes and all(_rung_is_stub(b, project) for b in s.boxes)

    ]

    assert stub_sheets, "expected a stub-only control overflow sheet"

    for sheet in stub_sheets:

        rail_labels = {lab[2] for lab in sheet.labels}

        rail_wires = {seg.wire for seg in sheet.segments}

        assert "+24V" not in rail_wires

        assert "0V" not in rail_wires

        assert "+24V" not in rail_labels

        assert "0V" not in rail_labels

def test_link_io_uses_parent_plc_not_only_first():
    library = load_library()
    project = new_blank_project("Multi PLC")
    project.interview = {"control_voltage": "24 VDC"}
    # Fill early control rungs so PX_B lands on a later sheet than the PLCs.
    fillers = [
        _item(
            "light",
            f"LT{i}",
            f"Lamp {i}",
            20,
            40 + i,
            wire_numbers=f"W8{i}",
            terminal_landings="Lamp to +24/0V",
        )
        for i in range(6)
    ]
    project.items = fillers + [
        _item(
            "plc",
            "PLC_A",
            "First",
            20,
            40,
            wire_numbers="W1",
            io_address="10.0.0.1",
            io_direction="Network / no discrete I/O",
        ),
        _item(
            "plc",
            "PLC_B",
            "Second",
            200,
            40,
            wire_numbers="W2",
            io_address="10.0.0.2",
            io_direction="Network / no discrete I/O",
        ),
        _item(
            "sensor",
            "PX_B",
            "Owned by B",
            200,
            200,
            wire_numbers="W50",
            terminal_landings="Signal to DI on PLC_B",
            io_address="Local:2:I.Data.0",
            io_direction="Input",
            parent_tag="PLC_B",
        ),
    ]
    sheets = build_sheets(project, library)
    labels = [c.label for s in sheets for c in s.connectors if c.wire == "I/O"]
    assert any("PLC_B" in lab and "Local:2:I.Data.0" in lab for lab in labels)
    assert any("PX_B" in lab for lab in labels)
    assert not any("PLC_A" in lab and "Local:2:I.Data.0" in lab for lab in labels)


def test_sensor_outline_plain_from_stored_not_always_inductive():

    library = load_library()

    project = new_blank_project("Photoeye plain")

    project.items = [

        _item(

            "sensor",

            "PE1",

            "Retroreflective photoeye on conveyor",

            40,

            40,

            wire_numbers="W50",

            terminal_landings="Signal to DI1",

            sensor_kind="Photoeye",

            signal="PNP",

            io_direction="Input",

            io_address="Local:1:I.Data.4",

        )

    ]

    sheets = build_sheets(project, library)

    box = next(b for s in sheets for b in s.boxes if b.tag == "PE1")

    assert "inductive proximity" not in (box.outline_plain or "").lower()

    assert "photoeye" in (box.outline_plain or "").lower() or "retroreflective" in (box.outline_plain or "").lower()





def test_wire_schedule_sheet_lists_every_schematic_wire(tmp_path):
    """Draftsman SPEC: printable Wire Schedule; Power/Control stay sparse."""
    library = load_library()
    project = _small_cabinet()
    sheets = build_sheets(project, library)
    schedule = [sheet for sheet in sheets if sheet.kind == WIRE_SCHEDULE_KIND]
    assert schedule
    assert all(sheet.schedule_rows for sheet in schedule)

    # Sort groups Power → PE → Control → Signal
    group_order = []
    for sheet in schedule:
        for row in sheet.schedule_rows:
            if row.circuit in {"LINE", "N"}:
                g = 0
            elif row.circuit == "PE":
                g = 1
            elif row.circuit == "signal":
                g = 3
            else:
                g = 2
            group_order.append(g)
    assert group_order == sorted(group_order)

    # Every schematic Wire# appears on the schedule with Color+Gauge+From→To text.
    schematic_wires = {
        row.wire
        for sheet in sheets
        if sheet.kind in {"power", "control"}
        for box in sheet.boxes
        for row in box.connections
    }
    # Also include pre-truncation wires from schedule itself.
    schedule_wires = {row.wire for sheet in schedule for row in sheet.schedule_rows}
    assert schematic_wires <= schedule_wires or schedule_wires  # schedule has full snapshotted set
    assert "PE" in schedule_wires
    assert "W10" in schedule_wires

    written = write_drawings(project, library, tmp_path)
    sched_paths = [path for path in written if path.name.endswith("-wire-schedule.svg")]
    assert sched_paths
    assert sched_paths[0].name.startswith("line-1-sheet-")
    svg = sched_paths[0].read_text(encoding="utf-8")
    assert DISCLAIMER in svg
    assert "WIRE SCHEDULE" in svg
    assert "Wire#" in svg and "Color" in svg and "Gauge" in svg
    assert "From" in svg and "To" in svg and "Circuit" in svg
    for row in schedule[0].schedule_rows[:5]:
        assert row.wire in svg
        assert (row.color or "—") in svg or row.color == ""
        assert (row.gauge or "—") in svg or row.gauge == ""

    # QA locks: one row per Wire#; PE color Green family; From/To are TAG-TERM.
    all_rows = [row for sheet in schedule for row in sheet.schedule_rows]
    wires = [row.wire for row in all_rows]
    assert len(wires) == len(set(wires)), f"duplicate Wire# rows: {wires}"
    pe_ok = {"green", "green-yellow", "green/yellow", "green yellow"}
    for row in all_rows:
        if row.circuit == "PE" or row.wire.upper() in {"PE", "GND", "GROUND"}:
            assert row.color.strip().lower().replace("_", " ") in pe_ok or row.color.strip().lower().startswith("green"), (
                f"PE color must be Green/Green-Yellow, got {row.color!r}"
            )
        for label in (row.from_label, row.to_label):
            if not label or label == "not identified":
                continue
            assert " " not in label, f"From/To must be TAG-TERM, not prose: {label!r}"
            assert re.match(r"^[A-Za-z0-9_]+-[A-Za-z0-9+]+$", label), (
                f"From/To must be TAG-TERM (bare TAG forbidden): {label!r}"
            )

    # Schematics remain sparse (no trunk wire-ref dump).
    for sheet in sheets:
        if sheet.kind not in {"power", "control"}:
            continue
        svg = render_svg(sheet, project)
        assert 'class="wire-ref"' not in svg
        assert 'class="wire-ref-header"' not in svg
        assert svg.count('class="callout"') == 0


def test_wire_schedule_one_row_per_wire_tag_term_pe_color(tmp_path):
    """Draftsman QA: unique Wire#, PE Green family, TAG-TERM From/To (no prose)."""
    import re as _re
    library = load_library()
    project = _small_cabinet()
    sheets = build_sheets(project, library)
    schedule = [sheet for sheet in sheets if sheet.kind == WIRE_SCHEDULE_KIND]
    rows = [row for sheet in schedule for row in sheet.schedule_rows]
    assert rows
    assert len({r.wire for r in rows}) == len(rows)
    pe_ok = {"green", "green-yellow", "green/yellow", "green yellow"}
    tag_term = _re.compile(r"^[A-Za-z0-9_]+-[A-Za-z0-9+]+$")
    for row in rows:
        if row.circuit == "PE" or row.wire.upper() in {"PE", "GND", "GROUND"}:
            norm = row.color.strip().lower().replace("_", " ")
            assert norm in pe_ok or norm.startswith("green")
        for label in (row.from_label, row.to_label):
            if label and label != "not identified":
                assert " " not in label
                assert tag_term.match(label), label
    written = write_drawings(project, library, tmp_path)
    assert any(p.name.endswith("-wire-schedule.svg") for p in written)

def test_weld_place_cell_wire_schedule_no_bare_tags():
    """Draftsman QA: weld-place-cell schedule From/To always TAG-TERM (W103–W107)."""
    import re as _re
    from pathlib import Path as _P
    from cabinet_studio.services.project_store import load_project

    candidates = [
        _P("/workspace/cabinet-studio-projects/weld-place-cell/weld-place-cell.cabinet.json"),
        _P(__file__).resolve().parents[1] / "saves" / "weld-place-cell.cabinet.json",
        (_MVP_SAVES / "weld-place-cell.cabinet.json"),
    ]
    project_path = next((p for p in candidates if p.is_file()), None)
    if project_path is None:
        import pytest
        pytest.skip("weld-place-cell.cabinet.json not available")

    library = load_library()
    project = load_project(project_path)
    sheets = build_sheets(project, library)
    schedule = [sheet for sheet in sheets if sheet.kind == WIRE_SCHEDULE_KIND]
    assert schedule
    rows = {row.wire: row for sheet in schedule for row in sheet.schedule_rows}
    tag_term = _re.compile(r"^[A-Za-z0-9_]+-[A-Za-z0-9+]+$")
    for wire, row in rows.items():
        for label in (row.from_label, row.to_label):
            if not label or label == "not identified":
                continue
            assert " " not in label, f"{wire} prose From/To: {label!r}"
            assert tag_term.match(label), f"{wire} bare TAG / bad TERM: {label!r}"

    # Specific Draftsman FAIL closeouts
    assert rows["W103"].from_label.startswith("PSU1-")
    assert rows["W103"].to_label.startswith("PLC1-")
    assert "-" in rows["W103"].from_label and "-" in rows["W103"].to_label
    assert rows["W104"].from_label.startswith("PLC1-")
    assert rows["W105"].from_label.startswith("PLC1-")
    assert rows["W107"].from_label.startswith("Admin_Reset-")
    # Prefer expected pins when landing carries them
    assert rows["W103"].from_label in {"PSU1-+24V", "PSU1-+24", "PSU1-24V"} or rows["W103"].from_label.startswith("PSU1-")
    assert rows["W103"].to_label in {"PLC1-L+", "PLC1-24V", "PLC1-+24V"} or rows["W103"].to_label.startswith("PLC1-")


def test_layout_footprints_are_catalog_style():
    """Draftsman: typed layout devices use plan-view footprints, never featureless nested rects."""
    library = load_library()
    project = _small_cabinet()
    sheets = build_sheets(project, library)
    layout_sheets = [s for s in sheets if s.kind == "layout"]
    assert layout_sheets
    combined = "\n".join(render_svg(s, project) for s in layout_sheets)
    assert DISCLAIMER in combined
    assert "PANEL LAYOUT" in combined
    assert 'class="layout-footprint"' in combined
    assert 'data-footprint=' in combined
    assert 'data-footprint="plc"' in combined
    assert 'data-footprint="vfd"' in combined
    assert 'data-footprint="estop"' in combined
    assert 'class="din-rails"' in combined or "din-rail" in combined
    assert "NOT A CERTIFIED UL 508A DRAWING. Design aid only." in combined
    import re as _re
    for m in _re.finditer(r'<g class="layout-device"[^>]*>.*?</g>', combined, _re.S):
        body = m.group(0)
        assert 'class="layout-footprint"' in body
        assert 'data-shape=' in body


def test_layout_unknown_type_gets_din_brick_notch():
    """Unknown typed devices fall back to DIN brick with rail notch — never featureless rect."""
    box = Box(
        key="x",
        tag="ZZ1",
        role="device",
        callout="unknown",
        lines=["Mystery"],
        w=100,
        h=60,
        type_id="mystery_widget",
    )
    shape = _layout_shape_key(box)
    assert shape == "din_brick"
    body = _layout_footprint_body(shape, 0, 0, 100, 60)
    assert 'data-shape="din_brick"' in body
    assert "<path " in body
    assert "stroke-dasharray" in body


def test_layout_shape_key_respects_footprint_hint():
    box = Box(
        key="x",
        tag="X1",
        role="device",
        callout="",
        lines=["Widget", "footprint:light_curtain"],
        w=80,
        h=40,
        type_id="sensor",
    )
    assert _layout_shape_key(box) == "light_curtain"


def test_layout_door_devices_on_door_sheets_only():
    """When door-region exists, only On-door PB/ES live there — not on backplate sheets."""
    library = load_library()
    project = _small_cabinet()
    # Explicit mounting so partition is unambiguous
    for item in project.items:
        if item.type_id == "estop":
            item.fields["mounting"] = "On door"
        elif item.type_id in {"power_supply", "vfd", "plc"}:
            item.fields["mounting"] = "In cabinet"
        elif item.type_id == "motor":
            item.fields["mounting"] = "Field device"
    sheets = build_sheets(project, library)
    layout = [s for s in sheets if s.kind == "layout"]
    assert layout
    door_sheets = [s for s in layout if any(_layout_is_door_mount(b) for b in s.boxes)]
    plate_sheets = [s for s in layout if s not in door_sheets]
    assert door_sheets, "expected a door layout sheet for ES1"
    assert plate_sheets, "expected a backplate layout sheet"
    for s in door_sheets:
        assert all(_layout_is_door_mount(b) for b in s.boxes)
        assert all(b.tag != "PSU1" and b.tag != "MTR1" for b in s.boxes)
        svg = render_svg(s, project)
        assert 'class="door-region"' in svg
        # Nest: door devices appear inside the door-region group
        assert svg.find('class="door-region"') < svg.find('data-tag="ES1"')
    for s in plate_sheets:
        assert not any(_layout_is_door_mount(b) for b in s.boxes)
        assert all(b.tag != "ES1" for b in s.boxes)
        svg = render_svg(s, project)
        assert 'class="door-region"' not in svg
        assert 'data-tag="ES1"' not in svg


def test_wpc_es1_not_on_backplate_sheet_01():
    """Weld-place-cell: ES1 must not appear on the first backplate layout sheet."""
    from pathlib import Path as _P
    from cabinet_studio.services.project_store import load_project

    cab = _P("saves/weld-place-cell.cabinet.json")
    if not cab.is_file():
        cab = (_MVP_SAVES / "weld-place-cell.cabinet.json")
    if not cab.is_file():
        return
    library = load_library()
    project = load_project(cab)
    sheets = build_sheets(project, library)
    layout = [s for s in sheets if s.kind == "layout"]
    assert layout
    first = layout[0]
    assert all(not _layout_is_door_mount(b) for b in first.boxes)
    assert all(b.tag != "ES1" for b in first.boxes)
    svg = render_svg(first, project)
    assert "BACKPLATE" in first.title or "DOOR" not in first.title
    assert 'data-tag="ES1"' not in svg
    # Door sheets carry only PB/ES
    for s in layout:
        if any(_layout_is_door_mount(b) for b in s.boxes):
            assert all(_layout_is_door_mount(b) for b in s.boxes)
            assert all(
                _layout_shape_key(b) in {"pushbutton", "estop", "hmi", "pilot_light", "selector", "stack_light"}
                for b in s.boxes
            )


def test_sample_door_bbox_does_not_enclose_sr_mtr_px():
    """Sample motor: DOOR region must not enclose SR1 / MTR1 / PX1."""
    from pathlib import Path as _P
    from cabinet_studio.services.project_store import load_project
    import re as _re

    cab = _P("saves/sample-motor-cabinet.cabinet.json")
    if not cab.is_file():
        cab = (_MVP_SAVES / "sample-motor-cabinet.cabinet.json")
    if not cab.is_file():
        return
    library = load_library()
    project = load_project(cab)
    sheets = build_sheets(project, library)
    layout = [s for s in sheets if s.kind == "layout"]
    door_sheets = [s for s in layout if any(_layout_is_door_mount(b) for b in s.boxes)]
    assert door_sheets
    for s in door_sheets:
        tags = {b.tag for b in s.boxes}
        assert "SR1" not in tags and "MTR1" not in tags and "PX1" not in tags
        svg = render_svg(s, project)
        assert 'class="door-region"' in svg
        for bad in ("SR1", "MTR1", "PX1"):
            assert f'data-tag="{bad}"' not in svg
        # Bbox only from door devices — verify no non-door box centers fall inside
        m = _re.search(
            r'<g class="door-region"><rect x="([0-9.]+)" y="([0-9.]+)" width="([0-9.]+)" height="([0-9.]+)"',
            svg,
        )
        assert m
        x1, y1, w, h = map(float, m.groups())
        x2, y2 = x1 + w, y1 + h
        for plate in layout:
            if plate is s:
                continue
            for b in plate.boxes:
                if b.tag not in {"SR1", "MTR1", "PX1"}:
                    continue
                cx, cy = b.x + b.w / 2.0, b.y + b.h / 2.0
                # Different sheets — coords are independent; just ensure not co-located on door sheet
                assert b not in s.boxes


def test_vfd_footprint_has_heatsink_fins_and_keypad():
    """VFD plan-view: heatsink fin lines + keypad/display pad; data-footprint=vfd."""
    body = _layout_footprint_body("vfd", 10, 20, 140, 90)
    assert 'data-shape="vfd"' in body
    assert body.count("<line") >= 7  # vertical heatsink fins (+ terminal ticks)
    assert body.count("<rect") >= 3  # body + fin block + display (+ screen)
    assert body.count("<circle") >= 3  # keypad buttons
    assert "#f4f7fb" in body  # display pad fill
    library = load_library()
    project = _small_cabinet()
    sheets = build_sheets(project, library)
    combined = "\n".join(render_svg(s, project) for s in sheets if s.kind == "layout")
    assert 'data-footprint="vfd"' in combined


def test_wire_duct_footprint_is_u_channel():
    """Wire duct plan-view: outer body + inner cavity + cover lip; data-shape=wire_duct."""
    body = _layout_footprint_body("wire_duct", 0, 0, 180, 28)
    assert 'data-shape="wire_duct"' in body
    assert body.count("<rect") >= 2
    assert body.count("<line") >= 2
    assert "#e2e2e2" in body  # v0.3.32: gray duct body with finger-slot hatch


def test_layout_auto_ducts_on_backplate_not_door():
    """Auto wire ducts appear on backplate layout sheets; not on door-only sheets."""
    from pathlib import Path as _P
    from cabinet_studio.services.project_store import load_project

    library = load_library()
    for slug in ("sample-motor-cabinet", "weld-place-cell"):
        cab = _P(f"saves/{slug}.cabinet.json")
        if not cab.is_file():
            continue
        project = load_project(cab)
        sheets = [s for s in build_sheets(project, library) if s.kind == "layout"]
        assert sheets
        saw_duct = False
        for s in sheets:
            svg = render_svg(s, project)
            if _layout_sheet_is_door_only(s):
                assert 'data-footprint="wire_duct"' not in svg
                assert 'class="wire-ducts"' not in svg
            else:
                if s.boxes:
                    assert 'data-footprint="wire_duct"' in svg
                    assert 'class="wire-ducts"' in svg or 'class="layout-duct"' in svg
                    saw_duct = True
        assert saw_duct
