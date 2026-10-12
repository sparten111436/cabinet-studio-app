"""v0.3.15: REG-5 (hint-less outer-join miswire, SAFETY), N-2 classic edit_rung(series=),
N-4 PLC-text print overflow pages without UL/NFPA footer.

Every REG-5 test exports with Cabinet Studio, STRIPS the ``cabinet-studio-elements``
hint, re-imports, and compares against the native program in the scan simulator.
"""
from __future__ import annotations

import itertools
import os
import random
import re
import shutil
import subprocess
from collections import Counter

import pytest

from cabinet_studio import __version__
from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
from cabinet_studio.services.ladder_ir import program_rung_to_elements
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import (
    AOI_TEMPLATES,
    SAFETY_DESIGN_AID_NOTE,
    apply_aoi_template,
)
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import (
    add_rung,
    add_rung_from_elements,
    append_series_contact,
    edit_rung,
    empty_program,
    format_plc_text,
    program_from_dict,
)

CYCLE = 100
UL_NEEDLE = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."
assert UL_NEEDLE == UL_DESIGN_AID


def C(v, nc=False):
    return {"kind": "contact", "var": v, "form": "NC" if nc else "NO"}


def O(v):
    return {"kind": "coil", "var": v, "form": "normal"}


def OR(*branches):
    return {"kind": "or", "branches": [list(b) for b in branches]}


def _strip_hint(xml: str) -> str:
    xml = re.sub(r"<documentation>\s*cabinet-studio-elements:.*?</documentation>", "", xml, flags=re.S)
    xml = re.sub(
        r"<documentation>\s*<(?:xhtml:)?p[^>]*>cabinet-studio-elements:.*?</(?:xhtml:)?p>\s*</documentation>",
        "",
        xml,
        flags=re.S,
    )
    return re.sub(r"cabinet-studio-elements:[^<]*", "", xml)


def _hintless(prog: dict) -> dict:
    xml = _strip_hint(export_program_to_plcopen_xml(prog, project_name="QA"))
    assert "cabinet-studio-elements" not in xml
    return program_from_dict(import_plcopen_xml_to_program(xml))


def _fmt(els) -> str:
    out = []
    for e in els or []:
        k = e.get("kind")
        if k == "contact":
            out.append(("/" if str(e.get("form")).upper() == "NC" else "") + e["var"])
        elif k == "or":
            out.append("(" + " | ".join(_fmt(b) for b in e["branches"]) + ")")
        elif k == "coil":
            out.append(f"({e['var']})")
        else:
            out.append(f"[{e.get('block') or e.get('op') or k} {e.get('var') or ''}]".strip())
    return " ".join(out)


def _top_level_contacts(els) -> list[tuple[str, str]]:
    return [
        (str(e.get("var")), str(e.get("form") or "NO").upper())
        for e in els or []
        if isinstance(e, dict) and e.get("kind") == "contact"
    ]


def _all_contacts(els) -> list[tuple[str, str]]:
    out = []
    for e in els or []:
        if not isinstance(e, dict):
            continue
        if e.get("kind") == "contact":
            out.append((str(e.get("var")), str(e.get("form") or "NO").upper()))
        if e.get("kind") == "or":
            for b in e.get("branches") or []:
                out.extend(_all_contacts(b))
    return out


def _out(prog, inputs, coil, scans=3):
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    v = None
    for _ in range(scans):
        v = sim.scan_once(dict(inputs))["vars"]
    return bool(v.get(coil))


def test_version_is_0315():
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 15)  # strict: parsed, not a prefix match


# ---------------------------------------------------------------- REG-5 exact shape


REG5_ELS = [
    OR([C("PB_Start")], [C("M1"), OR([C("Auto")], [C("Manual")])]),
    C("PB_Stop", True),
    O("M1"),
]


def test_reg5_exact_shape_stop_stays_in_series_outside_or():
    """(PB_Start | M1·(Auto|Manual))·/PB_Stop → M1: /PB_Stop must stay after the OR."""
    native = add_rung_from_elements(empty_program(), REG5_ELS)
    g = _hintless(native)
    els = program_rung_to_elements(g["rungs"][0])
    assert ("PB_Stop", "NC") in _top_level_contacts(els), _fmt(els)
    # Stop is NOT inside any OR branch
    ors = [e for e in els if e.get("kind") == "or"]
    assert ors, _fmt(els)
    for o in ors:
        assert ("PB_Stop", "NC") not in _all_contacts(o["branches"][0] + o["branches"][-1]), _fmt(els)
    assert Counter(_all_contacts(els)) == Counter(_all_contacts(REG5_ELS)), _fmt(els)
    assert _fmt(els) == "(PB_Start | M1 (Auto | Manual)) /PB_Stop (M1)"


def test_reg5_exact_shape_truth_table_and_stop_held_never_energizes():
    native = add_rung_from_elements(empty_program(), REG5_ELS)
    g = _hintless(native)
    ins = ["Auto", "Manual", "PB_Start", "PB_Stop"]
    for vals in itertools.product([False, True], repeat=len(ins)):
        f = dict(zip(ins, vals))
        a, b = _out(native, f, "M1"), _out(g, f, "M1")
        assert a == b, f"{f}: native={a} imported={b} rung={_fmt(program_rung_to_elements(g['rungs'][0]))}"
        if f["PB_Stop"]:
            assert b is False, f"Stop held but M1 energized: {f}"
    # Explicit unsafe repro from Audit: Start pressed with Stop held
    assert _out(g, {"PB_Start": True, "PB_Stop": True, "Auto": False, "Manual": False}, "M1") is False


def test_reg5_generic_shape_full_truth_table():
    """(A | B·(C|D))·S → Y: all 32 combos match native; S=0 never energizes."""
    els = [OR([C("A")], [C("B"), OR([C("C")], [C("D")])]), C("S"), O("Y")]
    native = add_rung_from_elements(empty_program(), els)
    g = _hintless(native)
    ge = program_rung_to_elements(g["rungs"][0])
    assert _fmt(ge) == "(A | B (C | D)) S (Y)", _fmt(ge)
    ins = ["A", "B", "C", "D", "S"]
    for vals in itertools.product([False, True], repeat=5):
        f = dict(zip(ins, vals))
        a, b = _out(native, f, "Y"), _out(g, f, "Y")
        assert a == b, f"{f}: native={a} imported={b}"
        if not f["S"]:
            assert b is False


@pytest.mark.parametrize(
    "els,expect",
    [
        # series contact after the OR, nested OR last in branch 2
        ([OR([C("A")], [C("B"), OR([C("C")], [C("D")])]), C("S"), C("T", True), O("Y")],
         "(A | B (C | D)) S /T (Y)"),
        # timer after the OR must not be pulled into branch 2
        ([OR([C("A")], [C("B"), OR([C("C")], [C("D")])]),
          {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 100}, O("Y")],
         "(A | B (C | D)) [TON T1] (Y)"),
        # nested OR followed by an in-branch contact, then outer series
        ([OR([C("A")], [C("B"), OR([C("C")], [C("D")]), C("E")]), C("S"), O("Y")],
         "(A | B (C | D) E) S (Y)"),
        # three top-level branches, nested last
        ([OR([C("A")], [C("F")], [C("B"), OR([C("C")], [C("D")])]), C("S", True), O("Y")],
         "(A | F | B (C | D)) /S (Y)"),
        # nested-branch-first (regression guard for the unaffected variant)
        ([OR([C("B"), OR([C("C")], [C("D")])], [C("A")]), C("S"), O("Y")],
         "(B (C | D) | A) S (Y)"),
    ],
)
def test_reg5_outer_join_variants_structure(els, expect):
    g = _hintless(add_rung_from_elements(empty_program(), els))
    assert _fmt(program_rung_to_elements(g["rungs"][0])) == expect


# ------------------------------------------- Raddus: randomized Stop placement

_STARTS = ["S1", "S2", "S3"]
_PERMS = ["P1", "P2", "P3"]
_MODES = ["Auto", "Manual", "Local"]


def _rand_branch(rnd, base):
    br = list(base)
    if rnd.random() < 0.5:
        br.append(C(rnd.choice(_PERMS), rnd.random() < 0.3))
    if rnd.random() < 0.55:
        k = rnd.randint(2, 3)
        nested = OR(*[[C(m)] for m in rnd.sample(_MODES, k)])
        br.insert(rnd.randint(0, len(br)), nested)
    return br


def _random_seal_in(rnd):
    """Seal-in rung: (starts | Y·…) with /PB_Stop at a random TOP-LEVEL position."""
    branches = [_rand_branch(rnd, [C(s)]) for s in rnd.sample(_STARTS, rnd.randint(1, 2))]
    branches.append(_rand_branch(rnd, [C("Y")]))
    rnd.shuffle(branches)
    top = [OR(*branches)]
    for _ in range(rnd.randint(0, 2)):
        top.insert(rnd.randint(0, len(top)), C(rnd.choice(_PERMS), rnd.random() < 0.3))
    top.insert(rnd.randint(0, len(top)), C("PB_Stop", True))
    return top + [O("Y")]


def _seq_inputs(rnd, names, stop_held):
    f = {n: rnd.random() < 0.5 for n in names}
    if stop_held:
        f["PB_Stop"] = True
    return f


@pytest.mark.parametrize("seed", range(6))
def test_reg5_randomized_stop_placement_seal_in_never_energizes_with_stop_held(seed):
    rnd = random.Random(1500 + seed)
    names = _STARTS + _PERMS + _MODES + ["PB_Stop"]
    for case in range(50):
        els = _random_seal_in(rnd)
        native = add_rung_from_elements(empty_program(), els)
        g = _hintless(native)
        ge = program_rung_to_elements(g["rungs"][0])
        label = f"seed={seed} case={case} native={_fmt(els)} imported={_fmt(ge)}"
        # Structure: Stop stays a top-level series contact and appears exactly once
        assert ("PB_Stop", "NC") in _top_level_contacts(ge), label
        assert Counter(_all_contacts(ge))[("PB_Stop", "NC")] == 1, label
        assert Counter(_all_contacts(ge)) == Counter(_all_contacts(els)), label
        # Stop held from power-up: imported never energizes over a random sequence
        sim_g = ScanSimulator.from_program(g, cycle_ms=CYCLE)
        for _ in range(12):
            v = sim_g.scan_once(_seq_inputs(rnd, names, stop_held=True))["vars"]
            assert not v.get("Y"), "Stop held but Y energized: " + label
        # Sealed first, then Stop pressed: imported drops out and stays out
        sim_n = ScanSimulator.from_program(native, cycle_ms=CYCLE)
        sim_g = ScanSimulator.from_program(g, cycle_ms=CYCLE)
        for step in range(16):
            f = _seq_inputs(rnd, names, stop_held=step >= 8)
            a = bool(sim_n.scan_once(dict(f))["vars"].get("Y"))
            b = bool(sim_g.scan_once(dict(f))["vars"].get("Y"))
            assert a == b, f"step {step} {f}: native={a} imported={b} " + label
            if step >= 8:
                assert b is False, "Stop held but Y energized: " + label


def _stop_rungs(prog):
    """(rung index, stop var, coils) for rungs with a top-level NC *stop* contact."""
    out = []
    rungs = prog["rungs"]
    written = Counter()
    for r in rungs:
        for e in program_rung_to_elements(r):
            if e.get("kind") == "coil":
                written[e["var"]] += 1
    for i, r in enumerate(rungs):
        els = program_rung_to_elements(r)
        stops = [v for v, f in _top_level_contacts(els) if f == "NC" and "stop" in v.lower()]
        coils = [
            e["var"] for e in els
            if e.get("kind") == "coil" and str(e.get("form") or "normal") == "normal" and written[e["var"]] == 1
        ]
        if stops and coils:
            out.append((i, stops[0], coils))
    return out


@pytest.mark.parametrize("name", sorted(AOI_TEMPLATES))
def test_reg5_templates_hintless_stop_held_never_energizes(name):
    native = program_from_dict(apply_aoi_template(empty_program(), name))
    g = _hintless(native)
    assert len(g["rungs"]) == len(native["rungs"])
    coil_vars = {
        e["var"] for r in native["rungs"] for e in program_rung_to_elements(r) if e.get("kind") == "coil"
    }
    inputs = sorted({
        v for r in native["rungs"] for v, _ in _all_contacts(program_rung_to_elements(r))
        if v not in coil_vars and "." not in v
    })
    rnd = random.Random(hash(name) & 0xFFFF)
    for idx, stop, coils in _stop_rungs(native):
        ge = program_rung_to_elements(g["rungs"][idx])
        assert (stop, "NC") in _top_level_contacts(ge), f"{name} rung {idx}: {_fmt(ge)}"
        for trial in range(20):
            sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
            for _ in range(8):
                f = {n: rnd.random() < 0.5 for n in inputs}
                f[stop] = True
                v = sim.scan_once(f)["vars"]
                for c in coils:
                    assert not v.get(c), f"{name}: {stop} held but {c} energized ({f})"


# ---------------------------------------------------------------- N-2


def _classic_ab():
    p = add_rung(empty_program(), contact_tag="A", coil_tag="Y",
                 parallel=[[{"tag": "A", "normally_closed": False}]],
                 series=[{"tag": "B", "normally_closed": False}])
    return p, p["rungs"][0]["id"]


def test_n2_edit_rung_series_empty_keeps_lead_contact():
    p, rid = _classic_ab()
    q = edit_rung(p, rid, series=[])
    els = program_rung_to_elements(q["rungs"][0])
    assert _fmt(els) == "A (Y)"
    assert _out(q, {"A": False, "B": True}, "Y") is False
    assert _out(q, {"A": True, "B": False}, "Y") is True


def test_n2_edit_rung_series_replace_keeps_lead_contact():
    p, rid = _classic_ab()
    q = edit_rung(p, rid, series=[{"tag": "B"}, {"tag": "GUARD"}])
    els = program_rung_to_elements(q["rungs"][0])
    assert Counter(_all_contacts(els)) == Counter([("A", "NO"), ("B", "NO"), ("GUARD", "NO")])
    assert _out(q, {"A": False, "B": True, "GUARD": True}, "Y") is False
    assert _out(q, {"A": True, "B": True, "GUARD": True}, "Y") is True


def test_n2_old_ui_style_series_with_lead_copy_not_duplicated():
    """REG-3 guard: payload built from series_contacts_from_rung() starts with A."""
    p, rid = _classic_ab()
    q = edit_rung(p, rid, series=[{"tag": "A"}, {"tag": "B"}, {"tag": "GUARD"}])
    els = program_rung_to_elements(q["rungs"][0])
    assert Counter(_all_contacts(els)) == Counter([("A", "NO"), ("B", "NO"), ("GUARD", "NO")]), _fmt(els)


def test_n2_add_rung_contact_tag_with_series_keeps_lead():
    p = add_rung(empty_program(), contact_tag="A", coil_tag="Y", series=[{"tag": "B"}])
    assert _fmt(program_rung_to_elements(p["rungs"][0])) == "A B (Y)"
    q = edit_rung(p, p["rungs"][0]["id"], series=[])
    assert _fmt(program_rung_to_elements(q["rungs"][0])) == "A (Y)"


def test_n2_classic_append_series_still_exact():
    p = add_rung(empty_program(), contact_tag="A", coil_tag="Y")
    q = append_series_contact(p, p["rungs"][0]["id"], "GUARD")
    assert Counter(_all_contacts(program_rung_to_elements(q["rungs"][0]))) == Counter(
        [("A", "NO"), ("GUARD", "NO")]
    )


# ---------------------------------------------------------------- N-4


def _stress_program(n=70):
    p = empty_program()
    for i in range(n):
        p = add_rung(
            p, contact_tag=f"In_{i:02d}", coil_tag=f"Out_{i:02d}",
            series=[{"tag": "Very_Long_Interlock_Tag_Name_For_Wrapping_%02d" % i, "normally_closed": i % 2 == 1},
                    {"tag": "Another_Extremely_Long_Permissive_%02d" % i}],
            comment=("Rung %d comment that is deliberately long so that the PLC text listing wraps "
                     "across the printable width of the page " % i) * 2,
        )
    return program_from_dict(p)


def test_n4_paginate_rows_and_cols_bounded():
    from cabinet_studio.services.ladder_print import (
        PRINT_PLC_COLS,
        PRINT_PLC_ROWS,
        paginate_plain_text,
    )

    plc = format_plc_text(_stress_program()["rungs"])
    pages = paginate_plain_text(plc, drop_lines=(UL_NEEDLE,))
    src_lines = plc.splitlines()
    assert len(pages) > -(-len(src_lines) // 45), "must paginate by visual rows, not 45 source lines"
    for pg in pages:
        assert 0 < len(pg) <= PRINT_PLC_ROWS
        for row in pg:
            assert len(row) <= PRINT_PLC_COLS
            assert UL_NEEDLE not in row
    # Nothing lost: all non-UL characters survive wrapping
    joined = "".join(r.strip() for pg in pages for r in pg).replace(" ", "")
    expect = "".join(l.strip() for l in src_lines if l.strip() != UL_NEEDLE).replace(" ", "")
    assert joined == expect
    # Geometry sanity for letter (10in usable at 0.5in margins): 9pt mono, 1.2 line-height
    assert PRINT_PLC_ROWS * 9 * 1.2 + 140 <= 720
    assert PRINT_PLC_COLS * 5.4 <= 540


def _print_html(prog, name, tmp_path, monkeypatch):
    pytest.importorskip("customtkinter")
    import tempfile
    import types
    import webbrowser

    from cabinet_studio.ui import programming_viewer as pv

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)
    if hasattr(os, "startfile"):
        monkeypatch.delattr(os, "startfile")
    status = types.SimpleNamespace(text=None)
    status.configure = lambda **kw: setattr(status, "text", kw.get("text"))
    stub = types.SimpleNamespace(
        program=prog,
        project=types.SimpleNamespace(name=name, items=[]),
        _flush_editor_to_program=lambda: None,
        status=status,
    )
    pv.ProgrammingViewer.print_ladder(stub)
    out = tmp_path / "cabinet_studio_ladder_print.html"
    assert out.exists(), status.text
    return out


def _split_pages(html_body: str) -> list[str]:
    parts = re.split(r'<div class="(?:sheet )?page">', html_body)
    return parts[1:]


@pytest.mark.parametrize("which", ["stress", "MotorStarter", "TwoHandStart"])
def test_n4_every_print_page_has_footer_exactly_once(which, tmp_path, monkeypatch):
    from cabinet_studio.services.ladder_print import PRINT_PLC_COLS, PRINT_PLC_ROWS, paginate_plain_text

    prog = _stress_program() if which == "stress" else program_from_dict(apply_aoi_template(empty_program(), which))
    body = _print_html(prog, which, tmp_path, monkeypatch).read_text(encoding="utf-8")
    pages = _split_pages(body)
    assert pages
    for i, pg in enumerate(pages, 1):
        assert pg.count(UL_NEEDLE) == 1, f"page {i}: UL x{pg.count(UL_NEEDLE)}"
        assert "NFPA 79" in pg, f"page {i}: NFPA note missing"
    plc_pages = [p for p in pages if "<h2>PLC text" in p]
    plc = prog.get("plc_text") or format_plc_text(prog["rungs"])
    assert len(plc_pages) == len(paginate_plain_text(plc, drop_lines=(UL_NEEDLE,)))
    for pg in plc_pages:
        pre = re.search(r"<pre>(.*?)</pre>", pg, flags=re.S).group(1)
        rows = pre.split("\n")
        assert len(rows) <= PRINT_PLC_ROWS
        import html as _h
        assert all(len(_h.unescape(r)) <= PRINT_PLC_COLS for r in rows)
    if which == "stress":
        assert len(plc_pages) > 10, "stress PLC text must span many pages"
        assert sum("(continued)" in p for p in plc_pages) == len(plc_pages) - 1


@pytest.mark.skipif(
    not (shutil.which("google-chrome") or shutil.which("chromium")) or not shutil.which("pdftotext"),
    reason="needs headless Chrome + poppler for physical page check",
)
def test_n4_rendered_pdf_every_physical_page_has_footer_once(tmp_path, monkeypatch):
    """Physical check: rendered pages == .page divs (no overflow) and UL once per page."""
    html_path = _print_html(_stress_program(), "STRESS", tmp_path, monkeypatch)
    divs = len(_split_pages(html_path.read_text(encoding="utf-8")))
    pdf = tmp_path / "out.pdf"
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    subprocess.run(
        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
         "--virtual-time-budget=3000", f"--print-to-pdf={pdf}", html_path.as_uri()],
        check=False, capture_output=True, timeout=120,
    )
    if not pdf.exists():
        pytest.skip("Chrome did not produce a PDF here")
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    n = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    assert n == divs, f"{n} physical pages for {divs} .page blocks — something overflowed"
    for i in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(pdf), "-"],
                           capture_output=True, text=True).stdout
        assert t.count("NOT A CERTIFIED UL 508A") == 1, f"physical page {i}: UL x{t.count('NOT A CERTIFIED UL 508A')}"
        assert "NFPA 79" in t, f"physical page {i}: no NFPA"
