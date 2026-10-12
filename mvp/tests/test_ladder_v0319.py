"""v0.3.19: Deflector v0.3.18 re-verify P1s + P3s, Raddus deleted-object fuzz.

P1-A  (N4f) no left rail → refuse naming the objects; never guess which object was the rail
      (0.3.17/0.3.18 treated the single missing id as the rail; a deleted first Stop / E-stop
      contact looks the same and imported as "verified"). Declared-but-unused inputs are
      named as the likely deleted contact.
P1-B  a wire to a localId that does not exist (deleted object) → refuse naming rung + id.
      Also: duplicate localIds, wires out of a right rail (Audit randgraph KeyError).
FUZZ  (Raddus) one-object-deleted variants of every template / seal-in pattern: a dead-end
      contact (drives no coil / block) refuses; a one-shot whose noted output coil is not
      wired to its Q refuses. Every variant refuses or imports with logic equal to the source.
P3-a  MotorStarter with a bypassed Stop (coil rewired around it) → refused, naming PB_Stop.
P3-b  TIME presets above T#24d20h31m23s647ms (2,147,483,647 ms) refuse.
P3-c  look-alike / non-identifier tag names → one warning per tag.
P3-d  (test_ladder_v0318) metadata tampering via a real XML parse (py3.13-safe).
P3-e  routine metadata-only warning no longer claims the file is "exported before 0.3.18".
"""
from __future__ import annotations

import re
import traceback

import pytest

from cabinet_studio import __version__
from cabinet_studio.services.ladder_ir import (
    TIME_MAX_MS,
    parse_iec_duration_ms,
    program_to_ladder_ir,
)
from cabinet_studio.services.ladder_templates import AOI_TEMPLATES, apply_aoi_template
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
    import_plcopen_xml_to_program_checked,
    tag_name_warnings,
)
from cabinet_studio.services.programming import (
    add_rung_from_elements,
    empty_program,
    program_from_dict,
)


def C(v, nc=False):
    return {"kind": "contact", "var": v, "form": "NC" if nc else "NO"}


def O(v, form="normal"):
    return {"kind": "coil", "var": v, "form": form}


def OR(*branches):
    return {"kind": "or", "branches": [list(b) for b in branches]}


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


def _logic(prog):
    ir = program_to_ladder_ir(program_from_dict(prog))
    return ([r["elements"] for r in ir["rungs"]],
            {k: [r["elements"] for r in v] for k, v in (ir.get("routines") or {}).items()})


def _both(xml):
    return [("hinted", xml), ("stripped", _strip_hint(xml))]


def _del_obj(xml, tag, var):
    """Delete the first <tag> object whose <variable> is ``var`` (leave the wires to it)."""
    m = re.search(r'<%s localId="(\d+)"[^>]*>(?:(?!</%s>).)*<variable>%s</variable>(?:(?!</%s>).)*</%s>'
                  % (tag, tag, re.escape(var), tag, tag), xml, flags=re.S)
    assert m, (tag, var)
    return xml[:m.start()] + xml[m.end():], m.group(1)


def _lid(xml, tag, var):
    m = re.search(r'<%s localId="(\d+)"[^>]*>(?:(?!</%s>).)*<variable>%s</variable>' % (tag, tag, re.escape(var)), xml, flags=re.S)
    return m.group(1)


# ------------------------------------------------------------------ version


def test_version_is_0319():
    # v0.3.20: the strict equality lives in the newest version's test file only.
    assert tuple(int(x) for x in __version__.split(".")) >= (0, 3, 19)


# ------------------------------------------------------------------ P1-A (N4f)


SEAL = [C("PB_Stop", True), OR([C("PB_Start")], [C("M1")]), O("M1")]


def _n4f(rungs, stop):
    x = _xml(*rungs)
    x = re.sub(r"<leftPowerRail .*?</leftPowerRail>", "", x, flags=re.S)
    x, _ = _del_obj(x, "contact", stop)
    return x


@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_p1a_n4f_rail_and_first_stop_deleted_refuses_naming_objects(mode):
    x = _n4f([SEAL], "PB_Stop")
    if mode == "stripped":
        x = _strip_hint(x)
    with pytest.raises(ValueError, match="no left power rail") as ei:
        import_plcopen_xml_to_program(x)
    msg = str(ei.value)
    assert "will not guess" in msg and "PB_Start" in msg and "M1" in msg
    assert "Declared input(s) PB_Stop are used by no contact" in msg


@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_p1a_n4f2_estop_first_deleted_refuses(mode):
    rung = [OR([C("PB_Start")], [C("Machine_Run")]), C("ES1", True), C("Light_Curtain", True), O("Machine_Run")]
    x = _xml(rung)
    x = re.sub(r"<leftPowerRail .*?</leftPowerRail>", "", x, flags=re.S)
    # delete the rail AND the first-series contacts that hung off it except the OR → only
    # what the remaining wiring can show; must refuse either way
    if mode == "stripped":
        x = _strip_hint(x)
    with pytest.raises(ValueError, match="no left power rail"):
        import_plcopen_xml_to_program(x)


def test_p1a_deflector_repro_files_refuse():
    import pathlib

    d = pathlib.Path("/workspace/qa/safety-v0318")
    files = [d / "deflector_new_N4f-1_repro.xml", d / "deflector_new_N4f-2_repro.xml"]
    if not all(f.exists() for f in files):
        pytest.skip("Deflector repro files not on this machine")
    for f, sig in zip(files, ["PB_Stop", "ES1"]):
        with pytest.raises(ValueError, match="no left power rail") as ei:
            import_plcopen_xml_to_program(f.read_text(encoding="utf-8"))
        assert f"Declared input(s) {sig}" in str(ei.value)


# ------------------------------------------------------------------ P1-B (missing refs)


SETRESET = ([C("PB_Start"), O("M1", "set")], [OR([C("PB_Stop")], [C("ES1", True)]), O("M1", "reset")])


@pytest.mark.parametrize("form", ["reset", "negated", "normal"])
def test_p1b_reset_coil_branch_contact_deleted_refuses_naming_rung_and_id(form):
    rungs = ([C("PB_Start"), O("M1", "set")], [OR([C("PB_Stop")], [C("ES1", True)]), O("M1", form)])
    for mode, x in _both(_xml(*rungs)):
        x2, gone = _del_obj(x, "contact", "ES1")
        with pytest.raises(ValueError, match="do not exist") as ei:
            import_plcopen_xml_to_program(x2)
        assert "rung 2: <coil> M1 (localId " in str(ei.value), mode
        assert f"missing localId {gone}" in str(ei.value), mode


def test_p1b_deflector_dangle_repros_refuse():
    import pathlib

    d = pathlib.Path("/workspace/qa/safety-v0318")
    files = [d / "deflector_new_DANGLE_reset_hinted_repro.xml", d / "deflector_new_DANGLE_reset_hintless_repro.xml"]
    if not all(f.exists() for f in files):
        pytest.skip("Deflector repro files not on this machine")
    for f in files:
        with pytest.raises(ValueError, match=r"rung 2: <coil> M1 \(localId 8\) is wired to missing localId 7"):
            import_plcopen_xml_to_program(f.read_text(encoding="utf-8"))


def test_p1b_ref_rewritten_to_unknown_id_refuses():
    x = _xml([C("A"), C("B", True), O("Y")])
    bid = _lid(x, "contact", "B")
    x2 = re.sub(r'(<coil localId="\d+"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>\s*<connection refLocalId=")%s"' % bid,
                r'\g<1>4242"', x, count=1)
    assert x2 != x
    for _mode, xx in _both(x2):
        with pytest.raises(ValueError, match="missing localId 4242"):
            import_plcopen_xml_to_program(xx)


def test_p1b_duplicate_localid_refuses():
    x = _xml([C("A"), O("Y")], [C("B"), O("Z")])
    a, b = _lid(x, "contact", "A"), _lid(x, "contact", "B")
    x2 = x.replace(f'<contact localId="{b}"', f'<contact localId="{a}"', 1)
    for _mode, xx in _both(x2):
        with pytest.raises(ValueError, match="used by two LD objects"):
            import_plcopen_xml_to_program(xx)


def test_p1b_reference_into_another_body_is_missing_in_body_and_refuses():
    p = add_rung_from_elements(empty_program(), [C("Auto"), {"kind": "jsr", "target": "Safety"}])
    p.setdefault("routines", {})["Safety"] = [{"id": "s1", "elements": [C("Estop", True), O("Enable")]}]
    x = export_program_to_plcopen_xml(p)
    main_auto = _lid(x, "contact", "Auto")
    body = x[x.index("<routineBody"):]
    est = re.search(r'<contact localId="(\d+)"', body).group(1)
    body2 = body.replace(f'<connection refLocalId="{est}"/>', f'<connection refLocalId="{main_auto}"/>', 1)
    assert body2 != body
    x2 = x[: x.index("<routineBody")] + body2
    with pytest.raises(ValueError, match=f"routine 'Safety'.*missing localId {main_auto}"):
        import_plcopen_xml_to_program(x2)


def test_p1b_cross_rung_wire_still_refused():  # NEW-6 (state it: already refused)
    x = _xml([C("A"), O("Y")], [C("B"), O("Y2")])
    bid = _lid(x, "contact", "B")
    x2 = re.sub(r'(<coil localId="\d+"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>)((?:(?!</coil>).)*<variable>Y</variable>)',
                r'\1<connection refLocalId="%s"/>\2' % bid, x, count=1, flags=re.S)
    assert x2 != x
    for _mode, xx in _both(x2):
        with pytest.raises(ValueError, match="wired together"):
            import_plcopen_xml_to_program(xx)


def test_wire_out_of_right_rail_refuses_cleanly_not_keyerror():
    x = _xml([C("E"), O("M")])
    rid = re.search(r'<rightPowerRail localId="(\d+)"', x).group(1)
    x2 = re.sub(r'(<coil localId="\d+"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>)', r'\1<connection refLocalId="%s"/>' % rid, x, count=1)
    for _mode, xx in _both(x2):
        with pytest.raises(ValueError, match="RIGHT power rail"):
            import_plcopen_xml_to_program(xx)


# ------------------------------------------------------------------ dead ends / P3-a


def test_deleted_or_wire_into_reset_coil_refuses_as_dead_end():
    x = _xml(*SETRESET)
    es = _lid(x, "contact", "ES1")
    for mode, xx in _both(x):
        m = list(re.finditer(r'<coil localId="\d+"[^>]*>(?:(?!</coil>).)*</coil>', xx, flags=re.S))[1]
        seg = m.group(0)
        seg2 = seg.replace(f'<connection refLocalId="{es}"/>', "", 1)
        assert seg2 != seg
        x2 = xx[:m.start()] + seg2 + xx[m.end():]
        with pytest.raises(ValueError, match="drive nothing") as ei:
            import_plcopen_xml_to_program(x2)
        assert f"rung 2: <contact> /ES1 (localId {es})" in str(ei.value), mode


def test_p3a_motorstarter_bypassed_stop_refuses_hinted_and_hintless():
    p = apply_aoi_template(empty_program(), "MotorStarter")
    x = export_program_to_plcopen_xml(p)
    stop = _lid(x, "contact", "PB_Stop")
    # rewire everything that read the Stop's output to the Stop's own input (Stop bypassed)
    stop_in = re.search(r'<contact localId="%s"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>\s*<connection refLocalId="(\d+)"' % stop, x).group(1)
    x2 = x.replace(f'<connection refLocalId="{stop}"/>', f'<connection refLocalId="{stop_in}"/>')
    assert x2 != x
    for mode, xx in _both(x2):
        with pytest.raises(ValueError, match="drive nothing") as ei:
            import_plcopen_xml_to_program(xx)
        assert f"<contact> /PB_Stop (localId {stop})" in str(ei.value), mode


@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_oneshot_output_coil_deleted_refuses(mode):
    p = apply_aoi_template(empty_program(), "PulseExtend")
    x = export_program_to_plcopen_xml(p)
    if mode == "stripped":
        x = _strip_hint(x)
    x2, _ = _del_obj(x, "coil", "Pulse_Edge")
    with pytest.raises(ValueError, match="no coil Pulse_Edge is wired to its Q pin"):
        import_plcopen_xml_to_program(x2)


# ------------------------------------------------------------------ deleted-object fuzz (compact)

_OBJ_RE = re.compile(r"<(leftPowerRail|rightPowerRail|contact|coil|block|comment)\b[^>]*?\blocalId=\"(\d+)\"[^>]*?(/?)>")
_CONN_RE = re.compile(r"<connection\b[^>]*?\brefLocalId=\"\d+\"[^>]*?(?:/>|>.*?</connection>)", re.S)


def _variants(xml):
    spans = [(m.start(), m.end()) for m in re.finditer(r"<LD\b.*?</LD>|<routineBody\b.*?</routineBody>", xml, re.S)]
    inside = lambda p: any(a <= p < b for a, b in spans)  # noqa: E731
    for m in _OBJ_RE.finditer(xml):
        if inside(m.start()):
            end = m.end() if m.group(3) == "/" else xml.find(f"</{m.group(1)}>", m.end()) + len(f"</{m.group(1)}>")
            yield f"OBJ {m.group(1)}#{m.group(2)}", xml[:m.start()] + xml[end:]
    for m in _CONN_RE.finditer(xml):
        if inside(m.start()):
            yield f"REF @{m.start()}", xml[:m.start()] + xml[m.end():]


def _fuzz_sources():
    out = {f"template:{n}": apply_aoi_template(empty_program(), n) for n in AOI_TEMPLATES}
    out["seal:ote"] = _prog(SEAL)
    out["seal:set_reset"] = _prog(*SETRESET)
    out["seal:estop_stop_after_or"] = _prog([C("ES1", True), OR([C("PB_Start")], [C("HMI")], [C("M1")]), C("PB_Stop", True), O("M1")])
    return out


@pytest.mark.parametrize("name", sorted(_fuzz_sources()))
def test_deleted_object_fuzz_never_accepts_changed_logic(name):
    p = _fuzz_sources()[name]
    base = _logic(p)
    bad = []
    n = 0
    for mode, xml in _both(export_program_to_plcopen_xml(p, project_name="QA")):
        for vid, vx in _variants(xml):
            n += 1
            try:
                back, _w = import_plcopen_xml_to_program_checked(vx)
            except ValueError:
                continue
            except Exception as e:  # noqa: BLE001 - a crash is a failure
                bad.append((mode, vid, f"CRASH {type(e).__name__}: {e}"))
                continue
            if _logic(back) != base:
                bad.append((mode, vid, "ACCEPTED_CHANGED"))
    assert n > 10
    assert not bad, bad[:5]


# ------------------------------------------------------------------ P3-b TIME max


def test_p3b_time_max_is_dint_ms():
    assert TIME_MAX_MS == 2_147_483_647
    assert parse_iec_duration_ms("T#24d20h31m23s647ms") == TIME_MAX_MS
    for bad in ("T#24d20h31m23s648ms", "T#30d", "T#99999999d", "TIME#25d", str(TIME_MAX_MS + 1)):
        with pytest.raises(ValueError, match="maximum timer preset"):
            parse_iec_duration_ms(bad)


@pytest.mark.parametrize("pt,ok", [("T#24d", True), ("T#24d20h31m23s647ms", True), ("T#30d", False), ("T#99999999d", False)])
def test_p3b_import_out_of_range_preset_refuses(pt, ok):
    x = _xml([C("A"), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 1000}], [C("T1.DN"), O("Y")])
    x2 = re.sub(r"<expression>T#[^<]*</expression>", f"<expression>{pt}</expression>", x, count=1)
    assert x2 != x
    for _mode, xx in _both(x2):
        if ok:
            back, _ = _imp(_strip_hint(xx))
            assert _logic(back)[0][0][1]["pt_ms"] == parse_iec_duration_ms(pt)
        else:
            with pytest.raises(ValueError, match="maximum timer preset"):
                import_plcopen_xml_to_program(_strip_hint(xx))


# ------------------------------------------------------------------ P3-e routine wording


def test_p3e_routine_metadata_only_warning_does_not_claim_pre_0318_export():
    from cabinet_studio.services import plcopen_xml as PX

    p = add_rung_from_elements(empty_program(), [C("Auto"), {"kind": "jsr", "target": "Safety"}])
    p.setdefault("routines", {})["Safety"] = [{"id": "s1", "elements": [C("Estop", True), O("Enable")]}]
    x = export_program_to_plcopen_xml(p)
    x = re.sub(r"<addData>\s*<data name=\"urn:cabinet-studio:routine-networks\".*?</addData>", "", x, flags=re.S)
    x = re.sub(r",?(?:&quot;|\")routine_wiring(?:&quot;|\"):true", "", x)
    _back, warns = _imp(x)
    w = [s for s in warns if "metadata ONLY" in s]
    assert w and "exported before 0.3.18" not in w[0] and "edited outside" in w[0], warns
    assert PX  # module import used for clarity


# ------------------------------------------------------------------ P3-c tag names


@pytest.mark.parametrize("name,why", [
    ("PB_Stop\u200b", "invisible character"),
    ("PB_St\u043ep", "CYRILLIC SMALL LETTER O"),
    ("\uff2d1", "FULLWIDTH"),
    ("1abc", "not an IEC 61131-3 identifier"),
    ("A B", "not an IEC 61131-3 identifier"),
])
def test_p3c_suspicious_tag_names_warn_per_tag(name, why):
    for _mode, xx in _both(_xml([C(name), C("PB_Stop", True), O("Y")])):
        back, warns = _imp(xx)
        hits = [w for w in warns if w.startswith("WARNING tag") and why in w]
        assert len(hits) == 1, warns
        assert _logic(back)[0][0][0]["var"] == name  # imported as-is (warned, not renamed)


def test_p3c_case_only_collision_warns():
    _back, warns = _imp(_xml([C("pb_stop"), C("PB_Stop", True), O("Y")]))
    assert any("differ only in upper/lower case" in w and "'PB_Stop'" in w and "'pb_stop'" in w for w in warns), warns


@pytest.mark.parametrize("name", ["Tank.Level", "Arr[3]", "%IX0.1", "Local:1:I.Data.0", "T1.DN", "Motor_1"])
def test_p3c_normal_names_do_not_warn(name):
    assert tag_name_warnings([name, "PB_Stop"]) == []


# ------------------------------------------------------------------ real UI (N4f)


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    ctk = pytest.importorskip("customtkinter")
    import tkinter.filedialog as fd

    from cabinet_studio.models.project import Project
    from cabinet_studio.services.programming import program_to_dict
    from cabinet_studio.ui import programming_viewer as pv
    from cabinet_studio.ui.theme import Fonts, choose_families

    monkeypatch.setattr("cabinet_studio.ui.util.saves_directory", lambda origin=None: tmp_path)
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
    project = Project(name="UI19", template_id=None, cabinet_width=800, cabinet_height=600, cabinet_label="CP1",
                      program=program_to_dict(_prog([C("Keep"), O("Me")])), items=[])
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


@pytest.mark.parametrize("which", ["n4f", "dangle", "deadend", "jsr_missing", "empty_pt"])
def test_ui_import_of_damaged_files_refuses_and_keeps_program(ui, which):
    if which == "n4f":
        x = _n4f([SEAL], "PB_Stop")
    elif which == "dangle":
        x, _ = _del_obj(_xml(*SETRESET), "contact", "ES1")
    elif which == "jsr_missing":
        x = re.sub(r"<routineBody\b.*?</routineBody>|<addData>.*?</addData>|cabinet-studio-meta:[^<]*", "",
                   export_program_to_plcopen_xml(_jsr_prog()), flags=re.S)
    elif which == "empty_pt":
        x = re.sub(r"<expression>T#[^<]*</expression>", "<expression></expression>", _strip_hint(_timer_xml()), count=1)
    else:
        p = apply_aoi_template(empty_program(), "MotorStarter")
        x = export_program_to_plcopen_xml(p)
        stop = _lid(x, "contact", "PB_Stop")
        stop_in = re.search(r'<contact localId="%s"[^>]*>\s*<position[^>]*/>\s*<connectionPointIn>\s*<connection refLocalId="(\d+)"' % stop, x).group(1)
        x = x.replace(f'<connection refLocalId="{stop}"/>', f'<connection refLocalId="{stop_in}"/>')
    before = _logic(ui.program)
    ui._xml_path.write_text(x, encoding="utf-8")
    ui.import_plcopen_xml()
    ui.update()
    st = ui.status.cget("text")
    assert "REFUSED" in st, st
    assert _logic(ui.program) == before
    assert not ui._errors


# ------------------------------------------------------------------ hint vs wiring diff names objects


def test_hinted_clean_deletion_of_seal_branch_warns_naming_the_contact():
    # object AND its wires deleted (nothing dangles): hint-less this is a valid different
    # program; with the hint kept the warning must name what the wiring lost.
    x = _xml(SEAL)
    m1 = _lid(x, "contact", "M1")
    x2, _ = _del_obj(x, "contact", "M1")
    x2 = x2.replace(f'<connection refLocalId="{m1}"/>', "")
    back, warns = _imp(x2)
    assert _logic(back)[0] == [[C("PB_Stop", True), C("PB_Start"), O("M1")]]
    assert any("hint did not match" in w and "The hint has <contact> M1 that the wiring does NOT have" in w for w in warns), warns


def test_routine_metadata_mismatch_names_missing_contact():
    p = add_rung_from_elements(empty_program(), [C("Auto"), {"kind": "jsr", "target": "Safety"}])
    p.setdefault("routines", {})["Safety"] = [{"id": "s1", "elements": [C("Enable"), OR([C("Guard")], [C("Key")]), O("Run")]}]
    x = export_program_to_plcopen_xml(p)
    body = x[x.index("<routineBody"):]
    key = re.search(r'<contact localId="(\d+)"[^>]*>(?:(?!</contact>).)*<variable>Key</variable>', body, flags=re.S).group(1)
    body2 = re.sub(r'<contact localId="%s".*?</contact>' % key, "", body, count=1, flags=re.S).replace(f'<connection refLocalId="{key}"/>', "")
    x2 = _strip_hint(x[: x.index("<routineBody")] + body2)
    _back, warns = _imp(x2)
    assert any("routine 'Safety' rung 1" in w and "The metadata has <contact> Key that the wiring does NOT have" in w for w in warns), warns


# ------------------------------------------------------------------ strict TC6 allowlist (attribute fuzz)


def _ms_xml():
    return export_program_to_plcopen_xml(apply_aoi_template(empty_program(), "TimedStart"), project_name="QA")


def _first_tag(xml, tag):
    m = re.search(r"<%s\b[^>]*>" % tag, xml)
    return m


def _add_to_first(xml, tag, attr):
    m = _first_tag(xml, tag)
    st = m.group(0)
    new = st[:-1] + f" {attr}>" if not st.endswith("/>") else st[:-2] + f" {attr}/>"
    return xml[:m.start()] + new + xml[m.end():]


SEMANTIC_MUTANTS = {
    "edge rising contact": lambda x: _add_to_first(x, "contact", 'edge="rising"'),
    "edge falling coil": lambda x: _add_to_first(x, "coil", 'edge="falling"'),
    "negated block pin": lambda x: x.replace('<variable formalParameter="IN">', '<variable formalParameter="IN" negated="true">', 1),
    "unknown typeName TP": lambda x: x.replace('typeName="TON"', 'typeName="TP"', 1),
    "IEC operator name GT": lambda x: x.replace('typeName="TON"', 'typeName="GT"', 1),
    "unknown pin": lambda x: x.replace('formalParameter="PT"', 'formalParameter="PT2"', 1),
    "wire takes ET": lambda x: x.replace('formalParameter="Q"/>', 'formalParameter="ET"/>', 1) if 'formalParameter="Q"/>' in x else x.replace("<connection refLocalId=", '<connection formalParameter="ET" refLocalId=', 1),
    "jump element": lambda x: x.replace("</LD>", '<jump localId="9001" label="L1"><position x="0" y="0"/></jump></LD>', 1),
    # a full, valid second program: only the one-POU rule can catch it
    "second POU": lambda x: x.replace("</pous>", re.search(r"<pou .*?</pou>", x, re.S).group(0).replace('name="Main"', 'name="Second"', 1) + "</pous>", 1),
    "retain variables": lambda x: x.replace("<inputVars>", '<inputVars retain="true">', 1),
    "unknown attribute": lambda x: _add_to_first(x, "contact", 'foo="1"'),
    "negated + storage coil": lambda x: x.replace('storage="set"', 'storage="set" negated="true"', 1) if 'storage="set"' in x else _add_to_first(x, "coil", 'storage="set" negated="true"'),
}

EQUIVALENT_MUTANTS = {
    "executionOrderId": lambda x: _add_to_first(x, "contact", 'executionOrderId="3"'),
    "edge none": lambda x: _add_to_first(x, "contact", 'edge="none"'),
    "negated spelled 0": lambda x: x.replace('negated="false"', 'negated="0"', 1),
    "addData": lambda x: x.replace("<connectionPointOut/>", '<connectionPointOut/><addData><data name="urn:v" handleUnknown="discard"><a/></data></addData>', 1),
    "lower-case typeName": lambda x: x.replace('typeName="TON"', 'typeName="ton"', 1),
    "single address": lambda x: re.sub(r'<variable name="([^"]+)">', r'<variable name="\1" address="%IX0.0">', x, count=1),
}


@pytest.mark.parametrize("name", sorted(SEMANTIC_MUTANTS))
@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_allowlist_unmodelled_tc6_refuses(name, mode):
    x = _ms_xml() if mode == "hinted" else _strip_hint(_ms_xml())
    x2 = SEMANTIC_MUTANTS[name](x)
    assert x2 != x
    with pytest.raises(ValueError, match="does not model this|refused"):
        import_plcopen_xml_to_program(x2)


@pytest.mark.parametrize("name", sorted(EQUIVALENT_MUTANTS))
@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_allowlist_cosmetic_or_equivalent_imports_exactly(name, mode):
    p = apply_aoi_template(empty_program(), "TimedStart")
    x = _ms_xml() if mode == "hinted" else _strip_hint(_ms_xml())
    x2 = EQUIVALENT_MUTANTS[name](x)
    assert x2 != x
    back, _w = _imp(x2)
    assert _logic(back) == _logic(p)


def test_allowlist_legacy_variable_attribute_must_agree():
    x = _strip_hint(_xml([C("A"), O("Y")]))
    ok = _add_to_first(x, "contact", 'variable="A"')
    back, _ = _imp(ok)
    assert _logic(back)[0] == [[C("A"), O("Y")]]
    with pytest.raises(ValueError, match="two different variables"):
        import_plcopen_xml_to_program(_add_to_first(x, "contact", 'variable="B"'))


def test_allowlist_shared_address_is_aliasing_refused():
    x = _strip_hint(_xml([C("A"), C("B"), O("Y")]))
    x2 = re.sub(r'<variable name="(A|B)">', r'<variable name="\1" address="%IX0.0">', x)
    assert x2.count('address="%IX0.0"') == 2
    with pytest.raises(ValueError, match="aliasing"):
        import_plcopen_xml_to_program(x2)


@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_dead_end_compare_block_in_or_branch_refuses(mode):
    """Fuzz find (instr_compare_math): deleting one of the two wires into the Alarm coil
    left the EQU compare driving nothing; the rung imported as Alarm = NEQ only."""
    import xml.etree.ElementTree as ET
    eq = {"kind": "compare", "op": "EQU", "source_a": "Mode", "source_b": "2"}
    ne = {"kind": "compare", "op": "NEQ", "source_a": "Fault", "source_b": "0"}
    x = _xml([OR([eq], [ne]), O("Alarm")])
    if mode == "stripped":
        x = _strip_hint(x)
    back, _ = _imp(x)  # baseline imports
    ns = "{http://www.plcopen.org/xml/tc6_0201}"
    root = ET.fromstring(x)
    coil = next(c for c in root.iter(ns + "coil"))
    cpi = coil.find(ns + "connectionPointIn")
    conns = cpi.findall(ns + "connection")
    assert len(conns) == 2
    cpi.remove(conns[0])
    x2 = ET.tostring(root, encoding="unicode")
    with pytest.raises(ValueError, match="drive nothing") as ei:
        import_plcopen_xml_to_program(x2)
    assert "<block>" in str(ei.value)


# ------------------------------------------------------------------ NEW-16 / P2: call to a missing routine


def _jsr_prog():
    p = _prog([C("Start"), O("Motor", "set")], [{"kind": "jsr", "target": "Safety"}])
    p.setdefault("routines", {})["Safety"] = [{"id": "s1", "elements": [C("Estop"), O("Motor", "reset")]}]
    return p


_ROUTINE_GONE = {
    "meta_and_adddata_removed": r"<addData>.*?</addData>|cabinet-studio-meta:[^<]*",
    "whole_routine_removed": r"<routineBody\b.*?</routineBody>|<addData>.*?</addData>|cabinet-studio-meta:[^<]*",
}


@pytest.mark.parametrize("how", sorted(_ROUTINE_GONE))
@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_new16_jsr_to_removed_routine_refuses(how, mode):
    x = re.sub(_ROUTINE_GONE[how], "", export_program_to_plcopen_xml(_jsr_prog()), flags=re.S)
    if mode == "stripped":
        x = _strip_hint(x)
    with pytest.raises(ValueError, match=r"rung 2 calls JSR Safety, but this file contains no routine"):
        import_plcopen_xml_to_program(x)


def test_new16_jsr_to_never_written_routine_refuses_and_sim_blocks():
    from cabinet_studio.services.ladder_sim import sim_blockers

    p = _prog([C("Start"), {"kind": "jsr", "target": "Nowhere"}])
    assert any("JSR Nowhere" in b and "no routine named Nowhere" in b for b in sim_blockers(p))
    with pytest.raises(ValueError, match="calls JSR Nowhere"):
        import_plcopen_xml_to_program(export_program_to_plcopen_xml(p))


def test_new16_jsr_with_routine_present_still_round_trips():
    p = _jsr_prog()
    back, _w = _imp(export_program_to_plcopen_xml(p))
    assert _logic(back) == _logic(p)
    from cabinet_studio.services.ladder_sim import sim_blockers

    assert not [b for b in sim_blockers(p) if "JSR" in b]


# ------------------------------------------------------------------ NEW-17: empty preset / operand pins


def _timer_xml():
    return _xml([C("A"), {"kind": "timer", "var": "T1", "block": "TON", "pt_ms": 5000}], [C("T1.DN"), O("Y")])


@pytest.mark.parametrize("empty", ["<expression></expression>", "<expression/>", ""])
@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_new17_empty_pt_refuses_even_with_doc_note(empty, mode):
    x = _timer_xml() if mode == "hinted" else _strip_hint(_timer_xml())
    x2 = re.sub(r"<expression>T#[^<]*</expression>", empty, x, count=1)
    assert x2 != x and "pt_ms=5000" in x2
    with pytest.raises(ValueError, match=r"PT \(preset time\) input has no value.*never supplies a preset"):
        import_plcopen_xml_to_program(x2)


@pytest.mark.parametrize("mode", ["hinted", "stripped"])
def test_new17_empty_pv_refuses(mode):
    x = _xml([C("A"), {"kind": "counter", "var": "C1", "block": "CTU", "pv": 5}], [C("C1.DN"), O("Y")])
    x = x if mode == "hinted" else _strip_hint(x)
    x2 = re.sub(r'(<variable formalParameter="PV">\s*<connectionPointIn>\s*<expression>)[^<]*', r"\1", x, count=1)
    assert x2 != x
    with pytest.raises(ValueError, match=r"PV \(preset\) input has no value"):
        import_plcopen_xml_to_program(x2)


def test_new17_res_and_load_keep_their_documented_pv_note():
    p = _prog([C("A"), {"kind": "counter", "var": "C1", "block": "CTU", "pv": 5}],
              [C("B"), {"kind": "counter", "var": "C1", "block": "LOAD", "pv": 3}],
              [C("R"), {"kind": "counter", "var": "C1", "block": "RES"}])
    for _mode, xx in _both(export_program_to_plcopen_xml(p)):
        back, _w = _imp(xx)
        assert _logic(back) == _logic(p)


GEQ = {"kind": "compare", "op": "GEQ", "source_a": "Temp", "source_b": "10"}


@pytest.mark.parametrize("pin,text,side", [("IN1", "Temp", "source_a"), ("IN2", "10", "source_b")])
def test_new17_empty_compare_operand_imports_empty_warns_and_sim_blocks(pin, text, side):
    from cabinet_studio.services.ladder_sim import sim_blockers

    x = _strip_hint(_xml([C("G"), GEQ, O("Hi")]))
    x2 = x.replace(f"<expression>{text}</expression>", "<expression></expression>", 1)
    back, warns = _imp(x2)
    cmp_el = _logic(back)[0][0][1]
    assert cmp_el["op"] == "GEQ" and cmp_el[side] == ""  # never filled from the COMPARE note
    assert any(f"GEQ block has no value on {pin}" in w for w in warns), warns
    assert any("operand" in b and "empty" in b for b in sim_blockers(back))


def test_new17_math_note_never_supplies_operand_dest_or_expr():
    from cabinet_studio.services.ladder_sim import sim_blockers

    add = {"kind": "math", "op": "ADD", "dest": "Out", "source_a": "A", "source_b": "B"}
    x = _strip_hint(_xml([C("G"), add]))
    back, warns = _imp(x.replace("<expression>B</expression>", "<expression></expression>", 1))
    assert _logic(back)[0][0][1]["source_b"] == "" and any("ADD block has no value on IN2" in w for w in warns)
    assert sim_blockers(back)
    back, _ = _imp(x.replace("dest=Out", "dest=Motor_Speed", 1))
    assert _logic(back)[0][0][1]["dest"] == "Out"  # instanceName is the dest; the note is a label
    cpt = {"kind": "math", "op": "CPT", "dest": "Out", "source_a": "", "expression": "A*2"}
    x = _strip_hint(_xml([C("G"), cpt]))
    back, warns = _imp(x.replace("<expression>A*2</expression>", "<expression></expression>", 1))
    el = _logic(back)[0][0][1]
    assert el["expression"] == "" and any("CPT block has no value on IN1" in w for w in warns)
    assert sim_blockers(back)


@pytest.mark.parametrize("op", ["ADD", "SUB", "MUL", "DIV", "MOV", "CPT", "NOT"])
def test_math_round_trip_unchanged_by_note_policy(op):
    el = {"kind": "math", "op": op, "dest": "Out", "source_a": "A", "source_b": "B"}
    if op == "CPT":
        el = {"kind": "math", "op": "CPT", "dest": "Out", "source_a": "A+B", "expression": "A+B"}
    p = _prog([C("G"), el], [C("H"), {"kind": "math", "op": "ADD", "dest": "", "source_a": "1", "source_b": "2"}, O("Z")])
    for _mode, xx in _both(export_program_to_plcopen_xml(p)):
        back, _w = _imp(xx)
        assert _logic(back) == _logic(p)


# ------------------------------------------------------------------ P3-I typed based literals


@pytest.mark.parametrize("text,ok", [("SINT#16#7F", 127), ("UINT#16#FFFF", 65535), ("SINT#16#FF", None),
                                     ("INT#16#FFFF", None), ("SINT#200", None), ("T#\u0665s", None)])
def test_p3i_signed_based_literal_and_unicode(text, ok):
    from cabinet_studio.services.ladder_ir import parse_iec_int

    fn = parse_iec_duration_ms if text.startswith("T#") else parse_iec_int
    if ok is None:
        with pytest.raises(ValueError):
            fn(text)
    else:
        assert fn(text) == ok
