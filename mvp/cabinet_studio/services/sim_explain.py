"""Explain run (v0.3.25): plain-English, part-by-part narration of the ladder simulator.

For each scanned rung it says, left to right, what every instruction is waiting for,
what it saw and what happened, then where power stopped and what would let it pass.
Built from the simulator's own power flow and values - offline, no AI key, never
guesses logic. Educational only; the software is never the safety function.
"""

from __future__ import annotations

from typing import Any, Callable

_OUTPUTS = {"coil", "timer", "counter", "math", "jsr", "ret"}


def _kind(el: dict) -> str:
    return str(el.get("kind") or "").lower()


def _branches(el: dict) -> list[list]:
    return [b if isinstance(b, list) else [] for b in (el.get("branches") or [])]


def flow_order(items: list, key_of: Callable[[int], str]) -> list[tuple[str, dict, int]]:
    """(power-flow key, element, depth) in scan order; OR branches top-down, depth+1."""
    out: list[tuple[str, dict, int]] = []

    def walk(seq: list, kof: Callable[[int], str], depth: int) -> None:
        for j, el in enumerate(seq or []):
            if not isinstance(el, dict):
                continue
            key = kof(j)
            out.append((key, el, depth))
            if _kind(el) == "or":
                for bi, branch in enumerate(_branches(el)):
                    walk(branch, lambda jj, bi=bi, key=key: f"{key}|b{bi}|{jj}", depth + 1)

    walk(items, key_of, 0)
    return out


def writers(rungs_elements: list[list[dict]]) -> dict[str, int]:
    """Tag -> first rung number (1-based) whose coil / timer / counter / math writes it."""
    found: dict[str, int] = {}
    for n, elements in enumerate(rungs_elements, start=1):
        for _key, el, _d in flow_order(elements, lambda j: str(j)):
            tag = str(el.get("var") or el.get("dest") or "").strip()
            if tag and _kind(el) in _OUTPUTS and tag not in found:
                found[tag] = n
    return found


def _secs(ms: Any) -> str:
    return f"{float(ms or 0) / 1000.0:.1f} s"


def _desc(el: dict) -> str:
    d = str(el.get("desc") or "").strip()
    return f" ({d})" if d else ""


def _source(tag: str, wmap: dict[str, int]) -> str:
    base = tag.split(".")[0]
    if base in wmap:
        return f" - it comes from rung {wmap[base]}"
    return " - an input (field device or click it in the sim)"


def explain_part(el: dict, flow: dict | None, sim: Any, wmap: dict[str, int]) -> str:
    """One line: the instruction, what it is waiting for, what it saw, what happened."""
    kind = _kind(el)
    flow = flow or {}
    pin, out = bool(flow.get("in")), bool(flow.get("out"))
    tag = str(el.get("var") or "").strip()
    no_power = "no power reaches it yet - waiting on the parts to its left."
    if kind == "contact":
        nc = str(el.get("form") or "NO").upper() == "NC"
        on = bool(sim.read(tag)) if tag else False
        head = f"{'XIO' if nc else 'XIC'} {tag}{_desc(el)}: "
        want = "OFF" if nc else "ON"
        state = "ON" if on else "OFF"
        if not pin:
            return head + f"needs {tag} {want}; {tag} is {state}; " + no_power
        if out:
            return head + f"needs {tag} {want} and it is {state} -> passes power on."
        member = tag.split(".")[-1].upper() if "." in tag else ""
        base = tag.split(".")[0]
        if member in {"DN", "TT", "EN"} and base in getattr(sim, "timers", {}):
            t = sim.timers[base]
            return head + (f"WAITING for timer {base} {member} ({_secs(t.get('acc_ms'))} of "
                           f"{_secs(t.get('pt_ms'))}). When it comes, power passes on.")
        return head + (f"WAITING for {tag} to turn {want} (it is {state}){_source(tag, wmap)}. "
                       f"When it turns {want}, power passes on.")
    if kind == "or":
        return ("Branch (OR): power gets through if ANY branch below passes -> "
                + ("a branch passed, power goes on." if out else
                   ("no branch passes yet - WAITING for one of them." if pin else no_power)))
    if kind == "coil":
        form = str(el.get("form") or "").lower()
        if form in {"set", "s"}:
            return (f"OTL {tag}{_desc(el)}: " + (f"gets power -> {tag} LATCHED ON (stays on until an OTU)."
                    if pin else f"WAITING for power to latch {tag}; {tag} keeps its last state "
                    f"({'ON' if sim.read(tag) else 'OFF'})."))
        if form in {"reset", "r"}:
            return (f"OTU {tag}{_desc(el)}: " + (f"gets power -> {tag} UNLATCHED (OFF)." if pin else
                    f"WAITING for power to unlatch {tag}; it stays {'ON' if sim.read(tag) else 'OFF'}."))
        return (f"OTE {tag}{_desc(el)}: " + (f"gets power -> {tag} turns ON." if pin else
                f"no power -> {tag} is OFF. WAITING for every part to its left to pass power."))
    if kind == "timer":
        t = getattr(sim, "timers", {}).get(tag) or {}
        block = str(el.get("block") or "TON").upper()
        acc, pre = _secs(t.get("acc_ms")), _secs(t.get("pt_ms") or el.get("pt_ms"))
        if t.get("q"):
            return f"{block} {tag}{_desc(el)}: DONE ({acc} of {pre}) -> {tag}.DN is ON."
        if pin and block in {"TON", "RTO"}:
            left = max(0.0, (float(t.get("pt_ms") or el.get("pt_ms") or 0) - float(t.get("acc_ms") or 0)) / 1000)
            return f"{block} {tag}{_desc(el)}: has power, TIMING {acc} of {pre} -> {tag}.DN turns ON in {left:.1f} s."
        if block == "TOF":
            return (f"TOF {tag}{_desc(el)}: " + ("has power -> DN ON, waiting for power to drop to start the off-delay."
                    if pin else f"power dropped -> off-delay timing {acc} of {pre}."))
        keep = " (RTO keeps its time)" if block == "RTO" else " (ACC resets to 0)"
        return f"{block} {tag}{_desc(el)}: WAITING for power to start timing{keep}; {acc} of {pre}."
    if kind == "counter":
        c = getattr(sim, "counters", {}).get(tag) or {}
        block = str(el.get("block") or "CTU").upper()
        state = f"ACC {int(c.get('acc') or 0)} of PRE {int(c.get('pre') or el.get('pv') or 0)}"
        if c.get("dn"):
            return f"{block} {tag}{_desc(el)}: DONE ({state}) -> {tag}.DN is ON."
        return (f"{block} {tag}{_desc(el)}: counts once each time its power goes OFF->ON; {state}; "
                + ("has power now." if pin else "WAITING for power."))
    if kind == "compare":
        op = str(el.get("op") or "EQU").upper()
        a, b = str(el.get("source_a") or ""), str(el.get("source_b") or "")

        def val(token: str) -> str:
            try:
                return f"{sim.read_number(token):g}"
            except Exception:
                return "?"

        cond = bool(flow.get("cond"))
        head = f"{op} {a} vs {b}: {a}={val(a)}, {b}={val(b)} -> {'TRUE' if cond else 'FALSE'}"
        if not pin:
            return head + "; " + no_power
        return head + ("; passes power on." if out else "; WAITING for the values to match the test.")
    if kind == "oneshot":
        return (f"{str(el.get('block') or 'ONS').upper()} {tag}: passes power for ONE scan when its input goes "
                f"OFF->ON -> " + ("pulse NOW." if out else "no pulse this scan."))
    name = str(el.get("op") or el.get("block") or kind or "?").upper()
    return f"{name} {tag}".strip() + (": has power -> runs." if pin else ": WAITING for power.")


def rung_summary(order: list[tuple[str, dict, int]], flows: dict, energized: bool | None,
                 sim: Any, wmap: dict[str, int]) -> str:
    """Where power stopped on the main line and what would let it through."""
    if energized:
        return "RESULT: rung ENERGIZED - every condition is met, the outputs are ON."
    for key, el, depth in order:
        f = flows.get(key) or {}
        if depth == 0 and f.get("in") and not f.get("out") and _kind(el) not in _OUTPUTS:
            line = explain_part(el, f, sim, wmap)
            return "RESULT: NOT energized - power stops at " + line
    return "RESULT: NOT energized - no power from the left rail reached the outputs."


def explain_rung(elements: list[dict], rid: str, number: int, total: int, comment: str,
                 flows: dict, energized: bool | None, sim: Any, wmap: dict[str, int]) -> list[str]:
    order = flow_order(elements, lambda j: f"{rid}|L|{j}")
    title = f"Rung {number}/{total}" + (f" - {comment.strip().splitlines()[0][:70]}" if comment.strip() else "")
    lines = [title]
    for i, (key, el, depth) in enumerate(order, start=1):
        lines.append("   " + "    " * depth + f"{i}. " + explain_part(el, flows.get(key), sim, wmap))
    lines.append("   " + rung_summary(order, flows, energized, sim, wmap))
    return lines
