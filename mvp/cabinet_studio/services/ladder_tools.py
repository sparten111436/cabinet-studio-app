"""Ladder editor tools (v0.3.7+): copy/paste, verify, tag database, cross-reference,
find/replace, rung reorder. v0.3.8: tag aliases, verify quick-fixes, watch/trend buffer,
subroutine (JSR/SBR/RET) awareness.

Pure functions over the ``project.program`` dict used by the Programming viewer
(no Tk). Ideas only from commercial editors (Studio 5000 verify / cross-reference,
TIA error list, Productivity tag database, CODESYS find/replace) — first-party code,
educational, not a vendor format.

Element paths follow ``rung_instruction_list``: ``(i,)`` at top level and
``(i, branch, j, ...)`` inside OR branches.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Iterator

from cabinet_studio.services.ladder_ir import (
    normalize_routine_name,
    normalize_tag_aliases,
    resolve_alias,
    COUNTER_OWNER_BLOCKS,
    NUMERIC_MAX,
    TIMER_BLOCKS,
    _looks_numeric_literal,
    clean_elements,
    clean_note,
    elements_to_program_rung,
    normalize_counter_block,
    normalize_math_op,
    normalize_oneshot_block,
    program_rung_to_elements,
    split_member,
)

CLIP_FORMAT = "cabinet-studio-ladder-clip"
CLIP_VERSION = 1

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}

INPUT_KINDS = {"contact", "compare", "or"}
OUTPUT_KINDS = {"coil", "timer", "counter", "math", "jsr", "ret"}

_TAG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*(\.[A-Za-z0-9_]+)?$")
_EXPR_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z0-9_]+)?")

_INPUT_DEVICE_TYPES = {
    "pushbutton", "estop", "selector", "limit_switch", "proximity", "photoeye", "sensor", "light_curtain",
}
_OUTPUT_DEVICE_TYPES = {
    "contactor", "relay", "solenoid", "motor", "lamp", "pilot_light", "valve", "horn",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _program_from_dict(program: Any) -> dict[str, Any]:
    from cabinet_studio.services.programming import program_from_dict

    return program_from_dict(program)


def _finish(data: dict[str, Any]) -> dict[str, Any]:
    from cabinet_studio.services.programming import format_plc_text

    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def _rebuild_rung(els: list[dict[str, Any]], *, rung_id: str | None, comment: str, index: int) -> dict[str, Any]:
    """Elements → normalized program rung; force-store ``elements`` when the classic
    fields alone would lose anything (e.g. two timers on one rung)."""
    from cabinet_studio.services.programming import _normalize_rung

    cleaned = clean_elements(els)
    new_rung = elements_to_program_rung(cleaned, rung_id=rung_id, comment=comment)
    if "elements" not in new_rung and cleaned:
        if clean_elements(program_rung_to_elements(new_rung)) != cleaned:
            new_rung["elements"] = cleaned
    return _normalize_rung(new_rung, index)


def device_io_class(device: dict[str, Any] | None) -> str:
    """input / output / internal guess for a cabinet device (same rules as the IR table)."""
    type_id = str((device or {}).get("type_id") or "").lower()
    direction = str((device or {}).get("io_direction") or "").lower()
    if direction.startswith("in"):
        return "input"
    if direction.startswith("out"):
        return "output"
    if type_id in _INPUT_DEVICE_TYPES or "sensor" in type_id or "button" in type_id:
        return "input"
    if type_id in _OUTPUT_DEVICE_TYPES or "relay" in type_id or "coil" in type_id:
        return "output"
    return "internal"


def valid_tag_name(tag: str) -> bool:
    t = (tag or "").strip()
    return bool(t) and not _looks_numeric_literal(t) and bool(_TAG_RE.match(t))


def is_literal(token: str) -> bool:
    t = (token or "").strip()
    return bool(t) and _looks_numeric_literal(t)


def expression_tags(expr: str) -> list[str]:
    return [m.group(0) for m in _EXPR_TOKEN_RE.finditer(expr or "") if not is_literal(m.group(0))]


def element_label(el: dict[str, Any]) -> str:
    """Short mnemonic label (Studio/CCW-style educational) for lists and cross-ref."""
    kind = str(el.get("kind") or "").lower()
    if kind == "contact":
        return f"{'XIO' if str(el.get('form')).upper() == 'NC' else 'XIC'} {el.get('var', '')}"
    if kind == "coil":
        form = str(el.get("form") or "normal").lower()
        mn = {"set": "OTL", "s": "OTL", "reset": "OTU", "r": "OTU", "negated": "OTE/"}.get(form, "OTE")
        return f"{mn} {el.get('var', '')}"
    if kind == "timer":
        if str(el.get("pt_tag") or "").strip():
            return f"{str(el.get('block') or 'TON').upper()} {el.get('var', '')} PT={str(el.get('pt_tag')).strip()} (tag, ms)"
        return f"{str(el.get('block') or 'TON').upper()} {el.get('var', '')} PT={int(el.get('pt_ms') or 0)}ms"
    if kind == "counter":
        blk = normalize_counter_block(el.get("block"))
        pre = f" PRE={int(el.get('pv') or 0)}" if blk in COUNTER_OWNER_BLOCKS or blk == "LOAD" else ""
        if pre and str(el.get("pv_tag") or "").strip():
            pre = f" PRE={str(el.get('pv_tag')).strip()} (tag)"
        return f"{blk} {el.get('var', '')}{pre}"
    if kind == "compare":
        op = str(el.get("op") or "EQU").upper()
        if op in {"LIM", "MEQ"}:
            return f"{op} {el.get('source_a', '')},{el.get('source_b', '')},{el.get('source_c', '')}"
        return f"{op} {el.get('source_a', '')},{el.get('source_b', '')}"
    if kind == "math":
        op = normalize_math_op(el.get("op"))
        if op == "CPT":
            return f"CPT {el.get('dest', '')} := {el.get('expression') or el.get('source_a', '')}"
        if op == "MOV":
            return f"MOV {el.get('source_a', '')} → {el.get('dest', '')}"
        if op == "NOT":
            return f"NOT ~{el.get('source_a', '')} → {el.get('dest', '')}"
        return f"{op} {el.get('source_a', '')},{el.get('source_b', '')} → {el.get('dest', '')}"
    if kind == "oneshot":
        blk = normalize_oneshot_block(el.get("block"))
        return f"{blk} {el.get('var', '')}" + (f" → {el.get('output')}" if el.get("output") else "")
    if kind == "or":
        return f"OR ({len(el.get('branches') or [])} branches)"
    if kind == "jsr":
        return f"JSR {el.get('target', '')}"
    if kind == "sbr":
        return f"SBR {el.get('name', '')}"
    if kind == "ret":
        return "RET"
    return kind


def _or_drives_output(el: dict[str, Any]) -> bool:
    """v0.3.18: an OR group with an output instruction in any branch."""
    if str(el.get("kind") or "").lower() != "or":
        return False
    for branch in el.get("branches") or []:
        for item in branch or []:
            if isinstance(item, dict) and (is_output_element(item) or _or_drives_output(item)):
                return True
    return False


def is_output_element(el: dict[str, Any]) -> bool:
    kind = str(el.get("kind") or "").lower()
    if kind in OUTPUT_KINDS:
        return True
    if kind == "oneshot":
        return normalize_oneshot_block(el.get("block")) in {"OSR", "OSF"}
    return False


def iter_elements(els: list[dict[str, Any]], prefix: tuple = ()) -> Iterator[tuple[tuple, dict[str, Any]]]:
    """Yield (path, element) for every instruction, descending into OR branches."""
    for i, el in enumerate(els or []):
        if not isinstance(el, dict):
            continue
        path = prefix + (i,)
        if str(el.get("kind") or "").lower() == "or":
            for bi, branch in enumerate(el.get("branches") or []):
                yield from iter_elements(list(branch or []), path + (bi,))
            continue
        yield path, el


def element_refs(el: dict[str, Any]) -> list[dict[str, str]]:
    """Tag references inside one instruction: field, tag, access, role."""
    kind = str(el.get("kind") or "").lower()
    out: list[dict[str, str]] = []

    def add(field: str, tag: str, access: str, role: str) -> None:
        t = (tag or "").strip()
        if t and not is_literal(t):
            out.append({"field": field, "tag": t, "access": access, "role": role})

    if kind == "contact":
        add("var", str(el.get("var") or ""), "read", "XIO" if str(el.get("form")).upper() == "NC" else "XIC")
    elif kind == "coil":
        form = str(el.get("form") or "normal").lower()
        add("var", str(el.get("var") or ""), "write", {"set": "OTL", "s": "OTL", "reset": "OTU", "r": "OTU"}.get(form, "OTE"))
    elif kind == "timer":
        add("var", str(el.get("var") or ""), "instance", str(el.get("block") or "TON").upper())
    elif kind == "counter":
        blk = normalize_counter_block(el.get("block"))
        add("var", str(el.get("var") or ""), "instance" if blk in COUNTER_OWNER_BLOCKS else "write", blk)
    elif kind == "oneshot":
        blk = normalize_oneshot_block(el.get("block"))
        add("var", str(el.get("var") or ""), "storage", f"{blk} storage")
        add("output", str(el.get("output") or ""), "write", f"{blk} output")
    elif kind == "compare":
        op = str(el.get("op") or "EQU").upper()
        add("source_a", str(el.get("source_a") or ""), "read", f"{op} A")
        add("source_b", str(el.get("source_b") or ""), "read", f"{op} B")
        add("source_c", str(el.get("source_c") or ""), "read", f"{op} C")
    elif kind == "math":
        op = normalize_math_op(el.get("op"))
        add("dest", str(el.get("dest") or ""), "write", f"{op} dest")
        add("source_a", str(el.get("source_a") or ""), "read", f"{op} A")
        add("source_b", str(el.get("source_b") or ""), "read", f"{op} B")
        for tok in expression_tags(str(el.get("expression") or "")):
            add("expression", tok, "read", f"{op} expr")
    return out


def program_refs(program: Any) -> list[dict[str, Any]]:
    """Every tag reference in the program, in rung order."""
    data = _program_from_dict(program)
    refs: list[dict[str, Any]] = []
    for index, rung in enumerate(data["rungs"], start=1):
        for path, el in iter_elements(program_rung_to_elements(rung)):
            label = element_label(el)
            for ref in element_refs(el):
                base, member = split_member(ref["tag"])
                refs.append(
                    {
                        **ref,
                        "base": base,
                        "member": member,
                        "rung_id": rung["id"],
                        "rung_index": index,
                        "path": path,
                        "kind": str(el.get("kind") or "").lower(),
                        "label": label,
                    }
                )
    return refs


# ---------------------------------------------------------------------------
# copy / paste / reorder
# ---------------------------------------------------------------------------


def copy_rungs(program: Any, rung_ids: list[str] | tuple[str, ...] | str) -> dict[str, Any]:
    """Clipboard payload for one or more rungs (lossless elements + comment)."""
    ids = [rung_ids] if isinstance(rung_ids, str) else list(rung_ids or [])
    data = _program_from_dict(program)
    chosen = [r for r in data["rungs"] if r["id"] in set(ids)]
    if not chosen:
        raise ValueError("Select a rung to copy.")
    return {
        "format": CLIP_FORMAT,
        "version": CLIP_VERSION,
        "kind": "rungs",
        "rungs": [
            {"comment": r.get("comment", ""), "elements": deepcopy(program_rung_to_elements(r))} for r in chosen
        ],
    }


def _locate(els: list[dict[str, Any]], path: tuple) -> dict[str, Any] | None:
    node_list = els
    el = None
    i = 0
    path = tuple(path or ())
    while i < len(path):
        if not isinstance(path[i], int) or path[i] < 0 or path[i] >= len(node_list):
            return None
        el = node_list[path[i]]
        i += 1
        if i < len(path):
            branches = el.get("branches") or []
            if path[i] >= len(branches):
                return None
            node_list = branches[path[i]]
            i += 1
    return el


def copy_instruction(program: Any, rung_id: str, path: tuple | list) -> dict[str, Any]:
    data = _program_from_dict(program)
    rung = next((r for r in data["rungs"] if r["id"] == rung_id), None)
    if rung is None:
        raise KeyError(f"No rung with id {rung_id}")
    el = _locate(program_rung_to_elements(rung), tuple(path))
    if el is None:
        raise ValueError("Instruction not found on that rung.")
    return {"format": CLIP_FORMAT, "version": CLIP_VERSION, "kind": "instruction", "element": deepcopy(el)}


def validate_clip(clip: Any) -> dict[str, Any]:
    if not isinstance(clip, dict) or clip.get("format") != CLIP_FORMAT:
        raise ValueError("Clipboard does not hold Cabinet Studio ladder data.")
    kind = clip.get("kind")
    if kind == "rungs":
        rungs = [r for r in clip.get("rungs") or [] if isinstance(r, dict) and clean_elements(r.get("elements"))]
        if not rungs:
            raise ValueError("Clipboard rungs are empty.")
        return {**clip, "rungs": rungs}
    if kind == "instruction":
        cleaned = clean_elements([clip.get("element")])
        if not cleaned:
            raise ValueError("Clipboard instruction is empty.")
        return {**clip, "element": cleaned[0]}
    raise ValueError(f"Unknown clipboard kind {kind!r}.")


def clip_to_text(clip: dict[str, Any]) -> str:
    return json.dumps(validate_clip(clip), separators=(",", ":"))


def clip_from_text(text: str) -> dict[str, Any] | None:
    """Parse system-clipboard text; None when it is not our ladder clip."""
    try:
        raw = json.loads((text or "").strip())
        return validate_clip(raw)
    except Exception:
        return None


def replace_rung_elements(
    program: Any, rung_id: str, elements: list[dict[str, Any]], *, comment: str | None = None
) -> dict[str, Any]:
    """Swap a Main rung's whole element list (same id, so selection and sim highlights stay)."""
    if not clean_elements(elements):
        raise ValueError("Rung elements are required.")
    data = _program_from_dict(program)
    for idx, rung in enumerate(data["rungs"]):
        if rung["id"] != rung_id:
            continue
        text = rung.get("comment", "") if comment is None else comment
        data["rungs"][idx] = _rebuild_rung(deepcopy(elements), rung_id=rung["id"], comment=text, index=idx + 1)
        return _finish(data)
    raise KeyError(f"No rung with id {rung_id}")


def insert_rung_elements(
    program: Any, elements: list[dict[str, Any]], *, comment: str = "", after_id: str | None = None
) -> tuple[dict[str, Any], str]:
    """Insert a new Main rung after ``after_id`` (or at the end); returns (program, new id)."""
    if not clean_elements(elements):
        raise ValueError("Rung elements are required.")
    data = _program_from_dict(program)
    ids = [r["id"] for r in data["rungs"]]
    pos = ids.index(after_id) + 1 if after_id in ids else len(ids)
    rung = _rebuild_rung(deepcopy(elements), rung_id=None, comment=comment, index=pos + 1)
    data["rungs"].insert(pos, rung)
    return _finish(data), rung["id"]


def paste_rungs(program: Any, clip: dict[str, Any], *, after_id: str | None = None) -> tuple[dict[str, Any], list[str]]:
    """Insert clipboard rungs (fresh ids) after ``after_id`` (or at the end)."""
    clip = validate_clip(clip)
    if clip["kind"] != "rungs":
        raise ValueError("Clipboard holds an instruction — use Paste instruction.")
    data = _program_from_dict(program)
    ids = [r["id"] for r in data["rungs"]]
    pos = ids.index(after_id) + 1 if after_id in ids else len(ids)
    new_rungs = []
    for offset, item in enumerate(clip["rungs"]):
        new_rungs.append(
            _rebuild_rung(
                deepcopy(item.get("elements") or []),
                rung_id=None,
                comment=str(item.get("comment") or ""),
                index=pos + offset + 1,
            )
        )
    data["rungs"][pos:pos] = new_rungs
    return _finish(data), [r["id"] for r in new_rungs]


def paste_instruction(program: Any, clip: dict[str, Any], rung_id: str) -> dict[str, Any]:
    """Insert a copied instruction into a rung.

    Inputs (contacts, compares, OR groups, ONS) go in series just before the first
    output; outputs (coils, timers, counters, math, OSR/OSF) append at the end
    (mid-rung / multi-output rungs are allowed, like CCW branches of outputs).
    """
    clip = validate_clip(clip)
    if clip["kind"] != "instruction":
        raise ValueError("Clipboard holds rungs — use Paste rung.")
    el = deepcopy(clip["element"])
    data = _program_from_dict(program)
    for idx, rung in enumerate(data["rungs"]):
        if rung["id"] != rung_id:
            continue
        els = deepcopy(program_rung_to_elements(rung))
        if is_output_element(el):
            els.append(el)
        else:
            first_out = next((i for i, e in enumerate(els) if is_output_element(e)), len(els))
            els.insert(first_out, el)
        data["rungs"][idx] = _rebuild_rung(els, rung_id=rung["id"], comment=rung.get("comment", ""), index=idx + 1)
        return _finish(data)
    raise KeyError(f"No rung with id {rung_id}")


def element_tag(el: dict[str, Any]) -> str:
    return str(el.get("var") or el.get("tag") or el.get("name") or "")


def move_instruction(
    program: Any, src_rung_id: str, tag: str, nth: int, dst_rung_id: str, position: int
) -> dict[str, Any]:
    """Drag-and-drop: lift the nth top-level instruction with ``tag`` out of one rung and drop it
    in series at ``position`` of another (or the same) rung. Inputs stay left of the first output,
    outputs stay right of the last input. Refuses branch members and rungs left without an output."""
    data = _program_from_dict(program)
    ids = [r["id"] for r in data["rungs"]]
    if src_rung_id not in ids or dst_rung_id not in ids:
        raise KeyError("That rung no longer exists.")
    si, di = ids.index(src_rung_id), ids.index(dst_rung_id)
    src = deepcopy(program_rung_to_elements(data["rungs"][si]))
    hits = [i for i, e in enumerate(src) if element_tag(e) == tag]
    if nth >= len(hits):
        raise ValueError(f"{tag} sits inside a branch - move it with the rung editor instead.")
    el = src.pop(hits[nth])
    if not src or not any(is_output_element(e) for e in src):
        if si != di:
            raise ValueError("Every rung needs an output - that would leave the old rung without one.")
    dst = src if si == di else deepcopy(program_rung_to_elements(data["rungs"][di]))
    if si == di and hits[nth] < position:
        position -= 1
    first_out = next((i for i, e in enumerate(dst) if is_output_element(e)), len(dst))
    if is_output_element(el):
        position = max(position, first_out)
    else:
        position = min(position, first_out)
    dst.insert(max(0, min(position, len(dst))), el)
    rungs = data["rungs"]
    rungs[di] = _rebuild_rung(dst, rung_id=dst_rung_id, comment=rungs[di].get("comment", ""), index=di + 1)
    if si != di:
        rungs[si] = _rebuild_rung(src, rung_id=src_rung_id, comment=rungs[si].get("comment", ""), index=si + 1)
    return _finish(data)


def _instruction_slot(els: list[dict[str, Any]], tag: str, nth: int) -> tuple[list, int, list]:
    """(list holding it, index, parent chain) for the nth instruction with ``tag`` (branches included).
    The chain is [(container list, index of the OR in it), ...] from the rung down."""
    found = 0

    def walk(items: list, chain: list):
        nonlocal found
        for i, el in enumerate(items):
            if not isinstance(el, dict):
                continue
            if str(el.get("kind") or "").lower() == "or":
                for branch in el.get("branches") or []:
                    hit = walk(branch, chain + [(items, i)])
                    if hit:
                        return hit
                continue
            if element_tag(el) == tag:
                if found == nth:
                    return items, i, chain
                found += 1
        return None

    hit = walk(els, [])
    if hit is None:
        raise ValueError(f"{tag} is not on that rung any more.")
    return hit


def _rung_edit(program: Any, rung_id: str, change) -> dict[str, Any]:
    data = _program_from_dict(program)
    for idx, rung in enumerate(data["rungs"]):
        if rung["id"] != rung_id:
            continue
        els = deepcopy(program_rung_to_elements(rung))
        change(els)
        if not els:
            raise ValueError("That would leave the rung empty - use Delete rung instead.")
        data["rungs"][idx] = _rebuild_rung(els, rung_id=rung_id, comment=rung.get("comment", ""), index=idx + 1)
        return _finish(data)
    raise KeyError(f"No rung with id {rung_id}")


def delete_instruction(program: Any, rung_id: str, tag: str, nth: int = 0) -> dict[str, Any]:
    """Remove one instruction; an emptied OR branch goes away and a one-path OR flattens back in series."""
    def change(els):
        items, i, chain = _instruction_slot(els, tag, nth)
        items.pop(i)
        while chain:
            parent, oi = chain.pop()
            branches = [b for b in parent[oi].get("branches") or [] if b]
            if len(branches) >= 2:
                parent[oi]["branches"] = branches
                break
            parent[oi:oi + 1] = branches[0] if branches else []
    return _rung_edit(program, rung_id, change)


def replace_instruction(program: Any, rung_id: str, tag: str, nth: int, new_el: dict[str, Any]) -> dict[str, Any]:
    """Swap one instruction for another in the same spot (e.g. a different contact or coil)."""
    def change(els):
        items, i, _chain = _instruction_slot(els, tag, nth)
        items[i] = deepcopy(new_el)
    return _rung_edit(program, rung_id, change)


def insert_instruction(program: Any, rung_id: str, tag: str, nth: int, new_el: dict[str, Any],
                       *, after: bool = False) -> dict[str, Any]:
    """Put a new instruction in series right before (or after) an existing one."""
    def change(els):
        items, i, _chain = _instruction_slot(els, tag, nth)
        items.insert(i + 1 if after else i, deepcopy(new_el))
    return _rung_edit(program, rung_id, change)


def duplicate_rung(program: Any, rung_id: str) -> tuple[dict[str, Any], str]:
    data, ids = paste_rungs(program, copy_rungs(program, [rung_id]), after_id=rung_id)
    return data, ids[0]


def move_rung(program: Any, rung_id: str, delta: int) -> dict[str, Any]:
    data = _program_from_dict(program)
    ids = [r["id"] for r in data["rungs"]]
    if rung_id not in ids:
        raise KeyError(f"No rung with id {rung_id}")
    i = ids.index(rung_id)
    j = max(0, min(len(ids) - 1, i + int(delta)))
    if i != j:
        rung = data["rungs"].pop(i)
        data["rungs"].insert(j, rung)
        _finish(data)
    return data


# ---------------------------------------------------------------------------
# tag database + cross-reference
# ---------------------------------------------------------------------------


def set_tag_description(program: Any, tag: str, description: str) -> dict[str, Any]:
    data = _program_from_dict(program)
    name = (tag or "").strip()
    if not name:
        raise ValueError("Tag name is required.")
    descs = dict(data.get("tag_descriptions") or {})
    text = clean_note(description)
    if text:
        descs[name] = text
    else:
        descs.pop(name, None)
    data["tag_descriptions"] = descs
    return data



def set_tag_alias(program: Any, alias: str, base: str) -> dict[str, Any]:
    """Create or update an alias → base mapping (empty base clears the alias)."""
    data = _program_from_dict(program)
    alias = str(alias or "").strip()
    base = str(base or "").strip()
    if not alias or " " in alias or not valid_tag_name(alias.split(".")[0]):
        raise ValueError("Alias must be a simple tag name (no spaces).")
    if alias.lower() == "main":
        raise ValueError("Main is reserved.")
    aliases = dict(data.get("tag_aliases") or {})
    if not base:
        aliases.pop(alias, None)
    else:
        if alias == base:
            raise ValueError("Alias cannot point at itself.")
        # Prevent cycles
        if resolve_alias(base, {**aliases, alias: base}) == alias:
            raise ValueError("Alias would create a cycle.")
        aliases[alias] = base
    if aliases:
        data["tag_aliases"] = aliases
    else:
        data.pop("tag_aliases", None)
    return _finish(data)


def list_routines(program: Any) -> list[str]:
    """Routine names: Main plus every named SBR."""
    data = _program_from_dict(program)
    names = ["Main"]
    routines = data.get("routines") if isinstance(data.get("routines"), dict) else {}
    for name in sorted(routines.keys(), key=lambda s: s.lower()):
        n = normalize_routine_name(name)
        if n and n != "Main" and n not in names:
            names.append(n)
    return names


def ensure_routine(program: Any, name: str) -> dict[str, Any]:
    """Ensure a named subroutine exists (empty rungs). Main is always program['rungs']."""
    data = _program_from_dict(program)
    name = normalize_routine_name(name)
    if not name or name == "Main":
        raise ValueError("Choose a subroutine name other than Main.")
    routines = dict(data.get("routines") or {})
    routines.setdefault(name, [])
    data["routines"] = routines
    return _finish(data)


def add_rung_to_routine(program: Any, routine: str, elements: list[dict], *, comment: str = "") -> dict[str, Any]:
    """Append a rung built from elements to Main or a named routine."""
    from cabinet_studio.services.programming import add_rung_from_elements, new_rung_id

    data = _program_from_dict(program)
    name = normalize_routine_name(routine) or "Main"
    if name == "Main":
        return add_rung_from_elements(data, elements, comment=comment)
    routines = dict(data.get("routines") or {})
    rungs = list(routines.get(name) or [])
    rung = {
        "id": new_rung_id(),
        "comment": (comment or "").strip(),
        "elements": clean_elements(elements),
        "parallel": [],
        "series": [],
        "coil_tag": "",
        "coil_negated": False,
        "contact_tag": "",
        "normally_closed": False,
    }
    # Normalize via elements_to_program_rung for classic fields
    rung = elements_to_program_rung(clean_elements(elements), rung_id=rung["id"], comment=comment)
    rungs.append(rung)
    routines[name] = rungs
    data["routines"] = routines
    return _finish(data)


def tag_table(program: Any, devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Tag database rows: devices + every program tag + described-only tags.

    Row: name, class, type, address, description, device_description, source,
    reads, writes, uses, refs (cross-reference list incl. member reads like T1.DN).
    """
    data = _program_from_dict(program)
    descs = dict(data.get("tag_descriptions") or {})
    aliases = normalize_tag_aliases(data.get("tag_aliases"))
    refs = program_refs(data)
    rows: dict[str, dict[str, Any]] = {}

    def row(name: str) -> dict[str, Any]:
        if name not in rows:
            rows[name] = {
                "name": name, "class": "", "type": "BOOL", "address": "", "description": "",
                "device_description": "", "source": "program", "refs": [],
                "alias_of": "", "aliases": [],
            }
        return rows[name]

    for d in devices or []:
        tag = str(d.get("tag") or "").strip()
        if not tag:
            continue
        r = row(tag)
        r["source"] = "device"
        r["class"] = device_io_class(d)
        addr = str(d.get("io_address") or "").strip()
        r["address"] = "" if addr.lower() == "n/a" else addr
        r["device_description"] = str(d.get("description") or d.get("function") or d.get("type_id") or "").strip()

    for ref in refs:
        base, member = ref["base"], ref["member"]
        name = base if member else ref["tag"]
        r = row(name)
        r["refs"].append(ref)
        if ref["access"] == "instance":
            blk = ref["role"]
            r["class"] = "timer" if blk in TIMER_BLOCKS else "counter"
            r["type"] = blk
        elif ref["kind"] == "counter" and r["class"] not in {"counter"}:
            r["class"], r["type"] = "counter", r["type"] if r["type"] in COUNTER_OWNER_BLOCKS else "CTU"
        elif ref["access"] == "storage" and r["source"] != "device":
            r["class"] = r["class"] or "storage"
        elif ref["kind"] in {"compare", "math"} and r["class"] in {"", "numeric"} and r["source"] != "device":
            r["class"], r["type"] = "numeric", "NUMERIC"

    for name in descs:
        row(name)

    for alias, base in aliases.items():
        r = row(alias)
        r["class"] = r["class"] or "alias"
        r["type"] = "ALIAS"
        r["alias_of"] = base
        r["source"] = r["source"] if r["source"] == "device" else "alias"
        base_row = row(base)
        base_row.setdefault("aliases", [])
        if alias not in base_row["aliases"]:
            base_row["aliases"].append(alias)

    for r in rows.values():
        if not r["class"]:
            writes = [x for x in r["refs"] if x["access"] in {"write", "instance"}]
            r["class"] = "output" if writes else ("input" if r["refs"] else "internal")
        if r["class"] == "storage":
            r["type"] = "BOOL"
        r["description"] = descs.get(r["name"]) or r["device_description"]
        r["user_description"] = descs.get(r["name"], "")
        r["reads"] = sum(1 for x in r["refs"] if x["access"] == "read")
        r["writes"] = sum(1 for x in r["refs"] if x["access"] in {"write", "instance", "storage"})
        r["uses"] = len(r["refs"])
    return sorted(rows.values(), key=lambda r: (r["source"] != "device", r["name"].lower()))


def cross_reference(program: Any, tag: str) -> list[dict[str, Any]]:
    """Where-used list for a tag (members like T1.DN count toward T1)."""
    name = (tag or "").strip()
    base_q, member_q = split_member(name)
    out = []
    for ref in program_refs(program):
        if ref["tag"] == name or (not member_q and ref["base"] == name and ref["member"]):
            out.append(ref)
    return out


def format_cross_reference_html(program: Any, devices: list[dict[str, Any]] | None = None) -> str:
    """Printable tag cross-reference table (for the ladder print page)."""
    import html as _h

    rows = [r for r in tag_table(program, devices) if r["uses"] or r["user_description"]]
    if not rows:
        return ""
    lines = [
        '<table class="xref"><thead><tr><th>Tag</th><th>Class</th><th>Address</th>'
        "<th>Description</th><th>Where used (rung: instruction)</th></tr></thead><tbody>"
    ]
    for r in rows:
        used = "; ".join(f"R{x['rung_index']}: {x['role']} {x['tag']}" for x in r["refs"]) or "—"
        lines.append(
            "<tr>"
            f"<td>{_h.escape(r['name'])}</td><td>{_h.escape(r['class'])}</td>"
            f"<td>{_h.escape(r['address'])}</td><td>{_h.escape(r['description'])}</td>"
            f"<td>{_h.escape(used)}</td></tr>"
        )
    lines.append("</tbody></table>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# find / replace
# ---------------------------------------------------------------------------


def _tag_matches(tag: str, query: str, *, match_case: bool, whole: bool) -> bool:
    t, q = (tag, query) if match_case else (tag.lower(), query.lower())
    if not q:
        return False
    if whole:
        base, member = split_member(t)
        return t == q or (bool(member) and base == q)
    return q in t


def find_tag_refs(program: Any, query: str, *, match_case: bool = False, whole: bool = False) -> list[dict[str, Any]]:
    q = (query or "").strip()
    return [r for r in program_refs(program) if _tag_matches(r["tag"], q, match_case=match_case, whole=whole)]


def _swap(tag: str, old: str, new: str, *, match_case: bool) -> str | None:
    """New text for ``tag`` when it is ``old`` (or ``old.MEMBER``); else None."""
    t = (tag or "").strip()
    eq = (lambda a, b: a == b) if match_case else (lambda a, b: a.lower() == b.lower())
    if t and eq(t, old):
        return new
    base, member = split_member(t)
    if member and eq(base, old) and "." not in new:
        return f"{new}.{member}"
    return None


def replace_tag(
    program: Any,
    old: str,
    new: str,
    *,
    match_case: bool = True,
    rung_ids: list[str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Rename a tag everywhere (or only in ``rung_ids``). Members follow: T1→T2 makes
    T1.DN → T2.DN. Returns (program, replacements). Descriptions move with a
    program-wide rename."""
    old_t, new_t = (old or "").strip(), (new or "").strip()
    if not old_t:
        raise ValueError("Enter the tag to find.")
    if not valid_tag_name(new_t):
        raise ValueError(f"{new_t!r} is not a valid tag name (letters, digits, _ ; no spaces).")
    data = _program_from_dict(program)
    only = set(rung_ids) if rung_ids else None
    total = 0
    for idx, rung in enumerate(data["rungs"]):
        if only is not None and rung["id"] not in only:
            continue
        els = deepcopy(program_rung_to_elements(rung))
        count = 0
        for _path, el in iter_elements(els):
            for field in ("var", "output", "source_a", "source_b", "source_c", "dest"):
                if field not in el:
                    continue
                swapped = _swap(str(el.get(field) or ""), old_t, new_t, match_case=match_case)
                if swapped is not None and not is_literal(str(el.get(field) or "")):
                    el[field] = swapped
                    count += 1
            expr = str(el.get("expression") or "")
            if expr:
                def sub(m: re.Match) -> str:
                    nonlocal count
                    swapped = _swap(m.group(0), old_t, new_t, match_case=match_case)
                    if swapped is None:
                        return m.group(0)
                    count += 1
                    return swapped

                el["expression"] = _EXPR_TOKEN_RE.sub(sub, expr)
        if count:
            total += count
            data["rungs"][idx] = _rebuild_rung(els, rung_id=rung["id"], comment=rung.get("comment", ""), index=idx + 1)
    if only is None:
        descs = dict(data.get("tag_descriptions") or {})
        key = next((k for k in descs if (k == old_t if match_case else k.lower() == old_t.lower())), None)
        if key is not None and new_t not in descs:
            descs[new_t] = descs.pop(key)
            data["tag_descriptions"] = descs
    if total:
        _finish(data)
    return data, total


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def _issue(severity: str, code: str, message: str, *, rung: dict | None = None, index: int = 0,
           path: tuple = (), tag: str = "", fix: dict | None = None) -> dict[str, Any]:
    out = {
        "severity": severity,
        "code": code,
        "message": message,
        "rung_id": (rung or {}).get("id", ""),
        "rung_index": index,
        "path": tuple(path),
        "tag": tag,
    }
    if fix:
        out["fix"] = fix
    return out


def verify_program(program: Any, devices: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Educational verify (TIA error list / Studio verify ideas).

    Errors: empty rung, no output, missing operand, bad preset, DIV by 0, literal
    destination, duplicate one-shot storage bit, duplicate timer instance,
    timer/counter name clash, undefined T/C member.
    Warnings: duplicate OTE, OTL with no OTU, missing tag (read, never written,
    not a cabinet device), output device read but never driven, CTU/CTD PRE <= 0,
    RES/LOAD on an unknown counter.
    Info: unconditional rung, cabinet output device with no coil, numeric never written.
    """
    data = _program_from_dict(program)
    devices = list(devices or [])
    device_tags = {str(d.get("tag") or "").strip() for d in devices if str(d.get("tag") or "").strip()}
    output_devices = {str(d.get("tag")).strip() for d in devices if d.get("tag") and device_io_class(d) == "output"}
    described = set((data.get("tag_descriptions") or {}).keys())
    aliases = normalize_tag_aliases(data.get("tag_aliases"))
    described |= set(aliases.keys()) | set(aliases.values())
    routine_names = set(list_routines(data)) - {"Main"}
    issues: list[dict[str, Any]] = []
    rungs = data["rungs"]
    if not rungs:
        return [_issue("info", "EMPTY_PROGRAM", "No rungs yet — add a rung or build a starter program.")]

    ote: dict[str, list] = {}
    otl: dict[str, list] = {}
    otu: dict[str, list] = {}
    writers: dict[str, list] = {}
    reads: list[tuple[dict, int, tuple, str, str]] = []  # rung, idx, path, tag, kind
    timers: dict[str, list] = {}
    counters: dict[str, list] = {}
    counter_ops: list[tuple[dict, int, tuple, str, str]] = []
    storage: dict[str, list] = {}
    preset_refs: list[tuple[dict, int, tuple, str, str]] = []

    for index, rung in enumerate(rungs, start=1):
        els = program_rung_to_elements(rung)
        if not els:
            issues.append(_issue("error", "EMPTY_RUNG", f"Rung {index} is empty.", rung=rung, index=index))
            continue
        top_outputs = [e for e in els if is_output_element(e)]
        # v0.3.18: parallel output branches (Start → (Motor | Lamp)) are outputs too.
        branch_outputs = [e for e in els if _or_drives_output(e)]
        if not top_outputs and branch_outputs:
            pass
        elif not top_outputs:
            issues.append(_issue(
                "error", "NO_OUTPUT",
                f"Rung {index} has no output instruction (add a coil, timer, counter, math or OSR/OSF).",
                rung=rung, index=index,
            ))
        else:
            first_out = next(i for i, e in enumerate(els) if is_output_element(e))
            if first_out == 0:
                issues.append(_issue(
                    "info", "UNCONDITIONAL",
                    f"Rung {index}: {element_label(els[0])} has no input conditions (always TRUE).",
                    rung=rung, index=index, path=(0,),
                ))
        for path, el in iter_elements(els):
            kind = str(el.get("kind") or "").lower()
            label = element_label(el)
            if kind == "contact":
                reads.append((rung, index, path, str(el.get("var") or "").strip(), kind))
            elif kind == "coil":
                tag = str(el.get("var") or "").strip()
                form = str(el.get("form") or "normal").lower()
                bucket = otl if form in {"set", "s"} else otu if form in {"reset", "r"} else ote
                bucket.setdefault(tag, []).append((rung, index, path))
                writers.setdefault(tag, []).append(("coil", rung, index, path))
            elif kind == "timer":
                tag = str(el.get("var") or "").strip()
                timers.setdefault(tag, []).append((rung, index, path))
                pt = int(el.get("pt_ms") or 0)
                if str(el.get("pt_tag") or "").strip():
                    # v0.3.18 NEW-9: preset read from a tag at run time.
                    preset_refs.append((rung, index, path, str(el.get("pt_tag")).strip(), label))
                elif pt <= 0:
                    issues.append(_issue("error", "BAD_PRESET",
                                         f"Rung {index}: {label} — preset is 0 ms (DN sets immediately).",
                                         rung=rung, index=index, path=path, tag=tag,
                                         fix={"action": "set_timer_preset", "rung_id": rung.get("id", ""),
                                              "path": list(path), "pt_ms": 1000}))
                elif pt > NUMERIC_MAX:
                    issues.append(_issue("error", "BAD_PRESET", f"Rung {index}: {label} — preset too large.",
                                         rung=rung, index=index, path=path, tag=tag))
            elif kind == "counter":
                tag = str(el.get("var") or "").strip()
                blk = normalize_counter_block(el.get("block"))
                if blk in COUNTER_OWNER_BLOCKS:
                    counters.setdefault(tag, []).append((rung, index, path, blk))
                    if str(el.get("pv_tag") or "").strip():
                        preset_refs.append((rung, index, path, str(el.get("pv_tag")).strip(), label))
                    elif int(el.get("pv") or 0) <= 0:
                        issues.append(_issue("warning", "BAD_PRESET",
                                             f"Rung {index}: {label} — PRE ≤ 0, DN is TRUE right away.",
                                             rung=rung, index=index, path=path, tag=tag))
                else:
                    counter_ops.append((rung, index, path, tag, blk))
            elif kind == "oneshot":
                tag = str(el.get("var") or "").strip()
                storage.setdefault(tag, []).append((rung, index, path))
                out = str(el.get("output") or "").strip()
                if out:
                    writers.setdefault(out, []).append(("oneshot", rung, index, path))
            elif kind == "compare":
                op = str(el.get("op") or "EQU").upper()
                sides = ("source_a", "source_b", "source_c") if op in {"LIM", "MEQ"} else ("source_a", "source_b")
                for side in sides:
                    val = str(el.get(side) or "").strip()
                    letter = {"source_a": "A", "source_b": "B", "source_c": "C"}[side]
                    if not val:
                        issues.append(_issue("error", "MISSING_OPERAND",
                                             f"Rung {index}: {label} — {letter} is missing.",
                                             rung=rung, index=index, path=path))
                    elif not is_literal(val):
                        reads.append((rung, index, path, val, "numeric"))
            elif kind == "math":
                op = normalize_math_op(el.get("op"))
                dest = str(el.get("dest") or "").strip()
                if is_literal(dest):
                    issues.append(_issue("error", "LITERAL_DEST",
                                         f"Rung {index}: {label} — destination must be a tag, not a number.",
                                         rung=rung, index=index, path=path))
                else:
                    writers.setdefault(dest, []).append(("math", rung, index, path))
                a = str(el.get("source_a") or "").strip()
                b = str(el.get("source_b") or "").strip()
                expr = str(el.get("expression") or "").strip()
                if op == "CPT":
                    if not (expr or a):
                        issues.append(_issue("error", "MISSING_OPERAND", f"Rung {index}: CPT needs an expression "
                                             "(simulation will not run until it is filled in).",
                                             rung=rung, index=index, path=path))
                    else:
                        from cabinet_studio.services.ladder_ir import cpt_expression_error

                        _cpt_err = cpt_expression_error(expr or a)
                        if _cpt_err:
                            issues.append(_issue("error", "CPT_INVALID",
                                                 f"Rung {index}: {_cpt_err} — fix it by hand (simulation will "
                                                 "not run until it is fixed).",
                                                 rung=rung, index=index, path=path))
                    for tok in expression_tags(expr):
                        reads.append((rung, index, path, tok, "numeric"))
                elif op == "MOV":
                    if not a:
                        issues.append(_issue("warning", "MISSING_OPERAND",
                                             f"Rung {index}: MOV source is empty (moves 0).",
                                             rung=rung, index=index, path=path))
                elif op == "NOT":
                    if not a:
                        issues.append(_issue("warning", "MISSING_OPERAND",
                                             f"Rung {index}: NOT source is empty (NOT 0).",
                                             rung=rung, index=index, path=path))
                else:
                    if not a or (op not in {"NOT"} and not b):
                        issues.append(_issue("warning", "MISSING_OPERAND",
                                             f"Rung {index}: {label} — empty source reads as 0.",
                                             rung=rung, index=index, path=path))
                    if op == "DIV" and is_literal(b) and float(b) == 0:
                        issues.append(_issue("error", "DIV_ZERO", f"Rung {index}: {label} — divide by zero.",
                                             rung=rung, index=index, path=path))
                if op == "CPT":
                    srcs = (a,) if not expr else ()
                elif op in {"MOV", "NOT"}:
                    srcs = (a,)
                else:
                    srcs = (a, b)
                for src in srcs:
                    if src and not is_literal(src):
                        reads.append((rung, index, path, src, "numeric"))
            elif kind == "jsr":
                target = normalize_routine_name(el.get("target"))
                if not target:
                    issues.append(_issue("error", "MISSING_OPERAND",
                                         f"Rung {index}: JSR needs a subroutine name.",
                                         rung=rung, index=index, path=path,
                                         fix={"action": "set_jsr_target", "rung_id": rung.get("id", ""),
                                              "path": list(path), "target": "Sub1"}))
                elif target == "Main":
                    issues.append(_issue("error", "BAD_JSR",
                                         f"Rung {index}: JSR Main is not valid — Main is the main program.",
                                         rung=rung, index=index, path=path, tag=target))
                elif target not in routine_names:
                    issues.append(_issue("error", "UNKNOWN_ROUTINE",
                                         f"Rung {index}: JSR {target} — no SBR named {target}.",
                                         rung=rung, index=index, path=path, tag=target,
                                         fix={"action": "create_routine", "name": target}))

    # Duplicate timer instances / name clashes
    for tag, uses in timers.items():
        for rung, index, path in uses[1:]:
            issues.append(_issue("error", "DUP_INSTANCE",
                                 f"Rung {index}: timer {tag} is already defined on rung {uses[0][1]} — use a unique name.",
                                 rung=rung, index=index, path=path, tag=tag))
        if tag in counters:
            rung, index, path, _blk = counters[tag][0]
            issues.append(_issue("error", "NAME_CLASH", f"Rung {index}: {tag} is both a timer and a counter.",
                                 rung=rung, index=index, path=path, tag=tag))
    for tag, uses in counters.items():
        seen_blocks: dict[str, int] = {}
        for rung, index, path, blk in uses:
            if blk in seen_blocks:
                issues.append(_issue("warning", "DUP_INSTANCE",
                                     f"Rung {index}: {blk} {tag} also on rung {seen_blocks[blk]} (counts twice per scan).",
                                     rung=rung, index=index, path=path, tag=tag))
            else:
                seen_blocks[blk] = index
    for tag in set(timers) | set(counters):
        if tag in writers:
            _src, rung, index, path = writers[tag][0]
            issues.append(_issue("error", "NAME_CLASH",
                                 f"Rung {index}: {tag} is a timer/counter instance — do not write it with a coil/math.",
                                 rung=rung, index=index, path=path, tag=tag))
    for rung, index, path, tag, blk in counter_ops:
        if tag not in counters:
            issues.append(_issue("warning", "UNKNOWN_COUNTER",
                                 f"Rung {index}: {blk} {tag} — no CTU/CTD {tag} in this program.",
                                 rung=rung, index=index, path=path, tag=tag))

    # Duplicate one-shot storage bits
    for tag, uses in storage.items():
        for rung, index, path in uses[1:]:
            issues.append(_issue("error", "DUP_STORAGE",
                                 f"Rung {index}: one-shot storage bit {tag} is already used on rung {uses[0][1]} "
                                 "— each ONS/OSR/OSF needs its own bit.",
                                 rung=rung, index=index, path=path, tag=tag,
                                 fix={"action": "rename_oneshot_storage", "rung_id": rung.get("id", ""),
                                      "path": list(path), "from": tag, "to": f"{tag}_{index}"}))
        clash = writers.get(tag) or []
        if clash or tag in timers or tag in counters:
            rung, index, path = uses[0]
            issues.append(_issue("error", "DUP_STORAGE",
                                 f"Rung {index}: storage bit {tag} is also written elsewhere — it must be private to the one-shot.",
                                 rung=rung, index=index, path=path, tag=tag))

    # Duplicate destructive OTE
    for tag, uses in ote.items():
        if len(uses) > 1:
            where = ", ".join(str(u[1]) for u in uses)
            rung, index, path = uses[-1]
            issues.append(_issue("warning", "DUP_OTE",
                                 f"OTE {tag} is driven on rungs {where} — the last rung wins each scan.",
                                 rung=rung, index=index, path=path, tag=tag))
    for tag, uses in otl.items():
        if tag not in otu:
            rung, index, path = uses[0]
            issues.append(_issue("warning", "LATCH_NO_UNLATCH",
                                 f"Rung {index}: OTL {tag} is never unlatched (add an OTU {tag}).",
                                 rung=rung, index=index, path=path, tag=tag,
                                 fix={"action": "add_otu", "tag": tag}))

    # Missing / undriven tags
    written = set(writers) | set(timers) | set(counters) | set(storage)
    fb_names = set(timers) | set(counters)
    reported: set[str] = set()
    read_tags: set[str] = set()
    for rung, index, path, tag, kind in reads:
        if not tag:
            continue
        base, member = split_member(tag)
        read_tags.add(base if member else tag)
        if member:
            if base not in fb_names and base not in device_tags and tag not in written:
                key = f"member:{tag}"
                if key not in reported:
                    reported.add(key)
                    issues.append(_issue("error", "UNDEFINED_MEMBER",
                                         f"Rung {index}: {tag} reads {base}, but no timer/counter {base} is defined.",
                                         rung=rung, index=index, path=path, tag=tag))
            continue
        if tag in written:
            continue
        if kind == "numeric":
            key = f"num:{tag}"
            if key not in reported and tag not in device_tags:
                reported.add(key)
                issues.append(_issue("info", "NEVER_WRITTEN",
                                     f"Rung {index}: numeric tag {tag} is never written (reads 0 in Simulate).",
                                     rung=rung, index=index, path=path, tag=tag))
            continue
        if tag in output_devices:
            key = f"undriven:{tag}"
            if key not in reported:
                reported.add(key)
                issues.append(_issue("warning", "UNDRIVEN_COIL",
                                     f"Rung {index}: {tag} is an output device used as a contact, but no coil drives it.",
                                     rung=rung, index=index, path=path, tag=tag))
            continue
        if tag not in device_tags and tag not in described:
            key = f"missing:{tag}"
            if key not in reported:
                reported.add(key)
                issues.append(_issue("warning", "MISSING_TAG",
                                     f"Rung {index}: {tag} is not a cabinet device tag and nothing writes it (missing tag?).",
                                     rung=rung, index=index, path=path, tag=tag))
    for tag in sorted(output_devices - written - read_tags):
        issues.append(_issue("info", "UNDRIVEN_COIL", f"Output device {tag} has no coil in this program.", tag=tag))

    # v0.3.18 NEW-9: presets read from a tag. The value is only known at run time; when no
    # instruction writes the tag the simulator refuses to run (it never assumes 0).
    if preset_refs:
        math_dests: set[str] = set()
        all_rungs = list(rungs) + [r for rl in (data.get("routines") or {}).values() for r in (rl or []) if isinstance(r, dict)]
        for r in all_rungs:
            for _p, e in iter_elements(program_rung_to_elements(r)):
                if str(e.get("kind") or "").lower() == "math" and str(e.get("dest") or "").strip():
                    math_dests.add(str(e.get("dest")).strip())
        for rung, index, path, ptag, label in preset_refs:
            _b, member = split_member(ptag)
            if member in {"PRE", "ACC"} or ptag in math_dests:
                issues.append(_issue("warning", "PRESET_TAG",
                                     f"Rung {index}: {label} — the preset is read from tag {ptag} at run time.",
                                     rung=rung, index=index, path=path, tag=ptag))
            else:
                issues.append(_issue("error", "PRESET_TAG_UNSET",
                                     f"Rung {index}: {label} — the preset is read from tag {ptag}, but no "
                                     f"instruction writes {ptag}; the simulator will not run until it does.",
                                     rung=rung, index=index, path=path, tag=ptag))
    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["rung_index"] or 10**6, i["code"]))
    return issues


def verify_summary(issues: list[dict[str, Any]]) -> str:
    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    infos = sum(1 for i in issues if i["severity"] == "info")
    if not errors and not warnings:
        return f"Verify OK — 0 errors, 0 warnings{f', {infos} info' if infos else ''}."
    return f"Verify: {errors} error(s), {warnings} warning(s), {infos} info."


def format_verify_text(issues: list[dict[str, Any]]) -> str:
    lines = [verify_summary(issues)]
    for i in issues:
        where = f"R{i['rung_index']} " if i["rung_index"] else ""
        lines.append(f"[{i['severity'].upper()}] {where}{i['code']}: {i['message']}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# verify quick-fixes (v0.3.8)
# ---------------------------------------------------------------------------


def apply_verify_fix(program: Any, issue: dict[str, Any]) -> dict[str, Any]:
    """Apply a one-click educational fix described by ``issue["fix"]``.

    Supported actions: rename_oneshot_storage, add_otu, set_timer_preset,
    create_routine, set_jsr_target, declare_tag.
    """
    data = _program_from_dict(program)
    fix = issue.get("fix") if isinstance(issue, dict) else None
    if not isinstance(fix, dict):
        raise ValueError("This issue has no one-click fix.")
    action = str(fix.get("action") or "")

    def _mutate_element(rung_id: str, path: list | tuple, mutator) -> None:
        for idx, rung in enumerate(data["rungs"]):
            if rung.get("id") != rung_id:
                continue
            els = program_rung_to_elements(rung)
            # locate
            cur: Any = els
            path_t = tuple(path)
            for i, step in enumerate(path_t):
                if i == len(path_t) - 1:
                    if not isinstance(cur, list) or step >= len(cur):
                        raise ValueError("Instruction path is stale — re-verify.")
                    cur[step] = mutator(cur[step])
                else:
                    el = cur[step]
                    if str(el.get("kind")).lower() == "or":
                        # next step is branch index, then continue
                        pass
                    cur = el.get("branches") if str(el.get("kind")).lower() == "or" and i + 1 < len(path_t) else cur
                    if isinstance(cur, list) and i + 1 < len(path_t):
                        # For OR paths from iter_elements: (or_i, branch_i, j, ...)
                        # After hitting or element at or_i, next is branch index
                        pass
            # Simpler approach: walk with iter_elements style mutation
            def walk(lst, pref=()):
                for i, el in enumerate(list(lst)):
                    p = pref + (i,)
                    if p == path_t:
                        lst[i] = mutator(el)
                        return True
                    if str(el.get("kind") or "").lower() == "or":
                        for bi, br in enumerate(el.get("branches") or []):
                            if walk(br, p + (bi,)):
                                return True
                return False
            if not walk(els):
                raise ValueError("Could not find the instruction to fix — re-verify.")
            data["rungs"][idx] = _rebuild_rung(els, rung_id=rung_id, comment=rung.get("comment") or "", index=idx + 1)
            return
        raise ValueError("Rung not found for fix.")

    if action == "rename_oneshot_storage":
        new_name = str(fix.get("to") or "").strip()
        if not new_name:
            raise ValueError("Fix is missing the new storage name.")
        def mut(el):
            el = dict(el)
            el["var"] = new_name
            return el
        _mutate_element(str(fix.get("rung_id") or issue.get("rung_id") or ""), fix.get("path") or issue.get("path") or (), mut)
        return _finish(data)

    if action == "set_timer_preset":
        pt = max(1, int(fix.get("pt_ms") or 1000))
        def mut(el):
            el = dict(el)
            el["pt_ms"] = pt
            return el
        _mutate_element(str(fix.get("rung_id") or issue.get("rung_id") or ""), fix.get("path") or issue.get("path") or (), mut)
        return _finish(data)

    if action == "set_jsr_target":
        target = normalize_routine_name(fix.get("target") or "Sub1")
        def mut(el):
            el = dict(el)
            el["target"] = target
            return el
        _mutate_element(str(fix.get("rung_id") or issue.get("rung_id") or ""), fix.get("path") or issue.get("path") or (), mut)
        data = ensure_routine(data, target)
        return data

    if action == "add_otu":
        tag = str(fix.get("tag") or issue.get("tag") or "").strip()
        if not tag:
            raise ValueError("Fix is missing the latch tag.")
        from cabinet_studio.services.programming import add_rung_from_elements
        data = add_rung_from_elements(
            data,
            [{"kind": "contact", "var": f"{tag}_Reset", "form": "NO"},
             {"kind": "coil", "var": tag, "form": "reset"}],
            comment=f"Unlatch {tag} (verify quick-fix)",
        )
        return data

    if action == "create_routine":
        name = normalize_routine_name(fix.get("name") or issue.get("tag") or "")
        if not name:
            raise ValueError("Fix is missing the routine name.")
        return ensure_routine(data, name)

    if action == "declare_tag":
        tag = str(fix.get("tag") or issue.get("tag") or "").strip()
        desc = str(fix.get("description") or "Declared by verify quick-fix").strip()
        if not tag:
            raise ValueError("Fix is missing the tag.")
        return set_tag_description(data, tag, desc)

    raise ValueError(f"Unknown fix action: {action}")


# ---------------------------------------------------------------------------
# Watch / trend buffer (v0.3.8; polish v0.3.10 — pause, labels, CSV)
# ---------------------------------------------------------------------------


class WatchTrendBuffer:
    """Ring buffer of tag samples collected during Simulate (Studio/TIA watch ideas).

    v0.3.10: optional pause (skip record), per-tag series labels, CSV export.
    """

    def __init__(self, *, capacity: int = 240) -> None:
        self.capacity = max(2, int(capacity))
        self.tags: list[str] = []
        self.labels: dict[str, str] = {}  # tag -> display label
        self.samples: list[dict[str, float]] = []  # each: {tag: number}
        self.scan_numbers: list[int] = []
        self.paused: bool = False

    def set_tags(self, tags: list[str] | tuple[str, ...]) -> None:
        cleaned = []
        for t in tags or []:
            name = str(t or "").strip()
            if name and name not in cleaned:
                cleaned.append(name)
        self.tags = cleaned[:24]
        # Drop labels for removed tags
        self.labels = {k: v for k, v in self.labels.items() if k in self.tags}

    def add_tag(self, tag: str, label: str | None = None) -> None:
        name = str(tag or "").strip()
        if name and name not in self.tags and len(self.tags) < 24:
            self.tags.append(name)
        if name and label is not None and str(label).strip():
            self.labels[name] = str(label).strip()

    def remove_tag(self, tag: str) -> None:
        name = str(tag or "").strip()
        self.tags = [t for t in self.tags if t != name]
        self.labels.pop(name, None)

    def set_label(self, tag: str, label: str) -> None:
        name = str(tag or "").strip()
        if not name:
            return
        text = str(label or "").strip()
        if text:
            self.labels[name] = text
        else:
            self.labels.pop(name, None)

    def series_label(self, tag: str) -> str:
        name = str(tag or "").strip()
        return self.labels.get(name) or name

    def clear(self) -> None:
        self.samples.clear()
        self.scan_numbers.clear()

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        return self.paused

    def record(self, result: dict[str, Any]) -> None:
        """Record one scan_once result for the watched tags (no-op while paused)."""
        if self.paused or not self.tags:
            return
        vars_map = result.get("vars") or {}
        numbers = result.get("numbers") or {}
        timers = result.get("timers") or {}
        counters = result.get("counters") or {}
        row: dict[str, float] = {}
        for tag in self.tags:
            row[tag] = float(self._value(tag, vars_map, numbers, timers, counters))
        self.samples.append(row)
        self.scan_numbers.append(int(result.get("scan_count") or len(self.samples)))
        overflow = len(self.samples) - self.capacity
        if overflow > 0:
            del self.samples[:overflow]
            del self.scan_numbers[:overflow]

    @staticmethod
    def _value(tag: str, vars_map, numbers, timers, counters) -> float:
        from cabinet_studio.services.ladder_ir import split_member
        # ACC/PRE are numeric members (not in BOOL MEMBER_SUFFIXES) — split manually.
        raw = (tag or "").strip()
        if "." in raw:
            base, _, member = raw.rpartition(".")
            member_u = member.upper()
            if member_u == "ACC" and base in counters:
                return float(counters[base].get("acc") or 0)
            if member_u == "ACC" and base in timers:
                return float(timers[base].get("acc_ms") or 0)
            if member_u == "PRE" and base in counters:
                return float(counters[base].get("pre") or 0)
        base, member = split_member(tag)
        if member in {"DN", "TT", "EN", "CU", "CD", "OV", "UN", "Q"}:
            if base in counters:
                key = {"DN": "dn", "CU": "cu", "CD": "cd", "OV": "ov", "UN": "un", "Q": "dn"}.get(member, member.lower())
                return 1.0 if counters[base].get(key) else 0.0
            if base in timers:
                key = {"DN": "q", "TT": "tt", "EN": "en", "Q": "q"}.get(member, member.lower())
                return 1.0 if timers[base].get(key) else 0.0
        if tag in numbers:
            return float(numbers[tag])
        if tag in vars_map:
            return 1.0 if vars_map[tag] else 0.0
        if base in vars_map and not member:
            return 1.0 if vars_map[base] else 0.0
        return 0.0

    def series(self, tag: str) -> list[float]:
        return [float(s.get(tag, 0.0)) for s in self.samples]

    def latest(self) -> dict[str, float]:
        return dict(self.samples[-1]) if self.samples else {}

    def to_csv(self) -> str:
        """Return CSV text: scan header first, then samples, then trailing design-aid rows.

        v0.3.14 REG-4: generic readers (csv.DictReader / Sniffer) need the header on
        row 1. Design-aid notes are trailing ``#,…`` comment rows (same width), not
        a preamble that steals the header.
        """
        import csv
        import io

        from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
        from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE

        buf = io.StringIO()
        writer = csv.writer(buf)
        headers = ["scan"] + [self.series_label(t) for t in self.tags]
        writer.writerow(headers)
        for i, row in enumerate(self.samples):
            scan = self.scan_numbers[i] if i < len(self.scan_numbers) else i + 1
            writer.writerow([scan] + [row.get(t, "") for t in self.tags])
        # Trailing comment rows only (header stays row 1 for DictReader / Sniffer).
        trail_pad = [""] * max(0, len(headers) - 2)
        if any(self.series_label(t) != t for t in self.tags):
            tag_pad = [""] * max(0, len(headers) - 1 - len(self.tags))
            writer.writerow(["#tag"] + list(self.tags) + tag_pad)
        writer.writerow(["#", UL_DESIGN_AID] + trail_pad)
        writer.writerow(["#", SAFETY_DESIGN_AID_NOTE] + trail_pad)
        return buf.getvalue()

    def export_csv(self, path: str) -> str:
        """Write CSV to path; return the absolute path string."""
        from pathlib import Path as _Path

        p = _Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="") as fh:
            fh.write(self.to_csv())
        return str(p.resolve())


