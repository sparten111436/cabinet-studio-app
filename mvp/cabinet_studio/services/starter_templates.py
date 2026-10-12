"""Starter cabinets (v0.3.35): complete starting points for a new cabinet.

Each template is a device list (real catalog ids from the starter library), interview
answers, a working ladder program, PLC I/O addresses and (where it makes sense) an HMI.
Devices go through the same path as New build with AI (suggest_device ->
apply_recommendations -> wiring assist), so wire numbers, landings and the enclosure
are filled exactly like an AI build. A maker swap uses the equivalent part from that
maker when the library has one, otherwise the Allen-Bradley (or generic) part stays.

Design aid only. E-stop, light curtain and two-hand functions must be hardwired or use
rated safety relays (NFPA 79 / ISO 13849). The software is never the safety function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.models.schema import Library
from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE
from cabinet_studio.services.layouts import new_blank_project, new_id

MAKERS = ("Allen-Bradley", "Siemens", "Omron")
SAFETY_NOTE = (
    SAFETY_DESIGN_AID_NOTE + ". E-stop and safety functions must be hardwired or use rated safety relays "
    "(NFPA 79 / ISO 13849). The software is never the safety function."
)

# Allen-Bradley part -> same job from another maker (only parts that exist in the library).
MAKER_EQUIV: dict[str, dict[str, str]] = {
    "ab-compactlogix-5380": {"Siemens": "siemens-s7-1200-1214c", "Omron": "omron-nx1p2"},
    "ab-micro850": {"Siemens": "siemens-s7-1200-1214c", "Omron": "omron-cp2e-n30"},
    "ab-5069-ib16": {"Siemens": "siemens-sm1221-di16", "Omron": "omron-nx-id5342"},
    "ab-5069-ob16": {"Siemens": "siemens-sm1222-dq16", "Omron": "omron-nx-od5256"},
    "ab-1606-xls": {"Siemens": "siemens-sitop", "Omron": "omron-s8vk-240"},
    "ab-194e-a40": {"Siemens": "siemens-3va-disconnect"},
    "ab-1489-m1c100": {"Siemens": "siemens-5sy4-1p-c16"},
    "ab-1489-m3c200": {"Siemens": "siemens-5sy6-3p-c10"},
    "ab-1492-j3-strip": {"Siemens": "siemens-8wh-strip", "Omron": "omron-xw5t-strip"},
    "ab-contactor-100c": {"Siemens": "siemens-contactor-3rt", "Omron": "omron-j7kna-09"},
    "ab-140mt-c-b63": {"Siemens": "siemens-3rv2011"},
    "ab-powerflex-525": {"Siemens": "siemens-g120c", "Omron": "omron-mx2-2k2"},
    "ab-estop-800t": {"Siemens": "siemens-estop-3su1", "Omron": "omron-a22ne-estop"},
    "ab-guardmaster-msr127": {"Siemens": "siemens-3sk1111", "Omron": "omron-g9se-201"},
    "ab-guardmaster-gsr-si": {"Siemens": "siemens-3sk1121", "Omron": "omron-g9se-201"},
    "ab-panelview-5310": {"Siemens": "siemens-ktp700", "Omron": "omron-na5-7w"},
    "ab-pb-green-start": {"Siemens": "siemens-pb-green-start", "Omron": "omron-a22n-green"},
    "ab-pb-red-stop": {"Siemens": "siemens-pb-red-stop"},
    "ab-indicator-green": {"Siemens": "siemens-3su1-pilot-green", "Omron": "omron-m22n-green"},
    "ab-440l-guardshield-640": {"Siemens": "siemens-3rg78-curtain", "Omron": "omron-f3sg-ra-640"},
    "ab-prox-871c": {"Siemens": "siemens-prox-3rg", "Omron": "omron-e2e-x5"},
    "ab-photo-42ef": {"Omron": "omron-e3z-d81"},
    "ab-relay-700ha": {"Omron": "omron-my2n"},
}


@dataclass(frozen=True)
class Slot:
    type_id: str
    catalog_id: str
    tag: str
    description: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StarterTemplate:
    id: str
    name: str
    glyph: str
    summary: str
    when: str
    change_first: tuple[str, ...]
    supplies: tuple[str, ...]
    control: str
    duty: str
    answers: dict[str, str]
    slots: Callable[[str, str], list[Slot]]
    rungs: Callable[[], list[dict[str, Any]]]
    hmi: bool = False
    tag_notes: dict[str, str] = field(default_factory=dict)

    @property
    def default_supply(self) -> str:
        return self.supplies[0]


# ----------------------------------------------------------------------------- ladder helpers

def _contacts(text: str) -> list[dict[str, Any]]:
    return [{"tag": t.lstrip("/"), "normally_closed": t.startswith("/")} for t in text.split() if t.strip("/")]


def rung(coil: str, series: str = "", *, any_of: tuple[str, ...] = (), timer: tuple | None = None,
         counter: tuple | None = None, note: str = "") -> dict[str, Any]:
    """One rung: (branch OR branch ...) then series contacts -> coil. '/TAG' is a normally-closed (XIO) contact."""
    out: dict[str, Any] = {
        "id": new_id(),
        "parallel": [_contacts(b) for b in any_of if b.strip()],
        "series": _contacts(series),
        "coil_tag": coil,
        "coil_negated": False,
        "comment": note,
    }
    if timer:
        out["timer"] = {"tag": timer[0], "block": timer[1], "pt_ms": int(timer[2])}
    if counter:
        out["counter"] = {"tag": counter[0], "block": counter[1], "pv": int(counter[2]) if len(counter) > 2 else 0}
    return out


def _stack(red: str, amber: str, green: str, note_amber: str) -> list[dict[str, Any]]:
    lamp = " Indication only - the safety relay does the stopping."
    return [
        rung("STK_Red", any_of=red.split("|"), note="RED stack light: E-stop pressed or a fault." + lamp),
        rung("STK_Amber", amber, note=f"AMBER stack light: {note_amber}." + lamp),
        rung("STK_Green", green, note="GREEN stack light: healthy - ready or running." + lamp),
    ]


# ----------------------------------------------------------------------------- device helpers

def _base(supply: str, control: str, *, plc: str = "ab-compactlogix-5380", modules: bool = True,
          estop: bool = True) -> list[Slot]:
    net = {"io_direction": "Network / no discrete I/O"}
    slots: list[Slot] = []
    if "VAC" in supply:
        slots.append(Slot("disconnect", "ab-194e-a40", "DS1", "Main disconnect (lockable)", net))
    slots += [
        Slot("breaker", "ab-1489-m1c100", "CB1", "Control power branch protection", net),
        Slot("power_supply", "ab-1606-xls", "PSU1", "24 VDC control power", {"output_voltage": "24 VDC"}),
        Slot("plc", plc, "PLC1", "Machine controller"),
        Slot("terminal_block", "ab-1492-j3-strip", "TB1", "Field wiring terminals", net),
    ]
    if modules:
        slots += [
            Slot("io_module", "ab-5069-ib16", "DI1", "Discrete inputs"),
            Slot("io_module", "ab-5069-ob16", "DO1", "Discrete outputs"),
        ]
    if estop:
        slots += [
            Slot("estop", "ab-estop-800t", "ES1", "Emergency stop (ON = pressed; status to PLC)",
                 {"voltage": control}),
            Slot("safety_relay", "ab-guardmaster-msr127", "SR1",
                 "E-stop safety relay - hardwired, drops the hazard power"),
        ]
    return slots


def _pb(tag: str, function: str, color: str, control: str, catalog: str = "") -> Slot:
    contact = "NC momentary" if function.lower().startswith("stop") else "NO momentary"
    default = {"Green": "ab-pb-green-start", "Red": "ab-pb-red-stop", "Blue": "ab-pb-reset"}.get(color, "ab-pb-reset")
    return Slot("pushbutton", catalog or default, tag, function,
                {"function": function, "contact": contact, "color": color, "voltage": control})


def _lamp(tag: str, function: str, color: str, control: str) -> Slot:
    catalog = "ab-indicator-red" if color in {"Red", "Amber"} else "ab-indicator-green"
    return Slot("light", catalog, tag, function, {"function": function, "color": color, "voltage": control,
                                                   "io_direction": "Output"})


def _stack_slots(control: str, amber_function: str) -> list[Slot]:
    out = []
    for color, function, cat in (("Green", "Ready / running", "ab-stack-855t-green"),
                                 ("Amber", amber_function, "ab-stack-855t-amber"),
                                 ("Red", "E-stop", "ab-stack-855t-red")):
        out.append(Slot("light", cat, f"STK_{color}", f"Stack light {color.lower()}: {amber_function.lower()}"
                        if color == "Amber" else f"Stack light {color.lower()}: {function.lower()}",
                        {"function": function, "color": color, "voltage": control,
                         "mounting": "Field device", "io_direction": "Output"}))
    return out


def _motor_starter_slots(supply: str, control: str, tag: str = "M1", load: str = "Motor") -> list[Slot]:
    hp = "motor-nema-5hp" if "480" in supply or "3-phase" in supply else "motor-nema-1hp"
    return [
        Slot("motor_protector", "ab-140mt-c-b63", "OL1", f"{load} motor protector - trip contact to PLC",
             {"io_direction": "Input"}),
        Slot("contactor", "ab-contactor-100c", tag, f"{load} contactor", {"coil_voltage": control}),
        Slot("motor", hp, "MTR1", f"{load} motor", {"voltage": supply}),
    ]


def _sensor(tag: str, catalog: str, description: str) -> Slot:
    return Slot("sensor", catalog, tag, description, {"function": description, "io_direction": "Input"})


# ----------------------------------------------------------------------------- templates

def _t_motor_slots(supply: str, control: str) -> list[Slot]:
    return [*_base(supply, control), *_motor_starter_slots(supply, control),
            _pb("PB_Start", "Start", "Green", control), _pb("PB_Stop", "Stop", "Red", control),
            _pb("PB_Reset", "Reset", "Blue", control),
            _lamp("LT_Run", "Run", "Green", control), _lamp("LT_Fault", "Fault", "Red", control)]


def _t_motor_rungs() -> list[dict[str, Any]]:
    return [
        rung("M1", "/PB_Stop /ES1 /Fault", any_of=("PB_Start", "M1"),
             note=f"{SAFETY_NOTE} | Start/stop seal-in: Start pulls in M1, M1 holds itself; Stop, E-stop or a "
                  "fault drops it."),
        rung("Fault", "/PB_Reset", any_of=("OL1", "Fault"),
             note="Fault latch: the overload (motor protector) trip holds Fault until Reset is pressed."),
        rung("LT_Run", "M1", note="Run light on while the contactor is pulled in."),
        rung("LT_Fault", any_of=("Fault", "ES1"), note="Fault light: overload trip or E-stop pressed."),
    ]


def _t_conveyor_slots(supply: str, control: str) -> list[Slot]:
    return [*_base(supply, control),
            Slot("vfd", "ab-powerflex-525", "VFD1", "Conveyor drive", {"io_direction": "Output"}),
            Slot("motor", "motor-nema-5hp" if "480" in supply else "motor-nema-1hp", "MTR1", "Conveyor motor",
                 {"voltage": supply}),
            _pb("PB_Start", "Start", "Green", control), _pb("PB_Stop", "Stop", "Red", control),
            _pb("PB_Reset", "Reset", "Blue", control),
            _sensor("PE1", "ab-photo-42ef", "Part photo-eye (ON = part in the beam)"),
            Slot("hmi", "ab-panelview-5310", "HMI1", "Operator panel"),
            *_stack_slots(control, "Batch complete")]


def _t_conveyor_rungs() -> list[dict[str, Any]]:
    return [
        rung("VFD1_RUN", "/PB_Stop /ES1 /Jam_Fault", any_of=("PB_Start", "VFD1_RUN"),
             note=f"{SAFETY_NOTE} | Conveyor run seal-in to the drive run input."),
        rung("", "PE1", counter=("C_Parts", "CTU", 100), note="Count each part that breaks the photo-eye."),
        rung("Batch_Done", "C_Parts.DN", note="Batch of 100 parts reached."),
        rung("", "PB_Reset", counter=("C_Parts", "RES", 0), note="Reset clears the part count."),
        rung("", "VFD1_RUN PE1", timer=("T_Jam", "TON", 5000),
             note="Jam timer: eye blocked for 5 s while running = jam."),
        rung("Jam_Fault", "/PB_Reset", any_of=("T_Jam.DN", "Jam_Fault"),
             note="Jam latch: stops the conveyor until Reset."),
        *_stack("ES1|Jam_Fault", "Batch_Done /ES1", "/ES1 /Jam_Fault", "batch complete"),
    ]


def _t_pump_slots(supply: str, control: str) -> list[Slot]:
    return [*_base(supply, control), *_motor_starter_slots(supply, control, load="Pump"),
            _pb("PB_Start", "Start auto", "Green", control), _pb("PB_Stop", "Stop", "Red", control),
            _pb("PB_Reset", "Reset", "Blue", control),
            _sensor("LS_Low", "ab-prox-871c", "Tank low level switch (ON = liquid at switch)"),
            _sensor("LS_High", "ab-prox-871c", "Tank high level switch (ON = liquid at switch)"),
            _sensor("LS_HiHi", "ab-prox-871c", "Tank high-high alarm switch (ON = overfill)"),
            _lamp("LT_Run", "Pump running", "Green", control), _lamp("LT_Fault", "Alarm", "Red", control),
            Slot("hmi", "ab-panelview-5310", "HMI1", "Operator panel")]


def _t_pump_rungs() -> list[dict[str, Any]]:
    return [
        rung("Auto_On", "/PB_Stop /ES1", any_of=("PB_Start", "Auto_On"),
             note=f"{SAFETY_NOTE} | Auto mode seal-in: Start turns automatic level control on."),
        rung("Pump_Call", "/LS_High", any_of=("/LS_Low", "Pump_Call"),
             note="Fill: call the pump when the level drops below the low switch, run until the high switch."),
        rung("M1", "Auto_On Pump_Call /LS_HiHi /Fault /ES1", note="Lead pump contactor."),
        rung("Alm_HiHi", "/PB_Reset", any_of=("LS_HiHi", "Alm_HiHi"), note="High-high (overfill) alarm latch."),
        rung("", "M1 /LS_Low", timer=("T_Dry", "TON", 120000),
             note="Pump has run 2 min and the level never reached the low switch = no flow."),
        rung("Fault", "/PB_Reset", any_of=("OL1", "T_Dry.DN", "Fault"),
             note="Fault latch: overload trip or no-flow timer, held until Reset."),
        rung("LT_Run", "M1", note="Pump running light."),
        rung("LT_Fault", any_of=("Fault", "Alm_HiHi", "ES1"), note="Alarm light: fault, overfill or E-stop."),
    ]


def _t_press_slots(supply: str, control: str) -> list[Slot]:
    return [*_base(supply, control),
            Slot("light_curtain", "ab-440l-guardshield-640", "LC1",
                 "Light curtain - status to PLC: ON = beam broken (safety relay does the stopping)",
                 {"io_direction": "Input"}),
            Slot("safety_relay", "ab-guardmaster-gsr-si", "SR_LC",
                 "Light curtain safety relay - monitors the OSSDs and drops valve power"),
            _pb("PB_2H_L", "Two-hand start left", "Green", control),
            _pb("PB_2H_R", "Two-hand start right", "Green", control),
            _pb("PB_Stop", "Stop", "Red", control), _pb("PB_Reset", "Reset", "Blue", control),
            Slot("solenoid", "solenoid-24vdc", "SOL_Ext", "Cylinder extend solenoid", {"io_direction": "Output"}),
            Slot("solenoid", "solenoid-24vdc", "SOL_Ret", "Cylinder retract solenoid", {"io_direction": "Output"}),
            _sensor("PX_Ext", "ab-prox-871c", "Cylinder extended sensor"),
            _sensor("PX_Ret", "ab-prox-871c", "Cylinder retracted (home) sensor"),
            Slot("hmi", "ab-panelview-5310", "HMI1", "Operator panel"),
            *_stack_slots(control, "Light curtain broken")]


def _t_press_rungs() -> list[dict[str, Any]]:
    return [
        rung("Hands_Both", "PB_2H_L PB_2H_R",
             note=f"{SAFETY_NOTE} | Two-hand control must use a rated two-hand safety module (ISO 13851); "
                  "this rung only monitors both buttons."),
        rung("", any_of=("PB_2H_L", "PB_2H_R"), timer=("T_2H", "TON", 500),
             note="Anti-tie-down: both hands must arrive within 0.5 s."),
        rung("Hands_OK", "Hands_Both", any_of=("/T_2H.DN", "Hands_OK"),
             note="Hands OK while both buttons stay held after a fair start."),
        rung("Cycle_Done", "Hands_Both", any_of=("T_Dwell.DN", "Cycle_Done"),
             note="One stroke per press: let go of both buttons to start the next cycle."),
        rung("SOL_Ext", "Hands_OK /Cycle_Done /SOL_Ret /PX_Ext /PB_Stop /ES1 /LC1 /Fault",
             any_of=("PX_Ret", "SOL_Ext"),
             note="Extend from home while both hands are held. Light curtain or E-stop drops the output."),
        rung("", "PX_Ext", timer=("T_Dwell", "TON", 1000), note="Dwell 1 s at the bottom of the stroke."),
        rung("SOL_Ret", "/PX_Ret", any_of=("T_Dwell.DN", "PB_Stop", "SOL_Ret"),
             note="Retract after the dwell (or on Stop) until the home sensor."),
        rung("", "T_Dwell.DN", counter=("C_Cycles", "CTU", 1000), note="Stroke counter."),
        rung("", "SOL_Ext", timer=("T_Cycle", "TON", 3000), note="Extend watchdog: 3 s without reaching bottom."),
        rung("Fault", "/PB_Reset", any_of=("T_Cycle.DN", "Fault"), note="Fault latch until Reset."),
        *_stack("ES1|Fault", "LC1 /ES1", "/ES1 /LC1 /Fault", "light curtain beam broken"),
    ]


def _t_mixer_slots(supply: str, control: str) -> list[Slot]:
    return [*_base(supply, control), *_motor_starter_slots(supply, control, load="Agitator"),
            Slot("contactor", "ab-contactor-100c", "HTR1", "Heater contactor", {"coil_voltage": control}),
            _pb("PB_Start", "Start batch", "Green", control), _pb("PB_Stop", "Stop", "Red", control),
            _pb("PB_Reset", "Reset", "Blue", control),
            _sensor("ZS_Lid", "ab-prox-871c", "Lid closed switch"),
            _sensor("TS_Temp", "ab-prox-871c", "Temperature switch (ON = batch at temperature)"),
            _lamp("LT_Run", "Batch running", "Green", control), _lamp("LT_Done", "Batch done", "Green", control),
            _lamp("LT_Fault", "Fault", "Red", control),
            Slot("hmi", "ab-panelview-5310", "HMI1", "Operator panel")]


def _t_mixer_rungs() -> list[dict[str, Any]]:
    return [
        rung("Batch", "/PB_Stop /ES1 /Fault /Mix_Done", any_of=("PB_Start ZS_Lid", "Batch"),
             note=f"{SAFETY_NOTE} | Batch seal-in: Start with the lid closed."),
        rung("M1", "Batch ZS_Lid", note="Agitator runs during the batch while the lid is closed."),
        rung("HTR1", "Batch /TS_Temp", note="Heat until the temperature switch makes."),
        rung("", "M1 TS_Temp", timer=("T_Mix", "TON", 600000), note="Timed mix: 10 min at temperature."),
        rung("Mix_Done", "/PB_Start", any_of=("T_Mix.DN", "Mix_Done"),
             note="Batch done latch; the next Start clears it."),
        rung("", "HTR1", timer=("T_Heat", "TON", 1800000), note="Heat watchdog: 30 min without temperature."),
        rung("Fault", "/PB_Reset", any_of=("OL1", "T_Heat.DN", "Fault"), note="Fault latch until Reset."),
        rung("LT_Run", "Batch", note="Batch running light."),
        rung("LT_Done", "Mix_Done", note="Batch done light."),
        rung("LT_Fault", any_of=("Fault", "ES1"), note="Fault light: overload, heat timeout or E-stop."),
    ]


def _t_indexer_slots(supply: str, control: str) -> list[Slot]:
    sol = lambda tag, d: Slot("solenoid", "solenoid-24vdc", tag, d, {"io_direction": "Output"})  # noqa: E731
    return [*_base(supply, control),
            _pb("PB_Start", "Start", "Green", control), _pb("PB_Stop", "Stop", "Red", control),
            _pb("PB_Reset", "Reset", "Blue", control),
            _sensor("PE_Part", "ab-photo-42ef", "Part present at pick"),
            _sensor("PX_Up", "ab-prox-871c", "Head up"), _sensor("PX_Down", "ab-prox-871c", "Head down"),
            _sensor("PX_Pick", "ab-prox-871c", "Arm at pick"), _sensor("PX_Place", "ab-prox-871c", "Arm at place"),
            sol("SOL_Down", "Lower head solenoid"), sol("SOL_Grip", "Gripper / vacuum solenoid"),
            sol("SOL_X", "Move arm to place solenoid"),
            Slot("hmi", "ab-panelview-5310", "HMI1", "Operator panel"),
            *_stack_slots(control, "Waiting for part")]


def _t_indexer_rungs() -> list[dict[str, Any]]:
    return [
        rung("Auto", "/PB_Stop /ES1 /Fault", any_of=("PB_Start", "Auto"),
             note=f"{SAFETY_NOTE} | Auto seal-in. Stop, E-stop or a fault ends the sequence."),
        rung("Step_1", "Auto /Step_2", any_of=("PE_Part PX_Pick PX_Up /Step_6", "Step_1"),
             note="Step 1: part present and arm home - lower the head."),
        rung("Step_2", "Auto /Step_3", any_of=("Step_1 PX_Down", "Step_2"), note="Step 2: head down - grip."),
        rung("", "Step_2", timer=("T_Grip", "TON", 500), note="Grip settle time."),
        rung("Step_3", "Auto /Step_4", any_of=("Step_2 T_Grip.DN", "Step_3"), note="Step 3: lift the part."),
        rung("Step_4", "Auto /Step_5", any_of=("Step_3 PX_Up", "Step_4"), note="Step 4: move to place."),
        rung("Step_5", "Auto /Step_6", any_of=("Step_4 PX_Place", "Step_5"), note="Step 5: lower and release."),
        rung("", "Step_5 PX_Down", timer=("T_Rel", "TON", 500), note="Release time."),
        rung("Step_6", "Auto", any_of=("Step_5 T_Rel.DN", "Step_6 /PX_Pick"),
             note="Step 6: lift and return home; ends when the arm is back at pick."),
        rung("SOL_Down", "/ES1", any_of=("Step_1", "Step_2", "Step_5"), note="Head down in steps 1, 2 and 5."),
        rung("SOL_Grip", "/ES1", any_of=("Step_2", "Step_3", "Step_4"), note="Grip held from step 2 to 4."),
        rung("SOL_X", "/ES1", any_of=("Step_4", "Step_5"), note="Arm to place in steps 4 and 5."),
        rung("", "T_Rel.DN", counter=("C_Placed", "CTU", 9999), note="Parts placed."),
        rung("", any_of=("Step_1", "Step_3", "Step_4", "Step_6"), timer=("T_Watch", "TON", 8000),
             note="Motion watchdog: a move taking over 8 s is a fault."),
        rung("Fault", "/PB_Reset", any_of=("T_Watch.DN", "Fault"), note="Fault latch until Reset."),
        *_stack("ES1|Fault", "Auto /PE_Part /ES1", "/ES1 /Fault", "waiting for a part"),
    ]


def _t_hvac_slots(supply: str, control: str) -> list[Slot]:
    return [*_base(supply, control),
            Slot("vfd", "ab-powerflex-525", "VFD1", "Exhaust fan drive", {"io_direction": "Output"}),
            Slot("motor", "motor-nema-5hp" if "480" in supply else "motor-nema-1hp", "MTR1", "Exhaust fan motor",
                 {"voltage": supply}),
            Slot("pushbutton", "ab-selector-hoa", "SS_Auto",
                 "HOA selector - Auto contact to PLC (Hand runs the drive from its keypad)",
                 {"function": "Selector HOA", "contact": "Maintained", "color": "Black", "voltage": control}),
            Slot("relay", "ab-relay-700ha", "CR_BMS", "Building system run request (dry contact in)",
                 {"io_direction": "Input", "coil_voltage": control}),
            _sensor("PS_Air", "ab-prox-871c", "Airflow proving pressure switch"),
            _pb("PB_Reset", "Reset", "Blue", control),
            _lamp("LT_Run", "Fan proven", "Green", control), _lamp("LT_Fault", "Airflow fault", "Red", control)]


def _t_hvac_rungs() -> list[dict[str, Any]]:
    return [
        rung("VFD1_RUN", "SS_Auto CR_BMS /ES1 /Fault",
             note=f"{SAFETY_NOTE} | Auto run: HOA in Auto and the building system asks for the fan."),
        rung("", "VFD1_RUN", timer=("T_Prove", "TON", 15000), note="Airflow must prove within 15 s."),
        rung("Fault", "/PB_Reset", any_of=("T_Prove.DN /PS_Air", "Fault"),
             note="Airflow fault latch: fan commanded but no pressure."),
        rung("LT_Run", "VFD1_RUN PS_Air", note="Fan proven light."),
        rung("LT_Fault", any_of=("Fault", "ES1"), note="Fault light."),
    ]


def _t_lighting_slots(supply: str, control: str) -> list[Slot]:
    relay = lambda tag, d: Slot("relay", "ab-relay-700ha", tag, d,  # noqa: E731
                                {"io_direction": "Output", "coil_voltage": control, "function": "Lighting"})
    return [*_base(supply, control, plc="ab-micro850", modules=False, estop=False),
            _sensor("PC1", "ab-photo-42ef", "Photocell (ON = dark outside)"),
            Slot("pushbutton", "ab-selector-hoa", "SS_Auto", "Auto / Off selector (ON = Auto)",
                 {"function": "Selector Auto", "contact": "Maintained", "color": "Black", "voltage": control}),
            _pb("PB_On", "Start override", "Green", control), _pb("PB_Off", "Stop override", "Red", control),
            relay("CR1", "Parking lot lights"), relay("CR2", "Building lights"), relay("CR3", "Sign lights"),
            _lamp("LT_On", "Lights on", "Green", control)]


def _t_lighting_rungs() -> list[dict[str, Any]]:
    return [
        rung("", "PC1", timer=("T_Dark", "TON", 60000),
             note=f"{SAFETY_NOTE} | Dark for 60 s (ignores headlights and clouds)."),
        rung("Override", "/PB_Off /T_Over.DN", any_of=("PB_On", "Override"), note="Manual override on (seal-in)."),
        rung("", "Override", timer=("T_Over", "TON", 7200000), note="Override turns itself off after 2 h."),
        rung("CR1", any_of=("SS_Auto T_Dark.DN", "Override"), note="Parking lot lights."),
        rung("CR2", any_of=("SS_Auto T_Dark.DN", "Override"), note="Building lights."),
        rung("CR3", "SS_Auto T_Dark.DN", note="Sign lights (auto only)."),
        rung("LT_On", any_of=("CR1", "CR2", "CR3"), note="Lights-on indicator."),
    ]


def _t_trainer_slots(supply: str, control: str) -> list[Slot]:
    return [*_base(supply, control, plc="ab-micro850", modules=False),
            _pb("PB_Start", "Start", "Green", control), _pb("PB_Stop", "Stop", "Red", control),
            _pb("PB_Reset", "Reset", "Blue", control),
            Slot("pushbutton", "ab-selector-hoa", "SS_Sel", "Two-position selector",
                 {"function": "Selector", "contact": "Maintained", "color": "Black", "voltage": control}),
            _sensor("PE1", "ab-photo-42ef", "Practice photo-eye"), _sensor("PX1", "ab-prox-871c", "Practice prox"),
            Slot("relay", "ab-relay-700ha", "CR1", "Practice relay output",
                 {"io_direction": "Output", "coil_voltage": control}),
            _lamp("LT_Green", "Run", "Green", control), _lamp("LT_Red", "Stopped", "Red", control),
            Slot("hmi", "ab-panelview-5310", "HMI1", "Practice touchscreen"),
            *_stack_slots(control, "Count reached")]


def _t_trainer_rungs() -> list[dict[str, Any]]:
    return [
        rung("Run", "/PB_Stop /ES1", any_of=("PB_Start", "Run"), note=f"{SAFETY_NOTE} | Practice start/stop seal-in."),
        rung("LT_Green", "Run", note="Green light while running."),
        rung("", "/T_Off.DN", timer=("T_On", "TON", 500), note="Flasher part 1."),
        rung("", "T_On.DN", timer=("T_Off", "TON", 500), note="Flasher part 2."),
        rung("LT_Red", any_of=("ES1", "/Run T_On.DN"), note="Red flashes when stopped, solid on E-stop."),
        rung("", "PE1", counter=("C_Count", "CTU", 10), note="Count photo-eye blocks."),
        rung("", "PB_Reset", counter=("C_Count", "RES", 0), note="Reset the count."),
        rung("CR1", "Run", any_of=("PX1", "SS_Sel"), note="Relay: prox or selector while running."),
        *_stack("ES1", "C_Count.DN /ES1", "Run /ES1", "count reached"),
    ]


def _answers(**kw: str) -> dict[str, str]:
    base = {"has_motor": "No", "motor_control": "No motor", "start_stop": "Pushbuttons", "has_estop": "Yes",
            "has_safety_relay": "Yes", "light_curtain": "No", "stack_light": "No", "has_hmi": "No",
            "has_control_relays": "No", "door_drawing": "Yes — draw the door", "operator_devices": ""}
    base.update(kw)
    return base


TEMPLATES: tuple[StarterTemplate, ...] = (
    StarterTemplate(
        "motor-starter", "Simple motor starter", "M",
        "One motor, across-the-line contactor and overload. Start / Stop / E-stop with run and fault lights.",
        "Any single fixed-speed motor: fan, pump, blower, saw.",
        ("Set the motor horsepower and full-load amps on MTR1.", "Size the motor protector OL1 to the motor FLA.",
         "Check the supply voltage and the contactor coil voltage."),
        ("480 VAC", "240 VAC 3-phase", "208 VAC"), "24 VDC", "motor starter",
        _answers(has_motor="Yes", motor_control="Contactor (across-the-line)",
                 operator_devices="Start pushbutton | Stop pushbutton | Reset pushbutton | Run indicator light | "
                                  "Fault indicator light"),
        _t_motor_slots, _t_motor_rungs),
    StarterTemplate(
        "conveyor-vfd", "Conveyor with VFD", "C",
        "Variable-speed conveyor with a photo-eye that counts parts and a jam timer. Stack light and HMI.",
        "Belt or roller conveyors that move parts and need counting or jam detection.",
        ("Set the batch size (C_Parts preset) and the jam time (T_Jam).", "Set the drive and motor horsepower.",
         "Point the photo-eye PE1 where parts pass one at a time."),
        ("480 VAC", "240 VAC 3-phase", "208 VAC"), "24 VDC", "conveyor motor drive",
        _answers(has_motor="Yes", motor_control="VFD (variable speed)", stack_light="Yes — green / amber / red stack light",
                 has_hmi="Yes", start_stop="Both"),
        _t_conveyor_slots, _t_conveyor_rungs, hmi=True),
    StarterTemplate(
        "pump-tank", "Pump and tank level", "P",
        "Fills a tank with one pump between low and high level switches, with overfill and no-flow alarms.",
        "Sumps, water tanks, wash tanks - anything filled or emptied by level.",
        ("Swap the level sensors for your float or level switches.", "Set the no-flow time (T_Dry).",
         "For pump-down (emptying) swap the LS_Low / LS_High contacts in the Pump_Call rung."),
        ("480 VAC", "240 VAC", "208 VAC"), "24 VDC", "pump tank level",
        _answers(has_motor="Yes", motor_control="Contactor (across-the-line)", has_hmi="Yes"),
        _t_pump_slots, _t_pump_rungs, hmi=True),
    StarterTemplate(
        "press-station", "Pneumatic press station", "PR",
        "Two-hand start, light curtain and safety relays, cylinder extend / retract sensors, dwell and cycle timers.",
        "Presses, crimpers, stakers - an operator loads by hand and a cylinder strokes.",
        ("Have the two-hand control and light curtain checked by a safety person (risk assessment).",
         "Set the dwell time (T_Dwell) and the stroke watchdog (T_Cycle).",
         "Match the valve solenoid voltage to your valve."),
        ("120 VAC", "240 VAC", "24 VDC"), "24 VDC", "pneumatic press station",
        _answers(light_curtain="Yes — add a light curtain + safety relay",
                 stack_light="Yes — green / amber / red stack light", has_hmi="Yes"),
        _t_press_slots, _t_press_rungs, hmi=True),
    StarterTemplate(
        "mixer-batch", "Mixer / batch tank", "MX",
        "Agitator motor and heater with a lid switch, temperature permissive and a timed mix.",
        "Mixing, heating or blending a batch for a set time.",
        ("Set the mix time (T_Mix) and the heat watchdog (T_Heat).", "Size the heater contactor HTR1 to the heater.",
         "Set the temperature switch to your batch temperature (add an analog input card and a 4-20 mA "
         "transmitter if you want to see the temperature)."),
        ("480 VAC", "240 VAC 3-phase", "208 VAC"), "24 VDC", "mixer batch agitator heater",
        _answers(has_motor="Yes", motor_control="Contactor (across-the-line)", has_hmi="Yes"),
        _t_mixer_slots, _t_mixer_rungs, hmi=True),
    StarterTemplate(
        "indexer-pnp", "Pick-and-place indexer", "PP",
        "Three solenoids run a 6-step pick-and-place sequence with step bits, part-present eye and watchdog.",
        "Packaging, transfer and assembly stations that move parts in steps.",
        ("Check each step in order against your machine.", "Set the grip and release times.",
         "Add or remove steps by copying a Step rung."),
        ("120 VAC", "240 VAC", "24 VDC"), "24 VDC", "packaging pick and place indexer",
        _answers(stack_light="Yes — green / amber / red stack light", has_hmi="Yes"),
        _t_indexer_slots, _t_indexer_rungs, hmi=True),
    StarterTemplate(
        "hvac-fan", "HVAC / exhaust fan", "F",
        "Fan drive with Hand-Off-Auto, building run request and an airflow proving switch.",
        "Exhaust, supply or make-up air fans run by a building system.",
        ("Set the proving delay (T_Prove).", "Wire the building system contact to CR_BMS.",
         "Set the fan drive and motor horsepower."),
        ("480 VAC", "208 VAC", "240 VAC 3-phase"), "120 VAC", "hvac exhaust fan",
        _answers(has_motor="Yes", motor_control="VFD (variable speed)",
                 operator_devices="Selector switch (HOA) | Reset pushbutton | Run indicator light | "
                                  "Fault indicator light"),
        _t_hvac_slots, _t_hvac_rungs),
    StarterTemplate(
        "lighting-panel", "Lighting control panel", "L",
        "Photocell, Auto/Off selector and override pushbuttons switch three lighting relays with timers.",
        "Parking lot, building or sign lighting on a small 120 V panel.",
        ("Rename the relays to your lighting zones.", "Set the dark delay (T_Dark) and override time (T_Over).",
         "Check each relay contact rating against the lighting load."),
        ("120 VAC", "240 VAC"), "24 VDC", "lighting control relay photocell",
        _answers(has_estop="No", has_safety_relay="No", has_control_relays="Yes — add control relays",
                 start_stop="Pushbuttons"),
        _t_lighting_slots, _t_lighting_rungs),
    StarterTemplate(
        "plc-trainer", "PLC trainer bench", "T",
        "A practice panel: PLC, pushbuttons, selector, sensors, a relay, lights and a stack light on 24 VDC.",
        "Learning ladder logic, testing programs or teaching a class.",
        ("Add your own rungs - the starter rungs are examples.", "Use the simulator to try each input.",
         "Swap the maker to match the PLC on your bench."),
        ("120 VAC", "24 VDC"), "24 VDC", "plc trainer bench",
        _answers(stack_light="Yes — green / amber / red stack light", has_hmi="Yes", door_drawing="No — no door drawing"),
        _t_trainer_slots, _t_trainer_rungs, hmi=True),
)
TEMPLATE_BY_ID = {t.id: t for t in TEMPLATES}


# ----------------------------------------------------------------------------- build

def maker_catalog_id(library: Library, catalog_id: str, maker: str) -> str:
    """Same part from ``maker`` when the library has an equivalent, else the original part."""
    if maker and maker != "Allen-Bradley":
        alt = MAKER_EQUIV.get(catalog_id, {}).get(maker)
        if alt and alt in library.catalog_by_id:
            return alt
    return catalog_id


def _recommendations(library: Library, profile, interview: dict[str, str], slots: list[Slot], maker: str):
    from cabinet_studio.services.ai_build import RecommendedDevice, catalog_label
    from cabinet_studio.services.suggestions import DeviceSuggestion, suggest_device, used_wire_numbers

    base = new_blank_project()
    used = used_wire_numbers(base)
    out = []
    for slot in slots:
        if slot.type_id not in library.types:
            continue
        cat = library.catalog_by_id[maker_catalog_id(library, slot.catalog_id, maker)]
        suggestion = suggest_device(library, profile, base, slot.type_id, interview, tag=slot.tag, used=used)
        fields = dict(suggestion.fields)
        fields.update(cat.default_map())
        fields["vendor"] = cat.vendor
        fields["catalog"] = cat.catalog
        fields["description"] = slot.description
        fields.update({k: v for k, v in slot.fields.items() if v})
        fields["tag"] = slot.tag
        reason = f"Starter template part ({cat.vendor} {cat.catalog})."
        number, vendor, name = catalog_label(library, cat.id)
        out.append(RecommendedDevice(
            key=slot.tag, type_id=slot.type_id, label=library.types[slot.type_id].label, catalog_id=cat.id,
            catalog_number=number, vendor=vendor, name=name, reason=reason,
            suggestion=DeviceSuggestion(type_id=slot.type_id, catalog_id=cat.id, stock=True, reason=reason,
                                        wire_role=suggestion.wire_role, fields=fields)))
        base.items.append(PlacedItem(id=new_id(), library_id=cat.id, type_id=slot.type_id, x=0, y=0,
                                     fields=dict(fields)))
    return out


def template_notes(template: StarterTemplate, maker: str, supply: str) -> str:
    lines = [f"Starter template: {template.name} ({maker}, {supply} supply, {template.control} control).",
             template.summary, f"When to use it: {template.when}", "What to change first:"]
    lines += [f"  {i}. {text}" for i, text in enumerate(template.change_first, 1)]
    lines += ["", "NOT A CERTIFIED UL 508A DRAWING. Design aid only.", SAFETY_NOTE]
    return "\n".join(lines)


def build_template_project(template: StarterTemplate | str, library: Library, *, maker: str = "Allen-Bradley",
                           supply: str = "", name: str = "", profile=None) -> Project:
    """A NEW project from a starter template: devices, interview, I/O, ladder and HMI."""
    from cabinet_studio.services.ai_build import apply_recommendations, interview_from_ai_answers
    from cabinet_studio.services.io_assign import assign_io
    from cabinet_studio.services.programming import build_starter_program, default_design_answers, refresh_plc_text
    from cabinet_studio.services.standards import default_profile
    from cabinet_studio.services.suggestions import enrich_with_wiring_assist

    if isinstance(template, str):
        template = TEMPLATE_BY_ID[template]
    maker = maker if maker in MAKERS else "Allen-Bradley"
    supply = supply or template.default_supply
    profile = profile or default_profile()
    answers = dict(template.answers)
    answers.update({"duty": template.duty, "manufacturer": maker, "supply_voltage": supply,
                    "control_voltage": template.control, "project_name": name or template.name})
    project = new_blank_project(name or template.name)
    project.template_id = f"starter:{template.id}"
    project.interview = interview_from_ai_answers(answers)
    project.interview["starter_template"] = template.id
    project.subtitle = f"Starter template: {template.name} - design aid, not a certified UL listing"
    project.notes = template_notes(template, maker, supply)
    slots = template.slots(supply, template.control)
    apply_recommendations(library, project, _recommendations(library, profile, project.interview, slots, maker),
                          profile=profile)
    for item in project.items:
        item.fields = enrich_with_wiring_assist(library, profile, project, item.type_id, item.fields,
                                                interview=project.interview)
    assign_io(project)

    program = build_starter_program(project, default_design_answers(project))
    program["rungs"] = template.rungs()
    program = refresh_plc_text(program, project)
    program["text_edited"] = False
    project.program = program

    if template.hmi:
        from cabinet_studio.services.hmi_design import generate_design, save_design

        save_design(project, generate_design(project))
    return project
