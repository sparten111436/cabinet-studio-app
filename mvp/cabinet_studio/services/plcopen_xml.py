"""PLCopen XML (IEC 61131-10 / TC6-style) interchange for Cabinet Studio ladder IR.

Educational subset: project → types → POUs → LD with left/right power rails,
contacts, coils, TON/TOF/RTO blocks, CTU/CTD counter blocks, and simple OR via
parallel connection points.

Not a full schema validator. Round-trips through our IR (contacts, coils,
parallel OR, timers with PT, counters with PV). External tools (Beremiz /
CODESYS / CCW) may open exports with varying fidelity.

Counters (v0.3.3): CTU → IEC CTU block (CU, RESET, PV → Q, CV); CTD → IEC CTD
block (CD, LOAD, PV → Q, CV). RES / LOAD rungs are written as small
``RES`` / ``LOAD`` blocks (Cabinet Studio educational extension; in CCW wire
that rung to the CTU RESET / CTD LOAD pin). Contacts on ``C1.DN`` export as
``C1.Q`` (IEC member) and import back as ``C1.DN``.

v0.3.5: nested OR, mid-rung, compare/math, OTL/OTU round-trip in educational LD.
v0.3.12: series-aware OR import (pure XML, no embed required); G-AID safety note in Comment.
v0.3.13: hint-less import keeps compare/math blocks; nested OR in OR branch; UL line in Comment.
v0.3.14: CPT expr parses full expression (or refuses); nested OR continues after join; UL on appendix continuations.
v0.3.15: REG-5 — hint-less nested-OR continuation only consumes a node when every predecessor is the nested branch's own end; outer series (Stop/interlock) stays outside the OR.
v0.3.16: H-DEEP — hint-less import rebuilds any OR depth (dominator series-parallel
  decomposition, plcopen_graph.py) and VERIFIES every rung against the LD wiring with a
  truth table; any mismatch refuses the whole import (ValueError, nothing imported).
  A Cabinet Studio hint is trusted only if it still matches the wiring. Visible import warning.
v0.3.17: NEW-1 guard model fixed (blocks gated by input power on both sides); NEW-3 the hint
  carries a hash of each rung's wiring ("wh") and every coil form / block setting is compared
  with the wiring — on any mismatch the hint is ignored for that rung, the rung is rebuilt
  from the wiring, verified, and a warning names the rung; NEW-2 exact BDD above 20 inputs
  (never sampled); NEW-4 no-left-rail files are verified [0.3.19: refused]; NEW-5 empty / malformed CPT
  imports verbatim (Verify error, sim blocked) instead of crashing; NEW-6 cross-rung wires
  refuse; non-PLCopen documents and files with no LD rungs are refused.
v0.3.19: account for every REFERENCE; never guess. A body with LD objects but no left rail
  refuses (the 0.3.17 NEW-4 rail recovery is gone — a deleted first Stop / E-stop contact
  looks the same); a wire to a missing localId, a duplicate localId, a wire out of a right
  rail, a powered contact or condition block (compare / ONS) that drives no coil / block
  (dead end) and a one-shot whose noted output coil is not wired to its Q all refuse the
  whole file, naming rung + object. TIME presets above T#24d20h31m23s647ms (2,147,483,647 ms)
  refuse. Look-alike / non-identifier tag names import with one warning per tag.
  Strict TC6 allowlist (``check_tc6_vocabulary``): every attribute / element / block typeName
  / pin / pin flag is modelled exactly, whitelisted as cosmetic, or refused by name (edge,
  negated pins, unknown typeNames incl. CTUD and IEC operator names, jumps / labels /
  connectors, extra POUs, retain lists, address aliasing, wires taking ET / ACC ...).

v0.3.6:
- Rung comments export as TC6 ``<comment>`` objects (xhtml content) placed
  before each rung's left rail; multi-line text is preserved. Import reads them
  back (falls back to the legacy first-contact documentation).
- One-shots: ONS → IEC ``R_TRIG`` (instance = storage bit, CLK = rung power,
  rung continues from Q). OSR / OSF → ``R_TRIG`` / ``F_TRIG`` whose Q drives
  a coil on the output bit (power passes through). Documentation carries
  ``ONESHOT <ONS|OSR|OSF> storage=… output=…`` for lossless return.
- Instruction notes (``desc``) export as ``note: …`` documentation on each
  contact / coil / block and import back onto the element.
Gaps: full schema validation; foreign R_TRIG/F_TRIG without our doc map to
ONS / OSF best-effort.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any
from xml.dom import minidom

from cabinet_studio.services.ladder_ir import (
    COUNTER_BLOCKS,
    COUNTER_OWNER_BLOCKS,
    IR_DIALECT,
    IR_FORMAT,
    IR_VERSION,
    clamp_counter,
    empty_ladder,
    normalize_counter_block,
    normalize_ladder_ir,
    program_to_ladder_ir,
    split_member,
)

TIMER_TYPES = {"TON", "TOF", "RTO"}
COUNTER_TYPES = set(COUNTER_OWNER_BLOCKS) | {"CTUD"}
COUNTER_ACTION_TYPES = {"RES", "LOAD"}
# v0.3.7: elementary numeric types for described compare / math operands.
NUMERIC_TYPES = {"INT", "DINT", "UINT", "REAL", "LREAL"}


NS = "http://www.plcopen.org/xml/tc6_0201"
XHTML_NS = "http://www.w3.org/1999/xhtml"
ET.register_namespace("", NS)
ET.register_namespace("xhtml", XHTML_NS)
ONESHOT_TYPES = {"R_TRIG", "F_TRIG", "ONS", "OSR", "OSF"}
NOTE_PREFIX = "note: "

# v0.3.16 (also back-ported to the 0.3.15 RC tree): shown on every PLCopen import.
PLCOPEN_IMPORT_WARNING = (
    "CHECK BY HAND: imported PLCopen logic (especially third-party files) may not match the "
    "source exactly. Compare every rung with the original before use. Design aid only."
)


def _el(tag: str, attrib: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    node = ET.Element(f"{{{NS}}}{tag}", attrib or {})
    if text is not None:
        node.text = text
    return node


def _sub(parent: ET.Element, tag: str, attrib: dict[str, str] | None = None, text: str | None = None) -> ET.Element:
    node = ET.SubElement(parent, f"{{{NS}}}{tag}", attrib or {})
    if text is not None:
        node.text = text
    return node



def _xhtml_doc(parent: ET.Element, text: str | None) -> ET.Element | None:
    """Attach TC6 formattedText documentation (single xhtml <p>)."""
    raw = (text or "").strip()
    if not raw:
        return None
    doc = _sub(parent, "documentation")
    para = ET.SubElement(doc, f"{{{XHTML_NS}}}p")
    para.text = raw
    return doc


def _read_doc_text(node: ET.Element | None) -> str:
    """Read plain or xhtml documentation text from a node."""
    if node is None:
        return ""
    doc = None
    for c in list(node):
        if _local(c.tag) == "documentation":
            doc = c
            break
    if doc is None:
        return ""
    # Prefer concatenated text from xhtml children; fall back to doc.text
    parts: list[str] = []
    for child in list(doc):
        t = "".join(child.itertext()).strip()
        if t:
            parts.append(t)
    if parts:
        return "\n".join(parts)
    return (doc.text or "").strip()


def _var_name_from_node(node: ET.Element) -> str:
    """Contact/coil variable: prefer child <variable>, fall back to attribute (legacy)."""
    for c in list(node):
        if _local(c.tag) == "variable":
            return (c.text or "").strip()
    return str(node.get("variable") or "").strip()

def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


# v0.3.17 NEW-3: attributes that are layout / identity only (not part of the logic hash).
_HASH_SKIP_ATTRS = {"localId", "refLocalId", "x", "y", "width", "height", "executionOrderId"}


def _rung_object_list(children: list[ET.Element], left_id: str) -> list[ET.Element]:
    """Objects reachable from one left rail (incl. the rail), in document order."""
    by_id: dict[str, ET.Element] = {}
    order: dict[str, int] = {}
    forward: dict[str, list[str]] = {}
    for i, child in enumerate(children):
        lid = child.get("localId")
        if not lid:
            continue
        by_id[lid] = child
        order[lid] = i
        for cpi in child.iter():
            if _local(cpi.tag) == "connection" and cpi.get("refLocalId"):
                forward.setdefault(str(cpi.get("refLocalId")), []).append(lid)
    seen: set[str] = set()
    stack = [left_id]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id:
            continue
        seen.add(cur)
        stack.extend(forward.get(cur) or [])
    return [by_id[n] for n in sorted(seen, key=lambda n: order[n])]


def rung_wiring_hash(objs: list[ET.Element]) -> str:
    """v0.3.17 NEW-3: hash of one rung's LD body (objects, wiring, coil forms, block
    parameters / documentation). Independent of localId numbering and layout; the left
    rail's own documentation (the Cabinet Studio hint) is excluded."""
    import hashlib

    idx = {str(o.get("localId")): i for i, o in enumerate(objs)}

    def walk(e: ET.Element, depth: int, is_left: bool) -> Any:
        tag = _local(e.tag)
        if tag == "position":
            return None
        if is_left and depth == 1 and tag == "documentation":
            return None
        attrs = sorted(
            (_local(k), str(v)) for k, v in e.attrib.items() if _local(k) not in _HASH_SKIP_ATTRS
        )
        if tag == "connection":
            attrs.append(("ref", str(idx.get(str(e.get("refLocalId")), "?"))))
        kids = [k for k in (walk(c, depth + 1, is_left) for c in list(e)) if k is not None]
        return [tag, attrs, (e.text or "").strip(), kids]

    canon = [walk(o, 0, _local(o.tag) == "leftPowerRail") for o in objs]
    blob = json.dumps(canon, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


class PLCopenDocumentError(ValueError):
    """v0.3.17: the file is not a PLCopen LD project Cabinet Studio can import (nothing imported)."""


def validate_plcopen_document(xml_text: str) -> None:
    """v0.3.17: refuse non-PLCopen XML BEFORE anything is replaced.

    Refuses: empty file, not well-formed XML, wrong root element or namespace, no POU,
    no LD (Ladder Diagram) body. Raises :class:`PLCopenDocumentError` (a ValueError).
    """
    text = (xml_text or "").strip()
    if not text:
        raise PLCopenDocumentError(
            "PLCopen import refused: the file is empty. Nothing was imported."
        )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise PLCopenDocumentError(
            f"PLCopen import refused: the file is not well-formed XML ({exc}). Nothing was imported."
        ) from None
    tag = str(root.tag)
    ns = tag[1:].split("}", 1)[0] if tag.startswith("{") else ""
    if _local(tag) != "project" or not ns.startswith("http://www.plcopen.org/xml/tc6"):
        raise PLCopenDocumentError(
            "PLCopen import refused: this is not a PLCopen TC6 XML project (root element "
            f"<{_local(tag)}>{' in namespace ' + ns if ns else ' with no namespace'}; expected "
            "<project> in http://www.plcopen.org/xml/tc6_0201). Nothing was imported."
        )
    pous = [n for n in root.iter() if _local(n.tag) == "pou"]
    if not pous:
        raise PLCopenDocumentError(
            "PLCopen import refused: the project has no POU (program). Nothing was imported."
        )
    if not any(_local(n.tag) == "LD" for n in root.iter()):
        raise PLCopenDocumentError(
            "PLCopen import refused: the project has no Ladder Diagram (LD) body — Cabinet Studio "
            "imports LD only (not ST / FBD / SFC / IL). Nothing was imported."
        )


def ladder_ir_to_plcopen_xml(ladder: dict[str, Any], *, pou_name: str = "Main") -> str:
    """Serialize ladder IR to a PLCopen TC6-ish XML string."""
    ladder = normalize_ladder_ir(ladder)
    project = _el("project")
    file_header = _sub(project, "fileHeader")
    file_header.set("companyName", "Cabinet Studio")
    file_header.set("productName", "Cabinet Studio Educational Ladder")
    file_header.set("productVersion", f"v{IR_VERSION}")
    file_header.set("creationDateTime", "2026-10-05T00:00:00")

    content = _sub(project, "contentHeader", {"name": str((ladder.get("meta") or {}).get("project") or "CabinetStudio")})
    # Comment must precede coordinateInfo per TC6 v2.01 (filled later if routines/aliases).
    comment_slot = _sub(content, "Comment")
    coord = _sub(content, "coordinateInfo")
    for dialect in ("fbd", "ld", "sfc"):
        d = _sub(coord, dialect)
        _sub(d, "scaling", {"x": "1", "y": "1"})

    types = _sub(project, "types")
    _sub(types, "dataTypes")  # required empty container
    pous = _sub(types, "pous")
    pou = _sub(pous, "pou", {"name": pou_name or "Main", "pouType": "program"})
    interface = _sub(pou, "interface")
    input_vars = _sub(interface, "inputVars")
    output_vars = _sub(interface, "outputVars")
    local_vars = _sub(interface, "localVars")

    fb_kind: dict[str, str] = {}
    for var in ladder.get("variables") or []:
        cls = str(var.get("class") or "").lower()
        if cls in {"timer", "counter"} and var.get("name"):
            fb_kind[str(var["name"])] = cls
    for rung in ladder.get("rungs") or []:
        for el in rung.get("elements") or []:
            k = str(el.get("kind") or "").lower()
            if k in {"timer", "counter"} and el.get("var"):
                fb_kind.setdefault(str(el["var"]), k)

    def export_var_name(tag: str) -> str:
        """C1.DN → C1.Q (IEC FB output) for timer / counter instances."""
        base, member = split_member(tag)
        if member == "DN" and base in fb_kind:
            return f"{base}.Q"
        return tag

    for var in ladder.get("variables") or []:
        name = str(var.get("name") or "").strip()
        if not name:
            continue
        cls = str(var.get("class") or "internal").lower()
        parent = input_vars if cls == "input" else output_vars if cls == "output" else local_vars
        addr = str(var.get("address") or "").strip()
        var_attrs = {"name": name}
        if addr:
            var_attrs["address"] = addr
        variable = _sub(parent, "variable", var_attrs)
        vtype = _sub(variable, "type")
        v_ty = str(var.get("type") or "BOOL").upper()
        desc = str(var.get("description") or "").strip()
        # initialValue for numeric / BOOL where we have a value
        init_raw = var.get("value", var.get("initial", None))
        def _write_init(simple: str) -> None:
            iv = _sub(variable, "initialValue")
            _sub(iv, "simpleValue", {"value": simple})
        if cls == "timer" or v_ty in {"TON", "TOF", "RTO"}:
            _sub(vtype, "derived", {"name": v_ty if v_ty in {"TON", "TOF", "RTO"} else "TON"})
            pt = var.get("pt_ms")
            doc = ""
            if pt is not None:
                doc = f"pt_ms={int(pt)}" + (f"\n{desc}" if desc else "")
            elif desc:
                doc = desc
            _xhtml_doc(variable, doc)
        elif cls == "counter" or v_ty in COUNTER_OWNER_BLOCKS:
            _sub(vtype, "derived", {"name": v_ty if v_ty in COUNTER_OWNER_BLOCKS else "CTU"})
            _xhtml_doc(variable, f"pv={clamp_counter(var.get('pv', 0))}" + (f"\n{desc}" if desc else ""))
        elif cls == "numeric" or v_ty in NUMERIC_TYPES:
            _sub(vtype, v_ty if v_ty in NUMERIC_TYPES else "REAL")
            if init_raw is not None and str(init_raw) != "":
                try:
                    _write_init(str(float(init_raw) if v_ty in {"REAL", "LREAL"} else int(float(init_raw))))
                except (TypeError, ValueError):
                    _write_init(str(init_raw))
            _xhtml_doc(variable, desc)
        else:
            _sub(vtype, "BOOL")
            if init_raw is not None and str(init_raw).lower() in {"1", "true", "yes"}:
                _write_init("TRUE")
            elif init_raw is not None and str(init_raw).lower() in {"0", "false", "no"}:
                _write_init("FALSE")
            _xhtml_doc(variable, desc)

    body = _sub(pou, "body")
    ld = _sub(body, "LD")

    local_id = 0

    def next_id() -> str:
        nonlocal local_id
        local_id += 1
        return str(local_id)

    def emit_rungs(ld: ET.Element, rung_list: list[dict[str, Any]]) -> None:
        for rung in rung_list or []:
            comment = (rung.get("comment") or "").strip()
            elements = list(rung.get("elements") or [])
            if comment:
                cmt = _sub(ld, "comment", {"localId": next_id(), "height": "40", "width": "600"})
                _sub(cmt, "position", {"x": "0", "y": "0"})
                content_el = _sub(cmt, "content")
                # TC6 formattedText allows one xhtml child — keep multi-line in a single <p>.
                para = ET.SubElement(content_el, f"{{{XHTML_NS}}}p")
                para.text = comment
            left_id = next_id()
            left = _sub(ld, "leftPowerRail", {"localId": left_id})
            pos = _sub(left, "position", {"x": "0", "y": "0"})
            _ = pos
            conn_point_out = _sub(left, "connectionPointOut", {"formalParameter": ""})
            _ = conn_point_out
            # Educational lossless hint for nested OR / mid-rung coils (ignored by most tools).
            # v0.3.17: written AFTER the rung body so it can carry the wiring hash ("wh").
            left_index = len(list(ld)) - 1

            prev_ids = [left_id]
            x = 1
            prev_param = ""  # formalParameter of the previous block output (Q)

            def emit_contact(el, y=0, doc=""):
                nonlocal x, prev_ids, prev_param
                cid = next_id()
                form = str(el.get("form") or "NO").upper()
                contact = _sub(
                    ld,
                    "contact",
                    {
                        "localId": cid,
                        "negated": "true" if form == "NC" else "false",
                    },
                )
                _sub(contact, "position", {"x": str(x * 100), "y": str(y)})
                c_in = _sub(contact, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                _sub(contact, "connectionPointOut")
                _sub(contact, "variable", text=export_var_name(str(el.get("var") or "")))
                if el.get("desc"):
                    _xhtml_doc(contact, f"{NOTE_PREFIX}{el.get('desc')}")
                prev_ids = [cid]
                prev_param = ""
                x += 1
                return cid

            def emit_timer(el):
                nonlocal x, prev_ids, prev_param
                cid = next_id()
                block_name = str(el.get("block") or "TON").upper()
                if block_name not in {"TON", "TOF", "RTO"}:
                    block_name = "TON"
                instance = str(el.get("var") or "").strip()
                pt_ms = max(0, int(el.get("pt_ms") or 0))
                pt_tag = str(el.get("pt_tag") or "").strip()
                if pt_tag:
                    # v0.3.18 NEW-9: preset read from a tag at run time (IEC: PT := tag).
                    pt_expr = pt_tag
                elif pt_ms >= 1000 and pt_ms % 1000 == 0:
                    pt_expr = f"T#{pt_ms // 1000}s"
                else:
                    pt_expr = f"T#{pt_ms}ms"
                block = _sub(
                    ld,
                    "block",
                    {"localId": cid, "typeName": block_name, "instanceName": instance},
                )
                _sub(block, "position", {"x": str(x * 100), "y": "0"})
                in_vars = _sub(block, "inputVariables")
                in_in = _sub(in_vars, "variable", {"formalParameter": "IN"})
                c_in = _sub(in_in, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                in_pt = _sub(in_vars, "variable", {"formalParameter": "PT"})
                c_pt = _sub(in_pt, "connectionPointIn")
                _sub(c_pt, "expression", text=pt_expr)
                _sub(block, "inOutVariables")
                out_vars = _sub(block, "outputVariables")
                out_q = _sub(out_vars, "variable", {"formalParameter": "Q"})
                _sub(out_q, "connectionPointOut")
                out_et = _sub(out_vars, "variable", {"formalParameter": "ET"})
                _sub(out_et, "connectionPointOut")
                _xhtml_doc(
                    block,
                    (f"TIMER {block_name} pt_tag={pt_tag}" if pt_tag else f"TIMER {block_name} pt_ms={pt_ms}")
                    + (f" | {NOTE_PREFIX}{el.get('desc')}" if el.get("desc") else ""),
                )
                prev_ids = [cid]
                prev_param = "Q"
                x += 1

            def emit_counter(el):
                nonlocal x, prev_ids, prev_param
                cid = next_id()
                block_name = normalize_counter_block(el.get("block"))
                instance = str(el.get("var") or "").strip()
                pv = clamp_counter(el.get("pv", 0))
                pv_tag = str(el.get("pv_tag") or "").strip()
                block = _sub(
                    ld,
                    "block",
                    {"localId": cid, "typeName": block_name, "instanceName": instance},
                )
                _sub(block, "position", {"x": str(x * 100), "y": "0"})
                in_vars = _sub(block, "inputVariables")
                if block_name in COUNTER_OWNER_BLOCKS:
                    count_pin = "CU" if block_name == "CTU" else "CD"
                    aux_pin = "RESET" if block_name == "CTU" else "LOAD"
                else:
                    count_pin = "EN"
                    aux_pin = ""
                pin = _sub(in_vars, "variable", {"formalParameter": count_pin})
                c_in = _sub(pin, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                if aux_pin:
                    aux = _sub(in_vars, "variable", {"formalParameter": aux_pin})
                    _sub(_sub(aux, "connectionPointIn"), "expression", text="FALSE")
                    pv_pin = _sub(in_vars, "variable", {"formalParameter": "PV"})
                    _sub(_sub(pv_pin, "connectionPointIn"), "expression", text=pv_tag or str(pv))
                _sub(block, "inOutVariables")
                out_vars = _sub(block, "outputVariables")
                if block_name in COUNTER_OWNER_BLOCKS:
                    out_q = _sub(out_vars, "variable", {"formalParameter": "Q"})
                    _sub(out_q, "connectionPointOut")
                    out_cv = _sub(out_vars, "variable", {"formalParameter": "CV"})
                    _sub(out_cv, "connectionPointOut")
                    doc = f"COUNTER {block_name} pv_tag={pv_tag}" if pv_tag else f"COUNTER {block_name} pv={pv}"
                    prev_param = "Q"
                else:
                    out_eno = _sub(out_vars, "variable", {"formalParameter": "ENO"})
                    _sub(out_eno, "connectionPointOut")
                    doc = (
                        f"COUNTER {block_name} pv={pv} (Cabinet Studio educational extension: "
                        f"in CCW wire this rung to the {'CTU RESET' if block_name == 'RES' else 'CTD LOAD'} pin of {instance})"
                    )
                    prev_param = "ENO"
                if el.get("desc"):
                    doc += f" | {NOTE_PREFIX}{el.get('desc')}"
                _xhtml_doc(block, doc)
                prev_ids = [cid]
                x += 1

            def emit_coil(el):
                nonlocal x, prev_ids, prev_param
                cid = next_id()
                form = str(el.get("form") or "normal").lower()
                attrib = {"localId": cid}
                if form in {"negated", "not", "nc"}:
                    attrib["negated"] = "true"
                if form in {"set", "s"}:
                    attrib["storage"] = "set"
                if form in {"reset", "r"}:
                    attrib["storage"] = "reset"
                coil = _sub(ld, "coil", attrib)
                _sub(coil, "position", {"x": str(x * 100), "y": "0"})
                c_in = _sub(coil, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                # Mid-rung coils expose an out point so later contacts can attach.
                _sub(coil, "connectionPointOut")
                _sub(coil, "variable", text=str(el.get("var") or ""))
                if el.get("desc"):
                    _xhtml_doc(coil, f"{NOTE_PREFIX}{el.get('desc')}")
                prev_ids = [cid]
                prev_param = ""
                x += 1

            def emit_or(el, y_base=0):
                nonlocal x, prev_ids, prev_param
                branch_out_ids = []
                fan_in = list(prev_ids)
                fan_param = prev_param
                max_depth = 1
                for bi, branch in enumerate(el.get("branches") or []):
                    prev_ids = list(fan_in)
                    prev_param = fan_param
                    branch_x_start = x
                    for item in branch or []:
                        kind = (item.get("kind") or "").lower()
                        if kind == "contact":
                            emit_contact(item, y=y_base + bi * 50)
                        elif kind == "or":
                            emit_or(item, y_base=y_base + bi * 50)
                        elif kind == "coil":
                            emit_coil(item)
                        elif kind == "timer":
                            emit_timer(item)
                        elif kind == "counter":
                            emit_counter(item)
                        elif kind == "compare":
                            emit_compare(item)
                        elif kind == "math":
                            emit_math(item)
                        elif kind == "oneshot":
                            emit_oneshot(item)
                        elif kind in {"jsr", "sbr", "ret"}:
                            emit_subroutine(item)
                    branch_out_ids.extend(prev_ids)
                    max_depth = max(max_depth, x - branch_x_start)
                prev_ids = branch_out_ids or fan_in
                prev_param = ""
                # x already advanced by branch contacts; ensure at least +1 for the OR column
                if not branch_out_ids:
                    x += 1

            def emit_compare(el):
                nonlocal x, prev_ids, prev_param
                cid = next_id()
                op = str(el.get("op") or "EQU").upper()
                a = str(el.get("source_a") or "")
                b = str(el.get("source_b") or "")
                c = str(el.get("source_c") or "")
                block = _sub(ld, "block", {"localId": cid, "typeName": op, "instanceName": f"{op}_{x}"})
                _sub(block, "position", {"x": str(x * 100), "y": "0"})
                in_vars = _sub(block, "inputVariables")
                in_en = _sub(in_vars, "variable", {"formalParameter": "EN"})
                c_in = _sub(in_en, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                in1 = _sub(in_vars, "variable", {"formalParameter": "IN1"})
                c1 = _sub(in1, "connectionPointIn")
                _sub(c1, "expression", text=a)
                in2 = _sub(in_vars, "variable", {"formalParameter": "IN2"})
                c2 = _sub(in2, "connectionPointIn")
                _sub(c2, "expression", text=b)
                if op in {"LIM", "MEQ"} or c:
                    in3 = _sub(in_vars, "variable", {"formalParameter": "IN3"})
                    c3 = _sub(in3, "connectionPointIn")
                    _sub(c3, "expression", text=c)
                _sub(block, "inOutVariables")
                out_vars = _sub(block, "outputVariables")
                out_eno = _sub(out_vars, "variable", {"formalParameter": "ENO"})
                _sub(out_eno, "connectionPointOut")
                doc = f"COMPARE {op} {a} {b}" + (f" {c}" if c else "")
                _xhtml_doc(block, doc + (f" | {NOTE_PREFIX}{el.get('desc')}" if el.get("desc") else ""))
                prev_ids = [cid]
                prev_param = "ENO"
                x += 1

            def emit_math(el):
                nonlocal x, prev_ids, prev_param
                cid = next_id()
                op = str(el.get("op") or "ADD").upper()
                dest = str(el.get("dest") or "")
                a = str(el.get("source_a") or "")
                b = str(el.get("source_b") or "")
                expr = str(el.get("expression") or "")
                block = _sub(
                    ld,
                    "block",
                    {"localId": cid, "typeName": op, "instanceName": dest or f"{op}_{x}"},
                )
                _sub(block, "position", {"x": str(x * 100), "y": "0"})
                in_vars = _sub(block, "inputVariables")
                in_en = _sub(in_vars, "variable", {"formalParameter": "EN"})
                c_in = _sub(in_en, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                in1 = _sub(in_vars, "variable", {"formalParameter": "IN1"})
                c1 = _sub(in1, "connectionPointIn")
                _sub(c1, "expression", text=(a if op != "CPT" else (expr or a)))
                if op not in {"MOV", "CPT", "NOT"}:
                    in2 = _sub(in_vars, "variable", {"formalParameter": "IN2"})
                    c2 = _sub(in2, "connectionPointIn")
                    _sub(c2, "expression", text=b)
                _sub(block, "inOutVariables")
                out_vars = _sub(block, "outputVariables")
                out_eno = _sub(out_vars, "variable", {"formalParameter": "ENO"})
                _sub(out_eno, "connectionPointOut")
                # v0.3.14: keep expr LAST so import can take the remainder (spaces in CPT).
                _math_doc = f"MATH {op} dest={dest} a={a} b={b}"
                if expr:
                    _math_doc += f" expr={expr}"
                if el.get("desc"):
                    _math_doc += f" | {NOTE_PREFIX}{el.get('desc')}"
                _xhtml_doc(block, _math_doc)
                prev_ids = [cid]
                prev_param = "ENO"
                x += 1

            def emit_oneshot(el):
                nonlocal x, prev_ids, prev_param
                from cabinet_studio.services.ladder_ir import normalize_oneshot_block

                blk = normalize_oneshot_block(el.get("block"))
                storage = str(el.get("var") or "").strip()
                output = str(el.get("output") or "").strip()
                iec = "F_TRIG" if blk == "OSF" else "R_TRIG"
                cid = next_id()
                block = _sub(ld, "block", {"localId": cid, "typeName": iec, "instanceName": storage or f"{blk}_{x}"})
                _sub(block, "position", {"x": str(x * 100), "y": "0"})
                in_vars = _sub(block, "inputVariables")
                clk = _sub(in_vars, "variable", {"formalParameter": "CLK"})
                c_in = _sub(clk, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                _sub(block, "inOutVariables")
                out_vars = _sub(block, "outputVariables")
                out_q = _sub(out_vars, "variable", {"formalParameter": "Q"})
                _sub(out_q, "connectionPointOut")
                doc = f"ONESHOT {blk} storage={storage}" + (f" output={output}" if output else "")
                _xhtml_doc(block, doc)
                x += 1
                if blk == "ONS":
                    prev_ids = [cid]
                    prev_param = "Q"
                    return
                # OSR / OSF: Q drives the output bit coil; rung power passes through.
                if output:
                    oid = next_id()
                    coil = _sub(ld, "coil", {"localId": oid})
                    _sub(coil, "position", {"x": str(x * 100), "y": "50"})
                    _sub(_sub(coil, "connectionPointIn"), "connection", {"refLocalId": cid, "formalParameter": "Q"})
                    _sub(coil, "connectionPointOut")
                    _sub(coil, "variable", text=output)
                    _xhtml_doc(coil, f"ONESHOT-OUTPUT of {blk} {storage}")

            def emit_subroutine(el):
                """Educational JSR / SBR / RET boxes (not standard IEC LD — CS extension)."""
                nonlocal x, prev_ids, prev_param
                kind = str(el.get("kind") or "").lower()
                cid = next_id()
                if kind == "jsr":
                    type_name, label = "JSR", str(el.get("target") or "")
                elif kind == "sbr":
                    type_name, label = "SBR", str(el.get("name") or "")
                else:
                    type_name, label = "RET", ""
                block = _sub(
                    ld, "block",
                    {"localId": cid, "typeName": type_name, "instanceName": label or type_name},
                )
                _sub(block, "position", {"x": str(x * 100), "y": "0"})
                in_vars = _sub(block, "inputVariables")
                pin = _sub(in_vars, "variable", {"formalParameter": "EN"})
                c_in = _sub(pin, "connectionPointIn")
                for pid in prev_ids:
                    attrs = {"refLocalId": pid}
                    if prev_param:
                        attrs["formalParameter"] = prev_param
                    _sub(c_in, "connection", attrs)
                _sub(block, "inOutVariables")
                out_vars = _sub(block, "outputVariables")
                out_eno = _sub(out_vars, "variable", {"formalParameter": "ENO"})
                _sub(out_eno, "connectionPointOut")
                doc = f"SUBROUTINE {type_name}" + (f" {label}" if label else "")
                if el.get("desc"):
                    doc += f" | {NOTE_PREFIX}{el.get('desc')}"
                _xhtml_doc(block, doc)
                prev_ids = [cid]
                prev_param = "ENO"
                x += 1
                return cid

            def emit_element(el, y=0):
                kind = (el.get("kind") or "").lower()
                if kind == "oneshot":
                    emit_oneshot(el)
                    return
                if kind == "contact":
                    emit_contact(el, y=y, doc=(comment if (y == 0 and x == 1) else ""))
                elif kind == "or":
                    emit_or(el, y_base=y)
                elif kind == "timer":
                    emit_timer(el)
                elif kind == "counter":
                    emit_counter(el)
                elif kind == "compare":
                    emit_compare(el)
                elif kind == "math":
                    emit_math(el)
                elif kind == "coil":
                    emit_coil(el)
                elif kind in {"jsr", "sbr", "ret"}:
                    emit_subroutine(el)

            for el in elements:
                emit_element(el)


            right_id = next_id()
            right = _sub(ld, "rightPowerRail", {"localId": right_id})
            _sub(right, "position", {"x": str(x * 100), "y": "0"})
            c_in = _sub(right, "connectionPointIn")
            for pid in prev_ids:
                attrs = {"refLocalId": pid}
                if prev_param:
                    attrs["formalParameter"] = prev_param
                _sub(c_in, "connection", attrs)
            try:
                wh = rung_wiring_hash(_rung_object_list(list(ld)[left_index:], left_id))
                payload = json.dumps(
                    {"comment": comment, "elements": elements, "wh": wh}, separators=(",", ":")
                )
                _xhtml_doc(left, f"cabinet-studio-elements:{payload}")
            except Exception:
                pass

    emit_rungs(ld, list(ladder.get("rungs") or []))

    # v0.3.12: always stamp G-AID safety note into contentHeader Comment / documentation.
    # v0.3.8: also stamp named routines + aliases for lossless restore.
    from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
    from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE

    routines = ladder.get("routines") if isinstance(ladder.get("routines"), dict) else {}
    aliases = (ladder.get("meta") or {}).get("tag_aliases") if isinstance(ladder.get("meta"), dict) else None
    used = ladder.get("aoi_templates_used") if isinstance(ladder.get("aoi_templates_used"), list) else []
    comment_lines = [UL_DESIGN_AID, SAFETY_DESIGN_AID_NOTE]
    try:
        payload = {
            "routines": routines or {},
            "tag_aliases": aliases or {},
            "aoi_templates_used": used or [],
        }
        if routines:
            payload["routine_wiring"] = True  # v0.3.18: routine LD networks are in addData
        if payload["routines"] or payload["tag_aliases"] or payload["aoi_templates_used"]:
            comment_lines.append(f"cabinet-studio-meta:{json.dumps(payload, separators=(',', ':'))}")
    except Exception:
        pass
    comment_slot.text = "\n".join(comment_lines)
    # v0.3.18: routine (SBR) bodies as real LD networks so import can verify them against
    # the wiring. Kept in the Main POU's addData (not separate POUs) so older Cabinet Studio
    # importers, which read every <LD> body as Main rungs, never merge routine rungs into Main.
    if routines:
        add_data = _sub(pou, "addData")
        data = _sub(add_data, "data", {"name": ROUTINE_DATA_NAME, "handleUnknown": "discard"})
        container = _sub(data, ROUTINE_CONTAINER_TAG, {"version": "1"})
        for rname, rrungs in routines.items():
            rbody = _sub(container, ROUTINE_BODY_TAG, {"name": str(rname)})
            emit_rungs(rbody, [r for r in (rrungs or []) if isinstance(r, dict)])
    # Also put the note on the POU as documentation so pure-XML readers see it.
    try:
        _xhtml_doc(pou, f"{UL_DESIGN_AID} | {SAFETY_DESIGN_AID_NOTE}")
    except Exception:
        pass

    # TC6 requires instances (may be empty configurations container).
    instances = _sub(project, "instances")
    _sub(instances, "configurations")

    # Pretty print
    rough = ET.tostring(project, encoding="utf-8", xml_declaration=True)
    try:
        parsed = minidom.parseString(rough)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    except Exception:
        return rough.decode("utf-8")


from cabinet_studio.services.plcopen_graph import (  # noqa: E402  (v0.3.16 H-DEEP)
    REFUSE_PREFIX as GRAPH_REFUSE_PREFIX,
    GraphImportError,
    LDGraph,
    VerifyLimitError,
    bridged_fan_in,
    effect_descriptor,
    effect_nodes,
    live_nodes,
    reconstruct_elements,
    strip_nids,
    tag_effects_in_order,
    verify_elements,
)


ROUTINE_DATA_NAME = "urn:cabinet-studio:routine-networks"
ROUTINE_CONTAINER_TAG = "routineNetworks"
ROUTINE_BODY_TAG = "routineBody"


_IEC_NAME_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+|\[\d+\])*"  # IEC identifier, members, index
    r"|%[IQM][XBWDL]?\d+(?:\.\d+)*"  # IEC direct address
    r"|[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)+(?:\.[A-Za-z0-9_]+)*)$"  # Rockwell module tag
)


def tag_name_warnings(names: list[str]) -> list[str]:
    """v0.3.19 (Deflector P3-c): one warning per suspicious tag name.

    * invisible / control / format characters (zero-width space, BOM, ...);
    * non-ASCII characters (Cyrillic / Greek look-alikes, fullwidth letters, ...);
    * not NFKC-normalised (compatibility characters that render like others);
    * not an IEC 61131-3 identifier / direct address / Rockwell module tag (``1abc``, ``A B``);
    * case-only collisions (IEC identifiers are case-insensitive: ``pb_stop`` vs ``PB_Stop``).
    Numeric literals are not tags and are skipped."""
    import unicodedata

    from cabinet_studio.services.ladder_ir import numeric_literal_value

    out: list[str] = []
    seen: set[str] = set()
    by_fold: dict[str, set[str]] = {}
    for raw in names:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if numeric_literal_value(name) is not None:
            continue
        by_fold.setdefault(name.casefold(), set()).add(name)
        shown = name.encode("ascii", "backslashreplace").decode("ascii")
        why: list[str] = []
        odd = [c for c in name if unicodedata.category(c) in {"Cf", "Cc", "Co", "Cs", "Cn"} or c in "\u00ad\u034f\u115f\u1160\u3164"]
        if odd:
            why.append("invisible character(s) " + ", ".join(
                f"U+{ord(c):04X} {unicodedata.name(c, 'UNNAMED')}" for c in dict.fromkeys(odd)))
        nonascii = [c for c in name if ord(c) > 127 and c not in odd]
        if nonascii:
            why.append("non-ASCII look-alike character(s) " + ", ".join(
                f"{c!r} U+{ord(c):04X} {unicodedata.name(c, 'UNNAMED')}" for c in list(dict.fromkeys(nonascii))[:4]))
        if unicodedata.normalize("NFKC", name) != name:
            why.append("not NFKC-normalised")
        if not why and not _IEC_NAME_RE.match(name):
            why.append("not an IEC 61131-3 identifier (letters, digits and _ only, not starting with a digit)")
        if why:
            out.append(
                f"WARNING tag '{shown}': {'; '.join(why)}. It may look like another tag but it is a "
                "different tag to Cabinet Studio and to a PLC. Check every rung that uses it by hand."
            )
    for fold, group in by_fold.items():
        if len(group) > 1:
            shown_g = ", ".join("'" + g.encode("ascii", "backslashreplace").decode("ascii") + "'" for g in sorted(group))
            out.append(
                f"WARNING tags {shown_g} differ only in upper/lower case. IEC 61131-3 PLCs treat them as "
                "the SAME tag; Cabinet Studio treats them as different tags. Check them by hand."
            )
    return out


def _element_objs(items: list[dict[str, Any]] | None, acc: Any = None) -> Any:
    """v0.3.19: multiset of "<contact> /Tag" / "<coil> Tag" in an element list (OR branches
    included), used to name what a hint / metadata copy has that the wiring lacks."""
    from collections import Counter

    acc = Counter() if acc is None else acc
    for it in items or []:
        k = str(it.get("kind") or "").lower()
        if k == "or":
            for b in it.get("branches") or []:
                _element_objs(list(b or []), acc)
        elif k in {"contact", "coil"}:
            pre = "/" if str(it.get("form") or "").upper() == "NC" else ""
            acc[f"<{k}> {pre}{it.get('var')}"] += 1
    return acc


def _reconcile_routines(
    meta_payload: dict[str, Any],
    wired: dict[str, list[dict[str, Any]]],
    file_has_routine_wiring: bool,
    warn: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """v0.3.18: routine bodies — the verified LD wiring wins over the metadata.

    * Routine with wiring: use the verified wiring. If the Cabinet Studio metadata copy
      differs, warn naming the routine and the rung.
    * Routine only in metadata, but this file carries routine wiring (0.3.18+ export) or
      says it should: refuse — the routine was added / edited outside its wiring.
    * Routine only in metadata in an older file (no routine wiring at all): import it with a
      loud per-routine warning (it cannot be verified).
    """
    from cabinet_studio.services.ladder_ir import clean_elements, normalize_routine_name

    meta_r = meta_payload.get("routines") if isinstance(meta_payload.get("routines"), dict) else {}
    meta_clean: dict[str, list[dict[str, Any]]] = {}
    for rname, rrungs in (meta_r or {}).items():
        name = normalize_routine_name(rname)
        if not name or name == "Main" or not isinstance(rrungs, list):
            continue
        meta_clean[name] = [r for r in rrungs if isinstance(r, dict)]
    expects_wiring = file_has_routine_wiring or bool(meta_payload.get("routine_wiring"))
    out: dict[str, list[dict[str, Any]]] = {}
    for name, mrungs in meta_clean.items():
        if name in wired:
            continue
        if expects_wiring:
            raise GraphImportError(
                f"{GRAPH_REFUSE_PREFIX}: routine '{name}' is in the Cabinet Studio metadata but has no "
                "LD wiring in this file, so it cannot be verified (the file was edited outside "
                "Cabinet Studio). Nothing was imported."
            )
        out[name] = [
            {"id": str(r.get("id") or f"{name}_{i}"), "comment": str(r.get("comment") or ""),
             "elements": clean_elements(list(r.get("elements") or []))}
            for i, r in enumerate(mrungs, start=1)
        ]
        warn.append(
            f"WARNING routine '{name}' ({len(mrungs)} rung(s)) was restored from Cabinet Studio "
            "metadata ONLY: this file carries no LD wiring for it, so it could NOT be verified "
            "(Cabinet Studio 0.3.18+ exports routine wiring; an older export, or a file edited outside "
            "Cabinet Studio, has none). Check every rung of this routine by hand (E-stops, guards, "
            "interlocks), or re-export it from Cabinet Studio 0.3.18 or later."
        )
    for name, wrungs in wired.items():
        mrungs = meta_clean.get(name)
        final: list[dict[str, Any]] = []
        for i, wr in enumerate(wrungs, start=1):
            rid = str(i)
            comment = str(wr.get("comment") or "")
            if mrungs is not None and i <= len(mrungs):
                m_el = clean_elements(list(mrungs[i - 1].get("elements") or []))
                w_el = clean_elements(list(wr.get("elements") or []))
                if m_el == w_el:
                    rid = str(mrungs[i - 1].get("id") or rid)
                    comment = comment or str(mrungs[i - 1].get("comment") or "")
                else:
                    _mo, _wo = _element_objs(m_el), _element_objs(w_el)
                    _miss = sorted((_mo - _wo).elements())
                    _extra = sorted((_wo - _mo).elements())
                    _d = (
                        f" The metadata has {', '.join(_miss[:6])} that the wiring does NOT have (deleted in "
                        "another tool?)." if _miss else ""
                    ) + (f" The wiring has {', '.join(_extra[:6])} that the metadata does not." if _extra else "")
                    warn.append(
                        f"WARNING routine '{name}' rung {i}: the Cabinet Studio metadata copy of this "
                        f"rung did not match the routine's LD wiring.{_d} The WIRING was used (verified). "
                        "Check this rung by hand."
                    )
            final.append({"id": rid, "comment": comment, "elements": list(wr.get("elements") or [])})
        if mrungs is None:
            warn.append(
                f"WARNING routine '{name}' has LD wiring but no Cabinet Studio metadata entry; it was "
                "imported from the wiring (verified). Check it by hand."
            )
        elif len(mrungs) != len(wrungs):
            warn.append(
                f"WARNING routine '{name}': the metadata lists {len(mrungs)} rung(s) but the LD wiring "
                f"has {len(wrungs)}. The WIRING was used (verified). Check this routine by hand."
            )
        if final:
            out[name] = final
    return out


# ---------------------------------------------------------------------------------------
# v0.3.19 (Raddus attribute-mutation fuzz): strict TC6 vocabulary allowlist.
# Every element / attribute the importer reads is modelled exactly; a short list of purely
# cosmetic ones (layout, ids, notes, vendor addData) is ignored; ANYTHING else — an edge
# contact, a negated block pin, an unknown block type or pin, a second POU, an ST body, a
# retain / constant variable list, ... — refuses the whole file. Ignoring an unmodelled
# attribute would import logic that differs from the file and call it verified.
# ---------------------------------------------------------------------------------------
_TC6_COSMETIC_ATTRS = frozenset({"localId", "width", "height", "executionOrderId", "globalId"})
_TC6_FREE_CHILDREN = frozenset({"documentation", "addData", "content"})  # never decide logic
_TC6_BOOL_TRUE = frozenset({"true", "1"})
_TC6_BOOL_FALSE = frozenset({"false", "0"})


def _tc6_block_pins() -> dict[str, tuple[frozenset[str], frozenset[str], frozenset[str | None]]]:
    """typeName -> (input pins, output pins, formalParameters a wire FROM the block may use)."""
    from cabinet_studio.services.ladder_ir import COMPARE_OPS, MATH_OPS

    pins: dict[str, tuple[frozenset[str], frozenset[str], frozenset[str | None]]] = {}
    for t in ("TON", "TOF", "RTO"):
        pins[t] = (frozenset({"IN", "PT"}), frozenset({"Q", "ET"}), frozenset({"Q", None}))
    pins["CTU"] = (frozenset({"CU", "RESET", "PV"}), frozenset({"Q", "CV"}), frozenset({"Q", None}))
    pins["CTD"] = (frozenset({"CD", "LOAD", "PV"}), frozenset({"Q", "CV"}), frozenset({"Q", None}))
    for t in ONESHOT_TYPES:
        pins[t] = (frozenset({"CLK"}), frozenset({"Q"}), frozenset({"Q", None}))
    for t in COMPARE_OPS:
        pins[t] = (frozenset({"EN", "IN1", "IN2"} | ({"IN3"} if t in {"LIM", "MEQ"} else set())),
                   frozenset({"ENO"}), frozenset({"ENO", None}))
    for t in MATH_OPS:
        pins[t] = (frozenset({"EN", "IN1"} | (set() if t in {"MOV", "CPT", "NOT"} else {"IN2"})),
                   frozenset({"ENO"}), frozenset({"ENO", None}))
    for t in ("JSR", "SBR", "RET", "RES", "LOAD"):
        pins[t] = (frozenset({"EN"}), frozenset({"ENO"}), frozenset({"ENO", None}))
    return pins


def check_tc6_vocabulary(root: ET.Element) -> None:
    """Raise GraphImportError on any TC6 element / attribute Cabinet Studio does not model."""
    from cabinet_studio.services.plcopen_graph import GraphImportError

    pins = _tc6_block_pins()

    def refuse(what: str) -> None:
        raise GraphImportError(
            f"PLCopen import refused: {what}. Cabinet Studio does not model this, and ignoring it "
            "would import logic that differs from the file. Nothing was imported."
        )

    def attrs_ok(el: ET.Element, allowed: set[str], where: str) -> None:
        for a in el.attrib:
            if a not in allowed and a not in _TC6_COSMETIC_ATTRS:
                refuse(f"{where} has the attribute {_local(a)}=\"{el.get(a)}\"")

    def children_ok(el: ET.Element, allowed: set[str], where: str) -> list[ET.Element]:
        out = []
        for c in list(el):
            lc = _local(c.tag)
            if lc in _TC6_FREE_CHILDREN:
                continue
            if lc not in allowed:
                refuse(f"{where} contains a <{lc}> element")
            out.append(c)
        return out

    def flag(el: ET.Element, attr: str, where: str, *, allow_true: bool) -> bool:
        raw = el.get(attr)
        if raw is None:
            return False
        v = str(raw).strip().lower()
        if v in _TC6_BOOL_FALSE:
            return False
        if v in _TC6_BOOL_TRUE and allow_true:
            return True
        refuse(f"{where} has {attr}=\"{raw}\"")
        return False

    def plain_only(el: ET.Element, attr: str, where: str, ok: set[str]) -> str:
        raw = el.get(attr)
        if raw is None:
            return ""
        v = str(raw).strip().lower()
        if v not in ok:
            refuse(f"{where} has {attr}=\"{raw}\"")
        return v

    def cp_in(el: ET.Element, where: str, *, expr_ok: bool) -> None:
        for c in children_ok(el, {"connection", "relPosition", "expression"}, where):
            lc = _local(c.tag)
            if lc == "expression" and not expr_ok:
                refuse(f"{where} has an <expression> where a wire is expected")
            if lc == "connection":
                attrs_ok(c, {"refLocalId", "formalParameter"}, f"a wire in {where}")
                children_ok(c, {"position"}, f"a wire in {where}")

    def cp_out(el: ET.Element, where: str) -> None:
        attrs_ok(el, {"formalParameter"}, where)
        children_ok(el, {"relPosition", "expression"}, where)

    def body_objects(body: ET.Element, label: str) -> None:
        by_id = {str(c.get("localId")): c for c in list(body) if c.get("localId")}
        for obj in list(body):
            tag = _local(obj.tag)
            if tag in _TC6_FREE_CHILDREN:
                continue
            nm = _var_name_from_node(obj) if tag in {"contact", "coil"} else str(obj.get("instanceName") or "")
            where = f"{label}<{tag}>{' ' + nm if nm else ''} (localId {obj.get('localId') or '?'})"
            if tag in {"leftPowerRail", "rightPowerRail"}:
                attrs_ok(obj, set(), where)
                for c in children_ok(obj, {"position", "connectionPointIn", "connectionPointOut"}, where):
                    if _local(c.tag) == "connectionPointIn":
                        cp_in(c, where, expr_ok=False)
                    elif _local(c.tag) == "connectionPointOut":
                        cp_out(c, where)
            elif tag == "comment":
                attrs_ok(obj, set(), where)
                children_ok(obj, {"position"}, where)
            elif tag in {"contact", "coil"}:
                attrs_ok(obj, {"negated", "edge", "storage", "variable"} if tag == "coil" else {"negated", "edge", "variable"}, where)
                _vels = [c for c in list(obj) if _local(c.tag) == "variable"]
                if len(_vels) > 1:
                    refuse(f"{where} has {len(_vels)} <variable> elements")
                if obj.get("variable") is not None and _vels and str(obj.get("variable")).strip() != (_vels[0].text or "").strip():
                    # legacy (0.3.9 / 0.3.10) exports carry the tag both ways; they must agree
                    refuse(f"{where} names two different variables ({obj.get('variable')!r} attribute, "
                           f"{(_vels[0].text or '').strip()!r} element)")
                neg = flag(obj, "negated", where, allow_true=True)
                plain_only(obj, "edge", where, {"none"})
                if tag == "coil":
                    st = plain_only(obj, "storage", where, {"none", "set", "reset"})
                    if neg and st in {"set", "reset"}:
                        refuse(f"{where} is both negated and storage=\"{obj.get('storage')}\"")
                for c in children_ok(obj, {"position", "connectionPointIn", "connectionPointOut", "variable"}, where):
                    lc = _local(c.tag)
                    if lc == "connectionPointIn":
                        cp_in(c, where, expr_ok=False)
                    elif lc == "connectionPointOut":
                        cp_out(c, where)
                    elif lc == "variable":
                        attrs_ok(c, set(), where)
                        children_ok(c, set(), where)
            elif tag == "block":
                attrs_ok(obj, {"typeName", "instanceName"}, where)
                typ = str(obj.get("typeName") or "").strip().upper()
                if typ not in pins:
                    refuse(f"{where} is a block of type \"{obj.get('typeName')}\" (not a Cabinet Studio instruction)")
                ins, outs, _w = pins[typ]
                for sect in children_ok(obj, {"position", "inputVariables", "inOutVariables", "outputVariables"}, where):
                    ls = _local(sect.tag)
                    if ls == "position":
                        continue
                    if ls == "inOutVariables":
                        if children_ok(sect, set(), where):
                            refuse(f"{where} has in-out variables")
                        continue
                    allowed_pins = ins if ls == "inputVariables" else outs
                    for v in children_ok(sect, {"variable"}, where):
                        fp = str(v.get("formalParameter") or "")
                        w2 = f"{where} pin {fp or '?'}"
                        attrs_ok(v, {"formalParameter", "negated", "edge", "storage"}, w2)
                        if fp.upper() not in allowed_pins:
                            refuse(f"{where} has an unknown {ls[:-9]} pin \"{fp}\" for {typ}")
                        flag(v, "negated", w2, allow_true=False)
                        plain_only(v, "edge", w2, {"none"})
                        plain_only(v, "storage", w2, {"none"})
                        for c in children_ok(v, {"connectionPointIn", "connectionPointOut", "expression"}, w2):
                            lc = _local(c.tag)
                            if lc == "connectionPointIn":
                                cp_in(c, w2, expr_ok=True)
                            elif lc == "connectionPointOut":
                                cp_out(c, w2)
            else:
                refuse(f"{label}LD body contains a <{tag}> element{' (localId ' + str(obj.get('localId')) + ')' if obj.get('localId') else ''}")
        # wires FROM a block may only use its power output pin (Q / ENO); from anything else, no pin
        for obj in list(body):
            for cn in obj.iter():
                if _local(cn.tag) != "connection":
                    continue
                src = by_id.get(str(cn.get("refLocalId") or ""))
                if src is None:
                    continue
                fp = cn.get("formalParameter")
                fp_n = None if fp is None or not str(fp).strip() else str(fp).strip().upper()
                if _local(src.tag) == "block":
                    ok = pins.get(str(src.get("typeName") or "").strip().upper(), (None, None, frozenset()))[2]
                    if fp_n not in ok:
                        refuse(f"{label}a wire takes the {fp} output of block {src.get('typeName')} "
                               f"{src.get('instanceName') or ''} (localId {src.get('localId')})")
                elif fp_n is not None and _local(src.tag) not in {"contact", "coil", "leftPowerRail"}:
                    # contacts, coils and the left rail have ONE output, so a pin name on a
                    # wire from them cannot select anything (cosmetic; a tool that re-points
                    # a block's Q wire at a contact leaves it behind). Anything else refuses.
                    refuse(f"{label}a wire from <{_local(src.tag)}> localId {src.get('localId')} names a pin \"{fp}\"")

    # ---- document structure
    for el in root.iter():
        if _local(el.tag) == "pous":
            pou_list = children_ok(el, {"pou"}, "the project")
            if len(pou_list) != 1:
                refuse(f"the project has {len(pou_list)} POUs (Cabinet Studio imports exactly one program)")
        elif _local(el.tag) == "pou":
            attrs_ok(el, {"name", "pouType"}, f"POU {el.get('name')!r}")
            if str(el.get("pouType") or "program") != "program":
                refuse(f"POU {el.get('name')!r} is a {el.get('pouType')} (only a program is imported)")
            children_ok(el, {"interface", "body"}, f"POU {el.get('name')!r}")
        elif _local(el.tag) == "body":
            kids = children_ok(el, {"LD"}, "the POU body")
            if len(kids) != 1:
                refuse("the POU body has no single LD network")
        elif _local(el.tag) == "interface":
            for vl in children_ok(el, {"inputVars", "outputVars", "localVars"}, "the POU interface"):
                attrs_ok(vl, set(), f"the {_local(vl.tag)} list")
                for v in children_ok(vl, {"variable"}, f"the {_local(vl.tag)} list"):
                    attrs_ok(v, {"name", "address"}, f"variable {v.get('name')!r}")
                    children_ok(v, {"type", "initialValue"}, f"variable {v.get('name')!r}")
        elif _local(el.tag) == "dataTypes":
            if children_ok(el, set(), "the project data types"):
                refuse("the project declares user data types")
    addrs: dict[str, str] = {}
    for el in root.iter():
        if _local(el.tag) == "variable" and el.get("address") and el.get("name"):
            a = str(el.get("address")).strip().upper()
            if a in addrs and addrs[a] != el.get("name"):
                refuse(f"variables {addrs[a]!r} and {el.get('name')!r} share the address {el.get('address')} (aliasing)")
            addrs[a] = str(el.get("name"))
    for el in root.iter():
        lt = _local(el.tag)
        if lt == "LD":
            body_objects(el, "")
        elif lt == "routineBody":
            body_objects(el, f"routine '{el.get('name')}' ")


def plcopen_xml_to_ladder_ir(xml_text: str) -> dict[str, Any]:
    """Parse a subset of PLCopen LD XML into Cabinet Studio ladder IR."""
    text = (xml_text or "").strip()
    if not text:
        return empty_ladder()
    root = ET.fromstring(text)
    check_tc6_vocabulary(root)  # v0.3.19: strict allowlist (refuses unmodelled TC6)

    def findall(node: ET.Element, name: str) -> list[ET.Element]:
        return [c for c in node.iter() if _local(c.tag) == name]

    def find_child(node: ET.Element, name: str) -> ET.Element | None:
        for c in list(node):
            if _local(c.tag) == name:
                return c
        return None

    ladder = empty_ladder()
    ladder["format"] = IR_FORMAT
    ladder["version"] = IR_VERSION
    ladder["dialect"] = IR_DIALECT
    ladder["meta"]["label"] = "Imported PLCopen XML"
    ladder["meta"]["not_a_vendor_format"] = True

    variables: list[dict[str, Any]] = []
    for section, cls in (("inputVars", "input"), ("outputVars", "output"), ("localVars", "internal")):
        for block in findall(root, section):
            for variable in block:
                if _local(variable.tag) != "variable":
                    continue
                name = variable.get("name") or ""
                if not name:
                    continue
                vtype_el = find_child(variable, "type")
                type_name = "BOOL"
                pt_ms = 0
                pv = 0
                var_cls = cls
                if vtype_el is not None:
                    for child in list(vtype_el):
                        local = _local(child.tag)
                        if local == "derived":
                            type_name = str(child.get("name") or "BOOL").upper()
                            if type_name in {"TON", "TOF", "RTO"}:
                                var_cls = "timer"
                            elif type_name in COUNTER_TYPES:
                                type_name = "CTU" if type_name == "CTUD" else type_name
                                var_cls = "counter"
                        elif local in {"TON", "TOF", "RTO"}:
                            type_name = local
                            var_cls = "timer"
                        elif local.upper() in COUNTER_TYPES:
                            type_name = "CTU" if local.upper() == "CTUD" else local.upper()
                            var_cls = "counter"
                        elif local == "BOOL":
                            type_name = "BOOL"
                        elif local.upper() in NUMERIC_TYPES:
                            type_name = local.upper()
                            var_cls = "numeric"
                raw_doc = _read_doc_text(variable)
                doc_lines = [ln.strip() for ln in raw_doc.split("\n")] if raw_doc else []
                description = ""
                if doc_lines and doc_lines[0].startswith("pt_ms="):
                    try:
                        pt_ms = max(0, int(doc_lines[0].split("=", 1)[1].strip()))
                    except ValueError:
                        pt_ms = 0
                    description = " ".join(doc_lines[1:]).strip()
                elif doc_lines and doc_lines[0].startswith("pv="):
                    pv = clamp_counter(doc_lines[0].split("=", 1)[1].strip())
                    description = " ".join(doc_lines[1:]).strip()
                elif doc_lines:
                    description = " ".join(doc_lines).strip()
                addr = str(variable.get("address") or "").strip()
                entry: dict[str, Any] = {
                    "name": name,
                    "class": var_cls,
                    "type": type_name,
                    "address": addr,
                }
                if description:
                    entry["description"] = description
                if var_cls == "timer":
                    entry["pt_ms"] = pt_ms
                if var_cls == "counter":
                    entry["pv"] = pv
                init_el = find_child(variable, "initialValue")
                if init_el is not None:
                    simple = find_child(init_el, "simpleValue")
                    if simple is not None and simple.get("value") is not None:
                        raw_init = simple.get("value")
                        if var_cls == "numeric" or type_name in NUMERIC_TYPES:
                            try:
                                entry["value"] = float(raw_init) if type_name in {"REAL", "LREAL"} else float(int(float(raw_init)))
                            except (TypeError, ValueError):
                                try:
                                    entry["value"] = float(raw_init)
                                except (TypeError, ValueError):
                                    pass
                        elif str(raw_init).upper() in {"TRUE", "FALSE"}:
                            entry["value"] = str(raw_init).upper() == "TRUE"
                variables.append(entry)
    ladder["variables"] = variables

    # Build connection graph from LD
    ld_nodes = findall(root, "LD")
    if not ld_nodes:
        return normalize_ladder_ir(ladder)

    # v0.3.18: routine (SBR) networks travel as real LD wiring in the Main POU's addData
    # (<routineBody name=…>) so they get the same verify-against-wiring guard as Main.
    routine_containers = findall(root, ROUTINE_CONTAINER_TAG)
    bodies: list[tuple[ET.Element, str | None]] = [(ld, None) for ld in ld_nodes]
    for _rb in findall(root, ROUTINE_BODY_TAG):
        bodies.append((_rb, str(_rb.get("name") or "").strip()))

    _where = {"label": "rung 1"}

    def _where_label() -> str:
        return _where["label"]

    main_rungs: list[dict[str, Any]] = []
    routine_rungs: dict[str, list[dict[str, Any]]] = {}
    rungs_out: list[dict[str, Any]] = main_rungs
    for ld, body_routine in bodies:
        if body_routine is None:
            rungs_out = main_rungs
            _body_prefix = ""
        else:
            from cabinet_studio.services.ladder_ir import normalize_routine_name as _nrn

            _rname = _nrn(body_routine)
            if not _rname or _rname == "Main" or _rname in routine_rungs:
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX}: routine wiring block {body_routine!r} has an invalid or "
                    "duplicate routine name. Nothing was imported."
                )
            body_routine = _rname
            rungs_out = routine_rungs.setdefault(_rname, [])
            _body_prefix = f"routine '{_rname}' "
        _where["label"] = f"{_body_prefix}rung {len(rungs_out) + 1}"
        # Group by walking from each leftPowerRail
        lefts = [n for n in list(ld) if _local(n.tag) == "leftPowerRail"]
        # Index all elements by localId
        by_id: dict[str, ET.Element] = {}
        for child in list(ld):
            lid = child.get("localId")
            if lid:
                if lid in by_id:
                    # v0.3.19 (P1-B family): a duplicate localId makes every wire to it a guess.
                    raise GraphImportError(
                        f"{GRAPH_REFUSE_PREFIX}: {_body_prefix}localId {lid} is used by two LD objects "
                        f"(<{_local(by_id[lid].tag)}> and <{_local(child.tag)}>), so a wire to it is "
                        "ambiguous. Nothing was imported."
                    )
                by_id[lid] = child

        # Reverse edges: refLocalId -> list of nodes that connect from it
        forward: dict[str, list[str]] = {}
        for child in list(ld):
            lid = child.get("localId")
            if not lid:
                continue
            for cpi in child.iter():
                if _local(cpi.tag) != "connection":
                    continue
                ref = cpi.get("refLocalId")
                if ref:
                    forward.setdefault(ref, []).append(lid)

        def is_contact(node: ET.Element) -> bool:
            return _local(node.tag) == "contact"

        def is_coil(node: ET.Element) -> bool:
            return _local(node.tag) == "coil"

        fb_instances = {
            str(v.get("name"))
            for v in variables
            if v.get("class") in {"timer", "counter"} and v.get("name")
        }
        for child in list(ld):
            if _local(child.tag) == "block" and child.get("instanceName"):
                fb_instances.add(str(child.get("instanceName")))

        def contact_el(node: ET.Element) -> dict[str, Any]:
            negated = str(node.get("negated", "false")).lower() in {"true", "1"}
            var = _var_name_from_node(node)
            base, member = split_member(var)
            if member == "Q" and base in fb_instances:
                var = f"{base}.DN"
            out = {
                "kind": "contact",
                "var": var,
                "form": "NC" if negated else "NO",
            }
            note = note_from_doc(node)
            if note:
                out["desc"] = note
            if node.get("localId"):
                out["_nid"] = str(node.get("localId"))
            return out

        def coil_el(node: ET.Element) -> dict[str, Any]:
            form = "normal"
            if str(node.get("negated", "false")).lower() in {"true", "1"}:
                form = "negated"
            storage = str(node.get("storage") or "").lower()
            if storage in {"set", "reset"}:
                form = storage
            out = {"kind": "coil", "var": _var_name_from_node(node), "form": form}
            note = note_from_doc(node)
            if note:
                out["desc"] = note
            if node.get("localId"):
                out["_nid"] = str(node.get("localId"))
            return out

        def _preset_refusal(what: str, detail: str) -> GraphImportError:
            return GraphImportError(
                f"{GRAPH_REFUSE_PREFIX} at {_where_label()}: {what} — {detail}. Nothing was imported. "
                "Cabinet Studio never guesses a preset (it would not default to 0 or to a "
                "documentation value); fix the value in the source tool and export again."
            )

        def _pin_expressions(node: ET.Element, formal: str) -> list[str]:
            want = str(formal or "").upper()
            found: list[str] = []
            for child in node.iter():
                if _local(child.tag) != "variable":
                    continue
                if str(child.get("formalParameter") or "").upper() != want:
                    continue
                for sub in child.iter():
                    if _local(sub.tag) == "expression":
                        found.append((sub.text or "").strip())
            return found

        def timer_el(node: ET.Element) -> dict[str, Any]:
            """v0.3.18 NEW-9: PT comes from the executable wiring — a full IEC 61131-3
            duration (T#1m30s, TIME#5s, T#5s_500ms, …) or a tag reference.
            v0.3.19 (Audit NEW-17): the block documentation never supplies PT. An empty or
            missing PT pin refuses (every Cabinet Studio export writes PT on the pin)."""
            from cabinet_studio.services.ladder_ir import is_tag_reference, parse_iec_duration_ms

            block = str(node.get("typeName") or "TON").upper()
            if block not in {"TON", "TOF", "RTO"}:
                block = "TON"
            instance = str(node.get("instanceName") or node.get("variable") or "").strip()
            label = f"timer {block} {instance}".strip()
            pt_ms = 0
            pt_tag = ""
            exprs = [e for e in _pin_expressions(node, "PT") if e]
            if len(exprs) > 1:
                raise _preset_refusal(label, f"its PT pin has {len(exprs)} values ({', '.join(exprs)})")
            if exprs:
                raw_pt = exprs[0]
                try:
                    pt_ms = parse_iec_duration_ms(raw_pt)
                except ValueError as exc:
                    if is_tag_reference(raw_pt):
                        pt_tag = raw_pt
                    else:
                        raise _preset_refusal(label, f"PT {raw_pt!r} is not a valid time ({exc})") from None
            else:
                raw = _read_doc_text(node)
                if "pt_ms=" in raw:
                    tok = raw.split("pt_ms=", 1)[1].split()[0] if raw.split("pt_ms=", 1)[1].split() else ""
                    raise _preset_refusal(
                        label,
                        f"its PT (preset time) input has no value; its note says pt_ms={tok!r}, "
                        "but a note is a label and never supplies a preset",
                    )
                raise _preset_refusal(label, "its PT (preset time) input has no value")
            if not instance:
                # Fall back to documentation TIMER name or typeName
                instance = block
            out = {
                "kind": "timer",
                "var": instance,
                "block": block,
                "pt_ms": pt_ms,
            }
            if pt_tag:
                out["pt_tag"] = pt_tag
            return out

        def is_timer_block(node: ET.Element) -> bool:
            if _local(node.tag) != "block":
                return False
            return str(node.get("typeName") or "").upper() in {"TON", "TOF", "RTO"}

        def is_counter_block(node: ET.Element) -> bool:
            if _local(node.tag) != "block":
                return False
            return str(node.get("typeName") or "").upper() in (COUNTER_TYPES | COUNTER_ACTION_TYPES)

        def counter_el(node: ET.Element) -> dict[str, Any]:
            """v0.3.18 NEW-9: PV from the wiring — IEC integer literal (42, 16#0A, 2#1010,
            INT#5 …) or a tag reference; out-of-range or unparseable values refuse."""
            from cabinet_studio.services.ladder_ir import COUNTER_MAX, COUNTER_MIN, is_tag_reference, parse_iec_int

            block = normalize_counter_block(node.get("typeName"))
            instance = str(node.get("instanceName") or node.get("variable") or "").strip() or block
            label = f"counter {block} {instance}".strip()
            pv = 0
            pv_tag = ""
            exprs = [e for e in _pin_expressions(node, "PV") if e]
            raw_pv = ""
            if len(exprs) > 1:
                raise _preset_refusal(label, f"its PV pin has {len(exprs)} values ({', '.join(exprs)})")
            if exprs:
                raw_pv = exprs[0]
            elif block in COUNTER_OWNER_BLOCKS:
                # v0.3.19 (Audit NEW-17): CTU / CTD carry PV on the pin; the note never
                # supplies it. RES / LOAD have no PV pin, so their pv= note stays the
                # documented Cabinet Studio extension.
                raise _preset_refusal(label, "its PV (preset) input has no value; a note never supplies a preset")
            else:
                raw = _read_doc_text(node)
                if "pv=" in raw:
                    rest = raw.split("pv=", 1)[1].split()
                    raw_pv = rest[0] if rest else ""
                    if not raw_pv:
                        raise _preset_refusal(label, "its note has an empty pv=")
            if raw_pv:
                try:
                    pv = parse_iec_int(raw_pv)
                except ValueError as exc:
                    if exprs and is_tag_reference(raw_pv):
                        pv_tag = raw_pv
                    else:
                        raise _preset_refusal(label, f"PV {raw_pv!r} is not a valid integer ({exc})") from None
                if not pv_tag and not (COUNTER_MIN <= pv <= COUNTER_MAX):
                    raise _preset_refusal(
                        label, f"PV {raw_pv!r} = {pv} is outside the counter range {COUNTER_MIN}..{COUNTER_MAX}"
                    )
            out = {"kind": "counter", "var": instance, "block": block, "pv": pv}
            if pv_tag and (block in COUNTER_OWNER_BLOCKS or block == "LOAD"):
                out["pv_tag"] = pv_tag
            return out

        def _expr_for_param(node: ET.Element, formal: str) -> str:
            want = str(formal or "").upper()
            for child in node.iter():
                if _local(child.tag) != "variable":
                    continue
                if str(child.get("formalParameter") or "").upper() != want:
                    continue
                for sub in child.iter():
                    if _local(sub.tag) == "expression" and (sub.text or "").strip():
                        return (sub.text or "").strip()
            return ""

        def is_compare_block(node: ET.Element) -> bool:
            from cabinet_studio.services.ladder_ir import COMPARE_OPS

            if _local(node.tag) != "block":
                return False
            typ = str(node.get("typeName") or "").upper()
            if typ in COMPARE_OPS:
                return True
            doc = _read_doc_text(node).upper()
            return doc.startswith("COMPARE ")

        def is_math_block(node: ET.Element) -> bool:
            from cabinet_studio.services.ladder_ir import MATH_OPS

            if _local(node.tag) != "block":
                return False
            typ = str(node.get("typeName") or "").upper()
            if typ in MATH_OPS:
                return True
            doc = _read_doc_text(node).upper()
            return doc.startswith("MATH ")

        def compare_el(node: ET.Element) -> dict[str, Any]:
            from cabinet_studio.services.ladder_ir import COMPARE_OPS, normalize_compare_op

            # v0.3.19 (Audit NEW-15 / NEW-17): the op is the block typeName and the operands
            # are the pin expressions. The "COMPARE …" note is a label: it never supplies the
            # op or an operand. An empty operand imports empty (Verify flags it and the
            # simulator will not run), exactly as written in the file.
            typ = str(node.get("typeName") or "").upper()
            if typ not in COMPARE_OPS:
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX}: compare block {node.get('instanceName') or ''} has type "
                    f"{node.get('typeName')!r}, which is not a Cabinet Studio compare instruction "
                    "(its note is a label and never supplies the op). Nothing was imported."
                )
            op = normalize_compare_op(typ)
            a = _expr_for_param(node, "IN1")
            b = _expr_for_param(node, "IN2")
            c = _expr_for_param(node, "IN3")
            el = {"kind": "compare", "op": op, "source_a": a, "source_b": b, "source_c": c}
            note = note_from_doc(node)
            if note:
                el["desc"] = note
            return el

        def math_el(node: ET.Element) -> dict[str, Any]:
            from cabinet_studio.services.ladder_ir import MATH_OPS, normalize_math_op

            # v0.3.19 (Audit NEW-15 / NEW-17): the op is the block typeName, the operands are
            # the pin expressions and dest is the instanceName. The "MATH …" note is a label:
            # it never supplies the op, dest or an operand that has a pin.
            typ = str(node.get("typeName") or "").upper()
            if typ not in MATH_OPS:
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX}: math block {node.get('instanceName') or ''} has type "
                    f"{node.get('typeName')!r}, which is not a Cabinet Studio math instruction "
                    "(its note is a label and never supplies the op). Nothing was imported."
                )
            op = normalize_math_op(typ)
            dest = str(node.get("instanceName") or "").strip()
            a = _expr_for_param(node, "IN1")
            b = _expr_for_param(node, "IN2")
            expr = ""
            doc = _read_doc_text(node)
            if doc.upper().startswith("MATH "):
                # MATH OP dest=D a=A b=B expr=…  (expr is LAST; may contain spaces)
                head, _note_sep, _note_tail = doc.partition(f" | {NOTE_PREFIX}")
                before_expr = head.partition("expr=")[0]
                fields = dict(tok.split("=", 1) for tok in before_expr.split()[2:] if "=" in tok)
                import re as _re

                # The exporter writes an auto instance name (e.g. ADD_3) for an empty dest,
                # with "dest=" empty in the note. Only that exact pair clears dest.
                if _re.fullmatch(rf"{_re.escape(typ)}_\d+", dest or "") and fields.get("dest", None) == "":
                    dest = ""
                # MOV / CPT / NOT have no IN2 pin and never read b; b= is only a label there.
                if op in {"MOV", "CPT", "NOT"} and not b:
                    b = fields.get("b", "")
            # CPT: the IN1 expression is the executable wiring; the note's expr= never
            # supplies it. v0.3.17 (Raddus / NEW-5): an empty or malformed CPT imports
            # VERBATIM (never rewritten to 0, never a crash). Verify (F7) flags it as an
            # error and the simulator refuses to run until it is fixed by hand.
            if op == "CPT":
                expr = a

            el = {
                "kind": "math",
                "op": op,
                "dest": dest,
                "source_a": a if op != "CPT" else (a or expr),
                "source_b": b,
                "expression": expr,
            }
            note = note_from_doc(node)
            if note:
                el["desc"] = note
            return el

        def fb_el(node: ET.Element) -> dict[str, Any]:
            if is_oneshot_block(node):
                el = oneshot_el(node)
            elif is_compare_block(node):
                el = compare_el(node)
            elif is_math_block(node):
                el = math_el(node)
            elif is_subroutine_block(node):
                el = subroutine_el(node)
            else:
                el = counter_el(node) if is_counter_block(node) else timer_el(node)
                note = note_from_doc(node)
                if note:
                    el["desc"] = note
            if node.get("localId"):
                el["_nid"] = str(node.get("localId"))
            return el

        def is_subroutine_block(node: ET.Element) -> bool:
            return _local(node.tag) == "block" and str(node.get("typeName") or "").upper() in {"JSR", "SBR", "RET"}

        def subroutine_el(node: ET.Element) -> dict[str, Any]:
            typ = str(node.get("typeName") or "").upper()
            label = str(node.get("instanceName") or "").strip()
            if typ == "JSR":
                el: dict[str, Any] = {"kind": "jsr", "target": label}
            elif typ == "SBR":
                el = {"kind": "sbr", "name": label}
            else:
                el = {"kind": "ret"}
            note = note_from_doc(node)
            if note:
                el["desc"] = note
            return el

        # v0.3.16 (H-DEEP): primary power pin per block type; any wire on another pin
        # cannot be represented and makes the hint-less import refuse.
        _POWER_PINS = {"IN", "CU", "CD", "EN", "CLK", ""}

        def build_rung_graph(left_node: ET.Element, only: set[str] | None = None) -> LDGraph:
            """LD wiring reachable from one left rail, as an LDGraph (for verify / rebuild).

            ``only`` (v0.3.17 NEW-4) restricts the walk to one wired component when the
            body has no left rail and a virtual rail feeds several rungs (unused since v0.3.19:
            a body with no left rail is refused)."""
            lid0 = str(left_node.get("localId") or "")
            g = LDGraph(lid0)
            stack = [lid0]
            seen: set[str] = set()
            while stack:
                cur_id = stack.pop()
                if cur_id in seen:
                    continue
                if only is not None and cur_id != lid0 and cur_id not in only:
                    continue
                seen.add(cur_id)
                for nxt in forward.get(cur_id) or []:
                    if nxt not in seen:
                        stack.append(nxt)
            for nid in sorted(seen - {lid0}, key=lambda x: (len(x), x)):
                node = by_id.get(nid)
                if node is None:
                    continue
                local = _local(node.tag)
                if local == "contact":
                    g.add_node(nid, "contact", contact_el(node))
                elif local == "coil":
                    absorbed = _read_doc_text(node).startswith("ONESHOT-OUTPUT")
                    g.add_node(nid, "coil", coil_el(node), absorbed=absorbed)
                elif local == "rightPowerRail":
                    g.add_node(nid, "right")
                elif local == "block" and (is_fb_block(node) or is_subroutine_block(node)):
                    el = fb_el(node)
                    passthrough = el.get("kind") == "oneshot" and str(el.get("block") or "").upper() in {"OSR", "OSF"}
                    g.add_node(nid, "fb", el, passthrough=passthrough)
                    for var_el in node.iter():
                        if _local(var_el.tag) != "variable":
                            continue
                        pin = str(var_el.get("formalParameter") or "").upper()
                        wired = [
                            c for c in var_el.iter()
                            if _local(c.tag) == "connection" and c.get("refLocalId")
                        ]
                        if wired and pin not in _POWER_PINS:
                            raise GraphImportError(
                                f"{GRAPH_REFUSE_PREFIX}: block {node.get('typeName')} "
                                f"{node.get('instanceName') or ''} has a wire on its {pin} pin, "
                                "which Cabinet Studio cannot represent. Nothing was imported."
                            )
                else:
                    raise GraphImportError(
                        f"{GRAPH_REFUSE_PREFIX}: LD object <{local}> "
                        f"{node.get('typeName') or ''} is not supported by the hint-less "
                        "importer. Nothing was imported."
                    )
                for cpi in node.iter():
                    if _local(cpi.tag) == "connection" and cpi.get("refLocalId"):
                        src_id = str(cpi.get("refLocalId"))
                        if src_id in seen:
                            g.add_edge(src_id, nid)
            # v0.3.18 (Audit P3-C): an R_TRIG / F_TRIG edge block (OSR / OSF form) whose Q
            # drives exactly one plain coil (and nothing else) is the IEC spelling of
            # "OSR / OSF with output bit": import it that way instead of refusing. Any other
            # use of Q (feeding more logic) stays outside the model and the guard refuses.
            _succ = g.succs()
            # v0.3.18: the "ONESHOT-OUTPUT" note alone never hides a coil. A coil is absorbed
            # into a one-shot only when it really hangs off that OSR / OSF block's Q (sole
            # input, nothing after it but the right rail, and the block names it as its
            # output). Otherwise it is an ordinary coil and the guard verifies it — a
            # rewired / edited "absorbed" coil used to be dropped silently.
            for c_id, c_node in list(g.nodes.items()):
                if not c_node.get("absorbed"):
                    continue
                c_preds = list(g.preds.get(c_id, []))
                b_node = g.nodes.get(c_preds[0]) if len(c_preds) == 1 else None
                c_var = str((c_node.get("el") or {}).get("var") or "")
                # v0.3.19 (Audit NEW-13): the note never overrides the coil. The coil must be
                # a plain (normal) coil and the block must name exactly this coil as its
                # output; a set / reset / negated coil, or a block without output=, is an
                # ordinary coil that the guard verifies (and refuses when unrepresentable).
                legit = (
                    b_node is not None
                    and bool(b_node.get("passthrough"))
                    and bool(c_var)
                    and str((b_node.get("el") or {}).get("output") or "") == c_var
                    and str((c_node.get("el") or {}).get("form") or "normal") == "normal"
                    and all((g.nodes.get(m) or {}).get("kind") == "right" for m in _succ.get(c_id, []))
                )
                if not legit:
                    c_node["absorbed"] = False
            for b_id, b_node in list(g.nodes.items()):
                if not b_node.get("passthrough"):
                    continue
                outs = [m for m in _succ.get(b_id, []) if not (g.nodes.get(m) or {}).get("absorbed")]
                if len(outs) != 1:
                    continue
                c_id = outs[0]
                c_node = g.nodes.get(c_id) or {}
                c_el = c_node.get("el") or {}
                if (
                    c_node.get("kind") != "coil"
                    or str(c_el.get("form") or "normal") != "normal"
                    or set(g.preds.get(c_id, [])) != {b_id}
                    or any((g.nodes.get(m) or {}).get("kind") != "right" for m in _succ.get(c_id, []))
                ):
                    continue
                c_node["absorbed"] = True
                b_el = dict(b_node.get("el") or {})
                b_el["output"] = str(c_el.get("var") or "")
                b_node["el"] = b_el
            return g

        def rung_outputs_label(g: LDGraph) -> str:
            names: list[str] = []
            for n in effect_nodes(g, live_nodes(g)):
                el = g.nodes[n].get("el") or {}
                k = str(el.get("kind") or "")
                nm = str(el.get("var") or el.get("dest") or el.get("target") or el.get("op") or k)
                lab = nm if k == "coil" else f"{k} {nm}".strip()
                if lab not in names:
                    names.append(lab)
            return ", ".join(names[:4]) + (" …" if len(names) > 4 else "") if names else "no outputs"

        def prune_dead(g: LDGraph, els: list[dict[str, Any]], rung_no: int) -> list[dict[str, Any]]:
            """v0.3.18 (Deflector P3-1): drop contacts that power nothing (dead ends left by an
            edit in another tool) so the drawing / print matches the logic; warn naming them.
            The pruned rung is verified again; if that fails the original is kept."""
            live = live_nodes(g)
            dead = {
                n for n, nd in g.nodes.items()
                if nd.get("kind") == "contact" and n not in live
            }
            if not dead:
                return els
            dropped: list[str] = []

            def walk(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
                out_i: list[dict[str, Any]] = []
                for it in items:
                    k = str(it.get("kind") or "").lower()
                    if k == "contact" and str(it.get("_nid")) in dead:
                        dropped.append(("/" if str(it.get("form") or "").upper() == "NC" else "") + str(it.get("var") or "?"))
                        continue
                    if k == "or":
                        brs = [walk(list(b or [])) for b in it.get("branches") or []]
                        brs = [b for b in brs if b]
                        if not brs:
                            continue
                        if len(brs) == 1:
                            out_i.extend(brs[0])
                            continue
                        out_i.append({**it, "branches": brs})
                        continue
                    out_i.append(it)
                return out_i

            pruned = walk(list(els))
            # v0.3.19 (Deflector P3-a): name EVERY dead-end contact of the wiring, also those
            # the rebuild never placed in the rung (MotorStarter with a bypassed Stop gave no
            # warning at all, hint-less).
            all_dead = sorted(
                ("/" if str((g.nodes[n].get("el") or {}).get("form") or "").upper() == "NC" else "")
                + str((g.nodes[n].get("el") or {}).get("var") or "?")
                + f" (localId {n})"
                for n in dead
            )
            result = els
            if dropped:
                try:
                    ok_p, _w = verify_elements(g, pruned)
                except GraphImportError:
                    ok_p = False
                if ok_p:
                    result = pruned
            ladder["meta"].setdefault("import_warnings", []).append(
                f"WARNING {_body_prefix}rung {rung_no}: contact(s) {', '.join(all_dead)} are not connected "
                "to anything that they could power (a dead end in the LD wiring), so they have no effect "
                "and are not part of this rung's logic. A wire was probably removed or bypassed in "
                "another tool. Check this rung by hand."
            )
            return result

        def verified_rung_elements(
            left_node: ET.Element | None,
            bfs_elements: list[dict[str, Any]],
            rung_no: int,
            prefer_rebuild: bool,
            *,
            graph: LDGraph | None = None,
            context: str = "",
        ) -> list[dict[str, Any]]:
            """v0.3.16 verify-and-refuse: keep the BFS result only when its truth table
            matches the source wiring; else rebuild series-parallel; else refuse."""
            g = graph if graph is not None else build_rung_graph(left_node)  # type: ignore[arg-type]
            why = ""
            try:
                bridge = bridged_fan_in(g)
                if bridge:
                    raise GraphImportError(f"{GRAPH_REFUSE_PREFIX}: {bridge}")
                if not prefer_rebuild:
                    ok, why = verify_elements(g, bfs_elements)
                    if ok:
                        return prune_dead(g, bfs_elements, rung_no)
                rebuilt = reconstruct_elements(g)
                ok2, why2 = verify_elements(g, rebuilt)
            except GraphImportError as exc:
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX} at {_body_prefix}rung {rung_no} ({rung_outputs_label(g)}){context}: "
                    f"{str(exc).replace(GRAPH_REFUSE_PREFIX + ': ', '')}"
                ) from None
            if ok2:
                return prune_dead(g, rebuilt, rung_no)
            raise GraphImportError(
                f"{GRAPH_REFUSE_PREFIX} at {_body_prefix}rung {rung_no} ({rung_outputs_label(g)}){context}: "
                f"{why2 or why}. Nothing was imported. "
                "The rung could not be rebuilt exactly from the PLCopen wiring, so importing it "
                "could make an output energize when the source logic does not. Re-export from "
                "Cabinet Studio (keeps the lossless hint) or simplify the rung, and check every "
                "imported rung by hand."
            )

        def is_fb_block(node: ET.Element) -> bool:
            return (
                is_timer_block(node)
                or is_counter_block(node)
                or is_oneshot_block(node)
                or is_compare_block(node)
                or is_math_block(node)
            )

        # TC6 <comment> objects: attach each to the next leftPowerRail in document order.
        rail_comments: dict[int, str] = {}
        pending: list[str] = []
        for child in list(ld):
            local = _local(child.tag)
            if local == "comment":
                content = find_child(child, "content")
                lines: list[str] = []
                if content is not None:
                    paras = [c for c in content.iter() if _local(c.tag) == "p"]
                    if paras:
                        lines = ["".join(p.itertext()) for p in paras]
                    else:
                        lines = ["".join(content.itertext()).strip()]
                text_c = "\n".join(lines).strip()
                if text_c:
                    pending.append(text_c)
            elif local == "leftPowerRail" and pending:
                rail_comments[id(child)] = "\n".join(pending)
                pending = []

        def note_from_doc(node: ET.Element) -> str:
            raw = _read_doc_text(node)
            if NOTE_PREFIX.strip() in raw:
                return raw.split(NOTE_PREFIX.strip(), 1)[1].strip()
            return ""

        def legacy_comment_doc(node: ET.Element) -> str:
            raw = _read_doc_text(node)
            return "" if raw.startswith(NOTE_PREFIX.strip()) else raw

        def is_oneshot_block(node: ET.Element) -> bool:
            return _local(node.tag) == "block" and str(node.get("typeName") or "").upper() in ONESHOT_TYPES

        def oneshot_el(node: ET.Element) -> dict[str, Any]:
            import re as _re_inst

            from cabinet_studio.services.ladder_ir import _oneshot_el

            typ = str(node.get("typeName") or "R_TRIG").upper()
            instance = str(node.get("instanceName") or "").strip() or typ
            raw = _read_doc_text(node)
            # documentation text (xhtml or plain)
            blk = {"R_TRIG": "ONS", "F_TRIG": "OSF"}.get(typ, typ)
            storage, output = instance, ""
            if raw.startswith("ONESHOT "):
                bits = raw.split()
                doc_blk = (bits[1] if len(bits) > 1 else blk).upper()
                # v0.3.17 NEW-3: the doc may refine R_TRIG to ONS / OSR, but never
                # contradict the executable typeName (F_TRIG ⇒ OSF).
                if typ == "F_TRIG":
                    blk = "OSF"
                elif typ == "R_TRIG":
                    blk = doc_blk if doc_blk in {"ONS", "OSR"} else "ONS"
                else:
                    blk = typ if typ in {"ONS", "OSR", "OSF"} else doc_blk
                _auto_inst = not node.get("instanceName") or _re_inst.fullmatch(
                    r"(?:ONS|OSR|OSF|R_TRIG|F_TRIG)_\d+", instance
                )
                for tok in bits[2:]:
                    if tok.startswith("storage="):
                        # v0.3.18 (Audit P3-D): the instanceName is the executable storage
                        # bit; the doc storage= is used only for an auto-generated name.
                        if _auto_inst:
                            storage = tok.split("=", 1)[1] or storage
                    elif tok.startswith("output="):
                        output = tok.split("=", 1)[1]
            elif blk == "OSF":
                output = f"{instance}_Q"
            el = _oneshot_el(blk, storage, output)
            note = note_from_doc(node)
            if note:
                el["desc"] = note
            return el

        # v0.3.17 NEW-6: rungs are independent in Cabinet Studio. A wire from one rail's
        # network into another's (LD: one network, Y = A OR B) cannot be split into
        # separate rungs without changing the logic — refuse the whole file.
        _rail_ids = {str(n.get("localId") or "") for n in lefts}
        _owner: dict[str, int] = {}
        for _ri, _left in enumerate(lefts, start=1):
            _seen_r: set[str] = set()
            _stack = [str(_left.get("localId") or "")]
            while _stack:
                _cur = _stack.pop()
                if _cur in _seen_r:
                    continue
                _seen_r.add(_cur)
                _stack.extend(forward.get(_cur) or [])
            for _nid in _seen_r:
                _nd = by_id.get(_nid)
                if _nd is None or _nid in _rail_ids or _local(_nd.tag) == "rightPowerRail":
                    continue
                if _nid in _owner and _owner[_nid] != _ri:
                    _what = _local(_nd.tag)
                    _var = _var_name_from_node(_nd) or str(_nd.get("typeName") or "")
                    raise GraphImportError(
                        f"{GRAPH_REFUSE_PREFIX}: {_body_prefix}rungs {_owner[_nid]} and {_ri} are wired together "
                        f"(<{_what}> {_var} localId {_nid} is powered from both rails). Cabinet "
                        "Studio rungs are independent, so splitting this network would change the "
                        "logic. Nothing was imported. Merge the network into one rung and export again."
                    )
                _owner[_nid] = _ri

        # v0.3.18: a contact or coil with no variable cannot be imported. The rebuild used
        # to drop such a contact silently, making the rest of the rung unconditional (a
        # guard contact with its tag erased → the coil always ON). Refuse; never guess.
        _novar = [
            c for c in list(ld)
            if _local(c.tag) in {"contact", "coil"} and c.get("localId") and not _var_name_from_node(c)
        ]
        if _novar:
            _desc = ", ".join(f"<{_local(c.tag)}> localId {c.get('localId')}" for c in _novar[:6])
            raise GraphImportError(
                f"{GRAPH_REFUSE_PREFIX}: {len(_novar)} {_body_prefix.strip() + ' ' if _body_prefix else ''}"
                f"LD contact/coil object(s) have no variable (tag name): {_desc}"
                f"{' …' if len(_novar) > 6 else ''}. Cabinet Studio will not guess what they read or "
                "write, and dropping them would change the rung. Nothing was imported."
            )

        # v0.3.19 (Deflector P1-B): account for every REFERENCE, not only every object.
        # A connection to a localId that does not exist in this body used to be skipped
        # silently: a reset coil lost its E-stop branch with zero warnings. Duplicate
        # localIds are the same guess in another form (which object did the wire mean?).
        _dangling_refs: list[str] = []
        _lpos = [i for i, c in enumerate(list(ld)) if _local(c.tag) == "leftPowerRail"]
        for _ci, _c in enumerate(list(ld)):
            _lid = str(_c.get("localId") or "")
            for _cpi in _c.iter():
                if _local(_cpi.tag) != "connection":
                    continue
                _ref = str(_cpi.get("refLocalId") or "")
                if _ref and _ref not in by_id:
                    _nm = _var_name_from_node(_c) or str(_c.get("instanceName") or _c.get("typeName") or "")
                    _ri_own = _owner.get(_lid)
                    if _ri_own:
                        _rung = f"{_body_prefix}rung {_ri_own}"
                    else:  # not powered by any rail: say where it sits in the document
                        _nb = sum(1 for _p in _lpos if _p < _ci)
                        _rung = (
                            f"not on any rail, after {_body_prefix}rung {_nb}" if _nb
                            else f"not on any rail, before {_body_prefix}rung 1"
                        )
                    _dangling_refs.append(
                        f"{_rung}: <{_local(_c.tag)}> {_nm} (localId {_lid or '?'}) is wired to missing localId {_ref}"
                        .replace("  ", " ")
                    )
        # v0.3.19: a wire that LEAVES a right power rail (an object fed from the right rail)
        # has no meaning in LD; the rebuild crashed (KeyError) on it. Refuse, naming it.
        _from_right = []
        for _c in list(ld):
            for _cpi in _c.iter():
                if _local(_cpi.tag) != "connection":
                    continue
                _ref = str(_cpi.get("refLocalId") or "")
                if _ref in by_id and _local(by_id[_ref].tag) == "rightPowerRail" and _c is not by_id[_ref]:
                    _from_right.append(
                        f"<{_local(_c.tag)}> {_var_name_from_node(_c) or _c.get('typeName') or ''} "
                        f"(localId {_c.get('localId') or '?'}) is wired from right power rail localId {_ref}"
                        .replace("  ", " ")
                    )
        if _from_right:
            raise GraphImportError(
                f"{GRAPH_REFUSE_PREFIX}: {_body_prefix}{len(_from_right)} wire(s) start at a RIGHT power "
                f"rail: {'; '.join(_from_right[:6])}{' …' if len(_from_right) > 6 else ''}. Power cannot "
                "flow out of the right rail; the file is damaged or was edited by hand. Nothing was imported."
            )
        if _dangling_refs and lefts:  # no rail at all: the clearer no-rail refusal below
            raise GraphImportError(
                f"{GRAPH_REFUSE_PREFIX}: {len(_dangling_refs)} wire(s) refer to LD objects that do not "
                f"exist: {'; '.join(_dangling_refs[:6])}{' …' if len(_dangling_refs) > 6 else ''}. The "
                "missing object was deleted or the file is damaged; Cabinet Studio will not guess what "
                "it was (it could be an E-stop or a rail). Nothing was imported."
            )

        if lefts:
            # v0.3.18 NEW-8: every LD object must belong to a rung. An object that no left
            # rail powers (e.g. a rung whose rail was deleted) used to vanish silently —
            # an E-stop or interlock rung could disappear. Refuse the whole file instead.
            _reach_all: set[str] = set()
            _stk = [str(n.get("localId") or "") for n in lefts]
            while _stk:
                _cur = _stk.pop()
                if _cur in _reach_all:
                    continue
                _reach_all.add(_cur)
                _stk.extend(forward.get(_cur) or [])
            _orphans = [
                c for c in list(ld)
                if _local(c.tag) in {"contact", "coil", "block"}
                and c.get("localId")
                and str(c.get("localId")) not in _reach_all
            ]
            if _orphans:
                _pos = {id(c): i for i, c in enumerate(list(ld))}
                _first = min(_pos[id(o)] for o in _orphans)
                _before = sum(1 for n in lefts if _pos[id(n)] < _first)
                _names = []
                for _o in _orphans[:6]:
                    _nm = _var_name_from_node(_o) or str(_o.get("instanceName") or _o.get("typeName") or "")
                    _names.append(f"<{_local(_o.tag)}> {_nm} (localId {_o.get('localId')})".replace("  ", " "))
                _at = (
                    f"after {_body_prefix}rung {_before}" if _before else f"before {_body_prefix}rung 1"
                ) if _before < len(lefts) else f"after the last {_body_prefix}rung"
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX}: {len(_orphans)} LD object(s) {_at} are not connected to any "
                    f"left power rail: {', '.join(_names)}{' …' if len(_orphans) > 6 else ''}. A rung's "
                    "left rail is missing or its wiring is broken; importing only the other rungs would "
                    "silently drop that logic (it could be an E-stop or interlock rung). Nothing was "
                    "imported. Repair the rung in the source tool and export again."
                )

        if lefts:
            # v0.3.19 (Raddus deleted-object fuzz): a contact that is powered but drives no
            # coil / block (a dead end) is refused. A deleted wire looks exactly like this —
            # the wire from an OR branch (e.g. an E-stop) into a reset coil, or a coil rewired
            # around its Stop contact — and the importer cannot tell a harmless leftover from
            # a lost branch. 0.3.18 dropped it with a warning; never guess.
            _sinks = {
                lid for lid, nd in by_id.items() if _local(nd.tag) in {"coil", "block"}
            }
            _dead_ends: list[str] = []
            from cabinet_studio.services.ladder_ir import COMPARE_OPS as _CMP_D, normalize_oneshot_block as _nob_d

            def _is_condition_block(nd: ET.Element) -> bool:
                # input-type blocks (compare, ONS) are conditions like a contact: they must
                # drive something. Output blocks (timers, counters, math, OSR/OSF, JSR ...)
                # may legitimately end a rung.
                t = str(nd.get("typeName") or "").strip().upper()
                return t in _CMP_D or (t in ONESHOT_TYPES and _nob_d(t) not in {"OSR", "OSF"})

            for _c in list(ld):
                if not _c.get("localId"):
                    continue
                if _local(_c.tag) == "block":
                    if not _is_condition_block(_c):
                        continue
                elif _local(_c.tag) != "contact":
                    continue
                _seen_d: set[str] = set()
                _stk_d = list(forward.get(str(_c.get("localId"))) or [])
                _live = False
                while _stk_d and not _live:
                    _cur = _stk_d.pop()
                    if _cur in _seen_d:
                        continue
                    _seen_d.add(_cur)
                    if _cur in _sinks:
                        _live = True
                        break
                    _stk_d.extend(forward.get(_cur) or [])
                if not _live:
                    _lid_d = str(_c.get("localId"))
                    if _local(_c.tag) == "block":
                        _tg = "block"
                        _nm = f"{_c.get('typeName') or ''} {_c.get('instanceName') or ''}".strip() or "?"
                    else:
                        _tg = "contact"
                        _nm = ("/" if str(_c.get("negated") or "").lower() == "true" else "") + (_var_name_from_node(_c) or "?")
                    _r_d = _owner.get(_lid_d)
                    _dead_ends.append(
                        f"{_body_prefix}rung {_r_d}: <{_tg}> {_nm} (localId {_lid_d})" if _r_d
                        else f"{_body_prefix}<{_tg}> {_nm} (localId {_lid_d})"
                    )
            if _dead_ends:
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX}: {len(_dead_ends)} contact(s) / condition block(s) drive nothing — their output is "
                    f"not wired to any coil or block: {'; '.join(_dead_ends[:6])}"
                    f"{' …' if len(_dead_ends) > 6 else ''}. A wire was probably deleted or rerouted in "
                    "another tool (an OR branch such as an E-stop into a reset coil, or a coil rewired "
                    "around its Stop contact look exactly like this), so Cabinet Studio will not guess "
                    "what the rung meant. Nothing was imported. Repair the wiring and export again."
                )

        # v0.3.19 (Raddus deleted-object fuzz): a one-shot block whose Cabinet Studio note
        # names an output bit ("ONESHOT OSR ... output=X") must really drive coil X from its
        # Q pin. With the coil deleted, 0.3.18 rebuilt the output from the note alone (an
        # unverified comment deciding logic). Refuse; the note never replaces a wire.
        for _b in list(ld):
            if _local(_b.tag) != "block" or not _b.get("localId"):
                continue
            _raw_b = _read_doc_text(_b)
            if not _raw_b.startswith("ONESHOT "):
                continue
            _out_b = next((t.split("=", 1)[1] for t in _raw_b.split()[2:] if t.startswith("output=")), "")
            if not _out_b:
                continue
            _bl = str(_b.get("localId"))
            _driven = [
                _var_name_from_node(c) for c in list(ld)
                if _local(c.tag) == "coil"
                and any(_local(x.tag) == "connection" and str(x.get("refLocalId") or "") == _bl for x in c.iter())
            ]
            if _out_b not in _driven:
                _r_b = _owner.get(_bl)
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX}: {_body_prefix}{'rung ' + str(_r_b) + ': ' if _r_b else ''}one-shot "
                    f"{_b.get('typeName') or ''} {_b.get('instanceName') or ''} (localId {_bl}) is noted as "
                    f"driving output bit {_out_b}, but no coil {_out_b} is wired to its Q pin"
                    f"{' (its Q drives: ' + ', '.join(_driven) + ')' if _driven else ''}. The coil was "
                    "deleted or rewired; Cabinet Studio will not rebuild logic from a note. Nothing was "
                    "imported."
                )

        if not lefts:
            # v0.3.19 (Deflector P1-A, Raddus: never guess the left rail). A body with LD
            # objects but no leftPowerRail is refused. 0.3.17/0.3.18 treated the single
            # missing id as "the rail" — when the deleted object was the first series Stop /
            # E-stop contact, the rung imported without it and was called verified.
            _objs = [
                c for c in list(ld)
                if _local(c.tag) in {"contact", "coil", "block"} and c.get("localId")
            ]
            if _objs:
                _names_a = [
                    f"<{_local(o.tag)}> {_var_name_from_node(o) or o.get('instanceName') or o.get('typeName') or ''}"
                    f" (localId {o.get('localId')})".replace("  ", " ")
                    for o in _objs[:6]
                ]
                _used = {_var_name_from_node(o) for o in _objs if _local(o.tag) == "contact"}
                _unused_in = sorted(
                    str(v.get("name")) for v in variables
                    if v.get("class") == "input" and str(v.get("type") or "BOOL") == "BOOL"
                    and str(v.get("name")) not in _used
                )
                _sig = (
                    f" Declared input(s) {', '.join(_unused_in[:6])} are used by no contact — a deleted "
                    "contact (e.g. a Stop or E-stop) is likely."
                    if _unused_in else ""
                )
                raise GraphImportError(
                    f"{GRAPH_REFUSE_PREFIX}: {_body_prefix}LD body has no left power rail "
                    f"({len(_objs)} LD object(s): {', '.join(_names_a)}{' …' if len(_objs) > 6 else ''}). "
                    "Every LD network must start at a left rail; Cabinet Studio will not guess which "
                    f"object was the rail (a deleted first contact looks the same).{_sig} Nothing was "
                    "imported. Repair the rungs in the source tool and export again."
                )
            continue

        for left in lefts:
            _where["label"] = f"{_body_prefix}rung {len(rungs_out) + 1}"
            elements: list[dict[str, Any]] = []
            comment = rail_comments.get(id(left), "") if left is not None else ""
            xml_comment = comment
            hint_context = ""
            if left is not None:
                raw_doc = _read_doc_text(left)
                if raw_doc.startswith("cabinet-studio-elements:"):
                    payload = {}
                    try:
                        payload = json.loads(raw_doc.split(":", 1)[1])
                        from cabinet_studio.services.ladder_ir import (
                            clean_elements,
                            elements_have_mid_rung_coil,
                            elements_have_nested_or,
                            elements_need_storage,
                        )

                        elements = clean_elements(payload.get("elements") or [])
                        comment = str(payload.get("comment") or "") or xml_comment
                    except Exception:
                        elements = []
                        comment = ""
                        ladder["meta"].setdefault("import_warnings", []).append(
                            f"WARNING {_body_prefix}rung {len(rungs_out) + 1}: the Cabinet Studio hint could not be "
                            "read (damaged?) — the rung was rebuilt from the LD wiring and verified. "
                            "Check this rung by hand."
                        )
                    # Prefer lossless hint when OR groups or other non-classic shapes exist.
                    # CRITICAL (P1-8 safety): OR + series NC (seal-in) looks "simple" to
                    # classic fields, but LD BFS fan-in duplicates the series contact as
                    # OR(STOP|STOP) and can collapse into the seal — prefer the hint
                    # whenever any top-level OR is present. Counter-only rungs (no OR)
                    # still walk the LD graph so foreign CTUD edits apply.
                    has_or = any(str(e.get("kind") or "").lower() == "or" for e in elements)
                    # v0.3.16: the hint is trusted only when it still matches the LD wiring
                    # (truth table, node-to-node). A third-party edit of the graph that left
                    # a stale hint falls through to the verified hint-less path.
                    # v0.3.17 NEW-3: (1) the wiring hash stored at export must still match
                    # (any edit to the rung body in another tool ⇒ ignore the hint); (2) the
                    # hint's coils / blocks map 1:1 onto the wiring (count, kind, coil tag);
                    # (3) exact power AND settings check (coil form, block parameters).
                    # Hints without a hash (older files) get (2) + (3). Any failure: the
                    # hint is ignored for this rung (coil types and block settings too),
                    # the rung is rebuilt from the wiring, verified, and a warning names it.
                    hint_ok = True
                    hint_why = ""
                    _hg = None
                    if elements:
                        try:
                            _hg = build_rung_graph(left)
                            _wh = payload.get("wh") if isinstance(payload, dict) else None
                            if _wh is not None:
                                _now = rung_wiring_hash(
                                    _rung_object_list(list(ld), str(left.get("localId") or ""))
                                )
                                if str(_wh) != _now:
                                    hint_ok = False
                                    hint_why = "the rung wiring changed after export (wiring hash mismatch)"
                            if hint_ok:
                                _tagged = tag_effects_in_order(_hg, elements)
                                if _tagged is None:
                                    hint_ok = False
                                    hint_why = "its coils / blocks (count, kind or coil tag) differ from the wiring"
                                else:
                                    _ok, _why = verify_elements(_hg, _tagged)
                                    if not _ok:
                                        hint_ok = False
                                        hint_why = _why
                        except VerifyLimitError as exc:
                            # v0.3.18 (Audit P3-A): a size limit is not a hint mismatch.
                            _lab = rung_outputs_label(_hg) if _hg is not None else "?"
                            raise VerifyLimitError(
                                f"{GRAPH_REFUSE_PREFIX} at {_body_prefix}rung {len(rungs_out) + 1} ({_lab}): "
                                f"{str(exc).replace(GRAPH_REFUSE_PREFIX + ': ', '')}"
                            ) from None
                        except GraphImportError as exc:
                            hint_ok = False
                            hint_why = str(exc)
                        if not hint_ok:
                            _lab = rung_outputs_label(_hg) if _hg is not None else "?"
                            # v0.3.19 (deleted-object fuzz): name what the hint has that the
                            # wiring lacks (a deleted Stop / seal branch) and vice versa.
                            _diff_txt = ""
                            if _hg is not None:
                                _h = _element_objs(elements)
                                _w = _element_objs([])
                                for _n in _hg.nodes.values():
                                    _k = str(_n.get("kind") or "")
                                    _e = _n.get("el") or {}
                                    if _k in {"contact", "coil"}:
                                        _pre = "/" if str(_e.get("form") or "").upper() == "NC" else ""
                                        _w[f"<{_k}> {_pre}{_e.get('var')}"] += 1
                                _miss = sorted((_h - _w).elements())
                                _extra = sorted((_w - _h).elements())
                                if _miss:
                                    _diff_txt += (
                                        f" The hint has {', '.join(_miss[:6])} that the wiring does NOT have "
                                        "(deleted in another tool?)."
                                    )
                                if _extra:
                                    _diff_txt += f" The wiring has {', '.join(_extra[:6])} that the hint does not."
                            ladder["meta"].setdefault("import_warnings", []).append(
                                f"WARNING {_body_prefix}rung {len(rungs_out) + 1} ({_lab}): Cabinet Studio hint did "
                                f"not match the LD wiring — {hint_why}.{_diff_txt} The hint was IGNORED for this "
                                "rung (coil types and block settings come from the wiring); the rung "
                                "was rebuilt from the wiring and verified. Check this rung by hand."
                            )
                            hint_context = " (Cabinet Studio hint ignored: it did not match the wiring)"
                    if elements and hint_ok and (
                        has_or
                        or elements_have_nested_or(elements)
                        or elements_have_mid_rung_coil(elements)
                        or elements_need_storage(elements)
                    ):
                        if _hg is not None:  # v0.3.19: dead ends are named on the hint path too
                            elements = prune_dead(_hg, elements, len(rungs_out) + 1)
                        rungs_out.append(
                            {
                                "id": str(len(rungs_out) + 1),
                                "comment": comment,
                                "elements": elements,
                                "_rail": str(left.get("localId") or ""),
                            }
                        )
                        continue
                    elements = []
                    comment = xml_comment
            start_id = left.get("localId") or ""
            # BFS layers; when a node has multiple successors that are contacts, emit OR
            frontier = list(forward.get(start_id) or [])
            visited: set[str] = set()
            guard = 0
            needs_rebuild = False
            while frontier and guard < 500:
                guard += 1
                # Dedupe fan-in (seal-in series contact is referenced from every OR branch).
                frontier = list(dict.fromkeys(frontier))
                # Split contacts vs coils vs rails at this frontier
                contact_ids = []
                coil_ids = []
                timer_ids = []
                other = []
                for nid in frontier:
                    if nid in visited:
                        continue
                    node = by_id.get(nid)
                    if node is None:
                        continue
                    if is_contact(node):
                        contact_ids.append(nid)
                    elif is_fb_block(node):
                        timer_ids.append(nid)
                    elif is_coil(node):
                        coil_ids.append(nid)
                    elif _local(node.tag) == "rightPowerRail":
                        continue
                    else:
                        other.append(nid)

                if len(contact_ids) > 1:
                    # v0.3.12: series-aware OR — walk each fan-out branch as a
                    # chain until a join node (multiple predecessors). Fixes
                    # TwoHandStart pure-XML import that previously collapsed
                    # (L·R·/locks | Cycle)·/Stop into (L|Cycle)·(R|/Stop)·…
                    reverse: dict[str, list[str]] = {}
                    for src, dests in forward.items():
                        for d in dests:
                            reverse.setdefault(d, []).append(src)

                    def _el_from_node(nid: str) -> dict[str, Any] | None:
                        node = by_id.get(nid)
                        if node is None:
                            return None
                        if is_contact(node):
                            if legacy_comment_doc(node) and not comment:
                                # nonlocal comment updated by outer scope via closure assign below
                                pass
                            return contact_el(node)
                        if is_fb_block(node):
                            return fb_el(node)
                        if is_coil(node):
                            return coil_el(node)
                        return None

                    def _starts_reaching_join(
                        starts: list[str], join: str
                    ) -> list[str]:
                        """Which OR-start contacts can reach ``join`` via LD edges."""
                        hit: list[str] = []
                        for s in starts:
                            seen_b: set[str] = set()
                            stack = [s]
                            while stack:
                                n = stack.pop()
                                if n in seen_b:
                                    continue
                                seen_b.add(n)
                                if n == join:
                                    hit.append(s)
                                    break
                                for nxt in forward.get(n) or []:
                                    nn = by_id.get(nxt)
                                    if nn is None:
                                        continue
                                    if is_coil(nn) or _local(nn.tag) == "rightPowerRail":
                                        continue
                                    stack.append(nxt)
                        return hit

                    def _early_join_clusters(
                        starts: list[str],
                    ) -> list[tuple[list[str], str]] | None:
                        """If some starts join at an intermediate contact before others, return
                        clusters (subset, join_id). Used for ((X2|X3)·X1)|X4 graphs."""
                        if len(starts) < 3:
                            return None
                        clusters: list[tuple[list[str], str]] = []
                        used: set[str] = set()
                        # Candidate joins: contacts with ≥2 preds reachable from starts
                        for nid, node in list(by_id.items()):
                            if not is_contact(node):
                                continue
                            if len(set(reverse.get(nid) or [])) < 2:
                                continue
                            reaching = _starts_reaching_join(starts, nid)
                            if len(reaching) < 2 or len(reaching) >= len(starts):
                                continue
                            # Prefer joins whose preds are among the reaching starts' frontier
                            if any(r in used for r in reaching):
                                continue
                            clusters.append((reaching, nid))
                            used.update(reaching)
                        return clusters or None

                    branches = []
                    branch_ends: list[str] = []
                    # v0.3.20 (fuzz seed 298084): branch order follows the file (lowest
                    # localId of each branch's first instruction). Cluster branches (those
                    # opening with a nested OR) used to be emitted before plain branches.
                    branch_keys: list[tuple[int, str]] = []

                    def _id_key(nid: str) -> tuple[int, str]:
                        return (int(nid), nid) if str(nid).isdigit() else (10**9, str(nid))

                    _clusters = _early_join_clusters(contact_ids)
                    _cluster_starts: set[str] = set()
                    if _clusters:
                        for _subset, _join in _clusters:
                            _cluster_starts.update(_subset)
                        # Emit one branch per cluster: nested OR of subset + series from join
                        for subset, join_id in _clusters:
                            sub_branches = []
                            sub_ends = []
                            for sc in subset:
                                if sc in visited:
                                    continue
                                sub_chain = [sc]
                                visited.add(sc)
                                scur = sc
                                while True:
                                    ssuccs = [s for s in (forward.get(scur) or []) if s not in visited]
                                    if len(ssuccs) != 1:
                                        if len(ssuccs) > 1:
                                            # v0.3.16 (H-DEEP): nested OR inside a cluster
                                            # sub-branch — rebuild with the recursive
                                            # series-parallel decomposition (any depth).
                                            needs_rebuild = True
                                        break
                                    snxt = ssuccs[0]
                                    if snxt == join_id:
                                        break
                                    if len(set(reverse.get(snxt) or [])) > 1:
                                        break
                                    nnd = by_id.get(snxt)
                                    if nnd is None or is_coil(nnd) or _local(nnd.tag) == "rightPowerRail":
                                        break
                                    if is_fb_block(nnd):
                                        break
                                    if not is_contact(nnd):
                                        break
                                    sub_chain.append(snxt)
                                    visited.add(snxt)
                                    scur = snxt
                                sub_els = []
                                for nid in sub_chain:
                                    el = _el_from_node(nid)
                                    if el is not None:
                                        sub_els.append(el)
                                if sub_els:
                                    sub_branches.append(sub_els)
                                    sub_ends.append(scur)
                            branch_els = []
                            if sub_branches:
                                branch_els.append({"kind": "or", "branches": sub_branches})
                            # Series from join_id onward until top-level merge.
                            # v0.3.15 (REG-5): after the cluster join, only consume a node
                            # when EVERY predecessor is the node we just consumed. Visited
                            # predecessors from other top-level branches are foreign too.
                            walk = join_id
                            last = join_id
                            own_prev: str | None = None
                            while walk and walk not in visited:
                                nnd = by_id.get(walk)
                                if nnd is None:
                                    break
                                if is_coil(nnd) or _local(nnd.tag) == "rightPowerRail":
                                    break
                                preds_w = set(reverse.get(walk) or [])
                                if walk != join_id and preds_w != {own_prev}:
                                    break
                                if is_contact(nnd) or is_fb_block(nnd):
                                    el = _el_from_node(walk)
                                    if el is not None:
                                        branch_els.append(el)
                                visited.add(walk)
                                last = walk
                                own_prev = walk
                                ssuccs = [s for s in (forward.get(walk) or []) if s not in visited]
                                if len(ssuccs) != 1:
                                    break
                                walk = ssuccs[0]
                            if branch_els:
                                branches.append(branch_els)
                                branch_ends.append(last)
                                branch_keys.append(min(_id_key(s) for s in subset))
                    for cid in contact_ids:
                        if cid in visited:
                            continue
                        if cid in _cluster_starts:
                            continue
                        chain_ids = [cid]
                        visited.add(cid)
                        node0 = by_id[cid]
                        if legacy_comment_doc(node0) and not comment:
                            comment = legacy_comment_doc(node0)
                        cur = cid
                        nested_or_el = None
                        while True:
                            succs = [s for s in (forward.get(cur) or []) if s not in visited]
                            if len(succs) != 1:
                                # v0.3.13: fan-out of contacts inside a branch = nested OR
                                contact_succs = [
                                    s for s in succs
                                    if by_id.get(s) is not None and is_contact(by_id[s])
                                ]
                                if len(contact_succs) > 1 and all(
                                    len(set(reverse.get(s) or [])) <= 1 for s in contact_succs
                                ):
                                    sub_branches = []
                                    sub_ends = []
                                    for sc in contact_succs:
                                        sub_chain = [sc]
                                        visited.add(sc)
                                        scur = sc
                                        while True:
                                            ssuccs = [s for s in (forward.get(scur) or []) if s not in visited]
                                            if len(ssuccs) != 1:
                                                break
                                            snxt = ssuccs[0]
                                            if len(set(reverse.get(snxt) or [])) > 1:
                                                break
                                            if by_id.get(snxt) is None:
                                                break
                                            # Stop before coils/rails for nested contact chain
                                            nnd = by_id[snxt]
                                            if is_coil(nnd) or _local(nnd.tag) == "rightPowerRail":
                                                break
                                            if is_fb_block(nnd):
                                                break
                                            sub_chain.append(snxt)
                                            visited.add(snxt)
                                            scur = snxt
                                        sub_els = []
                                        for nid in sub_chain:
                                            el = _el_from_node(nid)
                                            if el is not None:
                                                sub_els.append(el)
                                        if sub_els:
                                            sub_branches.append(sub_els)
                                            sub_ends.append(scur)
                                    if sub_branches:
                                        nested_or_el = {"kind": "or", "branches": sub_branches}
                                        # v0.3.14: continue AFTER the nested-OR join (X5 in
                                        # X1·(X2|X3)·X5) instead of stopping at sub_ends[0].
                                        common: set[str] | None = None
                                        for end in sub_ends:
                                            sset = set(forward.get(end) or [])
                                            common = sset if common is None else (common & sset)
                                        post_from_join: list[str] = []
                                        last_consumed: str | None = None
                                        if common:
                                            join_nodes = [
                                                n for n in common
                                                if len(set(reverse.get(n) or [])) > 1
                                            ]
                                            join = (
                                                join_nodes[0]
                                                if join_nodes
                                                else (next(iter(common)) if len(common) == 1 else None)
                                            )
                                            # v0.3.15 (REG-5): a node is "ours" (series after the
                                            # nested OR) only when EVERY predecessor is one of the
                                            # nested branch's own ends (for the join) or the node
                                            # we just consumed (afterwards). A visited predecessor
                                            # from a sibling top-level branch (e.g. PB_Start in
                                            # (PB_Start | M1(Auto|Manual))·/PB_Stop) makes the
                                            # node the OUTER join, which stays in series after the
                                            # whole OR — never pulled into this branch.
                                            own: set[str] = set(sub_ends)
                                            walk = join
                                            while walk and walk not in visited:
                                                nnd = by_id.get(walk)
                                                if nnd is None:
                                                    break
                                                if is_coil(nnd) or _local(nnd.tag) == "rightPowerRail":
                                                    break
                                                preds_w = set(reverse.get(walk) or [])
                                                if not preds_w or not preds_w <= own:
                                                    break
                                                if is_fb_block(nnd) or is_contact(nnd):
                                                    post_from_join.append(walk)
                                                visited.add(walk)
                                                last_consumed = walk
                                                own = {walk}
                                                ssuccs = [
                                                    s for s in (forward.get(walk) or [])
                                                    if s not in visited
                                                ]
                                                if len(ssuccs) != 1:
                                                    break
                                                walk = ssuccs[0]
                                        # stash post ids on nested_or_el for append below
                                        nested_or_el["_post_ids"] = post_from_join
                                        if last_consumed is not None:
                                            cur = last_consumed
                                        elif sub_ends:
                                            cur = sub_ends[0]
                                break
                            nxt = succs[0]
                            preds = reverse.get(nxt) or []
                            # Join: more than one incoming edge → leave for after the OR
                            if len(set(preds)) > 1:
                                break
                            if by_id.get(nxt) is None:
                                break
                            chain_ids.append(nxt)
                            visited.add(nxt)
                            nnode = by_id[nxt]
                            if is_contact(nnode) and legacy_comment_doc(nnode) and not comment:
                                comment = legacy_comment_doc(nnode)
                            cur = nxt
                        branch_els = []
                        for nid in chain_ids:
                            el = _el_from_node(nid)
                            if el is not None:
                                branch_els.append(el)
                        if nested_or_el is not None:
                            post_ids = list(nested_or_el.pop("_post_ids", []) or [])
                            branch_els.append(nested_or_el)
                            for nid in post_ids:
                                el = _el_from_node(nid)
                                if el is not None:
                                    branch_els.append(el)
                        if branch_els:
                            branches.append(branch_els)
                            branch_ends.append(cur)
                            branch_keys.append(_id_key(cid))
                    if len(branches) > 1 and len(branch_keys) == len(branches):
                        _order = sorted(range(len(branches)), key=lambda i: branch_keys[i])
                        branches = [branches[i] for i in _order]
                        branch_ends = [branch_ends[i] for i in _order]
                    if branches:
                        elements.append({"kind": "or", "branches": branches})
                    next_frontier: list[str] = []
                    for end in branch_ends:
                        for s in forward.get(end) or []:
                            if s not in visited:
                                next_frontier.append(s)
                    # Also pick up any timer/coil siblings that were on the same frontier
                    for tid in timer_ids:
                        if tid not in visited:
                            next_frontier.append(tid)
                    for coid in coil_ids:
                        if coid not in visited:
                            next_frontier.append(coid)
                    frontier = list(dict.fromkeys(next_frontier))
                elif len(contact_ids) == 1:
                    cid = contact_ids[0]
                    visited.add(cid)
                    node = by_id[cid]
                    if legacy_comment_doc(node) and not comment:
                        comment = legacy_comment_doc(node)
                    elements.append(contact_el(node))
                    frontier = [n for n in (forward.get(cid) or []) if n not in visited]
                    for tid in timer_ids:
                        if tid not in visited:
                            frontier.append(tid)
                    for coid in coil_ids:
                        if coid not in visited:
                            frontier.append(coid)
                else:
                    progressed = False
                    for tid in timer_ids:
                        if tid in visited:
                            continue
                        visited.add(tid)
                        elements.append(fb_el(by_id[tid]))
                        frontier = [n for n in (forward.get(tid) or []) if n not in visited]
                        progressed = True
                    if not progressed:
                        for coid in coil_ids:
                            if coid in visited:
                                continue
                            visited.add(coid)
                            elements.append(coil_el(by_id[coid]))
                            frontier = [n for n in (forward.get(coid) or []) if n not in visited]
                            progressed = True
                    if not progressed:
                        for oid in other:
                            visited.add(oid)
                            frontier = [n for n in (forward.get(oid) or []) if n not in visited]
                            progressed = True
                        if not progressed:
                            break

            if guard >= 500:
                needs_rebuild = True
            elements = verified_rung_elements(
                left, elements, len(rungs_out) + 1, needs_rebuild,
                context=hint_context or " (hint-less: rebuilt from the LD wiring)",
            )
            if elements:
                rungs_out.append(
                    {
                        "id": str(len(rungs_out) + 1),
                        "comment": comment,
                        "elements": elements,
                        "_rail": str(left.get("localId") or ""),
                    }
                )

        # v0.3.18 NEW-8: account for every rail. A rail that powers LD objects must have
        # produced a rung; an empty rail (nothing wired) is reported, never silent.
        if lefts:
            _made = {str(r.get("_rail")) for r in rungs_out if r.get("_rail") is not None}
            for _ri, _left in enumerate(lefts, start=1):
                _lid = str(_left.get("localId") or "")
                if _lid in _made:
                    continue
                _seen_l: set[str] = set()
                _stk2 = [_lid]
                while _stk2:
                    _cur = _stk2.pop()
                    if _cur in _seen_l:
                        continue
                    _seen_l.add(_cur)
                    _stk2.extend(forward.get(_cur) or [])
                _logic_l = [
                    n for n in _seen_l
                    if by_id.get(n) is not None and _local(by_id[n].tag) in {"contact", "coil", "block"}
                ]
                _effects_l = [n for n in _logic_l if _local(by_id[n].tag) in {"coil", "block"}]
                if _logic_l and not _effects_l:
                    # contacts only, driving nothing: no output can be lost — say so loudly
                    _cn = sorted({_var_name_from_node(by_id[n]) or n for n in _logic_l})
                    ladder["meta"].setdefault("import_warnings", []).append(
                        f"WARNING {_body_prefix}network {_ri} (left rail localId {_lid}) has only "
                        f"contact(s) {', '.join(_cn[:6])} that drive no coil or block; there was no "
                        "output to import, so the network was skipped. Check the source rung."
                    )
                    continue
                if _logic_l:
                    raise GraphImportError(
                        f"{GRAPH_REFUSE_PREFIX}: {_body_prefix}network {_ri} (left rail localId {_lid}) "
                        "is wired to LD objects but could not be turned into a rung. Nothing was imported."
                    )
                ladder["meta"].setdefault("import_warnings", []).append(
                    f"WARNING {_body_prefix}network {_ri} (left rail localId {_lid}) is empty — nothing is "
                    "wired to its left rail, so there was no logic to import."
                )

    rungs_out = main_rungs

    def _finish_rungs(rlist: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out_r: list[dict[str, Any]] = []
        for rung in rlist:
            out_r.append({k: v for k, v in rung.items() if k != "_rail"})
        return out_r

    cleaned = _finish_rungs(rungs_out)
    routines_wired = {name: _finish_rungs(rl) for name, rl in routine_rungs.items()}
    # Merge timer / counter instances discovered from blocks into the variable table.
    known = {str(v.get("name")) for v in ladder.get("variables") or []}
    for rung in cleaned + [r for rl in routines_wired.values() for r in rl]:
        for el in rung.get("elements") or []:
            if el.get("kind") == "counter":
                name = str(el.get("var") or "").strip()
                blk = normalize_counter_block(el.get("block"))
                if name and name not in known:
                    ladder.setdefault("variables", []).append(
                        {
                            "name": name,
                            "class": "counter",
                            "type": blk if blk in COUNTER_OWNER_BLOCKS else "CTU",
                            "address": "",
                            "pv": clamp_counter(el.get("pv", 0)) if blk != "RES" else 0,
                        }
                    )
                    known.add(name)
                continue
            if el.get("kind") != "timer":
                continue
            name = str(el.get("var") or "").strip()
            if name and name not in known:
                ladder.setdefault("variables", []).append(
                    {
                        "name": name,
                        "class": "timer",
                        "type": str(el.get("block") or "TON").upper(),
                        "address": "",
                        "pt_ms": max(0, int(el.get("pt_ms") or 0)),
                    }
                )
                known.add(name)
    for rung in cleaned:
        rung["elements"] = strip_nids(list(rung.get("elements") or []))
    for rl in routines_wired.values():
        for rung in rl:
            rung["elements"] = strip_nids(list(rung.get("elements") or []))
    ladder["rungs"] = cleaned
    warn = ladder["meta"].setdefault("import_warnings", [])
    # Restore v0.3.8 routines / aliases stamped on contentHeader (may follow G-AID note).
    meta_payload: dict[str, Any] = {}
    for node in root.iter():
        if _local(node.tag) != "Comment":
            continue
        raw = (node.text or "").strip()
        meta_line = ""
        for ln in raw.splitlines():
            if ln.strip().startswith("cabinet-studio-meta:"):
                meta_line = ln.strip()
                break
        if not meta_line and raw.startswith("cabinet-studio-meta:"):
            meta_line = raw
        if not meta_line:
            continue
        try:
            meta_payload = json.loads(meta_line[len("cabinet-studio-meta:"):])
        except Exception:
            meta_payload = {}
            warn.append(
                "WARNING: the Cabinet Studio metadata block (routines / tag aliases) could not be "
                "read (damaged?) and was ignored."
            )
        if not isinstance(meta_payload, dict):
            meta_payload = {}
        break
    routines_final = _reconcile_routines(meta_payload, routines_wired, bool(routine_containers), warn)
    if routines_final:
        ladder["routines"] = routines_final
    if isinstance(meta_payload.get("tag_aliases"), dict) and meta_payload["tag_aliases"]:
        ladder.setdefault("meta", {})["tag_aliases"] = meta_payload["tag_aliases"]
        shown = ", ".join(f"{k} → {v}" for k, v in list(meta_payload["tag_aliases"].items())[:8])
        more = " …" if len(meta_payload["tag_aliases"]) > 8 else ""
        warn.append(
            f"WARNING: {len(meta_payload['tag_aliases'])} tag alias(es) restored from Cabinet Studio "
            f"metadata ({shown}{more}). Aliases are not part of the LD wiring, so they could not be "
            "verified — check each alias by hand."
        )
    # v0.3.19 (Deflector P3-c): look-alike / non-identifier tag names. Warned per tag (not
    # refused): the text, print and simulator all use the same string, but a human reading
    # "PB_Stop" cannot see a zero-width space or a Cyrillic letter.
    _tag_names: list[str] = []

    def _collect_tags(items: list[dict[str, Any]]) -> None:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            k = str(it.get("kind") or "").lower()
            if k == "or":
                for b in it.get("branches") or []:
                    _collect_tags(list(b or []))
                continue
            keys = ["var", "dest", "storage", "output", "pt_tag", "pv_tag"]
            if not (k == "math" and str(it.get("op") or "").upper() == "CPT"):
                keys += ["source_a", "source_b"]
            for key in keys:
                v = it.get(key)
                if isinstance(v, str) and v.strip():
                    _tag_names.append(v)

    for _r in ladder.get("rungs") or []:
        _collect_tags(list(_r.get("elements") or []))
    for _rr in (ladder.get("routines") or {}).values():
        for _r in _rr or []:
            _collect_tags(list(_r.get("elements") or []))
    for _msg in tag_name_warnings(_tag_names + [str(v.get("name") or "") for v in variables]):
        warn.append(_msg)
    # v0.3.19 (Audit NEW-16 / P2): a JSR to a routine this file does not contain refuses.
    # From the file alone a deleted routine and a never-written one look the same, and
    # the call would silently do nothing (e.g. an E-stop reset routine gone).
    # v0.3.19 (Audit NEW-17): an empty compare / math operand imports as written, loudly.
    from cabinet_studio.services.ladder_ir import COMPARE_THREE_OPS, normalize_routine_name

    _routine_names = {normalize_routine_name(n) for n in (ladder.get("routines") or {})}
    _missing_calls: list[str] = []

    def _check_calls(items: list[dict[str, Any]], where: str) -> None:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            k = str(it.get("kind") or "").lower()
            if k == "or":
                for b in it.get("branches") or []:
                    _check_calls(list(b or []), where)
            elif k == "jsr":
                target = normalize_routine_name(it.get("target"))
                if target and target != "Main" and target not in _routine_names:
                    _missing_calls.append(f"{where} calls JSR {target}")
            elif k in {"compare", "math"}:
                op = str(it.get("op") or "").upper()
                if op == "CPT":
                    sides = [] if str(it.get("expression") or it.get("source_a") or "").strip() else ["source_a"]
                elif k == "compare":
                    sides = ["source_a", "source_b"] + (["source_c"] if op in COMPARE_THREE_OPS else [])
                else:
                    sides = ["source_a"] if op in {"MOV", "NOT"} else ["source_a", "source_b"]
                empty = [{"source_a": "IN1", "source_b": "IN2", "source_c": "IN3"}[s] for s in sides
                         if not str(it.get(s) or "").strip()]
                if empty:
                    warn.append(
                        f"WARNING {where}: {op} block has no value on {', '.join(empty)}. It was imported "
                        "empty, exactly as in the file (a note never fills it in). Verify (F7) flags it and "
                        "the simulator will not run until you fill it in."
                    )

    for _i, _r in enumerate(ladder.get("rungs") or [], start=1):
        _check_calls(list(_r.get("elements") or []), f"rung {_i}")
    for _rn, _rr in (ladder.get("routines") or {}).items():
        for _i, _r in enumerate(_rr or [], start=1):
            _check_calls(list(_r.get("elements") or []), f"routine '{_rn}' rung {_i}")
    if _missing_calls:
        raise PLCopenDocumentError(
            "PLCopen import refused: " + "; ".join(_missing_calls[:8])
            + (" …" if len(_missing_calls) > 8 else "")
            + ", but this file contains no routine by that name. The routine was deleted or the "
            "file is damaged, and the call would silently do nothing (for example an E-stop or "
            "reset routine). Cabinet Studio will not guess. Nothing was imported."
        )
    if not warn:
        ladder["meta"].pop("import_warnings", None)
    return normalize_ladder_ir(ladder)


def export_program_to_plcopen_xml(
    program: dict[str, Any] | None,
    *,
    project_name: str = "",
    devices: list[dict[str, str]] | None = None,
    pou_name: str = "Main",
) -> str:
    ir = program_to_ladder_ir(program, project_name=project_name, devices=devices)
    return ladder_ir_to_plcopen_xml(ir, pou_name=pou_name)


def _import_ir_checked(xml_text: str) -> dict[str, Any]:
    """v0.3.17: validate the document, parse + guard, and refuse a file with no rungs."""
    validate_plcopen_document(xml_text)
    ir = plcopen_xml_to_ladder_ir(xml_text)
    routines = ir.get("routines") if isinstance(ir.get("routines"), dict) else {}
    has_routine_rungs = any(list(v or []) for v in (routines or {}).values()) if routines else False
    if not (ir.get("rungs") or []) and not has_routine_rungs:
        raise PLCopenDocumentError(
            "PLCopen import refused: the LD body contains no rungs Cabinet Studio can import "
            "(no left power rail with wired contacts / coils / blocks). Nothing was imported."
        )
    return ir


def import_plcopen_xml_to_program(xml_text: str) -> dict[str, Any]:
    from cabinet_studio.services.ladder_ir import ladder_ir_to_program

    ir = _import_ir_checked(xml_text)
    return ladder_ir_to_program(ir)


def import_plcopen_xml_to_program_checked(xml_text: str) -> tuple[dict[str, Any], list[str]]:
    """v0.3.16: like :func:`import_plcopen_xml_to_program` but also returns import warnings
    (always starts with :data:`PLCOPEN_IMPORT_WARNING`). Raises ValueError on refusal."""
    from cabinet_studio.services.ladder_ir import ladder_ir_to_program

    ir = _import_ir_checked(xml_text)
    warnings = [PLCOPEN_IMPORT_WARNING]
    warnings.extend(str(w) for w in ((ir.get("meta") or {}).get("import_warnings") or []))
    return ladder_ir_to_program(ir), warnings
