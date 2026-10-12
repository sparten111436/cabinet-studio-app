"""PLC / Device: device_link with a FAKE driver (no network) and a headless gate that clicks EVERY new
button in the PLC / Device window plus the Programming-page entry button."""

from __future__ import annotations

import os
import sys
import time
import traceback

import pytest

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.services import device_link as dl
from cabinet_studio.services.programming import add_rung, empty_program, program_to_dict


def _project():
    prog = add_rung(empty_program(), contact_tag="Start_PB", coil_tag="Motor", comment="Start motor")
    items = [
        PlacedItem(id="p", library_id=None, type_id="plc", x=0, y=0,
                   fields={"tag": "PLC1", "catalog": "1769-L33ER", "ip_address": "192.168.1.10"}),
        PlacedItem(id="m1", library_id=None, type_id="io_module", x=0, y=0,
                   fields={"tag": "IO1", "io_kind": "DI", "point_count": "16", "slot": "1"}),
        PlacedItem(id="m2", library_id=None, type_id="io_module", x=0, y=0,
                   fields={"tag": "IO2", "io_kind": "DO", "point_count": "16", "slot": "2"}),
        PlacedItem(id="a", library_id=None, type_id="pushbutton", x=0, y=0, fields={"tag": "Start_PB"}),
        PlacedItem(id="e", library_id=None, type_id="estop", x=0, y=0, fields={"tag": "ES1"}),
        PlacedItem(id="c", library_id=None, type_id="contactor", x=0, y=0, fields={"tag": "Motor"}),
        PlacedItem(id="h", library_id=None, type_id="hmi", x=0, y=0, fields={"tag": "HMI1", "ip_address": ""}),
    ]
    return Project(name="Device Gate", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                   items=items, program=program_to_dict(prog))


def _fake(**kw):
    tags = {"HMI_Start": ("BOOL", 0), "Speed_SP": ("DINT", 100), "Start_PB": ("BOOL", 1), "Motor": ("DINT", 0),
            "Extra_Tag": ("BOOL", 0), "ES1": ("BOOL", 1)}
    return dl.FakeDriver(tags=tags, **kw)


# ----------------------------------------------------------------------------- service

def test_libraries_are_imported_lazily():
    if "pycomm3" in sys.modules or "snap7" in sys.modules:
        pytest.skip("another test already imported a driver library")
    assert "pycomm3" not in sys.modules and "snap7" not in sys.modules


def test_connect_info_read_watch_compare_write():
    drv = _fake()
    link = dl.DeviceLink(drv, _project())
    info = link.connect()
    assert info["Product"] == "Simulated PLC"
    assert link.read(["Speed_SP", "Start_PB"]) == {"Speed_SP": 100, "Start_PB": 1}
    for _ in range(3):  # watch = repeated reads
        assert link.read(["HMI_Start"])["HMI_Start"] == 0
    cmp = link.compare_tags()
    assert "Extra_Tag" in cmp.extra and "Motor" in [m[0] for m in cmp.mismatch]
    link.write("HMI_Start", 1, confirmed=True)
    link.write("Speed_SP", 250, confirmed=True)
    assert drv.writes == [("HMI_Start", 1), ("Speed_SP", 250)]
    assert link.read(["Speed_SP"])["Speed_SP"] == 250


@pytest.mark.parametrize("tag", ["ES1", "E_STOP_Reset", "LC1_Mute", "Guard_Door_Closed", "SR1_Reset"])
def test_safety_write_refused(tag):
    drv = _fake()
    link = dl.DeviceLink(drv, _project())
    link.connect()
    with pytest.raises(dl.DeviceError, match="safety"):
        link.write(tag, 1, confirmed=True)
    assert drv.writes == []


@pytest.mark.parametrize("tag", ["Start_PB", "Motor", "Local:1:I.Data.0", "%Q0.0", "_IO_EM_DO_00", "100.00"])
def test_physical_io_write_refused(tag):
    link = dl.DeviceLink(_fake(), _project())
    link.connect()
    with pytest.raises(dl.DeviceError, match="physical I/O"):
        link.write(tag, 1, confirmed=True)


def test_write_refused_without_confirmation():
    drv = _fake()
    link = dl.DeviceLink(drv, _project())
    link.connect()
    with pytest.raises(dl.DeviceError, match="at the machine"):
        link.write("HMI_Start", 1, confirmed=False)
    assert drv.writes == []


def test_timeouts_and_bad_input_are_plain_words():
    link = dl.DeviceLink(_fake(fail_connect=True), _project())
    with pytest.raises(Exception) as err:
        link.connect()
    assert "No answer from the PLC" in dl.plain_error(err.value, "10.0.0.9")
    with pytest.raises(dl.DeviceError, match="IP address"):
        dl.make_driver(0, "not an ip")
    assert isinstance(dl.make_driver("Simulated PLC (no network)", ""), dl.FakeDriver)


def test_address_parsers():
    assert dl.parse_s7("%I0.3") == {"area": "I", "db": 0, "byte": 0, "bit": 3, "size": "X"}
    assert dl.parse_s7("%MW20")["size"] == "W" and dl.parse_s7("DB1.DBX2.1")["bit"] == 1
    assert dl.parse_fins("D100") == ("D", 100, None) and dl.parse_fins("0.05") == ("CIO", 0, 5)
    with pytest.raises(dl.DeviceError):
        dl.parse_s7("Start_PB")
    s7 = dl.S7Link("192.168.0.1", tag_map={"Out1": "%Q0.0"})
    with pytest.raises(dl.DeviceError, match="never written"):
        s7.write("Out1", 1)
    fins = dl.FinsLink("192.168.0.1")
    with pytest.raises(dl.DeviceError, match="never written"):
        fins.write("CIO 100", 1)


# ----------------------------------------------------------------------------- UI gate

pytest.importorskip("customtkinter")
import customtkinter as ctk  # noqa: E402

needs_display = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)


def _all(widget):
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_all(child))
    return out


def _pump(w, n=3):
    for _ in range(n):
        try:
            w.update()
        except Exception:
            pass


def _settle(panel, limit=4.0):
    end = time.time() + limit
    while time.time() < end:
        _pump(panel, 1)
        if not panel.busy and panel._q.empty():
            _pump(panel, 2)
            return
        time.sleep(0.02)
    raise AssertionError("PLC / Device window stayed busy")


def _click(panel, label, errors):
    for b in _all(panel):
        if isinstance(b, ctk.CTkButton) and b.winfo_exists() and b.cget("text") == label:
            assert getattr(b, "_cs_hover_tip", None) is not None, f"{label} has no hover help"
            try:
                b.invoke()
            except Exception:
                errors.append(f"{label}: {traceback.format_exc()}")
            _settle(panel)
            return b
    raise AssertionError(f"button {label!r} not found")


@pytest.fixture()
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    monkeypatch.setattr("cabinet_studio.services.drawings.default_drawings_folder",
                        lambda project, path=None: tmp_path / "drawings")
    opened: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    errors: list[str] = []
    root = ctk.CTk()
    root.withdraw()
    root.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb)))
    project = _project()
    changes: list = []
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *a: changes.append(a))
    v.update()
    try:
        yield v, project, errors, opened, tmp_path
    finally:
        try:
            if getattr(v, "_device_panel", None) is not None and v._device_panel.winfo_exists():
                v._device_panel.close()
            if v.winfo_exists():
                v.close()
            root.update()
        except Exception:
            pass
        root.destroy()


@needs_display
def test_gate_every_device_button(gate):
    from cabinet_studio.ui.device_panel import DevicePanel

    v, project, errors, opened, tmp_path = gate
    entry = next(b for b in _all(v) if isinstance(b, ctk.CTkButton) and b.cget("text") == "PLC / Device")
    assert getattr(entry, "_cs_hover_tip", None) is not None
    entry.invoke()
    _pump(v)
    panel = v._device_panel
    assert isinstance(panel, DevicePanel) and panel.winfo_exists()
    assert "maker's software" in " ".join(w.cget("text") for w in _all(panel) if isinstance(w, ctk.CTkLabel))
    log = lambda: panel.out.get("1.0", "end")  # noqa: E731

    _click(panel, "Assign I/O", errors)
    assert project.find("a").fields["io_address"] == "Local:1:I.Data.0"
    _click(panel, "I/O list CSV", errors)
    assert (tmp_path / "drawings" / "plc" / "io-list.csv").exists()
    _click(panel, "Export files", errors)
    assert (tmp_path / "drawings" / "plc" / "program.L5X").exists()
    _click(panel, "Open folder", errors)
    assert opened
    _click(panel, "Download / upload program", errors)
    assert "not done over the wire" in log()

    # Not connected yet: every live button answers in plain words.
    for label in ("Read info", "Compare tags", "Start watch"):
        _click(panel, label, errors)
    assert "Not connected" in log()

    panel.driver_menu._dropdown_callback("Simulated PLC (no network)")
    _click(panel, "Connect", errors)
    assert "Connected." in log() and panel.link.connected
    _click(panel, "Read info", errors)
    _click(panel, "Compare tags", errors)
    assert "Missing in PLC" in log()
    panel.watch_var.set("Motor")
    _click(panel, "Add", errors)
    _click(panel, "Add all I/O", errors)
    assert "Start_PB" in panel.watch
    panel.watch_var.set("Start_PB")
    _click(panel, "Remove", errors)
    assert "Start_PB" not in panel.watch
    _click(panel, "Start watch", errors)
    assert panel.watching
    _settle(panel)
    assert "Motor" in panel.watch_box.get("1.0", "end")
    _click(panel, "Stop watch", errors)
    assert not panel.watching

    panel.write_tag.insert(0, "Motor_SP")
    panel.write_value.insert(0, "5")
    _click(panel, "Write", errors)
    assert "tick 'I am at the machine" in log()
    panel.safe_check.select()
    _click(panel, "Write", errors)
    assert "no tag named Motor_SP" in log()
    panel.write_tag.delete(0, "end")
    panel.write_tag.insert(0, "ES1")
    _click(panel, "Write", errors)
    assert "safety tag" in log()
    panel.link.driver.tags["HMI_Run"] = ("BOOL", 0)
    panel.write_tag.delete(0, "end")
    panel.write_tag.insert(0, "HMI_Run")
    panel.write_value.delete(0, "end")
    panel.write_value.insert(0, "1")
    _click(panel, "Write", errors)
    assert panel.link.driver.tags["HMI_Run"][1] == 1
    _click(panel, "Disconnect", errors)

    hmi_label = next(lbl for lbl, item in panel.choices if item.type_id == "hmi")
    panel.device_menu._dropdown_callback(hmi_label)
    _click(panel, "Export files", errors)
    assert "No HMI design" in log()
    _click(panel, "Connect", errors)
    assert "HMI's IP address" in log()
    _click(panel, "Assign I/O", errors)

    _click(panel, "Close", errors)
    assert not panel.winfo_exists()
    assert not errors, "\n\n".join(errors)


@needs_display
def test_tools_menu_has_device_entry(gate):
    v = gate[0]
    v._open_device_panel()
    _pump(v)
    assert v._device_panel.winfo_exists()
