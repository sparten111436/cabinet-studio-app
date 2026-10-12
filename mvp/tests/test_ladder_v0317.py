"""v0.3.17: Audit v0.3.16 FAIL fixes (guard model + hint tamper) and the P2 batch.

NEW-1  guard falsely refused a compare inside an OR branch after a series element
       (own hinted exports!) — block outputs are now gated by their input power on BOTH
       sides of the guard (LD graph and Cabinet Studio elements).
NEW-3  stale / tampered hint overrode coil form and block settings — the hint carries a
       wiring hash ("wh"); settings are compared node-to-node; wiring wins + warning.
NEW-2  >20 inputs were randomly sampled and silently accepted — exact BDD now, refuse
       beyond the BDD limits.
NEW-4  no-left-rail "flat dump" skipped the guard — verified rebuild or refuse.
NEW-5  empty / malformed CPT crashed the hinted import — imports verbatim; Verify error,
       simulator refuses to run (Raddus: no rung skipping, no partial import).
NEW-6  cross-rung wires — refuse.
NEW-7  RecursionError at 1,000+ series contacts — iterative rebuild / clear refusal.
Non-PLCopen XML / no LD / no rungs / empty file — refused BEFORE the Replace confirm.

Oracles are independent of the guard: the scan simulator and direct element comparison.
"""
from __future__ import annotations

import html
import itertools
import json
import random
import re
import traceback

import pytest

from cabinet_studio import __version__
from cabinet_studio.services import plcopen_graph as PG
from cabinet_studio.services import plcopen_xml as PX
from cabinet_studio.services.ladder_ir import program_rung_to_elements, program_to_ladder_ir
from cabinet_studio.services.ladder_sim import ScanSimulator, sim_blockers
from cabinet_studio.services.ladder_tools import verify_program
from cabinet_studio.services.plcopen_xml import (
    PLCOPEN_IMPORT_WARNING,
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
    import_plcopen_xml_to_program_checked,
    validate_plcopen_document,
)
from cabinet_studio.services.programming import add_rung_from_elements, empty_program, program_from_dict

CYCLE = 100


def C(v, nc=False):
    return {"kind": "contact", "var": v, "form": "NC" if nc else "NO"}


def O(v, form="normal"):
    return {"kind": "coil", "var": v, "form": form}


def OR(*branches):
    return {"kind": "or", "branches": [list(b) for b in branches]}


def CMP(op, a, b):
    return {"kind": "compare", "op": op, "source_a": a, "source_b": str(b)}


def _strip_hint(xml: str) -> str:
    xml = re.sub(r"<documentation>\s*cabinet-studio-elements:.*?</documentation>", "", xml, flags=re.S)
    xml = re.sub(
        r"<documentation>\s*<(?:xhtml:)?p[^>]*>cabinet-studio-elements:.*?</(?:xhtml:)?p>\s*</documentation>",
        "", xml, flags=re.S,
    )
    return re.sub(r"cabinet-studio-elements:[^<]*", "", xml)


def _edit_hint(xml: str, fn) -> str:
    def rep(m):
        d = json.loads(html.unescape(m.group(1)))
        fn(d)
        return "cabinet-studio-elements:" + html.escape(json.dumps(d), quote=False)

    out, n = re.subn(r"cabinet-studio-elements:(\{.*?\})(?=</)", rep, xml, count=1, flags=re.S)
    assert n == 1
    return out


def _prog(*rungs):
    p = empty_program()
    for els in rungs:
        p = add_rung_from_elements(p, els)
    return p


def _xml(*rungs) -> str:
    return export_program_to_plcopen_xml(_prog(*rungs), project_name="QA")


def _ir_rungs(prog) -> list[list[dict]]:
    return [r["elements"] for r in program_to_ladder_ir(program_from_dict(prog))["rungs"]]


def _imp(xml):
    prog, warns = import_plcopen_xml_to_program_checked(xml)
    return program_from_dict(prog), warns[1:]


def _sim_equal(native, imported, inputs, outs, scans=3, numbers=None):
    """Exhaustive over boolean inputs (fresh sims per vector); returns (differ, unsafe)."""
    differ = unsafe = 0
    for bits in itertools.product([False, True], repeat=len(inputs)):
        f = dict(zip(inputs, bits))
        sa = ScanSimulator.from_program(native, cycle_ms=CYCLE)
        sb = ScanSimulator.from_program(imported, cycle_ms=CYCLE)
        for k, v in (numbers or {}).items():
            sa.set_number(k, v)
            sb.set_number(k, v)
        for _ in range(scans):
            a = sa.scan_once(dict(f))["vars"]
            b = sb.scan_once(dict(f))["vars"]
        for o in outs:
            if bool(a.get(o)) != bool(b.get(o)):
                differ += 1
                if b.get(o) and not a.get(o):
                    unsafe += 1
    return differ, unsafe


# ------------------------------------------------------------------ version


def test_version_is_0317():
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 17)  # v0.3.18 moved on (strict parse)


# ------------------------------------------------------------------ NEW-1


NEW1_REPRO = [C("Start"), OR([CMP("GEQ", "Speed", 10)], [C("Jog")]), O("Run")]
NEW1_SHAPES = [
    NEW1_REPRO,
    [C("X6"), OR([CMP("GEQ", "N", 5)], [C("X0")]), {"kind": "timer", "var": "T1", "block": "TOF", "pt_ms": 300}],
    [C("X4"), OR([CMP("LEQ", "N", 3)], [C("X6")]), O("L1", "set")],
    [C("C1"), OR([C("X6"), CMP("EQU", "D", 4)], [C("X3")]), O("L1", "reset")],
    [C("A"), OR([C("B"), OR([CMP("GRT", "N", 2)], [C("E")])], [C("F")]), O("Y")],
    [C("A"), OR([{"kind": "math", "op": "ADD", "dest": "D", "source_a": "D", "source_b": "1"}], [C("B")]), O("Y")],
]


@pytest.mark.parametrize("i", range(len(NEW1_SHAPES)))
def test_new1_hinted_roundtrip_exact_no_refusal_no_hint_warning(i):
    els = NEW1_SHAPES[i]
    native = _prog(els)
    back, warns = _imp(_xml(els))
    assert _ir_rungs(back) == _ir_rungs(native)
    assert warns == []


@pytest.mark.parametrize("i", range(len(NEW1_SHAPES)))
def test_new1_hintless_compare_in_branch_imports_and_matches_sim(i):
    els = NEW1_SHAPES[i]
    native = _prog(els)
    back, _ = _imp(_strip_hint(_xml(els)))
    ins = sorted({e["var"] for e in _walk(els) if e.get("kind") == "contact"})
    for n in (0.0, 3.0, 4.0, 5.0, 11.0):
        d, u = _sim_equal(native, back, ins, ["Run", "Y", "L1", "T1"], numbers={"Speed": n, "N": n, "D": n})
        assert (d, u) == (0, 0)


def _walk(els):
    for e in els:
        if e.get("kind") == "or":
            for b in e["branches"]:
                yield from _walk(b)
        else:
            yield e


def test_new1_unit_guard_model_compare_in_branch_both_sides_agree():
    xml = _strip_hint(_xml(NEW1_REPRO))
    ir = PX.plcopen_xml_to_ladder_ir(xml)
    assert len(ir["rungs"]) == 1
    # and a wrong placement (compare moved before Start) is still refused by the model
    assert "cabinet-studio-elements" not in xml  # really the hint-less path
    assert [e["kind"] for e in ir["rungs"][0]["elements"]] == ["contact", "or", "coil"]
    g = PG.LDGraph("L")
    g.add_node("1", "contact", C("Start"))
    g.add_node("2", "fb", CMP("GEQ", "Speed", 10))
    g.add_node("3", "contact", C("Jog"))
    g.add_node("4", "coil", O("Run"))
    for a, b in (("L", "1"), ("1", "2"), ("1", "3"), ("2", "4"), ("3", "4")):
        g.add_edge(a, b)
    good = [dict(C("Start")), OR([{**CMP("GEQ", "Speed", 10), "_nid": "2"}], [C("Jog")]), {**O("Run"), "_nid": "4"}]
    assert PG.verify_elements(g, good) == (True, "exact")
    bad = [OR([{**CMP("GEQ", "Speed", 10), "_nid": "2"}], [C("Start"), C("Jog")]), {**O("Run"), "_nid": "4"}]
    ok, why = PG.verify_elements(g, bad)
    assert not ok and "ENERGIZE" in why


def _gen_mixed(rnd):
    tags = ["X0", "X1", "X2", "X3", "X4"]

    def item():
        r = rnd.random()
        if r < 0.25:
            return CMP(rnd.choice(["GRT", "LES", "EQU", "GEQ", "LEQ", "NEQ"]), rnd.choice(["N", "D"]), rnd.randint(2, 8))
        return C(rnd.choice(tags + ["Y", "T1", "C1"]), rnd.random() < 0.3)

    def branch(d):
        b = [item() for _ in range(rnd.randint(1, 3))]
        if d < 2 and rnd.random() < 0.4:
            b.insert(rnd.randint(0, len(b)), OR(*[branch(d + 1) for _ in range(rnd.randint(2, 3))]))
        return b

    els = [item()]
    for _ in range(rnd.randint(1, 3)):
        els.append(OR(*[branch(1) for _ in range(rnd.randint(2, 3))]) if rnd.random() < 0.6 else item())
    if rnd.random() < 0.3:
        els.append({"kind": "oneshot", "block": "ONS", "var": "OS1"})
    if rnd.random() < 0.3:
        els += [O("YM"), item()]
    els.append(rnd.choice([
        O("Y"), O("L1", "set"), O("L1", "reset"),
        {"kind": "timer", "var": "T1", "block": rnd.choice(["TON", "TOF", "RTO"]), "pt_ms": 300},
        {"kind": "counter", "var": "C1", "block": rnd.choice(["CTU", "CTD"]), "pv": 3},
        {"kind": "math", "op": rnd.choice(["ADD", "SUB", "MUL"]), "dest": "D", "source_a": "D", "source_b": "1"},
        {"kind": "oneshot", "block": "OSR", "var": "OS2", "output": "RISE"},
    ]))
    return els


@pytest.mark.parametrize("seed", [17017, 2026105])
def test_new1_hinted_mixed_fuzz_zero_refused_all_exact(seed):
    rnd = random.Random(seed)
    refused, inexact, warned = [], [], []
    for i in range(120):
        els = _gen_mixed(rnd)
        native = _prog(els)
        try:
            back, warns = _imp(export_program_to_plcopen_xml(native))
        except ValueError as exc:
            refused.append((i, str(exc)[:120]))
            continue
        if _ir_rungs(back) != _ir_rungs(native):
            inexact.append(i)
        if warns:
            warned.append((i, warns[0][:120]))
    assert refused == [] and inexact == [] and warned == []


# ------------------------------------------------------------------ NEW-3


SEAL = [OR([C("Start")], [C("Motor")]), C("Stop", True), O("Motor")]
BASE = [C("Start"), OR([C("Stop", True)], [C("Estop", True)]), O("Motor")]
CMP_R = [OR([C("Auto")], [C("Man")]), CMP("LES", "Level", 80), O("Pump")]
TIM = [OR([C("Run")], [C("Jog")]), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 5000}]
MTH = [OR([C("A")], [C("B")]), {"kind": "math", "op": "ADD", "dest": "Total", "source_a": "Total", "source_b": "1"}]
CNT = [OR([C("PE1")], [C("PE2")]), {"kind": "counter", "var": "C1", "block": "CTU", "pv": 10}, O("Batch")]


def _coil_xml(xml, attr):
    return re.sub(r'<coil localId="(\d+)"', r'<coil localId="\1" %s' % attr, xml, count=1)


def _drop_wh(xml):
    return _edit_hint(xml, lambda d: d.pop("wh", None))


TAMPER = {
    "T1_hint_set_xml_normal": (lambda: _edit_hint(_xml(SEAL), lambda d: d["elements"][-1].update(form="set")),
                               lambda els: els[-1]["form"] == "normal"),
    "T2_xml_reset_stale_hint": (lambda: _coil_xml(_xml(BASE), 'storage="reset"'),
                                lambda els: els[-1]["form"] == "reset"),
    "T3_xml_negated_stale_hint": (lambda: _coil_xml(_xml(BASE), 'negated="true"'),
                                  lambda els: els[-1]["form"] == "negated"),
    "T4_xml_cmp_op": (lambda: _xml(CMP_R).replace('typeName="LES"', 'typeName="GRT"'),
                      lambda els: els[1]["op"] == "GRT"),
    "T5_hint_cmp_op": (lambda: _edit_hint(_xml(CMP_R), lambda d: d["elements"][1].update(op="GRT")),
                       lambda els: els[1]["op"] == "LES"),
    "T5b_xml_cmp_operand": (lambda: _xml(CMP_R).replace("<expression>80</expression>", "<expression>20</expression>"),
                            lambda els: str(els[1]["source_b"]) == "20"),
    "T6_xml_timer_pt": (lambda: _xml(TIM).replace("<expression>T#5s</expression>", "<expression>T#500ms</expression>"),
                        lambda els: els[-1]["pt_ms"] == 500),
    "T6b_xml_timer_type": (lambda: _xml(TIM).replace('typeName="TON"', 'typeName="TOF"'),
                           lambda els: els[-1]["block"] == "TOF"),
    "T6c_hint_timer_pt": (lambda: _edit_hint(_xml(TIM), lambda d: d["elements"][-1].update(pt_ms=50)),
                          lambda els: els[-1]["pt_ms"] == 5000),
    "T10_xml_math_op": (lambda: _xml(MTH).replace('typeName="ADD"', 'typeName="SUB"'),
                        lambda els: els[-1]["op"] == "SUB"),
    "T10b_hint_math_op": (lambda: _edit_hint(_xml(MTH), lambda d: d["elements"][-1].update(op="MUL")),
                          lambda els: els[-1]["op"] == "ADD"),
    "T11_xml_counter_pv": (lambda: re.sub(r"<expression>10</expression>", "<expression>3</expression>", _xml(CNT), count=1),
                           lambda els: els[1]["pv"] == 3),
    "T11b_hint_counter_pv": (lambda: _edit_hint(_xml(CNT), lambda d: d["elements"][1].update(pv=99)),
                             lambda els: els[1]["pv"] == 10),
}


@pytest.mark.parametrize("name", sorted(TAMPER))
@pytest.mark.parametrize("hashed", [True, False], ids=["with_wh", "old_file_no_wh"])
def test_new3_tampered_hint_imports_the_wiring_and_warns_naming_the_rung(name, hashed):
    make, check = TAMPER[name]
    xml = make()
    if not hashed:
        xml = _drop_wh(xml)
        assert '"wh"' not in xml
    back, warns = _imp(xml)
    els = _ir_rungs(back)[0]
    assert check(els), (name, els)
    assert any(w.startswith("WARNING rung 1 (") and "IGNORED" in w for w in warns), warns


def test_new3_t1_set_latch_never_survives_stop():
    xml = _edit_hint(_xml(SEAL), lambda d: d["elements"][-1].update(form="set"))
    back, _ = _imp(xml)
    sim = ScanSimulator.from_program(back, cycle_ms=CYCLE)
    sim.scan_once({"Start": True, "Stop": False})
    v = sim.scan_once({"Start": False, "Stop": True})["vars"]
    assert not v.get("Motor")


def test_new3_own_export_carries_wiring_hash_and_is_trusted():
    xml = _xml(SEAL)
    m = re.search(r'cabinet-studio-elements:(\{.*?\})(?=</)', xml, flags=re.S)
    payload = json.loads(html.unescape(m.group(1)))
    assert re.fullmatch(r"[0-9a-f]{24}", payload["wh"])
    back, warns = _imp(xml)
    assert warns == [] and _ir_rungs(back) == _ir_rungs(_prog(SEAL))


def test_new3_hash_is_layout_and_localid_independent():
    xml = _xml(SEAL)
    shifted = re.sub(r'(localId|refLocalId)="(\d+)"', lambda m: f'{m.group(1)}="{int(m.group(2)) + 100}"', xml)
    shifted = re.sub(r'<position x="\d+" y="\d+"', '<position x="7" y="9"', shifted)
    back, warns = _imp(shifted)
    assert warns == [] and _ir_rungs(back) == _ir_rungs(_prog(SEAL))


def test_new3_logic_neutral_body_edit_still_ignores_hint_and_warns():
    # a doc note added on a contact changes the rung body hash -> hint ignored, wiring rebuilt (still exact)
    xml = _xml(SEAL)
    xml = re.sub(r"(<variable>Stop</variable>)", r"\1<documentation><xhtml:p>note: edited in CCW</xhtml:p></documentation>", xml, count=1)
    back, warns = _imp(xml)
    assert any("wiring hash mismatch" in w for w in warns)
    d, u = _sim_equal(_prog(SEAL), back, ["Start", "Stop"], ["Motor"])
    assert (d, u) == (0, 0)


def test_new3_tag_effects_in_order_rejects_coil_name_mismatch_unit():
    """Removing the hint coil-name check in tag_effects_in_order must be caught (Audit V10)."""
    g = PG.LDGraph("L")
    g.add_node("1", "contact", C("A"))
    g.add_node("2", "coil", O("Y"))
    g.add_edge("L", "1")
    g.add_edge("1", "2")
    assert PG.tag_effects_in_order(g, [C("A"), O("Y")]) is not None
    assert PG.tag_effects_in_order(g, [C("A"), O("Z")]) is None


def test_new3_hint_coil_renamed_imports_wiring_name_and_warns():
    xml = _edit_hint(_xml(SEAL), lambda d: d["elements"][-1].update(var="Pump"))
    back, warns = _imp(xml)
    assert _ir_rungs(back)[0][-1]["var"] == "Motor"
    assert any("IGNORED" in w for w in warns)


def test_new3_damaged_hint_json_warns_and_uses_wiring():
    xml = re.sub(r"cabinet-studio-elements:\{", "cabinet-studio-elements:{BROKEN", _xml(BASE), count=1)
    back, warns = _imp(xml)
    assert any("could not be read" in w for w in warns)
    assert _ir_rungs(back) == _ir_rungs(_prog(BASE))


def test_new3_effect_descriptor_covers_every_setting():
    D = PG.effect_descriptor
    assert D(O("Y")) != D(O("Y", "set")) != D(O("Y", "reset")) != D(O("Y", "negated"))
    assert D(CMP("LES", "L", 80)) != D(CMP("GRT", "L", 80)) != D(CMP("LES", "L", 20))
    t = {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 5000}
    assert D(t) != D({**t, "pt_ms": 500}) and D(t) != D({**t, "block": "TOF"})
    c = {"kind": "counter", "var": "C1", "block": "CTU", "pv": 10}
    assert D(c) != D({**c, "pv": 3}) and D(c) != D({**c, "block": "CTD"})
    m = {"kind": "math", "op": "ADD", "dest": "D", "source_a": "D", "source_b": "1"}
    assert D(m) != D({**m, "op": "SUB"}) and D(m) != D({**m, "source_b": "2"}) and D(m) != D({**m, "dest": "E"})
    cpt = {"kind": "math", "op": "CPT", "dest": "D", "expression": "A+1"}
    assert D(cpt) != D({**cpt, "expression": "A+2"})
    o = {"kind": "oneshot", "block": "OSR", "var": "S", "output": "Q"}
    assert D(o) != D({**o, "block": "OSF"}) and D(o) != D({**o, "output": "Q2"})


# ------------------------------------------------------------------ NEW-2


def _series_graph(n):
    g = PG.LDGraph("L")
    prev = "L"
    for i in range(n):
        g.add_node(str(i + 1), "contact", C(f"X{i}"))
        g.add_edge(prev, str(i + 1))
        prev = str(i + 1)
    g.add_node(str(n + 1), "coil", O("Y"))
    g.add_edge(prev, str(n + 1))
    return g


@pytest.mark.parametrize("n", [21, 24, 30, 64])
def test_new2_above_20_inputs_exact_bdd_catches_a_dropped_last_contact(n):
    g = _series_graph(n)
    good = [C(f"X{i}") for i in range(n)] + [{**O("Y"), "_nid": str(n + 1)}]
    assert PG.verify_elements(g, good) == (True, "exact-bdd")
    bad = [C(f"X{i}") for i in range(n - 1)] + [{**O("Y"), "_nid": str(n + 1)}]
    ok, why = PG.verify_elements(g, bad)
    assert not ok and "ENERGIZE" in why


def test_new2_30_contact_rung_hintless_imports_exactly():
    els = [C(f"I{i}", i % 3 == 0) for i in range(30)] + [O("Y")]
    back, _ = _imp(_strip_hint(_xml(els)))
    assert _ir_rungs(back) == _ir_rungs(_prog(els))


def test_new2_beyond_bdd_limit_refuses_clearly(monkeypatch):
    monkeypatch.setattr(PG, "BDD_MAX_INPUTS", 25)
    els = [C(f"I{i}") for i in range(30)] + [O("Y")]
    with pytest.raises(ValueError, match="verifies at most 25"):
        import_plcopen_xml_to_program(_strip_hint(_xml(els)))


def test_new2_bdd_and_truth_table_agree_on_random_mutants(monkeypatch):
    """Soundness: forcing the BDD path gives the same result as the exhaustive table.

    v0.3.18 (Audit P3): no tolerated refusals, a forced BDD path, and the algebra
    cross-check is against an independent brute-force evaluator with ops2 always
    different from ops1 (both equivalent rewrites and genuinely different formulas).
    """
    rnd = random.Random(31337)
    for _ in range(60):
        els = _gen_mixed(rnd)
        xml = _strip_hint(export_program_to_plcopen_xml(_prog(els)))
        assert "cabinet-studio-elements" not in xml
        table_ir = PX.plcopen_xml_to_ladder_ir(xml)  # must import: no refusal tolerated
        with monkeypatch.context() as m:
            m.setattr(PG, "EXHAUSTIVE_MAX_INPUTS", 0)  # every rung goes through the BDD
            bdd_ir = PX.plcopen_xml_to_ladder_ir(xml)
        assert table_ir["rungs"] and bdd_ir["rungs"] == table_ir["rungs"]

    names = [f"v:X{i}" for i in range(8)]

    def build(alg, ops):
        stack = []
        for op, arg in ops:
            if op == "v":
                stack.append(alg.var(arg))
            elif op == "n" and stack:
                stack.append(alg.not_(stack.pop()))
            elif op in "ao" and len(stack) >= 2:
                b, a = stack.pop(), stack.pop()
                stack.append(alg.and_(a, b) if op == "a" else alg.or_(a, b))
        return stack[-1] if stack else alg.false

    class _Brute:  # independent oracle: plain Python booleans over all 256 vectors
        false = tuple([False] * 256)

        def var(self, n):
            k = names.index(n)
            return tuple(bool((row >> k) & 1) for row in range(256))

        def not_(self, a):
            return tuple(not x for x in a)

        def and_(self, a, b):
            return tuple(x and y for x, y in zip(a, b))

        def or_(self, a, b):
            return tuple(x or y for x, y in zip(a, b))

    brute = _Brute()
    seen = {True: 0, False: 0}
    for i in range(300):
        ops1 = [(rnd.choice("vvvnao"), rnd.choice(names)) for _ in range(14)]
        if i % 2:
            # equivalent rewrite: double negation of the whole result
            ops2 = ops1 + [("n", ""), ("n", "")]
        else:
            ops2 = ops1[:]
            while ops2 == ops1:
                ops2 = [(rnd.choice("vvvnao"), rnd.choice(names)) for _ in range(14)]
        assert ops2 != ops1
        want = build(brute, ops1) == build(brute, ops2)
        tab, bdd = PG._Table(sorted(names)), PG._BDD(list(names))
        assert (build(tab, ops1) == build(tab, ops2)) == want
        f1, f2 = build(bdd, ops1), build(bdd, ops2)
        assert (f1 == f2) == want
        if not want:  # the BDD witness must be a real differing vector
            w = bdd.witness(bdd.or_(bdd.and_(f1, bdd.not_(f2)), bdd.and_(f2, bdd.not_(f1))))
            row = sum(1 << k for k, n in enumerate(names) if w[n])
            assert build(brute, ops1)[row] != build(brute, ops2)[row]
        seen[want] += 1
    assert seen[True] >= 100 and seen[False] >= 50


# ------------------------------------------------------------------ NEW-4


def _no_left(xml):
    return re.sub(r"<leftPowerRail .*?</leftPowerRail>", "", xml, flags=re.S)


# v0.3.19 (Deflector P1-A, Raddus policy "never guess the left rail"): the 0.3.17 NEW-4
# recovery (treat the single missing id as the rail) is gone — a deleted first Stop/E-stop
# contact looks exactly the same. Every no-rail body now refuses, naming its objects.
NO_RAIL = "no left power rail"


@pytest.mark.parametrize("hinted", [True, False])
def test_new4_no_left_rail_or_into_reset_coil_refuses(hinted):
    els = [OR([C("Stop")], [C("Estop")]), O("Motor", "reset")]
    xml = _xml(els) if hinted else _strip_hint(_xml(els))
    with pytest.raises(ValueError, match=NO_RAIL) as ei:
        import_plcopen_xml_to_program(_no_left(xml))
    assert "Stop" in str(ei.value) and "Estop" in str(ei.value) and "Motor" in str(ei.value)
    assert "will not guess" in str(ei.value)


def test_new4_no_left_rail_two_rungs_refuse():
    a = [C("A"), C("B", True), O("Y")]
    b = [OR([C("C")], [C("D")]), O("Z")]
    xml = _strip_hint(_xml(a, b))
    rails = re.findall(r'<leftPowerRail localId="(\d+)"', xml)
    assert len(rails) == 2
    xml = _no_left(xml).replace(f'refLocalId="{rails[1]}"', f'refLocalId="{rails[0]}"')
    with pytest.raises(ValueError, match=NO_RAIL):
        import_plcopen_xml_to_program(xml)


def test_new4_no_left_rail_per_rung_missing_rails_refuse_rather_than_guess():
    xml = _no_left(_strip_hint(_xml([C("A"), O("Y")], [C("B"), O("Z")])))
    with pytest.raises(ValueError, match=NO_RAIL):
        import_plcopen_xml_to_program(xml)


def test_new4_no_left_rail_unwired_object_refuses():
    xml = _no_left(_xml([C("A"), O("Y")]))
    xml = re.sub(r"(<contact [^>]*>\s*<position[^>]*/>\s*<connectionPointIn>)\s*<connection [^>]*/>", r"\1", xml, count=1)
    with pytest.raises(ValueError, match=NO_RAIL):
        import_plcopen_xml_to_program(xml)


def test_new4_no_left_rail_two_missing_sources_refuses():
    xml = _no_left(_xml([OR([C("A")], [C("B")]), O("Y")]))
    ids = re.findall(r'<contact localId="\d+"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>\s*<connection refLocalId="(\d+)"', xml)
    assert ids
    xml = xml.replace(f'<connection refLocalId="{ids[0]}"/>', '<connection refLocalId="999"/>', 1)
    with pytest.raises(ValueError, match=NO_RAIL):
        import_plcopen_xml_to_program(xml)


# ------------------------------------------------------------------ NEW-5 (CPT policy)


def _cpt(expr):
    return [C("EN"), {"kind": "math", "op": "CPT", "dest": "D", "source_a": "", "expression": expr}]


@pytest.mark.parametrize("expr", ["", "(2+3", "A + * 2"])
@pytest.mark.parametrize("hinted", [True, False])
def test_new5_bad_cpt_imports_verbatim_verify_errors_sim_blocked_others_intact(expr, hinted):
    a = [C("A"), O("Y")]
    b = _cpt(expr)
    c = [OR([C("B")], [C("Z")]), C("S", True), O("Z")]
    xml = _xml(a, b, c)
    if not hinted:
        xml = _strip_hint(xml)
    back, _ = _imp(xml)
    rungs = _ir_rungs(back)
    assert len(rungs) == 3
    assert rungs[0] == _ir_rungs(_prog(a))[0] and rungs[2] == _ir_rungs(_prog(c))[0]
    math = [e for e in rungs[1] if e.get("kind") == "math"][0]
    assert math["op"] == "CPT" and (math.get("expression") or "") == expr
    codes = {i["code"] for i in verify_program(back) if i["severity"] == "error"}
    assert codes & ({"MISSING_OPERAND"} if not expr else {"CPT_INVALID"})
    bl = sim_blockers(back)
    assert len(bl) == 1 and bl[0].startswith("Rung 2 (CPT → D)")
    # export round-trips the expression verbatim
    back2, _ = _imp(export_program_to_plcopen_xml(back))
    assert _ir_rungs(back2) == rungs


def test_new5_good_cpt_is_not_blocked():
    assert sim_blockers(_prog(_cpt("(A + 2) * 3"))) == []


# ------------------------------------------------------------------ NEW-6


def test_new6_cross_rung_wire_refuses_whole_file():
    xml = _strip_hint(_xml([C("A"), O("Y")], [C("B"), O("Y2")]))
    bid = re.search(r'<contact localId="(\d+)"[^>]*>(?:(?!</contact>).)*<variable>B</variable>', xml, flags=re.S).group(1)
    xml2 = re.sub(
        r'(<coil localId="\d+"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>)((?:(?!</coil>).)*<variable>Y</variable>)',
        r'\1<connection refLocalId="%s"/>\2' % bid, xml, count=1, flags=re.S,
    )
    assert xml2 != xml
    with pytest.raises(ValueError, match="wired together"):
        import_plcopen_xml_to_program(xml2)


# ------------------------------------------------------------------ NEW-7


def test_new7_1200_series_contacts_no_recursion_error_exact_or_clear_refusal():
    els = [C(f"X{i % 10}") for i in range(1200)] + [O("Y")]
    back, _ = _imp(_strip_hint(_xml(els)))
    assert _ir_rungs(back) == _ir_rungs(_prog(els))
    els2 = [C(f"Q{i}") for i in range(1200)] + [O("Y")]
    with pytest.raises(ValueError, match="verifies at most"):
        import_plcopen_xml_to_program(_strip_hint(_xml(els2)))


def test_new7_reconstruct_is_iterative_on_long_chain():
    g = _series_graph(3000)
    els = PG.reconstruct_elements(g)
    assert len(els) == 3001


# ------------------------------------------------------------------ wording


def test_hinted_refusal_message_does_not_say_hint_less():
    xml = _xml([C("A"), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 500}, O("Y")])
    cid = re.search(r'<contact localId="(\d+)"', xml).group(1)
    xml = re.sub(r'(<variable formalParameter="PT">\s*<connectionPointIn>)', r'\1<connection refLocalId="%s"/>' % cid, xml, count=1)
    with pytest.raises(ValueError) as ei:
        import_plcopen_xml_to_program(xml)
    assert "Hint-less" not in str(ei.value) and "refused" in str(ei.value)


# ------------------------------------------------------------------ non-PLCopen


ST_ONLY = (
    '<project xmlns="http://www.plcopen.org/xml/tc6_0201"><types><pous><pou name="Main" pouType="program">'
    "<body><ST><xhtml:p xmlns:xhtml=\"http://www.w3.org/1999/xhtml\">x := 1;</xhtml:p></ST></body></pou></pous></types></project>"
)
EMPTY_LD = (
    '<project xmlns="http://www.plcopen.org/xml/tc6_0201"><types><pous><pou name="Main" pouType="program">'
    "<body><LD></LD></body></pou></pous></types></project>"
)


@pytest.mark.parametrize(
    "xml,needle",
    [
        ("<notplcopen/>", "not a PLCopen"),
        ('<project xmlns="urn:other"><types/></project>', "not a PLCopen"),
        ("", "empty"),
        ("   \n", "empty"),
        ("<project", "not well-formed"),
        ('<project xmlns="http://www.plcopen.org/xml/tc6_0201"><types><pous/></types></project>', "no POU"),
        (ST_ONLY, "no Ladder Diagram"),
        (EMPTY_LD, "no rungs"),
    ],
)
def test_non_plcopen_or_empty_documents_are_refused(xml, needle):
    with pytest.raises(ValueError, match=needle):
        import_plcopen_xml_to_program(xml)
    with pytest.raises(ValueError, match=needle):
        import_plcopen_xml_to_program_checked(xml)


def test_validate_accepts_own_export():
    validate_plcopen_document(_xml(SEAL))


# ------------------------------------------------------------------ real UI


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
    asked: list = []

    def _ask(*a, **k):
        asked.append((a, k))
        return "yes"

    monkeypatch.setattr(pv, "ask_choice", _ask)
    monkeypatch.setattr(fd, "askopenfilename", lambda **k: str(xml_path))
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - no display
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    errors: list[str] = []
    root.report_callback_exception = lambda e, v, tb: errors.append("".join(traceback.format_exception(e, v, tb)))
    items = [PlacedItem(id="i1", library_id=None, type_id="pushbutton", x=10, y=10, fields={"tag": "PB_Start"})]
    project = Project(name="UI17", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                      program=program_to_dict(prog), items=items)
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *_: None)
    v.update()
    v._xml_path = xml_path
    v._errors = errors
    v._asked = asked
    try:
        yield v
    finally:
        try:
            if v.winfo_exists():
                v.close()
        except Exception:
            pass
        root.destroy()


@pytest.mark.parametrize("content", ["<notplcopen/>", "", ST_ONLY, EMPTY_LD])
def test_ui_non_plcopen_refused_before_confirm_and_rungs_survive(ui, content):
    before = [program_rung_to_elements(r) for r in ui.program["rungs"]]
    ui._xml_path.write_text(content, encoding="utf-8")
    ui.import_plcopen_xml()
    ui.update()
    assert ui._asked == []  # no Replace confirm was shown
    assert "REFUSED" in ui.status.cget("text") and "nothing was imported" in ui.status.cget("text")
    assert [program_rung_to_elements(r) for r in ui.program["rungs"]] == before
    assert not ui._errors


def test_ui_tampered_hint_warning_is_loud_on_status_line(ui):
    ui._xml_path.write_text(_coil_xml(_xml(BASE), 'storage="reset"'), encoding="utf-8")
    ui.import_plcopen_xml()
    ui.update()
    assert len(ui._asked) == 1  # valid file: confirm shown once
    st = ui.status.cget("text")
    assert "WARNING" in st and "rung 1 (Motor)" in st
    assert "IGNORED" in ui._import_banner.cget("text")
    assert program_rung_to_elements(ui.program["rungs"][0])[-1]["form"] == "reset"
    assert not ui._errors


def test_ui_simulation_refuses_to_run_with_empty_cpt(ui):
    ui._xml_path.write_text(_xml([C("A"), O("Y")], _cpt("")), encoding="utf-8")
    ui.import_plcopen_xml()
    ui.update()
    assert len(ui.program["rungs"]) == 2
    ui._sim_toggle_run()
    ui.update()
    assert not ui._sim_running
    assert "Sim BLOCKED" in ui._sim_status.cget("text") and "Rung 2" in ui._sim_status.cget("text")
    ui._sim_step()
    assert "Sim BLOCKED" in ui._sim_status.cget("text")
    assert not ui._errors
