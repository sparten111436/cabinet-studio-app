"""v0.3.8: watch/trend, JSR/SBR/RET, aliases, verify fixes, print packing."""

from __future__ import annotations

from cabinet_studio import __version__
from cabinet_studio.services.ladder_ir import (
    clean_elements,
    normalize_ladder_ir,
    program_to_ladder_ir,
    ladder_ir_to_program,
    resolve_alias,
)
from cabinet_studio.services.ladder_print import (
    INTER_RUNG_GAP,
    TITLE_BAND,
    packing_metrics,
    ladder_program_to_svg,
)
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.ladder_tools import (
    WatchTrendBuffer,
    apply_verify_fix,
    ensure_routine,
    add_rung_to_routine,
    set_tag_alias,
    tag_table,
    verify_program,
)
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import empty_program, add_rung_from_elements


def test_version_is_038():
    assert __version__.startswith("0.3.")


def test_alias_resolve_and_sim():
    assert resolve_alias("Start", {"Start": "PB_Start"}) == "PB_Start"
    assert resolve_alias("Start.DN", {"Start": "C1"}) == "C1.DN"
    p = empty_program()
    p = set_tag_alias(p, "Start", "PB_Start")
    p = add_rung_from_elements(
        p,
        [{"kind": "contact", "var": "Start", "form": "NO"}, {"kind": "coil", "var": "M1", "form": "normal"}],
    )
    ir = program_to_ladder_ir(p)
    sim = ScanSimulator(ir)
    r = sim.scan_once({"Start": True})  # force via alias
    assert r["vars"].get("M1") is True
    assert r["aliases"]["Start"] == "PB_Start"
    rows = tag_table(p)
    assert any(r["name"] == "Start" and r["alias_of"] == "PB_Start" for r in rows)


def test_jsr_sbr_ret_scan_and_roundtrip():
    p = empty_program()
    p = add_rung_from_elements(
        p,
        [{"kind": "contact", "var": "PB_Start", "form": "NO"}, {"kind": "jsr", "target": "Motor"}],
        comment="call",
    )
    p = ensure_routine(p, "Motor")
    p = add_rung_to_routine(
        p,
        "Motor",
        [{"kind": "sbr", "name": "Motor"}, {"kind": "coil", "var": "M1", "form": "normal"}, {"kind": "ret"}],
        comment="sbr",
    )
    ir = program_to_ladder_ir(p)
    assert "Motor" in (ir.get("routines") or {})
    sim = ScanSimulator(ir)
    r = sim.scan_once({"PB_Start": True})
    assert r["vars"].get("M1") is True
    # PLCopen round-trip
    xml = export_program_to_plcopen_xml(p, project_name="Cell")
    assert "JSR" in xml and "cabinet-studio-meta:" in xml
    back = import_plcopen_xml_to_program(xml)
    assert "Motor" in (back.get("routines") or {})
    assert back["rungs"][0]["elements"][1]["kind"] == "jsr"
    # IR normalize
    norm = normalize_ladder_ir(ir)
    assert norm["routines"]["Motor"][0]["elements"][0]["kind"] == "sbr"


def test_verify_fix_add_otu_and_rename_storage():
    p = empty_program()
    p = add_rung_from_elements(p, [{"kind": "coil", "var": "L1", "form": "set"}])
    issues = verify_program(p)
    latch = next(i for i in issues if i["code"] == "LATCH_NO_UNLATCH")
    assert latch.get("fix", {}).get("action") == "add_otu"
    p2 = apply_verify_fix(p, latch)
    assert len(p2["rungs"]) == 2
    assert any(
        e.get("form") in {"reset", "r"}
        for r in p2["rungs"]
        for e in (r.get("elements") or [])
    )

    p3 = empty_program()
    p3 = add_rung_from_elements(
        p3, [{"kind": "oneshot", "block": "ONS", "var": "OS1"}, {"kind": "coil", "var": "M1", "form": "normal"}]
    )
    p3 = add_rung_from_elements(
        p3, [{"kind": "oneshot", "block": "ONS", "var": "OS1"}, {"kind": "coil", "var": "M2", "form": "normal"}]
    )
    issues = verify_program(p3)
    dup = next(i for i in issues if i["code"] == "DUP_STORAGE" and i.get("fix"))
    p4 = apply_verify_fix(p3, dup)
    storages = [
        e.get("var")
        for r in p4["rungs"]
        for e in (r.get("elements") or [])
        if e.get("kind") == "oneshot"
    ]
    assert len(set(storages)) == 2


def test_watch_trend_buffer():
    w = WatchTrendBuffer(capacity=5)
    w.set_tags(["PB_Start", "C1.ACC"])
    for i in range(7):
        w.record(
            {
                "vars": {"PB_Start": bool(i % 2)},
                "numbers": {},
                "timers": {},
                "counters": {"C1": {"acc": i, "pre": 5, "dn": False}},
                "scan_count": i + 1,
            }
        )
    assert len(w.samples) == 5  # capacity
    assert w.series("C1.ACC")[-1] == 6.0  # last of trimmed window
    assert w.latest()["PB_Start"] in {0.0, 1.0}


def test_print_packing_tighter_and_jsr_symbol():
    assert INTER_RUNG_GAP <= 28
    assert TITLE_BAND <= 32  # v0.3.11 raised band so OR forks clear titles
    rungs = []
    for i in range(12):
        rungs.append(
            {
                "id": f"r{i}",
                "comment": f"R{i}",
                "elements": clean_elements(
                    [{"kind": "contact", "var": "PB", "form": "NO"}, {"kind": "coil", "var": f"M{i}", "form": "normal"}]
                ),
            }
        )
    metrics = packing_metrics(rungs)
    assert metrics["pages"] >= 1
    assert sum(metrics["rungs_per_page"]) == 12
    # JSR printable
    svg, _w, _h = ladder_program_to_svg(
        [
            {
                "id": "j1",
                "comment": "",
                "elements": clean_elements(
                    [{"kind": "contact", "var": "A", "form": "NO"}, {"kind": "jsr", "target": "Motor"}]
                ),
            }
        ]
    )
    assert "JSR" in svg and "Motor" in svg


def test_unknown_jsr_gets_create_routine_fix():
    p = empty_program()
    p = add_rung_from_elements(
        p, [{"kind": "contact", "var": "A", "form": "NO"}, {"kind": "jsr", "target": "Missing"}]
    )
    issues = verify_program(p)
    unk = next(i for i in issues if i["code"] == "UNKNOWN_ROUTINE")
    assert unk["fix"]["action"] == "create_routine"
    p2 = apply_verify_fix(p, unk)
    assert "Missing" in (p2.get("routines") or {})
