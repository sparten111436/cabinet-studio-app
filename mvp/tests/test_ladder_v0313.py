"""v0.3.13: REG-2 series-contact preserve, edit-ops matrix, UL surfaces, ACC, hint-less blocks."""
from __future__ import annotations

import json
import re
from copy import deepcopy

import pytest

from cabinet_studio import __version__
from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
from cabinet_studio.services.ladder_ir import (
    _coil_el,
    _contact_el,
    program_rung_to_elements,
)
from cabinet_studio.services.ladder_print import ladder_program_to_svg_pages
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import (
    AOI_TEMPLATES,
    SAFETY_DESIGN_AID_NOTE,
    apply_aoi_template,
    expand_aoi_template,
)
from cabinet_studio.services.ladder_tools import WatchTrendBuffer, copy_rungs, paste_rungs
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import (
    add_compare_rung,
    add_latch_rung,
    add_math_rung,
    add_mid_coil_rung,
    add_oneshot_rung,
    add_rung_from_elements,
    append_parallel_contact,
    append_series_contact,
    delete_rung,
    edit_rung,
    empty_program,
    format_ladder_html,
    format_ladder_txt,
    format_plc_text,
    program_from_dict,
    series_contacts_from_rung,
)

CYCLE = 100
UL_NEEDLE = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."
assert UL_NEEDLE == UL_DESIGN_AID


def _strip_embed(xml: str) -> str:
    return re.sub(r"cabinet-studio-elements:[^<]*", "", xml or "")


def _graph_only(prog: dict) -> dict:
    xml = export_program_to_plcopen_xml(prog, project_name="QA")
    return program_from_dict(import_plcopen_xml_to_program(_strip_embed(xml)))


def _contact_vars(els: list) -> set[str]:
    out: set[str] = set()

    def walk(nodes):
        for e in nodes or []:
            if not isinstance(e, dict):
                continue
            if e.get("kind") == "contact" and e.get("var"):
                out.add(str(e["var"]))
            if e.get("kind") == "or":
                for br in e.get("branches") or []:
                    walk(br)

    walk(els)
    return out


def _contact_multiset(els: list) -> list[tuple[str, str]]:
    """Ordered multiset of (var, form) for every contact — catches REG-3 duplicates."""
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


def _snapshot_logic(rung: dict) -> str:
    return json.dumps(program_rung_to_elements(rung), sort_keys=True, default=str)


def test_version_is_0313():
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 13)  # strict: parsed, not a prefix match


# ---------- REG-2 per rung type ----------


@pytest.mark.parametrize(
    "builder,kwargs,enable,out_tag",
    [
        (
            add_compare_rung,
            {"contact_tag": "A", "op": "GRT", "source_a": "7", "source_b": "5", "coil_tag": "Y"},
            "A",
            "Y",
        ),
        (
            add_math_rung,
            {"contact_tag": "A", "op": "MOV", "dest": "Q", "source_a": "3"},
            "A",
            None,
        ),
        (
            add_latch_rung,
            {"contact_tag": "A", "coil_tag": "Y", "latch": True},
            "A",
            "Y",
        ),
        (
            add_latch_rung,
            {"contact_tag": "A", "coil_tag": "Y", "latch": False},
            "A",
            "Y",
        ),
        (
            add_oneshot_rung,
            {"contact_tag": "A", "storage_tag": "OS1", "coil_tag": "Y", "block": "ONS"},
            "A",
            "Y",
        ),
    ],
)
def test_reg2_add_series_preserves_enable(builder, kwargs, enable, out_tag):
    prog = builder(empty_program(), **kwargs)
    rid = prog["rungs"][0]["id"]
    before = _contact_vars(program_rung_to_elements(prog["rungs"][0]))
    assert enable in before
    prog = append_series_contact(prog, rid, "GUARD")
    els = program_rung_to_elements(prog["rungs"][0])
    after = _contact_vars(els)
    assert enable in after, f"{enable} dropped by add-series"
    assert "GUARD" in after
    # A=0, GUARD=1 must NOT energize (enable still required)
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    forces = {enable: False, "GUARD": True}
    r = sim.scan_once(forces)
    if out_tag:
        assert r["vars"].get(out_tag) is not True
    if kwargs.get("op") == "MOV":
        assert r["numbers"].get("Q") in (None, 0, 0.0) or r["numbers"].get("Q") == 0.0


def test_reg2_mid_coil_add_series_preserves_contacts():
    prog = add_mid_coil_rung(
        empty_program(),
        contact_tag="A",
        mid_coil_tag="MID",
        after_contact_tag="B",
        coil_tag="Y",
    )
    rid = prog["rungs"][0]["id"]
    before = _contact_vars(program_rung_to_elements(prog["rungs"][0]))
    prog = append_series_contact(prog, rid, "GUARD")
    after = _contact_vars(program_rung_to_elements(prog["rungs"][0]))
    assert before <= after
    assert "GUARD" in after


def test_reg2_motor_starter_reg1_still_holds():
    prog = apply_aoi_template(empty_program(), "MotorStarter")
    rid = prog["rungs"][0]["id"]
    before = _contact_vars(program_rung_to_elements(prog["rungs"][0]))
    prog = append_series_contact(prog, rid, "GUARD")
    after = _contact_vars(program_rung_to_elements(prog["rungs"][0]))
    assert before <= after
    assert "GUARD" in after
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    sim.scan_once({"PB_Start": True, "PB_Stop": False, "GUARD": False})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False, "GUARD": False})["vars"].get("M1") is not True
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    sim.scan_once({"PB_Start": True, "PB_Stop": False, "GUARD": True})
    assert sim.scan_once({"PB_Start": False, "PB_Stop": False, "GUARD": True})["vars"].get("M1") is True


def test_reg2_ui_legacy_empty_series_path_via_edit_rung():
    """UI used to pass series=[GUARD] alone; sync must append, not replace."""
    prog = add_compare_rung(
        empty_program(),
        contact_tag="A",
        op="GRT",
        source_a="7",
        source_b="5",
        coil_tag="Y",
    )
    rid = prog["rungs"][0]["id"]
    assert not (prog["rungs"][0].get("series") or [])
    prog = edit_rung(prog, rid, series=[{"tag": "GUARD", "normally_closed": False}])
    vars_ = _contact_vars(program_rung_to_elements(prog["rungs"][0]))
    assert "A" in vars_ and "GUARD" in vars_
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    assert sim.scan_once({"A": False, "GUARD": True})["vars"].get("Y") is not True
    assert sim.scan_once({"A": True, "GUARD": True})["vars"].get("Y") is True


# ---------- 36-rung edit-ops matrix (regression gate) ----------


def _all_matrix_cases() -> list[tuple[str, dict, str]]:
    """(label, program_with_one_focus_rung_or_multi, focus_rung_id)."""
    cases: list[tuple[str, dict, str]] = []
    for name in sorted(AOI_TEMPLATES):
        prog = apply_aoi_template(empty_program(), name)
        for i, rung in enumerate(prog["rungs"]):
            # Single-rung program so delete/paste isolation is clear
            one = empty_program()
            one["rungs"] = [deepcopy(rung)]
            one["rungs"][0]["id"] = rung["id"]
            cases.append((f"TPL:{name}:r{i+1}", one, rung["id"]))
    # UI forms to reach ~36 with templates (33) + a few UI
    ui = [
        ("UI:compare", add_compare_rung(empty_program(), contact_tag="A", op="GRT", source_a="7", source_b="5", coil_tag="Y")),
        ("UI:math", add_math_rung(empty_program(), contact_tag="A", op="ADD", dest="Q", source_a="1", source_b="2")),
        ("UI:otl", add_latch_rung(empty_program(), contact_tag="A", coil_tag="Y", latch=True)),
        ("UI:oneshot", add_oneshot_rung(empty_program(), contact_tag="A", storage_tag="OS1", coil_tag="Y")),
        # v0.3.18 (Audit): parallel coils — add series must gate every coil
        ("UI:parallel_coils", add_rung_from_elements(empty_program(), [
            {"kind": "contact", "var": "A", "form": "NO"},
            {"kind": "or", "branches": [[{"kind": "coil", "var": "Y", "form": "normal"}],
                                        [{"kind": "coil", "var": "Z", "form": "normal"}]]},
        ])),
    ]
    for label, prog in ui:
        cases.append((label, prog, prog["rungs"][0]["id"]))
    return cases


_MATRIX = _all_matrix_cases()


def test_matrix_case_count_covers_templates_and_ui():
    assert len(_MATRIX) >= 36, f"expected >=36 cases, got {len(_MATRIX)}"
    tpl = [c for c in _MATRIX if c[0].startswith("TPL:")]
    assert len(tpl) == 33


@pytest.mark.parametrize("label,prog,rid", _MATRIX, ids=[c[0] for c in _MATRIX])
@pytest.mark.parametrize("op", ["add_series", "add_parallel", "tag_edit", "delete", "paste"])
def test_edit_ops_preserve_original_logic(label, prog, rid, op):
    """Every edit op on every template/UI rung: original contacts survive; GUARD=True sim OK."""
    prog = program_from_dict(deepcopy(prog))
    rung0 = next(r for r in prog["rungs"] if r["id"] == rid)
    before_vars = _contact_vars(program_rung_to_elements(rung0))
    before_snap = _snapshot_logic(rung0)

    if op == "add_series":
        before_ms = _contact_multiset(program_rung_to_elements(rung0))
        out = append_series_contact(prog, rid, "GUARD")
        rung = next(r for r in out["rungs"] if r["id"] == rid)
        after_els = program_rung_to_elements(rung)
        after_vars = _contact_vars(after_els)
        after_ms = _contact_multiset(after_els)
        assert before_vars <= after_vars, f"{label}: add_series dropped {before_vars - after_vars}"
        assert "GUARD" in after_vars
        # REG-3: every pre-existing contact instance must appear exactly once more GUARD
        from collections import Counter
        bc, ac = Counter(before_ms), Counter(after_ms)
        for key, n in bc.items():
            assert ac[key] == n, f"{label}: add_series duplicated {key}: before={n} after={ac[key]} ms={after_ms}"
        assert ac[("GUARD", "NO")] == bc[("GUARD", "NO")] + 1
        sim = ScanSimulator.from_program(out, cycle_ms=CYCLE)
        forces = {t: True for t in after_vars}
        sim.scan_once(forces)
        if label == "UI:parallel_coils":  # v0.3.18: the new series contact gates EVERY coil
            v_on = ScanSimulator.from_program(out, cycle_ms=CYCLE).scan_once({"A": True, "GUARD": True})["vars"]
            v_off = ScanSimulator.from_program(out, cycle_ms=CYCLE).scan_once({"A": True, "GUARD": False})["vars"]
            assert v_on.get("Y") and v_on.get("Z"), after_els
            assert not v_off.get("Y") and not v_off.get("Z"), after_els
    elif op == "add_parallel":
        before_ms = _contact_multiset(program_rung_to_elements(rung0))
        out = append_parallel_contact(prog, rid, "GUARD")
        rung = next(r for r in out["rungs"] if r["id"] == rid)
        after_els = program_rung_to_elements(rung)
        after_vars = _contact_vars(after_els)
        after_ms = _contact_multiset(after_els)
        assert before_vars <= after_vars, f"{label}: add_parallel dropped {before_vars - after_vars}"
        assert "GUARD" in after_vars
        from collections import Counter
        bc, ac = Counter(before_ms), Counter(after_ms)
        for key, n in bc.items():
            assert ac[key] == n, f"{label}: add_parallel duplicated {key}: before={n} after={ac[key]}"
        assert ac[("GUARD", "NO")] == bc[("GUARD", "NO")] + 1
        sim = ScanSimulator.from_program(out, cycle_ms=CYCLE)
        forces = {t: False for t in after_vars}
        sim.scan_once(forces)
    elif op == "tag_edit":
        # Rename coil if present, else first contact — structure must remain
        els = program_rung_to_elements(rung0)
        coil = next((e for e in els if e.get("kind") == "coil" and e.get("var")), None)
        if coil:
            out = edit_rung(prog, rid, coil_tag="RENAMED_COIL")
            rung = next(r for r in out["rungs"] if r["id"] == rid)
            assert any(
                e.get("kind") == "coil" and e.get("var") == "RENAMED_COIL"
                for e in program_rung_to_elements(rung)
            )
        else:
            # Math-only etc.: append series then ensure snap length stable
            out = append_series_contact(prog, rid, "GUARD")
            assert "GUARD" in _contact_vars(program_rung_to_elements(out["rungs"][0]))
        ScanSimulator.from_program(out, cycle_ms=CYCLE).scan_once({})
    elif op == "delete":
        # Paste a copy first, delete the copy, original logic intact
        clip = copy_rungs(prog, [rid])
        out, new_ids = paste_rungs(prog, clip, after_id=rid)
        assert new_ids
        out = delete_rung(out, new_ids[0])
        left = next(r for r in out["rungs"] if r["id"] == rid)
        assert _snapshot_logic(left) == before_snap
        assert _contact_vars(program_rung_to_elements(left)) == before_vars
    elif op == "paste":
        clip = copy_rungs(prog, [rid])
        out, new_ids = paste_rungs(prog, clip, after_id=rid)
        assert new_ids
        orig = next(r for r in out["rungs"] if r["id"] == rid)
        pasted = next(r for r in out["rungs"] if r["id"] == new_ids[0])
        assert _contact_vars(program_rung_to_elements(orig)) == before_vars
        assert _contact_vars(program_rung_to_elements(pasted)) == before_vars
        ScanSimulator.from_program(out, cycle_ms=CYCLE).scan_once({})


# ---------- P2a UL / design-aid surfaces ----------


def test_ul_line_on_all_export_surfaces():
    prog = apply_aoi_template(empty_program(), "MotorStarter")
    txt = format_ladder_txt(prog, cabinet_name="QA")
    html = format_ladder_html(prog, cabinet_name="QA")
    plc = format_plc_text(prog["rungs"])
    xml = export_program_to_plcopen_xml(prog, project_name="QA")
    pages = ladder_program_to_svg_pages(prog["rungs"], width=1000, project_name="QA")
    svg = "\n".join(pg[0] for pg in pages)
    buf = WatchTrendBuffer()
    buf.set_tags(["M1", "PB_Start"])
    buf.record({"vars": {"M1": False, "PB_Start": False}, "numbers": {}, "scan": 1})
    csv = buf.to_csv()
    for surface, body in [
        ("ladder-txt", txt),
        ("ladder-html", html),
        ("plc_text/CopyPLC/Export", plc),
        ("plcopen", xml),
        ("print-svg", svg),
        ("watch-csv", csv),
    ]:
        assert UL_NEEDLE in body, f"{surface} missing exact UL line"
        assert ("NFPA 79" in body or "ISO 13849" in body or SAFETY_DESIGN_AID_NOTE in body), (
            f"{surface} missing NFPA/ISO note"
        )


def test_print_svg_ul_appears_once_per_sheet():
    prog = apply_aoi_template(empty_program(), "TwoHandStart")
    pages = ladder_program_to_svg_pages(prog["rungs"], width=1000, project_name="QA")
    assert pages
    for i, (svg, _, _) in enumerate(pages):
        assert svg.count(UL_NEEDLE) == 1, f"sheet {i+1} UL count={svg.count(UL_NEEDLE)}"


# ---------- P2c ACC in compare ----------


def test_sim_reads_timer_acc_in_compare():
    from cabinet_studio.services.programming import add_timer_rung

    prog = add_timer_rung(
        empty_program(),
        contact_tag="EN",
        timer_tag="T1",
        pt_ms=1000,
        block="TON",
    )
    prog = add_compare_rung(
        prog,
        contact_tag="EN",
        op="GRT",
        source_a="T1.ACC",
        source_b="500",
        coil_tag="Y",
    )
    # Seed T1.ACC as numeric 0 (the bug path) via variables — still must read live ACC
    prog.setdefault("variables", []).append(
        {"name": "T1.ACC", "class": "numeric", "type": "DINT", "value": 0}
    )
    sim = ScanSimulator.from_program(prog, cycle_ms=100)
    # Run timer until ACC > 500
    for _ in range(6):
        r = sim.scan_once({"EN": True})
    assert float(sim.timers["T1"]["acc_ms"]) >= 500
    assert r["vars"].get("Y") is True
    # Below threshold
    sim2 = ScanSimulator.from_program(prog, cycle_ms=100)
    r2 = sim2.scan_once({"EN": True})  # ACC=100
    assert float(sim2.timers["T1"]["acc_ms"]) < 500
    assert r2["vars"].get("Y") is not True


# ---------- P2b hint-less compare/math ----------


def test_hintless_import_keeps_compare_and_math():
    prog = add_compare_rung(
        empty_program(),
        contact_tag="Auto",
        op="LIM",
        source_a="Level",
        source_b="10",
        source_c="90",
        coil_tag="InBand",
    )
    prog = add_math_rung(
        prog,
        contact_tag="Auto",
        op="MUL",
        dest="Scaled",
        source_a="Work",
        source_b="10",
    )
    g = _graph_only(prog)
    kinds = []
    for r in g["rungs"]:
        for e in program_rung_to_elements(r):
            kinds.append(e.get("kind"))
    assert "compare" in kinds, f"compare dropped; kinds={kinds}"
    assert "math" in kinds, f"math dropped; kinds={kinds}"
    # LIM still works after hint-less
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    sim.set_number("Level", 50)
    assert sim.scan_once({"Auto": True})["vars"].get("InBand") is True
    sim.set_number("Level", 200)
    assert sim.scan_once({"Auto": True})["vars"].get("InBand") is not True


def test_hintless_nested_or_in_or_branch_or_warns():
    """(X1·(X2|X3))|X4 — keep nested OR, or leave a clear warning comment."""
    els = [
        {
            "kind": "or",
            "branches": [
                [
                    _contact_el("X1"),
                    {"kind": "or", "branches": [[_contact_el("X2")], [_contact_el("X3")]]},
                ],
                [_contact_el("X4")],
            ],
        },
        _coil_el("Y"),
    ]
    prog = add_rung_from_elements(empty_program(), els, comment="or-in-or")  # v0.3.14: must not pass via fixture keyword alone
    g = _graph_only(prog)
    assert g.get("rungs"), "import dropped rung"
    back = program_rung_to_elements(g["rungs"][0])
    # Prefer correct structure
    top_ors = [e for e in back if e.get("kind") == "or"]
    nested_ok = False
    if len(top_ors) == 1:
        for br in top_ors[0].get("branches") or []:
            if any(isinstance(x, dict) and x.get("kind") == "or" for x in (br or [])):
                nested_ok = True
    comment = str(g["rungs"][0].get("comment") or "")
    # Always assert educational truth table (do not pass via fixture comment keywords).
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": False, "X2": False, "X3": False, "X4": True})["vars"].get("Y") is True
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": True, "X2": False, "X3": False, "X4": False})["vars"].get("Y") is not True
    sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    assert sim.scan_once({"X1": True, "X2": True, "X3": False, "X4": False})["vars"].get("Y") is True
    if not nested_ok:
        warn = (
            "nested" in comment.lower()
            or "warn" in comment.lower()
            or "simplified" in comment.lower()
            or "rewired" in comment.lower()
            or "hint" in comment.lower()
        )
        # Truth already checked; require an explicit warn if structure was flattened.
        assert warn, f"nested OR flattened without warning; elements={back!r} comment={comment!r}"


def test_series_contacts_from_rung_reads_elements_not_empty_legacy():
    prog = add_compare_rung(
        empty_program(), contact_tag="ES_OK", op="LES", source_a="Level", source_b="90", coil_tag="Pump"
    )
    series = series_contacts_from_rung(prog["rungs"][0])
    assert any(c.get("tag") == "ES_OK" for c in series)
