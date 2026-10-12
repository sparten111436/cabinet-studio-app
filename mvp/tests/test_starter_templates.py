"""Starter cabinets (v0.3.35): every template is a complete, checked starting point, and the
Start-from-a-template gallery clicks through headlessly."""

from __future__ import annotations

import os
import re
import traceback

import pytest

from cabinet_studio.services.drawings import build_sheets, drawing_issues, render_svg
from cabinet_studio.services.hmi_design import load_design, validate_design
from cabinet_studio.services.io_assign import assign_io, tag_addresses
from cabinet_studio.services.ladder_tools import verify_program
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.programming import cabinet_device_tags, flatten_contacts
from cabinet_studio.services.sim_autorun import normal_run_plan
from cabinet_studio.services.sim_plant import is_safety_tag
from cabinet_studio.services.starter_templates import (
    MAKER_EQUIV,
    MAKERS,
    TEMPLATES,
    build_template_project,
)

FOOTER = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."
LIB = load_library()
_BUILT: dict[tuple[str, str], object] = {}


def _project(tid: str, maker: str = "Allen-Bradley"):
    key = (tid, maker)
    if key not in _BUILT:
        _BUILT[key] = build_template_project(tid, LIB, maker=maker)
    return _BUILT[key]


def _elements(rung: dict) -> list[dict]:
    out: list[dict] = []
    if rung.get("parallel"):
        out.append({"kind": "or", "branches": [[{"kind": "contact", "var": c["tag"],
                                                  "form": "NC" if c["normally_closed"] else "NO"} for c in b]
                                                for b in rung["parallel"]]})
    out += [{"kind": "contact", "var": c["tag"], "form": "NC" if c["normally_closed"] else "NO"}
            for c in rung.get("series", [])]
    return out


def test_there_are_enough_templates_with_unique_ids():
    assert 8 <= len(TEMPLATES) <= 12
    assert len({t.id for t in TEMPLATES}) == len(TEMPLATES)
    for t in TEMPLATES:
        assert t.summary and t.when and t.change_first and t.supplies


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_template_is_a_complete_checked_cabinet(template):
    p = _project(template.id)
    # Real catalog parts, Allen-Bradley where the library has them.
    for item in p.items:
        assert item.library_id in LIB.catalog_by_id, item.library_id
        assert (item.fields.get("tag") or "").strip()
    assert any(i.type_id == "plc" for i in p.items) and any(i.type_id == "power_supply" for i in p.items)
    assert any(i.type_id in {"breaker", "disconnect", "motor_protector"} for i in p.items)
    # Interview answers filled.
    for key in ("supply_voltage", "control_voltage", "duty", "manufacturer"):
        assert p.interview.get(key), key
    assert p.interview["starter_template"] == template.id
    assert p.enclosure_maker == "Hoffman" and p.enclosure_catalog
    assert "What to change first" in p.notes and FOOTER in p.notes
    # Ladder: verifies clean, carries the safety note, uses a seal-in or a latch.
    devices = cabinet_device_tags(p)
    issues = verify_program(p.program, devices)
    assert not [i for i in issues if i.get("severity") == "error"], issues
    rungs = p.program["rungs"]
    assert "NFPA 79" in rungs[0]["comment"] and "never the safety function" in rungs[0]["comment"]
    assert any(r["coil_tag"] and any(c["tag"] == r["coil_tag"] for c in flatten_contacts(r)) for r in rungs)
    # I/O: every device the ladder reads or drives has a PLC address.
    report = assign_io(p, write=False)
    assert report.ok and report.rows and all(r.address for r in report.rows)
    addresses = tag_addresses(p)
    device_tags = {d["tag"] for d in devices}
    used = {c["tag"] for r in rungs for c in flatten_contacts(r)} | {r["coil_tag"] for r in rungs}
    for tag in used & device_tags:
        if any(d["tag"] == tag and d["type_id"] in {"pushbutton", "sensor", "light", "solenoid", "estop",
                                                    "light_curtain", "relay"} for d in devices):
            assert addresses.get(tag), f"{tag} has no PLC address"
    # Simulator Normal run never touches the E-stop, light curtain or safety relays.
    inputs = [d["tag"] for d in devices] + [a for a in addresses]
    plan = normal_run_plan([_elements(r) for r in rungs], inputs)
    for step in plan:
        for tag in step["set"]:
            assert not is_safety_tag(tag), (tag, step)
            assert tag not in {"ES1", "LC1", "SR1", "SR_LC"}
    # Drawings: shop-print order, no drawing issues, footer once per printed sheet.
    sheets = build_sheets(p, LIB)
    kinds = [s.kind for s in sheets]
    order = [kinds.index(k) for k in ("layout", "power", "control", "wire-schedule")]
    assert order == sorted(order), kinds
    for sheet in sheets:
        assert drawing_issues(sheet) == [], (sheet.kind, drawing_issues(sheet)[:3])
        printed = re.sub(r"<desc>.*?</desc>", "", render_svg(sheet, p), flags=re.S)
        assert printed.count(FOOTER) == 1, sheet.kind
    # HMI where the template has one.
    design = load_design(p)
    if template.hmi:
        assert design is not None and validate_design(design, p) == []
    else:
        assert design is None


@pytest.mark.parametrize("maker", ["Siemens", "Omron"])
@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t.id)
def test_maker_variants_use_that_makers_parts_and_still_check_clean(template, maker):
    p = _project(template.id, maker)
    assert p.interview["manufacturer"] == maker
    by_tag = {i.fields["tag"]: i for i in p.items}
    for slot in template.slots(template.default_supply, template.control):
        item = by_tag[slot.tag]
        alt = MAKER_EQUIV.get(slot.catalog_id, {}).get(maker)
        if alt:
            assert item.library_id == alt, (slot.tag, item.library_id)
            assert item.fields["vendor"] == maker == LIB.catalog_by_id[alt].vendor
    core = [i for i in p.items if i.type_id in {"plc", "io_module", "power_supply", "estop", "terminal_block"}]
    assert core and all(i.fields["vendor"] == maker for i in core)
    issues = verify_program(p.program, cabinet_device_tags(p))
    assert not [i for i in issues if i.get("severity") == "error"]
    assert all(r.address for r in assign_io(p, write=False).rows)
    for sheet in build_sheets(p, LIB):
        assert drawing_issues(sheet) == []


def test_supply_choice_flows_into_the_interview_and_motor():
    t = TEMPLATES[0]
    p = build_template_project(t, LIB, supply=t.supplies[-1], name="Shop fan")
    assert p.name == "Shop fan" and p.interview["supply_voltage"] == t.supplies[-1]
    motor = next(i for i in p.items if i.type_id == "motor")
    assert motor.fields.get("voltage") == t.supplies[-1]


# ----------------------------------------------------------------------------- UI gate

pytest.importorskip("customtkinter")
needs_display = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)


def _walk(widget):
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_walk(child))
    return out


@needs_display
def test_gate_v0335_gallery_every_template_button_and_dropdown(tmp_path, monkeypatch):
    import customtkinter as ctk

    monkeypatch.setenv("CABINET_STUDIO_NO_SPLASH", "1")
    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    from cabinet_studio.ui import main_window, theme
    from cabinet_studio.ui.dialogs import NewProjectDialog
    from cabinet_studio.ui.main_window import CabinetStudioApp
    from cabinet_studio.ui.starter_gallery import StarterGallery, open_starter_gallery

    prompts: list[str] = []
    answer = {"value": "discard"}
    monkeypatch.setattr(main_window, "ask_choice", lambda *a, **k: prompts.append(a[2]) or answer["value"])
    errors: list[str] = []
    app = CabinetStudioApp(LIB)
    app.report_callback_exception = lambda exc, val, tb: errors.append("".join(traceback.format_exception(exc, val, tb)))

    def pump():
        for _ in range(2):
            app.update()

    try:
        pump()
        assert app.templates_button._cs_hover_tip.text
        app.templates_button.invoke()
        pump()
        gallery = app.starter_gallery
        assert isinstance(gallery, StarterGallery) and gallery.winfo_exists()
        assert set(gallery.cards) == {t.id for t in TEMPLATES}
        for bit in (gallery.close_button, gallery.name):
            assert bit._cs_hover_tip.text
        for i, template in enumerate(TEMPLATES):
            if not gallery.winfo_exists():
                app.dirty = True
                gallery = open_starter_gallery(app)  # dirty -> the usual save prompt first
                assert prompts and prompts[-1] == "Save cabinet?"
                pump()
            card = gallery.cards[template.id]
            for bit in ("maker", "supply", "button"):
                assert card[bit]._cs_hover_tip.text, (template.id, bit)
            for maker in MAKERS:
                card["maker"]._dropdown_callback(maker)
                pump()
                assert card["maker_var"].get() == maker
            maker = MAKERS[i % len(MAKERS)]
            card["maker"]._dropdown_callback(maker)
            supply = template.supplies[i % len(template.supplies)]
            card["supply"]._dropdown_callback(supply)
            pump()
            before = app.project
            btn = card["button"]
            btn._canvas.event_generate("<Enter>")
            btn.invoke()
            pump()
            assert app.project is not before and app.project.template_id == f"starter:{template.id}"
            assert app.dirty and app.path is None
            assert app.project.interview["manufacturer"] == maker
            assert app.project.interview["supply_voltage"] == supply
            plc = next(it for it in app.project.items if it.type_id == "plc")
            assert plc.fields["vendor"] == maker
            assert not gallery.winfo_exists()
        # Cancel at the save prompt keeps the open cabinet.
        keep = app.project
        app.dirty = True
        answer["value"] = "cancel"
        assert open_starter_gallery(app) is None and app.project is keep
        answer["value"] = "discard"
        # Close button and Escape.
        gallery = open_starter_gallery(app)
        pump()
        gallery.close_button.invoke()
        pump()
        assert not gallery.winfo_exists()
        # New project dialog -> Start from a template (no second save prompt).
        app.dirty = False
        app.new_project()
        pump()
        dialog = next(w for w in _walk(app) if isinstance(w, NewProjectDialog))
        assert dialog.template_button._cs_hover_tip.text
        count = len(prompts)
        dialog.template_button.invoke()
        pump()
        gallery = app.starter_gallery
        assert gallery.winfo_exists() and not dialog.winfo_exists() and len(prompts) == count
        gallery.name.insert(0, "Bench 7")
        gallery.cards["plc-trainer"]["button"].invoke()
        pump()
        assert app.project.name == "Bench 7"
        # File menu entry routes to the gallery.
        app.dirty = False
        app.invoke_command("main.new_template")
        pump()
        assert app.starter_gallery.winfo_exists()
        app.starter_gallery.event_generate("<Escape>")
        pump()
        assert not errors, "\n\n".join(errors)
        assert not any(isinstance(w, ctk.CTkToplevel) and w.winfo_exists() and isinstance(w, StarterGallery)
                       for w in _walk(app))
    finally:
        app.destroy()
        theme.set_mode("dark", save=False)
