"""Cabinet Studio Educational Ladder IR (v3).

First-party intermediate representation for NO/NC contacts, coils, and
series/parallel structure. Converts to/from the project.program rung dicts
used by the Programming viewer so existing cabinets keep working.

Not a vendor PLC format. Not MicroLogix / .RSS / Do-more / CODESYS native.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


IR_FORMAT = "cabinet-studio-ladder"
IR_VERSION = 1
IR_DIALECT = "educational-iec"


def new_id(prefix: str = "r") -> str:
    return f"{prefix}{uuid4().hex[:8]}"


def empty_ladder(
    *,
    project_name: str = "",
    variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "format": IR_FORMAT,
        "version": IR_VERSION,
        "dialect": IR_DIALECT,
        "meta": {
            "project": project_name or "",
            "not_a_vendor_format": True,
            "label": "Cabinet Studio Educational Ladder",
        },
        "variables": list(variables or []),
        "rungs": [],
    }


def _contact_el(tag: str, normally_closed: bool = False) -> dict[str, Any]:
    return {
        "kind": "contact",
        "var": (tag or "").strip(),
        "form": "NC" if normally_closed else "NO",
    }


def _coil_el(tag: str, negated: bool = False, form: str | None = None) -> dict[str, Any]:
    coil_form = form or ("negated" if negated else "normal")
    return {
        "kind": "coil",
        "var": (tag or "").strip(),
        "form": coil_form,
    }


def program_rung_to_elements(rung: dict[str, Any]) -> list[dict[str, Any]]:
    """Map one project.program rung into IR element list (series of contact/or/coil)."""
    elements: list[dict[str, Any]] = []
    parallel = list(rung.get("parallel") or [])
    series = list(rung.get("series") or [])
    coil = (rung.get("coil_tag") or "").strip()
    coil_neg = bool(rung.get("coil_negated"))

    if parallel:
        if len(parallel) == 1 and len(parallel[0]) == 1:
            c = parallel[0][0]
            elements.append(_contact_el(c.get("tag", ""), bool(c.get("normally_closed"))))
        elif len(parallel) == 1:
            # Single branch with multiple contacts = series at the front
            for c in parallel[0]:
                elements.append(_contact_el(c.get("tag", ""), bool(c.get("normally_closed"))))
        else:
            branches: list[list[dict[str, Any]]] = []
            for branch in parallel:
                branch_els = [
                    _contact_el(c.get("tag", ""), bool(c.get("normally_closed")))
                    for c in branch
                    if (c.get("tag") or "").strip()
                ]
                if branch_els:
                    branches.append(branch_els)
            if len(branches) == 1:
                elements.extend(branches[0])
            elif branches:
                elements.append({"kind": "or", "branches": branches})

    for c in series:
        tag = (c.get("tag") or "").strip()
        if tag:
            elements.append(_contact_el(tag, bool(c.get("normally_closed"))))

    if coil:
        elements.append(_coil_el(coil, coil_neg))
    return elements


def elements_to_program_rung(
    elements: list[dict[str, Any]],
    *,
    rung_id: str | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Map IR elements back into the Programming viewer rung shape."""
    parallel: list[list[dict[str, Any]]] = []
    series: list[dict[str, Any]] = []
    coil_tag = ""
    coil_negated = False
    seen_or = False

    for el in elements or []:
        kind = (el.get("kind") or "").strip().lower()
        if kind == "or":
            seen_or = True
            for branch in el.get("branches") or []:
                contacts = []
                for item in branch:
                    if (item.get("kind") or "").lower() != "contact":
                        continue
                    tag = (item.get("var") or "").strip()
                    if not tag:
                        continue
                    contacts.append(
                        {
                            "tag": tag,
                            "normally_closed": str(item.get("form", "NO")).upper() == "NC",
                        }
                    )
                if contacts:
                    parallel.append(contacts)
        elif kind == "contact":
            tag = (el.get("var") or "").strip()
            if not tag:
                continue
            contact = {
                "tag": tag,
                "normally_closed": str(el.get("form", "NO")).upper() == "NC",
            }
            if not seen_or and not parallel and not series:
                # Leading contacts before any OR become a single parallel branch
                # (matches how starter builds seal-in: parallel first, then series).
                parallel.append([contact])
            elif not seen_or and len(parallel) == 1 and not series:
                # More leading contacts append into the only branch (series in branch)
                parallel[0].append(contact)
            else:
                series.append(contact)
        elif kind == "coil":
            coil_tag = (el.get("var") or "").strip()
            form = str(el.get("form", "normal")).lower()
            coil_negated = form in {"negated", "not", "nc"}
        elif kind == "timer":
            # Timers not stored in legacy program rungs yet; skip round-trip loss noted in meta.
            continue

    # If we only accumulated leading series into parallel[0] as one long branch and
    # never saw OR, that is fine for viewer drawing.
    contact_tag = ""
    normally_closed = False
    flat = []
    for branch in parallel:
        flat.extend(branch)
    flat.extend(series)
    if flat:
        contact_tag = flat[0].get("tag", "")
        normally_closed = bool(flat[0].get("normally_closed"))

    return {
        "id": (rung_id or new_id("r")).strip() or new_id("r"),
        "parallel": parallel,
        "series": series,
        "coil_tag": coil_tag,
        "coil_negated": bool(coil_negated),
        "comment": (comment or "").strip(),
        "contact_tag": contact_tag,
        "normally_closed": normally_closed,
    }


def variables_from_program(
    program: dict[str, Any] | None,
    *,
    devices: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build IR variable table from rungs + optional cabinet device tags."""
    seen: dict[str, dict[str, Any]] = {}
    for device in devices or []:
        tag = (device.get("tag") or "").strip()
        if not tag or tag in seen:
            continue
        type_id = (device.get("type_id") or "").lower()
        cls = "internal"
        if type_id in {
            "pushbutton",
            "estop",
            "selector",
            "limit_switch",
            "proximity",
            "photoeye",
            "sensor",
            "light_curtain",
        } or "sensor" in type_id or "button" in type_id:
            cls = "input"
        elif type_id in {
            "contactor",
            "relay",
            "solenoid",
            "motor",
            "lamp",
            "pilot_light",
            "valve",
            "horn",
        } or "relay" in type_id or "coil" in type_id:
            cls = "output"
        addr = (device.get("io_address") or "").strip()
        seen[tag] = {
            "name": tag,
            "class": cls,
            "type": "BOOL",
            "address": addr if addr and addr.lower() != "n/a" else "",
        }

    for rung in (program or {}).get("rungs") or []:
        for contact in list(rung.get("series") or []):
            tag = (contact.get("tag") or "").strip()
            if tag and tag not in seen:
                seen[tag] = {"name": tag, "class": "input", "type": "BOOL", "address": ""}
        for branch in rung.get("parallel") or []:
            for contact in branch:
                tag = (contact.get("tag") or "").strip()
                if tag and tag not in seen:
                    seen[tag] = {"name": tag, "class": "input", "type": "BOOL", "address": ""}
        coil = (rung.get("coil_tag") or "").strip()
        if coil:
            if coil not in seen:
                seen[coil] = {"name": coil, "class": "output", "type": "BOOL", "address": ""}
            elif seen[coil].get("class") == "input":
                # Coil use upgrades class to output for sim feedback.
                seen[coil]["class"] = "output"
    return list(seen.values())


def program_to_ladder_ir(
    program: dict[str, Any] | None,
    *,
    project_name: str = "",
    devices: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Convert project.program into cabinet-studio-ladder IR."""
    data = program or {}
    ladder = empty_ladder(project_name=project_name, variables=variables_from_program(data, devices=devices))
    rungs_out: list[dict[str, Any]] = []
    for index, rung in enumerate(data.get("rungs") or [], start=1):
        rid = str(rung.get("id") or index)
        rungs_out.append(
            {
                "id": rid,
                "comment": (rung.get("comment") or "").strip(),
                "elements": program_rung_to_elements(rung),
            }
        )
    ladder["rungs"] = rungs_out
    # Preserve answers/hmi as opaque meta for round-trip convenience (not IEC).
    if data.get("answers"):
        ladder["meta"]["answers"] = dict(data["answers"])
    if data.get("hmi_items"):
        ladder["meta"]["hmi_items"] = list(data["hmi_items"])
    return ladder


def ladder_ir_to_program(ladder: dict[str, Any] | None) -> dict[str, Any]:
    """Convert IR back into project.program shape (answers/hmi from meta when present)."""
    ladder = ladder or {}
    rungs = []
    for index, rung in enumerate(ladder.get("rungs") or [], start=1):
        elements = list(rung.get("elements") or [])
        # Support brief sketch that nests under rails.elements
        if not elements and isinstance(rung.get("rails"), dict):
            elements = list((rung.get("rails") or {}).get("elements") or [])
        rungs.append(
            elements_to_program_rung(
                elements,
                rung_id=str(rung.get("id") or index),
                comment=str(rung.get("comment") or ""),
            )
        )
    meta = ladder.get("meta") if isinstance(ladder.get("meta"), dict) else {}
    answers = dict(meta.get("answers") or {})
    hmi_items = list(meta.get("hmi_items") or [])
    return {
        "answers": answers,
        "rungs": rungs,
        "hmi_items": hmi_items,
        "plc_text": "",
        "hmi_text": "",
        "text_edited": False,
        "ladder_ir": {
            "format": ladder.get("format", IR_FORMAT),
            "version": ladder.get("version", IR_VERSION),
            "dialect": ladder.get("dialect", IR_DIALECT),
        },
    }


def normalize_ladder_ir(raw: object) -> dict[str, Any]:
    """Validate/normalize an IR dict; raise ValueError on hard errors."""
    if raw is None:
        return empty_ladder()
    if not isinstance(raw, dict):
        raise ValueError("Ladder IR must be an object.")
    fmt = raw.get("format", IR_FORMAT)
    if fmt not in {IR_FORMAT, "cabinet-studio-ladder", "plcopen-import"}:
        # Still accept if rungs present (imported sibling shapes).
        if "rungs" not in raw:
            raise ValueError(f"Unknown ladder format: {fmt!r}")
    ladder = empty_ladder(project_name=str((raw.get("meta") or {}).get("project") or ""))
    if isinstance(raw.get("meta"), dict):
        ladder["meta"].update({k: v for k, v in raw["meta"].items() if k != "project" or v})
        if raw["meta"].get("project"):
            ladder["meta"]["project"] = str(raw["meta"]["project"])
    ladder["version"] = int(raw.get("version") or IR_VERSION)
    ladder["dialect"] = str(raw.get("dialect") or IR_DIALECT)
    ladder["format"] = IR_FORMAT

    variables = []
    for item in raw.get("variables") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        variables.append(
            {
                "name": name,
                "class": str(item.get("class") or "internal"),
                "type": str(item.get("type") or "BOOL"),
                "address": str(item.get("address") or ""),
                **(
                    {"pt_ms": int(item["pt_ms"])}
                    if item.get("pt_ms") is not None and str(item.get("type", "")).upper() in {"TON", "TOF", "RTO"}
                    else {}
                ),
            }
        )
    ladder["variables"] = variables

    rungs = []
    for index, rung in enumerate(raw.get("rungs") or [], start=1):
        if not isinstance(rung, dict):
            raise ValueError(f"Rung {index} must be an object.")
        elements = list(rung.get("elements") or [])
        if not elements and isinstance(rung.get("rails"), dict):
            elements = list((rung.get("rails") or {}).get("elements") or [])
        clean_els = []
        for el in elements:
            if not isinstance(el, dict):
                continue
            kind = str(el.get("kind") or "").lower()
            if kind == "contact":
                clean_els.append(
                    {
                        "kind": "contact",
                        "var": str(el.get("var") or "").strip(),
                        "form": "NC" if str(el.get("form", "NO")).upper() == "NC" else "NO",
                    }
                )
            elif kind == "coil":
                form = str(el.get("form") or "normal").lower()
                if form not in {"normal", "negated", "set", "reset", "s", "r"}:
                    form = "normal"
                clean_els.append({"kind": "coil", "var": str(el.get("var") or "").strip(), "form": form})
            elif kind == "or":
                branches = []
                for branch in el.get("branches") or []:
                    if not isinstance(branch, list):
                        continue
                    b_els = []
                    for item in branch:
                        if not isinstance(item, dict):
                            continue
                        if str(item.get("kind") or "").lower() != "contact":
                            continue
                        b_els.append(
                            {
                                "kind": "contact",
                                "var": str(item.get("var") or "").strip(),
                                "form": "NC" if str(item.get("form", "NO")).upper() == "NC" else "NO",
                            }
                        )
                    if b_els:
                        branches.append(b_els)
                if branches:
                    clean_els.append({"kind": "or", "branches": branches})
            elif kind == "timer":
                clean_els.append(
                    {
                        "kind": "timer",
                        "var": str(el.get("var") or "").strip(),
                        "block": str(el.get("block") or "TON").upper(),
                    }
                )
        rungs.append(
            {
                "id": str(rung.get("id") or index),
                "comment": str(rung.get("comment") or "").strip(),
                "elements": clean_els,
            }
        )
    ladder["rungs"] = rungs
    return ladder


def collect_tags(ladder: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    """Return (inputs_guess, outputs/coils, all_tags) from IR."""
    coils: set[str] = set()
    contacts: set[str] = set()

    def walk(els: list[dict[str, Any]]) -> None:
        for el in els:
            kind = (el.get("kind") or "").lower()
            if kind == "contact":
                tag = (el.get("var") or "").strip()
                if tag:
                    contacts.add(tag)
            elif kind == "coil":
                tag = (el.get("var") or "").strip()
                if tag:
                    coils.add(tag)
            elif kind == "or":
                for branch in el.get("branches") or []:
                    walk(branch)
            elif kind == "timer":
                tag = (el.get("var") or "").strip()
                if tag:
                    coils.add(tag)

    for rung in ladder.get("rungs") or []:
        walk(list(rung.get("elements") or []))

    declared_in = {
        str(v.get("name"))
        for v in ladder.get("variables") or []
        if str(v.get("class") or "").lower() == "input" and v.get("name")
    }
    declared_out = {
        str(v.get("name"))
        for v in ladder.get("variables") or []
        if str(v.get("class") or "").lower() in {"output", "timer"} and v.get("name")
    }
    inputs = (contacts - coils) | declared_in
    outputs = coils | declared_out
    all_tags = contacts | coils | declared_in | declared_out
    return inputs, outputs, all_tags
