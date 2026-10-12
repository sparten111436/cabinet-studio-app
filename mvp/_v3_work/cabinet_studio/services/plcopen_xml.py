"""PLCopen XML (IEC 61131-10 / TC6-style) interchange for Cabinet Studio ladder IR.

Educational subset: project → types → POUs → LD with left/right power rails,
contacts, coils, and simple OR via parallel connection points.

Not a full schema validator. Round-trips through our IR. External tools
(Beremiz / CODESYS) may open exports with varying fidelity.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from xml.dom import minidom

from cabinet_studio.services.ladder_ir import (
    IR_DIALECT,
    IR_FORMAT,
    IR_VERSION,
    empty_ladder,
    normalize_ladder_ir,
    program_to_ladder_ir,
)


NS = "http://www.plcopen.org/xml/tc6_0201"
ET.register_namespace("", NS)


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


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag


def ladder_ir_to_plcopen_xml(ladder: dict[str, Any], *, pou_name: str = "Main") -> str:
    """Serialize ladder IR to a PLCopen TC6-ish XML string."""
    ladder = normalize_ladder_ir(ladder)
    project = _el("project")
    file_header = _sub(project, "fileHeader")
    file_header.set("companyName", "Cabinet Studio")
    file_header.set("productName", "Cabinet Studio Educational Ladder")
    file_header.set("productVersion", f"v{IR_VERSION}")
    file_header.set("creationDateTime", "2026-10-02T00:00:00")

    content = _sub(project, "contentHeader", {"name": str((ladder.get("meta") or {}).get("project") or "CabinetStudio")})
    _sub(content, "coordinateInfo")

    types = _sub(project, "types")
    pous = _sub(types, "pous")
    pou = _sub(pous, "pou", {"name": pou_name or "Main", "pouType": "program"})
    interface = _sub(pou, "interface")
    input_vars = _sub(interface, "inputVars")
    output_vars = _sub(interface, "outputVars")
    local_vars = _sub(interface, "localVars")

    for var in ladder.get("variables") or []:
        name = str(var.get("name") or "").strip()
        if not name:
            continue
        cls = str(var.get("class") or "internal").lower()
        parent = input_vars if cls == "input" else output_vars if cls == "output" else local_vars
        variable = _sub(parent, "variable", {"name": name})
        vtype = _sub(variable, "type")
        _sub(vtype, "BOOL")

    body = _sub(pou, "body")
    ld = _sub(body, "LD")

    local_id = 0

    def next_id() -> str:
        nonlocal local_id
        local_id += 1
        return str(local_id)

    for rung in ladder.get("rungs") or []:
        comment = (rung.get("comment") or "").strip()
        elements = list(rung.get("elements") or [])
        left_id = next_id()
        left = _sub(ld, "leftPowerRail", {"localId": left_id})
        pos = _sub(left, "position", {"x": "0", "y": "0"})
        _ = pos
        conn_point_out = _sub(left, "connectionPointOut", {"formalParameter": ""})
        _ = conn_point_out

        prev_ids = [left_id]
        x = 1
        coil_els = []
        logic_els = []
        for el in elements:
            kind = (el.get("kind") or "").lower()
            if kind == "coil":
                coil_els.append(el)
            else:
                logic_els.append(el)

        for el in logic_els:
            kind = (el.get("kind") or "").lower()
            if kind == "contact":
                cid = next_id()
                form = str(el.get("form") or "NO").upper()
                negated = "true" if form == "NC" else "false"
                contact = _sub(
                    ld,
                    "contact",
                    {
                        "localId": cid,
                        "negated": negated,
                        "variable": str(el.get("var") or ""),
                    },
                )
                _sub(contact, "position", {"x": str(x * 100), "y": "0"})
                c_in = _sub(contact, "connectionPointIn")
                for pid in prev_ids:
                    conn = _sub(c_in, "connection", {"refLocalId": pid})
                    _ = conn
                _sub(contact, "connectionPointOut")
                if comment and x == 1:
                    _sub(contact, "documentation", text=comment)
                prev_ids = [cid]
                x += 1
            elif kind == "or":
                branch_out_ids = []
                for bi, branch in enumerate(el.get("branches") or []):
                    branch_prev = list(prev_ids)
                    for ci, item in enumerate(branch):
                        if (item.get("kind") or "").lower() != "contact":
                            continue
                        cid = next_id()
                        form = str(item.get("form") or "NO").upper()
                        contact = _sub(
                            ld,
                            "contact",
                            {
                                "localId": cid,
                                "negated": "true" if form == "NC" else "false",
                                "variable": str(item.get("var") or ""),
                            },
                        )
                        _sub(contact, "position", {"x": str(x * 100), "y": str(bi * 50)})
                        c_in = _sub(contact, "connectionPointIn")
                        for pid in branch_prev:
                            _sub(c_in, "connection", {"refLocalId": pid})
                        _sub(contact, "connectionPointOut")
                        branch_prev = [cid]
                    if branch_prev != prev_ids:
                        branch_out_ids.extend(branch_prev)
                prev_ids = branch_out_ids or prev_ids
                x += 1
            elif kind == "timer":
                # Represent as a comment-bearing contact on Q for interchange simplicity.
                cid = next_id()
                contact = _sub(
                    ld,
                    "contact",
                    {
                        "localId": cid,
                        "negated": "false",
                        "variable": str(el.get("var") or ""),
                    },
                )
                _sub(contact, "position", {"x": str(x * 100), "y": "0"})
                c_in = _sub(contact, "connectionPointIn")
                for pid in prev_ids:
                    _sub(c_in, "connection", {"refLocalId": pid})
                _sub(contact, "connectionPointOut")
                _sub(contact, "documentation", text=f"TIMER {el.get('block') or 'TON'}")
                prev_ids = [cid]
                x += 1

        for el in coil_els:
            cid = next_id()
            form = str(el.get("form") or "normal").lower()
            attrib = {
                "localId": cid,
                "variable": str(el.get("var") or ""),
            }
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
                _sub(c_in, "connection", {"refLocalId": pid})
            prev_ids = [cid]
            x += 1

        right_id = next_id()
        right = _sub(ld, "rightPowerRail", {"localId": right_id})
        _sub(right, "position", {"x": str(x * 100), "y": "0"})
        c_in = _sub(right, "connectionPointIn")
        for pid in prev_ids:
            _sub(c_in, "connection", {"refLocalId": pid})

    # Pretty print
    rough = ET.tostring(project, encoding="utf-8", xml_declaration=True)
    try:
        parsed = minidom.parseString(rough)
        return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    except Exception:
        return rough.decode("utf-8")


def plcopen_xml_to_ladder_ir(xml_text: str) -> dict[str, Any]:
    """Parse a subset of PLCopen LD XML into Cabinet Studio ladder IR."""
    text = (xml_text or "").strip()
    if not text:
        return empty_ladder()
    root = ET.fromstring(text)

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
                variables.append({"name": name, "class": cls, "type": "BOOL", "address": ""})
    ladder["variables"] = variables

    # Build connection graph from LD
    ld_nodes = findall(root, "LD")
    if not ld_nodes:
        return normalize_ladder_ir(ladder)

    rungs_out: list[dict[str, Any]] = []
    for ld in ld_nodes:
        # Group by walking from each leftPowerRail
        lefts = [n for n in list(ld) if _local(n.tag) == "leftPowerRail"]
        # Index all elements by localId
        by_id: dict[str, ET.Element] = {}
        for child in list(ld):
            lid = child.get("localId")
            if lid:
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

        def contact_el(node: ET.Element) -> dict[str, Any]:
            negated = str(node.get("negated", "false")).lower() in {"true", "1"}
            return {
                "kind": "contact",
                "var": str(node.get("variable") or "").strip(),
                "form": "NC" if negated else "NO",
            }

        def coil_el(node: ET.Element) -> dict[str, Any]:
            form = "normal"
            if str(node.get("negated", "false")).lower() in {"true", "1"}:
                form = "negated"
            storage = str(node.get("storage") or "").lower()
            if storage in {"set", "reset"}:
                form = storage
            return {"kind": "coil", "var": str(node.get("variable") or "").strip(), "form": form}

        for left in lefts or [None]:
            elements: list[dict[str, Any]] = []
            comment = ""
            if left is None:
                # Flat dump: contacts then coils in document order
                for child in list(ld):
                    if is_contact(child):
                        elements.append(contact_el(child))
                        doc = find_child(child, "documentation")
                        if doc is not None and (doc.text or "").strip() and not comment:
                            comment = (doc.text or "").strip()
                    elif is_coil(child):
                        elements.append(coil_el(child))
                if elements:
                    rungs_out.append({"id": str(len(rungs_out) + 1), "comment": comment, "elements": elements})
                continue

            start_id = left.get("localId") or ""
            # BFS layers; when a node has multiple successors that are contacts, emit OR
            frontier = list(forward.get(start_id) or [])
            visited: set[str] = set()
            guard = 0
            while frontier and guard < 500:
                guard += 1
                # Split contacts vs coils vs rails at this frontier
                contact_ids = []
                coil_ids = []
                other = []
                for nid in frontier:
                    if nid in visited:
                        continue
                    node = by_id.get(nid)
                    if node is None:
                        continue
                    if is_contact(node):
                        contact_ids.append(nid)
                    elif is_coil(node):
                        coil_ids.append(nid)
                    elif _local(node.tag) == "rightPowerRail":
                        continue
                    else:
                        other.append(nid)

                if len(contact_ids) > 1:
                    branches = []
                    next_frontier = []
                    for cid in contact_ids:
                        visited.add(cid)
                        node = by_id[cid]
                        doc = find_child(node, "documentation")
                        if doc is not None and (doc.text or "").strip() and not comment:
                            comment = (doc.text or "").strip()
                        branches.append([contact_el(node)])
                        next_frontier.extend(forward.get(cid) or [])
                    elements.append({"kind": "or", "branches": branches})
                    frontier = [n for n in next_frontier if n not in visited]
                elif len(contact_ids) == 1:
                    cid = contact_ids[0]
                    visited.add(cid)
                    node = by_id[cid]
                    doc = find_child(node, "documentation")
                    if doc is not None and (doc.text or "").strip() and not comment:
                        comment = (doc.text or "").strip()
                    elements.append(contact_el(node))
                    frontier = [n for n in (forward.get(cid) or []) if n not in visited]
                    # Also keep coils that were siblings
                    for coid in coil_ids:
                        if coid not in visited:
                            frontier.append(coid)
                else:
                    for coid in coil_ids:
                        if coid in visited:
                            continue
                        visited.add(coid)
                        elements.append(coil_el(by_id[coid]))
                        frontier = [n for n in (forward.get(coid) or []) if n not in visited]
                    if not coil_ids:
                        # progress via other
                        for oid in other:
                            visited.add(oid)
                            frontier = [n for n in (forward.get(oid) or []) if n not in visited]
                        if not other:
                            break

            if elements:
                rungs_out.append(
                    {
                        "id": str(len(rungs_out) + 1),
                        "comment": comment,
                        "elements": elements,
                    }
                )

    ladder["rungs"] = rungs_out
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


def import_plcopen_xml_to_program(xml_text: str) -> dict[str, Any]:
    from cabinet_studio.services.ladder_ir import ladder_ir_to_program

    ir = plcopen_xml_to_ladder_ir(xml_text)
    return ladder_ir_to_program(ir)
