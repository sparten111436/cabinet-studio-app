"""v0.3.18: Audit v0.3.17 FAIL fixes + Deflector P3s.

NEW-8   a rung whose left rail was deleted (orphaned LD objects) was silently dropped —
        unreachable LD objects now refuse the whole file; every rail must yield a rung.
NEW-9   IEC PT/PV literals (T#1m30s, TIME#5s, 16#0A, 1_000 ...) and tag presets imported as
        0 / doc value — full IEC grammar; a tag preset stays a tag (pt_tag / pv_tag) and is
        read from the tag at run time; anything else refuses (never 0, never the doc note).
ROUTINE routine bodies travelled only in metadata — exported as real LD networks, verified
        against the wiring like main rungs; on mismatch the WIRING wins with a warning naming
        routine + rung; metadata-only routines in old files import with a loud warning; a
        metadata-only routine in a file that carries routine wiring refuses.
NEW-10  force / clear-forces / scan tick bypassed sim_blockers, and the core sim wrote 0 for
        a bad CPT — all entry points blocked; the core never writes a bad CPT destination.
PCOIL   add series contact on a parallel-coil rung gated only the first coil.
P3      Deflector P3-1/P3-2, Audit P3-A..E, strict version test.
"""
from __future__ import annotations

import html
import json
import re
import traceback

import pytest

from cabinet_studio import __version__
from cabinet_studio.services import ladder_sim as LS
from cabinet_studio.services import plcopen_graph as PG
from cabinet_studio.services import plcopen_xml as PX
from cabinet_studio.services.ladder_ir import (
    cpt_expression_error,
    eval_cpt_expression,
    parse_iec_duration_ms,
    parse_iec_int,
    program_rung_to_elements,
    program_to_ladder_ir,
)
from cabinet_studio.services.ladder_sim import ScanSimulator, sim_blockers
from cabinet_studio.services.ladder_tools import verify_program
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
    import_plcopen_xml_to_program_checked,
)
from cabinet_studio.services.programming import (
    add_rung_from_elements,
    append_series_contact,
    empty_program,
    program_from_dict,
)

CYCLE = 100


def C(v, nc=False):
    return {"kind": "contact", "var": v, "form": "NC" if nc else "NO"}


def O(v, form="normal"):
    return {"kind": "coil", "var": v, "form": form}


def OR(*branches):
    return {"kind": "or", "branches": [list(b) for b in branches]}


def TON(var, pt_ms=1000, pt_tag=None):
    d = {"kind": "timer", "var": var, "block": "TON", "pt_ms": pt_ms}
    if pt_tag:
        d["pt_tag"] = pt_tag
    return d


def CTU(var, pv=5, pv_tag=None):
    d = {"kind": "counter", "var": var, "block": "CTU", "pv": pv}
    if pv_tag:
        d["pv_tag"] = pv_tag
    return d


def MOV(dest, src):
    return {"kind": "math", "op": "MOV", "dest": dest, "source_a": str(src)}


def _strip_hint(xml: str) -> str:
    return re.sub(r"cabinet-studio-elements:[^<]*", "", xml)


def _prog(*rungs):
    p = empty_program()
    for els in rungs:
        p = add_rung_from_elements(p, els)
    return p


def _xml(*rungs) -> str:
    return export_program_to_plcopen_xml(_prog(*rungs), project_name="QA")


def _imp(xml):
    prog, warns = import_plcopen_xml_to_program_checked(xml)
    return program_from_dict(prog), warns[1:]


def _rungs(prog):
    return [r["elements"] for r in program_to_ladder_ir(program_from_dict(prog))["rungs"]]


def _routines(prog):
    return {k: [r["elements"] for r in v] for k, v in (program_to_ladder_ir(program_from_dict(prog)).get("routines") or {}).items()}


# ------------------------------------------------------------------ version


def test_version_is_at_least_0318():
    # v0.3.19: the strict equality lives in the newest version's test file only.
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 18)


# ------------------------------------------------------------------ NEW-8


ORPHAN_RUNGS = ([C("A"), C("B", True), O("Y")], [C("Estop"), O("Motor", "reset")], [OR([C("C")], [C("D")]), C("S", True), O("Z")])


def _drop_rail(xml, index, refs=False):
    rid = re.findall(r'<leftPowerRail localId="(\d+)"', xml)[index]
    x = re.sub(r'<leftPowerRail localId="%s".*?</leftPowerRail>' % rid, "", xml, flags=re.S)
    if refs:  # also delete the wires that pointed at the rail (an orphaned, not a dangling, rung)
        x = re.sub(r'<connection refLocalId="%s"[^>]*?(?:/>|>.*?</connection>)' % rid, "", x, flags=re.S)
    return x


@pytest.mark.parametrize("hinted", [True, False])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_new8_rung_with_deleted_left_rail_refuses_whole_file(hinted, index):
    # v0.3.19: deleting only the rail leaves wires to a missing localId → P1-B refusal;
    # deleting the rail AND its wires leaves an orphaned rung → NEW-8 refusal. Both refuse.
    xml = _xml(*ORPHAN_RUNGS)
    if not hinted:
        xml = _strip_hint(xml)
    with pytest.raises(ValueError, match="do not exist"):
        import_plcopen_xml_to_program(_drop_rail(xml, index))
    with pytest.raises(ValueError, match="not connected"):
        import_plcopen_xml_to_program(_drop_rail(xml, index, refs=True))


def test_new8_reset_rung_is_never_silently_lost():
    # the Audit repro: deleting rung 2's rail used to import rungs 1 and 3 only (Estop reset lost)
    xml = _drop_rail(_xml(*ORPHAN_RUNGS), 1)
    with pytest.raises(ValueError) as ei:
        import_plcopen_xml_to_program_checked(xml)
    assert "after rung 1" in str(ei.value)


def test_new8_accounting_every_rail_yields_one_rung():
    back, warns = _imp(_xml(*ORPHAN_RUNGS))
    assert len(back["rungs"]) == 3 and warns == []
    back, warns = _imp(_strip_hint(_xml(*ORPHAN_RUNGS)))
    assert len(back["rungs"]) == 3


def _forge_absorbed_note(xml, coil_index):
    m = list(re.finditer(r'(<coil localId="\d+"[^>]*>)', xml))[coil_index]
    return xml[: m.end()] + "<documentation><xhtml:p>ONESHOT-OUTPUT of OSR OS1</xhtml:p></documentation>" + xml[m.end():]


@pytest.mark.parametrize("hinted", [True, False])
def test_new8b_forged_oneshot_output_note_never_hides_a_reset_rung(hinted):
    # v0.3.17 silently dropped this whole reset rung (stripped: zero warnings)
    rungs = ([C("A"), O("Y")], [C("Stop"), O("Motor", "reset")])
    xml = _xml(*rungs)
    if not hinted:
        xml = _strip_hint(xml)
    back, _ = _imp(_forge_absorbed_note(xml, 1))
    assert _rungs(back) == _rungs(_prog(*rungs))


@pytest.mark.parametrize("hinted", [True, False])
def test_new8b_rewired_oneshot_output_coil_is_kept(hinted):
    # OSR block deleted and its "absorbed" output coil wired straight to the contact
    xml = _xml([C("A"), O("Y")], [C("PB"), {"kind": "oneshot", "block": "OSR", "var": "OS2", "output": "RISE"}])
    if not hinted:
        xml = _strip_hint(xml)
    blk = re.search(r'<block localId="(\d+)"[^>]*typeName="R_TRIG".*?</block>', xml, re.S)
    cid = re.search(r'<contact localId="(\d+)"[^>]*>(?:(?!</contact>).)*<variable>PB</variable>', xml, re.S).group(1)
    x2 = xml.replace(blk.group(0), "")
    x2, n = re.subn(r'(<coil localId="\d+"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>\s*<connection refLocalId=")%s(")'
                    % blk.group(1), r"\g<1>%s\2" % cid, x2)
    assert n == 1
    back, _ = _imp(x2)
    assert _rungs(back)[1] == [C("PB"), O("RISE")]


def test_new8b_own_osr_osf_exports_still_absorb_their_output_coil():
    for blk in ("OSR", "OSF"):
        rung = [C("PB"), {"kind": "oneshot", "block": blk, "var": "OS2", "output": "EDGE"}]
        for xml in (_xml(rung), _strip_hint(_xml(rung))):
            back, warns = _imp(xml)
            assert _rungs(back) == _rungs(_prog(rung)) and warns == []


@pytest.mark.parametrize("hinted", [True, False])
def test_new8_contact_only_network_refuses(hinted):
    # v0.3.19 (Raddus deleted-object fuzz): 0.3.18 skipped this network with a warning; a
    # network whose coil was deleted looks the same, so a dead-end contact now refuses.
    xml = _xml([C("A"), O("Y")])
    if not hinted:
        xml = _strip_hint(xml)
    extra = ('<leftPowerRail localId="9001"><position x="0" y="900"/><connectionPointOut formalParameter=""/>'
             '</leftPowerRail><contact localId="9002"><position x="0" y="0"/><connectionPointIn>'
             '<connection refLocalId="9001"/></connectionPointIn><connectionPointOut/><variable>Lonely</variable></contact>')
    with pytest.raises(ValueError, match="drive nothing") as ei:
        _imp(xml.replace("</LD>", extra + "</LD>", 1))
    assert "Lonely" in str(ei.value) and "9002" in str(ei.value)


@pytest.mark.parametrize("hinted", [True, False])
@pytest.mark.parametrize("blank", ["", "   "])
def test_contact_with_erased_tag_refuses_instead_of_making_coil_unconditional(hinted, blank):
    # v0.3.17 dropped the contact and imported "Z" as always ON (stripped: zero warnings)
    xml = _xml([C("A"), O("Y")], [C("Guard"), O("Z")])
    if not hinted:
        xml = _strip_hint(xml)
    with pytest.raises(ValueError, match="no variable"):
        import_plcopen_xml_to_program(xml.replace("<variable>Guard</variable>", f"<variable>{blank}</variable>"))
    with pytest.raises(ValueError, match="no variable"):
        import_plcopen_xml_to_program(xml.replace("<variable>Z</variable>", f"<variable>{blank}</variable>"))


def test_new8_empty_rail_is_a_warning_not_a_silent_skip():
    xml = _xml([C("A"), O("Y")])
    extra = '<leftPowerRail localId="9001"><position x="0" y="900"/><connectionPointOut formalParameter=""/></leftPowerRail>'
    xml2 = xml.replace("</LD>", extra + "</LD>", 1)
    back, warns = _imp(xml2)
    assert len(back["rungs"]) == 1
    assert any("empty" in w.lower() and "rail" in w.lower() for w in warns), warns


# ------------------------------------------------------------------ NEW-9


def _pt_xml(expr, hinted=False):
    xml = _xml([C("A"), TON("T1", 1000)], [C("T1"), O("Y")])
    if not hinted:
        xml = _strip_hint(xml)
    xml2, n = re.subn(r'(formalParameter="PT">\s*<connectionPointIn>\s*<expression>)[^<]*(</expression>)',
                      lambda m: m.group(1) + html.escape(expr) + m.group(2), xml)
    assert n == 1
    return xml2


def _pv_xml(expr, hinted=False):
    xml = _xml([C("A"), CTU("C1", 5)], [C("C1.DN"), O("Y")])
    if not hinted:
        xml = _strip_hint(xml)
    xml2, n = re.subn(r'(formalParameter="PV">\s*<connectionPointIn>\s*<expression>)[^<]*(</expression>)',
                      lambda m: m.group(1) + html.escape(expr) + m.group(2), xml)
    assert n == 1
    return xml2


PT_OK = [
    ("T#1m30s", 90000), ("T#1h", 3_600_000), ("TIME#5s", 5000), ("t#5s_500ms", 5500), ("T#1d", 86_400_000),
    ("LTIME#250ms", 250), ("T#1.5s", 1500), ("T#2h_3m", 7_380_000), ("2500", 2500), ("time#0.25s", 250),
    ("T#1000ms", 1000), ("T#5s", 5000), ("LT#1s", 1000),
]


@pytest.mark.parametrize("expr,ms", PT_OK)
@pytest.mark.parametrize("hinted", [False, True])
def test_new9_iec_pt_literals_import_exact_ms(expr, ms, hinted):
    back, _ = _imp(_pt_xml(expr, hinted))
    t = _rungs(back)[0][1]
    assert t["kind"] == "timer" and t["pt_ms"] == ms and not t.get("pt_tag")


@pytest.mark.parametrize("expr", ["T#-5s", "T#1.5ms", "T#5x", "garbage!", "T#", "T#1s1m", "T#1.5s2ms", "REAL#3.0", "3.7"])
def test_new9_bad_pt_literals_refuse_never_zero(expr):
    with pytest.raises(ValueError, match="rung"):
        import_plcopen_xml_to_program(_pt_xml(expr))


PV_OK = [("16#0A", 10), ("1_000", 1000), ("8#17", 15), ("2#101", 5), ("DINT#16#FF", 255), ("INT#7", 7), ("12", 12), ("+3", 3)]


@pytest.mark.parametrize("expr,pv", PV_OK)
def test_new9_iec_pv_literals_import_exact(expr, pv):
    back, _ = _imp(_pv_xml(expr))
    c = _rungs(back)[0][1]
    assert c["kind"] == "counter" and int(c["pv"]) == pv and not c.get("pv_tag")


@pytest.mark.parametrize("expr", ["10.7", "REAL#3.0", "16#", "1__0x", "99999999999999999999", "-"])
def test_new9_bad_pv_literals_refuse(expr):
    with pytest.raises(ValueError):
        import_plcopen_xml_to_program(_pv_xml(expr))


def test_new9_tag_presets_stay_tags_round_trip_hinted_and_stripped():
    rungs = ([MOV("Delay", 300), MOV("Lim", 2)], [C("A"), TON("T1", 0, "Delay")], [C("B"), CTU("C1", 0, "Lim")])
    for xml in (_xml(*rungs), _strip_hint(_xml(*rungs))):
        assert re.search(r'formalParameter="PT">\s*<connectionPointIn>\s*<expression>Delay<', xml)
        assert re.search(r'formalParameter="PV">\s*<connectionPointIn>\s*<expression>Lim<', xml)
        back, warns = _imp(xml)
        rs = _rungs(back)
        assert rs[1][1]["pt_tag"] == "Delay" and rs[2][1]["pv_tag"] == "Lim"
        assert not [w for w in warns if "hint did not match" in w]


def test_new9_foreign_tag_pt_not_doc_value():
    back, _ = _imp(_pt_xml("PresetTime", hinted=True))  # doc note says pt_ms=1000: must not be used
    t = _rungs(back)[0][1]
    assert t.get("pt_tag") == "PresetTime"
    assert t["pt_ms"] != 1000


def test_new9_sim_reads_preset_from_tag():
    p = program_from_dict(_prog([MOV("Delay", 300)], [C("A"), TON("T1", 0, "Delay")], [C("T1"), O("Y")]))
    assert sim_blockers(p) == []
    s = ScanSimulator.from_program(p, cycle_ms=CYCLE)
    ys = [s.scan_once({"A": True})["vars"].get("Y") for _ in range(6)]
    ref = ScanSimulator.from_program(program_from_dict(_prog([C("A"), TON("T1", 300)], [C("T1"), O("Y")])), cycle_ms=CYCLE)
    want = [ref.scan_once({"A": True})["vars"].get("Y") for _ in range(6)]
    assert ys == want and want.index(True) >= 2  # same as a fixed 300 ms preset, not 0 ms
    p2 = program_from_dict(_prog([MOV("Lim", 2)], [C("B"), CTU("C1", 0, "Lim")], [C("C1.DN"), O("Y")]))
    s2 = ScanSimulator.from_program(p2, cycle_ms=CYCLE)
    out = []
    for b in (True, False, True, False):
        out.append(s2.scan_once({"B": b})["vars"].get("Y"))
    assert out == [False, False, True, True]  # done at 2 counts, not at 0


def test_new9_unwritten_preset_tag_blocks_sim_and_verify_error():
    p = program_from_dict(_prog([C("A"), TON("T1", 0, "Delay")], [C("T1"), O("Y")]))
    bl = sim_blockers(p)
    assert bl and "Delay" in bl[0] and "Rung 1" in bl[0]
    codes = {i["code"] for i in verify_program(p)}
    assert "PRESET_TAG_UNSET" in codes
    p2 = program_from_dict(_prog([MOV("Delay", 5)], [C("A"), TON("T1", 0, "Delay")]))
    codes2 = {i["code"]: i["severity"] for i in verify_program(p2)}
    assert codes2.get("PRESET_TAG") == "warning" and "PRESET_TAG_UNSET" not in codes2


def test_new9_unit_parsers():
    assert parse_iec_duration_ms("T#1m30s") == 90000
    assert parse_iec_duration_ms("T#1d2h") == 93_600_000
    for bad in ("T#-1s", "T#0.5ms", "T#1s1h", "nonsense"):
        with pytest.raises(ValueError):
            parse_iec_duration_ms(bad)
    assert parse_iec_int("16#FF") == 255 and parse_iec_int("DINT#-5") == -5
    for bad in ("1.5", "REAL#1", "16#G"):
        with pytest.raises(ValueError):
            parse_iec_int(bad)


# ------------------------------------------------------------------ routines


def _routine_prog(estop_nc=True):
    p = add_rung_from_elements(empty_program(), [C("Auto"), {"kind": "jsr", "target": "Safety"}])
    p.setdefault("routines", {})["Safety"] = [
        {"id": "s1", "elements": [C("Estop", estop_nc), O("Enable")]},
        {"id": "s2", "elements": [C("Enable"), C("Guard"), O("Run")]},
    ]
    return p


# v0.3.19 (Deflector P3-d): edit the metadata / hint JSON through a real XML parse instead of
# matching the escaped text ("&quot;" on Python <= 3.12, a bare '"' on 3.13+).
import xml.etree.ElementTree as _ET


def _edit_texts(xml: str, edit, *, meta_only: bool = False) -> str:
    """Apply ``edit(text) -> text`` to every element text / tail (or only to the
    ``cabinet-studio-meta:`` comment when meta_only) and re-serialise the document."""
    root = _ET.fromstring(xml)
    ns = re.match(r"\{([^}]*)\}", root.tag)
    if ns:
        _ET.register_namespace("", ns.group(1))
    for el in root.iter():
        for attr in ("text", "tail"):
            t = getattr(el, attr)
            if not t or (meta_only and "cabinet-studio-meta:" not in t):
                continue
            setattr(el, attr, edit(t))
    return '<?xml version="1.0" encoding="utf-8"?>\n' + _ET.tostring(root, encoding="unicode")


def _json_texts(edit_obj):
    """Text editor that rewrites every JSON object/array after a ``cabinet-studio-*:`` prefix."""

    def _edit(text: str) -> str:
        out = []
        for ln in text.split("\n"):
            m = re.match(r"^(\s*cabinet-studio-[a-z-]+:)(.*)$", ln)
            if m:
                try:
                    obj = json.loads(m.group(2))
                except ValueError:
                    out.append(ln)
                    continue
                ln = m.group(1) + json.dumps(edit_obj(obj), separators=(",", ":"), ensure_ascii=False)
            out.append(ln)
        return "\n".join(out)

    return _edit


def _estop_nc_to_no(obj):
    if isinstance(obj, dict):
        if obj.get("var") == "Estop" and obj.get("form") == "NC":
            obj = dict(obj, form="NO")
        return {k: _estop_nc_to_no(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_estop_nc_to_no(v) for v in obj]
    return obj


def _drop_routine_wiring(obj):
    if isinstance(obj, dict):
        return {k: _drop_routine_wiring(v) for k, v in obj.items() if k != "routine_wiring"}
    if isinstance(obj, list):
        return [_drop_routine_wiring(v) for v in obj]
    return obj


def _enable(prog, estop):
    s = ScanSimulator.from_program(program_from_dict(prog), cycle_ms=CYCLE)
    return s.scan_once({"Auto": True, "Estop": estop, "Guard": True})["vars"].get("Enable")


def test_routine_export_has_verifiable_routine_networks_and_round_trips():
    xml = export_program_to_plcopen_xml(_routine_prog())
    assert '<routineBody name="Safety">' in xml and "routine_wiring" in xml
    back, warns = _imp(xml)
    assert warns == []
    assert _routines(back) == _routines(_routine_prog())
    assert _enable(back, estop=True) is False or not _enable(back, estop=True)


def test_routine_export_is_xsd_valid():
    lxml = pytest.importorskip("lxml.etree")
    import pathlib

    xsds = list(pathlib.Path(__file__).resolve().parents[1].rglob("tc6_xml_v201.xsd")) + list(
        pathlib.Path("/workspace").glob("**/tc6_xml_v201.xsd")
    )
    if not xsds:
        pytest.skip("PLCopen XSD not available")
    schema = lxml.XMLSchema(lxml.parse(str(xsds[0])))
    doc = lxml.fromstring(export_program_to_plcopen_xml(_routine_prog()).encode("utf-8"))
    assert schema.validate(doc), schema.error_log


def test_routine_metadata_tamper_estop_nc_to_no_wiring_wins_and_warns_routine_and_rung():
    xml = export_program_to_plcopen_xml(_routine_prog())
    x3 = _edit_texts(xml, _json_texts(_estop_nc_to_no), meta_only=True)  # metadata copy only
    assert x3 != xml and _edit_texts(xml, lambda t: t, meta_only=True) != x3
    back, warns = _imp(x3)
    r = _routines(back)["Safety"]
    assert r[0][0]["form"] == "NC"  # from the wiring
    assert [w for w in warns if "routine 'Safety' rung 1" in w and "metadata" in w and "WIRING was used" in w], warns
    assert not [w for w in warns if "hint did not match" in w]  # the wiring + its hint were untouched
    assert not _enable(back, estop=True)  # E-stop pressed → Enable off


def test_routine_audit_repro_metadata_and_hint_tampered_wiring_wins():
    xml = export_program_to_plcopen_xml(_routine_prog())
    x3 = _edit_texts(xml, _json_texts(_estop_nc_to_no))  # Audit's probe: every copy (meta + hints)
    assert x3 != _edit_texts(xml, lambda t: t)
    back, warns = _imp(x3)
    assert _routines(back)["Safety"][0][0]["form"] == "NC"
    assert any("routine 'Safety' rung 1" in w and "hint did not match" in w for w in warns), warns
    assert not _enable(back, estop=True)


def test_routine_wiring_tamper_imports_wiring_and_warns():
    xml = export_program_to_plcopen_xml(_routine_prog())
    body = xml[xml.index("<routineBody"):]
    body2 = body.replace('negated="true"', "", 1)
    x2 = xml[: xml.index("<routineBody")] + body2
    back, warns = _imp(x2)
    assert _routines(back)["Safety"][0][0]["form"] == "NO"
    assert any("routine 'Safety'" in w and "rung 1" in w for w in warns)
    assert any("metadata" in w.lower() and "WIRING" in w for w in warns)


def _old_style(xml):
    x = re.sub(r"<addData>\s*<data name=\"urn:cabinet-studio:routine-networks\".*?</addData>", "", xml, flags=re.S)
    x = _edit_texts(x, _json_texts(_drop_routine_wiring), meta_only=True)
    assert "routineBody" not in x and "routine_wiring" not in x
    return x


def test_routine_metadata_only_old_file_imports_with_loud_per_routine_warning():
    back, warns = _imp(_old_style(export_program_to_plcopen_xml(_routine_prog())))
    assert _routines(back)["Safety"][0][0]["form"] == "NC"
    assert any("Safety" in w and "metadata ONLY" in w and "could NOT be verified" in w for w in warns), warns


def test_routine_metadata_only_routine_in_new_file_refuses():
    xml = export_program_to_plcopen_xml(_routine_prog())
    x = re.sub(r"<addData>\s*<data name=\"urn:cabinet-studio:routine-networks\".*?</addData>", "", xml, flags=re.S)
    with pytest.raises(ValueError, match="Safety"):
        import_plcopen_xml_to_program(x)


def test_routine_duplicate_body_names_refuse():
    xml = export_program_to_plcopen_xml(_routine_prog())
    s = xml.index("<routineBody")
    e = xml.index("</routineBody>") + len("</routineBody>")
    x = xml[:e] + xml[s:e] + xml[e:]
    with pytest.raises(ValueError):
        import_plcopen_xml_to_program(x)


def test_alias_metadata_is_flagged_unverified():
    p = _prog([C("A"), O("Y")])
    p["tag_aliases"] = {"A": "Local:1:I.Data.0"}
    back, warns = _imp(export_program_to_plcopen_xml(p))
    assert any("alias" in w and "could not be verified" in w for w in warns), warns


# ------------------------------------------------------------------ NEW-10 / P3-2 / P3-E


@pytest.mark.parametrize("expr", ["", "A+", "1/0", "A/(2-2)", "(A"])
def test_new10_core_sim_never_writes_a_bad_cpt_destination(expr):
    p = program_from_dict(_prog([MOV("D", 7)], [C("Go"), {"kind": "math", "op": "CPT", "dest": "D", "source_a": expr}]))
    s = ScanSimulator.from_program(p, cycle_ms=CYCLE)
    s.scan_once({"Go": False})
    s.scan_once({"Go": True})
    assert s.read_number("D") == 7  # untouched: never 0
    assert sim_blockers(p)


def test_p3e_cpt_constant_division_flagged_hex_accepted():
    assert cpt_expression_error("1/0") and cpt_expression_error("A/(2-2)")
    for ok in ("A/(B-1)", "16#FF+1", "INT#5*A", "2#1010 + 8#7"):
        assert cpt_expression_error(ok) == "", ok
    assert eval_cpt_expression("16#FF+1", {}) == 256


def test_p3_2_sim_blockers_and_cpt_error_fail_closed(monkeypatch):
    from cabinet_studio.services import ladder_ir as LI

    p = program_from_dict(_prog([C("A"), O("Y")]))
    assert sim_blockers(p) == []
    monkeypatch.setattr(LI, "program_to_ladder_ir", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    bl = sim_blockers(p)
    assert bl and "could not" in bl[0].lower()
    monkeypatch.undo()

    monkeypatch.setattr(LI, "eval_cpt_expression", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert LI.cpt_expression_error("A+1")


# ------------------------------------------------------------------ parallel coils


def test_pcoil_add_series_gates_every_parallel_coil():
    p = _prog([C("Start"), OR([O("Motor")], [O("Lamp")])])
    rid = p["rungs"][0]["id"]
    out = append_series_contact(p, rid, "Guard_Closed")
    els = program_rung_to_elements(out["rungs"][0])
    assert [e["kind"] for e in els] == ["contact", "contact", "or"]
    s = ScanSimulator.from_program(program_from_dict(out), cycle_ms=CYCLE)
    v = s.scan_once({"Start": True, "Guard_Closed": False})["vars"]
    assert not v.get("Motor") and not v.get("Lamp")
    v = s.scan_once({"Start": True, "Guard_Closed": True})["vars"]
    assert v.get("Motor") and v.get("Lamp")
    assert not [i for i in verify_program(program_from_dict(out)) if i["code"] == "NO_OUTPUT"]


# ------------------------------------------------------------------ P3s


def test_p3a_input_limit_message_does_not_blame_the_hint(monkeypatch):
    monkeypatch.setattr(PG, "BDD_MAX_INPUTS", 25)
    with pytest.raises(ValueError) as ei:
        import_plcopen_xml_to_program(_xml([C(f"I{i}") for i in range(30)] + [O("Y")]))
    msg = str(ei.value)
    assert "independent inputs" in msg and "verifies at most 25" in msg
    assert "did not match" not in msg and "hint-less" not in msg


@pytest.mark.parametrize("k", [20, 26])
def test_p3b_bdd_order_independent_of_localids(k):
    """k parallel 2-contact branches; ids numbered column-wise (a foreign editor's style)."""
    g = PG.LDGraph("L")
    for i in range(k):
        g.add_node(str(i + 1), "contact", C(f"A{i}"))
        g.add_node(str(k + i + 1), "contact", C(f"B{i}"))
        g.add_edge("L", str(i + 1))
        g.add_edge(str(i + 1), str(k + i + 1))
    g.add_node("999", "coil", O("Y"))
    for i in range(k):
        g.add_edge(str(k + i + 1), "999")
    good = [OR(*[[C(f"A{i}"), C(f"B{i}")] for i in range(k)]), {**O("Y"), "_nid": "999"}]
    assert PG.verify_elements(g, good) == (True, "exact-bdd")
    bad = [OR(*[[C(f"A{i}"), C(f"B{i}")] for i in range(k - 1)] + [[C(f"A{k-1}")]]), {**O("Y"), "_nid": "999"}]
    ok, why = PG.verify_elements(g, bad)
    assert not ok and "ENERGIZE" in why


def test_p3c_r_trig_to_f_trig_imports_osf_with_output_and_warns():
    xml = _xml([C("PB"), {"kind": "oneshot", "block": "ONS", "var": "OS1"}, O("Pulse")])
    back, warns = _imp(xml.replace('typeName="R_TRIG"', 'typeName="F_TRIG"'))
    els = _rungs(back)[0]
    assert els[-1] == {"kind": "oneshot", "block": "OSF", "var": "OS1", "output": "Pulse"}
    assert warns and "rung 1" in warns[0]
    s = ScanSimulator.from_program(back, cycle_ms=CYCLE)
    assert [s.scan_once({"PB": v})["vars"].get("Pulse") for v in (False, True, True, False, False)] == [
        False, False, False, True, False]


def test_p3c_f_trig_q_feeding_more_logic_still_refuses():
    xml = _xml([C("PB"), {"kind": "oneshot", "block": "ONS", "var": "OS1"}, C("X"), O("Pulse")])
    x2 = xml.replace('typeName="R_TRIG"', 'typeName="F_TRIG"')
    with pytest.raises(ValueError, match="ENERGIZE"):  # outside the OSF model: fail-safe refusal
        import_plcopen_xml_to_program(x2)


def test_p3d_osr_instance_rename_is_honoured():
    xml = _xml([C("PB"), {"kind": "oneshot", "block": "OSR", "var": "OS2", "output": "RISE"}])
    back, warns = _imp(xml.replace('instanceName="OS2"', 'instanceName="OS9"'))
    assert _rungs(back)[0][-1]["var"] == "OS9" and warns


def test_p3_1_dangling_tamper_contact_refuses():
    # v0.3.19: 0.3.18 dropped the dead-end contact with a warning; now refused (never guess).
    xml = _xml([C("A"), O("Y")])
    rail = re.findall(r'<leftPowerRail localId="(\d+)"', xml)[0]
    extra = (f'<contact localId="9101"><position x="0" y="0"/><connectionPointIn><connection refLocalId="{rail}"/>'
             '</connectionPointIn><connectionPointOut/><variable>Tamper</variable></contact>')
    for x in (xml, _strip_hint(xml)):
        x2 = x.replace("<rightPowerRail", extra + "<rightPowerRail", 1)
        with pytest.raises(ValueError, match="drive nothing") as ei:
            _imp(x2)
        assert "rung 1: <contact> Tamper (localId 9101)" in str(ei.value)


# ------------------------------------------------------------------ real UI (NEW-10)


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    ctk = pytest.importorskip("customtkinter")

    from cabinet_studio.models.project import Project
    from cabinet_studio.services.programming import program_to_dict
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
    prog = _prog([C("A"), O("Y")])
    try:
        root = ctk.CTk()
    except Exception as exc:  # pragma: no cover - no display
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    errors: list[str] = []
    root.report_callback_exception = lambda e, v, tb: errors.append("".join(traceback.format_exception(e, v, tb)))
    project = Project(name="UI18", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                      program=program_to_dict(prog), items=[])
    v = pv.ProgrammingViewer(root, Fonts(*choose_families(root)), project, lambda *_: None)
    v.update()
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


def _make_bad(ui):
    ui.program = add_rung_from_elements(ui.program, [C("A"), {"kind": "math", "op": "CPT", "dest": "D", "source_a": "1/0"}])


def _count_scans(monkeypatch):
    calls = []
    orig = ScanSimulator.scan_once

    def spy(self, *a, **k):
        calls.append(1)
        return orig(self, *a, **k)

    monkeypatch.setattr(ScanSimulator, "scan_once", spy)
    return calls


def test_ui_force_and_clear_forces_blocked(ui, monkeypatch):
    _make_bad(ui)
    calls = _count_scans(monkeypatch)
    ui._sim_toggle_force("A")
    ui._sim_clear_forces()
    ui.update()
    assert calls == []
    assert "Sim BLOCKED" in ui._sim_status.cget("text")
    assert not ui._errors


def test_ui_running_scan_tick_stops_when_program_becomes_blocked(ui, monkeypatch):
    ui._sim_toggle_run()
    ui.update()
    assert ui._sim_running
    _make_bad(ui)
    calls = _count_scans(monkeypatch)
    ui._sim_scan_tick()
    ui.update()
    assert calls == [] and not ui._sim_running
    assert "Sim BLOCKED" in ui._sim_status.cget("text")
    assert not ui._errors


def test_ui_sim_blocked_fails_closed(ui, monkeypatch):
    monkeypatch.setattr(LS, "sim_blockers", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    calls = _count_scans(monkeypatch)
    ui._sim_step()
    ui._sim_toggle_force("A")
    ui.update()
    assert calls == []
    assert "Sim BLOCKED" in ui._sim_status.cget("text")
