"""Instruction palette (Studio 5000-style tabs) above the ladder.

Each button only sets the rung-editor fields and runs an existing registered
``rung.*`` command, so no new element types exist and the allow-listed
editor / verify / PLCopen paths stay the single source of truth.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import customtkinter as ctk

from cabinet_studio.services.ladder_tools import verify_program
from cabinet_studio.services.programming import cabinet_device_tags
from cabinet_studio.ui.hover_tip import attach as attach_tip
from cabinet_studio.ui.theme import BLUE, BLUE_HOVER, BORDER, HOVER, MUTED, PANEL, TEXT


@dataclass(frozen=True)
class PaletteItem:
    mnemonic: str
    tip: str
    command: str
    setup: dict = field(default_factory=dict)


def _cmp(op: str, tip: str) -> PaletteItem:
    return PaletteItem(op, tip, "rung.add_compare", {"field:compare_op": op})


def _math(op: str, tip: str, command: str = "rung.add_math") -> PaletteItem:
    return PaletteItem(op, tip, command, {"field:math_op": op})


PALETTE_GROUPS: list[tuple[str, list[PaletteItem]]] = [
    ("Bit", [
        PaletteItem("XIC", "Examine if closed: series contact on the selected rung", "rung.add_series_contact",
                    {"nc": "NO"}),
        PaletteItem("XIO", "Examine if open: NC series contact on the selected rung", "rung.add_series_contact",
                    {"nc": "NC"}),
        PaletteItem("OTE", "Output energize: new rung contact → coil", "rung.add", {"nc": "NO"}),
        PaletteItem("OTL", "Output latch (set)", "rung.add_otl", {"nc": "NO"}),
        PaletteItem("OTU", "Output unlatch (reset)", "rung.add_otu", {"nc": "NO"}),
        PaletteItem("ONS", "One-shot", "rung.add_oneshot", {"oneshot": "ONS"}),
        PaletteItem("OSR", "One-shot rising", "rung.add_oneshot", {"oneshot": "OSR"}),
        PaletteItem("OSF", "One-shot falling", "rung.add_oneshot", {"oneshot": "OSF"}),
        PaletteItem("Branch", "OR branch (nested OR rung)", "rung.add_nested_or", {"nc": "NO"}),
    ]),
    ("Timer/Counter", [
        PaletteItem("TON", "Timer on delay", "rung.add_timer", {"timer": "TON"}),
        PaletteItem("TOF", "Timer off delay", "rung.add_timer", {"timer": "TOF"}),
        PaletteItem("RTO", "Retentive timer on", "rung.add_timer", {"timer": "RTO"}),
        PaletteItem("CTU", "Count up", "rung.add_counter", {"counter": "CTU"}),
        PaletteItem("CTD", "Count down", "rung.add_counter", {"counter": "CTD"}),
        PaletteItem("RES", "Reset counter", "rung.add_counter", {"counter": "RES"}),
    ]),
    ("Compare", [
        _cmp("EQU", "Equal"), _cmp("NEQ", "Not equal"), _cmp("LES", "Less than"), _cmp("LEQ", "Less or equal"),
        _cmp("GRT", "Greater than"), _cmp("GEQ", "Greater or equal"),
        PaletteItem("LIM", "Limit test (A = test, B = low, C = high)", "rung.add_lim"),
        PaletteItem("MEQ", "Masked equal (A = source, B = mask, C = compare)", "rung.add_meq"),
    ]),
    ("Compute/Math", [
        _math("ADD", "Add A + B → dest"), _math("SUB", "Subtract A − B → dest"),
        _math("MUL", "Multiply A × B → dest"), _math("DIV", "Divide A ÷ B → dest"),
    ]),
    ("Move/Logical", [
        _math("MOV", "Move A → dest"),
        _math("AND", "Bitwise AND → dest", "rung.add_bitwise"), _math("OR", "Bitwise OR → dest", "rung.add_bitwise"),
        _math("XOR", "Bitwise XOR → dest", "rung.add_bitwise"), _math("NOT", "Bitwise NOT → dest", "rung.add_bitwise"),
    ]),
    ("Program Control", [
        PaletteItem("JSR", "Jump to subroutine (creates it if missing)", "rung.add_jsr"),
        PaletteItem("SBR", "Subroutine routine (SBR … RET)", "rung.add_sbr"),
        PaletteItem("RET", "Return from routine", "rung.add_ret"),
        PaletteItem("AOI", "Insert an AOI template (rung expansion)", "rung.add_aoi"),
    ]),
]
ITEMS: dict[str, PaletteItem] = {i.mnemonic: i for _g, items in PALETTE_GROUPS for i in items}

# Hover help: what the instruction does, when to use it, and an everyday example.
HELP: dict[str, tuple[str, str]] = {
    "XIC": ("Examine If Closed (normally open contact)",
            "Lets power pass when its tag is ON (1). Use it for 'only if this is on': a start button, a sensor "
            "seeing a part, a motor running feedback.\nExample: XIC Start_PB → the rung can turn on when Start is "
            "pressed.\nAdds a contact in series on the selected rung (the Contact box picks the tag)."),
    "XIO": ("Examine If Open (normally closed contact)",
            "Lets power pass when its tag is OFF (0). Use it for 'only if this is NOT on': stop buttons wired NC, a "
            "fault, a guard that must be closed.\nExample: XIO Fault → the motor may run only while there is no "
            "fault.\nAdds an NC contact in series on the selected rung."),
    "OTE": ("Output Energize (coil)",
            "Turns its tag ON while the rung has power and OFF as soon as it loses power. Use it for motors, "
            "lights, valves.\nExample: Start → OTE Motor_Run.\nCreates a NEW rung: Contact box → Coil box."),
    "OTL": ("Output Latch (set)",
            "Turns its tag ON and LEAVES it on, even after the rung loses power. Only an OTU with the same tag "
            "turns it off.\nUse for 'remember this happened': a fault, a cycle started.\nPair every OTL with an "
            "OTU."),
    "OTU": ("Output Unlatch (reset)",
            "Turns its tag OFF when the rung has power. It is the 'off switch' for a tag set with OTL.\nExample: "
            "Reset_PB → OTU Fault."),
    "ONS": ("One-Shot",
            "Passes power for exactly ONE scan when the rung goes from off to on, then blocks until the rung goes "
            "off again.\nUse so holding a button counts or triggers only once.\nNeeds a storage bit "
            "(filled in for you)."),
    "OSR": ("One-Shot Rising",
            "Turns its output bit ON for one scan when the rung turns ON. Same idea as ONS but writes the pulse "
            "to a separate tag you can use elsewhere."),
    "OSF": ("One-Shot Falling",
            "Turns its output bit ON for one scan when the rung turns OFF (on → off).\nUse to do something once "
            "when a button is released or a sensor stops seeing a part."),
    "Branch": ("Branch (OR)",
               "Adds a parallel path so EITHER path can power the rung.\nClassic use: the seal-in — Start OR "
               "Motor_Run keeps the motor on after you let go of Start.\nAdds an OR branch on the selected rung."),
    "TON": ("Timer On-Delay",
            "Starts counting when the rung turns on; its .DN (done) bit turns on after the preset time. If the "
            "rung turns off early, it resets to zero.\nExample: wait 5 s after Start before opening a valve.\n"
            "Preset is in milliseconds (5000 = 5 s)."),
    "TOF": ("Timer Off-Delay",
            "Its .DN bit is ON while the rung is on and STAYS on for the preset time after the rung turns off.\n"
            "Example: keep a cooling fan running 30 s after the motor stops."),
    "RTO": ("Retentive Timer On",
            "Like TON but keeps its time when the rung turns off; it continues where it left off. Only a RES "
            "clears it.\nExample: total run hours before maintenance."),
    "CTU": ("Count Up",
            "Adds 1 each time the rung goes from off to on. Its .DN bit turns on when the count reaches the "
            "preset.\nExample: count 12 parts into a box."),
    "CTD": ("Count Down",
            "Subtracts 1 each time the rung goes from off to on.\nExample: parts remaining in a batch."),
    "RES": ("Reset",
            "Sets a timer or counter back to zero (and clears .DN) while the rung has power.\nExample: Reset_PB → "
            "RES Part_Count."),
    "EQU": ("Equal", "Passes power when A = B.\nExample: Recipe = 3."),
    "NEQ": ("Not Equal", "Passes power when A ≠ B."),
    "LES": ("Less Than", "Passes power when A < B.\nExample: Tank_Level < 20 → start the fill pump."),
    "LEQ": ("Less Or Equal", "Passes power when A ≤ B."),
    "GRT": ("Greater Than", "Passes power when A > B.\nExample: Temperature > 80 → turn on the fan."),
    "GEQ": ("Greater Or Equal", "Passes power when A ≥ B."),
    "LIM": ("Limit Test", "Passes power when the test value is between the low and high limits.\nExample: "
                          "speed between 100 and 1800 rpm."),
    "MEQ": ("Masked Equal", "Compares only the bits allowed by the mask.\nExample: check just the low 4 bits of "
                            "a status word."),
    "ADD": ("Add", "Dest = A + B while the rung has power."),
    "SUB": ("Subtract", "Dest = A − B while the rung has power."),
    "MUL": ("Multiply", "Dest = A × B while the rung has power.\nExample: scale a count to inches."),
    "DIV": ("Divide", "Dest = A ÷ B while the rung has power. Dividing by zero is a fault — guard B first."),
    "MOV": ("Move", "Copies A into Dest while the rung has power.\nExample: load a recipe speed into the drive "
                    "setpoint."),
    "AND": ("Bitwise AND", "Dest = A AND B, bit by bit. Used to pick out bits with a mask."),
    "OR": ("Bitwise OR", "Dest = A OR B, bit by bit. Used to set bits."),
    "XOR": ("Bitwise XOR", "Dest = A XOR B, bit by bit. Shows which bits are different."),
    "NOT": ("Bitwise NOT", "Dest = every bit of A flipped."),
    "JSR": ("Jump to Subroutine", "Runs another routine and comes back. Creates the routine if it does not "
                                  "exist.\nUse to split a big program into sections (Conveyor, Alarms…)."),
    "SBR": ("Subroutine", "Creates a new routine (SBR … RET) that a JSR can call."),
    "RET": ("Return", "Ends a subroutine and goes back to the JSR that called it."),
    "AOI": ("Add-On Instruction template", "Inserts a ready-made block of rungs (for example a motor starter "
                                           "with seal-in and fault) that you can then edit."),
}


def _program_sig(program: dict) -> str:
    return json.dumps({"rungs": program.get("rungs"), "routines": program.get("routines")}, sort_keys=True,
                      default=str)


def _used_names(program: dict) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", _program_sig(program)))


def _next_free(base: str, used: set[str]) -> str:
    m = re.match(r"^(.*?)(\d+)$", base)
    stem, n = (m.group(1), int(m.group(2))) if m else (base, 1)
    while f"{stem}{n}" in used:
        n += 1
    return f"{stem}{n}"


class InstructionPalette(ctk.CTkFrame):
    def __init__(self, master, viewer) -> None:
        super().__init__(master, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
        self.viewer = viewer
        fonts = viewer.fonts
        self.buttons: dict[str, ctk.CTkButton] = {}
        self._groups = [g for g, _ in PALETTE_GROUPS]
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=6, pady=(4, 0))
        ctk.CTkLabel(top, text="INSTRUCTIONS", font=fonts.tiny, text_color=MUTED).pack(side="left", padx=(2, 8))
        self.tabs = ctk.CTkSegmentedButton(
            top, values=self._groups, command=self.show_group, font=fonts.tiny, height=24,
            selected_color=BLUE, selected_hover_color=BLUE_HOVER, unselected_hover_color=HOVER, text_color=TEXT,
        )
        self.tabs.pack(side="left")
        self.result = ctk.CTkLabel(top, text="", font=fonts.tiny, text_color=MUTED, anchor="w")
        self.result.pack(side="left", fill="x", expand=True, padx=10)
        self.row = ctk.CTkFrame(self, fg_color="transparent", height=34)
        self.row.pack(fill="x", padx=6, pady=(2, 4))
        self._frames: dict[str, ctk.CTkFrame] = {}
        for group, items in PALETTE_GROUPS:
            frame = ctk.CTkFrame(self.row, fg_color="transparent")
            self._frames[group] = frame
            for item in items:
                btn = ctk.CTkButton(
                    frame, text=item.mnemonic, width=max(48, 9 * len(item.mnemonic) + 16), height=26,
                    font=fonts.tiny, fg_color=("#e8ecf4", "#22283a"), hover_color=HOVER, text_color=TEXT,
                    border_width=1, border_color=BORDER, corner_radius=3,
                    command=lambda m=item.mnemonic: self.insert(m),
                )
                btn._cs_palette = item.mnemonic
                title, text = HELP.get(item.mnemonic, (item.mnemonic, item.tip))
                attach_tip(btn, text, f"{item.mnemonic} — {title}")
                btn.pack(side="left", padx=2)
                self.buttons[item.mnemonic] = btn
        self.show_group(self._groups[0])

    def show_group(self, group: str) -> None:
        if group not in self._frames:
            return
        for frame in self._frames.values():
            frame.pack_forget()
        self._frames[group].pack(side="left", fill="x")
        self.tabs.set(group)
        self.current_group = group

    def _prepare(self, item: PaletteItem) -> None:
        v = self.viewer
        choices = [t for t in v._tag_choices() if t and not t.startswith("(")]
        if not v._picked(v.contact_var) and choices:
            v.contact_var.set(choices[0])
        if not v._picked(v.coil_var) and choices:
            v.coil_var.set(choices[1] if len(choices) > 1 else choices[0])
        used = _used_names(v.program)
        fields = v._rung_field_vars

        def bump(name: str, default: str) -> None:
            current = fields[name].get().strip() or default
            fields[name].set(_next_free(current, used) if current in used else current)

        if "timer" in item.setup:
            bump("timer_tag", "T1")
        if item.setup.get("counter") in {"CTU", "CTD"}:
            bump("counter_tag", "C1")
        if "oneshot" in item.setup:
            bump("oneshot_storage", "OS1")
            bump("oneshot_output", "OS1_Pulse")
        if item.command == "rung.add_sbr":
            routines = set(v.program.get("routines") or {})
            name = fields["sbr_name"].get().strip() or "Sub1"
            fields["sbr_name"].set(_next_free(name, routines) if name in routines else name)
        for key, value in item.setup.items():
            if key == "nc":
                v.nc_var.set(value)
            elif key == "timer":
                v.timer_block_var.set(value)
            elif key == "counter":
                v.counter_block_var.set(value)
            elif key == "oneshot":
                v.oneshot_block_var.set(value)
            elif key.startswith("field:"):
                fields[key[6:]].set(value)

    def insert(self, mnemonic: str) -> bool:
        """Insert one instruction through the existing editor path, then verify. True if the program changed."""
        v = self.viewer
        item = ITEMS[mnemonic]
        self._prepare(item)
        before = _program_sig(v.program)
        v.invoke_command(item.command)
        changed = _program_sig(v.program) != before
        if changed:
            issues = verify_program(v.program, cabinet_device_tags(v.project))
            errors = sum(1 for i in issues if i.get("severity") == "error")
            text = f"{mnemonic} inserted · verify: {errors} error{'s' if errors != 1 else ''}"
        else:
            text = f"{mnemonic}: {v.status.cget('text')}"
        self.last_result = (mnemonic, changed)
        try:
            self.result.configure(text=text)
        except Exception:
            pass
        return changed
