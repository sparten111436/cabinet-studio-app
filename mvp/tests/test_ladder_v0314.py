"""v0.3.14: REG-3 no-dupe series, REG-4 CSV, G-AID-2 appendix, NEW-L CPT/nested OR, viewer paths."""
from __future__ import annotations

import csv
import io
import os
import re
from collections import Counter
from copy import deepcopy

import pytest

from cabinet_studio import __version__
from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
from cabinet_studio.services.ladder_ir import (
    _coil_el,
    _contact_el,
    program_rung_to_elements,
)
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE, apply_aoi_template
from cabinet_studio.services.ladder_tools import WatchTrendBuffer, format_cross_reference_html
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import (
    add_compare_rung,
    add_math_rung,
    add_rung,
    add_rung_from_elements,
    add_timer_rung,
    append_parallel_contact,
    append_series_contact,
    edit_rung,
    empty_program,
    format_plc_text,
    program_from_dict,
)

CYCLE = 100
UL_NEEDLE = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."
assert UL_NEEDLE == UL_DESIGN_AID


def _strip_embed(xml: str) -> str:
    return re.sub(r"cabinet-studio-elements:[^<]*", "", xml or "")


def _graph_only(prog: dict) -> dict:
    xml = export_program_to_plcopen_xml(prog, project_name="QA")
    return program_from_dict(import_plcopen_xml_to_program(_strip_embed(xml)))


def _contact_multiset(els: list) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    def walk(nodes):
        for e in nodes or []:
            if not isinstance(e, dict):
                continue
            if e.get("kind") == "contact" and e.get("var"):
                out.append((str(e["var"]), str(e.get("form") or "NO").upper()))
            if e.get("kind") == "or":
                for br in e.get("branches") or []:
                    walk(br)

    walk(els)
    return out


def test_version_is_0314():
    # v0.3.15: version moved on; keep the 0.3.1x line check.
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 14)  # strict: parsed, not a prefix match


# ---------- REG-3 ----------


def test_reg3_classic_add_series_no_duplicate():
    prog = add_rung(empty_program(), contact_tag="A", coil_tag="Y")
    rid = prog["rungs"][0]["id"]
    before = _contact_multiset(program_rung_to_elements(prog["rungs"][0]))
    assert before == [("A", "NO")]
    prog = append_series_contact(prog, rid, "GUARD")
    after = _contact_multiset(program_rung_to_elements(prog["rungs"][0]))
    assert after == [("A", "NO"), ("GUARD", "NO")], after
    # Follow-on API NC edit must not leave never-true logic
    prog = edit_rung(prog, rid, normally_closed=True)
    forms = _contact_multiset(program_rung_to_elements(prog["rungs"][0]))
    assert forms[0] == ("A", "NC")
    assert ("A", "NO") not in forms
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    assert sim.scan_once({"A": False, "GUARD": True})["vars"].get("Y") is True


def test_reg3_timer_and_counter_classic_no_duplicate():
    prog = add_timer_rung(
        empty_program(), contact_tag="A", timer_tag="T1", pt_ms=500, block="TON"
    )
    rid = prog["rungs"][0]["id"]
    prog = append_series_contact(prog, rid, "GUARD")
    ms = _contact_multiset(program_rung_to_elements(prog["rungs"][0]))
    assert Counter(ms)[("A", "NO")] == 1
    assert ("GUARD", "NO") in ms


def test_reg3_template_classic_rungs_no_duplicate():
    for name in ("TwoHandStart", "ValveCycle", "OffDelayStop"):
        prog = apply_aoi_template(empty_program(), name)
        for rung in prog["rungs"]:
            if rung.get("elements"):
                continue  # classic-only probe
            rid = rung["id"]
            before = Counter(_contact_multiset(program_rung_to_elements(rung)))
            out = append_series_contact(prog, rid, "GUARD")
            after = Counter(
                _contact_multiset(
                    program_rung_to_elements(next(r for r in out["rungs"] if r["id"] == rid))
                )
            )
            for key, n in before.items():
                assert after[key] == n, f"{name}/{rid} dup {key}: {before} -> {after}"
            assert after[("GUARD", "NO")] == before[("GUARD", "NO")] + 1


# ---------- REG-4 ----------


def test_reg4_watch_csv_generic_reader():
    buf = WatchTrendBuffer()
    buf.set_tags(["M1", "PB_Start"])
    buf.set_label("PB_Start", "Start PB")
    for i in range(3):
        buf.record({"vars": {"M1": bool(i), "PB_Start": False}, "numbers": {}, "scan": i + 1})
    text = buf.to_csv()
    assert text.splitlines()[0].startswith("scan")
    reader = csv.DictReader(io.StringIO(text))
    assert reader.fieldnames[0] == "scan"
    rows = [
        r
        for r in reader
        if str(r.get("scan") or "") not in {"#", "#tag"}
        and not str(r.get("scan") or "").startswith("#")
    ]
    assert len(rows) == 3
    assert float(rows[0]["M1"]) == 0.0
    # Trailing design-aid notes present
    assert UL_NEEDLE in text
    assert "NFPA 79" in text or SAFETY_DESIGN_AID_NOTE in text
    # Sniffer must accept the dialect
    dialect = csv.Sniffer().sniff(text.splitlines()[0] + "\n" + text.splitlines()[1])
    assert dialect.delimiter == ","


# ---------- G-AID-2 ----------


def test_gaid2_appendix_continuation_pages_have_ul_footer():
    """HTML print appendix chunks each carry the exact UL line (including continuations)."""
    pytest.importorskip("customtkinter")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt":
        pytest.skip("No display")
    import customtkinter as ctk
    from cabinet_studio.models.project import Project
    from cabinet_studio.services.programming import program_to_dict
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    # Fat program so xref + PLC text overflow one sheet
    prog = empty_program()
    for i in range(40):
        prog = add_rung(prog, contact_tag=f"I{i}", coil_tag=f"O{i}", comment=f"rung {i}")
    root = ctk.CTk()
    root.withdraw()
    project = Project(
        name="Aid",
        template_id=None,
        cabinet_width=800,
        cabinet_height=600,
        cabinet_label="CP1",
        program=program_to_dict(prog),
        items=[],
    )
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *_: None)
    try:
        # Build print HTML the same way print_ladder does (without opening browser)
        import html as html_mod
        import tempfile
        from pathlib import Path as _Path

        from cabinet_studio.services.drawings import DISCLAIMER as _UL_AID
        from cabinet_studio.services.ladder_print import ladder_program_to_svg_pages
        from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE as _SAFETY
        from cabinet_studio.services.programming import cabinet_device_tags, format_plc_text

        rungs = [r for r in (v.program.get("rungs") or []) if isinstance(r, dict)]
        pages = ladder_program_to_svg_pages(rungs, width=1000, project_name=v.project.name or "Aid")
        xref_html = format_cross_reference_html(v.program, cabinet_device_tags(v.project))
        plc = v.program.get("plc_text") or format_plc_text(rungs, cabinet_device_tags(v.project))
        plc_html = html_mod.escape(plc)
        # Re-run the pagination helpers by calling print_ladder's construction via monkeypatch
        # of webbrowser — invoke print_ladder and read the temp HTML it writes.
        written = {}

        def _capture(url):
            written["url"] = url
            return True

        import webbrowser

        old_open = webbrowser.open
        webbrowser.open = _capture
        try:
            v.print_ladder()
            v.update()
        finally:
            webbrowser.open = old_open
        assert "url" in written
        # file:// path (url2pathname also handles file:///C:/... on Windows)
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        path = url2pathname(urlparse(written["url"]).path)
        if path.startswith("/tmp") or "cabinet_studio_ladder_print" in path:
            html_body = _Path(path).read_text(encoding="utf-8")
        else:
            html_body = _Path(tempfile.gettempdir(), "cabinet_studio_ladder_print.html").read_text(
                encoding="utf-8"
            )
        # Every appendix .page that is xref/PLC must include UL once
        pages_html = re.findall(r'<div class="page">(.*?)</div>', html_body, flags=re.DOTALL)
        appendix = [p for p in pages_html if "Tag cross-reference" in p or "PLC text" in p]
        assert appendix, "expected appendix pages"
        for i, block in enumerate(appendix):
            assert UL_NEEDLE in block, f"appendix page {i+1} missing UL"
            assert '<div class="footer">' in block and UL_NEEDLE in block.split('<div class="footer">', 1)[1], (
                f"appendix page {i+1} missing footer div with UL"
            )
    finally:
        try:
            v.close()
        except Exception:
            pass
        root.destroy()


# ---------- NEW-L CPT ----------


def test_new_l_hintless_cpt_keeps_full_expression():
    prog = add_math_rung(
        empty_program(),
        contact_tag="EN",
        op="CPT",
        dest="D",
        source_a="(A + 2) * 3",
        expression="(A + 2) * 3",
    )
    g = _graph_only(prog)
    math = next(e for e in program_rung_to_elements(g["rungs"][0]) if e.get("kind") == "math")
    assert math.get("expression") == "(A + 2) * 3"
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    sim.set_number("A", 4)
    assert sim.scan_once({"EN": True})["numbers"].get("D") == 18.0


def test_new_l_hintless_cpt_truncated_imports_verbatim_never_zero():
    """v0.3.17 (Raddus): a malformed CPT is no longer a whole-file refusal. It imports
    VERBATIM (never rewritten to 0), Verify flags it as an error and the sim refuses.
    v0.3.19 (Audit NEW-17): with IN1 blank the note's expr= is NOT used (a note is a label),
    so the CPT imports empty — still never 0, still flagged, still blocked."""
    xml = export_program_to_plcopen_xml(
        add_math_rung(
            empty_program(),
            contact_tag="EN",
            op="CPT",
            dest="D",
            source_a="1",
            expression="(A + 2) * 3",
        ),
        project_name="QA",
    )
    # Corrupt the MATH doc to a truncated expr= (old bug shape) AND clear IN1
    xml = _strip_embed(xml)
    xml = re.sub(
        r"(<xhtml:p>)MATH CPT[^<]*(</xhtml:p>)",
        r"\1MATH CPT dest=D a= b= expr=(A\2",
        xml,
        count=1,
    )
    # Also blank IN1 expression so fallback cannot recover
    xml = re.sub(
        r'(formalParameter="IN1">\s*<connectionPointIn>\s*<expression>)[^<]*',
        r"\1",
        xml,
        count=1,
    )
    from cabinet_studio.services.ladder_sim import sim_blockers
    from cabinet_studio.services.ladder_tools import verify_program

    prog = import_plcopen_xml_to_program(xml)
    math = next(e for e in program_rung_to_elements(prog["rungs"][0]) if e.get("kind") == "math")
    assert math.get("op") == "CPT" and math.get("expression") == ""
    assert any(i.get("severity") == "error" and i.get("code") in {"CPT_INVALID", "MISSING_OPERAND"}
               for i in verify_program(prog))
    assert sim_blockers(prog) and "Rung 1" in sim_blockers(prog)[0]


# ---------- Nested shapes ----------


def test_hintless_nested_or_lead_then_nested_then_series():
    """(X1·(X2|X3)·X5)|X4 — X5 must stay after the nested OR."""
    els = [
        {
            "kind": "or",
            "branches": [
                [
                    _contact_el("X1"),
                    {"kind": "or", "branches": [[_contact_el("X2")], [_contact_el("X3")]]},
                    _contact_el("X5"),
                ],
                [_contact_el("X4")],
            ],
        },
        _coil_el("Y"),
    ]
    g = _graph_only(add_rung_from_elements(empty_program(), els, comment="shape-c"))
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": True, "X2": True, "X3": False, "X4": False, "X5": True})["vars"].get("Y") is True
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": True, "X2": True, "X3": False, "X4": False, "X5": False})["vars"].get("Y") is not True


def test_hintless_nested_or_nested_first_then_series():
    """((X2|X3)·X1)|X4 — must not flatten to (X2|X3|X4)·X1."""
    els = [
        {
            "kind": "or",
            "branches": [
                [
                    {"kind": "or", "branches": [[_contact_el("X2")], [_contact_el("X3")]]},
                    _contact_el("X1"),
                ],
                [_contact_el("X4")],
            ],
        },
        _coil_el("Y"),
    ]
    g = _graph_only(add_rung_from_elements(empty_program(), els, comment="shape-b"))
    back = program_rung_to_elements(g["rungs"][0])
    top = [e for e in back if e.get("kind") == "or"]
    assert top, back
    # X4 must be its own top-level branch, not inside the nested OR with X2/X3
    branch_tags = []
    for br in top[0].get("branches") or []:
        tags = []
        for e in br or []:
            if e.get("kind") == "contact":
                tags.append(e.get("var"))
            elif e.get("kind") == "or":
                tags.append("OR")
        branch_tags.append(tags)
    assert any(t == ["X4"] or t == ["X4"] for t in branch_tags) or any(
        "X4" in t and "OR" not in t and len(t) == 1 for t in branch_tags
    ), branch_tags
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": False, "X2": False, "X3": False, "X4": True})["vars"].get("Y") is True
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": True, "X2": False, "X3": False, "X4": False})["vars"].get("Y") is not True


# ---------- Real viewer paths ----------


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
    reason="No display for CustomTkinter",
)
def test_viewer_add_series_and_parallel_real_path():
    pytest.importorskip("customtkinter")
    import customtkinter as ctk

    from cabinet_studio.models.project import PlacedItem, Project
    from cabinet_studio.services.programming import program_to_dict
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    prog = add_rung(empty_program(), contact_tag="PB_Start", coil_tag="M1")
    root = ctk.CTk()
    root.withdraw()
    items = [
        PlacedItem(id="i1", library_id=None, type_id="pushbutton", x=10, y=10, fields={"tag": "PB_Start"}),
        PlacedItem(id="i2", library_id=None, type_id="pushbutton", x=20, y=10, fields={"tag": "GUARD"}),
        PlacedItem(id="i3", library_id=None, type_id="contactor", x=30, y=10, fields={"tag": "M1"}),
        PlacedItem(id="i4", library_id=None, type_id="pushbutton", x=40, y=10, fields={"tag": "OR1"}),
    ]
    project = Project(
        name="V",
        template_id=None,
        cabinet_width=800,
        cabinet_height=600,
        cabinet_label="CP1",
        program=program_to_dict(prog),
        items=items,
    )
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *_: None)
    try:
        v.update()
        rid = v.program["rungs"][0]["id"]
        v._selected_rung_id = rid
        v.contact_var.set("GUARD")
        v.nc_var.set("NO")
        # Real viewer method (not a source grep)
        v._add_series_contact()
        v.update()
        ms = _contact_multiset(program_rung_to_elements(v.program["rungs"][0]))
        assert ms == [("PB_Start", "NO"), ("GUARD", "NO")], ms
        # Parallel via real viewer method
        v.contact_var.set("OR1")
        v._add_parallel_contact()
        v.update()
        after = _contact_multiset(program_rung_to_elements(v.program["rungs"][0]))
        assert ("OR1", "NO") in after
        assert Counter(after)[("PB_Start", "NO")] == 1
        assert Counter(after)[("GUARD", "NO")] == 1
    finally:
        try:
            v.close()
        except Exception:
            pass
        root.destroy()


def test_reg2_still_holds_on_compare_after_0314():
    prog = add_compare_rung(
        empty_program(),
        contact_tag="A",
        op="GRT",
        source_a="7",
        source_b="5",
        coil_tag="Y",
    )
    rid = prog["rungs"][0]["id"]
    prog = append_series_contact(prog, rid, "GUARD")
    ms = _contact_multiset(program_rung_to_elements(prog["rungs"][0]))
    assert ("A", "NO") in ms and ("GUARD", "NO") in ms
    assert Counter(ms)[("A", "NO")] == 1
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    assert sim.scan_once({"A": False, "GUARD": True})["vars"].get("Y") is not True
    assert sim.scan_once({"A": True, "GUARD": True})["vars"].get("Y") is True
