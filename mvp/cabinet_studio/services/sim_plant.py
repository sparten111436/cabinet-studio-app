"""Pretend machine for Normal run (v0.3.28): the field reacts to the program like a healthy machine.

* Feedback inputs follow the output they belong to after a short travel time:
  Motor_Run ON -> Motor_Running / Motor_Aux ON 1 s later; Clamp_Sol ON -> Clamp_Extended ON,
  Clamp_Retracted OFF. Matching is by name stem, so it works on any program.
* Part sensors (eyes, prox, part present...) see a part pass every few seconds while a
  conveyor / motor output runs (or all the time if the program has none).

Safety inputs (E-stop, light curtain, guard) are never touched here - the user operates
them to test what the program does. Educational only; the software is never the safety function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FEEDBACK_SUFFIX = re.compile(
    r"_?(FBK|FB|FEEDBACK|AUX|RUNNING|RUN_FB|IS_ON|ON_FB|CONFIRM|PROVEN|EXTENDED|EXT|ADVANCED|CLOSED|OPENED|"
    r"OPEN|UP|DOWN|ENGAGED|AT_POS|IN_POS|RETRACTED|RET|RETURNED|HOME|RELEASED|LS|PX|PROX|SW)$",
    re.I,
)
_INVERT = re.compile(r"(RETRACTED|RET|RETURNED|HOME|RELEASED)$", re.I)
_OUTPUT_SUFFIX = re.compile(
    r"_?(RUN|CMD|OUT|SOL|SOLENOID|VALVE|VLV|EXTEND|ADVANCE|CLOSE|OPEN|ON|START|STARTER|CONTACTOR|COIL|M|K|"
    r"DRIVE|ENABLE)$",
    re.I,
)
_SAFETY = re.compile(r"E_?STOP|ES\d|(^|_)ES($|_)|EMERG|CURTAIN|LIGHT_?C|(^|_)LC\d*($|_)|GUARD|DOOR|GATE|SAFE|"
                     r"(^|_)SR\d", re.I)


def is_safety_tag(tag: str) -> bool:
    """E-stop, light curtain, guard, door and safety-relay inputs: only the user operates these."""
    return bool(_SAFETY.search(str(tag)))
_PART = re.compile(r"EYE|PHOTO|PE\d|PROX|PART|PRESENT|BOTTLE|(^|_)BOX|IN_PLACE|ARRIV|DETECT|PRODUCT", re.I)
_MOTION = re.compile(r"CONV|MOTOR|(^|_)M\d|DRIVE|VFD|FEED|INDEX|BELT|(^|_)RUN($|_)|_RUN$|PUMP", re.I)


def _stem(tag: str, pattern: re.Pattern) -> str:
    stem = tag
    for _ in range(2):
        new = pattern.sub("", stem)
        if new == stem or not new:
            break
        stem = new
    return re.sub(r"[^A-Z0-9]", "", stem.upper())


@dataclass
class PlantModel:
    input_tags: list[str]
    output_tags: list[str]
    delay_s: float = 1.0
    part_every_s: float = 4.0
    part_on_s: float = 1.2
    links: list[tuple[str, str, bool]] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    motion: list[str] = field(default_factory=list)
    _pending: dict[str, tuple[bool, float]] = field(default_factory=dict)
    _state: dict[str, bool] = field(default_factory=dict)
    _part_t0: float | None = None

    def __post_init__(self) -> None:
        outs = {}
        for out in self.output_tags:
            if "." in out:
                continue
            outs.setdefault(_stem(out, _OUTPUT_SUFFIX), out)
        for tag in self.input_tags:
            if "." in tag or _SAFETY.search(tag) or not _FEEDBACK_SUFFIX.search(tag):
                continue
            out = outs.get(_stem(tag, _FEEDBACK_SUFFIX))
            if out:
                self.links.append((tag, out, bool(_INVERT.search(tag))))
        linked = {t for t, _o, _i in self.links}
        self.parts = [t for t in self.input_tags
                      if t not in linked and "." not in t and not _SAFETY.search(t) and _PART.search(t)]
        self.motion = [o for o in self.output_tags if "." not in o and _MOTION.search(o)]

    @property
    def handled(self) -> set[str]:
        return {t for t, _o, _i in self.links} | set(self.parts)

    def describe(self) -> list[str]:
        lines = [f"{t} follows {o}{' (inverted)' if inv else ''} after {self.delay_s:g} s"
                 for t, o, inv in self.links]
        if self.parts:
            who = ", ".join(self.motion) if self.motion else "the machine"
            lines.append(f"{', '.join(self.parts)} see a part every {self.part_every_s:g} s while {who} runs")
        return lines

    def step(self, now: float, read) -> list[tuple[str, bool, str]]:
        """Changes to apply now: (input tag, value, plain-English reason)."""
        out: list[tuple[str, bool, str]] = []
        for tag, src, inv in self.links:
            want = bool(read(src)) != inv
            have = self._state.get(tag)
            if have is None:
                self._state[tag] = want
                out.append((tag, want, f"{tag} starts {'ON' if want else 'OFF'} ({src} is {'ON' if read(src) else 'OFF'})"))
                continue
            pending = self._pending.get(tag)
            if want == have:
                self._pending.pop(tag, None)
            elif pending is None or pending[0] != want:
                self._pending[tag] = (want, now + self.delay_s)
            elif now >= pending[1]:
                self._pending.pop(tag, None)
                self._state[tag] = want
                out.append((tag, want, f"{src} is {'ON' if read(src) else 'OFF'} -> {tag} turns {'ON' if want else 'OFF'}"))
        if self.parts:
            moving = any(read(o) for o in self.motion) if self.motion else True
            if not moving:
                self._part_t0 = None
                want = False
            else:
                if self._part_t0 is None:
                    self._part_t0 = now
                phase = (now - self._part_t0) % self.part_every_s
                want = self.part_every_s - self.part_on_s <= phase
            for tag in self.parts:
                if self._state.get(tag) != want:
                    self._state[tag] = want
                    out.append((tag, want, f"a part {'arrives at' if want else 'leaves'} {tag}"))
        return out
