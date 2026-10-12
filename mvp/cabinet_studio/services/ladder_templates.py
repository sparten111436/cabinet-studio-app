"""Educational AOI / function-block *templates* for Cabinet Studio (v0.3.14).

These are lightweight rung expansions inspired by Studio AOI / CODESYS FB
ideas — **not** a proprietary AOI runtime. Inserting a template copies a
small, named set of educational rungs into the program so learners can see
common patterns (motor seal-in, timed start, latch pair, counter batch,
forward/reverse, e-stop interlock, etc.).

EDUCATIONAL DESIGN AID ONLY. Real E-stop and safety functions must be
HARDWIRED or use rated safety relays / safety PLCs per NFPA 79 / ISO 13849.
Standard PLC ladder in these templates is NOT a safety system.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from cabinet_studio.services.ladder_ir import (
    _coil_el,
    _compare_el,
    _contact_el,
    _counter_el,
    _math_el,
    _oneshot_el,
    _timer_el,
    clean_elements,
)



# Exact educational design-aid note (G-AID / Deflector / Raddus v0.3.12).
# Must appear on first rung comment, print footer, PLCopen documentation, and txt.
SAFETY_DESIGN_AID_NOTE = (
    "Educational design aid only — real E-stop/safety functions must be "
    "hardwired or use rated safety relays per NFPA 79 / ISO 13849"
)

SAFETY_TEMPLATE_NAMES = frozenset({
    "MotorStarter",
    "ForwardReverse",
    "EstopInterlock",
    "ValveCycle",
    "TwoHandStart",
    "OffDelayStop",
    "JogOrRun",
})


def safety_aid_rung_comment(body: str) -> str:
    """Prefix the first rung of a safety template with the G-AID note."""
    body = (body or "").strip()
    if SAFETY_DESIGN_AID_NOTE.lower() in body.lower():
        return body
    return f"{SAFETY_DESIGN_AID_NOTE} | {body}" if body else SAFETY_DESIGN_AID_NOTE

# Parameterized templates. Keys are educational names (not vendor product names).
AOI_TEMPLATES: dict[str, dict[str, Any]] = {
    "MotorStarter": {
        "title": "Motor starter seal-in (educational)",
        "description": "Start PB seals through M1; Stop NC drops out. Studio/CCW seal-in idea. EDUCATIONAL DESIGN AID ONLY — real E-stop/safety must be hardwired or rated safety relays/PLCs (NFPA 79 / ISO 13849); not certified safety logic.",
        "params": {
            "start": "PB_Start",
            "stop": "PB_Stop",
            "motor": "M1",
        },
        "rungs": lambda p: [
            {
                "comment": safety_aid_rung_comment(f"AOI MotorStarter: seal-in {p['motor']}"),
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["start"])],
                            [_contact_el(p["motor"])],
                        ],
                    },
                    _contact_el(p["stop"], normally_closed=True),
                    _coil_el(p["motor"]),
                ],
            }
        ],
    },
    "TimedStart": {
        "title": "Timed start (TON then coil)",
        "description": "Enable runs TON; done bit drives the output coil.",
        "params": {
            "enable": "PB_Start",
            "timer": "T_Start",
            "pt_ms": "2000",
            "output": "M1",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI TimedStart: {p['timer']} PT={p['pt_ms']}ms",
                "elements": [
                    _contact_el(p["enable"]),
                    _timer_el(p["timer"], "TON", int(float(p.get("pt_ms") or 0))),
                ],
            },
            {
                "comment": f"AOI TimedStart: {p['timer']}.DN → {p['output']}",
                "elements": [
                    _contact_el(f"{p['timer']}.DN"),
                    _coil_el(p["output"]),
                ],
            },
        ],
    },
    "LatchPair": {
        "title": "OTL / OTU latch pair",
        "description": "Set and reset coils for a memory bit (educational SR).",
        "params": {
            "set": "PB_Set",
            "reset": "PB_Reset",
            "memory": "MEM1",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI LatchPair: OTL {p['memory']}",
                "elements": [_contact_el(p["set"]), _coil_el(p["memory"], form="set")],
            },
            {
                "comment": f"AOI LatchPair: OTU {p['memory']}",
                "elements": [_contact_el(p["reset"]), _coil_el(p["memory"], form="reset")],
            },
        ],
    },
    "CounterBatch": {
        "title": "CTU + GEQ batch complete",
        "description": "Count pulses; DN bit drives Done coil when ACC reaches PRE.",
        "params": {
            "pulse": "PB_Count",
            "counter": "C_Batch",
            "preset": "5",
            "done": "Batch_Done",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI CounterBatch: CTU {p['counter']}",
                "elements": [
                    _contact_el(p["pulse"]),
                    _counter_el(p["counter"], "CTU", int(float(p.get("preset") or 0))),
                ],
            },
            {
                "comment": f"AOI CounterBatch: {p['counter']}.DN → {p['done']}",
                "elements": [
                    _contact_el(f"{p['counter']}.DN"),
                    _coil_el(p["done"]),
                ],
            },
        ],
    },
    "LimitBand": {
        "title": "LIM band + alarm coil",
        "description": "LIM Test between Low/High; TRUE drives OK coil (educational process band).",
        "params": {
            "enable": "Auto",
            "test": "Level",
            "low": "10",
            "high": "90",
            "ok": "InBand",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI LimitBand: LIM {p['low']}≤{p['test']}≤{p['high']}",
                "elements": [
                    _contact_el(p["enable"]),
                    _compare_el("LIM", p["test"], p["low"], p["high"]),
                    _coil_el(p["ok"]),
                ],
            }
        ],
    },
    "MaskedFlag": {
        "title": "MEQ masked status bit",
        "description": "MEQ Source&Mask == Compare&Mask; educational bitfield check.",
        "params": {
            "enable": "Scan",
            "source": "StatusWord",
            "mask": "1",
            "compare": "1",
            "flag": "Bit0_On",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI MaskedFlag: MEQ {p['source']}&{p['mask']}",
                "elements": [
                    _contact_el(p["enable"]),
                    _compare_el("MEQ", p["source"], p["mask"], p["compare"]),
                    _coil_el(p["flag"]),
                ],
            }
        ],
    },
    # --- v0.3.10 cabinet-style educational expansions -------------------------
    "ForwardReverse": {
        "title": "FWD / REV mutually exclusive",
        "description": "Two seal-in motors; each path NC-interlocks the other (cabinet hoist / conveyor). EDUCATIONAL DESIGN AID ONLY — real E-stop/safety must be hardwired or rated safety relays/PLCs (NFPA 79 / ISO 13849); not certified safety logic.",
        "params": {
            "fwd_pb": "PB_Fwd",
            "rev_pb": "PB_Rev",
            "stop": "PB_Stop",
            "fwd": "M_Fwd",
            "rev": "M_Rev",
        },
        "rungs": lambda p: [
            {
                "comment": safety_aid_rung_comment(f"AOI ForwardReverse: FWD {p['fwd']} (interlock {p['rev']})"),
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["fwd_pb"])],
                            [_contact_el(p["fwd"])],
                        ],
                    },
                    _contact_el(p["stop"], normally_closed=True),
                    _contact_el(p["rev"], normally_closed=True),
                    _coil_el(p["fwd"]),
                ],
            },
            {
                "comment": f"AOI ForwardReverse: REV {p['rev']} (interlock {p['fwd']})",
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["rev_pb"])],
                            [_contact_el(p["rev"])],
                        ],
                    },
                    _contact_el(p["stop"], normally_closed=True),
                    _contact_el(p["fwd"], normally_closed=True),
                    _coil_el(p["rev"]),
                ],
            },
        ],
    },
    "OffDelayStop": {
        "title": "Run with TOF off-delay stop",
        "description": (
            "Enable drives TOF IN (not sealed by output). When enable drops, TOF Q stays "
            "true for PT ms then clears — output follows Q (cooling / purge)."
            + " EDUCATIONAL DESIGN AID ONLY — real E-stop/safety must be hardwired or "
            "rated safety relays/PLCs (NFPA 79 / ISO 13849); not certified safety logic."
        ),
        "params": {
            "enable": "Auto_Run",
            "timer": "T_OffDelay",
            "pt_ms": "3000",
            "output": "Fan1",
        },
        "rungs": lambda p: [
            {
                "comment": safety_aid_rung_comment(f"AOI OffDelayStop: {p['enable']} → TOF {p['timer']} PT={p['pt_ms']}ms (no output seal)"),
                "elements": [
                    _contact_el(p["enable"]),
                    _timer_el(p["timer"], "TOF", int(float(p.get("pt_ms") or 0))),
                ],
            },
            {
                "comment": f"AOI OffDelayStop: {p['timer']}.DN → {p['output']}",
                "elements": [
                    _contact_el(f"{p['timer']}.DN"),
                    _coil_el(p["output"]),
                ],
            },
        ],
    },
    "PulseExtend": {
        "title": "OSR edge + TON pulse stretch",
        "description": "Rising edge of Trigger starts TON; DN (or TT) can drive a stretched pulse coil.",
        "params": {
            "trigger": "PB_Pulse",
            "storage": "OS_Pulse",
            "edge": "Pulse_Edge",
            "timer": "T_Stretch",
            "pt_ms": "500",
            "output": "Pulse_Out",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI PulseExtend: OSR {p['trigger']} → {p['edge']}",
                "elements": [
                    _contact_el(p["trigger"]),
                    _oneshot_el("OSR", p["storage"], p["edge"]),
                ],
            },
            {
                "comment": f"AOI PulseExtend: TON {p['timer']} from edge",
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["edge"])],
                            [_contact_el(f"{p['timer']}.TT")],
                        ],
                    },
                    _timer_el(p["timer"], "TON", int(float(p.get("pt_ms") or 0))),
                ],
            },
            {
                "comment": f"AOI PulseExtend: {p['timer']}.TT → {p['output']}",
                "elements": [
                    _contact_el(f"{p['timer']}.TT"),
                    _coil_el(p["output"]),
                ],
            },
        ],
    },
    "TwoHandStart": {
        "title": "Two-hand start seal-in (educational)",
        "description": (
            "Both hand PBs required to start within ~0.5 s of each other (skew TON lockout); "
            "Stop NC drops out. NOT a Category-rated two-hand control module — educational only. "
            "Release-before-restart after Stop is not enforced in this educational subset."
            + " EDUCATIONAL DESIGN AID ONLY — real E-stop/safety must be hardwired or "
            "rated safety relays/PLCs (NFPA 79 / ISO 13849); not certified safety logic."
        ),
        "params": {
            "left": "PB_Left",
            "right": "PB_Right",
            "stop": "PB_Stop",
            "cycle": "Cycle_Run",
            "skew_ms": "500",
            # Optional overrides; default internals are prefixed by cycle tag (NEW-B).
            "skew_left": "",
            "skew_right": "",
            "lock_left": "",
            "lock_right": "",
        },
        "rungs": lambda p: (
            lambda sl, sr, ll, lr: [
            {
                "comment": safety_aid_rung_comment(f"AOI TwoHandStart: {p['left']} alone → TON skew"),
                "elements": [
                    _contact_el(p["left"]),
                    _contact_el(p["right"], normally_closed=True),
                    _timer_el(sl, "TON", int(float(p.get("skew_ms") or 500))),
                ],
            },
            {
                "comment": f"AOI TwoHandStart: skew DN → OTL {ll} (clears when Left released)",
                "elements": [
                    _contact_el(f"{sl}.DN"),
                    _coil_el(ll, form="set"),
                ],
            },
            {
                "comment": f"AOI TwoHandStart: /Left → OTU {ll}",
                "elements": [
                    _contact_el(p["left"], normally_closed=True),
                    _coil_el(ll, form="reset"),
                ],
            },
            {
                "comment": f"AOI TwoHandStart: {p['right']} alone → TON skew",
                "elements": [
                    _contact_el(p["right"]),
                    _contact_el(p["left"], normally_closed=True),
                    _timer_el(sr, "TON", int(float(p.get("skew_ms") or 500))),
                ],
            },
            {
                "comment": f"AOI TwoHandStart: skew DN → OTL {lr}",
                "elements": [
                    _contact_el(f"{sr}.DN"),
                    _coil_el(lr, form="set"),
                ],
            },
            {
                "comment": f"AOI TwoHandStart: /Right → OTU {lr}",
                "elements": [
                    _contact_el(p["right"], normally_closed=True),
                    _coil_el(lr, form="reset"),
                ],
            },
            {
                "comment": f"AOI TwoHandStart: both · /locks · /Stop → {p['cycle']}",
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [
                                _contact_el(p["left"]),
                                _contact_el(p["right"]),
                                _contact_el(ll, normally_closed=True),
                                _contact_el(lr, normally_closed=True),
                            ],
                            [_contact_el(p["cycle"])],
                        ],
                    },
                    _contact_el(p["stop"], normally_closed=True),
                    _coil_el(p["cycle"]),
                ],
            },
        ])(
            str(p.get("skew_left") or "").strip() or f"{p['cycle']}_T_LeftSkew",
            str(p.get("skew_right") or "").strip() or f"{p['cycle']}_T_RightSkew",
            str(p.get("lock_left") or "").strip() or f"{p['cycle']}_LeftLock",
            str(p.get("lock_right") or "").strip() or f"{p['cycle']}_RightLock",
        ),
    },
    "EstopInterlock": {
        "title": "E-stop + light-curtain seal",
        "description": "Start seals run through ES NC and Light_Curtain NC (cabinet safety idea). EDUCATIONAL DESIGN AID ONLY — real E-stop/safety must be hardwired or rated safety relays/PLCs (NFPA 79 / ISO 13849); not certified safety logic.",
        "params": {
            "start": "PB_Start",
            "estop": "ES1",
            "curtain": "Light_Curtain",
            "run": "Machine_Run",
        },
        "rungs": lambda p: [
            {
                "comment": safety_aid_rung_comment(f"AOI EstopInterlock: {p['run']} via ES/curtain"),
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["start"])],
                            [_contact_el(p["run"])],
                        ],
                    },
                    _contact_el(p["estop"], normally_closed=True),
                    _contact_el(p["curtain"], normally_closed=True),
                    _coil_el(p["run"]),
                ],
            }
        ],
    },
    "ValveCycle": {
        "title": "Place valve + welder feedback",
        "description": "Place_Relay seals with ES; Welder_Relay needs Arm_Deployed (Weld Place Cell pattern). EDUCATIONAL DESIGN AID ONLY — real E-stop/safety must be hardwired or rated safety relays/PLCs (NFPA 79 / ISO 13849); not certified safety logic.",
        "params": {
            "start": "PB_Start",
            "stop": "PB_Stop",
            "estop": "ES1",
            "place": "Place_Relay",
            "arm": "Arm_Deployed",
            "welder": "Welder_Relay",
        },
        "rungs": lambda p: [
            {
                "comment": safety_aid_rung_comment(f"AOI ValveCycle: {p['place']}"),
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["start"])],
                            [_contact_el(p["place"])],
                        ],
                    },
                    _contact_el(p["stop"], normally_closed=True),
                    _contact_el(p["estop"], normally_closed=True),
                    _coil_el(p["place"]),
                ],
            },
            {
                "comment": f"AOI ValveCycle: {p['welder']} needs {p['arm']}",
                "elements": [
                    _contact_el(p["place"]),
                    _contact_el(p["arm"]),
                    _coil_el(p["welder"]),
                ],
            },
        ],
    },
    "BatchReset": {
        "title": "CTU batch + RES on Done",
        "description": "Count to PRE; Done coil from DN; separate Reset PB RES the counter.",
        "params": {
            "pulse": "PB_Count",
            "reset": "PB_Reset",
            "counter": "C_Part",
            "preset": "10",
            "done": "Batch_Done",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI BatchReset: CTU {p['counter']}",
                "elements": [
                    _contact_el(p["pulse"]),
                    _counter_el(p["counter"], "CTU", int(float(p.get("preset") or 0))),
                ],
            },
            {
                "comment": f"AOI BatchReset: {p['counter']}.DN → {p['done']}",
                "elements": [
                    _contact_el(f"{p['counter']}.DN"),
                    _coil_el(p["done"]),
                ],
            },
            {
                "comment": f"AOI BatchReset: RES {p['counter']}",
                "elements": [
                    _contact_el(p["reset"]),
                    _counter_el(p["counter"], "RES", 0),
                ],
            },
        ],
    },
    "JogOrRun": {
        "title": "Jog OR continuous run",
        "description": (
            "Momentary Jog (no latch) OR Start/Stop RunMode OTE seal to the same motor; "
            "Stop NC is in series on both rungs so Stop always dominates. "
            "RunMode uses non-retentive OTE seal-in (not OTL) so it clears on power loss — "
            "no unexpected restart after power restore (NFPA 79 educational practice)."
            + " EDUCATIONAL DESIGN AID ONLY — real E-stop/safety must be hardwired or "
            "rated safety relays/PLCs (NFPA 79 / ISO 13849); not certified safety logic."
        ),
        "params": {
            "jog": "PB_Jog",
            "start": "PB_Start",
            "stop": "PB_Stop",
            "motor": "M1",
            "run_mode": "RunMode",
        },
        "rungs": lambda p: [
            {
                "comment": safety_aid_rung_comment(
                    f"AOI JogOrRun: (Start | {p['run_mode']}) · /Stop → OTE {p['run_mode']} (non-retentive)"
                ),
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["start"])],
                            [_contact_el(p["run_mode"])],
                        ],
                    },
                    _contact_el(p["stop"], normally_closed=True),
                    _coil_el(p["run_mode"]),  # OTE — clears on power loss
                ],
            },
            {
                "comment": f"AOI JogOrRun: (Jog | {p['run_mode']}) · /Stop → {p['motor']}",
                "elements": [
                    {
                        "kind": "or",
                        "branches": [
                            [_contact_el(p["jog"])],
                            [_contact_el(p["run_mode"])],
                        ],
                    },
                    _contact_el(p["stop"], normally_closed=True),
                    _coil_el(p["motor"]),
                ],
            },
        ],
    },
    "ScaleSetpoint": {
        "title": "MOV + MUL scale setpoint",
        "description": "Copy Raw to Work then MUL by Scale into Scaled (educational analog prep).",
        "params": {
            "enable": "Auto",
            "raw": "Raw_In",
            "work": "Work",
            "scale": "10",
            "scaled": "Scaled_Out",
        },
        "rungs": lambda p: [
            {
                "comment": f"AOI ScaleSetpoint: MOV {p['raw']} → {p['work']}",
                "elements": [
                    _contact_el(p["enable"]),
                    _math_el("MOV", p["work"], p["raw"], "0"),
                ],
            },
            {
                "comment": f"AOI ScaleSetpoint: MUL {p['work']}*{p['scale']} → {p['scaled']}",
                "elements": [
                    _contact_el(p["enable"]),
                    _math_el("MUL", p["scaled"], p["work"], p["scale"]),
                ],
            },
        ],
    },
}


def list_aoi_templates() -> list[dict[str, str]]:
    """Return [{name, title, description}, ...] for UI menus."""
    out = []
    for name, meta in AOI_TEMPLATES.items():
        out.append(
            {
                "name": name,
                "title": str(meta.get("title") or name),
                "description": str(meta.get("description") or ""),
            }
        )
    return out


def aoi_template_defaults(name: str) -> dict[str, str]:
    meta = AOI_TEMPLATES.get(name) or AOI_TEMPLATES["MotorStarter"]
    return {k: str(v) for k, v in (meta.get("params") or {}).items()}


def expand_aoi_template(name: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Expand a template into a list of {comment, elements} rung specs (cleaned)."""
    key = str(name or "MotorStarter").strip()
    if key not in AOI_TEMPLATES:
        # Case-insensitive match
        for k in AOI_TEMPLATES:
            if k.lower() == key.lower():
                key = k
                break
        else:
            raise ValueError(f"Unknown AOI template {name!r}. Known: {', '.join(AOI_TEMPLATES)}")
    meta = AOI_TEMPLATES[key]
    merged = dict(meta.get("params") or {})
    for k, v in (params or {}).items():
        if v is not None and str(v).strip() != "":
            merged[k] = str(v).strip()
    builder = meta["rungs"]
    specs = builder(merged)
    out = []
    for spec in specs:
        els = clean_elements(spec.get("elements") or [])
        if not els:
            continue
        out.append({"comment": str(spec.get("comment") or ""), "elements": els})
    return out


def apply_aoi_template(
    program: dict[str, Any],
    name: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Insert expanded template rungs at the end of the program (deep-copied)."""
    from cabinet_studio.services.programming import add_rung_from_elements, empty_program

    data = deepcopy(program) if program else empty_program()
    for spec in expand_aoi_template(name, params):
        data = add_rung_from_elements(data, spec["elements"], comment=spec.get("comment") or "")
    # Record which educational templates were used (for print / PLCopen meta).
    used = list(data.get("aoi_templates_used") or [])
    used.append({"name": name, "params": dict(params or aoi_template_defaults(name))})
    data["aoi_templates_used"] = used
    return data
