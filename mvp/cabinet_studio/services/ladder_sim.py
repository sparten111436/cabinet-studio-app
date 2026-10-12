"""Educational scan-cycle simulator for Cabinet Studio ladder IR.

Evaluates NO/NC contacts, series/parallel (OR, including nested OR), coils
(including mid-rung OTE-style passthrough), TON/TOF/RTO timers and
CTU/CTD counters (+ RES / LOAD), compares (EQU…LEQ), and math (ADD…MOV/CPT)
once per scan (left-to-right). Forces override BOOL tags for
teaching I/O. Not a live PLC; not a vendor engine.

Counter semantics (v0.3.3, educational approximation aligned with Micro800 /
CCW CTU/CTD and Rockwell .ACC/.PRE/.DN naming):
- CTU: ACC += 1 on each rising edge of rung-in (CU). Keeps counting past PRE
  (like CCW CV / Rockwell ACC), clamps at 32767 and sets OV. DN = ACC >= PRE.
- CTD: ACC -= 1 on each rising edge of rung-in (CD). Clamps at -32768 and sets
  UN. DN = ACC <= 0 (CCW CTD Q = CV <= 0).
- RES: while rung-in is true, ACC := 0 and OV/UN clear (CCW CTU RESET input /
  Rockwell RES). Edge memory (CU/CD) is NOT cleared, so a held count input does
  not double-count after a reset (CCW R_TRIG behaviour).
- LOAD: while rung-in is true, ACC := PRE (CCW CTD LOAD input).
- CU / CD bits mirror the count rung condition from the last scan.
- Reading the counter tag (or C1.DN) as a contact returns DN; C1.CU, C1.CD,
  C1.OV, C1.UN are also readable. Timers expose T1.DN / T1.TT / T1.EN.

One-shot semantics (v0.3.6, educational, Studio/CCW naming):
- ONS (input-style): rung-out is TRUE for exactly one scan when rung-in goes
  FALSE→TRUE. Storage bit := rung-in each scan.
- OSR (output-style): output bit TRUE for one scan on a rung-in rising edge.
  Storage bit := rung-in. Power passes through unchanged (like OTE); use the
  output bit as a contact on later rungs. IEC peer: R_TRIG.Q.
- OSF: same as OSR on a rung-in falling edge (TRUE→FALSE). IEC peer: F_TRIG.Q.

Power flow (v0.3.6): every scan records ``power_flow[key] = {in, cond, out}``
per instruction so the canvas can highlight energized wires (Studio/TIA
online-monitor style). ``cond`` is the instruction's own truth (contact
conducts, compare holds) independent of left power; ``in``/``out`` are rung
power entering / leaving it. Keys: top level ``"{rung}|L|{i}"``; inside an OR
``"{or_key}|b{branch}|{j}"``.

Rung-by-rung run (v0.3.20): ``scan_rung(i)`` executes one Main rung; a pass
over every rung is one scan. Setting ``clock_ms`` (monotonic ms) makes timers
count real elapsed time between their own evaluations. ``adopt_state(old)``
carries tag values, timer/counter ACC and forces into a simulator rebuilt
after a program edit, so the program can be edited while it runs.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from cabinet_studio.services.ladder_ir import (
    JSR_MAX_DEPTH,
    normalize_routine_name,
    normalize_tag_aliases,
    resolve_alias,
    COMPARE_OPS,
    COUNTER_MAX,
    COUNTER_MIN,
    COUNTER_OWNER_BLOCKS,
    MATH_OPS,
    ONESHOT_OUTPUT_BLOCKS,
    normalize_oneshot_block,
    clamp_counter,
    clamp_numeric,
    coerce_numeric,
    collect_tags,
    eval_cpt_expression,
    cpt_expression_error,
    numeric_literal_value,
    to_dint,
    COMPARE_THREE_OPS,
    normalize_compare_op,
    normalize_counter_block,
    normalize_ladder_ir,
    normalize_math_op,
    program_to_ladder_ir,
    split_member,
)


def _new_counter(block: str = "CTU", pre: int = 0) -> dict[str, Any]:
    blk = block if block in COUNTER_OWNER_BLOCKS else "CTU"
    pre = clamp_counter(pre)
    return {
        "block": blk,
        "pre": pre,
        "acc": 0,
        "dn": (0 <= 0) if blk == "CTD" else (0 >= pre),
        "cu": False,
        "cd": False,
        "ov": False,
        "un": False,
    }


class ScanSimulator:
    """In-process educational soft scan over ladder IR."""

    def __init__(
        self,
        ladder: dict[str, Any] | None = None,
        *,
        cycle_ms: int = 50,
    ) -> None:
        self.ladder = normalize_ladder_ir(ladder or {})
        self.cycle_ms = max(1, int(cycle_ms))
        self.vars: dict[str, bool] = {}
        self.numbers: dict[str, float] = {}
        self.number_types: dict[str, str] = {}
        self.forces: dict[str, bool] = {}
        self.timers: dict[str, dict[str, Any]] = {}
        self.counters: dict[str, dict[str, Any]] = {}
        self.scan_count = 0
        self.last_energized: dict[str, bool] = {}  # rung_id -> path true?
        self.last_contact_state: dict[str, bool] = {}  # "rung|idx|var" conducting
        self.power_flow: dict[str, dict[str, bool]] = {}  # key -> {in, cond, out}
        # v0.3.20: when clock_ms is set (monotonic ms), timers accumulate real
        # elapsed time between their own evaluations instead of cycle_ms.
        self.clock_ms: float | None = None
        self._timer_clock: dict[str, float] = {}
        self.rung_cursor = 0
        meta = self.ladder.get("meta") if isinstance(self.ladder.get("meta"), dict) else {}
        self.aliases = normalize_tag_aliases(meta.get("tag_aliases") or self.ladder.get("tag_aliases"))
        # Named routines (excluding Main which is ladder["rungs"]).
        self.routines: dict[str, list[dict]] = {}
        raw_routines = self.ladder.get("routines") if isinstance(self.ladder.get("routines"), dict) else {}
        for rname, rrungs in (raw_routines or {}).items():
            name = normalize_routine_name(rname)
            if name and name != "Main" and isinstance(rrungs, list):
                self.routines[name] = list(rrungs)
        self._call_stack: list[str] = []
        self._init_vars()

    def _init_vars(self) -> None:
        inputs, outputs, all_tags = collect_tags(self.ladder)
        for tag in all_tags:
            self.vars.setdefault(tag, False)
        for var in self.ladder.get("variables") or []:
            name = str(var.get("name") or "").strip()
            if not name:
                continue
            self.vars.setdefault(name, False)
            if str(var.get("type") or "").upper() in {"TON", "TOF", "RTO"} or str(
                var.get("class") or ""
            ).lower() == "timer":
                blk = str(var.get("type") or var.get("block") or "TON").upper()
                if blk not in {"TON", "TOF", "RTO"}:
                    blk = "TON"
                self.timers[name] = {
                    "block": blk,
                    "pt_ms": int(var.get("pt_ms") or 0),
                    "acc_ms": 0,
                    "q": False,
                    "tt": False,
                }
        # Seed timer instances declared only on rung elements (UI-placed timers).
        for rung in self.ladder.get("rungs") or []:
            for el in rung.get("elements") or []:
                if str(el.get("kind") or "").lower() != "timer":
                    continue
                name = str(el.get("var") or "").strip()
                if not name:
                    continue
                blk = str(el.get("block") or "TON").upper()
                if blk not in {"TON", "TOF", "RTO"}:
                    blk = "TON"
                pt_ms = max(0, int(el.get("pt_ms") or 0))
                self.vars.setdefault(name, False)
                if name not in self.timers:
                    self.timers[name] = {
                        "block": blk,
                        "pt_ms": pt_ms,
                        "acc_ms": 0,
                        "q": False,
                        "tt": False,
                    }
                elif pt_ms and not self.timers[name].get("pt_ms"):
                    self.timers[name]["pt_ms"] = pt_ms
        # Counter instances: variables first, then rung elements (CTU/CTD own the mode).
        for var in self.ladder.get("variables") or []:
            name = str(var.get("name") or "").strip()
            if not name:
                continue
            vtype = str(var.get("type") or "").upper()
            if vtype in COUNTER_OWNER_BLOCKS or str(var.get("class") or "").lower() == "counter":
                blk = vtype if vtype in COUNTER_OWNER_BLOCKS else "CTU"
                self.counters[name] = _new_counter(blk, var.get("pv", 0))
                self.vars.setdefault(name, False)
        owners_seen: set[str] = set()
        for rung in self.ladder.get("rungs") or []:
            for el in rung.get("elements") or []:
                if str(el.get("kind") or "").lower() != "counter":
                    continue
                name = str(el.get("var") or "").strip()
                if not name:
                    continue
                blk = normalize_counter_block(el.get("block"))
                self.vars.setdefault(name, False)
                if blk in COUNTER_OWNER_BLOCKS and name not in owners_seen:
                    owners_seen.add(name)
                    self.counters[name] = _new_counter(blk, el.get("pv", 0))
                elif name not in self.counters:
                    self.counters[name] = _new_counter("CTU", el.get("pv", 0) if blk == "LOAD" else 0)
        for name, ctr in self.counters.items():
            self.vars[name] = bool(ctr["dn"])
        # Numeric tags (compare/math) — educational INT/DINT-style values.
        self.number_types: dict[str, str] = getattr(self, "number_types", {})
        for var in self.ladder.get("variables") or []:
            name = str(var.get("name") or "").strip()
            if not name:
                continue
            # v0.3.13: do not treat T1.ACC / C1.PRE declarations as standalone numbers
            _base, _member = split_member(name)
            if _member in {"ACC", "PRE"}:
                continue
            cls = str(var.get("class") or "").lower()
            vtype = str(var.get("type") or "").upper()
            if cls == "numeric" or vtype in {"INT", "DINT", "REAL", "UINT", "LREAL", "SINT", "USINT", "UDINT"}:
                self.number_types[name] = vtype if vtype else "REAL"
                raw_val = var.get("value", var.get("initial", 0))
                self.numbers[name] = coerce_numeric(raw_val, self.number_types[name], op="MOV")
                self.vars.pop(name, None)  # numeric tags are not BOOL force targets
        for rung in self.ladder.get("rungs") or []:
            for el in rung.get("elements") or []:
                kind = str(el.get("kind") or "").lower()
                if kind == "compare":
                    for key in ("source_a", "source_b", "source_c"):
                        tok = str(el.get(key) or "").strip()
                        if not tok or tok in self.numbers:
                            continue
                        # Do not seed timer/counter members as numeric tags (P2c / NEW-I).
                        _base, _member = split_member(tok)
                        if _member:
                            continue
                        if numeric_literal_value(tok) is None:
                            self.numbers.setdefault(tok, 0.0)
                            self.vars.pop(tok, None)
                elif kind == "math":
                    for key in ("dest", "source_a", "source_b"):
                        tok = str(el.get(key) or "").strip()
                        if not tok or tok in self.numbers:
                            continue
                        _base, _member = split_member(tok)
                        if _member:
                            continue
                        if numeric_literal_value(tok) is None:
                            self.numbers.setdefault(tok, 0.0)
                            self.vars.pop(tok, None)
        # v0.3.18 NEW-9: PT / PV preset tags are numeric (never BOOL force targets).
        def _preset_walk(items: list) -> None:
            for el in items or []:
                if not isinstance(el, dict):
                    continue
                k = str(el.get("kind") or "").lower()
                if k == "or":
                    for b in el.get("branches") or []:
                        _preset_walk(list(b or []))
                    continue
                tag = str(el.get("pt_tag") or el.get("pv_tag") or "").strip() if k in {"timer", "counter"} else ""
                if tag and not split_member(tag)[1]:
                    self.numbers.setdefault(tag, 0.0)
                    self.number_types.setdefault(tag, "DINT")
                    self.vars.pop(tag, None)

        for rung in list(self.ladder.get("rungs") or []) + [
            r for rl in self.routines.values() for r in (rl or []) if isinstance(r, dict)
        ]:
            _preset_walk(list(rung.get("elements") or []))
        # Remove pure numeric tags from forceable input set
        self._input_tags = set(inputs) - set(self.numbers)
        self._output_tags = set(outputs) - set(self.numbers)

    @classmethod
    def from_program(
        cls,
        program: dict[str, Any] | None,
        *,
        project_name: str = "",
        devices: list[dict[str, str]] | None = None,
        cycle_ms: int = 50,
    ) -> "ScanSimulator":
        ir = program_to_ladder_ir(program, project_name=project_name, devices=devices)
        return cls(ir, cycle_ms=cycle_ms)

    def reset(self) -> None:
        for tag in list(self.vars):
            self.vars[tag] = False
        for name in list(self.numbers):
            self.numbers[name] = 0.0
        for tmr in self.timers.values():
            tmr["acc_ms"] = 0
            tmr["q"] = False
            tmr["tt"] = False
            tmr["en"] = False
        for name, ctr in self.counters.items():
            fresh = _new_counter(ctr.get("block", "CTU"), ctr.get("pre", 0))
            ctr.clear()
            ctr.update(fresh)
            self.vars[name] = bool(ctr["dn"])
        self.forces.clear()
        self.scan_count = 0
        self.last_energized.clear()
        self.last_contact_state.clear()
        self.power_flow.clear()
        self._timer_clock.clear()
        self.rung_cursor = 0

    def adopt_state(self, old: "ScanSimulator") -> None:
        """v0.3.20: carry live values from the simulator of the previous program
        version (edit while running). Only tags that still exist carry over;
        presets come from the new program."""
        for tag, val in old.vars.items():
            if tag in self.vars:
                self.vars[tag] = bool(val)
        for tag, val in old.numbers.items():
            if tag in self.numbers:
                self.numbers[tag] = val
        for name, tmr in old.timers.items():
            new = self.timers.get(name)
            if new is None:
                continue
            for key in ("acc_ms", "q", "tt", "en"):
                if key in tmr:
                    new[key] = tmr[key]
            if name in old._timer_clock:
                self._timer_clock[name] = old._timer_clock[name]
            self.vars[name] = bool(new.get("q"))
        for name, ctr in old.counters.items():
            new = self.counters.get(name)
            if new is None:
                continue
            for key in ("acc", "cu", "cd", "ov", "un"):
                if key in ctr:
                    new[key] = ctr[key]
            acc = int(new.get("acc") or 0)
            new["dn"] = acc <= 0 if new.get("block") == "CTD" else acc >= int(new.get("pre") or 0)
            self.vars[name] = bool(new["dn"])
        known = set(self.vars) | set(self.timers) | set(self.counters)
        for tag, val in old.forces.items():
            if tag in known:
                self.forces[tag] = bool(val)
                self.vars[tag] = bool(val)
        self.scan_count = old.scan_count
        self.clock_ms = old.clock_ms
        # Highlights survive only for rungs whose content did not change.
        old_rungs = {str(r.get("id") or ""): r for r in old.ladder.get("rungs") or []}
        same = {
            str(r.get("id") or "")
            for r in self.ladder.get("rungs") or []
            if old_rungs.get(str(r.get("id") or "")) == r
        }

        def _kept(key: str) -> bool:
            return key.split("|", 1)[0] in same

        self.power_flow = {k: dict(v) for k, v in old.power_flow.items() if _kept(k)}
        self.last_contact_state = {k: v for k, v in old.last_contact_state.items() if _kept(k)}
        self.last_energized = {k: v for k, v in old.last_energized.items() if _kept(k)}
        count = len(self.ladder.get("rungs") or [])
        self.rung_cursor = old.rung_cursor % count if count else 0


    def _resolve(self, tag: str) -> str:
        """Map alias (or alias.member) to the base tag used in vars/timers."""
        return resolve_alias(tag, self.aliases)

    def set_force(self, tag: str, value: bool | None) -> None:
        """Force a tag True/False, or None to clear the force."""
        name = self._resolve(tag)
        if not name:
            return
        if value is None:
            # A released input reads its (simulated, de-energized) field value again, like a
            # momentary button springing back; program-written tags keep their last value.
            if self.forces.pop(name, None) is not None and name in self._input_tags:
                self.vars[name] = False
        else:
            self.forces[name] = bool(value)
            self.vars[name] = bool(value)

    def toggle_force(self, tag: str) -> bool:
        name = self._resolve(tag)
        if not name:
            return False
        current = self.read(name)
        self.set_force(name, not current)
        return self.read(name)

    def reset_instruction(self, tag: str) -> bool:
        """v0.3.20: operator reset of a timer or counter (ACC := 0, bits off)."""
        name = self._resolve(split_member(tag)[0] or tag)
        if name in self.timers:
            tmr = self.timers[name]
            tmr.update(acc_ms=0, q=False, tt=False)
            self._timer_clock.pop(name, None)
            self.vars[name] = False
            return True
        if name in self.counters:
            ctr = self.counters[name]
            ctr.update(acc=0, ov=False, un=False)
            ctr["dn"] = ctr.get("block") == "CTD" or int(ctr.get("pre") or 0) <= 0
            self.vars[name] = bool(ctr["dn"])
            return True
        return False

    def set_number(self, tag: str, value: object) -> None:
        """Seed/update a numeric tag (educational INT/DINT)."""
        name = self._resolve(tag)
        if not name:
            return
        dtype = self.number_types.get(name) or "REAL"
        self.numbers[name] = coerce_numeric(value, dtype, op="MOV")

    def read_number(self, token: str) -> float:
        """Resolve a compare/math operand: literal (dec/hex) or numeric tag (else 0)."""
        raw = str(token or "").strip()
        if not raw:
            return 0.0
        lit = numeric_literal_value(raw)
        if lit is not None:
            return clamp_numeric(lit)
        if True:
            raw = self._resolve(raw)
            # v0.3.13 P2c: live timer/counter members beat a stale numeric seed
            # (T1.ACC was pre-seeded to 0.0 from compare operands, masking ACC).
            base, member = split_member(raw)
            if member == "ACC" and base in self.counters:
                return float(self.counters[base].get("acc") or 0)
            if member == "ACC" and base in self.timers:
                return float(self.timers[base].get("acc_ms") or 0)
            if member == "PRE" and base in self.counters:
                return float(self.counters[base].get("pre") or 0)
            if member == "PRE" and base in self.timers:
                return float(self.timers[base].get("pt_ms") or 0)
            if raw in self.numbers:
                return float(self.numbers[raw])
            return 0.0

    def read(self, tag: str) -> bool:
        name = self._resolve(tag)
        if name in self.forces:
            return bool(self.forces[name])
        if name in self.timers:
            return bool(self.timers[name].get("q"))
        if name in self.counters:
            return bool(self.counters[name].get("dn"))
        base, member = split_member(name)
        if member:
            if base in self.counters:
                ctr = self.counters[base]
                key = {"DN": "dn", "Q": "dn", "CU": "cu", "CD": "cd", "OV": "ov", "UN": "un"}.get(member)
                return bool(ctr.get(key)) if key else False
            if base in self.timers:
                tmr = self.timers[base]
                key = {"DN": "q", "Q": "q", "TT": "tt", "EN": "en"}.get(member)
                return bool(tmr.get(key)) if key else False
        return bool(self.vars.get(name, False))

    def _eval_contact(self, el: dict[str, Any], path_key: str) -> bool:
        tag = (el.get("var") or "").strip()
        form = str(el.get("form") or "NO").upper()
        value = self.read(tag)
        conducting = (not value) if form == "NC" else bool(value)
        self.last_contact_state[path_key] = conducting
        return conducting

    def _contact_conducts(self, el: dict[str, Any]) -> bool:
        """Instruction truth of a contact (no side effects, independent of power)."""
        value = self.read((el.get("var") or "").strip())
        return (not value) if str(el.get("form") or "NO").upper() == "NC" else bool(value)

    def _note_flow(self, key: str, pin: bool, cond: bool, pout: bool) -> None:
        self.power_flow[key] = {"in": bool(pin), "cond": bool(cond), "out": bool(pout)}

    def _apply_oneshot(self, el: dict[str, Any], power: bool) -> bool:
        """Evaluate ONS / OSR / OSF; return power leaving the instruction."""
        blk = normalize_oneshot_block(el.get("block"))
        storage = (el.get("var") or "").strip()
        prev = bool(self.vars.get(storage, False)) if storage else False
        if storage:
            self.vars[storage] = bool(power)
        if blk == "ONS":
            return bool(power) and not prev
        pulse = (bool(power) and not prev) if blk == "OSR" else ((not power) and prev)
        output = (el.get("output") or "").strip()
        if output and output not in self.forces:
            self.vars[output] = bool(pulse)
        return bool(power)

    def _series_flow(self, items: list[dict[str, Any]], prefix: str, pin: bool) -> bool:
        """Left-to-right power through a series list (OR branch). Records flow + contact state.

        v0.3.11: coils / timers / counters / math / JSR inside OR branches execute
        (ENO-style passthrough), matching top-level scan semantics.
        """
        power = bool(pin)
        for j, item in enumerate(items or []):
            key = f"{prefix}|{j}"
            kind = (item.get("kind") or "").lower()
            if kind == "contact":
                cond = self._contact_conducts(item)
                out = power and cond
                self.last_contact_state[key] = out
            elif kind == "or":
                cond = True
                out = self._or_flow(item, key, power)
            elif kind == "compare":
                cond = self._eval_compare(item)
                out = power and cond
            elif kind == "oneshot":
                cond = power
                out = self._apply_oneshot(item, power)
            elif kind == "coil":
                self._apply_coil(item, power)
                cond = True
                out = power
            elif kind == "timer":
                name = self._resolve(str(item.get("var") or ""))
                block = str(item.get("block") or "TON").upper()
                if block not in {"TON", "TOF", "RTO"}:
                    block = "TON"
                pt_ms = self._timer_preset_ms(item)
                if name:
                    if name not in self.timers:
                        self.timers[name] = {
                            "block": block, "pt_ms": pt_ms, "acc_ms": 0, "q": False, "tt": False,
                        }
                    else:
                        if pt_ms or item.get("pt_tag"):
                            self.timers[name]["pt_ms"] = pt_ms
                        self.timers[name]["block"] = block
                    self._update_timer(name, block, power)
                cond = True
                out = power  # ENO passthrough (box does not break the rail)
            elif kind == "counter":
                name = self._resolve(str(item.get("var") or ""))
                if name:
                    self._update_counter(name, str(item.get("block") or "CTU"), self._counter_preset(item), power)
                cond = True
                out = power
            elif kind == "math":
                self._apply_math(item, power)
                cond = True
                out = power
            elif kind == "jsr":
                target = normalize_routine_name(item.get("target"))
                cond = True
                out = power
                if power and target and target != "Main":
                    if target in self._call_stack or len(self._call_stack) >= JSR_MAX_DEPTH:
                        cond = False
                    elif target in self.routines:
                        self._call_stack.append(target)
                        try:
                            # Nested JSR inside OR: scan sub with a throwaway energized map
                            nested: dict[str, bool] = {}
                            self._scan_rung_list(
                                self.routines[target],
                                energized_paths=nested,
                                key_prefix=f"{key}>",
                            )
                        finally:
                            self._call_stack.pop()
            else:
                cond = power
                out = power
            self._note_flow(key, power, cond, out)
            power = out
        return power

    def _or_flow(self, el: dict[str, Any], key: str, pin: bool) -> bool:
        branches = list(el.get("branches") or [])
        any_out = False
        for bi, branch in enumerate(branches):
            if self._series_flow(list(branch or []), f"{key}|b{bi}", pin):
                any_out = True
        return bool(pin) and any_out

    # Back-compat helpers (pre-0.3.6 callers / tests)
    def _eval_series(self, elements: list[dict[str, Any]], key_prefix: str) -> bool:
        return self._series_flow(list(elements or []), key_prefix, True)

    def _eval_element(self, el: dict[str, Any], path_key: str) -> bool:
        kind = (el.get("kind") or "").lower()
        if kind == "contact":
            return self._eval_contact(el, path_key)
        if kind == "or":
            return self._or_flow(el, path_key, True)
        if kind == "timer":
            tag = (el.get("var") or "").strip()
            return bool(self.timers.get(tag, {}).get("q"))
        if kind == "coil":
            return True
        return False

    def _mark_or_dead(self, el: dict[str, Any], path_key: str) -> None:
        self._or_flow(el, path_key, False)

    def _apply_coil(self, el: dict[str, Any], energized: bool) -> None:
        tag = self._resolve(str(el.get("var") or ""))
        if not tag:
            return
        form = str(el.get("form") or "normal").lower()
        if tag in self.forces and form in {"normal", "negated"}:
            # Forced tags stay forced; educational note: force wins over coil.
            return
        if form in {"set", "s"}:
            if energized:
                self.vars[tag] = True
        elif form in {"reset", "r"}:
            if energized:
                self.vars[tag] = False
        elif form in {"negated", "not", "nc"}:
            self.vars[tag] = not energized
        else:
            self.vars[tag] = bool(energized)

    def _timer_preset_ms(self, el: dict[str, Any]) -> int:
        """v0.3.18 NEW-9: literal PT, or the live value (ms) of the PT tag."""
        tag = str(el.get("pt_tag") or "").strip()
        if tag:
            return max(0, int(self.read_number(tag)))
        return max(0, int(el.get("pt_ms") or 0))

    def _counter_preset(self, el: dict[str, Any]) -> int:
        """v0.3.18 NEW-9: literal PV, or the live value of the PV tag."""
        tag = str(el.get("pv_tag") or "").strip()
        if tag:
            return clamp_counter(self.read_number(tag))
        return int(el.get("pv") or 0)

    def _timer_elapsed_ms(self, name: str, counting: bool) -> int:
        """Time to add to a timer's ACC on this evaluation.

        Without a clock: cycle_ms per counting scan (legacy). With clock_ms:
        real time since this timer's previous counting evaluation; the scan
        that starts the count adds 0, like a PLC timer starting its timebase."""
        if self.clock_ms is None:
            return self.cycle_ms if counting else 0
        if not counting:
            self._timer_clock.pop(name, None)
            return 0
        now = float(self.clock_ms)
        last = self._timer_clock.get(name)
        self._timer_clock[name] = now
        return max(0, int(round(now - last))) if last is not None else 0

    def _update_timer(self, name: str, block: str, inn: bool) -> None:
        tmr = self.timers.setdefault(
            name,
            {"block": block or "TON", "pt_ms": 0, "acc_ms": 0, "q": False, "tt": False},
        )
        block = (block or tmr.get("block") or "TON").upper()
        pt = int(tmr.get("pt_ms") or 0)
        tmr["en"] = bool(inn)
        if block == "TOF":
            if inn:
                self._timer_elapsed_ms(name, False)
                tmr["acc_ms"] = 0
                tmr["q"] = True
                tmr["tt"] = False
            else:
                if tmr.get("q"):
                    tmr["acc_ms"] = int(tmr.get("acc_ms") or 0) + self._timer_elapsed_ms(name, True)
                    tmr["tt"] = True
                    if tmr["acc_ms"] >= pt:
                        tmr["q"] = False
                        tmr["tt"] = False
                        tmr["acc_ms"] = pt
                else:
                    self._timer_elapsed_ms(name, False)
                    tmr["tt"] = False
        else:  # TON / RTO-ish educational
            if inn:
                tmr["acc_ms"] = int(tmr.get("acc_ms") or 0) + self._timer_elapsed_ms(name, True)
                tmr["tt"] = tmr["acc_ms"] < pt
                tmr["q"] = tmr["acc_ms"] >= pt
                if tmr["q"]:
                    tmr["acc_ms"] = max(tmr["acc_ms"], pt)
                    tmr["tt"] = False
            else:
                self._timer_elapsed_ms(name, False)
                if block != "RTO":
                    tmr["acc_ms"] = 0
                tmr["q"] = False
                tmr["tt"] = False
        self.vars[name] = bool(tmr["q"])

    def tick_timers(self) -> bool:
        """v0.3.24: advance running timers to ``clock_ms`` between evaluations of their rungs.

        In slow rung-by-rung runs a timer's rung is only visited once per pass, but a
        PLC timer keeps timing while its rung stays enabled. A TON/RTO whose rung was
        last true, or a TOF whose rung was last false, accumulates real time here; the
        next evaluation of the rung continues from the same clock stamp, so nothing is
        counted twice. Returns True when a DN bit changed."""
        if self.clock_ms is None:
            return False
        now = float(self.clock_ms)
        changed = False
        for name, tmr in self.timers.items():
            if "en" not in tmr:
                continue  # never evaluated yet
            block = str(tmr.get("block") or "TON").upper()
            if block == "TOF":
                running = (not tmr.get("en")) and bool(tmr.get("q"))
            else:
                running = bool(tmr.get("en")) and not tmr.get("q")
            if not running:
                continue
            last = self._timer_clock.get(name)
            self._timer_clock[name] = now
            if last is None:
                continue
            pt = int(tmr.get("pt_ms") or 0)
            tmr["acc_ms"] = int(tmr.get("acc_ms") or 0) + max(0, int(round(now - last)))
            if tmr["acc_ms"] >= pt:
                tmr["acc_ms"] = pt
                tmr["q"] = block != "TOF"
                tmr["tt"] = False
                changed = True
            else:
                tmr["tt"] = True
            if name not in self.forces:
                self.vars[name] = bool(tmr["q"])
        return changed

    def freeze_timers(self) -> None:
        """Pause: bring timers up to date, then forget clock stamps so paused time is not counted."""
        self.tick_timers()
        self._timer_clock.clear()

    def _update_counter(self, name: str, block: str, pv: int, rung_in: bool) -> None:
        """One counter instruction evaluation (see module docstring for semantics)."""
        blk = normalize_counter_block(block)
        ctr = self.counters.get(name)
        if ctr is None:
            ctr = _new_counter(blk if blk in COUNTER_OWNER_BLOCKS else "CTU", pv)
            self.counters[name] = ctr
        acc = int(ctr.get("acc") or 0)
        if blk == "CTU":
            ctr["pre"] = clamp_counter(pv)
            if rung_in and not ctr.get("cu"):
                if acc >= COUNTER_MAX:
                    ctr["ov"] = True
                else:
                    acc += 1
            ctr["cu"] = bool(rung_in)
        elif blk == "CTD":
            ctr["pre"] = clamp_counter(pv)
            if rung_in and not ctr.get("cd"):
                if acc <= COUNTER_MIN:
                    ctr["un"] = True
                else:
                    acc -= 1
            ctr["cd"] = bool(rung_in)
        elif blk == "RES":
            if rung_in:
                acc = 0
                ctr["ov"] = False
                ctr["un"] = False
        elif blk == "LOAD":
            if rung_in:
                acc = int(ctr.get("pre") or 0)
        ctr["acc"] = acc
        pre = int(ctr.get("pre") or 0)
        ctr["dn"] = (acc <= 0) if ctr.get("block") == "CTD" else (acc >= pre)
        if name not in self.forces:
            self.vars[name] = bool(ctr["dn"])


    def _eval_compare(self, el: dict[str, Any]) -> bool:
        """CCW/Studio-style compare box: TRUE when relation holds (power gating).

        LIM: Low (B) <= Test (A) <= High (C).  MEQ: (A & Mask B) == (Compare C & Mask B).
        """
        op = normalize_compare_op(el.get("op"))
        a = self.read_number(str(el.get("source_a") or ""))
        b = self.read_number(str(el.get("source_b") or ""))
        c = self.read_number(str(el.get("source_c") or ""))
        if op == "EQU":
            return a == b
        if op == "NEQ":
            return a != b
        if op == "GRT":
            return a > b
        if op == "LES":
            return a < b
        if op == "GEQ":
            return a >= b
        if op == "LEQ":
            return a <= b
        if op == "LIM":
            # Studio / Rockwell LIM: A=Test, B=Low, C=High.
            # Normal (Low <= High): Low <= Test <= High.
            # Inverted (Low > High): Test >= Low OR Test <= High (outside the gap).
            if b <= c:
                return b <= a <= c
            return a >= b or a <= c
        if op == "MEQ":
            # Studio MEQ: (Source & Mask) == (Compare & Mask)
            mask = to_dint(b)
            return (to_dint(a) & mask) == (to_dint(c) & mask)
        return False

    def _apply_math(self, el: dict[str, Any], energized: bool) -> None:
        """Execute math/MOV/bitwise/CPT when rung-in is true (ENO-style passthrough)."""
        if not energized:
            return
        op = normalize_math_op(el.get("op"))
        dest = self._resolve(str(el.get("dest") or ""))
        if not dest:
            return
        a = self.read_number(str(el.get("source_a") or ""))
        b = self.read_number(str(el.get("source_b") or ""))
        if op == "MOV":
            result = a
        elif op == "ADD":
            result = a + b
        elif op == "SUB":
            result = a - b
        elif op == "MUL":
            result = a * b
        elif op == "DIV":
            result = 0.0 if b == 0 else a / b
        elif op == "AND":
            result = float(to_dint(a) & to_dint(b))
        elif op == "OR":
            result = float(to_dint(a) | to_dint(b))
        elif op == "XOR":
            result = float(to_dint(a) ^ to_dint(b))
        elif op == "NOT":
            result = float(to_dint(~to_dint(a)))
        elif op == "CPT":
            expr = str(el.get("expression") or el.get("source_a") or "").strip()
            try:
                if cpt_expression_error(expr):
                    raise ValueError("invalid CPT")
                result = eval_cpt_expression(expr, self.read_number)
            except Exception:
                # v0.3.18 NEW-10: an empty / malformed CPT never writes a made-up value
                # (it used to write 0). The destination keeps its value; the UI also
                # refuses to scan while sim_blockers() reports the rung.
                return
        else:
            result = a
        # v0.3.12: undeclared math destinations default to DINT (UI programs).
        dtype = self.number_types.get(dest) or "DINT"
        if dest not in self.number_types:
            self.number_types[dest] = dtype
        self.numbers[dest] = coerce_numeric(result, dtype, op=op)

    def _scan_rung_list(
        self,
        rungs: list[dict[str, Any]],
        *,
        energized_paths: dict[str, bool],
        key_prefix: str = "",
    ) -> None:
        """Scan a list of rungs (Main or a called subroutine). Handles JSR / RET / SBR."""
        for rung in rungs or []:
            rid = str(rung.get("id") or "")
            path_rid = f"{key_prefix}{rid}" if key_prefix else rid
            elements = list(rung.get("elements") or [])
            if not elements:
                self.last_energized[path_rid] = False
                energized_paths[path_rid] = False
                continue

            power = True
            power_into_last_actuator: bool | None = None
            early_return = False
            for index, el in enumerate(elements):
                kind = (el.get("kind") or "").lower()
                key = f"{path_rid}|L|{index}"
                pin = power
                cond = power
                if kind == "contact":
                    cond = self._contact_conducts(el)
                    power = power and cond
                    self.last_contact_state[key] = power
                elif kind == "or":
                    cond = True
                    power = self._or_flow(el, key, power)
                elif kind == "coil":
                    self._apply_coil(el, power)
                    power_into_last_actuator = power
                elif kind == "timer":
                    name = self._resolve(str(el.get("var") or ""))
                    block = str(el.get("block") or "TON").upper()
                    if block not in {"TON", "TOF", "RTO"}:
                        block = "TON"
                    pt_ms = self._timer_preset_ms(el)
                    if name:
                        if name not in self.timers:
                            self.timers[name] = {
                                "block": block, "pt_ms": pt_ms, "acc_ms": 0, "q": False, "tt": False,
                            }
                        else:
                            if pt_ms or el.get("pt_tag"):
                                self.timers[name]["pt_ms"] = pt_ms
                            self.timers[name]["block"] = block
                        self._update_timer(name, block, power)
                    power_into_last_actuator = power
                elif kind == "counter":
                    name = self._resolve(str(el.get("var") or ""))
                    if name:
                        self._update_counter(name, str(el.get("block") or "CTU"), self._counter_preset(el), power)
                    power_into_last_actuator = power
                elif kind == "compare":
                    cond = self._eval_compare(el)
                    power = power and cond
                elif kind == "math":
                    self._apply_math(el, power)
                    power_into_last_actuator = power
                elif kind == "oneshot":
                    blk = normalize_oneshot_block(el.get("block"))
                    power = self._apply_oneshot(el, power)
                    if blk in ONESHOT_OUTPUT_BLOCKS:
                        power_into_last_actuator = power
                    cond = power
                elif kind == "sbr":
                    # Label only — documents the routine; power passes through.
                    cond = True
                elif kind == "jsr":
                    target = normalize_routine_name(el.get("target"))
                    cond = True
                    power_into_last_actuator = power
                    if power and target and target != "Main":
                        if target in self._call_stack:
                            # Educational: recursive JSR is a no-op (avoid loops).
                            cond = False
                        elif len(self._call_stack) >= JSR_MAX_DEPTH:
                            cond = False
                        elif target in self.routines:
                            self._call_stack.append(target)
                            try:
                                self._scan_rung_list(
                                    self.routines[target],
                                    energized_paths=energized_paths,
                                    key_prefix=f"{key}>",
                                )
                            finally:
                                self._call_stack.pop()
                elif kind == "ret":
                    power_into_last_actuator = power
                    if power:
                        early_return = True
                self._note_flow(key, pin, cond, power)
                if early_return:
                    break

            path_ok = (
                bool(power_into_last_actuator)
                if power_into_last_actuator is not None
                else bool(power)
            )
            self.last_energized[path_rid] = path_ok
            energized_paths[path_rid] = path_ok
            if early_return:
                return True
        return False

    def scan_rung(self, index: int) -> dict[str, Any]:
        """v0.3.20: execute one Main rung (and any routine it calls).

        Used by the rung-by-rung run: a pass through every rung equals one
        scan. Highlights of the other rungs are kept from their last
        evaluation. Result adds ``rung_index`` (rung just run) and
        ``next_rung`` (0 after the last rung or a RET)."""
        rungs = list(self.ladder.get("rungs") or [])
        if not rungs:
            self.rung_cursor = 0
            result = self._scan_result(dict(self.last_energized))
            result.update(rung_index=-1, next_rung=0)
            return result
        index = int(index) % len(rungs)
        for tag, value in self.forces.items():
            self.vars[tag] = bool(value)
        rid = str(rungs[index].get("id") or "")

        def _mine(key: str) -> bool:
            return key == rid or key.startswith(rid + "|")

        for table in (self.power_flow, self.last_contact_state, self.last_energized):
            for key in [k for k in table if _mine(k)]:
                del table[key]
        self._call_stack.clear()
        early = self._scan_rung_list([rungs[index]], energized_paths={})
        last = early or index == len(rungs) - 1
        if last:
            self.scan_count += 1
        self.rung_cursor = 0 if last else index + 1
        result = self._scan_result(dict(self.last_energized))
        result.update(rung_index=index, next_rung=self.rung_cursor)
        return result

    def _scan_result(self, energized_paths: dict[str, bool]) -> dict[str, Any]:
        return {
            "vars": {k: bool(v) for k, v in self.vars.items()},
            "numbers": {k: float(v) for k, v in self.numbers.items()},
            "forces": {k: bool(v) for k, v in self.forces.items()},
            "energized_paths": energized_paths,
            "contact_state": dict(self.last_contact_state),
            "power_flow": {k: dict(v) for k, v in self.power_flow.items()},
            "timers": deepcopy(self.timers),
            "counters": deepcopy(self.counters),
            "scan_count": self.scan_count,
            "cycle_ms": self.cycle_ms,
            "aliases": dict(self.aliases),
            "routines": sorted(self.routines.keys()),
        }

    def scan_once(self, forces: dict[str, bool] | None = None) -> dict[str, Any]:
        """One scan cycle. Optional forces merge into sticky force table for this call."""
        if forces:
            for tag, value in forces.items():
                self.set_force(str(tag), bool(value))

        # Apply forces into vars snapshot
        for tag, value in self.forces.items():
            self.vars[tag] = bool(value)

        self.last_contact_state.clear()
        self.last_energized.clear()
        self.power_flow.clear()
        self._call_stack.clear()
        energized_paths: dict[str, bool] = {}

        self._scan_rung_list(list(self.ladder.get("rungs") or []), energized_paths=energized_paths)

        self.scan_count += 1
        self.rung_cursor = 0
        return self._scan_result(energized_paths)

    def input_tags(self) -> list[str]:
        return sorted(self._input_tags)

    def output_tags(self) -> list[str]:
        return sorted(self._output_tags)

    def active_tags(self) -> set[str]:
        """Tags that are logically TRUE this scan (for ladder highlight)."""
        active = {tag for tag, value in self.vars.items() if value}
        for name, ctr in self.counters.items():
            if ctr.get("dn"):
                active.update({name, f"{name}.DN"})
        for name, tmr in self.timers.items():
            if tmr.get("q"):
                active.update({name, f"{name}.DN"})
            if tmr.get("tt"):
                active.add(f"{name}.TT")
        return active


def program_rung_flow_keys(rung: dict[str, Any], *, index: int = 1) -> dict[str, Any]:
    """Map a classic program rung's drawn parts to scan ``power_flow`` keys.

    Mirrors ``ladder_ir.program_rung_to_elements`` ordering so the classic
    (parallel / series / timer / counter / coil) canvas drawer can light the
    same instructions the scan evaluated. Rungs with ``elements`` use the
    element index directly (``"{rid}|L|{i}"``).
    Returns ``{"rid", "parallel": {(bi, j): key}, "series": {k: key},
    "timer", "counter", "coil", "or"}`` (missing parts -> None).
    """
    rid = str(rung.get("id") or index)
    out: dict[str, Any] = {
        "rid": rid, "parallel": {}, "series": {}, "timer": None, "counter": None, "coil": None, "or": None,
    }
    i = 0
    parallel = [
        [c for c in (branch or []) if isinstance(c, dict) and (c.get("tag") or "").strip()]
        for branch in (rung.get("parallel") or [])
    ]
    parallel = [b for b in parallel if b]
    if len(parallel) == 1:
        for j, _c in enumerate(parallel[0]):
            out["parallel"][(0, j)] = f"{rid}|L|{i}"
            i += 1
    elif len(parallel) > 1:
        or_key = f"{rid}|L|{i}"
        out["or"] = or_key
        for bi, branch in enumerate(parallel):
            for j, _c in enumerate(branch):
                out["parallel"][(bi, j)] = f"{or_key}|b{bi}|{j}"
        i += 1
    for mc in rung.get("mid_coils") or []:
        if isinstance(mc, dict) and (mc.get("tag") or mc.get("var") or "").strip():
            i += 1
    k = 0
    for c in rung.get("series") or []:
        if (c.get("tag") or "").strip():
            out["series"][k] = f"{rid}|L|{i}"
            i += 1
            k += 1
    timer = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
    if timer and (timer.get("tag") or timer.get("var") or "").strip():
        out["timer"] = f"{rid}|L|{i}"
        i += 1
    counter = rung.get("counter") if isinstance(rung.get("counter"), dict) else None
    if counter and (counter.get("tag") or counter.get("var") or "").strip():
        out["counter"] = f"{rid}|L|{i}"
        i += 1
    if (rung.get("coil_tag") or "").strip():
        out["coil"] = f"{rid}|L|{i}"
    return out


def scan_once(
    ladder_or_program: dict[str, Any],
    forces: dict[str, bool] | None = None,
    *,
    from_program: bool = False,
    project_name: str = "",
    devices: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Functional helper matching the brief API: scan_once(forces) → result."""
    if from_program or (
        isinstance(ladder_or_program, dict)
        and "rungs" in ladder_or_program
        and ladder_or_program.get("format") != "cabinet-studio-ladder"
        and "answers" in ladder_or_program
    ):
        sim = ScanSimulator.from_program(
            ladder_or_program, project_name=project_name, devices=devices
        )
    else:
        sim = ScanSimulator(ladder_or_program)
    return sim.scan_once(forces)


def sim_blockers(program: Any, *, project_name: str = "", devices: list[dict[str, str]] | None = None) -> list[str]:
    """v0.3.17 (Raddus): reasons the educational simulator must NOT run.

    * any CPT whose expression is empty, malformed or divides by a constant zero (e.g.
      imported verbatim from a PLCopen file) — the simulator would otherwise make up a value;
    * v0.3.18 NEW-9: a timer PT / counter PV read from a tag that no instruction in this
      program writes (the simulator cannot know its value and must not assume 0);
    * v0.3.19: an empty compare / math operand, or a JSR to a routine that does not exist.

    Each message names the rung (number, routine and instruction). v0.3.18 (Deflector
    P3-2): fails CLOSED — if the program cannot be analysed, that itself blocks the sim."""
    from cabinet_studio.services.ladder_ir import cpt_expression_error, program_to_ladder_ir

    try:
        if isinstance(program, dict) and program.get("format") and "rungs" in program and "variables" in program:
            ir = program
        else:
            ir = program_to_ladder_ir(program, project_name=project_name, devices=devices)
    except Exception as exc:
        return [
            f"the program could not be analysed for simulation ({type(exc).__name__}: {exc}); "
            "simulation will not run until Verify (F7) is clean"
        ]
    out: list[str] = []
    try:
        routines = ir.get("routines") if isinstance(ir.get("routines"), dict) else {}
        routine_names = {normalize_routine_name(n) for n in (routines or {})}
        bodies: list[tuple[str, list[dict[str, Any]]]] = [
            (f"Rung {i}", list(r.get("elements") or []))
            for i, r in enumerate(ir.get("rungs") or [], start=1)
        ]
        for name, rungs in (routines or {}).items():
            for i, rung in enumerate(rungs or [], start=1):
                if isinstance(rung, dict):
                    bodies.append((f"{name} rung {i}", list(rung.get("elements") or [])))
        written: set[str] = set()

        def collect(items: list[dict[str, Any]]) -> None:
            for el in items or []:
                k = str(el.get("kind") or "").lower()
                if k == "or":
                    for b in el.get("branches") or []:
                        collect(list(b or []))
                elif k == "math" and str(el.get("dest") or "").strip():
                    written.add(str(el.get("dest")).strip())

        for _w, els in bodies:
            collect(els)

        def walk(items: list[dict[str, Any]], where: str) -> None:
            for el in items or []:
                k = str(el.get("kind") or "").lower()
                if k == "or":
                    for b in el.get("branches") or []:
                        walk(list(b or []), where)
                elif k == "math" and str(el.get("op") or "").upper() == "CPT":
                    err = cpt_expression_error(el.get("expression") or el.get("source_a"))
                    if err:
                        out.append(
                            f"{where} (CPT → {el.get('dest') or '?'}): {err}. Fix it by hand (Verify F7); "
                            "simulation will not run until it is filled in."
                        )
                elif k in {"compare", "math"}:
                    # v0.3.19 (Audit NEW-17): an empty operand would read as 0 in the sim.
                    op = str(el.get("op") or "").upper()
                    if k == "compare":
                        sides = ["source_a", "source_b"] + (["source_c"] if op in COMPARE_THREE_OPS else [])
                    else:
                        sides = ["source_a"] if op in {"MOV", "NOT"} else ["source_a", "source_b"]
                    empty = [s for s in sides if not str(el.get(s) or "").strip()]
                    if empty:
                        names = ", ".join({"source_a": "A", "source_b": "B", "source_c": "C"}[s] for s in empty)
                        out.append(
                            f"{where} ({op or k.upper()}): operand {names} is empty, and the simulator "
                            "will not assume 0. Fill it in (Verify F7); simulation will not run until then."
                        )
                elif k == "jsr":
                    target = normalize_routine_name(el.get("target"))
                    if target and target != "Main" and target not in routine_names:
                        out.append(
                            f"{where} (JSR {target}): there is no routine named {target}, so the call "
                            "would do nothing. Create the routine or fix the name (Verify F7); "
                            "simulation will not run until then."
                        )
                elif k in {"timer", "counter"}:
                    tag = str(el.get("pt_tag" if k == "timer" else "pv_tag") or "").strip()
                    if not tag:
                        continue
                    base, member = split_member(tag)
                    if member in {"PRE", "ACC"}:
                        continue
                    if tag not in written:
                        what = "PT (preset time)" if k == "timer" else "PV (preset)"
                        out.append(
                            f"{where} ({str(el.get('block') or k).upper()} {el.get('var') or '?'}): {what} is read "
                            f"from tag {tag}, but no instruction in this program writes {tag}, so the "
                            "simulator cannot know its value (it will not assume 0). Add a MOV to "
                            f"{tag} or type a fixed preset; simulation will not run until then."
                        )

        for where, els in bodies:
            walk(els, where)
    except Exception as exc:
        return [
            f"the program could not be analysed for simulation ({type(exc).__name__}: {exc}); "
            "simulation will not run until Verify (F7) is clean"
        ]
    return out

