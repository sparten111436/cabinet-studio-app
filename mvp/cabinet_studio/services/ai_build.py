"""New build with AI: plain-English interview and library-backed device picks.

Catalog numbers come only from the starter library. Prefer Allen-Bradley when
the library has one for that device class. Never invent a catalog number.
"""

from __future__ import annotations

from dataclasses import dataclass

from cabinet_studio.models.project import PlacedItem, Project
from cabinet_studio.models.schema import CatalogItem, Library
from cabinet_studio.services.layouts import new_blank_project, new_id
from cabinet_studio.services.placement import next_free_position
from cabinet_studio.services.standards import StandardsProfile
from cabinet_studio.services.suggestions import DeviceSuggestion, suggest_device, used_wire_numbers

CATALOG_NOT_IDENTIFIED = "catalog not identified"

AI_BUILD_DISCLAIMER = (
    "This is a design aid, not a certified UL 508A listing. "
    "Programming here is cut-and-paste help only — not a live PLC download."
)

# One question at a time. Labels are plain English for a young reader.
# kind: text | choice | multi
DOOR_YES = "Yes — draw the door"
DOOR_NO = "No — no door drawing"
MAKERS = ("Allen-Bradley", "Siemens", "Omron", "Best fit (AI picks)")
LC_YES = "Yes — add a light curtain + safety relay"
STACK_YES = "Yes — green / amber / red stack light"
_GUARD_WORDS = ("press", "weld", "robot", "cell", "punch", "cut", "saw", "shear", "crimp", "stamp", "guard", "safety")

AI_BUILD_QUESTIONS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "duty",
        "What does this machine do?",
        "text",
        (),
    ),
    (
        "manufacturer",
        "Which manufacturer do you prefer for the parts?",
        "choice",
        MAKERS,
    ),
    (
        "supply_voltage",
        "What voltage feeds the cabinet?",
        "choice",
        ("480 VAC", "240 VAC", "240 VAC 3-phase", "220 VAC", "208 VAC", "120 VAC", "24 VDC", "Other / not sure"),
    ),
    (
        "control_voltage",
        "What voltage do the pushbuttons and sensors use?",
        "choice",
        ("24 VDC", "120 VAC", "24 VAC", "Other / not sure"),
    ),
    (
        "has_motor",
        "Does this machine run a motor?",
        "choice",
        ("Yes", "No", "Not sure"),
    ),
    (
        "motor_control",
        "How should the motor be controlled? (skip if no motor)",
        "choice",
        ("VFD (variable speed)", "Contactor (across-the-line)", "Both / not sure", "No motor"),
    ),
    (
        "start_stop",
        "How do people start and stop it?",
        "choice",
        ("Pushbuttons", "Touchscreen (HMI)", "Both", "Not sure"),
    ),
    (
        "operator_devices",
        "Which operator devices should go on the door / panel? (pick all that apply)",
        "multi",
        (
            "Start pushbutton",
            "Stop pushbutton",
            "Selector switch (HOA)",
            "Reset pushbutton",
            "Run indicator light",
            "Fault indicator light",
        ),
    ),
    (
        "has_control_relays",
        "Do you want interposing / control relays in the cabinet?",
        "choice",
        ("Yes — add control relays", "No", "Not sure (AI will suggest)"),
    ),
    (
        "has_estop",
        "Is there an emergency stop (e-stop) button?",
        "choice",
        ("Yes", "No", "Not sure"),
    ),
    (
        "has_safety_relay",
        "Should we include a safety relay to monitor the e-stop?",
        "choice",
        ("Yes", "No", "Not sure (AI will suggest)"),
    ),
    (
        "light_curtain",
        "Does a light curtain guard the operator opening? (beam broken = machine stops)",
        "choice",
        (LC_YES, "No"),
    ),
    (
        "stack_light",
        "Add a 3-color stack light? (green = ready / running, amber = light curtain broken, red = E-stop)",
        "choice",
        (STACK_YES, "No"),
    ),
    (
        "has_hmi",
        "Is there a touchscreen or HMI for the operator?",
        "choice",
        ("Yes", "No", "Not sure"),
    ),
    (
        "door_drawing",
        "Do you need a cabinet door drawing? (buttons, lights, e-stop or HMI mounted on the door)",
        "choice",
        (DOOR_YES, DOOR_NO),
    ),
    (
        "project_name",
        "What should we call this cabinet project?",
        "text",
        (),
    ),
)


@dataclass(frozen=True)
class RecommendedDevice:
    key: str
    type_id: str
    label: str
    catalog_id: str | None
    catalog_number: str
    vendor: str
    name: str
    reason: str
    suggestion: DeviceSuggestion


def blank_ai_answers() -> dict[str, str]:
    return {key: "" for key, _label, _kind, _options in AI_BUILD_QUESTIONS}


def interview_suggestion(answers: dict[str, str], question_key: str) -> str:
    """Short AI tip shown under the current interview question."""
    duty = (answers.get("duty") or "").lower()
    has_motor = (answers.get("has_motor") or "").strip().lower()
    start_stop = (answers.get("start_stop") or "").strip().lower()
    has_estop = (answers.get("has_estop") or "").strip().lower()
    tips: dict[str, str] = {
        "duty": "Say what the machine does in plain words (conveyor, pump, weld cell…). That steers motors, valves, and sensors.",
        "supply_voltage": "Most industrial cabinets are 480 VAC three-phase. Pick Other if you are not sure yet.",
        "control_voltage": "24 VDC is the usual educational / machine-control default for buttons and sensors.",
        "has_motor": "A Yes answer will add motor and drive or contactor suggestions from the library.",
        "motor_control": "VFD when speed matters; contactor for simple on/off. Not sure → AI suggests a VFD on 480 V and a contactor otherwise.",
        "start_stop": "Pushbuttons land as discrete PLC inputs. HMI means operator actions on a screen.",
        "operator_devices": "AI suggests Start + Stop for pushbutton control. Add HOA when Hand/Auto mode is needed. Lights help the operator see Run/Fault.",
        "has_control_relays": "Control relays (interposing) keep PLC outputs off high coil currents. AI suggests one when motors, contactors, or solenoids are present.",
        "has_estop": "UL 508A teaching panels almost always show an e-stop. Dual-channel e-stop + safety relay is the safer learning pattern.",
        "has_safety_relay": "If e-stop is Yes, AI suggests a safety relay from the library unless you say No.",
        "has_hmi": "Pick Yes when operators use a touchscreen. Catalog numbers come only from the library.",
        "door_drawing": "Yes adds a DOOR elevation sheet with the door-mounted devices. No skips it - "
                        "pick No when the buttons live on a remote operator station or there are none.",
        "project_name": "This name becomes the open cabinet — Programming will ask questions about these devices next.",
        "manufacturer": "Every part the AI picks comes from this maker when the library has one (Allen-Bradley, "
                        "Siemens or Omron). Best fit mixes makers. You can swap any part afterwards.",
        "light_curtain": "A light curtain is an invisible fence of light beams across the opening where the "
                         "operator's hands go. Break a beam and the machine stops. It wires to a safety relay "
                         "(added for you) - the PLC only watches it.",
        "stack_light": "A tower light on top of the cabinet: GREEN ready / running, AMBER light curtain broken, "
                       "RED E-stop pressed. The program rungs for it are written for you.",
    }
    base = tips.get(question_key, "Answer in plain words. You can change devices on the next screen.")
    extras: list[str] = []
    if question_key == "operator_devices":
        if "push" in start_stop or start_stop == "both" or start_stop == "not sure":
            extras.append("Suggested: Start pushbutton + Stop pushbutton.")
        if "conveyor" in duty or "pump" in duty or "motor" in duty:
            extras.append("Suggested: HOA selector when operators need Hand/Auto.")
        if has_motor.startswith("y"):
            extras.append("Suggested: green Run light.")
    if question_key == "has_control_relays" and (
        has_motor.startswith("y") or "contactor" in (answers.get("motor_control") or "").lower()
    ):
        extras.append("Suggested: Yes — add at least one interposing control relay.")
    if question_key == "has_safety_relay" and has_estop.startswith("y"):
        extras.append("Suggested: Yes — pair the e-stop with a safety relay.")
    if question_key == "motor_control" and has_motor.startswith("y"):
        supply = (answers.get("supply_voltage") or "")
        if "480" in supply:
            extras.append("Suggested: VFD (variable speed) for a 480 VAC motor learning cabinet.")
        else:
            extras.append("Suggested: Contactor (across-the-line) unless you need speed control.")
    if question_key in {"door_drawing", "manufacturer", "light_curtain", "stack_light"}:
        extras.append(f"Suggested: {interview_default(answers, question_key)}.")
    if extras:
        return base + "  " + " ".join(extras)
    return base


_MOTOR_WORDS = ("motor", "conveyor", "pump", "fan", "mixer", "spindle", "blower", "compressor", "drive", "agitator")


def interview_default(answers: dict[str, str], question_key: str) -> str:
    """The concrete answer the AI recommends for one question ('' when it cannot guess, e.g. duty)."""
    duty = (answers.get("duty") or "").lower()
    supply = answers.get("supply_voltage") or ""
    has_motor = (answers.get("has_motor") or "").lower()
    start_stop = (answers.get("start_stop") or "").lower()
    motorish = has_motor.startswith("y") or (not has_motor and any(w in duty for w in _MOTOR_WORDS))
    estop = (answers.get("has_estop") or "Yes").lower().startswith("y")
    if question_key == "manufacturer":
        return "Allen-Bradley"
    if question_key == "light_curtain":
        return LC_YES if any(w in duty for w in _GUARD_WORDS) else "No"
    if question_key == "stack_light":
        guarded = (answers.get("light_curtain") or "").lower().startswith("y")
        return STACK_YES if motorish or guarded or estop else "No"
    if question_key == "supply_voltage":
        return "480 VAC"
    if question_key == "control_voltage":
        return "24 VDC"
    if question_key == "has_motor":
        return "Yes" if any(w in duty for w in _MOTOR_WORDS) else "No"
    if question_key == "motor_control":
        if not motorish:
            return "No motor"
        return "VFD (variable speed)" if "480" in supply or not supply else "Contactor (across-the-line)"
    if question_key == "start_stop":
        return "Pushbuttons"
    if question_key == "operator_devices":
        picks = ["Start pushbutton", "Stop pushbutton", "Reset pushbutton"]
        if motorish:
            picks.append("Run indicator light")
        picks.append("Fault indicator light")
        return "|".join(picks)
    if question_key == "has_control_relays":
        contactor = "contactor" in (answers.get("motor_control") or "").lower()
        return "Yes — add control relays" if motorish or contactor else "No"
    if question_key == "has_estop":
        return "Yes"
    if question_key == "has_safety_relay":
        return "Yes" if estop else "No"
    if question_key == "has_hmi":
        return "Yes" if "touch" in start_stop or start_stop == "both" else "No"
    if question_key == "door_drawing":
        door = bool(answers.get("operator_devices")) or estop or (answers.get("has_hmi") or "").lower().startswith("y")
        return DOOR_YES if door else DOOR_NO
    if question_key == "project_name":
        words = (answers.get("duty") or "").strip().split()
        return " ".join(words[:5]).title() if words else "AI cabinet build"
    return ""


def interview_from_ai_answers(answers: dict[str, str]) -> dict[str, str]:
    """Map AI answers into the project interview keys Guide build already uses."""
    duty = (answers.get("duty") or "").strip()
    start_stop = (answers.get("start_stop") or "").strip().lower()
    has_hmi = (answers.get("has_hmi") or "").strip().lower()
    has_motor = (answers.get("has_motor") or "").strip().lower()
    has_estop = (answers.get("has_estop") or "").strip().lower()
    operator = (answers.get("operator_devices") or "").strip()
    bits = [duty]
    if has_motor.startswith("y"):
        bits.append("motor drive")
    if "push" in start_stop or start_stop == "both":
        bits.append("start stop pushbutton")
    if "touch" in start_stop or "hmi" in start_stop or has_hmi.startswith("y"):
        bits.append("hmi operator screen")
    if has_estop.startswith("y"):
        bits.append("safety e-stop")
    if "selector" in operator.lower():
        bits.append("hoa selector")
    if "relay" in (answers.get("has_control_relays") or "").lower() or (
        answers.get("has_control_relays") or ""
    ).strip().lower().startswith("y"):
        bits.append("control relay")
    return {
        "duty": " ".join(part for part in bits if part).strip() or duty,
        "supply_voltage": _clean_choice(answers.get("supply_voltage", "")),
        "control_voltage": _clean_choice(answers.get("control_voltage", "")),
        "environment": "",
        "enclosure_type": "",
        "grounding": "",
        "sccr": "",
        "disconnect": "",
        "branch_protection": "",
        "power_control_separation": "",
        "field_wiring": "",
        "has_motor": (answers.get("has_motor") or "").strip(),
        "motor_control": (answers.get("motor_control") or "").strip(),
        "start_stop": (answers.get("start_stop") or "").strip(),
        "operator_devices": operator,
        "has_control_relays": (answers.get("has_control_relays") or "").strip(),
        "has_estop": (answers.get("has_estop") or "").strip(),
        "has_safety_relay": (answers.get("has_safety_relay") or "").strip(),
        "has_hmi": (answers.get("has_hmi") or "").strip(),
        "door_drawing": (answers.get("door_drawing") or "").strip(),
        "manufacturer": (answers.get("manufacturer") or "").strip(),
        "light_curtain": (answers.get("light_curtain") or "").strip(),
        "stack_light": (answers.get("stack_light") or "").strip(),
    }


def _clean_choice(value: str) -> str:
    text = (value or "").strip()
    if not text or "not sure" in text.lower() or text.lower().startswith("other"):
        return ""
    return text


def _multi_parts(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def ab_catalog_for_type(library: Library, type_id: str) -> CatalogItem | None:
    for item in library.catalog:
        if item.type_id == type_id and "allen" in item.vendor.lower():
            return item
    return None


def catalog_by_prefer_id(library: Library, catalog_id: str | None) -> CatalogItem | None:
    if not catalog_id:
        return None
    return library.catalog_by_id.get(catalog_id)


def catalog_label(library: Library, catalog_id: str | None) -> tuple[str, str, str]:
    """Return (catalog_number, vendor, name). Never invent a number."""
    if not catalog_id:
        return CATALOG_NOT_IDENTIFIED, "", ""
    item = library.catalog_by_id.get(catalog_id)
    if item is None:
        return CATALOG_NOT_IDENTIFIED, "", ""
    number = (item.catalog or "").strip() or CATALOG_NOT_IDENTIFIED
    return number, item.vendor, item.name


def _wants_pushbuttons(answers: dict[str, str]) -> bool:
    start_stop = (answers.get("start_stop") or "").strip().lower()
    return "push" in start_stop or start_stop == "both" or start_stop == "not sure"


def _operator_selection(answers: dict[str, str]) -> set[str]:
    parts = {p.lower() for p in _multi_parts(answers.get("operator_devices", ""))}
    if parts:
        return parts
    # Defaults when the multi question was skipped / empty.
    selected: set[str] = set()
    if _wants_pushbuttons(answers):
        selected.update({"start pushbutton", "stop pushbutton"})
    return selected


def _wants_control_relays(answers: dict[str, str]) -> bool:
    raw = (answers.get("has_control_relays") or "").strip().lower()
    if raw.startswith("y") or "add control" in raw:
        return True
    if raw.startswith("n") and "not sure" not in raw:
        return False
    # AI default suggestion
    has_motor = (answers.get("has_motor") or "").strip().lower().startswith("y")
    motor_ctrl = (answers.get("motor_control") or "").lower()
    return has_motor or "contactor" in motor_ctrl


def _wants_safety_relay(answers: dict[str, str]) -> bool:
    raw = (answers.get("has_safety_relay") or "").strip().lower()
    if raw.startswith("y"):
        return True
    if raw.startswith("n") and "not sure" not in raw:
        return False
    return (answers.get("has_estop") or "").strip().lower().startswith("y")


def recommend_type_ids(answers: dict[str, str]) -> list[str]:
    """Unique type ids (for tests / summaries). Order matches placement priority."""
    return list(dict.fromkeys(slot[0] for slot in recommend_slots(answers)))


def recommend_slots(answers: dict[str, str]) -> list[tuple[str, str, str | None, dict[str, str], str]]:
    """Return (type_id, key, prefer_catalog_id, field_overrides, reason) slots."""
    has_motor = (answers.get("has_motor") or "").strip().lower()
    start_stop = (answers.get("start_stop") or "").strip().lower()
    has_estop = (answers.get("has_estop") or "").strip().lower()
    has_hmi = (answers.get("has_hmi") or "").strip().lower()
    duty = (answers.get("duty") or "").lower()
    motor_ctrl = (answers.get("motor_control") or "").strip().lower()
    supply = (answers.get("supply_voltage") or "")
    control = _clean_choice(answers.get("control_voltage", "")) or "24 VDC"
    operator = _operator_selection(answers)

    slots: list[tuple[str, str, str | None, dict[str, str], str]] = []

    def add(
        type_id: str,
        key: str,
        prefer: str | None,
        fields: dict[str, str],
        reason: str,
    ) -> None:
        slots.append((type_id, key, prefer, fields, reason))

    add("plc", "plc", "ab-compactlogix-5380", {}, "Every learning cabinet gets a PLC from the starter library.")
    add("power_supply", "power_supply", "ab-1606-xls", {"output_voltage": control}, "24 VDC (or control) supply for buttons, relays, and sensors.")
    no_io = {"io_direction": "Network / no discrete I/O"}
    if "VAC" in supply or not supply:
        add("disconnect", "disconnect", "ab-194e-a40", {"tag": "DS1", **no_io},
            "Main disconnect: UL 508A needs a lockable means of disconnect for the incoming power.")
    add("breaker", "cb_control", "ab-1489-m1c100", {"tag": "CB1", **no_io},
        "Branch protection for the control power supply.")
    add("terminal_block", "tb_field", "ab-1492-j3-strip", {"tag": "TB1", **no_io},
        "Field wiring lands on terminals, never straight on the PLC.")

    wants_motor = has_motor.startswith("y") or any(
        word in duty for word in ("motor", "conveyor", "pump", "drive", "vfd")
    )
    if wants_motor:
        want_vfd = "vfd" in motor_ctrl or "variable" in motor_ctrl or (
            ("not sure" in motor_ctrl or "both" in motor_ctrl or not motor_ctrl) and "480" in supply
        )
        want_contactor = "contactor" in motor_ctrl or "across" in motor_ctrl or (
            ("not sure" in motor_ctrl or "both" in motor_ctrl or not motor_ctrl) and "480" not in supply
        )
        if "both" in motor_ctrl:
            want_vfd = True
            want_contactor = True
        if not want_vfd and not want_contactor:
            want_vfd = "480" in supply
            want_contactor = not want_vfd
        if want_vfd:
            add("vfd", "vfd", "ab-powerflex-525", {}, "Motor answer + interview → VFD from the library.")
        if want_contactor:
            add(
                "contactor",
                "contactor",
                "ab-contactor-100c",
                {"coil_voltage": control},
                "Across-the-line / contactor control from the library.",
            )
            add("motor_protector", "mp_motor", "ab-140mt-c-b63", {"tag": "MP1", "io_direction": "Network / no discrete I/O"},
                "Motor branch protection and overload ahead of the contactor.")
        add("motor", "motor", None, {}, "Motor load for the drive or contactor (catalog may be generic).")

    if has_estop.startswith("y") or has_estop == "not sure":
        add("estop", "estop", "ab-estop-800t", {"voltage": control}, "E-stop from the starter library.")
    if _wants_safety_relay(answers):
        add(
            "safety_relay",
            "safety_relay",
            "ab-guardmaster-msr127",
            {},
            "AI suggests a safety relay when e-stop is part of the panel.",
        )

    if (
        has_hmi.startswith("y")
        or "touch" in start_stop
        or "hmi" in start_stop
        or start_stop == "both"
    ):
        add("hmi", "hmi", "ab-panelview-5310", {}, "Operator touchscreen from the library.")

    if "start pushbutton" in operator or (not operator and _wants_pushbuttons(answers)):
        add(
            "pushbutton",
            "pb_start",
            "ab-pb-green-start",
            {"function": "Start", "contact": "NO momentary", "color": "Green", "voltage": control, "tag": "PB_Start"},
            "Start pushbutton selected in the interview.",
        )
    if "stop pushbutton" in operator or (not operator and _wants_pushbuttons(answers)):
        add(
            "pushbutton",
            "pb_stop",
            "ab-pb-red-stop",
            {"function": "Stop", "contact": "NC momentary", "color": "Red", "voltage": control, "tag": "PB_Stop"},
            "Stop pushbutton selected in the interview.",
        )
    if any("selector" in part for part in operator):
        prefer = "ab-selector-hoa"
        add(
            "pushbutton",
            "pb_selector",
            prefer,
            {
                "function": "Selector HOA",
                "contact": "Maintained",
                "color": "Black",
                "voltage": control,
                "tag": "SS_HOA",
            },
            "HOA / selector switch selected in the interview.",
        )
    if any("reset" in part for part in operator):
        add(
            "pushbutton",
            "pb_reset",
            "ab-pb-reset",
            {"function": "Reset", "contact": "NO momentary", "color": "Blue", "voltage": control, "tag": "PB_Reset"},
            "Reset pushbutton selected in the interview.",
        )
    if any("run indicator" in part for part in operator):
        add(
            "light",
            "lt_run",
            "ab-indicator-green",
            {"function": "Run", "color": "Green", "voltage": control, "tag": "LT_Run"},
            "Run indicator light selected in the interview.",
        )
    if any("fault indicator" in part for part in operator):
        add(
            "light",
            "lt_fault",
            "ab-indicator-red",
            {"function": "Fault", "color": "Red", "voltage": control, "tag": "LT_Fault"},
            "Fault indicator light selected in the interview.",
        )

    if _wants_control_relays(answers):
        add(
            "relay",
            "relay_cr1",
            "ab-relay-700ha",
            {
                "coil_voltage": control,
                "contact_form": "2NO+2NC",
                "amp_rating": "10 A",
                "function": "Interposing",
                "tag": "CR1",
            },
            "Control / interposing relay from the starter library (interview selection or AI suggestion).",
        )
        if wants_motor:
            add(
                "relay",
                "relay_cr2",
                "ab-relay-700hk",
                {
                    "coil_voltage": control,
                    "contact_form": "4PDT",
                    "amp_rating": "10 A",
                    "function": "Seal-in / hold",
                    "tag": "CR2",
                },
                "Second control relay suggested for motor seal-in / auxiliary contacts.",
            )

    if (answers.get("light_curtain") or "").strip().lower().startswith("y"):
        add("light_curtain", "light_curtain", "ab-440l-guardshield-640",
            {"tag": "LC1", "io_direction": "Input",
             "description": "Light curtain - status to PLC: ON = beam broken (safety relay does the stopping)"},
            "Light curtain chosen in the interview: guards the operator opening.")
        add("safety_relay", "safety_relay_lc", "ab-guardmaster-gsr-si", {"tag": "SR_LC"},
            "Safety relay that monitors the light curtain OSSD outputs and drops the hazard power.")
    if (answers.get("stack_light") or "").strip().lower().startswith("y"):
        for color, function, prefer in (("Green", "Ready / running", "ab-stack-855t-green"),
                                        ("Amber", "Light curtain broken", "ab-stack-855t-amber"),
                                        ("Red", "E-stop", "ab-stack-855t-red")):
            add("light", f"stack_{color.lower()}", prefer,
                {"function": function, "color": color, "voltage": control, "tag": f"STK_{color}",
                 "mounting": "Field device", "io_direction": "Output"},
                f"Stack light {color.lower()} segment: {function.lower()}.")

    return slots


def _vendor_pick(library: Library, type_id: str, maker: str, preferred: CatalogItem | None,
                 fields: dict[str, str]) -> CatalogItem | None:
    """Same kind of part from the preferred maker (color / function / mounting matched), or None."""
    words = {w.lower() for w in (fields.get("color", ""), fields.get("function", "")) if w}
    if preferred is not None:
        words |= {w for w in ("start", "stop", "reset", "selector", "stack", "pilot", "green", "red", "amber", "blue")
                  if w in (preferred.name + " " + preferred.summary).lower()}
    best, best_score = None, -1
    for item in library.catalog:
        if item.type_id != type_id or item.vendor != maker:
            continue
        hay = (item.name + " " + item.summary + " " + " ".join(v for _k, v in item.defaults)).lower()
        score = sum(2 for w in words if w and w in hay)
        if preferred is not None and dict(item.defaults).get("mounting") == preferred.default_map().get("mounting"):
            score += 1
        if score > best_score:
            best, best_score = item, score
    return best


def recommend_devices(
    library: Library,
    profile: StandardsProfile,
    answers: dict[str, str],
    *,
    project: Project | None = None,
) -> list[RecommendedDevice]:
    """Build recommendations from answers. AB catalog only when the library has one."""
    base = project or new_blank_project()
    interview = interview_from_ai_answers(answers)
    used = used_wire_numbers(base)
    out: list[RecommendedDevice] = []
    for type_id, key, prefer_id, field_overrides, reason in recommend_slots(answers):
        if type_id not in library.types:
            continue
        preferred = catalog_by_prefer_id(library, prefer_id)
        if preferred is not None and preferred.type_id != type_id:
            preferred = None
        ab = preferred or ab_catalog_for_type(library, type_id)
        maker = (answers.get("manufacturer") or "").strip()
        if maker in MAKERS[:3] and (ab is None or ab.vendor != maker):
            ab = _vendor_pick(library, type_id, maker, ab, field_overrides) or ab
        tag_hint = (field_overrides.get("tag") or "").strip() or None
        suggestion = suggest_device(
            library, profile, base, type_id, interview, tag=tag_hint, used=used
        )
        if ab is not None:
            fields = dict(suggestion.fields)
            fields.update(ab.default_map())
            fields["vendor"] = ab.vendor
            fields["catalog"] = ab.catalog
            fields["description"] = ab.summary or fields.get("description", "")
            fields.update({k: v for k, v in field_overrides.items() if v})
            if tag_hint:
                fields["tag"] = tag_hint
            suggestion = DeviceSuggestion(
                type_id=type_id,
                catalog_id=ab.id,
                stock=True,
                reason=reason or f"Allen-Bradley part from the starter library ({ab.catalog}).",
                wire_role=suggestion.wire_role,
                fields=fields,
            )
            catalog_number, vendor, name = catalog_label(library, ab.id)
            catalog_id = ab.id
        else:
            fields = dict(suggestion.fields)
            fields["catalog"] = CATALOG_NOT_IDENTIFIED
            if not fields.get("vendor"):
                fields["vendor"] = "Generic / Modbus"
            fields = _fill_class_defaults(type_id, fields, interview)
            fields.update({k: v for k, v in field_overrides.items() if v})
            if tag_hint:
                fields["tag"] = tag_hint
            suggestion = DeviceSuggestion(
                type_id=type_id,
                catalog_id=None,
                stock=False,
                reason=reason or "No Allen-Bradley catalog for this class in the library.",
                wire_role=suggestion.wire_role,
                fields=fields,
            )
            catalog_id = None
            catalog_number = CATALOG_NOT_IDENTIFIED
            vendor = fields.get("vendor") or ""
            name = library.types[type_id].label
        equipment = library.types[type_id]
        label = equipment.label
        if type_id == "pushbutton" and field_overrides.get("function"):
            label = f"{equipment.label} ({field_overrides['function']})"
        elif type_id == "light" and field_overrides.get("function"):
            label = f"{equipment.label} ({field_overrides['function']})"
        elif type_id == "relay" and field_overrides.get("tag"):
            label = f"{equipment.label} ({field_overrides['tag']})"
        out.append(
            RecommendedDevice(
                key=key,
                type_id=type_id,
                label=label,
                catalog_id=catalog_id,
                catalog_number=catalog_number,
                vendor=vendor,
                name=name or equipment.label,
                reason=suggestion.reason,
                suggestion=suggestion,
            )
        )
        # Keep tag uniqueness for subsequent suggest_device calls on same blank project.
        base.items.append(
            PlacedItem(
                id=new_id(),
                library_id=suggestion.catalog_id,
                type_id=type_id,
                x=0,
                y=0,
                fields=dict(suggestion.fields),
            )
        )
    return out


def apply_recommendations(
    library: Library,
    project: Project,
    recommendations: list[RecommendedDevice],
    *,
    selected_keys: set[str] | None = None,
    selected_type_ids: set[str] | None = None,
    profile: StandardsProfile | None = None,
) -> Project:
    """Place confirmed recommendations onto a project with wiring continuity filled."""
    from cabinet_studio.services.suggestions import enrich_with_wiring_assist
    from cabinet_studio.services.wiring_assist import remember_device_fields
    from cabinet_studio.services.standards import default_profile

    standards = profile or default_profile()
    for rec in recommendations:
        if selected_keys is not None and rec.key not in selected_keys:
            continue
        if selected_type_ids is not None and rec.type_id not in selected_type_ids:
            continue
        suggestion = rec.suggestion
        fields = dict(suggestion.fields)
        fields = enrich_with_wiring_assist(
            library,
            standards,
            project,
            rec.type_id,
            fields,
            interview=project.interview,
        )
        from cabinet_studio.services.wiring_assist import suggest_field

        continuity_keys = ["io_address", "wire_color"]
        if rec.type_id in {"plc", "hmi", "ethernet_switch", "vfd"}:
            continuity_keys.append("ip_address")
        if rec.type_id == "io_module":
            continuity_keys.extend(["parent_tag", "slot"])
        for key in continuity_keys:
            assist = suggest_field(
                project,
                library,
                standards,
                type_id=rec.type_id,
                field_key=key,
                prior=fields,
                interview=project.interview,
            )
            if assist.value:
                fields[key] = assist.value
        if rec.type_id != "io_module":
            fields.pop("slot", None)
            fields.pop("parent_tag", None)
        if rec.type_id not in {"plc", "hmi", "ethernet_switch", "vfd"}:
            fields.pop("ip_address", None)
        fields = _fill_class_defaults(rec.type_id, fields, project.interview)
        # Preserve interview-chosen tags / functions after defaults.
        for keep_key in ("tag", "function", "color", "contact", "coil_voltage", "contact_form"):
            prior = suggestion.fields.get(keep_key)
            if prior:
                fields[keep_key] = prior
        x, y = next_free_position(project, library, rec.type_id)
        project.items.append(
            PlacedItem(
                id=new_id(),
                library_id=suggestion.catalog_id,
                type_id=rec.type_id,
                x=x,
                y=y,
                fields=fields,
            )
        )
        standards = remember_device_fields(
            project,
            standards,
            type_id=rec.type_id,
            fields=fields,
            interview=project.interview,
        )
    suggest_enclosure_for(library, project)
    return project


def suggest_enclosure_for(library: Library, project: Project) -> str:
    """Pick the smallest Hoffman enclosure whose backplate holds every plate device in power
    zones with duct spacing, unless the interview already chose one. Returns the label."""
    from cabinet_studio.services.drawings import _item_is_door_mount, device_tag
    from cabinet_studio.services.enclosure_select import apply_enclosure_selection
    from cabinet_studio.services.panel_zones import ZONES, item_inches, suggest_enclosure, zone_of

    interview = dict(project.interview or {})
    if (interview.get("enclosure_selection") or "").strip():
        return interview["enclosure_selection"]
    devices = []
    for item in project.items:
        zone = zone_of(item.type_id, device_tag(item), item.fields.get("mounting", ""))
        if zone in ZONES and not _item_is_door_mount(item):
            devices.append((item.id, zone, *item_inches(library, item)))
    if not devices:
        return ""
    label, _fits = suggest_enclosure(devices)
    if label:
        interview["enclosure_selection"] = label
        apply_enclosure_selection(project, interview)
    return label


def _fill_class_defaults(type_id: str, fields: dict[str, str], interview: dict[str, str]) -> dict[str, str]:
    """Fill common blank ratings without inventing catalog numbers."""
    out = dict(fields)
    supply = (interview.get("supply_voltage") or "").strip()
    control = (interview.get("control_voltage") or "").strip() or "24 VDC"

    def blank(key: str) -> bool:
        return not str(out.get(key, "")).strip()

    if type_id == "motor":
        if blank("horsepower"):
            out["horsepower"] = "5 HP" if "480" in supply or "460" in supply else "1 HP"
        if blank("rpm"):
            out["rpm"] = "1750"
        if blank("voltage"):
            out["voltage"] = supply or "460 VAC"
        if blank("fla"):
            out["fla"] = "7.6 A" if "5 HP" in out.get("horsepower", "") else "3.0 A"
        if blank("torque"):
            out["torque"] = "15 lb-ft" if "5 HP" in out.get("horsepower", "") else "3 lb-ft"
        if blank("pinout"):
            out["pinout"] = "T1 T2 T3 / PE"
    elif type_id == "vfd":
        if blank("horsepower"):
            out["horsepower"] = "5 HP" if "480" in supply or "460" in supply else "1 HP"
        if blank("voltage"):
            out["voltage"] = supply or "480 VAC"
        if blank("fla"):
            out["fla"] = "10.5 A" if "5 HP" in out.get("horsepower", "") else "4.2 A"
        if blank("control_mode"):
            out["control_mode"] = "V/Hz"
        if blank("comms"):
            out["comms"] = "EtherNet/IP"
    elif type_id == "power_supply":
        if blank("input_voltage"):
            out["input_voltage"] = supply or "480 VAC"
        if blank("output_voltage"):
            out["output_voltage"] = control
        if blank("output_current"):
            out["output_current"] = "10 A"
        if blank("phases"):
            out["phases"] = "3" if "480" in (supply or "") or "3" in (supply or "") else "1"
    elif type_id == "contactor":
        if blank("coil_voltage"):
            out["coil_voltage"] = control
        if blank("poles"):
            out["poles"] = "3"
        if blank("amp_rating"):
            out["amp_rating"] = "25 A"
    elif type_id == "relay":
        if blank("coil_voltage"):
            out["coil_voltage"] = control
        if blank("contact_form"):
            out["contact_form"] = "2NO+2NC"
        if blank("amp_rating"):
            out["amp_rating"] = "10 A"
        if blank("function"):
            out["function"] = "Interposing"
    elif type_id == "pushbutton":
        if blank("function"):
            out["function"] = "Start"
        if blank("contact"):
            out["contact"] = "NO momentary"
        if blank("color"):
            out["color"] = "Green"
        if blank("voltage"):
            out["voltage"] = control
    elif type_id == "estop":
        if blank("contact_config"):
            out["contact_config"] = "2NC"
        if blank("reset_style"):
            out["reset_style"] = "Twist"
        if blank("voltage"):
            out["voltage"] = control
    elif type_id == "hmi":
        if blank("screen_size"):
            out["screen_size"] = "7 in"
        if blank("protocol"):
            out["protocol"] = "EtherNet/IP"
    elif type_id == "plc":
        if blank("slot_count"):
            out["slot_count"] = "8"
        if blank("protocol"):
            out["protocol"] = "EtherNet/IP"
    elif type_id == "light":
        if blank("color"):
            out["color"] = "Green"
        if blank("voltage"):
            out["voltage"] = control
        if blank("function"):
            out["function"] = "Run"
    return out


def project_name_from_answers(answers: dict[str, str]) -> str:
    name = (answers.get("project_name") or "").strip()
    return name or "AI cabinet build"
