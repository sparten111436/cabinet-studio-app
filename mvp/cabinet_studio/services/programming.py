"""Learning PLC/HMI program for the open cabinet (cut-and-paste text, not a download)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from cabinet_studio.models.project import Project

LEARNING_NOTE = "Learning program for this cabinet. Not a download to a live PLC."

# One question at a time. Plain words a 14-year-old can follow.
PROGRAM_QUESTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "on_start",
        "What should happen when Start is pressed?",
        (
            "The motor should run",
            "The motor should run forward",
            "Nothing yet - I will write it myself",
        ),
    ),
    (
        "on_stop",
        "What should happen when Stop is pressed?",
        (
            "The motor should stop",
            "The motor should stop and stay stopped until Start again",
            "Nothing yet - I will write it myself",
        ),
    ),
    (
        "on_estop",
        "What must the e-stop do?",
        (
            "Stop the motor right away and keep it stopped",
            "Stop everything that moves",
            "Nothing yet - I will write it myself",
        ),
    ),
    (
        "direction",
        "Does the motor run forward only, or also reverse?",
        (
            "Forward only",
            "Forward and reverse",
        ),
    ),
    (
        "hmi_show",
        "What should the HMI show?",
        (
            "Running, Stopped, and Fault",
            "Running and Stopped only",
            "Running, Stopped, Fault, Start, and Stop",
        ),
    ),
)

TYPE_ROLE_NAMES: dict[str, str] = {
    "pushbutton": "PB",
    "estop": "E-Stop",
    "contactor": "Motor Contactor",
    "relay": "Control Relay",
    "safety_relay": "Safety Relay",
    "motor": "Motor",
    "vfd": "VFD",
    "sensor": "Sensor",
    "light": "Light",
    "solenoid": "Solenoid",
    "valve": "Valve",
    "plc": "PLC",
    "hmi": "HMI",
    "io_module": "I/O Module",
    "power_supply": "Power Supply",
    "transmitter": "Transmitter",
    "ethernet_switch": "Ethernet Switch",
}


def new_rung_id() -> str:
    return uuid.uuid4().hex[:10]


def empty_program() -> dict[str, Any]:
    return {
        "answers": {},
        "rungs": [],
        "hmi_items": [],
        "plc_text": "",
        "hmi_text": "",
        "text_edited": False,
    }



def program_questions_for_project(project: Project | None = None) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """One-at-a-time questions grounded in devices already on the open cabinet.

    Falls back to PROGRAM_QUESTIONS when the panel has no useful I/O tags yet.
    Never invents tags — options only name devices that exist on the project.
    """
    if project is None:
        return PROGRAM_QUESTIONS
    devices = cabinet_device_tags(project)
    if not devices:
        return PROGRAM_QUESTIONS
    start = find_start_tag(devices)
    stop = find_stop_tag(devices)
    estop = find_estop_tag(devices)
    coils = find_output_coil_tags(devices)
    sensors = find_sensor_tags(devices)
    motorish = any(d["type_id"] in {"contactor", "motor", "vfd"} for d in devices)
    start_label = start or "Start"
    stop_label = stop or "Stop"
    estop_label = estop or "E-Stop"
    questions: list[tuple[str, str, tuple[str, ...]]] = []

    if coils:
        start_opts: list[str] = [f"Energize {tag}" for tag in coils]
        if len(coils) >= 2:
            start_opts.append(f"Energize {coils[0]} (primary); later question covers {coils[1]}")
        if motorish:
            start_opts = [
                "The motor should run",
                "The motor should run forward",
                *start_opts,
            ]
        start_opts.append("Nothing yet - I will write it myself")
        # de-dupe preserve order
        seen: set[str] = set()
        start_opts = [o for o in start_opts if not (o in seen or seen.add(o))]
        questions.append(
            (
                "on_start",
                f"What should happen when {start_label} is pressed? (cabinet outputs: {', '.join(coils)})",
                tuple(start_opts),
            )
        )
    else:
        questions.append(PROGRAM_QUESTIONS[0])

    if stop or coils:
        stop_opts = [
            f"Drop {coils[0]} and keep it off until Start again" if coils else "The motor should stop and stay stopped until Start again",
            "Drop all outputs and keep them off until Start again" if coils else "The motor should stop",
            "Nothing yet - I will write it myself",
        ]
        if motorish:
            stop_opts = [
                "The motor should stop",
                "The motor should stop and stay stopped until Start again",
                "Nothing yet - I will write it myself",
            ]
        questions.append(
            (
                "on_stop",
                f"What should happen when {stop_label} is pressed?",
                tuple(stop_opts),
            )
        )
    else:
        questions.append(PROGRAM_QUESTIONS[1])

    if estop or coils:
        estop_opts = [
            "Drop all outputs right away and keep them off",
            f"Drop {coils[0]} right away and keep it off" if coils else "Stop the motor right away and keep it stopped",
            "Stop everything that moves",
            "Nothing yet - I will write it myself",
        ]
        if motorish:
            estop_opts = [
                "Stop the motor right away and keep it stopped",
                "Stop everything that moves",
                "Nothing yet - I will write it myself",
            ]
        questions.append(
            (
                "on_estop",
                f"What must {estop_label} do?",
                tuple(dict.fromkeys(estop_opts)),
            )
        )
    else:
        questions.append(PROGRAM_QUESTIONS[2])

    if motorish:
        questions.append(PROGRAM_QUESTIONS[3])  # direction
    elif len(coils) >= 2:
        second_opts = [
            f"When {sensors[0]} is made, energize {coils[1]}" if sensors else f"Energize {coils[1]} with the same Start path",
            f"Energize {coils[1]} with the same Start path",
            f"Energize {coils[1]} only (no auto link from sensors)",
            "Nothing yet - I will write it myself",
        ]
        if sensors and len(sensors) >= 2:
            second_opts.insert(
                1,
                f"When {sensors[1]} is made, energize {coils[1]}",
            )
        questions.append(
            (
                "second_coil",
                f"This cabinet also has {coils[1]}. When should it turn on?",
                tuple(dict.fromkeys(second_opts)),
            )
        )

    if sensors and coils:
        sensor_opts: list[str] = []
        for tag in sensors:
            if "curtain" in tag.lower():
                sensor_opts.append(f"Pause when {tag} is blocked (NC in place path)")
            else:
                sensor_opts.append(f"Require {tag} clear/OK in the run path")
                sensor_opts.append(f"Use {tag} only to fire a second output (not in Start path)")
        sensor_opts.append("Do not add sensor contacts yet")
        sensor_opts.append("Nothing yet - I will write it myself")
        questions.append(
            (
                "sensor_interlock",
                f"How should cabinet sensors ({', '.join(sensors)}) affect the ladder?",
                tuple(dict.fromkeys(sensor_opts)),
            )
        )

    questions.append(PROGRAM_QUESTIONS[4])  # hmi_show
    return tuple(questions)



def default_design_answers(project: Project | None = None) -> dict[str, str]:
    """Starter answers from the cabinet design (devices/wires already placed).

    Same defaults the AI-build / "Build from drawings" path uses. Does not invent
    tags — build_starter_program only wires tags that already exist on the panel.
    """
    answers: dict[str, str] = {
        "on_start": "The motor should run",
        "on_stop": "The motor should stop and stay stopped until Start again",
        "on_estop": "Stop everything that moves",
        "direction": "Forward only",
        "hmi_show": "Running, Stopped, and Fault",
    }
    coils: list[str] = []
    sensors: list[str] = []
    motorish = False
    if project is not None:
        devices = cabinet_device_tags(project)
        coils = find_output_coil_tags(devices)
        sensors = find_sensor_tags(devices)
        motorish = any(d["type_id"] in {"contactor", "motor", "vfd"} for d in devices)
        if coils and not motorish:
            primary = coils[0]
            answers["on_start"] = f"Energize {primary}"
            answers["on_stop"] = "Drop all outputs and keep them off until Start again"
            answers["on_estop"] = "Drop all outputs right away and keep them off"
            if len(coils) >= 2 and sensors:
                answers["second_coil"] = f"When {sensors[0]} is made, energize {coils[1]}"
                answers["sensor_interlock"] = f"Require {sensors[0]} clear/OK in the run path"
            elif len(coils) >= 2:
                answers["second_coil"] = f"Energize {coils[1]} with the same Start path"
        elif coils and motorish:
            answers["on_start"] = "The motor should run"
    interview = getattr(project, "interview", None) or {} if project is not None else {}
    if isinstance(interview, dict):
        start_stop = str(interview.get("start_stop") or "").lower()
        if "touch" in start_stop or "hmi" in start_stop:
            answers["hmi_show"] = "Running, Stopped, Fault, Start, and Stop"
        direction = str(interview.get("direction") or interview.get("motor_direction") or "").lower()
        if "reverse" in direction:
            answers["direction"] = "Forward and reverse"
        duty = str(interview.get("duty") or "").lower()
        if coils and not motorish:
            if "place" in duty and len(coils) >= 1:
                answers["on_start"] = f"Energize {coils[0]}"
            if "weld" in duty and len(coils) >= 2 and sensors:
                arm = next((s for s in sensors if "arm" in s.lower()), sensors[0])
                answers["second_coil"] = f"When {arm} is made, energize {coils[1]}"
            if any("curtain" in s.lower() for s in sensors):
                curtain = next(s for s in sensors if "curtain" in s.lower())
                answers["sensor_interlock"] = f"Pause when {curtain} is blocked (NC in place path)"
    return answers





def plc_text_looks_stale_empty(plc_text: str, rungs: list[Any] | None = None) -> bool:
    """True when saved PLC text still says no rungs but structured rungs exist (or text blank)."""
    text = (plc_text or "").strip()
    if not text:
        return True
    if rungs and "(No rungs yet" in text:
        # Stale empty banner left over after rungs were added/saved without refreshing text.
        return True
    return False


def program_has_content(program: dict[str, Any] | None) -> bool:
    if not program:
        return False
    if (program.get("plc_text") or "").strip():
        return True
    if (program.get("hmi_text") or "").strip():
        return True
    if program.get("rungs"):
        return True
    if program.get("hmi_items"):
        return True
    if any(str(v).strip() for v in (program.get("answers") or {}).values()):
        return True
    return False


def program_looks_edited(program: dict[str, Any] | None) -> bool:
    """True when the user already has a program we should not silently replace."""
    if not program:
        return False
    if program.get("text_edited"):
        return True
    return program_has_content(program)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "nc"}


def _normalize_contact(raw: object, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Contact {index} must be an object.")
    tag = raw.get("tag", raw.get("contact_tag", ""))
    if not isinstance(tag, str):
        raise ValueError(f"Contact {index} tag must be text.")
    nc = _as_bool(raw.get("normally_closed", False))
    return {"tag": tag.strip(), "normally_closed": bool(nc)}


def _normalize_timer(raw: object) -> dict[str, Any] | None:
    """Optional educational timer block on a rung (TON/TOF/RTO)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Rung timer must be an object.")
    tag = raw.get("tag", raw.get("var", ""))
    if not isinstance(tag, str):
        raise ValueError("Rung timer tag must be text.")
    tag = tag.strip()
    if not tag:
        return None
    block = str(raw.get("block") or "TON").upper().strip()
    if block not in {"TON", "TOF", "RTO"}:
        block = "TON"
    try:
        pt_ms = max(0, int(raw.get("pt_ms") or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Rung timer pt_ms must be an integer.") from exc
    return {"tag": tag, "block": block, "pt_ms": pt_ms}


COUNTER_BLOCK_CHOICES = ("CTU", "CTD", "RES", "LOAD")


def _normalize_counter(raw: object) -> dict[str, Any] | None:
    """Optional educational counter instruction on a rung (CTU/CTD/RES/LOAD).

    CTU/CTD carry the preset (pv, Rockwell .PRE). RES zeros ACC; LOAD sets ACC=PRE
    (CCW CTD LOAD). See ladder_sim for the scan semantics.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Rung counter must be an object.")
    tag = raw.get("tag", raw.get("var", ""))
    if not isinstance(tag, str):
        raise ValueError("Rung counter tag must be text.")
    tag = tag.strip()
    if not tag:
        return None
    from cabinet_studio.services.ladder_ir import clamp_counter, normalize_counter_block

    block = normalize_counter_block(raw.get("block"))
    raw_pv = raw.get("pv", raw.get("pre", 0))
    try:
        int(float(raw_pv or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Rung counter pv must be an integer.") from exc
    pv = clamp_counter(raw_pv) if block in {"CTU", "CTD", "LOAD"} else 0
    return {"tag": tag, "block": block, "pv": pv}


def counter_text_mark(counter: dict[str, Any] | None) -> str:
    if not counter or not (counter.get("tag") or "").strip():
        return ""
    blk = str(counter.get("block") or "CTU").upper()
    tag = (counter.get("tag") or "").strip()
    if blk in {"RES", "LOAD"}:
        return f"({blk} {tag})"
    return f"{blk}[{tag}/PRE={int(counter.get('pv') or 0)}]"


def flatten_contacts(rung: dict[str, Any]) -> list[dict[str, Any]]:
    """All contacts on a rung in draw order (parallel branches, then series)."""
    out: list[dict[str, Any]] = []
    for branch in rung.get("parallel") or []:
        for contact in branch:
            out.append(dict(contact))
    for contact in rung.get("series") or []:
        out.append(dict(contact))
    return out


def _legacy_fields_from_rung(rung: dict[str, Any]) -> dict[str, Any]:
    contacts = flatten_contacts(rung)
    first = contacts[0] if contacts else {"tag": "", "normally_closed": False}
    return {
        "contact_tag": first.get("tag", ""),
        "normally_closed": bool(first.get("normally_closed")),
    }


def rung_has_seal_in(rung: dict[str, Any]) -> bool:
    """True when a normally-open coil-tag contact sits in parallel with another branch."""
    coil = (rung.get("coil_tag") or "").strip()
    if not coil:
        return False
    parallel = rung.get("parallel") or []
    if len(parallel) < 2:
        return False
    for branch in parallel:
        for contact in branch:
            if (contact.get("tag") or "").strip() == coil and not contact.get("normally_closed"):
                return True
    return False


def _normalize_rung(raw: object, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Rung {index} must be an object.")
    comment = raw.get("comment", "")
    coil = raw.get("coil_tag", "")
    if not isinstance(coil, str) or not isinstance(comment, str):
        raise ValueError(f"Rung {index} fields must be text.")
    coil_negated = _as_bool(raw.get("coil_negated", False))
    rung_id = raw.get("id") or new_rung_id()
    if not isinstance(rung_id, str) or not rung_id.strip():
        rung_id = new_rung_id()
    parallel_raw = raw.get("parallel")
    series_raw = raw.get("series")
    if parallel_raw is None and series_raw is None and "contact_tag" in raw:
        contact = _normalize_contact(
            {
                "tag": raw.get("contact_tag", ""),
                "normally_closed": raw.get("normally_closed", False),
            },
            index,
        )
        parallel: list[list[dict[str, Any]]] = [[contact]] if contact["tag"] else []
        series: list[dict[str, Any]] = []
    else:
        if parallel_raw is None:
            parallel_raw = []
        if series_raw is None:
            series_raw = []
        if not isinstance(parallel_raw, list):
            raise ValueError(f"Rung {index} parallel must be a list of branches.")
        if not isinstance(series_raw, list):
            raise ValueError(f"Rung {index} series must be a list of contacts.")
        parallel = []
        for bi, branch in enumerate(parallel_raw, start=1):
            if not isinstance(branch, list):
                raise ValueError(f"Rung {index} parallel branch {bi} must be a list.")
            contacts = [_normalize_contact(c, bi * 100 + ci) for ci, c in enumerate(branch, start=1)]
            contacts = [c for c in contacts if c["tag"]]
            if contacts:
                parallel.append(contacts)
        series = [_normalize_contact(c, index * 1000 + ci) for ci, c in enumerate(series_raw, start=1)]
        series = [c for c in series if c["tag"]]
    rung = {
        "id": rung_id.strip(),
        "parallel": parallel,
        "series": series,
        "coil_tag": coil.strip(),
        "coil_negated": bool(coil_negated),
        "comment": comment.strip(),
    }
    timer = _normalize_timer(raw.get("timer"))
    if timer:
        rung["timer"] = timer
    counter = _normalize_counter(raw.get("counter"))
    if counter:
        rung["counter"] = counter
    mid_coils_raw = raw.get("mid_coils")
    if isinstance(mid_coils_raw, list) and mid_coils_raw:
        mid = []
        for item in mid_coils_raw:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag") or item.get("var") or "").strip()
            if not tag:
                continue
            form = str(item.get("form") or ("negated" if item.get("negated") else "normal")).lower()
            if form not in {"normal", "negated", "set", "reset"}:
                form = "normal"
            mid.append({"tag": tag, "form": form, "negated": form == "negated"})
        if mid:
            rung["mid_coils"] = mid
    if isinstance(raw.get("elements"), list) and raw.get("elements"):
        try:
            from cabinet_studio.services.ladder_ir import clean_elements

            cleaned = clean_elements(raw.get("elements"))
            if cleaned:
                rung["elements"] = cleaned
        except Exception:
            pass
    legacy = _legacy_fields_from_rung(rung)
    rung["contact_tag"] = legacy["contact_tag"]
    rung["normally_closed"] = legacy["normally_closed"]
    return rung


def _normalize_hmi_item(raw: object, index: int) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"HMI item {index} must be an object.")
    item_id = raw.get("id") or new_rung_id()
    kind = raw.get("kind", "indicator")
    label = raw.get("label", "")
    if not isinstance(item_id, str) or not isinstance(kind, str) or not isinstance(label, str):
        raise ValueError(f"HMI item {index} fields must be text.")
    return {"id": item_id.strip() or new_rung_id(), "kind": kind.strip() or "indicator", "label": label.strip()}


def _normalize_tag_descriptions(raw: object) -> dict[str, str]:
    """Tag → description (single line, capped). Bad shapes are ignored, not fatal."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        text = " ".join(str(value or "").split())[:240]
        if name and text:
            out[name] = text
    return out


def _normalize_tag_aliases(raw: object) -> dict[str, str]:
    """v0.3.8 alias → base tag map (educational Studio alias tags)."""
    from cabinet_studio.services.ladder_ir import normalize_tag_aliases

    return normalize_tag_aliases(raw)


def _normalize_routines(raw: object) -> dict[str, list[dict[str, Any]]]:
    """v0.3.8 named subroutines (excluding Main which lives in program['rungs'])."""
    from cabinet_studio.services.ladder_ir import normalize_routine_name

    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for key, value in raw.items():
        name = normalize_routine_name(key)
        if not name or name == "Main" or not isinstance(value, list):
            continue
        rungs = [_normalize_rung(item, i) for i, item in enumerate(value, start=1) if isinstance(item, dict)]
        out[name] = rungs
    return out



def _normalize_aoi_templates_used(raw: object) -> list[dict[str, Any]]:
    """v0.3.9+ educational AOI/FB template usage stamps (name + params)."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        params_raw = item.get("params") or {}
        params: dict[str, str] = {}
        if isinstance(params_raw, dict):
            for k, v in params_raw.items():
                if isinstance(k, str) and k.strip():
                    params[k.strip()] = "" if v is None else str(v)
        out.append({"name": name, "params": params})
    return out


def program_from_dict(raw: object) -> dict[str, Any]:
    """Parse a program block. Missing or empty is fine (older cabinets)."""
    if raw is None:
        return empty_program()
    if not isinstance(raw, dict):
        raise ValueError("Program must be an object.")
    answers_raw = raw.get("answers", {})
    if answers_raw is None:
        answers_raw = {}
    if not isinstance(answers_raw, dict):
        raise ValueError("Program answers must be an object.")
    answers: dict[str, str] = {}
    for key, value in answers_raw.items():
        if not isinstance(key, str):
            raise ValueError("Program answer names must be text.")
        if isinstance(value, (dict, list)):
            raise ValueError(f"Program answer {key} must be a single value.")
        answers[key] = "" if value is None else str(value)
    rungs_raw = raw.get("rungs", [])
    if rungs_raw is None:
        rungs_raw = []
    if not isinstance(rungs_raw, list):
        raise ValueError("Program rungs must be a list.")
    rungs = [_normalize_rung(item, i) for i, item in enumerate(rungs_raw, start=1)]
    hmi_raw = raw.get("hmi_items", [])
    if hmi_raw is None:
        hmi_raw = []
    if not isinstance(hmi_raw, list):
        raise ValueError("Program hmi_items must be a list.")
    hmi_items = [_normalize_hmi_item(item, i) for i, item in enumerate(hmi_raw, start=1)]
    plc_text = raw.get("plc_text", "")
    hmi_text = raw.get("hmi_text", "")
    if plc_text is None:
        plc_text = ""
    if hmi_text is None:
        hmi_text = ""
    if not isinstance(plc_text, str) or not isinstance(hmi_text, str):
        raise ValueError("Program plc_text and hmi_text must be text.")
    text_edited = bool(raw.get("text_edited", False))
    program = {
        "answers": answers,
        "rungs": rungs,
        "hmi_items": hmi_items,
        "plc_text": plc_text,
        "hmi_text": hmi_text,
        "text_edited": text_edited,
    }
    # v0.3.7 tag database: user descriptions keyed by tag (kept only when present).
    descs = _normalize_tag_descriptions(raw.get("tag_descriptions"))
    if descs:
        program["tag_descriptions"] = descs
    aliases = _normalize_tag_aliases(raw.get("tag_aliases"))
    if aliases:
        program["tag_aliases"] = aliases
    routines = _normalize_routines(raw.get("routines"))
    if routines:
        program["routines"] = routines
    aoi_used = _normalize_aoi_templates_used(raw.get("aoi_templates_used"))
    if aoi_used:
        program["aoi_templates_used"] = aoi_used
    if rungs and (not text_edited) and plc_text_looks_stale_empty(plc_text, rungs):
        program["plc_text"] = format_plc_text(rungs)
    elif rungs and not plc_text.strip():
        program["plc_text"] = format_plc_text(rungs)
    if hmi_items and not hmi_text.strip():
        program["hmi_text"] = format_hmi_text(hmi_items)
    return program


def program_to_dict(program: dict[str, Any] | None) -> dict[str, Any]:
    data = program_from_dict(program or {})
    rungs_out = []
    for rung in data["rungs"]:
        entry = {
            "id": rung["id"],
            "parallel": [[dict(c) for c in branch] for branch in rung.get("parallel") or []],
            "series": [dict(c) for c in rung.get("series") or []],
            "coil_tag": rung.get("coil_tag", ""),
            "coil_negated": bool(rung.get("coil_negated", False)),
            "comment": rung.get("comment", ""),
            "contact_tag": rung.get("contact_tag", ""),
            "normally_closed": bool(rung.get("normally_closed", False)),
        }
        if isinstance(rung.get("timer"), dict) and rung["timer"].get("tag"):
            entry["timer"] = {
                "tag": str(rung["timer"].get("tag") or "").strip(),
                "block": str(rung["timer"].get("block") or "TON").upper(),
                "pt_ms": max(0, int(rung["timer"].get("pt_ms") or 0)),
            }
        counter = _normalize_counter(rung.get("counter")) if isinstance(rung.get("counter"), dict) else None
        if counter:
            entry["counter"] = counter
        if isinstance(rung.get("mid_coils"), list) and rung.get("mid_coils"):
            entry["mid_coils"] = [dict(m) for m in rung["mid_coils"] if isinstance(m, dict)]
        if isinstance(rung.get("elements"), list) and rung.get("elements"):
            entry["elements"] = [dict(e) for e in rung["elements"] if isinstance(e, dict)]
        rungs_out.append(entry)
    out = {
        "answers": dict(data["answers"]),
        "rungs": rungs_out,
        "hmi_items": [dict(item) for item in data["hmi_items"]],
        "plc_text": data["plc_text"],
        "hmi_text": data["hmi_text"],
        "text_edited": bool(data["text_edited"]),
    }
    if data.get("tag_descriptions"):
        out["tag_descriptions"] = dict(data["tag_descriptions"])
    if data.get("tag_aliases"):
        out["tag_aliases"] = dict(data["tag_aliases"])
    if data.get("routines"):
        # Re-serialize each routine's rungs with the same shape as Main.
        routines_out: dict[str, list] = {}
        for rname, rrungs in data["routines"].items():
            # Build via temporary program_to_dict of a stub
            stub = program_to_dict({"rungs": rrungs, "answers": {}, "hmi_items": [],
                                   "plc_text": "", "hmi_text": "", "text_edited": False})
            routines_out[str(rname)] = stub["rungs"]
        out["routines"] = routines_out
    if data.get("aoi_templates_used"):
        program_aoi = _normalize_aoi_templates_used(data.get("aoi_templates_used"))
        if program_aoi:
            out["aoi_templates_used"] = program_aoi

    return out


def cabinet_device_tags(project: Project) -> list[dict[str, str]]:
    """Tags and I/O already on the cabinet. Never invent catalog numbers or tags."""
    devices: list[dict[str, str]] = []
    for item in project.items:
        tag = (item.fields.get("tag") or "").strip()
        if not tag:
            continue
        devices.append(
            {
                "tag": tag,
                "type_id": item.type_id,
                "function": (item.fields.get("function") or "").strip(),
                "description": (item.fields.get("description") or "").strip(),
                "io_direction": (item.fields.get("io_direction") or "").strip(),
                "io_address": (item.fields.get("io_address") or "").strip(),
                "wire_numbers": (item.fields.get("wire_numbers") or "").strip(),
                "terminal_landings": (item.fields.get("terminal_landings") or "").strip(),
            }
        )
    return devices


def devices_by_tag(project: Project) -> dict[str, dict[str, str]]:
    return {d["tag"]: d for d in cabinet_device_tags(project)}


def _haystack(device: dict[str, str]) -> str:
    return " ".join(
        [
            device.get("tag", ""),
            device.get("function", ""),
            device.get("description", ""),
            device.get("type_id", ""),
        ]
    ).lower()


def device_role_label(device: dict[str, str] | None, *, normally_closed: bool = False) -> str:
    """Plain hardware role for ladder captions, e.g. Start PB, E-Stop, Motor Contactor."""
    if not device:
        return "Device"
    type_id = (device.get("type_id") or "").strip()
    function = (device.get("function") or "").strip()
    hay = _haystack(device)
    if type_id == "pushbutton":
        role = function or (
            "Start"
            if "start" in hay
            else "Stop"
            if "stop" in hay and "e-stop" not in hay and "estop" not in hay
            else "Reverse"
            if "reverse" in hay or "rev" in hay.split()
            else "Forward"
            if "forward" in hay or "fwd" in hay.split()
            else "Pushbutton"
        )
        if role.lower() == "pushbutton":
            base = "PB"
        elif role.lower().endswith(" pb"):
            base = role
        else:
            base = f"{role} PB"
    elif type_id == "estop":
        base = "E-Stop"
    elif type_id == "contactor":
        if "reverse" in hay or "rev" in device.get("tag", "").lower():
            base = "Reverse Contactor"
        elif "forward" in hay or "fwd" in device.get("tag", "").lower():
            base = "Forward Contactor"
        else:
            base = "Motor Contactor"
    elif type_id == "safety_relay":
        base = "Safety Relay"
    else:
        base = TYPE_ROLE_NAMES.get(type_id, type_id.replace("_", " ").title() or "Device")
    if normally_closed and type_id in {"pushbutton", "estop", "contactor", "safety_relay"}:
        if " NC" not in base:
            return f"{base} NC"
    return base


def device_caption(device: dict[str, str] | None, tag: str, *, normally_closed: bool = False) -> str:
    """Tag plus role, e.g. HS_START (Start PB)."""
    role = device_role_label(device, normally_closed=normally_closed)
    clean = (tag or "").strip() or "(no tag)"
    return f"{clean} ({role})"


def device_hover_detail(
    device: dict[str, str] | None,
    tag: str,
    *,
    kind: str = "contact",
    normally_closed: bool = False,
    wire_hint: str = "",
    rung_comment: str = "",
) -> str:
    """Multi-line popup text for ladder hover (device type, tag, wires, from/to, I/O, why)."""
    role = device_role_label(device, normally_closed=normally_closed)
    clean = (tag or "").strip() or "(no tag)"
    symbol = "NC contact" if normally_closed and kind == "contact" else (
        "NO contact" if kind == "contact" else ("Negated coil" if kind == "coil" else "Coil")
    )
    if kind == "wire":
        symbol = "Wire"
    lines = [f"{symbol}: {clean}", f"Type: {role}"]
    if device:
        desc = (device.get("description") or "").strip()
        if desc:
            lines.append(f"Why: {desc}")
        wires = (device.get("wire_numbers") or "").strip()
        if wires:
            lines.append(f"Wires: {wires}")
        land = (device.get("terminal_landings") or "").strip()
        if land:
            lines.append(f"From/to: {land}")
        io_bits = [
            (device.get("io_direction") or "").strip(),
            (device.get("io_address") or "").strip(),
        ]
        io_line = " ".join(bit for bit in io_bits if bit)
        if io_line:
            lines.append(f"I/O: {io_line}")
        func = (device.get("function") or "").strip()
        if func and func.lower() not in (desc or "").lower():
            lines.append(f"Function: {func}")
    if wire_hint:
        lines.append(f"Net: {wire_hint}")
    if rung_comment:
        lines.append(f"Rung: {rung_comment}")
    return "\n".join(lines)


def find_start_tag(devices: list[dict[str, str]]) -> str | None:
    for device in devices:
        if device["type_id"] == "pushbutton" and "start" in _haystack(device):
            hay = _haystack(device)
            if "reverse" in hay or device["tag"].upper().endswith("_REV"):
                continue
            return device["tag"]
    for device in devices:
        if "start" in _haystack(device) and device["type_id"] in {"pushbutton", "io_module"}:
            return device["tag"]
    return None


def find_stop_tag(devices: list[dict[str, str]]) -> str | None:
    for device in devices:
        if device["type_id"] == "pushbutton" and "stop" in _haystack(device) and "e-stop" not in _haystack(device) and "estop" not in _haystack(device):
            return device["tag"]
    for device in devices:
        hay = _haystack(device)
        if "stop" in hay and "e-stop" not in hay and "estop" not in hay and device["type_id"] == "pushbutton":
            return device["tag"]
    return None


def find_estop_tag(devices: list[dict[str, str]]) -> str | None:
    for device in devices:
        if device["type_id"] == "estop":
            return device["tag"]
    for device in devices:
        hay = _haystack(device)
        if "e-stop" in hay or "estop" in hay or "e stop" in hay:
            return device["tag"]
    return None


def find_output_coil_tags(devices: list[dict[str, str]]) -> list[str]:
    """Actuated outputs already on the panel (never invent tags). Prefer drive hardware first.

    When a contactor is present, coil tags are contactors only (motor/VFD are the load, not the
    PLC coil). Otherwise use motor/VFD/solenoid/valve/light tags that already exist.
    """
    found: list[str] = []
    contactors_fwd: list[str] = []
    contactors_rev: list[str] = []
    for device in devices:
        if device["type_id"] != "contactor":
            continue
        tag = (device.get("tag") or "").strip()
        if not tag:
            continue
        hay = _haystack(device)
        if "reverse" in hay or tag.upper().endswith("_REV"):
            if tag not in contactors_rev:
                contactors_rev.append(tag)
        else:
            if tag not in contactors_fwd:
                contactors_fwd.append(tag)
    if contactors_fwd or contactors_rev:
        return contactors_fwd + contactors_rev
    for type_id in ("relay", "motor", "vfd", "solenoid", "valve", "light"):
        for device in devices:
            if device["type_id"] != type_id:
                continue
            tag = (device.get("tag") or "").strip()
            if tag and tag not in found:
                found.append(tag)
    return found


def find_sensor_tags(devices: list[dict[str, str]]) -> list[str]:
    return [
        (d.get("tag") or "").strip()
        for d in devices
        if d.get("type_id") == "sensor" and (d.get("tag") or "").strip()
    ]


def find_reset_tag(devices: list[dict[str, str]]) -> str | None:
    for device in devices:
        if device["type_id"] != "pushbutton":
            continue
        hay = _haystack(device)
        if "reset" in hay or "re-arm" in hay or "rearm" in hay:
            return device["tag"]
    return None


def find_safety_relay_tag(devices: list[dict[str, str]]) -> str | None:
    for device in devices:
        if device["type_id"] == "safety_relay":
            return device["tag"]
    return None


def find_motor_coil_tag(devices: list[dict[str, str]]) -> str | None:
    """Primary output coil on this cabinet — contactor/motor/VFD, else solenoid/valve/light."""
    coils = find_output_coil_tags(devices)
    return coils[0] if coils else None




def find_reverse_tag(devices: list[dict[str, str]]) -> str | None:
    for device in devices:
        hay = _haystack(device)
        tag_u = device["tag"].upper()
        if device["type_id"] == "pushbutton" and ("reverse" in hay or tag_u.endswith("_REV") or tag_u.endswith("-REV") or tag_u.startswith("HS_REV")):
            return device["tag"]
    for device in devices:
        if "reverse" in _haystack(device) or device["tag"].upper().endswith("_REV") or "REV" in device["tag"].upper():
            if device["type_id"] in {"pushbutton", "io_module"}:
                return device["tag"]
    return None


def find_reverse_coil_tag(devices: list[dict[str, str]], forward_coil: str | None) -> str | None:
    for device in devices:
        if device["type_id"] != "contactor":
            continue
        hay = _haystack(device)
        tag_u = device["tag"].upper()
        if "reverse" in hay or tag_u.endswith("_REV") or tag_u.endswith("-REV") or "REV" in tag_u:
            if forward_coil and device["tag"] == forward_coil:
                continue
            return device["tag"]
    contactors = [d["tag"] for d in devices if d["type_id"] == "contactor"]
    if forward_coil and len(contactors) >= 2:
        for tag in contactors:
            if tag != forward_coil:
                return tag
    return None


def _contact_mark(tag: str, nc: bool) -> str:
    clean = tag or "(no tag)"
    return f"[/{clean}]" if nc else f"[{clean}]"


def _coil_mark(tag: str, negated: bool = False) -> str:
    clean = tag or "(no coil)"
    return f"(/{clean})" if negated else f"({clean})"


def format_plc_text(rungs: list[dict[str, Any]], devices: list[dict[str, str]] | None = None) -> str:
    by_tag = {d["tag"]: d for d in (devices or [])}
    from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
    from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE

    lines = [
        LEARNING_NOTE,
        UL_DESIGN_AID,
        SAFETY_DESIGN_AID_NOTE,
        "",
        "PLC ladder (plain text you can copy into your real PLC programmer)",
        "Symbols: [TAG]=NO contact  [/TAG]=NC contact  (TAG)=coil  (/TAG)=negated coil  TON/TOF/RTO=timer  CTU/CTD=counter  (RES C1)=reset  ONS/OSR/OSF=one-shot  nested OR / mid-rung coils supported",
        "Real ladder order: Start NO seals with contactor NO, Stop NC and E-Stop NC in series, coil = contactor.",
        "",
    ]
    if not rungs:
        lines.append("(No rungs yet. Answer the questions or type your own ladder below.)")
        lines.append("")
        return "\n".join(lines)
    for index, rung in enumerate(rungs, start=1):
        comment = (rung.get("comment") or "").strip()
        coil = (rung.get("coil_tag") or "").strip()
        coil_neg = bool(rung.get("coil_negated"))
        parallel = rung.get("parallel") or []
        series = rung.get("series") or []
        comment_rows = [ln.rstrip() for ln in comment.splitlines()] if comment else []
        title = f"Rung {index}" + (f" - {comment_rows[0]}" if comment_rows else "")
        lines.append(title)
        for extra_row in comment_rows[1:]:
            lines.append(f"  // {extra_row}" if extra_row.strip() else "  //")
        if isinstance(rung.get("elements"), list) and rung.get("elements"):
            # Compact IR dump for nested OR / mid-rung educational rungs
            def _el_mark(el: dict) -> str:
                mark = _el_mark_core(el)
                note = str(el.get("desc") or "").strip()
                return f"{mark}{{{note}}}" if note else mark

            def _el_mark_core(el: dict) -> str:
                kind = str(el.get("kind") or "").lower()
                if kind == "oneshot":
                    blk = str(el.get("block") or "ONS").upper()
                    if blk == "ONS":
                        return f"ONS[{el.get('var', '')}]"
                    return f"{blk}[{el.get('var', '')}→{el.get('output', '')}]"
                if kind == "contact":
                    return _contact_mark(el.get("var", ""), str(el.get("form", "NO")).upper() == "NC")
                if kind == "coil":
                    form = str(el.get("form", "")).lower()
                    if form in {"set", "s"}:
                        return f"(S){el.get('var', '')}"
                    if form in {"reset", "r"}:
                        return f"(R){el.get('var', '')}"
                    return _coil_mark(el.get("var", ""), form == "negated")
                if kind == "or":
                    parts = []
                    for br in el.get("branches") or []:
                        parts.append("+".join(_el_mark(i) for i in br))
                    return "(" + " OR ".join(parts) + ")"
                if kind == "timer":
                    if str(el.get("pt_tag") or "").strip():
                        return f"{el.get('block','TON')}[{el.get('var')}/PT={el.get('pt_tag')}]"
                    return f"{el.get('block','TON')}[{el.get('var')}/{el.get('pt_ms',0)}ms]"
                if kind == "counter":
                    if str(el.get("pv_tag") or "").strip():
                        return f"{str(el.get('block') or 'CTU').upper()}[{el.get('var')}/PRE={el.get('pv_tag')}]"
                    return counter_text_mark({"tag": el.get("var"), "block": el.get("block"), "pv": el.get("pv", 0)})
                if kind == "compare":
                    op = str(el.get("op") or "EQU").upper()
                    if op in {"LIM", "MEQ"}:
                        return f"{op}[{el.get('source_a')},{el.get('source_b')},{el.get('source_c','')}]"
                    return f"{op}[{el.get('source_a')},{el.get('source_b')}]"
                if kind == "math":
                    op = str(el.get("op") or "ADD").upper()
                    if op == "MOV":
                        return f"MOV[{el.get('source_a')}→{el.get('dest')}]"
                    if op == "CPT":
                        return f"CPT[{el.get('dest')}={el.get('expression') or el.get('source_a')}]"
                    if op == "NOT":
                        return f"NOT[{el.get('dest')}=~{el.get('source_a')}]"
                    return f"{op}[{el.get('dest')}={el.get('source_a')},{el.get('source_b')}]"
                return kind
            body = "----".join(_el_mark(e) for e in rung["elements"])
            lines.append(f"  |----{body}----|")
            mid = rung.get("mid_coils") or []
            if mid:
                lines.append("  Mid-coils: " + ", ".join(m.get("tag", "?") for m in mid))
            if coil:
                lines.append(f"  Coil:    {_coil_mark(coil, coil_neg)}")
            if comment_rows:
                lines.append(f"  Note:    {comment_rows[0]}")
            lines.append("")
            continue
        series_marks = [_contact_mark(c.get("tag", ""), bool(c.get("normally_closed"))) for c in series]
        series_bit = "----".join(series_marks) if series_marks else ""
        coil_bit = _coil_mark(coil, coil_neg) if coil else ""
        tmr = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
        timer_bit = ""
        if tmr and (tmr.get("tag") or "").strip():
            timer_bit = f"{str(tmr.get('block') or 'TON').upper()}[{(tmr.get('tag') or '').strip()}/{int(tmr.get('pt_ms') or 0)}ms]"
        ctr = rung.get("counter") if isinstance(rung.get("counter"), dict) else None
        counter_bit = counter_text_mark(ctr)
        actuator_bits = [b for b in (timer_bit, counter_bit, coil_bit) if b]
        actuator = "----".join(actuator_bits) if actuator_bits else "()"
        if parallel:
            branch_marks = []
            for branch in parallel:
                marks = [_contact_mark(c.get("tag", ""), bool(c.get("normally_closed"))) for c in branch]
                branch_marks.append("----".join(marks) if marks else "[ ]")
            width = max(len(b) for b in branch_marks)
            pad_branches = [b.ljust(width) for b in branch_marks]
            after = f"----{series_bit}----{actuator}" if series_bit else f"----{actuator}"
            if len(pad_branches) == 1:
                lines.append(f"  |----{pad_branches[0]}{after}----|")
            else:
                lines.append(f"  |----{pad_branches[0]}----+{after}----|")
                pad = " " * (len(after) + 3)
                for branch in pad_branches[1:]:
                    lines.append(f"  |----{branch}----+{pad}|")
        else:
            body = "----".join(series_marks + actuator_bits) if series_marks else actuator
            lines.append(f"  |----{body}----|")
        for branch in parallel:
            for contact in branch:
                tag = contact.get("tag", "")
                cap = device_caption(by_tag.get(tag), tag, normally_closed=bool(contact.get("normally_closed")))
                form = "NC" if contact.get("normally_closed") else "NO"
                seal = "  (seal-in)" if tag == coil and not contact.get("normally_closed") else ""
                lines.append(f"  Contact: {_contact_mark(tag, bool(contact.get('normally_closed')))}  ({form})  {cap}{seal}")
        for contact in series:
            tag = contact.get("tag", "")
            cap = device_caption(by_tag.get(tag), tag, normally_closed=bool(contact.get("normally_closed")))
            form = "NC" if contact.get("normally_closed") else "NO"
            lines.append(f"  Contact: {_contact_mark(tag, bool(contact.get('normally_closed')))}  ({form})  {cap}")
        tmr = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
        if tmr and (tmr.get("tag") or "").strip():
            t_tag = (tmr.get("tag") or "").strip()
            blk = str(tmr.get("block") or "TON").upper()
            pt = int(tmr.get("pt_ms") or 0)
            lines.append(f"  Timer:   {blk}({t_tag}) PT={pt}ms")
        if ctr and (ctr.get("tag") or "").strip():
            c_tag = (ctr.get("tag") or "").strip()
            c_blk = str(ctr.get("block") or "CTU").upper()
            if c_blk == "RES":
                lines.append(f"  Counter: RES({c_tag})  ACC:=0")
            elif c_blk == "LOAD":
                lines.append(f"  Counter: LOAD({c_tag})  ACC:=PRE")
            else:
                done = "ACC>=PRE" if c_blk == "CTU" else "ACC<=0"
                lines.append(
                    f"  Counter: {c_blk}({c_tag}) PRE={int(ctr.get('pv') or 0)}  DN when {done}"
                )
        if coil:
            coil_cap = device_caption(by_tag.get(coil), coil)
            lines.append(f"  Coil:    {_coil_mark(coil, coil_neg)}  {coil_cap}")
        if comment_rows:
            lines.append(f"  Note:    {comment_rows[0]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_hmi_text(items: list[dict[str, str]]) -> str:
    lines = [
        LEARNING_NOTE,
        "",
        "HMI screens and indicators (edit the names, then copy into your HMI software)",
        "",
        "Screen: Main",
    ]
    if not items:
        lines.append("  (No indicators yet.)")
        lines.append("")
        return "\n".join(lines)
    for item in items:
        kind = (item.get("kind") or "indicator").strip()
        label = (item.get("label") or "").strip() or "(unnamed)"
        lines.append(f"  - [{kind}] {label}")
    lines.append("")
    return "\n".join(lines)


def refresh_plc_text(program: dict[str, Any], project: Project | None = None) -> dict[str, Any]:
    data = program_from_dict(program)
    devices = cabinet_device_tags(project) if project is not None else []
    data["plc_text"] = format_plc_text(data["rungs"], devices)
    return data


_ELEMENT_OUTPUT_KINDS = frozenset(
    {"coil", "timer", "counter", "math", "compare", "oneshot", "jsr", "sbr", "ret"}
)


# v0.3.18: an OR whose branches drive outputs (parallel coils, e.g. Start → (Motor | Lamp))
# is part of the OUTPUT section: a series contact added to the rung must gate all of them.
_ACTUATOR_KINDS = frozenset({"coil", "timer", "counter", "math", "oneshot", "jsr", "ret"})


def _is_output_branch_group(el: dict[str, Any]) -> bool:
    if str(el.get("kind") or "").lower() != "or":
        return False

    def has_actuator(items: list) -> bool:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            k = str(it.get("kind") or "").lower()
            if k in _ACTUATOR_KINDS:
                return True
            if k == "or" and any(has_actuator(list(b or [])) for b in it.get("branches") or []):
                return True
        return False

    return any(has_actuator(list(b or [])) for b in el.get("branches") or [])


def _series_portion_bounds(els: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (series_start, out_start) for trailing series contacts before outputs."""
    out_start = len(els)
    for j in range(len(els) - 1, -1, -1):
        if str(els[j].get("kind") or "").lower() in _ELEMENT_OUTPUT_KINDS or _is_output_branch_group(els[j]):
            out_start = j
        else:
            break
    series_start = out_start
    while series_start > 0 and str(els[series_start - 1].get("kind") or "").lower() == "contact":
        series_start -= 1
    return series_start, out_start


def series_contacts_from_rung(rung: dict[str, Any]) -> list[dict[str, Any]]:
    """Legacy-shaped contacts currently in the series portion (from elements when present).

    Compare / math / OTL / oneshot rungs store the enable contact in ``parallel``
    (or only in ``elements``), so legacy ``series`` is often empty — callers that
    rebuild from ``series`` alone wipe that enable contact (REG-2).
    """
    from cabinet_studio.services.ladder_ir import program_rung_to_elements

    els = program_rung_to_elements(rung) if isinstance(rung, dict) else []
    if els:
        series_start, out_start = _series_portion_bounds(els)
        out: list[dict[str, Any]] = []
        for e in els[series_start:out_start]:
            if str(e.get("kind") or "").lower() != "contact":
                continue
            tag = str(e.get("var") or "").strip()
            if not tag:
                continue
            out.append(
                {
                    "tag": tag,
                    "normally_closed": str(e.get("form") or "NO").upper() == "NC",
                }
            )
        return out
    return [dict(c) for c in (rung.get("series") or []) if isinstance(c, dict)]


def append_series_contact(
    program: dict[str, Any],
    rung_id: str,
    tag: str,
    *,
    normally_closed: bool = False,
) -> dict[str, Any]:
    """UI / API 'Add series contact' — preserves enable contacts without duplicating (REG-1/2/3).

    Classic legacy rungs store the first contact in ``parallel`` with empty ``series``.
    Rewriting via ``edit_rung(series=[…])`` left ``parallel`` stale and doubled contacts
    (REG-3). Always rebuild from elements like ``append_parallel_contact``.
    """
    from copy import deepcopy

    from cabinet_studio.services.ladder_ir import (
        _contact_el,
        clean_elements,
        elements_to_program_rung,
        program_rung_to_elements,
    )

    contact = str(tag or "").strip()
    if not contact:
        raise ValueError("Series contact tag is required.")
    data = program_from_dict(program)
    target = next((r for r in data["rungs"] if r["id"] == rung_id), None)
    if target is None:
        raise KeyError(f"No rung with id {rung_id}")
    els = deepcopy(program_rung_to_elements(target))
    new_c = _contact_el(contact, normally_closed)
    if not els:
        els = [new_c]
    else:
        _series_start, out_start = _series_portion_bounds(els)
        els = els[:out_start] + [new_c] + els[out_start:]
    new_rung = elements_to_program_rung(
        clean_elements(els),
        rung_id=str(target.get("id") or ""),
        comment=str(target.get("comment") or ""),
    )
    target.clear()
    target.update(new_rung)
    legacy = _legacy_fields_from_rung(target)
    target["contact_tag"] = legacy["contact_tag"]
    target["normally_closed"] = legacy["normally_closed"]
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def append_parallel_contact(
    program: dict[str, Any],
    rung_id: str,
    tag: str,
    *,
    normally_closed: bool = False,
) -> dict[str, Any]:
    """Add a parallel OR branch contact without dropping existing logic."""
    from copy import deepcopy

    from cabinet_studio.services.ladder_ir import (
        _contact_el,
        clean_elements,
        elements_to_program_rung,
        program_rung_to_elements,
    )

    contact = str(tag or "").strip()
    if not contact:
        raise ValueError("Parallel contact tag is required.")
    data = program_from_dict(program)
    target = None
    for rung in data["rungs"]:
        if rung["id"] == rung_id:
            target = rung
            break
    if target is None:
        raise KeyError(f"No rung with id {rung_id}")
    els = deepcopy(program_rung_to_elements(target))
    new_c = _contact_el(contact, normally_closed)
    if not els:
        els = [new_c]
    else:
        # Insert as OR with the leading condition group (contact or OR), else prefix.
        head = els[0]
        kind = str(head.get("kind") or "").lower()
        if kind == "or":
            branches = list(head.get("branches") or [])
            branches.append([new_c])
            head["branches"] = branches
        elif kind == "contact":
            els[0] = {"kind": "or", "branches": [[head], [new_c]]}
        else:
            els.insert(0, new_c)
    new_rung = elements_to_program_rung(
        clean_elements(els),
        rung_id=str(target.get("id") or ""),
        comment=str(target.get("comment") or ""),
    )
    target.clear()
    target.update(new_rung)
    legacy = _legacy_fields_from_rung(target)
    target["contact_tag"] = legacy["contact_tag"]
    target["normally_closed"] = legacy["normally_closed"]
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def _sync_elements_after_legacy_edit(rung: dict[str, Any], changes: dict[str, Any]) -> None:
    """Keep stored ``elements`` in sync with series/coil/contact edits (REG-1 + REG-2).

    Seal-in / AOI / compare / math / latch / oneshot rungs force-store ``elements``.
    Sim, print, export and PLC text all read ``elements``.
    """
    from copy import deepcopy

    from cabinet_studio.services.ladder_ir import (
        _coil_el,
        _contact_el,
        clean_elements,
        elements_to_program_rung,
        program_rung_to_elements,
    )

    if not isinstance(rung.get("elements"), list) or not rung.get("elements"):
        return
    structural = any(
        k in changes
        for k in (
            "series",
            "parallel",
            "coil_tag",
            "coil_negated",
            "contact_tag",
            "normally_closed",
            "timer",
            "counter",
        )
    )
    if not structural:
        return

    els = deepcopy(program_rung_to_elements(rung))
    if not els:
        return
    series_start, out_start = _series_portion_bounds(els)
    prefix = els[:series_start]
    outputs = els[out_start:]
    existing_series = els[series_start:out_start]

    if "series" in changes and changes["series"] is not None:
        new_series = []
        for c in changes["series"] or []:
            if not isinstance(c, dict):
                continue
            tag = str(c.get("tag") or "").strip()
            if tag:
                new_series.append(_contact_el(tag, bool(c.get("normally_closed"))))
        # REG-2: if caller rebuilt from empty legacy ``series`` (UI path for
        # compare/math/OTL/oneshot), the list may be only the newly added
        # contact(s). Preserve existing series-portion contacts and append.
        existing_tags = {
            str(e.get("var") or "")
            for e in existing_series
            if str(e.get("kind") or "").lower() == "contact"
        }
        new_tags = {str(e.get("var") or "") for e in new_series}
        if existing_series and new_series and existing_tags and not (existing_tags & new_tags):
            els = prefix + existing_series + new_series + outputs
        else:
            els = prefix + new_series + outputs
    else:
        els = prefix + existing_series + outputs

    if "coil_tag" in changes and changes["coil_tag"] is not None:
        new_coil = str(changes["coil_tag"]).strip()
        old_coil = ""
        for e in els:
            if e.get("kind") != "coil":
                continue
            form = str(e.get("form") or "normal").lower()
            # v0.3.13: rename OTE and OTL/OTU coils (set/reset) for tag edit.
            old_coil = str(e.get("var") or "")
            e["var"] = new_coil
            if "coil_negated" in changes and changes["coil_negated"] is not None:
                if form in {"set", "reset", "otl", "otu"}:
                    pass  # keep latch form
                else:
                    e["form"] = "negated" if changes["coil_negated"] else "normal"
            break
        if old_coil and new_coil and old_coil != new_coil:
            def _rename(node):
                if not isinstance(node, dict):
                    return
                if node.get("kind") == "contact" and node.get("var") == old_coil:
                    node["var"] = new_coil
                if node.get("kind") == "or":
                    for br in node.get("branches") or []:
                        for item in br or []:
                            _rename(item)
            for e in els:
                _rename(e)

    if "contact_tag" in changes and changes["contact_tag"] is not None:
        tag = str(changes["contact_tag"]).strip()
        nc = (
            bool(changes["normally_closed"])
            if "normally_closed" in changes and changes["normally_closed"] is not None
            else None
        )
        updated = False
        for e in els:
            if e.get("kind") == "or":
                branches = e.get("branches") or []
                if branches and branches[0]:
                    first = branches[0][0]
                    if isinstance(first, dict) and first.get("kind") == "contact":
                        first["var"] = tag
                        if nc is not None:
                            first["form"] = "NC" if nc else "NO"
                        updated = True
                        break
            if e.get("kind") == "contact":
                e["var"] = tag
                if nc is not None:
                    e["form"] = "NC" if nc else "NO"
                updated = True
                break
        _ = updated

    new_rung = elements_to_program_rung(
        clean_elements(els),
        rung_id=str(rung.get("id") or ""),
        comment=str(rung.get("comment") or ""),
    )
    rung.clear()
    rung.update(new_rung)


def edit_rung(program: dict[str, Any], rung_id: str, **changes: Any) -> dict[str, Any]:
    """Update one rung and refresh plc_text. Used by tests and the editor."""
    data = program_from_dict(program)
    found = False
    for rung in data["rungs"]:
        if rung["id"] != rung_id:
            continue
        found = True
        if "comment" in changes and changes["comment"] is not None:
            rung["comment"] = str(changes["comment"]).strip()
        if "coil_tag" in changes and changes["coil_tag"] is not None:
            rung["coil_tag"] = str(changes["coil_tag"]).strip()
        if "coil_negated" in changes and changes["coil_negated"] is not None:
            rung["coil_negated"] = bool(changes["coil_negated"])
        if "normally_closed" in changes and changes["normally_closed"] is not None:
            nc = bool(changes["normally_closed"])
            rung["normally_closed"] = nc
            if rung.get("parallel") and rung["parallel"][0]:
                rung["parallel"][0][0]["normally_closed"] = nc
            elif rung.get("series"):
                rung["series"][0]["normally_closed"] = nc
        if "contact_tag" in changes and changes["contact_tag"] is not None:
            tag = str(changes["contact_tag"]).strip()
            rung["contact_tag"] = tag
            if rung.get("parallel") and rung["parallel"][0]:
                rung["parallel"][0][0]["tag"] = tag
            elif rung.get("series"):
                rung["series"][0]["tag"] = tag
            else:
                rung["parallel"] = [[{"tag": tag, "normally_closed": bool(rung.get("normally_closed"))}]]
        if "parallel" in changes and changes["parallel"] is not None:
            rung["parallel"] = changes["parallel"]
        if "series" in changes and changes["series"] is not None:
            # v0.3.15 N-2: classic rungs (no stored elements) keep their
            # ``parallel`` lead contact(s); ``series=`` replaces only the legacy
            # series list. REG-3: callers that built the list from
            # series_contacts_from_rung() include the single-branch lead
            # contact(s) at the front — strip that copy so it is not duplicated.
            if not (isinstance(rung.get("elements"), list) and rung.get("elements")):
                new_series: list[dict[str, Any]] = []
                for c in changes["series"] or []:
                    if not isinstance(c, dict):
                        continue
                    t = str(c.get("tag") or "").strip()
                    if t:
                        new_series.append({"tag": t, "normally_closed": bool(c.get("normally_closed"))})
                par = rung.get("parallel") or []
                if (
                    len(par) == 1
                    and isinstance(par[0], list)
                    and par[0]
                    and all(isinstance(c, dict) and str(c.get("kind") or "contact").lower() == "contact" for c in par[0])
                ):
                    lead = [
                        (str(c.get("tag") or "").strip(), bool(c.get("normally_closed")))
                        for c in par[0]
                    ]
                    head = [(c["tag"], c["normally_closed"]) for c in new_series[: len(lead)]]
                    if lead and head == lead:
                        new_series = new_series[len(lead):]
                rung["series"] = new_series
                # Classic rung: nothing stored in ``elements`` to sync.
                changes = {k: v for k, v in changes.items() if k != "series"}
            else:
                rung["series"] = changes["series"]
        if "timer" in changes:
            timer = _normalize_timer(changes["timer"])
            if timer:
                rung["timer"] = timer
            else:
                rung.pop("timer", None)
        if "counter" in changes:
            counter = _normalize_counter(changes["counter"])
            if counter:
                rung["counter"] = counter
            else:
                rung.pop("counter", None)
        # REG-1: elements-stored rungs must reflect series/coil/contact edits.
        _sync_elements_after_legacy_edit(rung, changes)
        legacy = _legacy_fields_from_rung(rung)
        rung["contact_tag"] = legacy["contact_tag"]
        rung["normally_closed"] = legacy["normally_closed"]
        break
    if not found:
        raise KeyError(f"No rung with id {rung_id}")
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def add_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    coil_tag: str,
    normally_closed: bool = False,
    comment: str = "",
    series: list[dict[str, Any]] | None = None,
    parallel: list[list[dict[str, Any]]] | None = None,
    coil_negated: bool = False,
) -> dict[str, Any]:
    data = program_from_dict(program)
    if parallel is None:
        # v0.3.15 N-2: ``contact_tag`` is the lead contact even when ``series``
        # is given (A·B -> Y); previously it was silently dropped.
        contact = {"tag": contact_tag.strip(), "normally_closed": bool(normally_closed)}
        parallel = [[contact]] if contact["tag"] else []
        if series is None:
            series = []
    rung = {
        "id": new_rung_id(),
        "parallel": parallel or [],
        "series": series or [],
        "coil_tag": coil_tag.strip(),
        "coil_negated": bool(coil_negated),
        "comment": comment.strip(),
    }
    legacy = _legacy_fields_from_rung(rung)
    rung["contact_tag"] = legacy["contact_tag"]
    rung["normally_closed"] = legacy["normally_closed"]
    data["rungs"].append(rung)
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def set_rung_timer(
    program: dict[str, Any],
    rung_id: str,
    *,
    tag: str,
    block: str = "TON",
    pt_ms: int = 1000,
) -> dict[str, Any]:
    """Attach or replace an educational timer on an existing rung."""
    data = program_from_dict(program)
    timer = _normalize_timer({"tag": tag, "block": block, "pt_ms": pt_ms})
    if not timer:
        raise ValueError("Timer tag is required.")
    found = False
    for rung in data["rungs"]:
        if rung["id"] != rung_id:
            continue
        rung["timer"] = timer
        found = True
        break
    if not found:
        raise KeyError(f"No rung with id {rung_id}")
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def add_timer_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    timer_tag: str,
    block: str = "TON",
    pt_ms: int = 1000,
    normally_closed: bool = False,
    coil_tag: str = "",
    comment: str = "",
) -> dict[str, Any]:
    """Add a rung with contact(s) energizing a TON/TOF/RTO timer (optional coil after)."""
    data = add_rung(
        program,
        contact_tag=contact_tag,
        coil_tag=coil_tag or "",
        normally_closed=normally_closed,
        comment=comment or f"{str(block or 'TON').upper()} {timer_tag.strip()}",
    )
    rid = data["rungs"][-1]["id"]
    return set_rung_timer(data, rid, tag=timer_tag, block=block, pt_ms=pt_ms)


def set_rung_counter(
    program: dict[str, Any],
    rung_id: str,
    *,
    tag: str,
    block: str = "CTU",
    pv: int = 5,
) -> dict[str, Any]:
    """Attach or replace an educational counter instruction on an existing rung."""
    data = program_from_dict(program)
    counter = _normalize_counter({"tag": tag, "block": block, "pv": pv})
    if not counter:
        raise ValueError("Counter tag is required.")
    found = False
    for rung in data["rungs"]:
        if rung["id"] != rung_id:
            continue
        rung["counter"] = counter
        found = True
        break
    if not found:
        raise KeyError(f"No rung with id {rung_id}")
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def add_counter_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    counter_tag: str,
    block: str = "CTU",
    pv: int = 5,
    normally_closed: bool = False,
    coil_tag: str = "",
    comment: str = "",
) -> dict[str, Any]:
    """Add a rung: contact → CTU/CTD (or RES/LOAD) on counter_tag (optional coil after)."""
    blk = str(block or "CTU").upper()
    if not comment:
        comment = f"{blk} {counter_tag.strip()}" + (f" PRE={int(pv)}" if blk in {"CTU", "CTD"} else "")
    data = add_rung(
        program,
        contact_tag=contact_tag,
        coil_tag=coil_tag or "",
        normally_closed=normally_closed,
        comment=comment,
    )
    rid = data["rungs"][-1]["id"]
    return set_rung_counter(data, rid, tag=counter_tag, block=blk, pv=pv)




def add_rung_from_elements(
    program: dict[str, Any],
    elements: list[dict[str, Any]],
    *,
    comment: str = "",
) -> dict[str, Any]:
    """Add a rung from a full IR element list (nested OR / mid-rung coils)."""
    from cabinet_studio.services.ladder_ir import clean_elements, elements_to_program_rung

    data = program_from_dict(program)
    cleaned = clean_elements(elements)
    if not cleaned:
        raise ValueError("Rung elements are required.")
    rung = elements_to_program_rung(cleaned, comment=comment)
    data["rungs"].append(rung)
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def add_nested_or_rung(
    program: dict[str, Any],
    *,
    lead_tag: str,
    or_branches: list[list[dict[str, Any]]],
    coil_tag: str,
    series_after: list[dict[str, Any]] | None = None,
    comment: str = "",
) -> dict[str, Any]:
    """Build ``lead -- (branch0 OR branch1 OR ...) -- series -- (coil)``.

    Each branch is a list of contact dicts ``{tag, normally_closed}`` and may
    itself contain a nested ``{"kind":"or","branches":[...]}`` IR element for
    deeper nesting (educational CCW-style).
    """
    from cabinet_studio.services.ladder_ir import _contact_el, _coil_el, _clean_logic_item

    elements: list[dict[str, Any]] = []
    lead = (lead_tag or "").strip()
    if lead:
        elements.append(_contact_el(lead, False))
    branches: list[list[dict[str, Any]]] = []
    for branch in or_branches or []:
        branch_els: list[dict[str, Any]] = []
        for item in branch or []:
            if isinstance(item, dict) and str(item.get("kind") or "").lower() == "or":
                cleaned = _clean_logic_item(item)
                if cleaned:
                    branch_els.append(cleaned)
            else:
                tag = str((item or {}).get("tag") or (item or {}).get("var") or "").strip()
                if tag:
                    branch_els.append(
                        _contact_el(tag, bool((item or {}).get("normally_closed")))
                    )
        if branch_els:
            branches.append(branch_els)
    if branches:
        elements.append({"kind": "or", "branches": branches})
    for c in series_after or []:
        tag = str(c.get("tag") or "").strip()
        if tag:
            elements.append(_contact_el(tag, bool(c.get("normally_closed"))))
    coil = (coil_tag or "").strip()
    if coil:
        elements.append(_coil_el(coil))
    return add_rung_from_elements(program, elements, comment=comment or "Nested OR")


def add_mid_coil_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    mid_coil_tag: str,
    after_contact_tag: str,
    coil_tag: str,
    normally_closed: bool = False,
    after_normally_closed: bool = False,
    comment: str = "",
) -> dict[str, Any]:
    """``[contact] -- (mid_coil) -- [after_contact] -- (coil)`` mid-rung pattern."""
    from cabinet_studio.services.ladder_ir import _contact_el, _coil_el

    elements = [
        _contact_el(contact_tag, normally_closed),
        _coil_el(mid_coil_tag),
        _contact_el(after_contact_tag, after_normally_closed),
        _coil_el(coil_tag),
    ]
    return add_rung_from_elements(
        program,
        elements,
        comment=comment or f"Mid-rung {mid_coil_tag} then {coil_tag}",
    )



def add_compare_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    op: str,
    source_a: str,
    source_b: str,
    coil_tag: str,
    source_c: str = "",
    normally_closed: bool = False,
    comment: str = "",
) -> dict[str, Any]:
    """``[contact] -- CMP(op) -- (coil)`` educational compare rung (LIM/MEQ use source_c)."""
    from cabinet_studio.services.ladder_ir import _contact_el, _coil_el, _compare_el

    elements = [
        _contact_el(contact_tag, normally_closed),
        _compare_el(op, source_a, source_b, source_c),
        _coil_el(coil_tag),
    ]
    mop = str(op or "EQU").upper()
    detail = f"{source_a},{source_b},{source_c}" if mop in {"LIM", "MEQ"} else f"{source_a},{source_b}"
    return add_rung_from_elements(
        program,
        elements,
        comment=comment or f"Compare {mop} {detail}",
    )


def add_math_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    op: str,
    dest: str,
    source_a: str,
    source_b: str = "",
    expression: str = "",
    normally_closed: bool = False,
    comment: str = "",
) -> dict[str, Any]:
    """``[contact] -- MATH/MOV --`` educational math rung (no coil required)."""
    from cabinet_studio.services.ladder_ir import _contact_el, _math_el

    elements = [
        _contact_el(contact_tag, normally_closed),
        _math_el(op, dest, source_a, source_b, expression),
    ]
    return add_rung_from_elements(
        program,
        elements,
        comment=comment or f"Math {str(op or 'ADD').upper()} → {dest}",
    )


def add_aoi_template_rungs(
    program: dict[str, Any],
    name: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Insert an educational AOI/FB template (rung expansion — not a vendor AOI runtime)."""
    from cabinet_studio.services.ladder_templates import apply_aoi_template

    return apply_aoi_template(program, name, params)


def add_latch_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    coil_tag: str,
    latch: bool = True,
    normally_closed: bool = False,
    comment: str = "",
) -> dict[str, Any]:
    """OTL (set) / OTU (reset) latch coil rung — CCW/Studio educational."""
    from cabinet_studio.services.ladder_ir import _contact_el, _coil_el

    form = "set" if latch else "reset"
    label = "OTL" if latch else "OTU"
    elements = [
        _contact_el(contact_tag, normally_closed),
        _coil_el(coil_tag, form=form),
    ]
    return add_rung_from_elements(
        program,
        elements,
        comment=comment or f"{label} {coil_tag}",
    )


def add_oneshot_rung(
    program: dict[str, Any],
    *,
    contact_tag: str,
    block: str = "ONS",
    storage_tag: str,
    output_tag: str = "",
    coil_tag: str = "",
    normally_closed: bool = False,
    comment: str = "",
) -> dict[str, Any]:
    """One-shot rung (Studio/CCW educational).

    ONS: ``[contact] -- [ONS storage] -- (coil)`` — coil is TRUE one scan per press.
    OSR/OSF: ``[contact] -- [OSR storage → output]`` (optional coil after; power
    passes through). Use the output bit as a contact on later rungs.
    """
    from cabinet_studio.services.ladder_ir import (
        _coil_el,
        _contact_el,
        _oneshot_el,
        normalize_oneshot_block,
    )

    blk = normalize_oneshot_block(block)
    storage = (storage_tag or "").strip()
    if not storage:
        raise ValueError("One-shot storage bit is required.")
    output = (output_tag or "").strip()
    if blk in {"OSR", "OSF"} and not output:
        raise ValueError(f"{blk} needs an output bit.")
    elements = [_contact_el(contact_tag, normally_closed), _oneshot_el(blk, storage, output)]
    coil = (coil_tag or "").strip()
    if coil:
        elements.append(_coil_el(coil))
    if not comment:
        if blk == "ONS":
            comment = f"ONS one-shot on {contact_tag}" + (f" → {coil}" if coil else "")
        else:
            edge = "rising" if blk == "OSR" else "falling"
            comment = f"{blk} {edge}-edge pulse {output} from {contact_tag}"
    return add_rung_from_elements(program, elements, comment=comment)


def set_rung_comment(program: dict[str, Any], rung_id: str, comment: str) -> dict[str, Any]:
    """Replace a rung's (possibly multi-line) comment. Trailing spaces per line trimmed."""
    text = "\n".join(line.rstrip() for line in str(comment or "").replace("\r\n", "\n").split("\n")).strip()
    return edit_rung(program, rung_id, comment=text)


def rung_instruction_list(rung: dict[str, Any]) -> list[tuple[tuple, str, str]]:
    """Instructions on a rung for the note editor: [(path, label, current_note)].

    ``path`` addresses the element in ``program_rung_to_elements(rung)``:
    ``(i,)`` top level, ``(i, bi, j, ...)`` inside OR branches (pairs repeat for nesting).
    """
    from cabinet_studio.services.ladder_ir import program_rung_to_elements

    out: list[tuple[tuple, str, str]] = []

    def label_for(el: dict) -> str:
        kind = str(el.get("kind") or "").lower()
        if kind == "contact":
            return f"{'XIO' if str(el.get('form')).upper() == 'NC' else 'XIC'} {el.get('var', '')}"
        if kind == "coil":
            form = str(el.get("form") or "normal").lower()
            mn = {"set": "OTL", "s": "OTL", "reset": "OTU", "r": "OTU"}.get(form, "OTE")
            return f"{mn} {el.get('var', '')}"
        if kind in {"timer", "counter"}:
            return f"{str(el.get('block') or '').upper()} {el.get('var', '')}"
        if kind == "compare":
            return f"{el.get('op', 'EQU')} {el.get('source_a', '')},{el.get('source_b', '')}"
        if kind == "math":
            return f"{el.get('op', 'ADD')} → {el.get('dest', '')}"
        if kind == "oneshot":
            blk = str(el.get("block") or "ONS").upper()
            return f"{blk} {el.get('var', '')}" + (f" → {el.get('output')}" if el.get("output") else "")
        return kind

    def walk(els: list, prefix: tuple) -> None:
        for i, el in enumerate(els or []):
            if not isinstance(el, dict):
                continue
            path = prefix + (i,)
            if str(el.get("kind") or "").lower() == "or":
                for bi, branch in enumerate(el.get("branches") or []):
                    walk(list(branch or []), path + (bi,))
                continue
            out.append((path, label_for(el), str(el.get("desc") or "")))

    walk(program_rung_to_elements(rung), ())
    return out


def set_instruction_notes(
    program: dict[str, Any],
    rung_id: str,
    notes: dict[tuple, str],
) -> dict[str, Any]:
    """Set instruction notes (``desc``) by element path; empty text clears a note.

    Classic rungs are promoted to an ``elements`` rung so notes survive save /
    PLCopen round-trips (the classic fields stay in sync).
    """
    from copy import deepcopy

    from cabinet_studio.services.ladder_ir import (
        clean_elements,
        clean_note,
        elements_to_program_rung,
        program_rung_to_elements,
    )

    data = program_from_dict(program)
    for idx, rung in enumerate(data["rungs"]):
        if rung["id"] != rung_id:
            continue
        els = deepcopy(program_rung_to_elements(rung))

        def locate(path: tuple) -> dict | None:
            node_list = els
            el = None
            i = 0
            while i < len(path):
                if path[i] >= len(node_list):
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

        for path, text in (notes or {}).items():
            el = locate(tuple(path))
            if el is None or str(el.get("kind") or "").lower() == "or":
                continue
            note = clean_note(text)
            if note:
                el["desc"] = note
            else:
                el.pop("desc", None)
        new_rung = elements_to_program_rung(clean_elements(els), rung_id=rung["id"], comment=rung.get("comment", ""))
        if "elements" not in new_rung and rung.get("elements"):
            new_rung["elements"] = clean_elements(els)
        data["rungs"][idx] = _normalize_rung(new_rung, idx + 1)
        data["plc_text"] = format_plc_text(data["rungs"])
        data["text_edited"] = True
        return data
    raise KeyError(f"No rung with id {rung_id}")


def delete_rung(program: dict[str, Any], rung_id: str) -> dict[str, Any]:
    data = program_from_dict(program)
    data["rungs"] = [rung for rung in data["rungs"] if rung["id"] != rung_id]
    data["plc_text"] = format_plc_text(data["rungs"])
    data["text_edited"] = True
    return data


def _make_run_rung(
    *,
    start: str | None,
    stop: str | None,
    estop: str | None,
    coil: str,
    comment: str,
    interlock_nc: str | None = None,
    include_start: bool = True,
    include_seal: bool = True,
    include_stop: bool = True,
    include_estop: bool = True,
) -> dict[str, Any]:
    """One real ladder run rung: (Start NO || Seal NO) - Stop NC - E-Stop NC - (interlock NC) - (Coil)."""
    parallel: list[list[dict[str, Any]]] = []
    if include_start and start:
        parallel.append([{"tag": start, "normally_closed": False}])
    if include_seal and coil and parallel:
        parallel.append([{"tag": coil, "normally_closed": False}])
    series: list[dict[str, Any]] = []
    if include_stop and stop:
        series.append({"tag": stop, "normally_closed": True})
    if include_estop and estop:
        series.append({"tag": estop, "normally_closed": True})
    if interlock_nc:
        series.append({"tag": interlock_nc, "normally_closed": True})
    rung = {
        "id": new_rung_id(),
        "parallel": parallel,
        "series": series,
        "coil_tag": coil,
        "coil_negated": False,
        "comment": comment,
    }
    legacy = _legacy_fields_from_rung(rung)
    rung["contact_tag"] = legacy["contact_tag"]
    rung["normally_closed"] = legacy["normally_closed"]
    return rung



def simulation_rung_tags(rung: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Tags lit for one educational sim step: (active contacts+coil, optional pulse coils).

    Pulse set highlights Place_Relay / Welder-style outputs on weld-place-cell.
    Educational only — not live PLC evaluation.
    """
    active: set[str] = set()
    for contact in flatten_contacts(rung):
        tag = (contact.get("tag") or "").strip()
        if tag:
            active.add(tag)
    coil = (rung.get("coil_tag") or "").strip()
    if coil:
        active.add(coil)
    pulse: set[str] = set()
    for name in active:
        upper = name.upper().replace("-", "_")
        if (
            upper in {"PLACE_RELAY", "WELDER_RELAY", "WELDER", "PLACE"}
            or "WELDER" in upper
            or upper.startswith("PLACE_")
        ):
            pulse.add(name)
    return active, pulse


def _tag_named_in_answer(answer: str, tags: list[str]) -> str | None:
    """Return the longest cabinet tag explicitly named in an answer string."""
    text = answer or ""
    hits = [tag for tag in tags if tag and tag in text]
    if not hits:
        return None
    hits.sort(key=len, reverse=True)
    return hits[0]



_STACK_FUNCTION = {"ready / running": "green", "light curtain broken": "amber", "e-stop": "red"}


def find_light_curtain_tag(devices: list[dict[str, str]]) -> str | None:
    for device in devices:
        if device["type_id"] == "light_curtain":
            return device["tag"]
    for device in devices:
        if "curtain" in _haystack(device):
            return device["tag"]
    return None


def find_stack_light_tags(devices: list[dict[str, str]]) -> dict[str, str]:
    """{'green'|'amber'|'red': tag} for stack light segments (by function, else STK_<color> tag)."""
    found: dict[str, str] = {}
    for device in devices:
        if device["type_id"] != "light":
            continue
        color = _STACK_FUNCTION.get(device.get("function", "").strip().lower())
        tag = device["tag"]
        if color is None and tag.upper().startswith("STK"):
            color = next((c for c in ("green", "amber", "red") if c in tag.lower()), None)
        if color and color not in found:
            found[color] = tag
    return found


def _stack_light_rungs(stack: dict[str, str], estop: str | None, curtain: str | None,
                       run_coil: str | None) -> list[dict[str, Any]]:
    """Red = E-stop pressed; amber = light curtain broken (and no E-stop); green = healthy: ready or running.
    Only one color is on at a time. The lights only REPORT - the safety relay does the stopping."""
    note = " Indication only: E-stop / light curtain must stop the machine through rated safety relays."
    plans = []
    if stack.get("red") and estop:
        plans.append((stack["red"], [(estop, False)], f"RED stack light: E-stop {estop} pressed."))
    if stack.get("amber") and curtain:
        plans.append((stack["amber"], [(curtain, False)] + ([(estop, True)] if estop else []),
                      f"AMBER stack light: light curtain {curtain} beam broken (red wins if the E-stop is also in)."))
    if stack.get("green"):
        series = ([(curtain, True)] if curtain else []) + ([(estop, True)] if estop else [])
        if not series and run_coil:
            series = [(run_coil, False)]
        if series:
            plans.append((stack["green"], series, "GREEN stack light: healthy - ready for Start, and on while running."))
    rungs = []
    for coil_tag, series, comment in plans:
        rung = {
            "id": new_rung_id(),
            "parallel": [],
            "series": [{"tag": t, "normally_closed": nc} for t, nc in series],
            "coil_tag": coil_tag,
            "coil_negated": False,
            "comment": comment + note,
        }
        legacy = _legacy_fields_from_rung(rung)
        rung["contact_tag"] = legacy["contact_tag"]
        rung["normally_closed"] = legacy["normally_closed"]
        rungs.append(rung)
    return rungs


def build_starter_program(project: Project, answers: dict[str, str]) -> dict[str, Any]:
    """Build real ladder rungs and HMI from answers + tags already on the cabinet."""
    devices = cabinet_device_tags(project)
    start = find_start_tag(devices)
    stop = find_stop_tag(devices)
    estop = find_estop_tag(devices)
    coils = find_output_coil_tags(devices)
    coil = find_motor_coil_tag(devices)
    reverse_start = find_reverse_tag(devices)
    reverse_coil = find_reverse_coil_tag(devices, coil)
    sensors = find_sensor_tags(devices)

    rungs: list[dict[str, Any]] = []
    on_start = (answers.get("on_start") or "").strip()
    on_stop = (answers.get("on_stop") or "").strip()
    on_estop = (answers.get("on_estop") or "").strip()
    direction = (answers.get("direction") or "").strip()
    hmi_show = (answers.get("hmi_show") or "").strip()
    second_coil_ans = (answers.get("second_coil") or "").strip()
    sensor_ans = (answers.get("sensor_interlock") or "").strip()

    skip_start = "nothing yet" in on_start.lower()
    skip_stop = "nothing yet" in on_stop.lower()
    skip_estop = "nothing yet" in on_estop.lower()
    want_reverse = "reverse" in direction.lower()

    # Prefer a coil the user named ("Energize Place_Relay"), else primary cabinet output.
    named_coil = _tag_named_in_answer(on_start, coils)
    if named_coil:
        coil = named_coil
    elif not coil and coils:
        coil = coils[0]

    # Sensor NC contacts for the primary run path (pause / clear-OK).
    interlock_series: list[str] = []
    if sensor_ans and "nothing yet" not in sensor_ans.lower() and "do not add" not in sensor_ans.lower():
        if "only to fire" not in sensor_ans.lower():
            named_sensor = _tag_named_in_answer(sensor_ans, sensors)
            if named_sensor:
                interlock_series.append(named_sensor)
            elif sensors and ("require" in sensor_ans.lower() or "pause" in sensor_ans.lower()):
                interlock_series.append(sensors[0])

    if coil and not skip_start:
        if start or (not skip_stop and stop) or (not skip_estop and estop):
            note_parts = []
            if start and not skip_start:
                note_parts.append(on_start or "Start energizes the output")
            if stop and not skip_stop:
                note_parts.append(on_stop or "Stop opens the rung")
            if estop and not skip_estop:
                note_parts.append(on_estop or "E-stop must drop the output")
            if want_reverse and reverse_coil:
                note_parts.append("Forward rung - interlocked against reverse")
            for tag in interlock_series:
                note_parts.append(f"Sensor interlock {tag}")
            comment = "; ".join(note_parts) if note_parts else "Run output"
            if start and not skip_start:
                comment = (comment + " (seal-in holds the output after Start is released).").strip()
            # First sensor NC goes through interlock_nc; extras appended after build.
            first_sensor = interlock_series[0] if interlock_series else None
            rev_ilock = reverse_coil if (want_reverse and reverse_coil) else None
            # Prefer reverse interlock as dedicated arg; sensors via series extension below.
            rung = _make_run_rung(
                start=start if not skip_start else None,
                stop=stop if not skip_stop else None,
                estop=estop if not skip_estop else None,
                coil=coil,
                comment=comment if not want_reverse else f"Forward: {comment}",
                interlock_nc=rev_ilock or first_sensor,
                include_start=not skip_start,
                include_seal=bool(start) and not skip_start,
                include_stop=not skip_stop,
                include_estop=not skip_estop,
            )
            if rev_ilock and first_sensor:
                rung["series"].append({"tag": first_sensor, "normally_closed": True})
            for extra in interlock_series[1:]:
                rung["series"].append({"tag": extra, "normally_closed": True})
            legacy = _legacy_fields_from_rung(rung)
            rung["contact_tag"] = legacy["contact_tag"]
            rung["normally_closed"] = legacy["normally_closed"]
            rungs.append(rung)
    elif coil and (not skip_stop or not skip_estop):
        rungs.append(
            _make_run_rung(
                start=None,
                stop=stop if not skip_stop else None,
                estop=estop if not skip_estop else None,
                coil=coil,
                comment="; ".join(
                    p for p in [on_stop if not skip_stop else "", on_estop if not skip_estop else ""] if p
                )
                or "Stop / e-stop permissive",
                include_start=False,
                include_seal=False,
                include_stop=not skip_stop,
                include_estop=not skip_estop,
            )
        )

    if want_reverse and coil:
        rev_coil = reverse_coil
        rev_pb = reverse_start
        if rev_coil or rev_pb:
            use_coil = rev_coil or coil
            if rev_coil:
                use_coil = rev_coil
            rungs.append(
                _make_run_rung(
                    start=rev_pb,
                    stop=stop if not skip_stop else None,
                    estop=estop if not skip_estop else None,
                    coil=use_coil,
                    comment="Reverse: seal-in with interlocking so Forward and Reverse cannot both be on.",
                    interlock_nc=coil if (rev_coil and coil and rev_coil != coil) else None,
                    include_start=bool(rev_pb),
                    include_seal=bool(rev_pb),
                    include_stop=not skip_stop,
                    include_estop=not skip_estop,
                )
            )

    # Second output (e.g. Welder_Relay when Arm_Deployed is made) — cabinet tags only.
    if second_coil_ans and "nothing yet" not in second_coil_ans.lower() and coils:
        second = _tag_named_in_answer(second_coil_ans, [c for c in coils if c != coil]) or (
            coils[1] if len(coils) >= 2 and coils[1] != coil else None
        )
        if second and second != coil:
            trigger = _tag_named_in_answer(second_coil_ans, sensors)
            same_start = "same start" in second_coil_ans.lower()
            if same_start:
                rungs.append(
                    _make_run_rung(
                        start=start if not skip_start else None,
                        stop=stop if not skip_stop else None,
                        estop=estop if not skip_estop else None,
                        coil=second,
                        comment=second_coil_ans or f"Secondary output {second}",
                        include_start=bool(start) and not skip_start,
                        include_seal=bool(start) and not skip_start,
                        include_stop=not skip_stop,
                        include_estop=not skip_estop,
                    )
                )
            else:
                # Sensor (or bare permissive) fires second coil; keep e-stop in series.
                parallel: list[list[dict[str, Any]]] = []
                series: list[dict[str, Any]] = []
                if trigger:
                    parallel.append([{"tag": trigger, "normally_closed": False}])
                    # Seal on the coil so it can hold if desired; educational cell often
                    # wants sensor-true → coil. Add seal when a start-like path exists.
                    parallel.append([{"tag": second, "normally_closed": False}])
                elif start and not skip_start:
                    parallel.append([{"tag": start, "normally_closed": False}])
                    parallel.append([{"tag": second, "normally_closed": False}])
                if stop and not skip_stop:
                    series.append({"tag": stop, "normally_closed": True})
                if estop and not skip_estop:
                    series.append({"tag": estop, "normally_closed": True})
                rung = {
                    "id": new_rung_id(),
                    "parallel": parallel,
                    "series": series,
                    "coil_tag": second,
                    "coil_negated": False,
                    "comment": second_coil_ans or f"Secondary output {second}",
                }
                legacy = _legacy_fields_from_rung(rung)
                rung["contact_tag"] = legacy["contact_tag"]
                rung["normally_closed"] = legacy["normally_closed"]
                if parallel or series:
                    rungs.append(rung)

    curtain = find_light_curtain_tag(devices)
    if curtain:
        for rung in rungs:
            if rung.get("coil_tag") and not any(s.get("tag") == curtain for s in rung.get("series", [])):
                rung["series"].append({"tag": curtain, "normally_closed": True})
                rung["comment"] = (rung.get("comment", "") + f" Light curtain {curtain} broken drops the output.").strip()
    rungs.extend(_stack_light_rungs(find_stack_light_tags(devices), estop, curtain, coil))

    hmi_items: list[dict[str, str]] = []
    if hmi_show == "Running, Stopped, Fault, Start, and Stop":
        wanted = [
            ("indicator", "Running"),
            ("indicator", "Stopped"),
            ("indicator", "Fault"),
            ("button", "Start"),
            ("button", "Stop"),
        ]
    elif hmi_show == "Running and Stopped only":
        wanted = [("indicator", "Running"), ("indicator", "Stopped")]
    elif hmi_show == "Running, Stopped, and Fault" or hmi_show:
        wanted = [("indicator", "Running"), ("indicator", "Stopped"), ("indicator", "Fault")]
    else:
        wanted = []
    for kind, label in wanted:
        hmi_items.append({"id": new_rung_id(), "kind": kind, "label": label})

    plc_text = format_plc_text(rungs, devices)
    if want_reverse and not reverse_coil and not reverse_start:
        plc_text = (
            plc_text.rstrip()
            + "\n\nNote: You chose forward and reverse, but this cabinet has no reverse start or reverse "
            "contactor tag yet.\nAdd a reverse device on the panel before naming a reverse rung.\n"
        )

    if devices:
        legend = ["", "Devices on this cabinet (from the panel - do not invent tags):"]
        for device in devices:
            addr = device.get("io_address") or ""
            wires = device.get("wire_numbers") or ""
            role = device_role_label(device)
            bits = [device["tag"], f"({role})", device["type_id"]]
            if addr and addr.lower() != "n/a":
                bits.append(f"I/O {addr}")
            if wires:
                bits.append(f"wires {wires}")
            legend.append("  - " + " | ".join(bits))
        legend.append("")
        plc_text = plc_text.rstrip() + "\n" + "\n".join(legend)

    # Persist every answered key (dynamic questions) plus the classic set.
    answer_keys = [key for key, _q, _opts in PROGRAM_QUESTIONS]
    for key in answers:
        if key not in answer_keys:
            answer_keys.append(key)
    return {
        "answers": {key: str(answers.get(key, "") or "") for key in answer_keys},
        "rungs": rungs,
        "hmi_items": hmi_items,
        "plc_text": plc_text,
        "hmi_text": format_hmi_text(hmi_items),
        "text_edited": False,
    }




def format_ladder_txt(program: dict[str, Any] | None, *, cabinet_name: str = "") -> str:
    """Plain-text ladder document (separate from schematic SVGs).

    v0.3.11: when a rung carries full ``elements``, print instruction mnemonics
    (compare / math / oneshot / JSR / nested OR) instead of only classic
    PARALLEL/SERIES/COIL fields (which showed ``COIL: (?)`` for math rungs).
    """
    from cabinet_studio.services.ladder_ir import program_rung_to_elements
    from cabinet_studio.services.ladder_tools import element_label

    data = program_from_dict(program or {})
    lines: list[str] = []
    title = (cabinet_name or "Cabinet").strip() or "Cabinet"
    from cabinet_studio.services.drawings import DISCLAIMER as UL_DESIGN_AID
    from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE

    lines.append(f"LADDER LOGIC — {title}")
    lines.append(LEARNING_NOTE)
    lines.append(UL_DESIGN_AID)
    lines.append("Separate artifact from schematic drawings. Design aid only.")
    lines.append(SAFETY_DESIGN_AID_NOTE)
    lines.append("")
    rungs = data.get("rungs") or []
    if not rungs:
        lines.append("(No rungs yet.)")
        lines.append("")
    for index, rung in enumerate(rungs, start=1):
        comment = (rung.get("comment") or "").strip()
        lines.append(f"R{index}" + (f" — {comment}" if comment else ""))
        els = program_rung_to_elements(rung)
        if rung.get("elements") or any(
            str(e.get("kind") or "").lower() in {"compare", "math", "oneshot", "jsr", "sbr", "ret", "or", "timer", "counter"}
            for e in els
        ):
            bits = []
            for e in els:
                kind = str(e.get("kind") or "").lower()
                if kind == "or":
                    branch_txt = []
                    for br in e.get("branches") or []:
                        branch_txt.append(" · ".join(element_label(x) for x in (br or []) if isinstance(x, dict)))
                    bits.append("(" + " | ".join(branch_txt) + ")")
                else:
                    bits.append(element_label(e))
            lines.append("  LOGIC:    " + " — ".join(bits) if bits else "  LOGIC:    (empty)")
        else:
            parallel = rung.get("parallel") or []
            if parallel:
                branch_bits = []
                for branch in parallel:
                    contacts = []
                    for c in branch:
                        if isinstance(c, dict) and c.get("kind") == "or":
                            contacts.append("(nested-OR)")
                            continue
                        tag = (c.get("tag") or "?").strip()
                        contacts.append(f"[/{tag}]" if c.get("normally_closed") else f"[{tag}]")
                    branch_bits.append(" — ".join(contacts) if contacts else "(empty)")
                lines.append("  PARALLEL: " + "  ||  ".join(branch_bits))
            series = rung.get("series") or []
            if series:
                contacts = []
                for c in series:
                    tag = (c.get("tag") or "?").strip()
                    contacts.append(f"[/{tag}]" if c.get("normally_closed") else f"[{tag}]")
                lines.append("  SERIES:   " + " — ".join(contacts))
            tmr = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
            if tmr and (tmr.get("tag") or "").strip():
                lines.append(
                    f"  TIMER:    {str(tmr.get('block') or 'TON').upper()}({(tmr.get('tag') or '').strip()}) "
                    f"PT={int(tmr.get('pt_ms') or 0)}ms"
                )
            ctr = rung.get("counter") if isinstance(rung.get("counter"), dict) else None
            if ctr and (ctr.get("tag") or "").strip():
                lines.append(f"  COUNTER:  {counter_text_mark(ctr)}")
            coil = (rung.get("coil_tag") or "").strip()
            if coil or not ((tmr and tmr.get("tag")) or (ctr and ctr.get("tag"))):
                coil = coil or "?"
                lines.append(f"  COIL:     (/{coil})" if rung.get("coil_negated") else f"  COIL:     ({coil})")
        lines.append("")
    # Routines
    routines = data.get("routines") if isinstance(data.get("routines"), dict) else {}
    for rname, rrungs in (routines or {}).items():
        lines.append(f"=== SUBROUTINE {rname} ===")
        for index, rung in enumerate(rrungs or [], start=1):
            if not isinstance(rung, dict):
                continue
            comment = (rung.get("comment") or "").strip()
            lines.append(f"R{index}" + (f" — {comment}" if comment else ""))
            els = program_rung_to_elements(rung)
            bits = [element_label(e) for e in els]
            lines.append("  LOGIC:    " + " — ".join(bits) if bits else "  LOGIC:    (empty)")
            lines.append("")
    plc = (data.get("plc_text") or "").strip()
    if plc:
        lines.append("========== PLC TEXT ==========")
        lines.append(plc)
        lines.append("")
    hmi = (data.get("hmi_text") or "").strip()
    if hmi:
        lines.append("========== HMI TEXT ==========")
        lines.append(hmi)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_ladder_html(program: dict[str, Any] | None, *, cabinet_name: str = "") -> str:
    import html as _html
    title = _html.escape((cabinet_name or "Cabinet").strip() or "Cabinet")
    pre = _html.escape(format_ladder_txt(program, cabinet_name=cabinet_name))
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>Ladder Logic — {title}</title>
<style>
  @page {{ margin: 0.6in; }}
  body {{ font-family: Segoe UI, Arial, sans-serif; color: #111; background: #fff; }}
  h1 {{ font-size: 16pt; margin: 0 0 6px 0; }}
  .meta {{ color: #444; font-size: 10pt; margin-bottom: 12px; }}
  pre {{ font-family: Consolas, Liberation Mono, monospace; font-size: 10pt;
         white-space: pre-wrap; border: 1px solid #ccc; padding: 12px; background: #fafafa; }}
  @media print {{ .noprint {{ display: none; }} }}
</style></head><body>
<h1>Ladder Logic — {title}</h1>
<div class="meta">{_html.escape(LEARNING_NOTE)} Separate from schematic SVGs. Design aid only.</div>
<p class="noprint"><button onclick="window.print()">Print…</button></p>
<pre>{pre}</pre>
</body></html>
"""


def write_ladder_logic(
    project: Project,
    folder: Path | str,
    *,
    program: dict[str, Any] | None = None,
) -> list[Path]:
    """Write ladder-logic.txt and ladder-logic.html under the drawings folder."""
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    prog = program if program is not None else getattr(project, "program", None)
    name = getattr(project, "name", "") or "Cabinet"
    txt_path = target / "ladder-logic.txt"
    html_path = target / "ladder-logic.html"
    txt_path.write_text(format_ladder_txt(prog, cabinet_name=name), encoding="utf-8")
    html_path.write_text(format_ladder_html(prog, cabinet_name=name), encoding="utf-8")
    return [txt_path, html_path]


def program_ladder_ir(program, *, project_name: str = "", devices=None):
    """v3 helper: project.program → educational ladder IR (does not mutate)."""
    from cabinet_studio.services.ladder_ir import program_to_ladder_ir

    return program_to_ladder_ir(program, project_name=project_name, devices=devices)
