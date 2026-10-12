"""Import-ready files for the selected PLC (or HMI), written to saves/drawings/<slug>/plc/.

Full project download into a real controller is done with the maker's software (Studio 5000 / CCW,
TIA Portal, Sysmac Studio / CX-Programmer). These files carry the program, tags and I/O addresses
into that software:

* Allen-Bradley Logix: Studio 5000 .L5X (program import: MainProgram / MainRoutine RLL rungs,
  program tags, I/O alias tags) plus a Studio 5000 tag CSV.
* Micro800 (CCW), Siemens TIA and Omron Sysmac: the PLCopen XML program plus vendor tag tables.
* Every maker: the I/O list CSV, a plain rung listing and README.txt with step-by-step imports.

Anything the L5X writer cannot map exactly refuses the whole L5X with a plain message; nothing is
silently dropped. The software is never the safety function (NFPA 79 / ISO 13849).
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.services.io_assign import SAFETY_NOTE, IoReport, assign_io, detect_profile, selected_plc

DISCLAIMER = "NOT A CERTIFIED UL 508A DRAWING. Design aid only."
LOGIX_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")
_CMP2 = ("EQU", "NEQ", "GRT", "LES", "GEQ", "LEQ")
_MATH3 = ("ADD", "SUB", "MUL", "DIV", "AND", "OR", "XOR")
_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


class RllError(ValueError):
    """An instruction cannot be written as Studio 5000 RLL text exactly."""


# ----------------------------------------------------------------------------- IR -> RLL text

def _need(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RllError(f"{what} is empty.")
    return text


def element_to_rll(el: dict[str, Any]) -> str:
    kind = str(el.get("kind") or "").lower()
    if kind == "contact":
        return f"{'XIO' if str(el.get('form')).upper() == 'NC' else 'XIC'}({_need(el.get('var'), 'Contact tag')})"
    if kind == "coil":
        form = str(el.get("form") or "normal").lower()
        mn = {"normal": "OTE", "set": "OTL", "s": "OTL", "reset": "OTU", "r": "OTU"}.get(form)
        if mn is None:
            raise RllError(f"Negated coil on {el.get('var')}: Studio 5000 has no negated OTE. "
                           "Use an XIO contact feeding a normal OTE instead.")
        return f"{mn}({_need(el.get('var'), 'Coil tag')})"
    if kind == "timer":
        blk = str(el.get("block") or "TON").upper()
        if blk not in ("TON", "TOF", "RTO"):
            raise RllError(f"Timer type {blk} has no Studio 5000 equivalent.")
        if str(el.get("pt_tag") or "").strip():
            raise RllError(f"Timer {el.get('var')} takes its preset from tag {el.get('pt_tag')}. Studio 5000 "
                           "timers need a number; set a number, or add MOV(tag,Timer.PRE) after import.")
        return f"{blk}({_need(el.get('var'), 'Timer tag')},{int(el.get('pt_ms') or 0)},0)"
    if kind == "counter":
        blk = str(el.get("block") or "CTU").upper()
        if blk == "RES":
            return f"RES({_need(el.get('var'), 'Counter tag')})"
        if blk not in ("CTU", "CTD"):
            raise RllError(f"Counter instruction {blk} has no Studio 5000 equivalent (use MOV to Counter.ACC).")
        if str(el.get("pv_tag") or "").strip():
            raise RllError(f"Counter {el.get('var')} takes its preset from tag {el.get('pv_tag')}. Studio 5000 "
                           "counters need a number here.")
        return f"{blk}({_need(el.get('var'), 'Counter tag')},{int(el.get('pv') or 0)},0)"
    if kind == "compare":
        op = str(el.get("op") or "EQU").upper()
        a, b, c = (str(el.get(k) or "").strip() for k in ("source_a", "source_b", "source_c"))
        if op in _CMP2:
            return f"{op}({_need(a, op + ' source A')},{_need(b, op + ' source B')})"
        if op == "LIM":
            return f"LIM({_need(b, 'LIM low')},{_need(a, 'LIM test')},{_need(c, 'LIM high')})"
        if op == "MEQ":
            return f"MEQ({_need(a, 'MEQ source')},{_need(b, 'MEQ mask')},{_need(c, 'MEQ compare')})"
        raise RllError(f"Compare {op} has no Studio 5000 equivalent.")
    if kind == "math":
        op = str(el.get("op") or "ADD").upper()
        dest = _need(el.get("dest"), f"{op} destination")
        a, b = str(el.get("source_a") or "").strip(), str(el.get("source_b") or "").strip()
        if op in _MATH3:
            return f"{op}({_need(a, op + ' source A')},{_need(b, op + ' source B')},{dest})"
        if op == "MOV":
            return f"MOV({_need(a, 'MOV source')},{dest})"
        if op == "NOT":
            return f"NOT({_need(a, 'NOT source')},{dest})"
        if op == "CPT":
            return f"CPT({dest},{_need(el.get('expression') or a, 'CPT expression')})"
        raise RllError(f"Math {op} has no Studio 5000 equivalent.")
    if kind == "oneshot":
        blk = str(el.get("block") or "ONS").upper()
        var = _need(el.get("var"), f"{blk} storage bit")
        if blk == "ONS":
            return f"ONS({var})"
        if blk in ("OSR", "OSF"):
            return f"{blk}({var},{_need(el.get('output'), blk + ' output bit')})"
        raise RllError(f"One-shot {blk} has no Studio 5000 equivalent.")
    if kind == "or":
        branches = [b for b in (el.get("branches") or []) if b]
        if len(branches) < 2:
            raise RllError("A branch needs at least two legs.")
        return "[" + ",".join(elements_to_rll(list(b), terminate=False) for b in branches) + "]"
    if kind == "jsr":
        return f"JSR({_need(el.get('target'), 'JSR routine')},0)"
    if kind == "sbr":
        return "SBR()"
    if kind == "ret":
        return "RET()"
    raise RllError(f"Instruction '{kind or '?'}' is not one Cabinet Studio can write to Studio 5000.")


def elements_to_rll(els: list[dict[str, Any]], *, terminate: bool = True) -> str:
    body = "".join(element_to_rll(el) for el in els if isinstance(el, dict))
    if not body and terminate:
        raise RllError("Empty rung.")
    return body + (";" if terminate else "")


# ----------------------------------------------------------------------------- RLL text -> elements

def _split_args(text: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    out.append(cur)
    return [a.strip() for a in out] if text.strip() else []


def parse_rll(text: str) -> list[dict[str, Any]]:
    """Neutral rung text -> element list (only the instructions element_to_rll writes)."""
    src = text.strip()
    if src.endswith(";"):
        src = src[:-1]
    pos = 0

    def parse_seq(stop: str) -> list[dict[str, Any]]:
        nonlocal pos
        els: list[dict[str, Any]] = []
        while pos < len(src) and src[pos] not in stop:
            if src[pos] == "[":
                pos += 1
                branches = [parse_seq(",]")]
                while pos < len(src) and src[pos] == ",":
                    pos += 1
                    branches.append(parse_seq(",]"))
                if pos >= len(src) or src[pos] != "]":
                    raise RllError("Unclosed branch '['.")
                pos += 1
                els.append({"kind": "or", "branches": branches})
                continue
            m = re.match(r"\s*([A-Z]{2,4})\(", src[pos:])
            if not m:
                raise RllError(f"Cannot read rung text at: {src[pos:pos + 20]!r}")
            pos += m.end()
            depth, start = 1, pos
            while pos < len(src) and depth:
                depth += src[pos] == "("
                depth -= src[pos] == ")"
                pos += 1
            if depth:
                raise RllError("Unclosed '('.")
            els.append(_from_mnemonic(m.group(1), _split_args(src[start:pos - 1])))
        return els

    out = parse_seq("")
    if pos != len(src):
        raise RllError("Unexpected text after rung.")
    return out


def _int(text: str) -> int:
    return int(float(text))


def _from_mnemonic(mn: str, a: list[str]) -> dict[str, Any]:
    if mn in ("XIC", "XIO"):
        return {"kind": "contact", "var": a[0], "form": "NC" if mn == "XIO" else "NO"}
    if mn in ("OTE", "OTL", "OTU"):
        return {"kind": "coil", "var": a[0], "form": {"OTE": "normal", "OTL": "set", "OTU": "reset"}[mn]}
    if mn in ("TON", "TOF", "RTO"):
        return {"kind": "timer", "var": a[0], "block": mn, "pt_ms": _int(a[1])}
    if mn in ("CTU", "CTD"):
        return {"kind": "counter", "var": a[0], "block": mn, "pv": _int(a[1])}
    if mn == "RES":
        return {"kind": "counter", "var": a[0], "block": "RES"}
    if mn in _CMP2:
        return {"kind": "compare", "op": mn, "source_a": a[0], "source_b": a[1]}
    if mn == "LIM":
        return {"kind": "compare", "op": "LIM", "source_a": a[1], "source_b": a[0], "source_c": a[2]}
    if mn == "MEQ":
        return {"kind": "compare", "op": "MEQ", "source_a": a[0], "source_b": a[1], "source_c": a[2]}
    if mn in _MATH3:
        return {"kind": "math", "op": mn, "source_a": a[0], "source_b": a[1], "dest": a[2]}
    if mn in ("MOV", "NOT"):
        return {"kind": "math", "op": mn, "source_a": a[0], "dest": a[1]}
    if mn == "CPT":
        return {"kind": "math", "op": "CPT", "dest": a[0], "expression": ",".join(a[1:])}
    if mn == "ONS":
        return {"kind": "oneshot", "block": "ONS", "var": a[0]}
    if mn in ("OSR", "OSF"):
        return {"kind": "oneshot", "block": mn, "var": a[0], "output": a[1]}
    if mn == "JSR":
        return {"kind": "jsr", "target": a[0]}
    if mn == "SBR":
        return {"kind": "sbr"}
    if mn == "RET":
        return {"kind": "ret"}
    raise RllError(f"Unknown instruction {mn}.")


def canonical(els: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Logic-only view of an element list (drops notes / display fields) for round-trip checks."""
    out: list[dict[str, Any]] = []
    for el in els or []:
        kind = str(el.get("kind") or "").lower()
        g = lambda k: str(el.get(k) or "").strip()  # noqa: E731
        if kind == "contact":
            out.append({"kind": kind, "var": g("var"), "form": "NC" if g("form").upper() == "NC" else "NO"})
        elif kind == "coil":
            f = g("form").lower() or "normal"
            out.append({"kind": kind, "var": g("var"), "form": {"s": "set", "r": "reset"}.get(f, f)})
        elif kind == "timer":
            out.append({"kind": kind, "var": g("var"), "block": g("block").upper() or "TON",
                        "pt_ms": int(el.get("pt_ms") or 0)})
        elif kind == "counter":
            blk = g("block").upper() or "CTU"
            c = {"kind": kind, "var": g("var"), "block": blk}
            if blk != "RES":
                c["pv"] = int(el.get("pv") or 0)
            out.append(c)
        elif kind == "compare":
            op = g("op").upper()
            c = {"kind": kind, "op": op, "source_a": g("source_a"), "source_b": g("source_b")}
            if op in ("LIM", "MEQ"):
                c["source_c"] = g("source_c")
            out.append(c)
        elif kind == "math":
            op = g("op").upper()
            c = {"kind": kind, "op": op, "dest": g("dest")}
            if op == "CPT":
                c["expression"] = g("expression") or g("source_a")
            else:
                c["source_a"] = g("source_a")
                if op in _MATH3:
                    c["source_b"] = g("source_b")
            out.append(c)
        elif kind == "oneshot":
            blk = g("block").upper() or "ONS"
            c = {"kind": kind, "block": blk, "var": g("var")}
            if blk != "ONS":
                c["output"] = g("output")
            out.append(c)
        elif kind == "or":
            out.append({"kind": "or", "branches": [canonical(list(b)) for b in el.get("branches") or [] if b]})
        elif kind == "jsr":
            out.append({"kind": kind, "target": g("target")})
        elif kind in ("sbr", "ret"):
            out.append({"kind": kind})
        else:
            out.append({"kind": kind or "?"})
    return out


# ----------------------------------------------------------------------------- program access

_KNOWN = {"contact", "coil", "timer", "counter", "compare", "math", "oneshot", "or", "jsr", "sbr", "ret"}


def _unknown_kinds(els: Any) -> list[str]:
    bad: list[str] = []
    for el in els or []:
        if not isinstance(el, dict):
            bad.append(type(el).__name__)
            continue
        kind = str(el.get("kind") or "").lower()
        if kind not in _KNOWN and kind not in {"ons", "osr", "osf", "r_trig", "f_trig"}:
            bad.append(kind or "(blank)")
        for branch in el.get("branches") or []:
            bad.extend(_unknown_kinds(branch))
    return bad


def program_routines(project: Project) -> list[tuple[str, list[dict[str, Any]]]]:
    """[(routine name, rungs)] with MainRoutine first; each rung has comment + elements."""
    from cabinet_studio.services.ladder_ir import program_rung_to_elements
    from cabinet_studio.services.programming import program_from_dict

    raw = project.program if isinstance(project.program, dict) else {}
    data = program_from_dict(raw)
    out: list[tuple[str, list[dict[str, Any]]]] = []
    sources = [("MainRoutine", data.get("rungs") or [], raw.get("rungs") or [])]
    for name, rungs in sorted((data.get("routines") or {}).items()):
        sources.append((str(name), rungs or [], ((raw.get("routines") or {}).get(name) or [])))
    for name, rungs, raw_rungs in sources:
        built = []
        for i, rung in enumerate(rungs):
            raw_rung = raw_rungs[i] if i < len(raw_rungs) and isinstance(raw_rungs[i], dict) else {}
            bad = _unknown_kinds(raw_rung.get("elements"))
            built.append({"comment": str(rung.get("comment") or ""), "elements": program_rung_to_elements(rung),
                          "unknown": bad})
        out.append((name, built))
    return out


def _walk(els: list[dict[str, Any]]):
    for el in els or []:
        if str(el.get("kind") or "").lower() == "or":
            for b in el.get("branches") or []:
                yield from _walk(list(b or []))
        else:
            yield el


def _tag_types(routines: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, str]:
    from cabinet_studio.services.ladder_tools import expression_tags, is_literal

    types: dict[str, str] = {}

    def put(tag: str, dtype: str, strong: bool = False) -> None:
        t = (tag or "").strip()
        if not t or is_literal(t) or _NUM.match(t):
            return
        base = t.split(".")[0].split("[")[0]
        if "." in t:
            types.setdefault(base, "DINT" if dtype == "DINT" else "BOOL")
            return
        if strong or base not in types or types[base] in ("BOOL", "DINT") and dtype not in ("BOOL", "DINT"):
            types[base] = dtype

    for _name, rungs in routines:
        for rung in rungs:
            for el in _walk(rung["elements"]):
                k = str(el.get("kind") or "").lower()
                if k == "timer":
                    put(el.get("var"), "TIMER", True)
                elif k == "counter":
                    put(el.get("var"), "COUNTER", True)
                elif k in ("contact", "coil"):
                    put(el.get("var"), "BOOL")
                elif k == "oneshot":
                    put(el.get("var"), "BOOL")
                    put(el.get("output"), "BOOL")
                elif k in ("compare", "math"):
                    for key in ("source_a", "source_b", "source_c", "dest"):
                        if key == "source_a" and str(el.get("op") or "").upper() == "CPT":
                            continue
                        put(el.get(key), "DINT")
                    for tok in expression_tags(str(el.get("expression") or "")):
                        put(tok, "DINT")
    return types


# ----------------------------------------------------------------------------- L5X

def _cdata(text: str) -> str:
    return str(text).replace("]]>", "]] >")


def build_l5x(project: Project, plc_id: str | None = None, *, report: IoReport | None = None) -> str:
    """Studio 5000 program-import L5X. Raises RllError naming the first thing it cannot map."""
    report = report or assign_io(project, plc_id, write=False)
    routines = program_routines(project)
    problems: list[str] = []
    texts: dict[str, list[tuple[str, str]]] = {}
    for name, rungs in routines:
        lines = []
        for i, rung in enumerate(rungs):
            if rung["unknown"]:
                problems.append(f"{name} rung {i}: unknown instruction(s) {', '.join(rung['unknown'])}.")
                continue
            try:
                text = elements_to_rll(rung["elements"])
                if canonical(parse_rll(text)) != canonical(rung["elements"]):
                    raise RllError("rung text does not read back to the same logic.")
                lines.append((rung["comment"], text))
            except RllError as exc:
                problems.append(f"{name} rung {i}: {exc}")
        texts[name] = lines
    io_alias = {r.tag: r.address for r in report.rows if r.address and r.address != "UNASSIGNED"}
    types = _tag_types(routines)
    for tag in [*types, *io_alias]:
        if not LOGIX_NAME.match(tag) or "__" in tag or tag.endswith("_"):
            problems.append(f"Tag name '{tag}' is not a legal Studio 5000 name (letters, digits, single "
                            "underscores, 40 characters, not ending in _).")
    if problems:
        raise RllError("L5X not written. Fix these first (nothing was dropped):\n- " + "\n- ".join(problems))
    descs = (project.program or {}).get("tag_descriptions") or {}
    dev_desc = {r.tag: r.description for r in report.rows}
    ctrl = re.sub(r"[^A-Za-z0-9_]", "_", project.name or "Cabinet").strip("_")[:40] or "Cabinet"
    if not ctrl[0].isalpha():
        ctrl = "C_" + ctrl[:38]
    stamp = datetime.now().strftime("%a %b %d %H:%M:%S %Y")
    x: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f"<!-- {DISCLAIMER} {SAFETY_NOTE} -->",
        '<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="33.00" TargetName="MainProgram" '
        f'TargetType="Program" TargetClass="Standard" ContainsContext="true" ExportDate={quoteattr(stamp)} '
        'ExportOptions="References NoRawData L5KData DecoratedData Context Dependencies ForceProtectedEncoding '
        'AllProjDocTrans">',
        f'<Controller Use="Context" Name={quoteattr(ctrl)}>',
        '<DataTypes Use="Context"/>',
        '<Tags Use="Context">',
    ]
    for tag, addr in io_alias.items():
        x.append(f'<Tag Name={quoteattr(tag)} TagType="Alias" Radix="Decimal" AliasFor={quoteattr(addr)} '
                 'ExternalAccess="Read/Write">')
        d = descs.get(tag) or dev_desc.get(tag) or ""
        if d:
            x.append(f"<Description><![CDATA[{_cdata(d)}]]></Description>")
        x.append("</Tag>")
    x += ["</Tags>", '<Programs Use="Context">',
          '<Program Use="Target" Name="MainProgram" TestEdits="false" MainRoutineName="MainRoutine" '
          'Disabled="false" UseAsFolder="false">', "<Tags>"]
    for tag in sorted(types):
        if tag in io_alias:
            continue
        x.append(f'<Tag Name={quoteattr(tag)} TagType="Base" DataType="{types[tag]}" '
                 + ('Radix="Decimal" ' if types[tag] in ("BOOL", "DINT") else "")
                 + 'Constant="false" ExternalAccess="Read/Write">')
        if descs.get(tag):
            x.append(f"<Description><![CDATA[{_cdata(descs[tag])}]]></Description>")
        x.append("</Tag>")
    x += ["</Tags>", "<Routines>"]
    for name, lines in texts.items():
        x += [f'<Routine Name={quoteattr(name)} Type="RLL">', "<RLLContent>"]
        for n, (comment, text) in enumerate(lines):
            x.append(f'<Rung Number="{n}" Type="N">')
            if comment.strip():
                x.append(f"<Comment><![CDATA[{_cdata(comment.strip())}]]></Comment>")
            x.append(f"<Text><![CDATA[{text}]]></Text>")
            x.append("</Rung>")
        x += ["</RLLContent>", "</Routine>"]
    x += ["</Routines>", "</Program>", "</Programs>", "</Controller>", "</RSLogix5000Content>", ""]
    xml = "\n".join(x)
    ET.fromstring(xml.encode("utf-8"))  # well-formed or raise
    return xml


def l5x_rung_texts(xml_text: str) -> dict[str, list[str]]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    return {r.get("Name"): [t.text or "" for t in r.iter("Text")] for r in root.iter("Routine")}


# ----------------------------------------------------------------------------- tag tables

def _csv_text(rows: list[list[str]]) -> str:
    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    return buf.getvalue()


def ab_tag_csv(project: Project, report: IoReport) -> str:
    types = _tag_types(program_routines(project))
    alias = {r.tag: r for r in report.rows if r.address != "UNASSIGNED"}
    rows: list[list[str]] = [
        ["remark", "CSV-Import-Export"], ["remark", f"Date = {datetime.now():%a %b %d %H:%M:%S %Y}"],
        ["remark", "Version = RSLogix 5000 v33.00"], ["remark", DISCLAIMER], ["0.3"],
        ["TYPE", "SCOPE", "NAME", "DESCRIPTION", "DATATYPE", "SPECIFIER", "ATTRIBUTES"],
    ]
    for tag, r in alias.items():
        rows.append(["ALIAS", "", tag, r.description, "", r.address,
                     "(RADIX := Decimal, ExternalAccess := Read/Write)"])
    for tag in sorted(types):
        if tag not in alias:
            rows.append(["TAG", "MainProgram", tag, "", types[tag], "",
                         "(Constant := false, ExternalAccess := Read/Write)"])
    return _csv_text(rows)


def micro800_variables_csv(project: Project, report: IoReport) -> str:
    rows = [["Name", "Data Type", "Alias / I/O variable", "Comment"]]
    for r in report.rows:
        rows.append([r.tag, "BOOL" if r.kind in ("DI", "DO") else "INT", r.address, r.description])
    for tag, dtype in sorted(_tag_types(program_routines(project)).items()):
        if tag not in {r.tag for r in report.rows}:
            rows.append([tag, {"TIMER": "TON", "COUNTER": "CTU"}.get(dtype, dtype), "", ""])
    return _csv_text(rows)


SIEMENS_COLUMNS = ["Name", "Path", "Data Type", "Logical Address", "Comment", "Hmi Visible", "Hmi Accessible",
                   "Hmi Writeable", "Typeobject ID", "Version ID"]


def siemens_tag_csv(report: IoReport) -> str:
    rows = [SIEMENS_COLUMNS]
    for r in report.rows:
        if r.address == "UNASSIGNED":
            continue
        rows.append([r.tag, "Default tag table", "Bool" if r.kind in ("DI", "DO") else "Int", r.address,
                     r.description, "True", "True", "False" if r.kind in ("DI", "AI") else "True", "", ""])
    return _csv_text(rows)


def omron_variables_csv(project: Project, report: IoReport) -> str:
    nx = report.profile is not None and report.profile.family == "omron-nx"
    io_tags = {r.tag for r in report.rows}
    if nx:
        rows = [["Name", "Data Type", "Initial Value", "AT", "Retain", "Constant", "Network Publish", "Comment"]]
        for r in report.rows:
            rows.append([r.tag, "BOOL" if r.kind in ("DI", "DO") else "INT", "", "", "FALSE", "FALSE",
                         "Do not publish", f"{r.description} | I/O Map port: {r.address}".strip(" |")])
        for tag, dtype in sorted(_tag_types(program_routines(project)).items()):
            if tag not in io_tags:
                rows.append([tag, {"TIMER": "TON", "COUNTER": "CTU"}.get(dtype, dtype), "", "", "FALSE", "FALSE",
                             "Do not publish", ""])
        return _csv_text(rows)
    rows = [["Name", "Data Type", "Address/Value", "Comment"]]
    for r in report.rows:
        if r.address != "UNASSIGNED":
            rows.append([r.tag, "BOOL" if r.kind in ("DI", "DO") else "CHANNEL", r.address, r.description])
    return _csv_text(rows)


# ----------------------------------------------------------------------------- README

def readme_text(project: Project, report: IoReport, files: list[str], refused: list[str]) -> str:
    p = report.profile
    head = [
        f"Cabinet Studio PLC export - {project.name}",
        "=" * 60,
        DISCLAIMER,
        "",
        "WHAT THIS IS",
        "These files carry your program, tags and I/O addresses into the PLC maker's software.",
        "Cabinet Studio does NOT download a program into a PLC over the wire. The maker's software",
        "(Studio 5000 / CCW, TIA Portal, Sysmac Studio / CX-Programmer) compiles and downloads it.",
        "Cabinet Studio's 'PLC / Device' window can read and watch tags on a running PLC for testing.",
        "",
        "SAFETY: " + SAFETY_NOTE,
        "Never download, force or write tags while people are at risk. Be at the machine.",
        "",
        f"PLC: {p.tag} - {p.maker} {p.label} {p.catalog}".rstrip() if p else "PLC: none in the cabinet",
        "",
        "FILES",
        *[f"  {f}" for f in files],
        "",
    ]
    if refused:
        head += ["NOT WRITTEN (fix in Cabinet Studio, then export again):", *[f"  {m}" for m in refused], ""]
    if report.shortages:
        head += ["I/O SHORTAGE:", *[f"  {s}" for s in report.shortages], ""]
    steps: list[str] = []
    fam = p.family if p else ""
    if fam == "logix":
        steps = [
            "ALLEN-BRADLEY STUDIO 5000 (CompactLogix / ControlLogix)",
            "1. Open (or create) the controller project in Studio 5000 with the right controller and firmware.",
            "2. In the I/O Configuration tree add every module in the slot shown in io-list.csv (Module column).",
            "3. In the Controller Organizer right-click Tasks > MainTask > Add > Import Program...",
            "4. Pick program.L5X. Accept 'Create' for new tags. If MainProgram already exists, rename on import.",
            "5. Optional: Tools > Import > Tags and Logic Comments, pick ab-tags.csv, to load tags only.",
            "6. Verify the project (Logic > Verify Controller). Fix any red X before downloading.",
            "7. Go online (Communications > Who Active), select the PLC, then Download. Put the PLC in Run",
            "   only when you are at the machine and it is safe.",
        ]
    elif fam == "micro800":
        steps = [
            "ALLEN-BRADLEY CONNECTED COMPONENTS WORKBENCH (Micro800)",
            "1. Create the project in CCW with the controller catalog number and add any plug-ins / expansion I/O.",
            "2. Open micro800-variables.csv. In the program's Local Variables (or Global Variables) grid, create",
            "   each Name with the Data Type and set Alias to the I/O variable (e.g. _IO_EM_DI_00).",
            "3. If your CCW version offers Import > PLCopen XML, import program-plcopen.xml. If not, re-enter",
            "   the rungs from rungs.txt (each line is one rung).",
            "4. Build, connect (Connect / Download), and put the PLC in Run only when it is safe.",
        ]
    elif fam.startswith("s7"):
        steps = [
            "SIEMENS TIA PORTAL",
            "1. Create the project, add the CPU (same order number and firmware) and the signal modules in the",
            "   slots listed in io-list.csv. Check the I/O start addresses match (Device view > Properties).",
            "2. Open siemens-plc-tags.csv in Excel and Save As .xlsx (the columns are TIA's PLC tag table layout:",
            "   Name, Path, Data Type, Logical Address, Comment, Hmi Visible, Hmi Accessible, Hmi Writeable).",
            "3. In the project tree open PLC tags, click the Import button (or right-click > Import), pick the",
            "   .xlsx. Internal (non-I/O) tags go in a global data block - create them there.",
            "4. TIA does not import PLCopen ladder in every version. If 'External source files' > PLCopen XML is",
            "   not offered, re-enter the rungs from rungs.txt in a LAD block (Main [OB1]).",
            "5. Compile, then Download to device. Put the CPU in RUN only when it is safe.",
            "6. S7-1200/1500: for Cabinet Studio to read tags live, enable 'Permit access with PUT/GET' in the",
            "   CPU protection settings (only on a protected machine network).",
        ]
    elif fam.startswith("omron"):
        steps = [
            "OMRON SYSMAC STUDIO (NX/NJ) or CX-PROGRAMMER (CJ/CP)",
            "1. Create the project with the CPU model and add the I/O units in the order listed in io-list.csv.",
            "2. Sysmac Studio: open Global Variables, select the grid, paste the rows from omron-variables.csv",
            "   (copy from Excel). Then open I/O Map and map each variable to the port named in the Comment.",
            "   CX-Programmer: open Symbols and paste the rows (Name, Data Type, Address, Comment).",
            "3. Sysmac Studio may import program-plcopen.xml (File > Import, PLCopen XML) depending on version.",
            "   If not, re-enter the rungs from rungs.txt.",
            "4. Build / compile, Transfer to Controller, and switch to RUN only when it is safe.",
            "5. Live link: Cabinet Studio's Omron link is BETA and reads/writes DM and CIO words over FINS/UDP",
            "   (port 9600). Enable FINS on the CPU's Ethernet port if you want to use it.",
        ]
    tail = ["", "I/O LIST: io-list.csv lists every input and output, its address, module, terminal and wire #.",
            "The same list is printed as the I/O LIST drawing sheet after the Wire Schedule.", ""]
    return "\r\n".join(head + steps + tail)


# ----------------------------------------------------------------------------- write

@dataclass
class ExportResult:
    folder: Path
    files: list[Path] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    report: IoReport | None = None

    def summary(self) -> str:
        lines = [f"Wrote {len(self.files)} file(s) to {self.folder}"]
        lines += [f"  {f.name}" for f in self.files]
        if self.refused:
            lines += ["Not written:", *[f"  {m}" for m in self.refused]]
        return "\n".join(lines)


def export_folder(project: Project, save_path: Path | str | None = None, sub: str = "plc") -> Path:
    from cabinet_studio.services.drawings import default_drawings_folder

    return Path(default_drawings_folder(project, save_path)) / sub


def write_plc_exports(project: Project, folder: Path | str | None = None, *, plc_id: str | None = None,
                      save_path: Path | str | None = None) -> ExportResult:
    from cabinet_studio.services.io_assign import write_io_csv
    from cabinet_studio.services.plcopen_xml import export_program_to_plcopen_xml
    from cabinet_studio.services.programming import cabinet_device_tags, format_plc_text, program_from_dict

    target = Path(folder) if folder else export_folder(project, save_path)
    target.mkdir(parents=True, exist_ok=True)
    report = assign_io(project, plc_id, write=False)
    result = ExportResult(target, report=report)
    if report.profile is None:
        result.refused.append("No PLC in the cabinet. Add a PLC first.")
        return result

    def put(name: str, text: str) -> None:
        path = target / name
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        result.files.append(path)

    result.files.append(write_io_csv(report, target / "io-list.csv"))
    data = program_from_dict(project.program if isinstance(project.program, dict) else {})
    devices = cabinet_device_tags(project)
    put("rungs.txt", f"{DISCLAIMER}\r\n{SAFETY_NOTE}\r\n\r\n" + format_plc_text(data["rungs"], devices))
    fam = report.profile.family
    if fam == "logix":
        try:
            put("program.L5X", build_l5x(project, plc_id, report=report))
        except RllError as exc:
            result.refused.append(str(exc))
        put("ab-tags.csv", ab_tag_csv(project, report))
    else:
        try:
            put("program-plcopen.xml", export_program_to_plcopen_xml(
                project.program, project_name=project.name, devices=devices))
        except Exception as exc:  # the PLCopen writer refuses on its own rules
            result.refused.append(f"PLCopen XML: {exc}")
        if fam == "micro800":
            put("micro800-variables.csv", micro800_variables_csv(project, report))
        elif fam.startswith("s7"):
            put("siemens-plc-tags.csv", siemens_tag_csv(report))
        elif fam.startswith("omron"):
            put("omron-variables.csv", omron_variables_csv(project, report))
    readme = readme_text(project, report, [f.name for f in result.files] + ["README.txt"], result.refused)
    put("README.txt", readme)
    return result


def write_hmi_exports(project: Project, folder: Path | str | None = None, *,
                      save_path: Path | str | None = None) -> ExportResult:
    """HMI: the tag table from the saved HMI design + plain import steps for the HMI software."""
    from cabinet_studio.services import hmi_design as hd

    target = Path(folder) if folder else export_folder(project, save_path, "hmi")
    target.mkdir(parents=True, exist_ok=True)
    result = ExportResult(target)
    design = hd.load_design(project)
    if design is None:
        result.refused.append("No HMI design saved on this cabinet. Open the HMI editor and Save a design first.")
        return result
    rows = hd.tag_table(design, project)
    path = target / "hmi-tags.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        keys = list(rows[0].keys()) if rows else ["tag"]
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    result.files.append(path)
    readme = "\r\n".join([
        f"Cabinet Studio HMI export - {project.name}", "=" * 60, DISCLAIMER, "",
        "Cabinet Studio does NOT download screens into an HMI. Build and download the HMI runtime with the",
        "maker's software: FactoryTalk View ME / Optix (Allen-Bradley PanelView), WinCC in TIA Portal",
        "(Siemens Comfort/Basic panels), Sysmac Studio or NB-Designer (Omron NA/NB).", "",
        "1. Create the HMI project with the panel model shown on the HMI drawing sheets.",
        "2. Add the PLC connection (driver and IP address from the cabinet).",
        "3. Create each tag in hmi-tags.csv (most HMI tools import tags from CSV/Excel), pointing at the",
        "   PLC tag or address in the same row.",
        "4. Draw the screens from the HMI SCREEN LAYOUT drawing sheets, then download from the HMI software.",
        "", "SAFETY: " + SAFETY_NOTE, "HMI buttons are never a safety function. E-stop stays hard-wired.", ""])
    rp = target / "README.txt"
    with rp.open("w", encoding="utf-8", newline="") as fh:
        fh.write(readme)
    result.files.append(rp)
    return result


def device_choices(project: Project) -> list[tuple[str, PlacedItem]]:
    """(label, item) for every PLC and HMI in the cabinet."""
    out: list[tuple[str, PlacedItem]] = []
    for item in project.items:
        if item.type_id not in ("plc", "hmi"):
            continue
        tag = (item.fields.get("tag") or item.id).strip()
        kind = "PLC" if item.type_id == "plc" else "HMI"
        extra = detect_profile(item).label if item.type_id == "plc" else (item.fields.get("vendor") or "").strip()
        out.append((f"{kind} {tag} - {extra}".rstrip(" -"), item))
    return out


__all__ = ["RllError", "element_to_rll", "elements_to_rll", "parse_rll", "canonical", "build_l5x",
           "l5x_rung_texts", "write_plc_exports", "write_hmi_exports", "device_choices", "selected_plc"]
