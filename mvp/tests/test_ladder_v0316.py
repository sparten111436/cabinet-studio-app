"""v0.3.16: H-DEEP (hint-less import of 3+ OR levels dropped the innermost OR — UNSAFE),
verify-and-refuse guard, stale-hint guard, visible PLCopen import warning.

Every hint-less test exports with Cabinet Studio, STRIPS the ``cabinet-studio-elements``
hint, re-imports, and compares against the native program in the scan simulator (an
independent oracle — not the importer's own truth-table guard). A refused import
(ValueError) is fail-safe and allowed; an accepted import must match exactly.
"""
from __future__ import annotations

import itertools
import random
import re
import traceback

import pytest

from cabinet_studio import __version__
from cabinet_studio.services import plcopen_graph as PG
from cabinet_studio.services import plcopen_xml as PX
from cabinet_studio.services.ladder_ir import program_rung_to_elements, program_to_ladder_ir
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_templates import AOI_TEMPLATES, apply_aoi_template
from cabinet_studio.services.plcopen_xml import (
    PLCOPEN_IMPORT_WARNING,
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
    import_plcopen_xml_to_program_checked,
    plcopen_xml_to_ladder_ir,
)
from cabinet_studio.services.programming import add_rung_from_elements, empty_program, program_from_dict

CYCLE = 100


def C(v, nc=False):
    return {"kind": "contact", "var": v, "form": "NC" if nc else "NO"}


def O(v, form="normal"):
    return {"kind": "coil", "var": v, "form": form}


def OR(*branches):
    return {"kind": "or", "branches": [list(b) for b in branches]}


def _strip_hint(xml: str) -> str:
    xml = re.sub(r"<documentation>\s*cabinet-studio-elements:.*?</documentation>", "", xml, flags=re.S)
    xml = re.sub(
        r"<documentation>\s*<(?:xhtml:)?p[^>]*>cabinet-studio-elements:.*?</(?:xhtml:)?p>\s*</documentation>",
        "", xml, flags=re.S,
    )
    return re.sub(r"cabinet-studio-elements:[^<]*", "", xml)


def _prog(els):
    return add_rung_from_elements(empty_program(), els)


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


def _out(prog, inputs, coil, scans=2):
    sim = ScanSimulator.from_program(prog, cycle_ms=CYCLE)
    v = {}
    for _ in range(scans):
        v = sim.scan_once(dict(inputs))["vars"]
    return bool(v.get(coil))


def _exhaustive(native, imported, inputs, coil):
    """(differ, unsafe) over every input combination, fresh simulator per vector."""
    differ = unsafe = 0
    for bits in itertools.product([False, True], repeat=len(inputs)):
        f = dict(zip(inputs, bits))
        a, b = _out(native, f, coil), _out(imported, f, coil)
        if a != b:
            differ += 1
            if b and not a:
                unsafe += 1
    return differ, unsafe


# ------------------------------------------------------------------ version


def test_version_is_0316():
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 16)  # strict: parsed, not a prefix match


# ------------------------------------------------------------------ H-DEEP exact repro

HDEEP = [
    OR([OR([C("Start")], [C("Remote"), OR([C("K1")], [C("K2")])]), C("Perm")], [C("M")]),
    C("Stop", True),
    O("M"),
]


def test_hdeep_exact_repro_keeps_innermost_or_structure():
    g = _hintless(_prog(HDEEP))
    els = program_rung_to_elements(g["rungs"][0])
    assert _fmt(els) == "((Start | Remote (K1 | K2)) Perm | M) /Stop (M)", _fmt(els)


def test_hdeep_exact_repro_remote_perm_without_key_does_not_energize():
    g = _hintless(_prog(HDEEP))
    f = {"Start": False, "Remote": True, "Perm": True, "K1": False, "K2": False, "Stop": False}
    assert _out(g, f, "M") is False
    f["K2"] = True
    assert _out(g, f, "M") is True
    f["Stop"] = True
    assert _out(g, f, "M") is False


def test_hdeep_exact_repro_full_truth_table_64_of_64():
    native = _prog(HDEEP)
    g = _hintless(native)
    inputs = ["Start", "Remote", "K1", "K2", "Perm", "Stop"]
    assert _exhaustive(native, g, inputs, "M") == (0, 0)


def test_hdeep_minimal_shape_truth_table():
    els = [OR([OR([C("A")], [C("B"), OR([C("C")], [C("D")])]), C("S")], [C("E")]), O("Y")]
    native = _prog(els)
    g = _hintless(native)
    assert _fmt(program_rung_to_elements(g["rungs"][0])) == "((A | B (C | D)) S | E) (Y)"
    assert _exhaustive(native, g, ["A", "B", "C", "D", "S", "E"], "Y") == (0, 0)


FOUR_LEVEL = [
    OR(
        [OR([C("A"), OR([C("B")], [C("C"), OR([C("D")], [C("E", True)])])], [C("F")]), C("G")],
        [C("H"), OR([C("J")], [C("K"), OR([C("L")], [C("M2")])])],
    ),
    C("Stop", True),
    O("Y"),
]


def test_four_level_nesting_exact():
    native = _prog(FOUR_LEVEL)
    g = _hintless(native)
    assert _fmt(program_rung_to_elements(g["rungs"][0])) == _fmt(FOUR_LEVEL)
    inputs = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M2", "Stop"]
    rnd = random.Random(16)
    for _ in range(600):
        f = {n: rnd.random() < 0.5 for n in inputs}
        assert _out(native, f, "Y") == _out(g, f, "Y"), f


# ------------------------------------------------------------------ verify-and-refuse guard


def _graph_for(prog, rung=0):
    """LDGraph for one exported rung (hint stripped), via the importer's own builder."""
    xml = _strip_hint(export_program_to_plcopen_xml(prog, project_name="QA"))
    captured = {}
    real = PX.reconstruct_elements

    def spy(g):
        captured.setdefault("g", g)
        return real(g)

    PX.reconstruct_elements = spy
    try:
        PX.plcopen_xml_to_ladder_ir(xml)
    finally:
        PX.reconstruct_elements = real
    return captured.get("g")


def test_guard_flags_v0315_wrong_rebuild_as_unsafe():
    g = _graph_for(_prog(HDEEP))
    assert g is not None
    rebuilt = PG.reconstruct_elements(g)
    assert PG.verify_elements(g, rebuilt) == (True, "exact")

    # The v0.3.15 output: innermost (K1|K2) silently dropped.
    def drop_inner(els):
        out = []
        for e in els:
            if e.get("kind") == "or":
                bs = []
                for b in e["branches"]:
                    vars_ = [x.get("var") for x in b if x.get("kind") == "contact"]
                    if vars_ == ["Remote"] and any(x.get("kind") == "or" for x in b):
                        b = [x for x in b if x.get("kind") != "or"]
                    bs.append(drop_inner(b))
                e = {**e, "branches": bs}
            out.append(e)
        return out

    wrong = drop_inner(rebuilt)
    assert _fmt(wrong) != _fmt(rebuilt)
    ok, why = PG.verify_elements(g, wrong)
    assert not ok
    assert "ENERGIZE" in why and "Remote" in why


def test_guard_refuses_and_imports_nothing_when_rebuild_is_wrong(monkeypatch):
    """Mutation proof: break the rebuilder; the guard must refuse, never import wrong logic."""
    real = PX.reconstruct_elements

    def broken(g):
        els = real(g)
        # drop every nested OR inside OR branches (the H-DEEP failure class)
        def flat(es, depth=0):
            res = []
            for e in es:
                if e.get("kind") == "or":
                    if depth >= 1:
                        continue
                    e = {**e, "branches": [flat(b, depth + 1) for b in e["branches"]]}
                res.append(e)
            return res
        return flat(els)

    monkeypatch.setattr(PX, "reconstruct_elements", broken)
    xml = _strip_hint(export_program_to_plcopen_xml(_prog(HDEEP), project_name="QA"))
    with pytest.raises(ValueError) as ei:
        import_plcopen_xml_to_program(xml)
    msg = str(ei.value)
    assert "refused" in msg.lower() and "Nothing was imported" in msg


def test_guard_refuses_when_bfs_wrong_and_rebuild_wrong(monkeypatch):
    """Even a classic BFS-path rung is refused if neither result matches the wiring."""
    monkeypatch.setattr(PX, "verify_elements", lambda g, els: (False, "forced mismatch for test"))
    xml = _strip_hint(export_program_to_plcopen_xml(_prog([C("A"), C("B", True), O("Y")]), project_name="QA"))
    with pytest.raises(ValueError, match="forced mismatch for test"):
        import_plcopen_xml_to_program(xml)


def _single_rung_xml(els):
    return _strip_hint(export_program_to_plcopen_xml(_prog(els), project_name="QA"))


def test_refuse_shorting_wire():
    xml = _single_rung_xml([C("A"), O("Y")])
    # wire the coil straight from the left rail as well (empty OR branch = short)
    left_id = re.search(r'<leftPowerRail localId="(\d+)"', xml).group(1)
    xml = re.sub(r'(<coil localId="\d+">.*?<connectionPointIn>)', r'\1<connection refLocalId="%s"/>' % left_id, xml, count=1, flags=re.S)
    with pytest.raises(ValueError, match="(?i)refused"):
        import_plcopen_xml_to_program(xml)


def test_refuse_wire_on_timer_pt_pin():
    xml = _single_rung_xml([C("A"), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 500}, O("Y")])
    cid = re.search(r'<contact localId="(\d+)"', xml).group(1)
    xml = re.sub(
        r'(<variable formalParameter="PT">\s*<connectionPointIn>)',
        r'\1<connection refLocalId="%s"/>' % cid, xml, count=1,
    )
    with pytest.raises(ValueError, match="PT pin"):
        import_plcopen_xml_to_program(xml)


def test_refuse_feedback_cycle():
    xml = _single_rung_xml([C("A"), C("B"), O("Y")])
    ids = re.findall(r'<contact localId="(\d+)"', xml)
    # B -> A feedback wire
    xml = re.sub(
        r'(<contact localId="%s"[^>]*>.*?<connectionPointIn>)' % ids[0],
        r'\1<connection refLocalId="%s"/>' % ids[1], xml, count=1, flags=re.S,
    )
    with pytest.raises(ValueError, match="(?i)refused"):
        import_plcopen_xml_to_program(xml)


def test_bridge_network_rebuilt_exactly_or_refused():
    """Non series-parallel 'bridge' wiring (third-party style) — exact or refused, never wrong."""
    xml = _single_rung_xml([OR([C("A"), C("Cc")], [C("B"), C("D")]), O("Y")])
    ids = dict(re.findall(r'<contact localId="(\d+)"[^>]*>.*?<variable>(\w+)</variable>', xml, flags=re.S)[::1])
    by_var = {v: k for k, v in ids.items()}
    # add bridge contact E from A's output into D's input
    new_id = "900"
    bridge = (
        f'<contact localId="{new_id}" negated="false"><position x="0" y="0"/><connectionPointIn>'
        f'<connection refLocalId="{by_var["A"]}"/></connectionPointIn><connectionPointOut/>'
        f"<variable>E</variable></contact>"
    )
    xml = xml.replace("<rightPowerRail", bridge + "<rightPowerRail", 1)
    xml = re.sub(
        r'(<contact localId="%s"[^>]*>.*?<connectionPointIn>)' % by_var["D"],
        r'\1<connection refLocalId="%s"/>' % new_id, xml, count=1, flags=re.S,
    )
    try:
        g = program_from_dict(import_plcopen_xml_to_program(xml))
    except ValueError:
        return  # fail-safe is acceptable
    for bits in itertools.product([False, True], repeat=5):
        f = dict(zip(["A", "B", "Cc", "D", "E"], bits))
        want = (f["A"] and f["Cc"]) or (f["B"] and f["D"]) or (f["A"] and f["E"] and f["D"])
        assert _out(g, f, "Y") == want, f


# ------------------------------------------------------------------ stale hint guard


def test_stale_hint_is_ignored_and_wiring_wins():
    els = [OR([C("Start")], [C("M"), OR([C("Auto")], [C("Manual")])]), C("Stop", True), O("M")]
    xml = export_program_to_plcopen_xml(_prog(els), project_name="QA")
    assert "cabinet-studio-elements" in xml
    # a third-party tool rewires Stop to a different tag but leaves our hint behind
    xml2 = xml.replace("<variable>Stop</variable>", "<variable>EStop</variable>", 1)
    assert xml2 != xml
    prog, warnings = import_plcopen_xml_to_program_checked(xml2)
    g = program_from_dict(prog)
    got = _fmt(program_rung_to_elements(g["rungs"][0]))
    assert "/EStop" in got and "/Stop" not in got, got
    assert warnings[0] == PLCOPEN_IMPORT_WARNING
    assert any("hint did not match" in w for w in warnings[1:])


def test_fresh_hint_is_trusted_with_only_the_standard_warning():
    prog, warnings = import_plcopen_xml_to_program_checked(
        export_program_to_plcopen_xml(_prog(HDEEP), project_name="QA")
    )
    assert warnings == [PLCOPEN_IMPORT_WARNING]


@pytest.mark.parametrize("name", sorted(AOI_TEMPLATES))
def test_templates_hinted_roundtrip_exact_and_hint_trusted(name):
    native = program_from_dict(apply_aoi_template(empty_program(), name))
    ir = plcopen_xml_to_ladder_ir(export_program_to_plcopen_xml(native, project_name="QA"))
    assert not (ir.get("meta") or {}).get("import_warnings"), ir["meta"].get("import_warnings")
    back = program_from_dict(import_plcopen_xml_to_program(export_program_to_plcopen_xml(native, project_name="QA")))
    a = [_fmt(program_rung_to_elements(r)) for r in native["rungs"]]
    b = [_fmt(program_rung_to_elements(r)) for r in back["rungs"]]
    assert a == b


@pytest.mark.parametrize("name", sorted(AOI_TEMPLATES))
def test_templates_hintless_exact_or_refused(name):
    native = program_from_dict(apply_aoi_template(empty_program(), name))
    try:
        g = _hintless(native)
    except ValueError:
        return
    assert len(g["rungs"]) == len(native["rungs"])
    nat_ir = program_to_ladder_ir(native)
    inputs = sorted({
        e["var"] for r in nat_ir["rungs"] for e in _walk(r["elements"])
        if e.get("kind") == "contact" and "." not in e["var"]
    })
    rnd = random.Random(len(name))
    sa = ScanSimulator.from_program(native, cycle_ms=CYCLE)
    sb = ScanSimulator.from_program(g, cycle_ms=CYCLE)
    for _ in range(200):
        f = {n: rnd.random() < 0.45 for n in inputs}
        a, b = sa.scan_once(dict(f))["vars"], sb.scan_once(dict(f))["vars"]
        for k in a:
            assert bool(a.get(k)) == bool(b.get(k)), (name, k, f)


def _walk(els):
    for e in els or []:
        yield e
        if e.get("kind") == "or":
            for b in e.get("branches") or []:
                yield from _walk(b)


# ------------------------------------------------------------------ fresh-seed fuzz (Audit generator)

TAGS = ["X0", "X1", "X2", "X3", "X4", "X5", "X6"]


def _audit_cases(seed, n, depth):
    """Audit Droid's probe_nohint_fuzz_fresh generator (same RNG consumption order)."""
    rnd = random.Random(seed)

    def gen(cat):
        def contact():
            return C(rnd.choice(TAGS + ["Y"]), rnd.random() < 0.3)

        def branch(d):
            b = [contact() for _ in range(rnd.randint(1, 3))]
            if d < depth and rnd.random() < 0.45:
                b.insert(rnd.randint(0, len(b)), orel(d + 1))
            return b

        def orel(d):
            return {"kind": "or", "branches": [branch(d) for _ in range(rnd.randint(2, 4))]}

        els = []
        for _ in range(rnd.randint(1, 4)):
            els.append(orel(0) if rnd.random() < 0.55 else contact())
        if rnd.random() < 0.5:
            els += [contact() for _ in range(rnd.randint(1, 3))]
        if cat == "midcoil":
            els.append(O("YM"))
            els.append(contact())
        if cat == "timer":
            els.append({"kind": "timer", "var": "T1", "block": rnd.choice(["TON", "TOF"]), "pt_ms": 300})
            return els
        if cat == "compare":
            els.insert(rnd.randint(0, len(els)), {"kind": "compare", "op": rnd.choice(["GRT", "LES", "EQU"]), "source_a": "N", "source_b": "5"})
        if cat == "otl":
            els.append(O("Y", rnd.choice(["set", "reset"])))
            return els
        els.append(O("Y"))
        return els

    out = []
    for cat in ("plain", "midcoil", "timer", "compare", "otl"):
        for i in range(n):
            out.append((cat, i, gen(cat)))
    return out


def _fuzz_one(els, seed, i, scans=200):
    prog = _prog(els)
    try:
        back = _hintless(prog)
    except ValueError:
        return "refused"
    ins = sorted({e["var"] for r in program_to_ladder_ir(prog)["rungs"] for e in _walk(r["elements"])
                  if e.get("kind") == "contact"} - {"Y", "YM"})
    sa = ScanSimulator(program_to_ladder_ir(prog), cycle_ms=CYCLE)
    sb = ScanSimulator(program_to_ladder_ir(back), cycle_ms=CYCLE)
    r2 = random.Random(seed * 1000 + i)
    for _ in range(scans):
        f = {t: r2.random() < 0.45 for t in ins}
        nums = {"N": float(r2.randint(0, 10))}
        sa.numbers.update(nums)
        sb.numbers.update(nums)
        a, b = sa.scan_once(f)["vars"], sb.scan_once(f)["vars"]
        d = [k for k in ("Y", "YM", "T1") if bool(a.get(k)) != bool(b.get(k))]
        if d:
            return "UNSAFE" if any(b.get(k) and not a.get(k) for k in d) else "MISMATCH"
    return "ok"


# Audit v0.3.15 per-case regressions (seed 77001, depth 2): exact in 0.3.13, UNSAFE in 0.3.15.
AUDIT_REGRESSIONS = [
    ("compare", 79), ("midcoil", 190), ("midcoil", 280), ("midcoil", 303), ("midcoil", 344),
    ("midcoil", 352), ("midcoil", 385), ("otl", 111), ("otl", 291), ("plain", 212), ("timer", 136),
    # the other ok->bad ids from Audit's diff vs 0.3.13 / 0.3.14
    ("compare", 170), ("otl", 234), ("otl", 398), ("timer", 209), ("compare", 57), ("compare", 267),
    ("compare", 318), ("midcoil", 242), ("midcoil", 372), ("otl", 310), ("otl", 334), ("otl", 364),
    ("plain", 121), ("plain", 265), ("timer", 69), ("timer", 87), ("timer", 199), ("timer", 250),
    ("timer", 295), ("timer", 335), ("timer", 347), ("timer", 375),
]


def test_audit_fresh_seed_77001_depth2_regression_cases_exact():
    cases = {(c, i): e for c, i, e in _audit_cases(77001, 400, 2)}
    bad = []
    for key in AUDIT_REGRESSIONS:
        res = _fuzz_one(cases[key], 77001, key[1], scans=300)
        if res != "ok":
            bad.append((key, res))
    assert not bad, bad


@pytest.mark.parametrize(
    "seed,depth,per_cat",
    [(77001, 2, 50), (58013, 2, 40), (77001, 3, 40), (31337, 3, 40), (20261005, 4, 20)],
)
def test_fresh_seed_hintless_fuzz_zero_unsafe_or_mismatch_accepted(seed, depth, per_cat):
    tally = {"ok": 0, "refused": 0, "UNSAFE": 0, "MISMATCH": 0}
    bad = []
    for cat, i, els in _audit_cases(seed, per_cat, depth):
        res = _fuzz_one(els, seed, i)
        tally[res] += 1
        if res in {"UNSAFE", "MISMATCH"}:
            bad.append((cat, i, res, _fmt(els)))
    assert not bad, (tally, bad[:5])
    # fail-safe refusals are allowed but must stay rare for Cabinet Studio's own exports
    assert tally["refused"] <= max(1, (5 * per_cat) // 50), tally


def test_randomized_stop_placement_depth3_seal_in_stop_held_never_energizes():
    """Raddus REG-5 generator raised to 3 OR levels: Stop held => seal coil never energizes."""
    rnd = random.Random(3160)
    tags = ["A", "B", "Cc", "D", "E", "F"]

    def branch(d):
        b = [C(rnd.choice(tags + ["M"]), rnd.random() < 0.25) for _ in range(rnd.randint(1, 2))]
        if d < 3 and rnd.random() < 0.6:
            b.insert(rnd.randint(0, len(b)), orel(d + 1))
        return b

    def orel(d):
        return {"kind": "or", "branches": [branch(d) for _ in range(rnd.randint(2, 3))]}

    checked = 0
    for _ in range(60):
        body = [orel(0)]
        if rnd.random() < 0.5:
            body.append(C(rnd.choice(tags)))
        pos = rnd.randint(0, len(body))
        body.insert(pos, C("Stop", True))
        if rnd.random() < 0.5:
            body.insert(0, OR([C("Start")], [C("M")]))
        native = _prog(body + [O("M")])
        try:
            g = _hintless(native)
        except ValueError:
            continue
        checked += 1
        sim = ScanSimulator.from_program(g, cycle_ms=CYCLE)
        for _s in range(40):
            f = {t: rnd.random() < 0.5 for t in tags + ["Start"]}
            f["Stop"] = True
            assert not sim.scan_once(f)["vars"].get("M"), _fmt(body)
    assert checked >= 50


# ------------------------------------------------------------------ real UI: warning + refusal


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    ctk = pytest.importorskip("customtkinter")
    import tkinter.filedialog as fd

    from cabinet_studio.models.project import PlacedItem, Project
    from cabinet_studio.services.programming import add_rung, program_to_dict
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    prog = add_rung(empty_program(), contact_tag="PB_Start", coil_tag="M1", comment="Start motor")
    xml_path = tmp_path / "import.xml"
    monkeypatch.setattr(pv, "ask_choice", lambda *a, **k: "yes")
    monkeypatch.setattr(fd, "askopenfilename", lambda **k: str(xml_path))
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - no display
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    errors: list[str] = []
    root.report_callback_exception = lambda e, v, tb: errors.append("".join(traceback.format_exception(e, v, tb)))
    items = [PlacedItem(id="i1", library_id=None, type_id="pushbutton", x=10, y=10, fields={"tag": "PB_Start"})]
    project = Project(name="UI16", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                      program=program_to_dict(prog), items=items)
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *_: None)
    v.update()
    v._xml_path = xml_path
    v._errors = errors
    try:
        yield v
    finally:
        try:
            if v.winfo_exists():
                v.close()
        except Exception:
            pass
        root.destroy()


def test_ui_import_shows_check_by_hand_warning(ui):
    ui._xml_path.write_text(_strip_hint(export_program_to_plcopen_xml(_prog(HDEEP))), encoding="utf-8")
    ui.import_plcopen_xml()
    ui.update()
    assert "CHECK BY HAND" in ui.status.cget("text")
    assert "CHECK BY HAND" in ui._import_banner.cget("text")
    assert ui._import_banner.winfo_manager() == "pack"
    els = program_rung_to_elements(ui.program["rungs"][0])
    assert _fmt(els) == "((Start | Remote (K1 | K2)) Perm | M) /Stop (M)"
    assert not ui._errors


def test_ui_refused_import_keeps_existing_program_and_says_so(ui, monkeypatch):
    before = [dict(r) for r in ui.program["rungs"]]
    monkeypatch.setattr(PX, "verify_elements", lambda g, els: (False, "forced mismatch"))
    ui._xml_path.write_text(_strip_hint(export_program_to_plcopen_xml(_prog(HDEEP))), encoding="utf-8")
    ui.import_plcopen_xml()
    ui.update()
    assert "REFUSED" in ui.status.cget("text") and "nothing was imported" in ui.status.cget("text")
    assert "refused" in ui._import_banner.cget("text")
    assert [r.get("id") for r in ui.program["rungs"]] == [r.get("id") for r in before]
    assert program_rung_to_elements(ui.program["rungs"][0]) == program_rung_to_elements(before[0])
    assert not ui._errors


# ------------------------------------------------------------------ P3 print polish


def test_p3_wrap_print_line_never_splits_a_tag_mid_word():
    from cabinet_studio.services.ladder_print import PRINT_PLC_CONT_INDENT, wrap_print_line

    tags = [f"Very_Long_Tag_Name_{i:02d}_For_Wrapping" for i in range(12)]
    line = " ".join(f"XIC {t}" for t in tags)
    rows = wrap_print_line(line, 60)
    assert all(len(r) <= 60 for r in rows)
    joined = rows[0] + "".join(r[len(PRINT_PLC_CONT_INDENT):] for r in rows[1:])
    assert joined == line  # nothing lost or added
    for t in tags:
        assert any(t in r for r in rows), f"{t} split across rows: {rows}"
    # a single token longer than a row still hard-breaks (never loops / drops text)
    giant = "X" * 150
    rows = wrap_print_line(giant, 60)
    assert rows[0] + "".join(r[len(PRINT_PLC_CONT_INDENT):] for r in rows[1:]) == giant


def test_p3_plc_text_body_drops_nfpa_line_footer_keeps_it():
    from cabinet_studio.services.ladder_print import paginate_plain_text
    from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE
    from cabinet_studio.services.drawings import DISCLAIMER
    from cabinet_studio.services.programming import format_plc_text

    prog = _prog(HDEEP)
    text = format_plc_text(prog["rungs"])
    assert SAFETY_DESIGN_AID_NOTE in text
    pages = paginate_plain_text(text, drop_lines=(DISCLAIMER, SAFETY_DESIGN_AID_NOTE))
    body = "\n".join("\n".join(p) for p in pages)
    assert SAFETY_DESIGN_AID_NOTE not in body and DISCLAIMER not in body


@pytest.mark.parametrize("which", ["MotorStarter", "TwoHandStart"])
def test_p3_printed_plc_text_pages_carry_nfpa_exactly_once(which, tmp_path, monkeypatch):
    """Real print_ladder HTML: every page has UL once and the NFPA note once (footer only)."""
    from test_ladder_v0315 import _print_html, _split_pages

    prog = program_from_dict(apply_aoi_template(empty_program(), which))
    body = _print_html(prog, which, tmp_path, monkeypatch).read_text(encoding="utf-8")
    pages = _split_pages(body)
    plc_pages = [p for p in pages if "<h2>PLC text" in p]
    assert plc_pages
    for i, pg in enumerate(pages, 1):
        assert pg.count("NOT A CERTIFIED UL 508A DRAWING. Design aid only.") == 1, i
        assert "NFPA 79" in pg, i
    from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE
    import html as _h

    for pg in plc_pages:
        pre = _h.unescape(re.search(r"<pre>(.*?)</pre>", pg, flags=re.S).group(1))
        # the standalone header copy is gone (footer carries it); rung comments keep G-AID
        assert SAFETY_DESIGN_AID_NOTE not in [ln.strip() for ln in pre.splitlines()]
        assert pg.count(SAFETY_DESIGN_AID_NOTE) == pre.count(SAFETY_DESIGN_AID_NOTE) + 1


def test_p3_plain_program_plc_text_page_has_nfpa_once(tmp_path, monkeypatch):
    from test_ladder_v0315 import _print_html, _split_pages

    body = _print_html(_prog(HDEEP), "HDEEP", tmp_path, monkeypatch).read_text(encoding="utf-8")
    plc_pages = [p for p in _split_pages(body) if "<h2>PLC text" in p]
    assert plc_pages and all(p.count("NFPA 79") == 1 for p in plc_pages)
