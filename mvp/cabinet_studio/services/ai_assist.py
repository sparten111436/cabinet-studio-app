"""AI help for the interview and the live ladder simulation.

* Builds the prompts (rules + the program + the live simulator state).
* Built-in answers that work with no AI service: rung explanations from the
  live simulator ("why is this coil off?") and a test checklist.
* AI rung proposals: parsed from ```cabinet-rung``` blocks and checked with a
  strict allow-list. Anything unknown refuses the WHOLE proposal; a proposal is
  only applied after the user clicks Apply, and only if verify + sim blockers
  stay clean. The AI never edits the program on its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from cabinet_studio.services.ladder_ir import (
    COMPARE_OPS,
    COMPARE_THREE_OPS,
    MATH_OPS,
    ONESHOT_BLOCKS,
    TIMER_BLOCKS,
    clean_elements,
    cpt_expression_error,
    numeric_literal_value,
    program_to_ladder_ir,
)
from cabinet_studio.services.ladder_tools import (
    element_label,
    insert_rung_elements,
    replace_rung_elements,
    valid_tag_name,
    verify_program,
)
from cabinet_studio.services.programming import program_from_dict

SAFETY_NOTE = (
    "E-stop and safety functions must be hardwired or use rated safety relays "
    "(NFPA 79 / ISO 13849). The software is never the safety function."
)

_SAFETY_TAG_RE = re.compile(r"(e[_-]?stop|estop|^es\d|safety|guard|light[_-]?curtain|^sr\d|interlock)", re.I)

BASE_RULES = f"""You are the assistant inside Cabinet Studio, an educational control-cabinet and PLC ladder design aid.
It is NOT a certified UL 508A tool and NOT a live PLC; the simulator is educational.
Rules:
- Answer in plain, short language for a controls technician. Use numbered steps when useful.
- Base every statement on the program, answers and live state you are given. If something is not there, say so.
- Never invent catalog numbers, part numbers or ratings.
- Software is never the safety function. Whenever e-stop, guards or safety come up, include: "{SAFETY_NOTE}"
"""

RUNG_FORMAT = """To PROPOSE a ladder change, add one fenced block per rung, exactly like this:
```cabinet-rung
{"action": "replace", "rung": 12, "comment": "why", "elements": [ ... ]}
```
"action" is "replace" (Main rung number shown as R12) or "add" (new Main rung; optional "after": rung number).
Elements run left to right. Allowed elements ONLY (anything else is refused):
{"kind":"contact","var":"Tag","form":"NO"|"NC"}
{"kind":"coil","var":"Tag","form":"normal"|"negated"|"set"|"reset"}
{"kind":"or","branches":[[...elements...],[...elements...]]}
{"kind":"timer","var":"T1","block":"TON"|"TOF"|"RTO","pt_ms":5000}   (or "pt_tag":"PresetTag")
{"kind":"counter","var":"C1","block":"CTU"|"CTD"|"RES"|"LOAD","pv":10}
{"kind":"compare","op":"EQU|NEQ|GRT|LES|GEQ|LEQ","source_a":"Tag","source_b":"5"}
{"kind":"compare","op":"LIM","source_a":"Test","source_b":"Low","source_c":"High"}
{"kind":"compare","op":"MEQ","source_a":"Source","source_b":"Mask","source_c":"Compare"}
{"kind":"math","op":"ADD|SUB|MUL|DIV|AND|OR|XOR","dest":"D","source_a":"A","source_b":"B"}
{"kind":"math","op":"MOV|NOT","dest":"D","source_a":"A"}
{"kind":"math","op":"CPT","dest":"D","expression":"(A + 2) * 3"}
{"kind":"oneshot","block":"ONS","var":"StorageBit"}   (OSR/OSF also need "output":"PulseBit")
{"kind":"jsr","target":"RoutineName"}   {"kind":"ret"}
Members: T1.DN T1.TT T1.EN T1.ACC, C1.DN C1.ACC. Only propose when the user asks for a change or a fix.
Never weaken e-stop / guard / safety rungs; say what should be hardwired instead.
"""


# ------------------------------------------------------------------ text views
def _els_text(els: list[dict[str, Any]]) -> str:
    parts = []
    for el in els or []:
        if str(el.get("kind") or "").lower() == "or":
            parts.append("[ " + " | ".join(_els_text(b) for b in el.get("branches") or []) + " ]")
        else:
            parts.append(element_label(el))
    return " -- ".join(parts)


def program_text(program: Any, *, limit_chars: int = 24000) -> str:
    ir = program_to_ladder_ir(program_from_dict(program))
    lines = ["MAIN ROUTINE"]
    for i, rung in enumerate(ir.get("rungs") or [], start=1):
        comment = str(rung.get("comment") or "").strip()
        lines.append(f"R{i}: {_els_text(rung.get('elements') or [])}" + (f"    // {comment}" if comment else ""))
    for name, rungs in (ir.get("routines") or {}).items():
        lines.append(f"ROUTINE {name}")
        for i, rung in enumerate(rungs or [], start=1):
            comment = str(rung.get("comment") or "").strip()
            lines.append(f"  {name}.R{i}: {_els_text(rung.get('elements') or [])}" + (f"    // {comment}" if comment else ""))
    aliases = (program_from_dict(program).get("tag_aliases") or {}) if isinstance(program, dict) else {}
    if aliases:
        lines.append("ALIASES: " + ", ".join(f"{a}->{b}" for a, b in aliases.items()))
    text = "\n".join(lines)
    if len(text) > limit_chars:
        text = text[:limit_chars] + "\n... (program truncated)"
    return text


def sim_state_text(sim: Any, *, cursor_index: int | None = None, blockers: list[str] | None = None) -> str:
    if sim is None:
        return "SIMULATION: not running."
    on = sorted(k for k, v in (sim.vars or {}).items() if v and "." not in k)
    off = sorted(k for k, v in (sim.vars or {}).items() if not v and "." not in k)
    lines = [f"SIMULATION: scan #{getattr(sim, 'scan_count', 0)}"
             + (f", executing Main R{cursor_index + 1}" if cursor_index is not None else "")]
    lines.append("ON: " + (", ".join(on) or "-"))
    lines.append("OFF: " + (", ".join(off) or "-"))
    if sim.forces:
        lines.append("FORCED (operator inputs): " + ", ".join(f"{k}={'ON' if v else 'OFF'}" for k, v in sorted(sim.forces.items())))
    for name, t in sorted((sim.timers or {}).items()):
        lines.append(f"TIMER {name} {t.get('block', 'TON')}: ACC {int(t.get('acc_ms') or 0)} / PRE {int(t.get('pt_ms') or 0)} ms"
                     f" EN={int(bool(t.get('en')))} TT={int(bool(t.get('tt')))} DN={int(bool(t.get('q')))}")
    for name, c in sorted((sim.counters or {}).items()):
        lines.append(f"COUNTER {name} {c.get('block', 'CTU')}: ACC {c.get('acc', 0)} / PRE {c.get('pre', 0)} DN={int(bool(c.get('dn')))}")
    if sim.numbers:
        lines.append("NUMBERS: " + ", ".join(f"{k}={_num(v)}" for k, v in sorted(sim.numbers.items())))
    if blockers:
        lines.append("BLOCKERS (sim refuses to run): " + " | ".join(blockers))
    return "\n".join(lines)


def _num(v: Any) -> str:
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else f"{f:.3f}"
    except (TypeError, ValueError):
        return str(v)


# ------------------------------------------------------------------ prompts
def interview_system() -> str:
    return BASE_RULES + (
        "\nYou are helping during the 'New build with AI' interview. The device list is filled ONLY from "
        "the user's library afterwards, so recommend device CLASSES (VFD, contactor, safety relay...), not part numbers."
    )


def _answers_text(answers: dict[str, str], questions: tuple) -> str:
    lines = []
    for key, label, _kind, _opts in questions:
        val = (answers.get(key) or "").strip()
        if val:
            lines.append(f"- {label} -> {val}")
    return "\n".join(lines) or "- (no answers yet)"


def interview_tip_messages(answers: dict[str, str], questions: tuple, index: int) -> list[dict[str, str]]:
    key, label, kind, options = questions[index]
    opts = f"\nOptions: {', '.join(options)}" if options else ""
    return [{"role": "user", "content": (
        f"Answers so far:\n{_answers_text(answers, questions)}\n\nCurrent question: {label}{opts}\n"
        "Give a tip for this question in at most 2 short sentences. If there are options, say which one "
        "you suggest for this machine and why."
    )}]


def interview_question_messages(
    answers: dict[str, str], questions: tuple, index: int, history: list[dict[str, str]], question: str
) -> list[dict[str, str]]:
    _key, label, _kind, options = questions[index]
    context = (f"Answers so far:\n{_answers_text(answers, questions)}\nCurrent question: {label}"
               + (f" (options: {', '.join(options)})" if options else ""))
    return list(history) + [{"role": "user", "content": f"{context}\n\nMy question: {question}"}]


def sim_system() -> str:
    return BASE_RULES + "\nYou are helping while the user tests a ladder program in the live simulator.\n" + RUNG_FORMAT


def sim_messages(
    history: list[dict[str, str]],
    question: str,
    *,
    program: Any,
    sim: Any,
    selected_index: int | None,
    cursor_index: int | None,
    blockers: list[str] | None,
    project_name: str = "",
) -> list[dict[str, str]]:
    sel = f"Selected rung: Main R{selected_index + 1}\n" if selected_index is not None else ""
    context = (f"PROJECT: {project_name}\n{program_text(program)}\n\n"
               f"{sim_state_text(sim, cursor_index=cursor_index, blockers=blockers)}\n{sel}")
    return list(history) + [{"role": "user", "content": f"{context}\nQUESTION: {question}"}]


# ------------------------------------------------------------------ built-in (offline) answers
def _ir_rungs(program: Any) -> list[dict[str, Any]]:
    return list(program_to_ladder_ir(program_from_dict(program)).get("rungs") or [])


def _written_by(program: Any) -> dict[str, list[int]]:
    """tag -> Main rung numbers that drive it (coil, one-shot output, timer/counter, math dest)."""
    out: dict[str, list[int]] = {}

    def walk(els, n):
        for el in els or []:
            k = str(el.get("kind") or "").lower()
            if k == "or":
                for b in el.get("branches") or []:
                    walk(b, n)
                continue
            tag = {"coil": el.get("var"), "timer": el.get("var"), "counter": el.get("var"),
                   "math": el.get("dest"), "oneshot": el.get("output")}.get(k)
            if tag:
                out.setdefault(str(tag), []).append(n)

    for n, rung in enumerate(_ir_rungs(program), start=1):
        walk(rung.get("elements"), n)
    return out


def _conducts(el: dict[str, Any], sim: Any) -> bool | None:
    k = str(el.get("kind") or "").lower()
    if sim is None:
        return None
    if k == "contact":
        return bool(sim._contact_conducts(el))
    if k == "compare":
        try:
            return bool(sim._eval_compare(el))
        except Exception:
            return None
    if k == "oneshot":
        return None
    return True


def _branch_passes(els: list[dict[str, Any]], sim: Any) -> bool | None:
    result: bool | None = True
    for el in els or []:
        if str(el.get("kind") or "").lower() == "or":
            res = [_branch_passes(b, sim) for b in el.get("branches") or []]
            c = True if any(r is True for r in res) else (None if any(r is None for r in res) else False)
        elif str(el.get("kind") or "").lower() in {"coil", "timer", "counter", "math", "jsr", "ret"}:
            continue
        else:
            c = _conducts(el, sim)
        if c is False:
            return False
        if c is None:
            result = None
    return result


def explain_rung(program: Any, index: int, sim: Any = None) -> str:
    """Built-in, offline: walk one Main rung and show what passes or blocks power right now."""
    rungs = _ir_rungs(program)
    if not (0 <= index < len(rungs)):
        return "Select a rung on the ladder first."
    rung = rungs[index]
    writers = _written_by(program)
    lines = [f"Rung R{index + 1}: {rung.get('comment') or '(no comment)'}", ""]
    blockers: list[str] = []

    def describe(els, depth):
        pad = "   " * depth
        for el in els or []:
            k = str(el.get("kind") or "").lower()
            if k == "or":
                lines.append(f"{pad}OR - power passes if ANY branch passes:")
                for bi, br in enumerate(el.get("branches") or [], start=1):
                    ok = _branch_passes(br, sim)
                    mark = "" if ok is None else (" (passes)" if ok else " (blocked)")
                    lines.append(f"{pad}  branch {bi}{mark}:")
                    describe(br, depth + 2)
                continue
            label = element_label(el)
            if sim is None:
                lines.append(f"{pad}- {label}")
                continue
            if k == "contact":
                tag = str(el.get("var") or "")
                val = bool(sim.read(tag))
                ok = bool(sim._contact_conducts(el))
                lines.append(f"{pad}{'OK ' if ok else 'XX '} {label}: {tag} is {'ON' if val else 'OFF'} -> "
                             f"{'passes' if ok else 'BLOCKS'}")
                if not ok:
                    blockers.append(_blocker_hint(tag, el, val, writers, index + 1))
            elif k == "compare":
                ok = _conducts(el, sim)
                vals = ", ".join(f"{s}={_num(sim.read_number(str(el.get(s_key) or '')))}"
                                 for s_key in ("source_a", "source_b", "source_c")
                                 for s in [str(el.get(s_key) or "")] if s)
                lines.append(f"{pad}{'OK ' if ok else 'XX '} {label} ({vals}) -> {'true' if ok else 'FALSE'}")
                if ok is False:
                    blockers.append(f"{label} is false right now ({vals}).")
            elif k == "coil":
                tag = str(el.get("var") or "")
                lines.append(f"{pad}=> {label}: {tag} is {'ON' if sim.read(tag) else 'OFF'}")
            elif k == "timer":
                t = (sim.timers or {}).get(str(el.get("var") or ""), {})
                lines.append(f"{pad}=> {label}: ACC {int(t.get('acc_ms') or 0)} ms, DN={'ON' if t.get('q') else 'OFF'}")
            elif k == "counter":
                c = (sim.counters or {}).get(str(el.get("var") or ""), {})
                lines.append(f"{pad}=> {label}: ACC {c.get('acc', 0)} / PRE {c.get('pre', 0)}, DN={'ON' if c.get('dn') else 'OFF'}")
            else:
                lines.append(f"{pad}-  {label}")

    describe(rung.get("elements") or [], 0)
    if sim is None:
        lines += ["", "Start the simulation to see which instructions pass or block power."]
        return "\n".join(lines)
    ok = _branch_passes(rung.get("elements") or [], sim)
    lines.append("")
    if ok is True:
        lines.append("Power reaches the outputs on this rung right now.")
    elif ok is False:
        lines.append("Power is BLOCKED on this rung. To energize it:")
        lines += [f"  - {b}" for b in dict.fromkeys(blockers)] or ["  - (an OR group has no passing branch)"]
    else:
        lines.append("Part of this rung depends on a one-shot or value that only changes during a scan.")
    if any(_SAFETY_TAG_RE.search(str(el.get("var") or "")) for el in _walk(rung.get("elements") or [])):
        lines += ["", SAFETY_NOTE]
    return "\n".join(lines)


def _walk(els):
    for el in els or []:
        yield el
        if str(el.get("kind") or "").lower() == "or":
            for b in el.get("branches") or []:
                yield from _walk(b)


def _blocker_hint(tag: str, el: dict[str, Any], val: bool, writers: dict[str, list[int]], here: int) -> str:
    want = "OFF" if str(el.get("form") or "NO").upper() == "NC" else "ON"
    base = tag.split(".", 1)[0]
    rungs = writers.get(tag) or writers.get(base)
    if rungs == [here] and "." not in tag:
        return f"{tag} is this rung's own seal-in - it holds itself on once the rest of the rung lets power through."
    if "." in tag:
        return f"{tag} must be {want} - it comes from {base} (rung {', '.join(f'R{r}' for r in rungs or [])})."
    if rungs:
        return f"{tag} must be {want} - it is driven by rung {', '.join(f'R{r}' for r in rungs)}; look there."
    return f"{tag} must be {want} - it is an input: click it on the ladder (or in the I/O panel) to turn it {want}."


def test_checklist(program: Any) -> str:
    """Built-in, offline: what to click to exercise every input, timer and counter."""
    rungs = _ir_rungs(program)
    writers = _written_by(program)
    used: dict[str, list[int]] = {}
    timers, counters = [], []
    for n, rung in enumerate(rungs, start=1):
        for el in _walk(rung.get("elements") or []):
            k = str(el.get("kind") or "").lower()
            if k == "contact":
                tag = str(el.get("var") or "")
                if "." not in tag and tag not in writers:
                    used.setdefault(tag, []).append(n)
            elif k == "timer":
                timers.append(f"{el.get('block', 'TON')} {el.get('var')} (R{n})")
            elif k == "counter" and str(el.get("block") or "").upper() in {"CTU", "CTD"}:
                counters.append(f"{el.get('block')} {el.get('var')} (R{n})")
    lines = ["Test checklist (Built-in):", "", "1. Inputs to click on / off (each one, then watch the rungs listed):"]
    safety = [t for t in used if _SAFETY_TAG_RE.search(t)]
    for tag, rs in sorted(used.items()):
        lines.append(f"   - {tag}: used on {', '.join(f'R{r}' for r in sorted(set(rs)))}")
    if timers:
        lines.append("2. Timers - hold their rung true and watch ACC reach PRE, then break it early once:")
        lines += [f"   - {t}" for t in timers]
    if counters:
        lines.append("3. Counters - pulse the input past the preset, then test the reset:")
        lines += [f"   - {c}" for c in counters]
    lines.append("4. Try an edit while it runs and confirm the outputs follow.")
    if safety:
        lines += ["", f"Safety-related inputs ({', '.join(safety)}): test that each one drops the outputs. " + SAFETY_NOTE]
    return "\n".join(lines)


# ------------------------------------------------------------------ built-in free-form answers (v0.3.24)
GLOSSARY = {
    "TON": "TON (timer on-delay): times while its rung is true. DN turns on when ACC reaches PRE; "
           "the rung going false resets ACC to 0. TT is on while timing.",
    "TOF": "TOF (timer off-delay): DN is on while the rung is true. When the rung goes false it times; "
           "DN turns off when ACC reaches PRE.",
    "RTO": "RTO (retentive timer): like TON but keeps ACC when the rung goes false. Clear it with RES.",
    "CTU": "CTU (count up): adds 1 to ACC on each false-to-true change of its rung. DN when ACC >= PRE. Clear with RES.",
    "CTD": "CTD (count down): subtracts 1 on each false-to-true change of its rung.",
    "RES": "RES (reset): sets a timer or counter ACC back to 0 while its rung is true.",
    "ONS": "ONS (one-shot): passes power for exactly one scan when its rung goes false to true.",
    "OSR": "OSR (one-shot rising): turns its output bit on for one scan on a rising rung edge.",
    "OSF": "OSF (one-shot falling): turns its output bit on for one scan on a falling rung edge.",
    "XIC": "XIC / NO contact [ ]: passes power when its bit is ON.",
    "XIO": "XIO / NC contact [/]: passes power when its bit is OFF.",
    "OTE": "OTE / coil ( ): the bit follows the rung - ON while power reaches it, OFF otherwise.",
    "OTL": "OTL / set coil (S): latches the bit ON; it stays ON until an OTU / reset coil clears it.",
    "OTU": "OTU / reset coil (R): unlatches the bit (sets it OFF) while its rung is true.",
    "SEAL": "Seal-in: the output's own contact in parallel with the start button keeps the rung true after "
            "the button is released; a stop contact in series breaks it.",
    "MOV": "MOV: copies Source into Dest while the rung is true.",
    "CPT": "CPT: calculates an expression into Dest while the rung is true.",
    "LIM": "LIM: true when Low <= Test <= High.",
    "MEQ": "MEQ: true when (Source AND Mask) equals (Compare AND Mask).",
    "EQU": "EQU / NEQ / GRT / LES / GEQ / LEQ: compare A with B; true passes power like a contact.",
    "JSR": "JSR: runs a subroutine while its rung is true; RET returns early.",
    "ESTOP": "E-stop: " + SAFETY_NOTE,
}
_GLOSS_ALIASES = {"SEAL-IN": "SEAL", "SEAL IN": "SEAL", "LATCH": "OTL", "UNLATCH": "OTU", "E-STOP": "ESTOP",
                  "E STOP": "ESTOP", "EMERGENCY STOP": "ESTOP", "ONE-SHOT": "ONS", "ONE SHOT": "ONS",
                  "ON-DELAY": "TON", "ON DELAY": "TON", "OFF-DELAY": "TOF", "OFF DELAY": "TOF",
                  "RETENTIVE": "RTO", "COUNT UP": "CTU", "COUNT DOWN": "CTD", "NEQ": "EQU", "GRT": "EQU",
                  "LES": "EQU", "GEQ": "EQU", "LEQ": "EQU", "RET": "JSR"}


def glossary_answer(question: str) -> str:
    q = " " + re.sub(r"[^A-Z0-9 -]", " ", (question or "").upper()) + " "
    hits = [k for k in GLOSSARY if f" {k} " in q]
    hits += [v for k, v in _GLOSS_ALIASES.items() if f" {k} " in q and v not in hits]
    return "\n\n".join(GLOSSARY[k] for k in dict.fromkeys(hits))


def _program_tags(program: Any, sim: Any) -> set[str]:
    tags = set(_written_by(program))
    for rung in _ir_rungs(program):
        for el in _walk(rung.get("elements") or []):
            for k in ("var", "dest", "output", "source_a", "source_b", "source_c"):
                v = str(el.get(k) or "").strip()
                if v and numeric_literal_value(v) is None:
                    tags.add(v.split(".", 1)[0])
    if sim is not None:
        tags |= {t.split(".", 1)[0] for t in (sim.vars or {})}
    return {t for t in tags if t}


def _used_by(program: Any, tag: str) -> list[int]:
    out = []
    for n, rung in enumerate(_ir_rungs(program), start=1):
        for el in _walk(rung.get("elements") or []):
            if str(el.get("kind") or "").lower() in {"contact", "compare"} and any(
                    str(el.get(k) or "").split(".", 1)[0] == tag for k in ("var", "source_a", "source_b", "source_c")):
                out.append(n)
                break
    return out


def program_problems(program: Any) -> list[str]:
    """Verify errors / warnings plus common logic slips (double coils, unused bits, RTO/CTU never reset)."""
    found = [f"{str(i.get('severity', '')).upper()}: {i.get('message')}" for i in verify_program(program_from_dict(program))]
    writers: dict[str, list[int]] = {}
    resets: set[str] = set()
    retentive: dict[str, int] = {}
    for n, rung in enumerate(_ir_rungs(program), start=1):
        for el in _walk(rung.get("elements") or []):
            k = str(el.get("kind") or "").lower()
            tag = str(el.get("var") or "")
            if k == "coil" and str(el.get("form") or "normal").lower() in {"normal", "negated"}:
                writers.setdefault(tag, []).append(n)
            if k == "counter" and str(el.get("block") or "").upper() == "RES":
                resets.add(tag)
            if (k == "timer" and str(el.get("block") or "").upper() == "RTO") or (
                    k == "counter" and str(el.get("block") or "CTU").upper() in {"CTU", "CTD"}):
                retentive.setdefault(tag, n)
    for tag, rs in sorted(writers.items()):
        if len(rs) > 1:
            found.append(f"{tag} is driven by normal coils on {', '.join(f'R{r}' for r in rs)} - only the last "
                         "one wins each scan. Combine them into one rung with an OR branch.")
    for tag, n in sorted(retentive.items()):
        if tag not in resets:
            found.append(f"{tag} (R{n}) keeps its count / time but nothing resets it - add a RES rung.")
    for tag, rs in sorted(writers.items()):
        if not _used_by(program, tag) and not any(c in tag.upper() for c in ("LAMP", "LIGHT", "HORN", "MOTOR", "VALVE", "RUN")):
            found.append(f"{tag} (R{rs[0]}) is set but no contact reads it - fine if it drives a field device.")
    return found


def builtin_answer(program: Any, sim: Any, question: str, *, selected_index: int | None = None,
                   cursor_index: int | None = None) -> str:
    """Cabinet Studio AI (free, offline): answers typed questions from the program and live sim state."""
    q = (question or "").strip()
    low = q.lower()
    rungs = _ir_rungs(program)
    m = re.search(r"\b(?:r|rung\s*#?)\s*(\d{1,4})\b", low)
    if m:
        return explain_rung(program, int(m.group(1)) - 1, sim)
    if re.search(r"\b(fix|problem|wrong|issue|error|check|mistake|bug)", low):
        probs = program_problems(program)
        return ("Program check (Built-in):\n" + "\n".join(f"- {p}" for p in probs)) if probs else \
            "Program check: no problems found by verify or the logic checks."
    if re.search(r"\b(test|next|try|checklist)\b", low):
        return test_checklist(program)
    tags = _program_tags(program, sim)
    named = [t for t in sorted(tags, key=len, reverse=True) if re.search(rf"(?<![\w.]){re.escape(t.lower())}(?![\w])", low)]
    if named:
        tag = named[0]
        lines = []
        if sim is not None:
            if tag in (sim.timers or {}):
                t = sim.timers[tag]
                lines.append(f"Timer {tag} {t.get('block', 'TON')}: ACC {int(t.get('acc_ms') or 0) / 1000:.1f} s of "
                             f"{int(t.get('pt_ms') or 0) / 1000:.1f} s, TT={'ON' if t.get('tt') else 'off'}, "
                             f"DN={'ON' if t.get('q') else 'off'}.")
            elif tag in (sim.counters or {}):
                c = sim.counters[tag]
                lines.append(f"Counter {tag}: ACC {c.get('acc', 0)} / PRE {c.get('pre', 0)}, DN={'ON' if c.get('dn') else 'off'}.")
            elif tag in (sim.numbers or {}):
                lines.append(f"{tag} = {_num(sim.numbers[tag])}.")
            else:
                lines.append(f"{tag} is {'ON' if sim.read(tag) else 'OFF'} right now"
                             + (" (forced by you)." if tag in (sim.forces or {}) else "."))
        drivers = _written_by(program).get(tag) or []
        users = _used_by(program, tag)
        if drivers:
            lines.append(f"Driven by {', '.join(f'R{r}' for r in drivers)}; read by "
                         f"{', '.join(f'R{r}' for r in users) or 'no rung'}.")
            lines += ["", explain_rung(program, drivers[-1] - 1, sim)]
        else:
            lines.append(f"{tag} is an input (no rung drives it) - click it on the ladder to switch it while simulating. "
                         f"Used on {', '.join(f'R{r}' for r in users) or 'no rung'}.")
        gloss = glossary_answer(q)
        return "\n".join(lines) + (f"\n\n{gloss}" if gloss else "")
    if re.search(r"\btimers?\b", low) and sim is not None and sim.timers:
        return "\n".join(f"{n} {t.get('block', 'TON')}: ACC {int(t.get('acc_ms') or 0) / 1000:.1f} / "
                         f"{int(t.get('pt_ms') or 0) / 1000:.1f} s  {'DN' if t.get('q') else ('timing' if t.get('tt') else 'idle')}"
                         for n, t in sorted(sim.timers.items()))
    if re.search(r"\bcounters?\b", low) and sim is not None and sim.counters:
        return "\n".join(f"{n}: ACC {c.get('acc', 0)} / {c.get('pre', 0)} {'DN' if c.get('dn') else ''}"
                         for n, c in sorted(sim.counters.items()))
    gloss = glossary_answer(q)
    if gloss:
        return gloss
    idx = selected_index if selected_index is not None else cursor_index
    head = ("I'm the built-in Cabinet Studio AI (free, offline). Ask me things like: \"why is Motor_Run off?\", "
            "\"explain R5\", \"what does TON do?\", \"check for problems\", \"what should I test?\", \"timers\".")
    if idx is not None and 0 <= idx < len(rungs):
        return head + "\n\n" + explain_rung(program, idx, sim)
    return head


# ------------------------------------------------------------------ proposals
_PROPOSAL_RE = re.compile(r"```cabinet-rung\s*(.*?)```", re.S | re.I)
_COMMON = {"kind", "desc"}
_ALLOWED_KEYS = {
    "contact": {"var", "form"},
    "coil": {"var", "form"},
    "or": {"branches"},
    "timer": {"var", "block", "pt_ms", "pt_tag"},
    "counter": {"var", "block", "pv", "pv_tag"},
    "compare": {"op", "source_a", "source_b", "source_c"},
    "math": {"op", "dest", "source_a", "source_b", "expression"},
    "oneshot": {"block", "var", "output"},
    "jsr": {"target"},
    "ret": set(),
}


@dataclass
class Proposal:
    action: str
    rung: int | None
    after: int | None
    comment: str
    elements: list[dict[str, Any]]
    problems: list[str] = field(default_factory=list)
    safety: bool = False
    raw: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> str:
        where = f"replace R{self.rung}" if self.action == "replace" else (
            f"add after R{self.after}" if self.after else "add at the end")
        return f"{where}: {_els_text(self.elements)}" + (f"   // {self.comment}" if self.comment else "")


def _check_element(el: Any, routines: set[str], problems: list[str], path: str) -> None:
    if not isinstance(el, dict):
        problems.append(f"{path}: not an instruction object")
        return
    kind = str(el.get("kind") or "").lower()
    if kind not in _ALLOWED_KEYS:
        problems.append(f"{path}: '{el.get('kind')}' is not an instruction Cabinet Studio models")
        return
    extra = set(el) - _ALLOWED_KEYS[kind] - _COMMON
    if extra:
        problems.append(f"{path}: {kind} has unknown field(s) {sorted(extra)}")

    def tag(key, required=True):
        val = str(el.get(key) or "").strip()
        if not val:
            if required:
                problems.append(f"{path}: {kind} needs '{key}'")
            return
        if not valid_tag_name(val):
            problems.append(f"{path}: '{val}' is not a valid tag name")

    def operand(key, required=True):
        val = str(el.get(key) or "").strip()
        if not val:
            if required:
                problems.append(f"{path}: {kind} needs '{key}'")
            return
        if numeric_literal_value(val) is None and not valid_tag_name(val):
            problems.append(f"{path}: '{val}' is not a tag or number")

    if kind == "contact":
        tag("var")
        if str(el.get("form") or "NO").upper() not in {"NO", "NC"}:
            problems.append(f"{path}: contact form must be NO or NC")
    elif kind == "coil":
        tag("var")
        if str(el.get("form") or "normal").lower() not in {"normal", "negated", "set", "reset"}:
            problems.append(f"{path}: coil form must be normal, negated, set or reset")
    elif kind == "or":
        branches = el.get("branches")
        if not isinstance(branches, list) or len(branches) < 2 or not all(isinstance(b, list) and b for b in branches):
            problems.append(f"{path}: OR needs at least two non-empty branches")
            return
        for bi, br in enumerate(branches, start=1):
            for ei, sub in enumerate(br, start=1):
                _check_element(sub, routines, problems, f"{path}.b{bi}.{ei}")
    elif kind == "timer":
        tag("var")
        if str(el.get("block") or "TON").upper() not in TIMER_BLOCKS:
            problems.append(f"{path}: timer block must be one of {', '.join(TIMER_BLOCKS)}")
        if el.get("pt_tag"):
            tag("pt_tag")
        elif not isinstance(el.get("pt_ms"), int) or el.get("pt_ms") <= 0:
            problems.append(f"{path}: timer needs pt_ms (whole milliseconds > 0) or pt_tag")
    elif kind == "counter":
        tag("var")
        blk = str(el.get("block") or "CTU").upper()
        if blk not in {"CTU", "CTD", "RES", "LOAD"}:
            problems.append(f"{path}: counter block must be CTU, CTD, RES or LOAD")
        if blk != "RES" and not el.get("pv_tag") and not isinstance(el.get("pv"), int):
            problems.append(f"{path}: {blk} needs a whole-number pv")
        if el.get("pv_tag"):
            tag("pv_tag")
    elif kind == "compare":
        op = str(el.get("op") or "").upper()
        if op not in COMPARE_OPS:
            problems.append(f"{path}: compare op must be one of {', '.join(COMPARE_OPS)}")
        operand("source_a")
        operand("source_b")
        operand("source_c", required=op in COMPARE_THREE_OPS)
    elif kind == "math":
        op = str(el.get("op") or "").upper()
        if op not in MATH_OPS:
            problems.append(f"{path}: math op must be one of {', '.join(MATH_OPS)}")
        tag("dest")
        if op == "CPT":
            expr = str(el.get("expression") or "").strip()
            err = cpt_expression_error(expr) if expr else "missing expression"
            if err:
                problems.append(f"{path}: CPT expression problem ({err})")
        else:
            operand("source_a")
            operand("source_b", required=op not in {"MOV", "NOT"})
    elif kind == "oneshot":
        blk = str(el.get("block") or "ONS").upper()
        if blk not in ONESHOT_BLOCKS:
            problems.append(f"{path}: one-shot block must be one of {', '.join(ONESHOT_BLOCKS)}")
        tag("var")
        tag("output", required=blk in {"OSR", "OSF"})
    elif kind == "jsr":
        target = str(el.get("target") or "").strip()
        if target not in routines:
            problems.append(f"{path}: JSR target '{target}' is not an existing routine")


def parse_proposals(text: str, program: Any) -> list[Proposal]:
    """Every ```cabinet-rung``` block in an AI reply, each strictly checked (not applied)."""
    data = program_from_dict(program)
    n_rungs = len(data.get("rungs") or [])
    routines = set((data.get("routines") or {}).keys())
    out: list[Proposal] = []
    for raw in _PROPOSAL_RE.findall(text or ""):
        problems: list[str] = []
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            out.append(Proposal("?", None, None, "", [], [f"not valid JSON ({exc.msg})"], raw=raw))
            continue
        if not isinstance(obj, dict):
            out.append(Proposal("?", None, None, "", [], ["proposal must be a JSON object"], raw=raw))
            continue
        extra = set(obj) - {"action", "rung", "after", "comment", "elements"}
        if extra:
            problems.append(f"unknown field(s) {sorted(extra)}")
        action = str(obj.get("action") or "").lower()
        rung = obj.get("rung") if isinstance(obj.get("rung"), int) else None
        after = obj.get("after") if isinstance(obj.get("after"), int) else None
        if action not in {"replace", "add"}:
            problems.append("action must be 'replace' or 'add'")
        if action == "replace" and not (rung and 1 <= rung <= n_rungs):
            problems.append(f"rung must be a Main rung number 1..{n_rungs}")
        if action == "add" and after is not None and not (1 <= after <= n_rungs):
            problems.append(f"after must be a Main rung number 1..{n_rungs}")
        els = obj.get("elements")
        if not isinstance(els, list) or not els:
            problems.append("elements must be a non-empty list")
            els = []
        for i, el in enumerate(els, start=1):
            _check_element(el, routines, problems, f"element {i}")
        if not problems and len(list(_walk(clean_elements(els)))) != len(list(_walk(els))):
            problems.append("some instructions could not be modelled exactly")
        tags = {str(e.get(k) or "") for e in _walk(els) if isinstance(e, dict) for k in ("var", "dest", "output")}
        if action == "replace" and rung and 1 <= rung <= n_rungs:
            old = _ir_rungs(program)[rung - 1].get("elements") or []
            tags |= {str(e.get("var") or "") for e in _walk(old)}
        out.append(Proposal(action, rung, after, str(obj.get("comment") or "").strip(), els, problems,
                            safety=any(_SAFETY_TAG_RE.search(t) for t in tags if t), raw=raw))
    return out


def apply_proposal(program: Any, prop: Proposal, *, sim_blockers_fn=None) -> tuple[dict[str, Any], str]:
    """Return (new program, new/changed rung id). Raises ValueError if it would break the program."""
    if not prop.ok:
        raise ValueError("Refused: " + "; ".join(prop.problems))
    data = program_from_dict(program)
    ids = [r["id"] for r in data.get("rungs") or []]
    if prop.action == "replace":
        rid = ids[prop.rung - 1]
        new = replace_rung_elements(data, rid, prop.elements, comment=prop.comment or None)
    else:
        new, rid = insert_rung_elements(data, prop.elements, comment=prop.comment or "AI suggestion",
                                        after_id=ids[prop.after - 1] if prop.after else None)

    def errors(p):
        return {(i.get("code"), str(i.get("message"))) for i in verify_program(p)
                if str(i.get("severity", "")).lower() == "error"}

    added = errors(new) - errors(data)
    if added:
        raise ValueError("Refused - it would add verify errors: " + "; ".join(m for _c, m in sorted(added))[:400])
    if sim_blockers_fn is not None:
        blk = sim_blockers_fn(new)
        if blk:
            raise ValueError("Refused - the simulator could not run it: " + " | ".join(blk)[:400])
    return new, rid
