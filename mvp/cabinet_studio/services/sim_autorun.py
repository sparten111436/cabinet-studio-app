"""Normal run (v0.3.25): an automatic operator sequence for the ladder simulator.

From the program's own contacts it builds the steps an operator and machine would
normally take: make every stop / guard / fault input healthy, press reset, press
start, then make each remaining sensor in the order the ladder first reads it.
The healthy value of a permissive is the one that lets its first contact conduct
(XIC -> ON, XIO -> OFF), so NC-wired stops work too. Educational only - the
software is never the safety function.
"""

from __future__ import annotations

import re
from typing import Any

from cabinet_studio.services.sim_plant import is_safety_tag

_HEALTHY = re.compile(
    r"STOP|E_?STOP|EMERG|GUARD|CURTAIN|LIGHT_?C|(^|_)LC\d*($|_)|(^|_)ES\d*($|_)|DOOR|GATE|INTERLOCK|"
    r"(^|_)OL\d*($|_)|OVERLOAD|"
    r"FAULT|TRIP|ALARM|SAFE|(^|_)OK($|_)|READY|PERMIT|AIR|PRESS(URE)?_?(OK|SW)|HEALTHY",
    re.I,
)
_RESET = re.compile(r"RESET|(^|_)RST($|_)|(^|_)ACK|ACKNOW", re.I)
_PRESS = re.compile(r"START|CYCLE|(^|_)RUN($|_)|(^|_)GO($|_)|(^|_)PB($|_)|BTN|BUTTON|PUSH|(^|_)SS($|_)", re.I)


def _walk(items: list, uses: dict[str, str], order: list[str]) -> None:
    for el in items or []:
        if not isinstance(el, dict):
            continue
        kind = str(el.get("kind") or "").lower()
        if kind == "or":
            for branch in el.get("branches") or []:
                _walk(branch if isinstance(branch, list) else [], uses, order)
        elif kind == "contact":
            tag = str(el.get("var") or "").strip()
            if tag and tag not in uses:
                uses[tag] = "NC" if str(el.get("form") or "NO").upper() == "NC" else "NO"
                order.append(tag)


def normal_run_plan(rung_elements: list[list[dict[str, Any]]], input_tags: list[str] | set[str],
                    skip: set[str] | None = None) -> list[dict[str, Any]]:
    """Steps: ``{"label", "set": {tag: True/False/None}}``; None releases the force.
    Tags in ``skip`` are driven by the pretend machine (sim_plant), not by the plan."""
    inputs = {str(t) for t in input_tags} - set(skip or ())
    uses: dict[str, str] = {}
    order: list[str] = []
    for elements in rung_elements:
        _walk(elements, uses, order)
    tags = [t for t in order if t in inputs and "." not in t]
    safety = [t for t in tags if is_safety_tag(t)]
    tags = [t for t in tags if t not in safety]

    healthy = [t for t in tags if _HEALTHY.search(t) and not _RESET.search(t)]
    resets = [t for t in tags if t not in healthy and _RESET.search(t)]
    presses = [t for t in tags if t not in healthy and t not in resets and _PRESS.search(t)]
    sensors = [t for t in tags if t not in healthy and t not in resets and t not in presses]

    steps: list[dict[str, Any]] = []
    if safety:
        steps.append({"label": "Safety left to you (not touched): " + ", ".join(safety), "set": {}})
    if healthy:
        values = {t: uses[t] == "NO" for t in healthy}
        steps.append({
            "label": "Make safe / ready: " + ", ".join(f"{t} {'ON' if v else 'OFF'}" for t, v in values.items()),
            "set": values,
        })
    for t in resets + presses:
        steps.append({"label": f"Press {t}", "set": {t: True}})
        steps.append({"label": f"Release {t}", "set": {t: None}})
    for t in sensors:
        steps.append({"label": f"{t} turns ON", "set": {t: True}})
    return steps
