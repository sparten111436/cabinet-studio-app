"""Run an HMI design against the ladder scan simulator (SIMULATION - not a live PLC).

HMI_ bits are written as PLC program variables (memory bits the ladder reads next scan), never as forced
physical inputs. Safety tags (E-stop, light curtain, guard, safety relay) are never written.
"""

from __future__ import annotations

from typing import Callable

from cabinet_studio.services.hmi_design import (
    HmiDesign,
    HmiObject,
    is_graphic,
    project_tags,
    write_refusal,
)

BANNER = "SIMULATION - not a live PLC"
FILL_RATE = 0.02


class HmiRuntime:
    """Live HMI objects. ``sim_provider()`` -> (sim, running) shares the Programming page simulator;
    when it is not running (or absent) this runtime scans its own copy every ``tick``."""

    def __init__(self, project, design: HmiDesign, sim=None,
                 sim_provider: Callable[[], tuple[object, bool]] | None = None):
        self.project = project
        self.design = design
        self._provider = sim_provider
        self._own = sim
        self._tags = {t["tag"]: t for t in project_tags(project)}
        self.phase = 0
        self.levels: dict[str, float] = {}
        self.log: list[str] = []

    # ---------------------------------------------------------------- simulator
    @property
    def sim(self):
        shared = self._shared()
        if shared is not None:
            return shared[0]
        if self._own is None:
            from cabinet_studio.services.ladder_sim import ScanSimulator
            from cabinet_studio.services.programming import cabinet_device_tags

            self._own = ScanSimulator.from_program(self.project.program or {}, project_name=self.project.name,
                                                   devices=cabinet_device_tags(self.project), cycle_ms=100)
        return self._own

    def _shared(self):
        if self._provider is None:
            return None
        try:
            got = self._provider()
        except Exception:  # noqa: BLE001 - a closed Programming page just means "use our own"
            return None
        return got if got and got[0] is not None else None

    @property
    def shared(self) -> bool:
        return self._shared() is not None

    def tick(self) -> None:
        """One ~100 ms step: scan (unless the Programming page is already running the same sim), advance animation."""
        shared = self._shared()
        if shared is None or not shared[1]:
            self.sim.scan_once()
        self.phase += 1
        for screen in self.design.screens:
            for obj in screen.objects:
                if obj.anim == "fill" and obj.tag:
                    lvl = self.levels.get(obj.id, 0.0)
                    self.levels[obj.id] = min(1.0, lvl + FILL_RATE) if self.read_bool(obj.tags[0]) \
                        else max(0.0, lvl - FILL_RATE / 2)

    # ---------------------------------------------------------------- writes
    def _refuse(self, tag: str) -> str:
        why = write_refusal(tag, self.project, self._tags)
        if why:
            self.log.append(why)
        return why

    def write_bool(self, tag: str, value: bool) -> str:
        """Write a BOOL as a program variable. Returns '' or the refusal text."""
        tag = tag.strip()
        if not tag:
            return "No tag on this object."
        why = self._refuse(tag)
        if why:
            return why
        sim = self.sim
        name = sim._resolve(tag)
        if name in sim.forces:
            return f"{tag} is forced on the Programming page; clear the force first."
        sim.vars[name] = bool(value)
        return ""

    def press(self, obj: HmiObject) -> str:
        if obj.kind == "momentary":
            return self.write_bool(obj.tag, True)
        if obj.kind == "toggle":
            return self.write_bool(obj.tag, not self.read_bool(obj.tag))
        return ""

    def release(self, obj: HmiObject) -> str:
        return self.write_bool(obj.tag, False) if obj.kind == "momentary" else ""

    def enter_number(self, obj: HmiObject, value) -> str:
        if obj.kind != "numeric_entry" or not obj.tag:
            return "Only a numeric entry with a tag can send a number."
        why = self._refuse(obj.tag)
        if why:
            return why
        try:
            number = float(value)
        except (TypeError, ValueError):
            return f"{value!r} is not a number."
        self.sim.set_number(obj.tag, number)
        return ""

    # ---------------------------------------------------------------- reads
    def read_bool(self, tag: str) -> bool:
        tag = tag.strip()
        if not tag:
            return False
        try:
            return bool(self.sim.read(tag))
        except Exception:  # noqa: BLE001 - unknown tag reads as OFF
            return False

    def read_num(self, tag: str) -> float:
        tag = tag.strip()
        if not tag:
            return 0.0
        try:
            return float(self.sim.read_number(tag) or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def anim_state(self, obj: HmiObject) -> dict:
        """State dict for hmi_symbols.symbol_shapes (graphics) or {'on','value'} for plain objects."""
        tags = obj.tags
        first = tags[0] if tags else ""
        on = self.read_bool(first)
        state = {"on": on, "phase": self.phase, "fault": False, "value": 0.0, "level": 0.0}
        anim = obj.anim or "none"
        if not is_graphic(obj.kind):
            state["value"] = self.read_num(first)
            return state
        if anim == "none":
            state["on"] = False
        elif anim in ("level", "needle", "bar"):
            value = max(0.0, min(100.0, self.read_num(first)))
            state.update(value=value, level=value / 100.0, on=value > 0)
        elif anim == "fill":
            state["level"] = self.levels.get(obj.id, 0.0)
        elif anim == "fault":
            state.update(fault=on, on=on)
        elif anim == "lights":
            tiers = [self.read_bool(t) for t in obj.tag.split(",")[:3]]
            state["tiers"] = tuple(tiers + [False] * (3 - len(tiers)))
        return state
