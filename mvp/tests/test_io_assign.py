"""I/O enumeration: native addresses per maker, stability on re-run, shortage report, I/O LIST sheet."""

from __future__ import annotations

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.services.io_assign import assign_io, detect_profile, tag_addresses, write_io_csv

_n = 0


def _it(type_id, **fields):
    global _n
    _n += 1
    return PlacedItem(id=f"i{_n}", library_id=None, type_id=type_id, x=0, y=0, fields=fields)


def _proj(items, program=None):
    return Project(name="IO Test", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                   items=items, program=program or {})


def _addr(report):
    return {r.tag: r.address for r in report.rows}


def _plc(catalog, vendor=""):
    return _it("plc", tag="PLC1", catalog=catalog, vendor=vendor, ip_address="192.168.1.10")


def _mod(slot, kind, pts, catalog=""):
    return _it("io_module", tag=f"IO{slot}", io_kind=kind, point_count=str(pts), slot=str(slot), parent_tag="PLC1",
               catalog=catalog)


def test_compactlogix_local_slot_bits_and_types():
    items = [_plc("1769-L33ER"), _mod(1, "DI", 16), _mod(2, "DO", 16),
             _it("pushbutton", tag="PB_Start", function="Start"), _it("estop", tag="ES1"),
             _it("light_curtain", tag="LC1"), _it("motor_protector", tag="OL1"),
             _it("light", tag="PL_Run"), _it("contactor", tag="M1"), _it("solenoid", tag="SOL1"),
             _it("motor", tag="MTR1"), _it("power_supply", tag="PS1")]
    report = assign_io(_proj(items))
    a = _addr(report)
    assert detect_profile(items[0]).family == "logix"
    assert [a["PB_Start"], a["ES1"], a["LC1"], a["OL1"]] == [f"Local:1:I.Data.{i}" for i in range(4)]
    assert [a["PL_Run"], a["M1"], a["SOL1"]] == [f"Local:2:O.Data.{i}" for i in range(3)]
    assert "MTR1" not in a and "PS1" not in a
    assert items[3].fields["io_address"] == "Local:1:I.Data.0" and items[3].fields["io_direction"] == "Input"
    assert not report.shortages


def test_micro800_embedded_names():
    items = [_plc("2080-LC50-24QWB"), _it("sensor", tag="PE1", signal="PNP"), _it("light", tag="PL1")]
    a = _addr(assign_io(_proj(items)))
    assert a == {"PE1": "_IO_EM_DI_00", "PL1": "_IO_EM_DO_00"}


def test_siemens_1200_embedded_then_module_and_analog():
    items = [_plc("6ES7214-1AG40-0XB0"), _mod(2, "", 16, "6ES7221-1BH32-0XB0")]
    items += [_it("pushbutton", tag=f"PB{i}") for i in range(15)]
    items += [_it("transmitter", tag="PT1", signal="4-20 mA"), _it("valve", tag="V1")]
    a = _addr(assign_io(_proj(items)))
    assert a["PB0"] == "%I0.0" and a["PB7"] == "%I0.7" and a["PB8"] == "%I1.0"
    assert a["PB14"] == "%I8.0"  # 14 embedded inputs, then the SM in slot 2
    assert a["PT1"] == "%IW64" and a["V1"] == "%Q0.0"


def test_omron_cp_and_cj_and_nx():
    cp = [_plc("CP2E-N30DT-D")] + [_it("pushbutton", tag=f"PB{i}") for i in range(13)] + [_it("light", tag="PL1")]
    a = _addr(assign_io(_proj(cp)))
    assert a["PB0"] == "0.00" and a["PB11"] == "0.11" and a["PB12"] == "1.00" and a["PL1"] == "100.00"
    cj = [_plc("CJ2M-CPU31", "Omron"), _mod(0, "DI", 16), _mod(1, "DO", 16),
          _it("pushbutton", tag="PB1"), _it("relay", tag="CR1")]
    cj[1].fields["slot"] = "1"
    cj[2].fields["slot"] = "2"
    a = _addr(assign_io(_proj(cj)))
    assert a == {"PB1": "0.00", "CR1": "1.00"}
    nx = [_plc("NX1P2-9024DT"), _it("pushbutton", tag="PB1"), _it("light", tag="PL1")]
    a = _addr(assign_io(_proj(nx)))
    assert a == {"PB1": "BuiltIn_Input_Bit_00", "PL1": "BuiltIn_Output_Bit_00"}


def test_stable_when_rerun_and_device_added_in_front():
    items = [_plc("1769-L33ER"), _mod(1, "DI", 16), _it("pushbutton", tag="PB1"), _it("pushbutton", tag="PB2")]
    proj = _proj(items)
    first = _addr(assign_io(proj))
    again = assign_io(proj)
    assert _addr(again) == first and all(r.kept for r in again.rows)
    proj.items.insert(2, _it("pushbutton", tag="PB0"))
    third = _addr(assign_io(proj))
    assert third["PB1"] == first["PB1"] and third["PB2"] == first["PB2"]
    assert third["PB0"] == "Local:1:I.Data.2"
    wires = {i.fields.get("tag"): i.fields.get("io_wire") for i in proj.items}
    assign_io(proj)
    assert {i.fields.get("tag"): i.fields.get("io_wire") for i in proj.items} == wires


def test_shortage_reported_and_points_spill_to_next_module():
    items = [_plc("1769-L33ER"), _mod(1, "DI", 16), _mod(3, "DI", 8)]
    items += [_it("sensor", tag=f"S{i}") for i in range(27)]
    report = assign_io(_proj(items))
    a = _addr(report)
    assert a["S16"] == "Local:3:I.Data.0" and a["S23"] == "Local:3:I.Data.7"
    assert a["S24"] == "UNASSIGNED"
    assert report.shortages == ["Need 1 more 16-pt DI module (3 input points without an address)."]


def test_wire_and_terminal_follow_existing_wiring_and_csv_has_no_blank_lines(tmp_path):
    items = [_plc("1769-L33ER"), _mod(1, "DI", 16), _it("terminal_block", tag="TB2"),
             _it("pushbutton", tag="PB1", wire_numbers="W101, PE", terminal_landings="TB2-14 to PB1 13"),
             _it("pushbutton", tag="PB2", wire_numbers="W205")]
    report = assign_io(_proj(items))
    rows = {r.tag: r for r in report.rows}
    assert (rows["PB1"].wire, rows["PB1"].terminal) == ("W101", "TB2-14")
    assert (rows["PB2"].wire, rows["PB2"].terminal) == ("W205", "TB2-15")
    path = write_io_csv(report, tmp_path / "io.csv")
    lines = path.read_bytes().split(b"\r\n")
    assert lines[0].startswith(b"Tag,Device") and b"" not in lines[:-1]


def test_vfd_hardwired_and_aux_and_aliases():
    items = [_plc("1769-L33ER"), _mod(1, "DI", 16), _mod(2, "DO", 16),
             _it("vfd", tag="VFD1", io_direction="Output"), _it("vfd", tag="VFD2"),
             _it("contactor", tag="M1", io_direction="Input and Output")]
    proj = _proj(items, program={"tag_aliases": {"Motor": "M1"}})
    a = _addr(assign_io(proj))
    assert a["VFD1_RUN"] == "Local:2:O.Data.0" and a["VFD1_DIR"] == "Local:2:O.Data.1"
    assert "VFD2_RUN" not in a  # network drive: no discrete points
    assert a["M1"] == "Local:2:O.Data.2" and a["M1_AUX"] == "Local:1:I.Data.0"
    assert items[3].fields["io_points"] == "VFD1_RUN=Local:2:O.Data.0; VFD1_DIR=Local:2:O.Data.1"
    assert tag_addresses(proj)["Motor"] == "Local:2:O.Data.2"


def test_io_list_sheet_after_wire_schedule_with_one_footer():
    from cabinet_studio.services.drawings import DISCLAIMER, build_sheets, render_svg
    from cabinet_studio.services.library_loader import load_library

    items = [_plc("1769-L33ER"), _mod(1, "DI", 16), _mod(2, "DO", 16),
             _it("pushbutton", tag="PB1", wire_numbers="W101"), _it("contactor", tag="M1", wire_numbers="W201")]
    proj = _proj(items)
    sheets = build_sheets(proj, load_library())
    kinds = [s.kind for s in sheets]
    assert "io-list" in kinds
    io_at = kinds.index("io-list")
    if "wire-schedule" in kinds:
        assert io_at > max(i for i, k in enumerate(kinds) if k == "wire-schedule")
    svg = render_svg(sheets[io_at], proj)
    assert svg.count(DISCLAIMER) <= 2 and "Local:1:I.Data.0" in svg  # <desc> + title block
    assert [s.number for s in sheets] == list(range(1, len(sheets) + 1))
