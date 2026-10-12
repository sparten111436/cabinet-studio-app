"""Programming screen: questions, visual ladder, editable PLC/HMI text (not a download)."""

from __future__ import annotations

import html
import json
import os
import tempfile
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path as _Path

import customtkinter as ctk

from cabinet_studio import __version__ as _CS_VERSION
from cabinet_studio.models.project import Project
from cabinet_studio.services.ladder_history import LadderHistory
from cabinet_studio.services.ladder_ir import program_rung_to_elements, program_to_ladder_ir, split_member
from cabinet_studio.services.ladder_print import comment_extra_height, comment_lines
from cabinet_studio.services.ladder_sim import ScanSimulator, program_rung_flow_keys
from cabinet_studio.services.sim_autorun import normal_run_plan
from cabinet_studio.services.sim_plant import PlantModel, is_safety_tag
from cabinet_studio.ui.hover_tip import attach as attach_tip
from cabinet_studio.ui.rung_help import rung_help
from cabinet_studio.services.sim_explain import explain_part, explain_rung, flow_order, rung_summary, writers
from cabinet_studio.services.ladder_tools import (
    WatchTrendBuffer,
    add_rung_to_routine,
    apply_verify_fix,
    clip_from_text,
    clip_to_text,
    copy_instruction,
    copy_rungs,
    cross_reference,
    duplicate_rung,
    ensure_routine,
    find_tag_refs,
    format_cross_reference_html,
    list_routines,
    move_rung,
    paste_instruction,
    move_instruction,
    element_tag,
    delete_instruction,
    replace_instruction,
    insert_instruction,
    paste_rungs,
    replace_tag,
    set_tag_alias,
    set_tag_description,
    tag_table,
    valid_tag_name,
    verify_program,
    verify_summary,
)
from cabinet_studio.services.plcopen_xml import (
    PLCOPEN_IMPORT_WARNING,
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
    import_plcopen_xml_to_program_checked,
)
from cabinet_studio.services.programming import (
    LEARNING_NOTE,
    PROGRAM_QUESTIONS,
    add_counter_rung,
    add_aoi_template_rungs,
    add_compare_rung,
    add_latch_rung,
    add_math_rung,
    add_mid_coil_rung,
    add_nested_or_rung,
    add_oneshot_rung,
    add_rung_from_elements,
    add_rung,
    add_timer_rung,
    build_starter_program,
    cabinet_device_tags,
    default_design_answers,
    delete_rung,
    device_hover_detail,
    devices_by_tag,
    edit_rung,
    append_series_contact,
    append_parallel_contact,
    empty_program,
    flatten_contacts,
    format_hmi_text,
    format_plc_text,
    program_from_dict,
    program_looks_edited,
    program_to_dict,
    refresh_plc_text,
    rung_has_seal_in,
    rung_instruction_list,
    set_instruction_notes,
    set_rung_comment,
    set_rung_timer,
    simulation_rung_tags,
)
from cabinet_studio.ui.ai_assistant import AiAssistantWindow
from cabinet_studio.ui.commands import CommandRegistry
from cabinet_studio.ui.dialogs import ask_choice
from cabinet_studio.ui.theme import (
    BG,
    BLUE,
    BLUE_HOVER,
    BORDER,
    CYAN,
    ENTRY,
    HOVER,
    MUTED,
    ORANGE,
    PALETTE,
    PANEL,
    TEXT,
    TIP_BG,
    TIP_BORDER,
    TIP_TEXT,
    TRACK_HOVER,
    bind_theme_redraw,
    c,
    current_mode,
    is_dark,
    set_mode,
    toggle_mode,
    ghost_button,
    ladder_palette,
    primary_button,
    section_label,
)
from cabinet_studio.ui.prefs import load_width
from cabinet_studio.ui.shell.sim_toolbar import SimToolbar
from cabinet_studio.ui.shell.statusbar import EDU_BADGE, StatusBar
from cabinet_studio.ui.studio.organizer import ControllerOrganizer
from cabinet_studio.ui.studio.palette import InstructionPalette
from cabinet_studio.ui.studio.program_wizard import ProgramWizard
from cabinet_studio.ui.studio.properties import PropertiesPane
from cabinet_studio.ui.util import (
    apply_saved_geometry,
    bind_geometry_autosave,
    remember_window_geometry,
    ui_geometry_path,
)

# Pop-out canvas geometry key (saves/ui_window_geometry.json)
_PROG_CANVAS_GEOM_KEY = "programming_canvas"
_PROG_CANVAS_MIN = (1000, 700)
_PROG_CANVAS_DEFAULT = (1280, 860)
_PROG_RUNG_EDITOR_GEOM_KEY = "programming_rung_editor"
_PROG_RUNG_EDITOR_MIN = (560, 240)
_PROG_RUNG_EDITOR_DEFAULT = (900, 330)
_PROG_RUNG_EDITOR_TOP_PREF = "programming_rung_editor_on_top"
_PROG_RUNG_EDITOR_FLOAT_PREF = "programming_rung_editor_floating"
_PROG_FORCE_GEOM_KEY = "programming_force_strip"   # v0.3.7 floating Force / I/O strip
_PROG_FORCE_MIN = (520, 160)
_PROG_FORCE_DEFAULT = (1100, 200)
_PROG_FORCE_FLOAT_PREF = "programming_force_strip_floating"
# v0.3.20 rung-by-rung simulation
_PROG_SIM_SPEED_PREF = "programming_sim_speed"
_PROG_SIM_ON_TOP_PREF = "programming_sim_on_top"
# v0.3.22 layout + Follow rung
_PROG_LAYOUT_PREF = "programming_layout"
_PROG_FOLLOW_PREF = "prog_follow_rung"
_PROG_PARTS_PREF = "prog_sim_each_part"
_SIM_PART_MIN_MS = 120
_SIM_AUTO_POLL_MS = 250
_SIM_AUTO_MIN_STEP_MS = 1000
_PART_HILITE = "#f2c200"
_LAYOUTS = ("studio", "classic")
_FOLLOW_SUSPEND_S = 3.0
_FOLLOW_MARGIN = 40
# v0.3.23 Studio panes (Controller Organizer | ladder | Properties)
_PANE_PREFS = {
    "organizer": ("prog_organizer_visible", "prog_organizer_width", 240, 160, 520),
    "properties": ("prog_properties_visible", "prog_properties_width", 300, 200, 560),
}
_DEVICE_TIP = ("Real PLC / HMI: assign I/O addresses, export import-ready files (Studio 5000 L5X, TIA / Sysmac tag "
               "tables, PLCopen) with step-by-step instructions, and a live Ethernet link to read and watch tags. "
               "Download itself is done in the maker's software.")
_SIM_SPEEDS = {
    "0.25 s / rung": 250,
    "0.5 s / rung": 500,
    "1 s / rung": 1000,
    "2 s / rung": 2000,
    "PLC speed (full scan)": 0,
}
_SIM_DEFAULT_SPEED = "1 s / rung"
_SIM_SCAN_TICK_MS = 120
_SIM_TIMER_TICK_MS = 100
_SIM_FIX_POLL_MS = 500
_SIM_CURSOR_OUTLINE = "#1f9d55"
_SIM_CURSOR_FILL = "#dff5e6"


def _ui_prefs_path() -> _Path:
    """Small UI booleans (keep-on-top, floating) next to ui_window_geometry.json."""
    return ui_geometry_path().with_name("ui_prefs.json")


def _load_ui_pref(key: str, default=None):
    try:
        data = json.loads(_ui_prefs_path().read_text(encoding="utf-8"))
        return data.get(key, default) if isinstance(data, dict) else default
    except Exception:
        return default


def _save_ui_pref(key: str, value) -> None:
    path = _ui_prefs_path()
    data: dict = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        data = {}
    data[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        pass

# Ladder drawing palette (light sheet on dark chrome, like shop prints).
LADDER_BG = "#d8d4cc"
LADDER_RAIL = "#1a1a22"
LADDER_WIRE = "#2a2a32"
LADDER_SYMBOL = "#0d0d0f"
LADDER_LABEL = "#1c1c22"
LADDER_MUTED = "#5a5a66"
LADDER_SELECT = "#2f6bff"
LADDER_COIL = "#0b5e4a"
LADDER_ACTIVE = "#f5a623"
LADDER_ACTIVE_FILL = "#ffe6a8"
LADDER_PULSE = "#ff3b5c"
# v0.3.6 live power-flow (Studio / TIA online-monitor style, ideas only)
LADDER_POWER = "#12a150"       # energized wire / TRUE instruction
LADDER_TRUE_FILL = "#c8f0d4"
LADDER_FORCE = "#d0021b"       # forced I/O marker
LADDER_NOTE = "#3d4a5c"
LADDER_ONESHOT = "#7a1f5c"
COMMENT_LINE_PX = 14

# Expanded clearances so device tags / type captions never sit under rails, wires, or symbols.
CONTACT_HALF_H = 18          # contact bar half-height (| |)
CONTACT_GAP = 16             # gap between contact bars
COIL_RADIUS = 18
TAG_CLEAR_ABOVE = 24         # tag baseline offset above symbol top
CAPTION_CLEAR_BELOW = 22     # caption baseline offset below symbol bottom
BRANCH_ROW_H = 128           # vertical pitch between parallel branch wires
TITLE_BAND = 64              # room for "Rung N: comment" above first wire
BOTTOM_PAD = 40              # room under lowest tag/symbol before rail end
INTER_RUNG_GAP = 118         # space between rung blocks (never overlap after hover declutter)
CONTACT_COL_W = 136          # x step for contacts in a parallel branch (>=2)
MIN_SERIES_W = 140           # minimum series contact column width
RAIL_INSET = 68              # left/right rail inset from content edges
SERIES_AFTER_PARALLEL = 72   # gap from parallel bus to first series contact
COIL_INSET = 84              # coil center inset from right rail
SEAL_IN_GAP = 12             # seal-in label clear of right rail
TIMER_BOX_W = 132
TIMER_BOX_H = 78
TIMER_INSET = 100            # timer box center inset from right rail (left of coil)
LADDER_TIMER = "#5b3d8a"
COUNTER_BOX_W = 96
COUNTER_BOX_H = 56
COUNTER_OUT_W = 72           # RES / LOAD drawn as an output "coil" oval
COUNTER_OUT_H = 40
FB_GAP = 28                  # wire gap between function boxes / coil
LADDER_COUNTER = "#8a4b12"
SLOT_LEAD = 26               # minimum wire on each side of an instruction
SLOT_PAD = 14                # tag text clearance inside an instruction slot
OR_PAD = 18                  # wire between an OR bar and its first / last instruction
_OUTPUT_KINDS = {"coil", "timer", "counter", "math", "jsr", "ret", "oneshot_out"}


def _el_kind(el: dict) -> str:
    kind = str(el.get("kind") or "").lower()
    if kind == "oneshot" and str(el.get("block") or "ONS").upper() in {"OSR", "OSF"}:
        return "oneshot_out"
    return kind


def _or_branches(el: dict) -> list[list]:
    return [b if isinstance(b, list) else [] for b in (el.get("branches") or [])]


def _part_name(el: dict) -> str:
    kind = _el_kind(el)
    tag = str(el.get("var") or el.get("tag") or "").strip()
    if kind == "contact":
        op = "XIO" if str(el.get("form") or "NO").upper() == "NC" else "XIC"
    elif kind == "coil":
        form = str(el.get("form") or "").lower()
        op = {"set": "OTL", "s": "OTL", "reset": "OTU", "r": "OTU"}.get(form, "OTE")
    elif kind == "or":
        return "branch (OR)"
    else:
        op = str(el.get("block") or el.get("op") or kind or "?").upper()
    return f"{op} {tag}".strip()


def _series_rows(items: list) -> int:
    rows = 1
    for el in items or []:
        if isinstance(el, dict) and _el_kind(el) == "or":
            rows = max(rows, _or_rows(el))
    return rows


def _or_rows(el: dict) -> int:
    return max(1, sum(_series_rows(b) for b in _or_branches(el)))


def timer_live_text(tmr: dict) -> tuple[str, str, float]:
    """(ACC text, status text, done fraction 0..1) for a live timer box."""
    acc = int(tmr.get("acc_ms") or 0)
    pt = int(tmr.get("pt_ms") or 0)
    block = str(tmr.get("block") or "TON").upper()
    frac = 1.0 if pt <= 0 else max(0.0, min(1.0, acc / pt))
    left = max(0, pt - acc) / 1000.0
    if tmr.get("tt"):
        status = f"{'▼' if block == 'TOF' else '▲'} {left:.1f} s left"
    elif tmr.get("q"):
        status = "DN  output ON" if block == "TOF" and not acc else "DN  done"
    elif block == "RTO" and acc:
        status = "held (RTO)"
    else:
        status = "idle"
    return f"ACC {acc / 1000:.1f} s", status, frac


def _rung_fb_boxes(rung: dict) -> list[tuple[str, dict, float]]:
    """Function boxes on a rung in draw order: (kind, data, width)."""
    out: list[tuple[str, dict, float]] = []
    timer = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
    if timer and (timer.get("tag") or "").strip():
        out.append(("timer", timer, float(TIMER_BOX_W)))
    counter = rung.get("counter") if isinstance(rung.get("counter"), dict) else None
    if counter and (counter.get("tag") or "").strip():
        blk = str(counter.get("block") or "CTU").upper()
        width = COUNTER_OUT_W if blk in {"RES", "LOAD"} else COUNTER_BOX_W
        out.append(("counter", counter, float(width)))
    return out


def _rung_fb_space(rung: dict) -> float:
    return sum(w + FB_GAP for _k, _d, w in _rung_fb_boxes(rung))


def _actuator_layout(rung: dict, right: float) -> tuple[list[tuple[str, dict, float, float]], float | None]:
    """Place timer / counter boxes left of the coil (or the right rail).

    Returns ([(kind, data, center_x, width)], coil_x or None when no coil is drawn).
    Rungs without boxes always draw the coil slot (``?`` when empty), like before.
    """
    coil = (rung.get("coil_tag") or "").strip()
    boxes = _rung_fb_boxes(rung)
    coil_x = right - COIL_INSET
    draw_coil = bool(coil) or not boxes
    edge = (coil_x - COIL_RADIUS - FB_GAP) if draw_coil else (right - 40)
    placed: list[tuple[str, dict, float, float]] = []
    for kind, data, width in reversed(boxes):
        cx = edge - width / 2
        placed.insert(0, (kind, data, cx, width))
        edge = cx - width / 2 - FB_GAP
    return placed, (coil_x if draw_coil else None)



def _hscroll_strip(
    parent,
    *,
    fg_color: str,
    height: int = 42,
    corner_radius: int = 0,
    border_width: int = 0,
    border_color: str | None = None,
):
    """Fill-x shell with a horizontally scrollable inner row for toolbar widgets.

    Pack always-visible right-side controls on ``shell`` *before* packing the
    returned ``inner`` (side=left, expand). Pack overflowing buttons into ``inner``.
    """
    shell_kwargs: dict = {"fg_color": fg_color, "corner_radius": corner_radius}
    if border_width:
        shell_kwargs["border_width"] = border_width
        shell_kwargs["border_color"] = border_color or BORDER
    shell = ctk.CTkFrame(parent, **shell_kwargs)
    inner = ctk.CTkScrollableFrame(
        shell,
        fg_color=fg_color,
        orientation="horizontal",
        height=height,
        corner_radius=0,
        border_width=0,
        scrollbar_button_color=BORDER,
        scrollbar_button_hover_color=TRACK_HOVER,
    )
    return shell, inner


class ProgrammingViewer(ctk.CTkToplevel):
    """Ask simple questions, show a real ladder canvas, keep copyable PLC/HMI text."""

    def __init__(self, master, fonts, project: Project, on_change) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.project = project
        self.on_change = on_change
        self.program = program_from_dict(project.program or {})
        self._q_index = 0
        self._answers: dict[str, str] = dict(self.program.get("answers") or {})
        self._asking = False
        self._selected_rung_id: str | None = None
        self._device_map = devices_by_tag(project)
        self._hover_targets: list[tuple[float, float, float, float, str]] = []
        self._hover_tip: ctk.CTkToplevel | None = None
        self._hover_after: str | None = None
        self._hover_key: str | None = None
        self._sim_running = False
        self._sim_after: str | None = None
        self._sim_index = -1
        self._sim_flash_on = False
        self._sim_flash_count = 0
        self._sim_active_tags: set[str] = set()
        self._sim_pulse_tags: set[str] = set()
        self._sim_status_var = None  # set after widgets
        self._scan_sim: ScanSimulator | None = None
        self._sim_engine = "scan"  # v3 educational scan; "walk" = legacy rung walk
        self._force_buttons: dict[str, ctk.CTkButton] = {}
        self._sim_flow: dict[str, dict[str, bool]] = {}
        self._sim_energized: dict[str, bool] = {}
        # v0.3.20: a sim "session" lasts from Run/Step until Stop; edits during a
        # session rebuild the simulator but carry its live state (_sim_carry).
        self._sim_session = False
        self._sim_carry: ScanSimulator | None = None
        self._sim_resume_when_fixed = False
        self._sim_cursor_rung_id: str | None = None
        self._click_targets: list[tuple[float, float, float, float, str, str]] = []
        self._force_sig = None
        self._force_value_widgets: dict[str, object] = {}
        self._sim_status_float = None
        self._ai_window: AiAssistantWindow | None = None
        speed = _load_ui_pref(_PROG_SIM_SPEED_PREF, _SIM_DEFAULT_SPEED)
        self._sim_speed_var = tk.StringVar(master=self, value=speed if speed in _SIM_SPEEDS else _SIM_DEFAULT_SPEED)
        self._sim_on_top_var = tk.BooleanVar(master=self, value=bool(_load_ui_pref(_PROG_SIM_ON_TOP_PREF, True)))
        self._history = LadderHistory(program_to_dict(self.program))
        self._restoring = False
        # v0.3.7 editor tools: ladder clipboard, verify / tags / find windows.
        self._ladder_clip: dict | None = None
        self._tool_windows: dict[str, ctk.CTkToplevel] = {}
        self._verify_issues: list[dict] = []
        self._verify_list = None
        self._verify_summary_lbl = None
        self._tag_rows_frame = None
        self._tag_xref_frame = None
        self._tag_xref_label = None
        self._tag_filter_var = None
        self._tag_count_lbl = None
        self._find_results = None
        self._find_result_lbl = None
        # v0.3.8 watch / trend + verify highlight
        self._watch = WatchTrendBuffer()
        self._watch_list = None
        self._watch_plot = None
        self._watch_tag_var = None
        self._watch_pause_btn = None
        self._watch_label_var = None
        self._highlight_rung_id: str | None = None
        self._highlight_path: tuple | None = None
        self._active_routine = "Main"
        self.title(f"Programming - {project.name}")
        self.minsize(1100, 720)
        self.protocol("WM_DELETE_WINDOW", self.close)

        # Full-screen workspace so the ladder is readable without crowding the cabinet UI.
        self._open_maximized()

        self._canvas_popout: ctk.CTkToplevel | None = None
        self._canvas_geom_flush = None
        self._force_popout: ctk.CTkToplevel | None = None
        self._force_geom_flush = None
        self._force_hint = None
        self._sim_toolbars: list = []
        self._ladder_simbar = None
        self._sim_speeds = _SIM_SPEEDS
        # v0.3.22 Follow rung: keep the executing rung in view while simulating.
        self._follow_var = tk.BooleanVar(master=self, value=bool(_load_ui_pref(_PROG_FOLLOW_PREF, True)))
        self._sim_parts_var = tk.BooleanVar(master=self, value=bool(_load_ui_pref(_PROG_PARTS_PREF, False)))
        self._sim_parts: dict | None = None
        self._sim_part_key: str | None = None
        self._sim_part_after = None
        self._sim_auto: dict | None = None
        self._sim_auto_after = None
        self._sim_plant: PlantModel | None = None
        self._follow_suspend_until = 0.0
        self._follow_last_states: dict[str, str] = {}
        layout = _load_ui_pref(_PROG_LAYOUT_PREF, "studio")
        self._layout_var = tk.StringVar(master=self, value=layout if layout in _LAYOUTS else "studio")
        self._built_layout: str | None = None
        self._theme_var = tk.StringVar(master=self, value=current_mode())
        self._error_after: str | None = None
        self._wizard: ProgramWizard | None = None
        self.organizer = self.palette = self.properties = self._work = None
        self._pane_vars = {
            name: tk.BooleanVar(master=self, value=bool(_load_ui_pref(spec[0], True)))
            for name, spec in _PANE_PREFS.items()
        }
        self._init_rung_editor_state()
        self.commands = CommandRegistry()
        self._register_commands()
        self.commands.build_menubar(self)
        self._content = None
        self._tab = "ladder"
        self._rung_hitboxes: list[tuple[str, float, float, float, float]] = []
        self._build_layout()

        self._apply_tab_layout()
        self._load_editor()
        self._draw_ladder()
        self._show_idle_question_prompt()
        self.bind("<Escape>", lambda _e: self.close())
        self._bind_edit_shortcuts(self)
        self._update_undo_buttons()
        self.after(40, self._arm)
        self.after(120, self._offer_starter_if_empty)
        if _load_ui_pref(_PROG_RUNG_EDITOR_FLOAT_PREF, False):
            self.after(260, self._restore_rung_editor_popout)
        if _load_ui_pref(_PROG_FORCE_FLOAT_PREF, False):
            self.after(300, lambda: self._force_popout is None and self._pop_out_force_strip())
        bind_theme_redraw(self, self._on_theme)


    # --- v0.3.22 window chrome: commands, menus, Studio / Classic layouts ------

    def _register_commands(self) -> None:
        reg = self.commands
        add = reg.add
        add("file.new_wizard", "New Program / Routine…", self.open_program_wizard, menu="File")
        add("file.ask_questions", "Ask questions (in the strip)…", self.start_questions, menu="File")
        add("file.build_starter", "Build starter program", self._build_starter_program, menu="File")
        add("file.build_drawings", "Build from drawings", self._build_from_drawings, menu="File")
        reg.separator("File")
        add("file.import_plcopen", "Import PLCopen XML…", self.import_plcopen_xml, menu="File")
        reg.separator("File")
        add("file.export_ladder", "Export Ladder…", self.export_ladder_artifact, menu="File")
        add("file.export_plcopen", "Export PLCopen XML…", self.export_plcopen_xml, menu="File")
        add("file.export_txt", "Export .txt…", self.export_txt, menu="File")
        reg.separator("File")
        add("file.print", "Print ladder…", self.print_ladder, menu="File")
        reg.separator("File")
        add("file.done", "Done - return to cabinet", self.close, menu="File", shortcut="Esc")

        add("edit.undo", "Undo", self._undo, menu="Edit", shortcut="Ctrl+Z")
        add("edit.redo", "Redo", self._redo, menu="Edit", shortcut="Ctrl+Y")
        reg.separator("Edit")
        add("edit.copy_rung", "Copy rung", self._copy_rung, menu="Edit", shortcut="Ctrl+C")
        add("edit.paste_rung", "Paste rung", self._paste_rung, menu="Edit", shortcut="Ctrl+V")
        add("edit.copy_instr", "Copy instruction…", self._copy_instruction, menu="Edit", shortcut="Ctrl+Shift+C")
        add("edit.paste_instr", "Paste instruction", self._paste_instruction, menu="Edit", shortcut="Ctrl+Shift+V")
        add("edit.duplicate", "Duplicate rung", self._duplicate_rung, menu="Edit", shortcut="Ctrl+D")
        add("edit.delete", "Delete rung", self._delete_selected_rung, menu="Edit", shortcut="Del")
        reg.separator("Edit")
        add("edit.find", "Find…", self._open_find_replace, menu="Edit", shortcut="Ctrl+F")
        add("edit.replace", "Replace…", lambda: self._open_find_replace(focus_replace=True), menu="Edit",
            shortcut="Ctrl+H")
        reg.separator("Edit")
        add("edit.copy_plc", "Copy PLC text", self.copy_plc, menu="Edit")
        add("edit.copy_hmi", "Copy HMI text", self.copy_hmi, menu="Edit")
        add("edit.sync_text", "Sync text from ladder", self._sync_text_from_ladder, menu="Edit")

        add("view.ladder", "Ladder", lambda: self._show_tab("ladder"), menu="View")
        add("view.plc", "PLC text", lambda: self._show_tab("plc"), menu="View")
        add("view.hmi", "HMI text", lambda: self._show_tab("hmi"), menu="View")
        reg.separator("View")
        add("view.popout", "Pop out / dock ladder", self._toggle_canvas_popout, menu="View")
        add("view.float_io", "Float / dock I/O panel", self._toggle_force_popout, menu="View")
        add("view.popout_editor", "Pop out / dock rung editor", self._toggle_rung_editor_popout, menu="View")
        reg.separator("View")
        add("view.organizer", "Controller Organizer", lambda: self._on_pane_menu("organizer"), menu="View",
            kind="check", variable=self._pane_vars["organizer"])
        add("view.properties", "Properties", lambda: self._on_pane_menu("properties"), menu="View",
            kind="check", variable=self._pane_vars["properties"])
        reg.separator("View")
        for mode, label in (("light", "Light"), ("dark", "Dark"), ("system", "System")):
            add(f"view.theme.{mode}", label, self._on_theme_menu, menu="View/Theme", kind="radio",
                variable=self._theme_var, value=mode)
        add("view.theme_toggle", "Light / Dark", self._toggle_theme)
        add("view.layout.studio", "Studio", self._on_layout_menu, menu="View/Layout", kind="radio",
            variable=self._layout_var, value="studio")
        add("view.layout.classic", "Classic (until v0.3.24)", self._on_layout_menu, menu="View/Layout",
            kind="radio", variable=self._layout_var, value="classic")

        for cmd_id, label, fn in (
            ("rung.add", "Add rung (XIC → OTE)", self._add_rung),
            ("rung.add_series_contact", "Add series contact (XIC / XIO)", self._add_series_contact),
            ("rung.add_timer", "Add timer (TON / TOF / RTO)", self._add_timer_rung),
            ("rung.add_counter", "Add counter (CTU / CTD)", self._add_counter_rung),
            ("rung.add_nested_or", "Add nested OR branch", self._add_nested_or_rung),
            ("rung.add_mid_coil", "Add mid-rung coil", self._add_mid_coil_rung),
            ("rung.add_compare", "Add compare (EQU / GEQ / …)", self._add_compare_rung),
            ("rung.add_math", "Add math (ADD / CPT / …)", self._add_math_rung),
            ("rung.add_lim", "Add LIM", self._add_lim_rung),
            ("rung.add_meq", "Add MEQ", self._add_meq_rung),
            ("rung.add_bitwise", "Add bitwise (AND / OR / XOR)", self._add_bitwise_rung),
            ("rung.add_aoi", "Add AOI", self._add_aoi_template),
            ("rung.add_otl", "Add OTL (latch)", self._add_otl_rung),
            ("rung.add_otu", "Add OTU (unlatch)", self._add_otu_rung),
            ("rung.add_oneshot", "Add one-shot (ONS / OSR / OSF)", self._add_oneshot_rung),
            ("rung.add_jsr", "Add JSR", self._add_jsr_rung),
            ("rung.add_sbr", "Add SBR routine", self._add_sbr_routine),
            ("rung.add_ret", "Add RET", self._add_ret_rung),
        ):
            add(cmd_id, label, fn, menu="Rung")
        reg.separator("Rung")
        add("rung.move_up", "Move rung up", self._move_rung_up, menu="Rung", shortcut="Ctrl+Up")
        add("rung.move_down", "Move rung down", self._move_rung_down, menu="Rung", shortcut="Ctrl+Down")
        add("rung.comment", "Comment…", self._edit_rung_comments, menu="Rung", shortcut="Ctrl+E")

        add("sim.run", "Run", self._sim_run, menu="Simulate", shortcut="F5")
        add("sim.pause", "Pause", self._sim_pause, menu="Simulate", shortcut="F9")
        add("sim.step_rung", "Step rung", self._sim_step_rung, menu="Simulate", shortcut="F6")
        add("sim.step_scan", "Step scan", self._sim_step, menu="Simulate", shortcut="F10")
        add("sim.stop", "Stop", self._sim_stop, menu="Simulate", shortcut="Shift+F5")
        add("sim.reset", "Reset", self._sim_reset, menu="Simulate")
        add("sim.normal_run", "Normal run", self._sim_auto_start, menu="Simulate")
        add("sim.parts", "Show each part", self._on_parts_toggle, menu="Simulate", kind="check",
            variable=self._sim_parts_var)
        reg.separator("Simulate")
        for i, speed in enumerate(_SIM_SPEEDS):
            add(f"sim.speed.{i}", speed, lambda s=speed: self._on_sim_speed(s), menu="Simulate/Speed", kind="radio",
                variable=self._sim_speed_var, value=speed)
        add("sim.follow", "Follow rung", self._on_follow_toggle, menu="Simulate", kind="check",
            variable=self._follow_var)

        add("tools.verify", "Verify", self._open_verify_panel, menu="Tools", shortcut="F7")
        add("tools.explain_run", "Explain run", self._open_explain_run, menu="Tools")
        add("tools.tags", "Tags / X-ref", self._open_tag_list, menu="Tools", shortcut="Ctrl+T")
        add("tools.watch", "Watch / Trend", self._open_watch_panel, menu="Tools")
        add("tools.hmi_editor", "HMI editor…", self._open_hmi_editor, menu="Tools")
        add("tools.device", "PLC / Device (export & connect)…", self._open_device_panel, menu="Tools")
        reg.separator("Tools")
        add("tools.ask_ai", "Ask AI", self._open_ai_assistant, menu="Tools")
        add("tools.ai_settings", "AI settings…", self._open_ai_settings, menu="Tools")

        add("help.manual", "User manual", self._open_manual, menu="Help")
        add("help.shortcuts", "Keyboard shortcuts", self._show_shortcuts, menu="Help", shortcut="F1")
        add("help.about", "About Cabinet Studio", self._show_about, menu="Help")

    def invoke_command(self, cmd_id: str):
        """Run a registered command exactly like its menu entry / toolbar button."""
        return self.commands.invoke(cmd_id)

    def _update_title(self) -> None:
        self.title(f"Programming - {self.project.name}  |  Cabinet Studio v{_CS_VERSION}  |  {LEARNING_NOTE}")

    def _build_layout(self) -> None:
        """(Re)build the window body for the chosen layout; program and sim state are kept."""
        status = sim_status = ""
        if self._content is not None:
            try:
                status = self.status.cget("text")
                sim_status = self._sim_status.cget("text")
            except Exception:
                pass
        old = self._content
        self._content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        if old is not None:
            self._hide_hover_tip()
            try:
                old.destroy()
            except Exception:
                pass
        self._sim_toolbars = [tb for tb in self._sim_toolbars if self._alive(tb)]
        self._content.pack(fill="both", expand=True)
        self._update_title()
        layout = self._layout_var.get()
        if layout == "classic":
            self._build_classic_layout(self._content)
        else:
            self._build_studio_layout(self._content)
        self._built_layout = layout
        if status:
            self.status.configure(text=status)
        if sim_status:
            self._sim_status.configure(text=sim_status)
        self._update_statusbar()
        self._schedule_error_count(0)

    @staticmethod
    def _alive(widget) -> bool:
        try:
            return bool(widget is not None and widget.winfo_exists())
        except Exception:
            return False

    def _vsep(self, parent) -> None:
        ctk.CTkFrame(parent, width=1, height=22, fg_color=BORDER, corner_radius=0).pack(side="left", padx=6, pady=6)

    def _build_statusbar(self, root) -> None:
        self.statusbar = StatusBar(root, self.fonts, version=_CS_VERSION, badge=EDU_BADGE)
        self.statusbar.pack(side="bottom", fill="x")
        self.status = self.statusbar.message
        self.meta = self.statusbar.version_label
        self.hint = self.statusbar.badge_label

    def _build_question_strip(self, root, *, pady=(0, 6)) -> None:
        self.q_frame = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
        self.q_frame.pack(fill="x", padx=12, pady=pady)
        self.q_label = ctk.CTkLabel(
            self.q_frame, text="", font=self.fonts.body, text_color=TEXT, anchor="w", justify="left", wraplength=1200,
        )
        self.q_label.pack(fill="x", padx=12, pady=(6, 2))
        self.q_choices = ctk.CTkFrame(self.q_frame, fg_color="transparent")
        self.q_choices.pack(fill="x", padx=8, pady=(0, 6))

    def _build_sim_row(self, root) -> None:
        shell = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
        shell.pack(fill="x", padx=12, pady=(0, 6))
        bar = SimToolbar(shell, self)
        bar.pack(side="left", padx=4, pady=2)
        self._sim_toolbars.append(bar)
        self._sim_status = ctk.CTkLabel(
            shell, text="Sim off (educational — not a live PLC). Run the ladder program here.",
            font=self.fonts.small, text_color=MUTED, anchor="w",
        )
        self._sim_status.pack(side="left", fill="x", expand=True, padx=10)

    def _build_force_row(self, root) -> None:
        self._force_wrap, self._force_strip = _hscroll_strip(
            root, fg_color=PANEL, height=36, corner_radius=4, border_width=1, border_color=BORDER
        )
        self._force_wrap.pack(fill="x", padx=12, pady=(0, 6))
        self._force_home_strip = self._force_strip
        self._force_toggle_btn = self.commands.button(
            self._force_wrap, "view.float_io", text="Float I/O", width=86, font=self.fonts.tiny
        )
        self._force_toggle_btn.pack(side="right", padx=(4, 8), pady=4)
        self._force_strip.pack(side="left", fill="both", expand=True, padx=4, pady=2)
        ctk.CTkLabel(
            self._force_strip, text="Force inputs appear when Run / Step runs (educational scan).",
            font=self.fonts.tiny, text_color=MUTED,
        ).pack(side="left", padx=6, pady=4)

    def _build_body(self, root) -> None:
        """Controller Organizer | (instruction palette over the ladder body) | Properties."""
        self._work = tk.PanedWindow(root, orient="horizontal", sashwidth=6, bd=0, sashrelief="flat",
                                    background=c(BORDER), showhandle=False)
        self._work.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.organizer = ControllerOrganizer(self._work, self)
        center = ctk.CTkFrame(self._work, fg_color=BG, corner_radius=0)
        self.properties = PropertiesPane(self._work, self)
        scale = self._pane_scale()
        for name, pane in (("organizer", self.organizer), ("properties", self.properties)):
            _vis, width_key, default, lo, hi = _PANE_PREFS[name]
            if name == "properties":
                self._work.add(center, minsize=int(420 * scale), stretch="always")
            self._work.add(pane, width=int(load_width(width_key, default, lo, hi) * scale), minsize=int(lo * scale),
                           stretch="never")
        for name in _PANE_PREFS:
            self._set_pane_visible(name, self._pane_vars[name].get(), save=False)
        self._work.bind("<ButtonRelease-1>", lambda _e: self._save_pane_widths(), add="+")
        self.palette = InstructionPalette(center, self)
        self.palette.pack(fill="x", pady=(0, 4))
        self.body = ctk.CTkFrame(center, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
        self.body.pack(fill="both", expand=True)
        self._canvas_placeholder = ctk.CTkLabel(
            self.body,
            text="Ladder view popped out — drag that window to another monitor. Controls here still drive sim / rungs.\n"
            "Click Dock ladder (or close the pop-out) to bring the canvas back.",
            font=self.fonts.small, text_color=MUTED, anchor="center", justify="center",
        )
        self._mount_ladder_canvas(self.body)
        self.editor = ctk.CTkTextbox(
            self.body, font=self.fonts.mono_small, fg_color=ENTRY, text_color=TEXT, border_color=BORDER,
            border_width=0, corner_radius=4, wrap="word", height=180,
        )
        self.editor.bind("<KeyRelease>", self._on_typed)

    def _build_rung_row(self, root) -> None:
        self._rung_shell, self._rung_bar = _hscroll_strip(root, fg_color=BG, height=40)
        self._rung_shell.pack(fill="x", padx=12, pady=(0, 4))
        self._rung_bar.pack(side="left", fill="both", expand=True)
        self._build_rung_editor_controls(self._rung_bar, floating=False)

    def _build_studio_layout(self, root) -> None:
        """Studio (default): native menus + one compact toolbar + sim toolbar + status bar."""
        fonts = self.fonts
        reg = self.commands
        self._build_statusbar(root)
        bar_shell, bar = _hscroll_strip(root, fg_color=PANEL, height=34)
        bar_shell.pack(fill="x", pady=(0, 6))
        reg.button(bar_shell, "file.done", text="Done", width=70, primary=True, font=fonts.small).pack(
            side="right", padx=(4, 10), pady=4
        )
        self._theme_btn = reg.button(bar_shell, "view.theme_toggle", text=self._theme_toggle_text(), width=92,
                                     font=fonts.small)
        self._theme_btn.pack(side="right", padx=4, pady=4)
        self.tab_label = ctk.CTkLabel(bar_shell, text="LADDER", font=fonts.small, text_color=MUTED, anchor="e")
        self.tab_label.pack(side="right", padx=8)
        self._hmi_btn = reg.button(bar_shell, "tools.hmi_editor", text="HMI editor", width=96, primary=True,
                                   font=fonts.small)
        self._hmi_btn.pack(side="right", padx=4, pady=4)
        attach_tip(self._hmi_btn, "Design the operator touch screen (HMI) for this cabinet: answer a few questions "
                                  "or drag buttons, lights and numbers onto the screen, tied to these PLC tags.",
                   "HMI editor")
        self._device_btn = reg.button(bar_shell, "tools.device", text="PLC / Device", width=100, primary=True,
                                      font=fonts.small)
        self._device_btn.pack(side="right", padx=4, pady=4)
        attach_tip(self._device_btn, _DEVICE_TIP, "PLC / Device")
        bar.pack(side="left", fill="both", expand=True)
        reg.button(bar, "file.new_wizard", text="New…", width=58, primary=True, font=fonts.small).pack(
            side="left", padx=2, pady=3)
        self._vsep(bar)
        for cmd_id, text, width in (("view.ladder", "Ladder", 70), ("view.plc", "PLC text", 78),
                                    ("view.hmi", "HMI text", 78)):
            reg.button(bar, cmd_id, text=text, width=width, font=fonts.small).pack(side="left", padx=2, pady=3)
        self._vsep(bar)
        for cmd_id, text, width in (("view.organizer", "Organizer", 84), ("view.properties", "Properties", 84)):
            reg.button(bar, cmd_id, text=text, width=width, font=fonts.small).pack(side="left", padx=2, pady=3)
        self._vsep(bar)
        self._popout_btn = reg.button(bar, "view.popout", text="Pop out ladder", width=112, font=fonts.small)
        self._popout_btn.pack(side="left", padx=2, pady=3)
        self._vsep(bar)
        for cmd_id, text, width in (("tools.verify", "Verify", 66), ("tools.explain_run", "Explain run", 92),
                                    ("tools.tags", "Tags / X-ref", 96),
                                    ("tools.watch", "Watch / Trend", 104)):
            reg.button(bar, cmd_id, text=text, width=width, font=fonts.small).pack(side="left", padx=2, pady=3)
        self._build_sim_row(root)
        self._build_question_strip(root)
        self._build_force_row(root)
        self._build_body(root)
        self._build_rung_row(root)

    def _build_classic_layout(self, root) -> None:
        """Classic (v0.3.21 look, kept one release): button strips; sim uses the shared SimToolbar."""
        fonts = self.fonts
        reg = self.commands
        self._build_statusbar(root)
        self._build_question_strip(root, pady=(10, 6))
        tools_shell, tools = _hscroll_strip(root, fg_color=BG, height=40)
        tools_shell.pack(fill="x", padx=12, pady=(0, 4))
        self._popout_btn = reg.button(tools_shell, "view.popout", text="Pop out ladder", width=120, font=fonts.small)
        self._popout_btn.pack(side="right", padx=4)
        self.tab_label = ctk.CTkLabel(tools_shell, text="LADDER", font=fonts.small, text_color=MUTED, anchor="e")
        self.tab_label.pack(side="right", padx=8)
        self._hmi_btn = reg.button(tools_shell, "tools.hmi_editor", text="HMI editor", width=110, primary=True,
                                   font=fonts.small, height=34)
        self._hmi_btn.pack(side="right", padx=4)
        attach_tip(self._hmi_btn, "Design the operator touch screen (HMI) for this cabinet: answer a few questions "
                                  "or drag buttons, lights and numbers onto the screen, tied to these PLC tags.",
                   "HMI editor")
        self._device_btn = reg.button(tools_shell, "tools.device", text="PLC / Device", width=110, primary=True,
                                      font=fonts.small, height=34)
        self._device_btn.pack(side="right", padx=4)
        attach_tip(self._device_btn, _DEVICE_TIP, "PLC / Device")
        tools.pack(side="left", fill="both", expand=True)
        for cmd_id, text, width, primary in (
            ("file.new_wizard", "New program wizard", 160, True),
            ("file.ask_questions", "Ask questions", 130, True),
            ("file.build_starter", "Build starter program", 180, True),
            ("file.build_drawings", "Build from drawings", 160, False),
            ("view.ladder", "Ladder", 90, False),
            ("view.plc", "PLC text", 100, False),
            ("view.hmi", "HMI text", 100, False),
            ("edit.copy_plc", "Copy PLC", 100, False),
            ("edit.copy_hmi", "Copy HMI", 100, False),
            ("file.print", "Print", 90, False),
            ("file.export_ladder", "Export Ladder", 120, False),
            ("file.export_plcopen", "Export PLCopen", 130, False),
            ("file.import_plcopen", "Import PLCopen", 130, False),
            ("tools.verify", "Verify (F7)", 110, False),
            ("tools.explain_run", "Explain run", 110, False),
            ("tools.tags", "Tags / X-ref", 120, False),
            ("edit.find", "Find / Replace", 130, False),
            ("tools.watch", "Watch / Trend", 120, False),
            ("help.shortcuts", "Shortcuts (F1)", 120, False),
        ):
            reg.button(tools, cmd_id, text=text, width=width, primary=primary, font=fonts.small, height=34).pack(
                side="left", padx=4
            )
        self._build_sim_row(root)
        self._build_force_row(root)
        self._build_body(root)
        self._build_rung_row(root)
        nav_shell, nav = _hscroll_strip(root, fg_color=BG, height=42)
        nav_shell.pack(fill="x", padx=12, pady=(0, 8))
        reg.button(nav_shell, "file.done", text="Done", width=120, primary=True, font=fonts.body, height=34).pack(
            side="right", padx=4
        )
        nav.pack(side="left", fill="both", expand=True)
        reg.button(nav, "file.export_txt", text="Export .txt", width=120, font=fonts.body, height=34).pack(
            side="left", padx=4
        )
        reg.button(nav, "edit.sync_text", text="Sync text from ladder", width=170, font=fonts.body, height=34).pack(
            side="left", padx=4
        )
        self._theme_btn = None

    def _on_layout_menu(self) -> None:
        self._set_layout(self._layout_var.get())

    def _set_layout(self, layout: str) -> None:
        layout = layout if layout in _LAYOUTS else "studio"
        self._layout_var.set(layout)
        _save_ui_pref(_PROG_LAYOUT_PREF, layout)
        if layout == self._built_layout:
            return
        self._flush_editor_to_program()
        ladder_out = self._canvas_popout is not None
        io_out = self._force_popout is not None
        editor_out = self._rung_editor_popout is not None
        if ladder_out:
            self._dock_ladder_canvas()
        if io_out:
            self._dock_force_strip()
        if editor_out:
            self._dock_rung_editor()
        self._build_layout()
        self._apply_tab_layout()
        self._load_editor()
        self._show_idle_question_prompt()
        self._rebuild_force_strip_safe()
        self._update_undo_buttons()
        if editor_out:
            self._pop_out_rung_editor()
        if io_out:
            self._pop_out_force_strip()
        if ladder_out:
            self._pop_out_ladder_canvas()
        self._draw_ladder(preserve_scroll=False)
        self.status.configure(text=f"Layout: {layout.title()}.")

    # --- theme ------------------------------------------------------------------

    @property
    def _lbg(self) -> str:
        return ladder_palette()["bg"]

    def _theme_toggle_text(self) -> str:
        return "☀ Light" if is_dark() else "☾ Dark"

    def _on_theme_menu(self) -> None:
        set_mode(self._theme_var.get())

    def _toggle_theme(self) -> None:
        toggle_mode()

    def _on_theme(self) -> None:
        """Redraw the plain-Tk parts (CTk widgets repaint themselves)."""
        self._theme_var.set(current_mode())
        if self._alive(getattr(self, "_theme_btn", None)):
            self._theme_btn.configure(text=self._theme_toggle_text())
        try:
            self.canvas.configure(background=self._lbg)
        except Exception:
            pass
        if self._alive(self._work):
            self._work.configure(background=c(BORDER))
        self._draw_ladder(preserve_scroll=True)
        if self._alive(self._watch_plot):
            try:
                self._watch_plot.configure(background=c("PLOT_BG"))
                self._draw_watch_plot()
            except Exception:
                pass

    # --- status bar + Follow rung ---------------------------------------------------

    def _update_statusbar(self) -> None:
        sb = getattr(self, "statusbar", None)
        if not self._alive(sb):
            return
        sb.set_mode("RUN" if self._sim_running else ("STEP" if self._sim_session else "PROG"))
        sim = self.__dict__.get("_scan_sim_obj")
        sb.set_scan(int(sim.scan_count) if (sim is not None and self._sim_session) else None)
        rungs = self._sim_rungs()
        ids = [r.get("id") for r in rungs]
        idx = ids.index(self._sim_cursor_rung_id) + 1 if self._sim_cursor_rung_id in ids else None
        sb.set_rung(idx, len(rungs))

    def _schedule_error_count(self, delay_ms: int = 400) -> None:
        if self._error_after is not None:
            try:
                self.after_cancel(self._error_after)
            except Exception:
                pass
        self._error_after = self.after(delay_ms, self._refresh_error_count)

    def _refresh_error_count(self) -> None:
        self._error_after = None
        sb = getattr(self, "statusbar", None)
        if not self._alive(sb):
            return
        try:
            issues = verify_program(self.program, cabinet_device_tags(self.project))
        except Exception:
            return
        errors = sum(1 for i in issues if i.get("severity") == "error")
        warnings = sum(1 for i in issues if i.get("severity") == "warning")
        sb.set_errors(errors, warnings)

    def _on_follow_toggle(self) -> None:
        on = bool(self._follow_var.get())
        _save_ui_pref(_PROG_FOLLOW_PREF, on)
        if on:
            self._follow_suspend_until = 0.0
            self._follow_rung(self._sim_cursor_rung_id)
        self._sim_set_status(
            "Follow rung ON - the view keeps the executing rung visible." if on
            else "Follow rung OFF - the view stays where you put it."
        )

    def _note_manual_scroll(self) -> None:
        """A wheel / scrollbar move by the user pauses Follow rung for a few seconds."""
        self._follow_suspend_until = time.monotonic() + _FOLLOW_SUSPEND_S

    def _follow_target(self) -> str | None:
        """Rung to keep in view: the cursor rung, else (full-scan speed) the first rung that changed."""
        energized = self._sim_energized
        by_rung: dict[str, list] = {}
        for key, val in (self._sim_flow or {}).items():
            by_rung.setdefault(str(key).split("|", 1)[0], []).append((key, sorted((val or {}).items())))
        states: dict[str, str] = {}
        changed = None
        for rung in self._sim_rungs():
            rid = rung.get("id")
            sig = repr((sorted(by_rung.get(rid, [])), energized.get(rid)))
            states[rid] = sig
            if changed is None and self._follow_last_states and self._follow_last_states.get(rid) != sig:
                changed = rid
        self._follow_last_states = states
        return self._sim_cursor_rung_id or changed

    def _follow_rung(self, rung_id: str | None) -> bool:
        """Scroll so rung_id sits inside the visible canvas with a margin. True if it moved."""
        if not rung_id or not self._follow_var.get() or not self._sim_session:
            return False
        if time.monotonic() < self._follow_suspend_until:
            return False
        box = next((b for b in self._rung_hitboxes if b[0] == rung_id), None)
        if box is None:
            return False
        canvas = self.canvas
        try:
            canvas.update_idletasks()  # pending geometry changes make winfo_height stale
            region = [float(v) for v in str(canvas.cget("scrollregion")).split()]
            total = region[3] - region[1]
            view_h = max(1, int(canvas.winfo_height()))
        except Exception:
            return False
        if total <= view_h:
            return False
        top = canvas.canvasy(0)
        bottom = top + view_h
        y0, y1 = box[2], box[4]
        margin = min(_FOLLOW_MARGIN, max(0, (view_h - (y1 - y0)) / 2))
        if y0 - margin >= top and y1 + margin <= bottom:
            return False
        if y1 - y0 + 2 * margin > view_h or y0 - margin < top:
            target = y0 - margin
        else:
            target = y1 + margin - view_h
        canvas.yview_moveto(max(0.0, min(target, total - view_h)) / total)
        return True

    def _on_vbar(self, *args) -> None:
        self._note_manual_scroll()
        self.canvas.yview(*args)

    def _on_hbar(self, *args) -> None:
        self.canvas.xview(*args)

    def _open_ai_settings(self) -> None:
        self._open_ai_assistant()
        if self._ai_window is not None:
            self._ai_window.open_settings()

    def _open_manual(self) -> bool:
        from cabinet_studio.ui.manual import manual_path, open_manual

        ok = open_manual()
        self.status.configure(text="User manual opened in your browser." if ok
                              else f"User manual not found: {manual_path()}")
        return ok

    def _show_about(self) -> None:
        ask_choice(
            self, self.fonts, "About Cabinet Studio",
            f"Cabinet Studio v{_CS_VERSION}\n{EDU_BADGE}.\n\n"
            "E-stop and safety functions must be hardwired or use rated safety relays "
            "(NFPA 79 / ISO 13849). The software is never the safety function.\n\n"
            "NOT A CERTIFIED UL 508A DRAWING. Design aid only.",
            [("ok", "OK", "primary")],
        )

    # --- Rung editor: docked strip / floating Toplevel (v0.3.6) -------------

    # --- v0.3.23 Studio panes: organizer / properties / wizard ---------------------

    def _pane(self, name: str):
        return {"organizer": self.organizer, "properties": self.properties}.get(name)

    def _set_pane_visible(self, name: str, visible: bool, *, save: bool = True) -> None:
        self._pane_vars[name].set(bool(visible))
        if save:
            _save_ui_pref(_PANE_PREFS[name][0], bool(visible))
        pane = self._pane(name)
        if self._alive(self._work) and self._alive(pane):
            if not visible:
                self._save_pane_widths()
            self._work.paneconfigure(pane, hide=not visible)

    def _on_pane_menu(self, name: str) -> None:
        self._set_pane_visible(name, self._pane_vars[name].get())

    def pane_visible(self, name: str) -> bool:
        pane = self._pane(name)
        try:
            return bool(self._alive(pane) and not int(self._work.panecget(pane, "hide")))
        except Exception:
            return False

    def _pane_scale(self) -> float:
        """tk.PanedWindow works in pixels; prefs store CTk logical widths."""
        try:
            return float(ctk.ScalingTracker.get_widget_scaling(self))
        except Exception:
            return 1.0

    def _save_pane_widths(self) -> None:
        scale = self._pane_scale() or 1.0
        for name, (_vis, width_key, _d, lo, hi) in _PANE_PREFS.items():
            if not self.pane_visible(name):
                continue
            try:
                width = round(self._pane(name).winfo_width() / scale)
            except Exception:
                continue
            if lo <= width <= hi:
                _save_ui_pref(width_key, width)

    def open_program_wizard(self) -> ProgramWizard:
        if self._wizard is not None and self._alive(self._wizard):
            self._wizard.lift()
            return self._wizard
        self._wizard = ProgramWizard(self)
        return self._wizard

    def open_routine(self, name: str) -> None:
        """Organizer: MainRoutine shows the ladder; a subroutine opens its read-only listing."""
        self._show_tab("ladder")
        rungs = self.program.get("rungs") or []
        if not name or name == "Main":
            if rungs:
                self._select_rung(rungs[0]["id"], status=f"MainRoutine — {len(rungs)} rung(s).")
            else:
                self.status.configure(text="MainRoutine is empty — use the palette or New… to add rungs.")
            return
        body = list((self.program.get("routines") or {}).get(name) or [])
        caller = next((r for r in rungs for el in (r.get("elements") or [])
                       if isinstance(el, dict) and el.get("kind") == "jsr" and el.get("target") == name), None)
        if caller is not None:
            self._select_rung(caller["id"])
        win, fresh = self._tool_window("routine", f"Routine {name}", "780x480")
        if not fresh:
            self._clear_children(win)
        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))
        section_label(top, f"ROUTINE {name.upper()} — {len(body)} RUNG(S), READ-ONLY VIEW", self.fonts.tiny).pack(
            side="left")
        ghost_button(top, "Close", lambda: self._close_tool_window("routine"), self.fonts.small, width=80).pack(
            side="right")
        text = ctk.CTkTextbox(win, font=self.fonts.mono_small, fg_color=ENTRY, text_color=TEXT, wrap="none")
        text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        text.insert("1.0", format_plc_text(body, cabinet_device_tags(self.project)) if body else
                    f"{name} has no rungs yet.")
        text.configure(state="disabled")
        self._routine_text = text
        where = f" Called from rung {rungs.index(caller) + 1}." if caller is not None else " Not called by a JSR yet."
        self.status.configure(text=f"Subroutine {name}: {len(body)} rung(s).{where}")

    def io_point_text(self, tag: str) -> str:
        d = devices_by_tag(self.project).get(tag) or {}
        parts = [tag, d.get("io_direction") or "", d.get("io_address") or "", d.get("description") or d.get("function") or ""]
        return "I/O  " + "  ·  ".join(p for p in parts if p) + "   (double-click for the tag)"

    def show_tag(self, tag: str) -> None:
        self._open_tag_list()
        if self._tag_filter_var is not None:
            self._tag_filter_var.set(tag)
            self._refresh_tag_list()
        self._show_tag_xref(tag)
        self.status.configure(text=f"Tag {tag}: see the tag view for description and where it is used.")

    def apply_rung_comment(self, rung_id: str, text: str) -> None:
        self._apply_tool_edit(set_rung_comment(self.program, rung_id, text), "Rung comment updated.", select=rung_id)

    def apply_preset(self, rung_id: str, raw: str) -> None:
        rung = next((r for r in self.program.get("rungs") or [] if r.get("id") == rung_id), None)
        if rung is None:
            return
        try:
            value = int(float(str(raw).strip()))
        except ValueError:
            self.status.configure(text="Preset must be a number.")
            return
        timer = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
        if timer:
            program = set_rung_timer(self.program, rung_id, tag=timer.get("tag", ""), block=timer.get("block", "TON"),
                                     pt_ms=max(0, value))
            label = f"{timer.get('tag')} PT = {max(0, value)} ms"
        else:
            counter = dict(rung.get("counter") or {})
            counter["pv"] = max(-32768, min(32767, value))
            program = edit_rung(self.program, rung_id, counter=counter)
            label = f"{counter.get('tag')} PRE = {counter['pv']}"
        self._apply_tool_edit(program, f"Preset updated: {label}.", select=rung_id)

    def apply_operand_rename(self, rung_id: str, old: str, new: str) -> None:
        if not valid_tag_name(new.split(".")[0]):
            self.status.configure(text=f"{new!r} is not a valid tag name.")
            return
        program, count = replace_tag(self.program, old, new, rung_ids=[rung_id])
        if count:
            self._apply_tool_edit(program, f"Renamed {old} → {new} on this rung ({count}).", select=rung_id)
        else:
            self.status.configure(text=f"{old} not found on this rung.")

    def apply_instruction_note(self, rung_id: str, path: tuple, note: str) -> None:
        program = set_instruction_notes(self.program, rung_id, {tuple(path): note})
        self._apply_tool_edit(program, "Instruction note updated.", select=rung_id)

    def apply_tag_description(self, tag: str, text: str) -> None:
        self._apply_tool_edit(set_tag_description(self.program, tag, text), f"Description of {tag} updated.")

    def _init_rung_editor_state(self) -> None:
        self._rung_editor_popout: ctk.CTkToplevel | None = None
        self._rung_editor_geom_flush = None
        self._rung_editor_status = None
        self._rung_editor_topmost_applied = False
        self._rung_editor_on_top = tk.BooleanVar(master=self, value=bool(_load_ui_pref(_PROG_RUNG_EDITOR_TOP_PREF, True)))
        self.contact_var = ctk.StringVar(master=self, value="")
        self.nc_var = ctk.StringVar(master=self, value="NO")
        self.coil_var = ctk.StringVar(master=self, value="")
        self.timer_block_var = ctk.StringVar(master=self, value="TON")
        self.counter_block_var = ctk.StringVar(master=self, value="CTU")
        self.oneshot_block_var = ctk.StringVar(master=self, value="ONS")
        defaults = {
            "comment": "", "timer_tag": "T1", "timer_pt": "1000", "counter_tag": "C1", "counter_pv": "5",
            "compare_op": "GEQ", "compare_a": "N7_0", "compare_b": "3", "compare_c": "100",
            "math_op": "ADD", "math_dest": "N7_0",
            "oneshot_storage": "OS1", "oneshot_output": "OS1_Pulse",
            "jsr_target": "Motor", "sbr_name": "Motor",
            "aoi_name": "MotorStarter",
        }
        self._rung_field_vars = {k: ctk.StringVar(master=self, value=v) for k, v in defaults.items()}

    def _build_rung_editor_controls(self, parent, *, floating: bool) -> None:
        """Create the rung-editor widgets under parent.

        Docked = one horizontal (scrollable) row. Floating = grouped rows in the
        pop-out window. Widgets are rebuilt on every pop-out / dock; values persist
        in StringVars, and ``self.contact_menu`` etc. always point at the live set.
        """
        fonts = self.fonts
        if floating:
            rows: list = []

            def row(i: int):
                while len(rows) <= i:
                    fr = ctk.CTkFrame(parent, fg_color="transparent")
                    fr.pack(fill="x", padx=8, pady=3)
                    rows.append(fr)
                return rows[i]
        else:
            def row(_i: int):
                return parent

        last_label = [""]

        def tip(widget, text: str) -> None:
            if rung_help(text):
                attach_tip(widget, rung_help(text), text)

        def label(i: int, text: str, padx=(10, 0)) -> None:
            lab = ctk.CTkLabel(row(i), text=text, font=fonts.tiny, text_color=MUTED)
            lab.pack(side="left", padx=padx)
            last_label[0] = text
            tip(lab, text)

        def menu(i: int, values, var, width: int, button_color=BLUE, hover=BLUE_HOVER):
            m = ctk.CTkOptionMenu(
                row(i), values=values, variable=var, font=fonts.tiny, dropdown_font=fonts.tiny,
                width=width, height=28, fg_color=ENTRY, button_color=button_color, button_hover_color=hover,
                dropdown_fg_color=PANEL, dropdown_hover_color=HOVER, dropdown_text_color=TEXT, text_color=TEXT,
            )
            m.pack(side="left", padx=4)
            tip(m, last_label[0])
            return m

        def entry(i: int, key: str, width: int):
            e = ctk.CTkEntry(
                row(i), textvariable=self._rung_field_vars[key], font=fonts.tiny, width=width, height=28,
                fg_color=ENTRY, border_color=BORDER, text_color=TEXT,
            )
            e.pack(side="left", padx=2)
            tip(e, last_label[0])
            return e

        def button(i: int, text: str, cmd, width: int):
            b = ghost_button(row(i), text, cmd, fonts.tiny, width=width)
            b.pack(side="left", padx=4 if not floating else 3, pady=1)
            tip(b, text)
            return b

        section_label(row(0), "RUNG EDITOR", fonts.tiny).pack(side="left", padx=(4, 8))
        toggle_text = "Dock editor" if floating else "Pop out editor"
        self._rung_editor_toggle_btn = ghost_button(
            row(0), toggle_text, self._toggle_rung_editor_popout, fonts.tiny, width=110,
        )
        self._rung_editor_toggle_btn.pack(side="left", padx=2)
        tip(self._rung_editor_toggle_btn, toggle_text)
        if floating:
            on_top = ctk.CTkCheckBox(
                row(0), text="Keep on top", variable=self._rung_editor_on_top, command=self._on_rung_editor_on_top_toggle,
                font=fonts.tiny, text_color=TEXT, checkbox_width=18, checkbox_height=18,
            )
            on_top.pack(side="left", padx=(10, 4))
            tip(on_top, "Keep on top")
        self._undo_btn = ghost_button(row(0), "↶ Undo", self._undo, fonts.tiny, width=78)
        self._undo_btn.pack(side="left", padx=2)
        tip(self._undo_btn, "↶ Undo")
        self._redo_btn = ghost_button(row(0), "↷ Redo", self._redo, fonts.tiny, width=78)
        self._redo_btn.pack(side="left", padx=(2, 8))
        tip(self._redo_btn, "↷ Redo")
        if floating:
            self._rung_editor_status = ctk.CTkLabel(row(0), text="", font=fonts.tiny, text_color=MUTED, anchor="w")
            self._rung_editor_status.pack(side="left", fill="x", expand=True, padx=8)

        label(1, "Contact", padx=(4, 0))
        self.contact_menu = menu(1, self._tag_choices(), self.contact_var, 150)
        menu(1, ["NO", "NC"], self.nc_var, 70)
        label(1, "Coil", padx=(8, 0))
        self.coil_menu = menu(1, self._tag_choices(), self.coil_var, 150)
        label(1, "Comment", padx=(8, 0))
        self.comment_entry = entry(1, "comment", 240 if floating else 220)

        label(2, "Timer", padx=(4 if floating else 10, 0))
        menu(2, ["TON", "TOF", "RTO"], self.timer_block_var, 78, "#5b3d8a", "#4a3270")
        self.timer_tag_entry = entry(2, "timer_tag", 72)
        self.timer_pt_entry = entry(2, "timer_pt", 70)
        label(2, "Counter")
        menu(2, ["CTU", "CTD", "RES", "LOAD"], self.counter_block_var, 80, LADDER_COUNTER, "#6e3c0e")
        self.counter_tag_entry = entry(2, "counter_tag", 72)
        self.counter_pv_entry = entry(2, "counter_pv", 60)

        label(3, "Compare A op B [C]", padx=(4 if floating else 10, 0))
        self.compare_op_entry = entry(3, "compare_op", 54)
        self.compare_a_entry = entry(3, "compare_a", 70)
        self.compare_b_entry = entry(3, "compare_b", 54)
        self.compare_c_entry = entry(3, "compare_c", 54)
        label(3, "Math op → dest")
        self.math_op_entry = entry(3, "math_op", 54)
        self.math_dest_entry = entry(3, "math_dest", 70)
        label(3, "One-shot")
        menu(3, ["ONS", "OSR", "OSF"], self.oneshot_block_var, 74, LADDER_ONESHOT, "#5e1847")
        self.oneshot_storage_entry = entry(3, "oneshot_storage", 80)
        self.oneshot_output_entry = entry(3, "oneshot_output", 90)
        label(3, "AOI")
        self.aoi_name_entry = entry(3, "aoi_name", 110)

        button(4, "Add rung", self._add_rung, 90)
        button(4, "Add timer", self._add_timer_rung, 100)
        button(4, "Add counter", self._add_counter_rung, 110)
        button(4, "Add nested OR", self._add_nested_or_rung, 120)
        button(4, "Add mid coil", self._add_mid_coil_rung, 110)
        button(4, "Add compare", self._add_compare_rung, 110)
        button(5, "Add math", self._add_math_rung, 90)
        button(5, "Add LIM", self._add_lim_rung, 80)
        button(5, "Add MEQ", self._add_meq_rung, 80)
        button(5, "Add bitwise", self._add_bitwise_rung, 100)
        button(5, "Add AOI", self._add_aoi_template, 80)
        button(5, "Add OTL", self._add_otl_rung, 80)
        button(5, "Add OTU", self._add_otu_rung, 80)
        button(5, "Add one-shot", self._add_oneshot_rung, 110)
        label(5, "JSR→")
        entry(5, "jsr_target", 80)
        button(5, "Add JSR", self._add_jsr_rung, 80)
        button(5, "Add SBR", self._add_sbr_routine, 80)
        button(5, "Add RET", self._add_ret_rung, 80)
        button(5, "Comment…", self._edit_rung_comments, 96)
        button(5, "Add series contact", self._add_series_contact, 140)
        button(5, "Delete rung", self._delete_selected_rung, 100)
        # v0.3.7 copy / paste / reorder
        label(6, "Edit", padx=(4 if floating else 10, 0))
        button(6, "Copy rung", self._copy_rung, 90)
        button(6, "Paste rung", self._paste_rung, 94)
        button(6, "Duplicate", self._duplicate_rung, 90)
        button(6, "Move ↑", self._move_rung_up, 74)
        button(6, "Move ↓", self._move_rung_down, 74)
        button(6, "Copy instr…", self._copy_instruction, 100)
        button(6, "Paste instr", self._paste_instruction, 96)
        button(6, "Delete instr", self._delete_selected_instr, 100)
        button(6, "Replace instr", self._replace_selected_instr, 108)
        self._update_undo_buttons()

    def _clear_children(self, widget) -> None:
        for child in list(widget.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass

    def _rung_editor_owner(self):
        """Window the floating editor is transient to (ladder pop-out if open)."""
        win = self._canvas_popout
        try:
            if win is not None and win.winfo_exists():
                return win
        except Exception:
            pass
        return self

    def _apply_rung_editor_on_top(self) -> None:
        win = self._rung_editor_popout
        if win is None:
            return
        on = bool(self._rung_editor_on_top.get())
        try:
            if on:
                win.wm_transient(self._rung_editor_owner())
            else:
                win.tk.call("wm", "transient", win._w, "")
        except tk.TclError:
            pass
        try:
            win.attributes("-topmost", on)
            self._rung_editor_topmost_applied = on
        except Exception:
            self._rung_editor_topmost_applied = False

    def _on_rung_editor_on_top_toggle(self) -> None:
        _save_ui_pref(_PROG_RUNG_EDITOR_TOP_PREF, bool(self._rung_editor_on_top.get()))
        self._apply_rung_editor_on_top()

    def rung_editor_is_floating(self) -> bool:
        return self._rung_editor_popout is not None

    def _toggle_rung_editor_popout(self) -> None:
        if self._rung_editor_popout is not None:
            self._dock_rung_editor()
        else:
            self._pop_out_rung_editor()

    def _restore_rung_editor_popout(self) -> None:
        try:
            if self.winfo_exists() and self._rung_editor_popout is None:
                self._pop_out_rung_editor()
        except Exception:
            pass

    def _pop_out_rung_editor(self) -> None:
        """Float the rung editor in a movable, NON-modal window.

        No grab_set / focus_force: the ladder pop-out and main window keep working
        while the editor is open. Every edit commits → redraws the live canvas
        (docked or popped out) immediately.
        """
        if self._rung_editor_popout is not None:
            return
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title(f"Rung editor - {self.project.name}")
        win.minsize(*_PROG_RUNG_EDITOR_MIN)
        apply_saved_geometry(
            win,
            _PROG_RUNG_EDITOR_GEOM_KEY,
            default_w=_PROG_RUNG_EDITOR_DEFAULT[0],
            default_h=_PROG_RUNG_EDITOR_DEFAULT[1],
            min_w=_PROG_RUNG_EDITOR_MIN[0],
            min_h=_PROG_RUNG_EDITOR_MIN[1],
        )
        win.protocol("WM_DELETE_WINDOW", self._dock_rung_editor)
        self._rung_editor_popout = win
        self._rung_editor_geom_flush = bind_geometry_autosave(
            win, _PROG_RUNG_EDITOR_GEOM_KEY, min_w=_PROG_RUNG_EDITOR_MIN[0], min_h=_PROG_RUNG_EDITOR_MIN[1]
        )
        body = ctk.CTkScrollableFrame(win, fg_color=BG)
        body.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_rung_editor_controls(body, floating=True)
        self._bind_edit_shortcuts(win)
        # Docked strip collapses to a one-line hint + Dock button (keeps pack order).
        self._clear_children(self._rung_bar)
        section_label(self._rung_bar, "RUNG EDITOR", self.fonts.tiny).pack(side="left", padx=(4, 8))
        ctk.CTkLabel(
            self._rung_bar,
            text="Floating — drag it anywhere (other monitor too). Edits update the ladder live.",
            font=self.fonts.tiny,
            text_color=MUTED,
        ).pack(side="left", padx=6)
        ghost_button(self._rung_bar, "Dock editor", self._dock_rung_editor, self.fonts.tiny, width=110).pack(
            side="left", padx=4
        )
        # -topmost only sticks once the window is mapped (X11 + Windows WMs).
        try:
            win.update_idletasks()
        except Exception:
            pass
        self._apply_rung_editor_on_top()
        try:
            win.after(120, self._apply_rung_editor_on_top)
            # The main window finishes loading after this and lands on top; bring the editor back to the front.
            for delay in (300, 900, 2000):
                win.after(delay, self._raise_rung_editor)
        except Exception:
            pass
        self._mirror_status()
        _save_ui_pref(_PROG_RUNG_EDITOR_FLOAT_PREF, True)

    @staticmethod
    def _keep_on_screen(win) -> None:
        """Pull a window back when its saved spot is on a monitor that is no longer there."""
        try:
            import ctypes

            metrics = ctypes.windll.user32.GetSystemMetrics
            vx, vy, vw, vh = metrics(76), metrics(77), metrics(78), metrics(79)
        except Exception:
            vx, vy, vw, vh = 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()
        x, y = win.winfo_rootx(), win.winfo_rooty()
        if vw <= 0 or vh <= 0 or (vx <= x <= vx + vw - 120 and vy <= y <= vy + vh - 80):
            return
        win.geometry(f"+{max(40, vx + 80)}+{max(20, vy + 60)}")

    def _raise_rung_editor(self) -> None:
        win = self._rung_editor_popout
        try:
            if win is None or not win.winfo_exists():
                return
            if win.state() in ("iconic", "withdrawn"):
                win.deiconify()
            self._keep_on_screen(win)
            win.lift()
            win.attributes("-topmost", True)
            if not self._rung_editor_on_top.get():
                win.after(50, lambda: win.winfo_exists() and win.attributes("-topmost", False))
        except Exception:
            pass

    def _close_rung_editor_window(self) -> None:
        win = self._rung_editor_popout
        if win is None:
            return
        if self._rung_editor_geom_flush:
            try:
                self._rung_editor_geom_flush()
            except Exception:
                pass
            self._rung_editor_geom_flush = None
        else:
            remember_window_geometry(
                win, _PROG_RUNG_EDITOR_GEOM_KEY, min_w=_PROG_RUNG_EDITOR_MIN[0], min_h=_PROG_RUNG_EDITOR_MIN[1]
            )
        self._rung_editor_popout = None
        self._rung_editor_status = None
        try:
            win.destroy()
        except Exception:
            pass

    def _dock_rung_editor(self) -> None:
        if self._rung_editor_popout is None:
            return
        self._close_rung_editor_window()
        _save_ui_pref(_PROG_RUNG_EDITOR_FLOAT_PREF, False)
        try:
            self._clear_children(self._rung_bar)
            self._build_rung_editor_controls(self._rung_bar, floating=False)
        except Exception:
            pass

    def _mirror_status(self) -> None:
        """Floating editor shows the same status line as the main window."""
        lbl = self._rung_editor_status
        if lbl is None:
            return
        try:
            lbl.configure(text=self.status.cget("text"))
        except Exception:
            pass

    def _dialog_parent(self):
        """Parent for small dialogs: floating editor when open (so they stay visible)."""
        win = self._rung_editor_popout
        try:
            if win is not None and win.winfo_exists():
                return win
        except Exception:
            pass
        return self

    def _mount_ladder_canvas(self, parent) -> None:
        """Create ladder canvas + scrollbars under parent (home body or pop-out)."""
        self.ladder_wrap = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=0)
        self.canvas = tk.Canvas(self.ladder_wrap, background=self._lbg, highlightthickness=0)
        self.vbar = ctk.CTkScrollbar(self.ladder_wrap, orientation="vertical", command=self._on_vbar)
        self.hbar = ctk.CTkScrollbar(self.ladder_wrap, orientation="horizontal", command=self._on_hbar)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.vbar.pack(side="right", fill="y")
        self.hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<ButtonPress-1>", self._ladder_drag_press, add="+")
        self.canvas.bind("<B1-Motion>", self._ladder_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._ladder_drag_release)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._hide_hover_tip)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._wheel_x)
        self.canvas.bind("<Button-4>", lambda _e=None: (self._note_manual_scroll(), self.canvas.yview_scroll(-1, "units")))
        self.canvas.bind("<Button-5>", lambda _e=None: (self._note_manual_scroll(), self.canvas.yview_scroll(1, "units")))
        self.ladder_wrap.bind("<MouseWheel>", self._wheel)
        self.ladder_wrap.bind("<Shift-MouseWheel>", self._wheel_x)
        self.vbar.bind("<MouseWheel>", self._wheel)
        self.hbar.bind("<MouseWheel>", self._wheel_x)

    def _sync_popout_button_labels(self, *, popped: bool) -> None:
        """The single pop-out control reads Dock ladder while the ladder floats."""
        try:
            self._popout_btn.configure(text="Dock ladder" if popped else "Pop out ladder")
        except Exception:
            pass

    def _toggle_canvas_popout(self) -> None:
        if self._canvas_popout is not None:
            self._dock_ladder_canvas()
        else:
            self._pop_out_ladder_canvas()

    def _pop_out_ladder_canvas(self) -> None:
        if self._canvas_popout is not None:
            return
        self._hide_hover_tip()
        try:
            self.ladder_wrap.pack_forget()
        except Exception:
            pass
        try:
            self.ladder_wrap.destroy()
        except Exception:
            pass

        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title(f"Ladder view - {self.project.name}")
        win.minsize(*_PROG_CANVAS_MIN)
        # Free-float: no transient so it can sit on a second monitor.
        apply_saved_geometry(
            win,
            _PROG_CANVAS_GEOM_KEY,
            default_w=_PROG_CANVAS_DEFAULT[0],
            default_h=_PROG_CANVAS_DEFAULT[1],
            min_w=_PROG_CANVAS_MIN[0],
            min_h=_PROG_CANVAS_MIN[1],
            parent=self,
            center_fallback=False,
        )
        win.protocol("WM_DELETE_WINDOW", self._dock_ladder_canvas)
        self._canvas_popout = win
        self._canvas_geom_flush = bind_geometry_autosave(
            win, _PROG_CANVAS_GEOM_KEY, min_w=_PROG_CANVAS_MIN[0], min_h=_PROG_CANVAS_MIN[1]
        )
        top = ctk.CTkFrame(win, fg_color=PANEL, corner_radius=0)
        top.pack(fill="x")
        self.commands.button(top, "view.popout", text="Dock ladder", width=100, font=self.fonts.small).pack(
            side="right", padx=8, pady=3
        )
        self._ladder_simbar = SimToolbar(top, self)
        self._ladder_simbar.pack(side="left", padx=4, pady=2)
        self._sim_toolbars.append(self._ladder_simbar)
        self._mount_ladder_canvas(win)
        self._bind_edit_shortcuts(win)
        self._apply_rung_editor_on_top()
        if self._sim_session and self._force_popout is None:
            self._pop_out_force_strip()
        self._apply_force_on_top()
        self._apply_ai_on_top()
        self.ladder_wrap.pack(fill="both", expand=True, padx=8, pady=8)
        self._sync_popout_button_labels(popped=True)
        self._apply_tab_layout()
        try:
            win.update_idletasks()
        except Exception:
            pass
        self._draw_ladder(preserve_scroll=False)
        # Second draw after the pop-out has a real pixel size (first pass may see ~1px).
        try:
            win.after(40, lambda: self._draw_ladder(False))
        except Exception:
            pass
        try:
            win.lift()
        except Exception:
            pass

    def _dock_ladder_canvas(self) -> None:
        """Return ladder canvas to the home Programming window; keep sim state."""
        win = self._canvas_popout
        if win is None:
            return
        self._hide_hover_tip()
        if self._canvas_geom_flush:
            try:
                self._canvas_geom_flush()
            except Exception:
                pass
            self._canvas_geom_flush = None
        else:
            remember_window_geometry(
                win, _PROG_CANVAS_GEOM_KEY, min_w=_PROG_CANVAS_MIN[0], min_h=_PROG_CANVAS_MIN[1]
            )
        self._canvas_popout = None
        self._ladder_simbar = None
        self._apply_rung_editor_on_top()  # re-parent transient before the pop-out dies
        self._apply_force_on_top()
        self._apply_ai_on_top()
        try:
            win.destroy()
        except Exception:
            pass
        self._mount_ladder_canvas(self.body)
        self._sync_popout_button_labels(popped=False)
        self._apply_tab_layout()
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._draw_ladder(preserve_scroll=False)
        try:
            self.after(40, lambda: self._draw_ladder(False))
        except Exception:
            pass

    def _open_maximized(self) -> None:
        """Use nearly the full screen so ladder symbols and device labels stay readable."""
        try:
            self.update_idletasks()
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
            # Leave a thin margin so Windows taskbar / title chrome stay usable.
            margin = 8
            self.geometry(f"{max(1100, sw - margin * 2)}x{max(720, sh - margin * 2 - 40)}+{margin}+{margin}")
        except Exception:
            self.geometry("1280x860+40+20")
        try:
            self.state("zoomed")
        except Exception:
            try:
                self.attributes("-zoomed", True)
            except Exception:
                pass

    def _arm(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self._open_maximized()
        except Exception:
            return

    def _tag_choices(self) -> list[str]:
        tags = [d["tag"] for d in cabinet_device_tags(self.project)]
        # Timer / counter done bits usable as contacts (T1.DN, C1.DN …).
        program = getattr(self, "program", None) or {}
        seen = set(tags)
        for rung in program.get("rungs") or []:
            for key in ("timer", "counter"):
                blk = rung.get(key) if isinstance(rung.get(key), dict) else None
                name = (blk.get("tag") or "").strip() if blk else ""
                if name and f"{name}.DN" not in seen:
                    seen.add(f"{name}.DN")
                    tags.append(f"{name}.DN")
            for el in rung.get("elements") or []:
                if isinstance(el, dict) and str(el.get("kind") or "").lower() == "oneshot":
                    out_bit = str(el.get("output") or "").strip()
                    if out_bit and out_bit not in seen:
                        seen.add(out_bit)
                        tags.append(out_bit)
        return tags if tags else ["(no device tags)"]

    def _refresh_tag_menus(self) -> None:
        try:
            values = self._tag_choices()
            self.contact_menu.configure(values=values)
            self.coil_menu.configure(values=values)
        except Exception:
            pass

    def _show_idle_question_prompt(self) -> None:
        self._asking = False
        for child in self.q_choices.winfo_children():
            child.destroy()
        has_rungs = bool(self.program.get("rungs"))
        if has_rungs and program_looks_edited(self.program):
            self.q_label.configure(
                text="A program is already saved with this cabinet. Press Ask questions to rebuild it "
                "(you will be asked before anything is replaced), or edit the ladder / text below."
            )
        elif not has_rungs:
            self.q_label.configure(
                text="No rungs yet — answer the questions or click Build starter program. "
                "Build from drawings uses the devices and wires already on this cabinet (no invented tags)."
            )
        else:
            self.q_label.configure(
                text="Press Ask questions. We will ask a few easy questions one at a time, "
                "then draw a real ladder you can edit and copy."
            )
        if not has_rungs:
            primary_button(
                self.q_choices, "Build starter program", self._build_starter_program, self.fonts.small, width=180
            ).pack(side="left", padx=4)
            ghost_button(
                self.q_choices, "Build from drawings", self._build_from_drawings, self.fonts.small, width=160
            ).pack(side="left", padx=4)
        ghost_button(self.q_choices, "Ask questions", self.start_questions, self.fonts.small, width=140).pack(
            side="left", padx=4
        )

    def _offer_starter_if_empty(self) -> None:
        """When Programming opens with no rungs, auto-offer a starter so the ladder is not blank."""
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if self._asking or (self.program.get("rungs") or []):
            return
        answer = ask_choice(
            self,
            self.fonts,
            "No rungs yet",
            "No rungs yet — answer the questions or click Build starter program. "
            "Build a starter now from the devices already on this cabinet?",
            [
                ("build", "Build starter program", "primary"),
                ("questions", "Ask questions", "ghost"),
                ("later", "Later", ""),
            ],
        )
        if answer == "build":
            self._build_starter_program(confirm=False)
        elif answer == "questions":
            self.start_questions()

    def _confirm_replace_program(self) -> bool:
        if not program_looks_edited(self.program):
            return True
        if not (self.program.get("rungs") or []):
            return True
        answer = ask_choice(
            self,
            self.fonts,
            "Replace program?",
            "You already edited or saved a program for this cabinet. "
            "Replace it with a new starter from the cabinet devices?",
            [("yes", "Replace", "primary"), ("no", "Keep mine", "ghost")],
        )
        return answer == "yes"

    def _apply_built_program(self, program: dict, status: str) -> None:
        self._scan_sim = None
        self.program = program
        self.program["text_edited"] = False
        self._answers = dict(self.program.get("answers") or {})
        self._device_map = devices_by_tag(self.project)
        if self.program.get("rungs"):
            self._selected_rung_id = self.program["rungs"][0]["id"]
        else:
            self._selected_rung_id = None
        self._commit(status=status)
        self._show_tab("ladder")
        self._show_idle_question_prompt()

    def _build_starter_program(self, confirm: bool = True) -> None:
        """Build a starter ladder from design defaults (cabinet device tags only)."""
        if confirm and not self._confirm_replace_program():
            self.status.configure(text="Kept your existing program.")
            return
        answers = default_design_answers(self.project)
        program = build_starter_program(self.project, answers)
        if not program.get("rungs"):
            self._apply_built_program(
                program,
                status="No rungs yet — this cabinet has no start/stop/coil tags to wire. "
                "Add devices on the panel, or answer the questions / Add rung.",
            )
            return
        self._apply_built_program(
            program,
            status="Starter ladder built from cabinet devices. Edit symbols or text, then Save the cabinet.",
        )

    def _build_from_drawings(self) -> None:
        """Same as starter-from-design: use devices/wires already on the cabinet (no invented tags)."""
        self._build_starter_program(confirm=True)

    def start_questions(self) -> None:
        if program_looks_edited(self.program):
            answer = ask_choice(
                self,
                self.fonts,
                "Replace program?",
                "You already edited or saved a program for this cabinet. "
                "Replace it with a new starter from the questions?",
                [("yes", "Replace", "primary"), ("no", "Keep mine", "ghost")],
            )
            if answer != "yes":
                self.status.configure(text="Kept your existing program.")
                return
        self._answers = {}
        self._q_index = 0
        self._asking = True
        self._show_current_question()

    def _show_current_question(self) -> None:
        for child in self.q_choices.winfo_children():
            child.destroy()
        if self._q_index >= len(PROGRAM_QUESTIONS):
            self._finish_questions()
            return
        key, prompt, options = PROGRAM_QUESTIONS[self._q_index]
        step = f"Question {self._q_index + 1} of {len(PROGRAM_QUESTIONS)}"
        self.q_label.configure(text=f"{step}: {prompt}")
        for option in options:
            ghost_button(
                self.q_choices,
                option,
                lambda chosen=option, answer_key=key: self._answer(answer_key, chosen),
                self.fonts.small,
                width=min(420, 40 + 7 * len(option)),
            ).pack(side="left", padx=4, pady=2)

    def _answer(self, key: str, value: str) -> None:
        self._answers[key] = value
        self._q_index += 1
        self._show_current_question()

    def _finish_questions(self) -> None:
        self._asking = False
        self.program = build_starter_program(self.project, self._answers)
        self.program["text_edited"] = False
        self._device_map = devices_by_tag(self.project)
        if self.program.get("rungs"):
            self._selected_rung_id = self.program["rungs"][0]["id"]
        self._commit(status="Starter ladder built from your answers. Edit symbols or text, then Save the cabinet.")
        self._show_tab("ladder")
        self._show_idle_question_prompt()

    def _show_tab(self, tab: str) -> None:
        self._flush_editor_to_program()
        self._tab = tab
        label = {"ladder": "LADDER", "plc": "PLC TEXT", "hmi": "HMI"}.get(tab, tab.upper())
        self.tab_label.configure(text=label)
        self._apply_tab_layout()
        self._load_editor()
        if tab in {"ladder", "plc"}:
            self._draw_ladder()

    def _apply_tab_layout(self) -> None:
        """Pack home-body widgets for the active tab.

        When the ladder is popped out, never pack_forget ladder_wrap — that would
        unpack it from the free-float window and leave a black blank pop-out.
        Only manage the home body (placeholder + editor); keep/ensure ladder_wrap
        packed on the pop-out.
        """
        popped = self._canvas_popout is not None
        try:
            self._canvas_placeholder.pack_forget()
        except Exception:
            pass
        self.editor.pack_forget()

        if popped:
            # Ladder stays in the pop-out window — re-assert pack, do not forget.
            try:
                self.ladder_wrap.pack(fill="both", expand=True, padx=8, pady=8)
            except Exception:
                pass
            if self._tab in {"ladder", "plc"}:
                self._canvas_placeholder.pack(fill="both", expand=True, padx=4, pady=(4, 2))
                if self._tab == "ladder":
                    if self._built_layout == "classic":
                        self.editor.configure(height=160)
                        self.editor.pack(fill="x", expand=False, padx=4, pady=(2, 4))
                else:
                    self.editor.configure(height=220)
                    self.editor.pack(fill="both", expand=True, padx=4, pady=(2, 4))
            else:
                self.editor.configure(height=400)
                self.editor.pack(fill="both", expand=True, padx=4, pady=4)
            return

        # Docked: ladder lives in home body.
        try:
            self.ladder_wrap.pack_forget()
        except Exception:
            pass
        if self._tab == "ladder":
            # Studio: the PLC text pane only shows on its own tab, so the ladder gets the space.
            self.ladder_wrap.pack(fill="both", expand=True, padx=4, pady=(4, 2))
            if self._built_layout == "classic":
                self.editor.configure(height=160)
                self.editor.pack(fill="x", expand=False, padx=4, pady=(2, 4))
        elif self._tab == "plc":
            self.ladder_wrap.pack(fill="both", expand=True, padx=4, pady=(4, 2))
            self.editor.configure(height=220)
            self.editor.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        else:
            self.editor.configure(height=400)
            self.editor.pack(fill="both", expand=True, padx=4, pady=4)

    def _load_editor(self) -> None:
        if self._tab == "hmi":
            text = self.program.get("hmi_text", "") or format_hmi_text(self.program.get("hmi_items") or [])
        else:
            text = self.program.get("plc_text", "")
            if not (text or "").strip():
                text = format_plc_text(self.program.get("rungs") or [], cabinet_device_tags(self.project))
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)

    def _on_typed(self, _event=None) -> None:
        self.program["text_edited"] = True
        self._flush_editor_to_program()
        self._commit(status="Program text edited by hand. Sync text from ladder will warn before overwrite.", mark_dirty_only=True)

    def _flush_editor_to_program(self) -> None:
        content = self.editor.get("1.0", "end-1c")
        if self._tab == "hmi":
            self.program["hmi_text"] = content
        else:
            self.program["plc_text"] = content

    def _commit(self, status: str = "", mark_dirty_only: bool = False) -> None:
        self.project.program = program_to_dict(self.program)
        if not mark_dirty_only and self._sim_session:
            self._scan_sim = None  # running sim picks up the edit, keeping its live state
        if not mark_dirty_only and not getattr(self, "_restoring", False) and hasattr(self, "_history"):
            self._history.record(self.project.program, label=(status or "Edit")[:60])
            self._update_undo_buttons()
        if self.on_change:
            self.on_change(status or "Program updated")
        if not mark_dirty_only and hasattr(self, "statusbar"):
            self._schedule_error_count()
        if status:
            self.status.configure(text=status)
        self._mirror_status()
        self._draw_ladder()
        self._refresh_open_tool_panels()
        if self._alive(self.organizer):
            self.organizer.refresh()

    def copy_plc(self) -> None:
        self._flush_editor_to_program()
        if not self.program.get("text_edited"):
            self.program = refresh_plc_text(self.program, self.project)
        text = self.program.get("plc_text") or ""
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text="PLC text copied. Paste it into your real PLC programmer.")

    def copy_hmi(self) -> None:
        self._flush_editor_to_program()
        text = self.program.get("hmi_text") or ""
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text="HMI text copied.")

    def export_txt(self) -> None:
        from pathlib import Path
        from tkinter import filedialog

        self._flush_editor_to_program()
        chosen = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("JSON", "*.json"), ("All files", "*.*")],
            initialfile="cabinet-program.txt",
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() == ".json":
            import json

            path.write_text(json.dumps(program_to_dict(self.program), indent=2) + "\n", encoding="utf-8")
        else:
            body = (
                self.program.get("plc_text", "")
                + "\n\n========== HMI ==========\n\n"
                + self.program.get("hmi_text", "")
            )
            path.write_text(body, encoding="utf-8")
        self.status.configure(text=f"Exported {path.name}")

    def _sync_text_from_ladder(self) -> None:
        if self.program.get("text_edited"):
            answer = ask_choice(
                self,
                self.fonts,
                "Overwrite hand-edited text?",
                "You edited the PLC text by hand. Regenerate it from the visual ladder? "
                "Your typed changes will be replaced.",
                [("yes", "Overwrite from ladder", "primary"), ("no", "Keep my text", "ghost")],
            )
            if answer != "yes":
                self.status.configure(text="Kept your hand-edited PLC text.")
                return
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = False
        if self._tab != "hmi":
            self._load_editor()
        self._commit(status="PLC text regenerated from the visual ladder.")

    def _add_rung(self) -> None:
        contact = self.contact_var.get().strip()
        coil = self.coil_var.get().strip()
        if not contact or contact.startswith("(") or not coil or coil.startswith("("):
            self.status.configure(text="Pick contact and coil tags from devices on this cabinet.")
            return
        comment = self.comment_entry.get().strip()
        self.program = add_rung(
            self.program,
            contact_tag=contact,
            coil_tag=coil,
            normally_closed=self.nc_var.get() == "NC",
            comment=comment,
        )
        # Keep device captions in regenerated text.
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._show_tab("ladder")
        self._commit(status=f"Added rung {contact} -> {coil}")

    def _parse_timer_pt_ms(self) -> int:
        raw = (self.timer_pt_entry.get() or "").strip() or "1000"
        try:
            return max(0, int(float(raw)))
        except ValueError:
            return 1000

    def _add_timer_rung(self) -> None:
        contact = self.contact_var.get().strip()
        timer_tag = (self.timer_tag_entry.get() or "").strip()
        if not contact or contact.startswith("("):
            self.status.configure(text="Pick a contact tag, then Add timer.")
            return
        if not timer_tag:
            self.status.configure(text="Enter a timer tag (e.g. T1).")
            return
        block = (self.timer_block_var.get() or "TON").upper()
        pt_ms = self._parse_timer_pt_ms()
        coil = self.coil_var.get().strip()
        if coil.startswith("("):
            coil = ""
        comment = self.comment_entry.get().strip() or f"{block} {timer_tag} PT={pt_ms}ms"
        self.program = add_timer_rung(
            self.program,
            contact_tag=contact,
            timer_tag=timer_tag,
            block=block,
            pt_ms=pt_ms,
            normally_closed=self.nc_var.get() == "NC",
            coil_tag=coil,
            comment=comment,
        )
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._scan_sim = None
        self._refresh_tag_menus()
        self._show_tab("ladder")
        self._commit(status=f"Added {block} timer {timer_tag} (PT={pt_ms}ms) on contact {contact}")

    def _parse_counter_pv(self) -> int:
        raw = (self.counter_pv_entry.get() or "").strip() or "5"
        try:
            return max(-32768, min(32767, int(float(raw))))
        except ValueError:
            return 5

    def _add_counter_rung(self) -> None:
        """Place a CTU / CTD (or RES / LOAD) counter rung — educational scan, not a live PLC."""
        contact = self.contact_var.get().strip()
        counter_tag = (self.counter_tag_entry.get() or "").strip()
        if not contact or contact.startswith("("):
            self.status.configure(text="Pick a contact tag (count / reset input), then Add counter.")
            return
        if not counter_tag:
            self.status.configure(text="Enter a counter tag (e.g. C1).")
            return
        block = (self.counter_block_var.get() or "CTU").upper()
        pv = self._parse_counter_pv()
        coil = self.coil_var.get().strip()
        if coil.startswith("(") or block in {"RES", "LOAD"}:
            coil = ""
        if block in {"CTU", "CTD"}:
            default_comment = f"{block} {counter_tag} PRE={pv}"
        else:
            default_comment = f"{block} {counter_tag}"
        comment = self.comment_entry.get().strip() or default_comment
        self.program = add_counter_rung(
            self.program,
            contact_tag=contact,
            counter_tag=counter_tag,
            block=block,
            pv=pv,
            normally_closed=self.nc_var.get() == "NC",
            coil_tag=coil,
            comment=comment,
        )
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._scan_sim = None
        self._refresh_tag_menus()
        self._show_tab("ladder")
        what = f"{block} counter {counter_tag} (PRE={pv})" if block in {"CTU", "CTD"} else f"{block} on counter {counter_tag}"
        self._commit(status=f"Added {what} on contact {contact}. Use {counter_tag}.DN as a contact for the done bit.")


    def _add_nested_or_rung(self) -> None:
        """Lead contact + OR of contact|coil seal + optional series Stop, then coil.

        Educational nested-OR demo: uses contact menu as lead, coil as output,
        and builds (lead) -- (lead OR coil) style only when seal-like; otherwise
        asks for a second contact via the comment field as "TAG2" or uses the
        selected contact twice with a nested OR of contact OR (coil).
        Preferred: contact=A, coil=OUT, comment="B|C&D" meaning branches B and (C series D nested OR skipped).
        Simple default: A -- (A OR B) -- (OUT) where B is typed in comment or defaults to coil seal.
        """
        contact = self.contact_var.get().strip()
        coil = self.coil_var.get().strip()
        if not contact or contact.startswith("(") or not coil or coil.startswith("("):
            self.status.configure(text="Pick lead contact and coil, then Add nested OR.")
            return
        comment_raw = self.comment_entry.get().strip()
        # Parse branches: "B|C" => two contact branches; "B|(C|D)" not fully parsed —
        # default educational pattern: (contact) OR (coil seal) with nested (X|Y) from comment.
        branches: list[list[dict]] = [[{"tag": contact, "normally_closed": False}]]
        if comment_raw and "|" in comment_raw.split(" ")[0]:
            # e.g. B|C or B|C,D  — comma = series within branch, | = OR
            spec = comment_raw.split(" ")[0]
            branches = []
            for part in spec.split("|"):
                series_tags = [t.strip() for t in part.split(",") if t.strip()]
                if not series_tags:
                    continue
                if len(series_tags) == 1:
                    branches.append([{"tag": series_tags[0], "normally_closed": False}])
                else:
                    # First tag series with nested OR of remaining? Keep as series contacts.
                    branches.append(
                        [{"tag": t, "normally_closed": False} for t in series_tags]
                    )
            note = f"Nested OR {spec}"
        else:
            # Classic seal-style outer OR of lead and coil, plus optional second tag in comment
            second = comment_raw.split()[0] if comment_raw else ""
            if second and second.upper() not in {"NC", "NO"} and not second.startswith("("):
                # Nested: branch0=second, branch1=nested OR of contact|coil? Keep simple:
                # lead -- (second OR (contact series unused)) 
                branches = [
                    [{"tag": second, "normally_closed": False}],
                    [
                        {
                            "kind": "or",
                            "branches": [
                                [{"kind": "contact", "var": contact, "form": "NO"}],
                                [{"kind": "contact", "var": coil, "form": "NO"}],
                            ],
                        }
                    ],
                ]
                note = f"Nested OR {second}|( {contact} OR {coil} )"
            else:
                branches = [
                    [{"tag": contact, "normally_closed": False}],
                    [{"tag": coil, "normally_closed": False}],
                ]
                note = comment_raw or f"{contact} OR {coil} seal-style"
        self.program = add_nested_or_rung(
            self.program,
            lead_tag="",
            or_branches=branches,
            coil_tag=coil,
            comment=note,
        )
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._scan_sim = None
        self._refresh_tag_menus()
        self._show_tab("ladder")
        self._commit(status=f"Added nested OR rung → {coil}")

    def _add_mid_coil_rung(self) -> None:
        """[contact]-(mid)-(same contact as enable for second?)-[coil] using comment as mid tag.

        contact menu = first contact, coil menu = final coil, comment = mid coil tag
        (default MID1). Second contact defaults to the same contact tag (teach passthrough)
        unless comment has "mid/after" form: MID/PB_Enable.
        """
        contact = self.contact_var.get().strip()
        coil = self.coil_var.get().strip()
        if not contact or contact.startswith("(") or not coil or coil.startswith("("):
            self.status.configure(text="Pick contact and final coil, then Add mid coil.")
            return
        raw = self.comment_entry.get().strip()
        if "/" in raw:
            mid, after = [p.strip() for p in raw.split("/", 1)]
        elif raw and not raw.startswith("("):
            mid, after = raw, contact
        else:
            mid, after = "MID1", contact
        if not mid:
            mid = "MID1"
        if not after:
            after = contact
        self.program = add_mid_coil_rung(
            self.program,
            contact_tag=contact,
            mid_coil_tag=mid,
            after_contact_tag=after,
            coil_tag=coil,
            normally_closed=self.nc_var.get() == "NC",
            comment=f"Mid-rung {mid} then {coil}",
        )
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._scan_sim = None
        self._refresh_tag_menus()
        self._show_tab("ladder")
        self._commit(status=f"Added mid-rung coil {mid} → {coil}")

    def _picked(self, var) -> str:
        value = (var.get() or "").strip()
        return "" if value.startswith("(") else value

    def _after_element_add(self, status: str) -> None:
        """Shared tail for element-based Add* buttons (no overwrite prompt)."""
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._scan_sim = None
        self._refresh_tag_menus()
        self._show_tab("ladder")
        self._commit(status=status)

    def _add_compare_rung(self) -> None:
        contact = self._picked(self.contact_var)
        coil = self._picked(self.coil_var)
        op = (self.compare_op_entry.get() or "EQU").strip()
        a = (self.compare_a_entry.get() or "").strip()
        b = (self.compare_b_entry.get() or "").strip()
        c = (self.compare_c_entry.get() or "").strip() if getattr(self, "compare_c_entry", None) else ""
        if not contact or not coil or not a:
            self.status.configure(text="Pick contact + coil, and set compare A/B[/C], then Add compare.")
            return
        self.program = add_compare_rung(
            self.program,
            contact_tag=contact,
            op=op,
            source_a=a,
            source_b=b or "0",
            source_c=c,
            coil_tag=coil,
            normally_closed=self.nc_var.get() == "NC",
            comment=self.comment_entry.get().strip(),
        )
        detail = f"{a},{b or '0'}" + (f",{c}" if c else "")
        self._after_element_add(f"Added compare {op.upper()} {detail} → {coil}.")

    def _add_lim_rung(self) -> None:
        """LIM Low<=Test<=High — uses compare A=Test, B=Low, C=High."""
        self._rung_field_vars["compare_op"].set("LIM")
        self._add_compare_rung()

    def _add_meq_rung(self) -> None:
        """MEQ (Source & Mask) == (Compare & Mask) — A=Source, B=Mask, C=Compare."""
        self._rung_field_vars["compare_op"].set("MEQ")
        self._add_compare_rung()

    def _add_bitwise_rung(self) -> None:
        """AND/OR/XOR/NOT via math box (op from Math field; default AND)."""
        op = (self.math_op_entry.get() or "AND").strip().upper()
        if op not in {"AND", "OR", "XOR", "NOT"}:
            self._rung_field_vars["math_op"].set("AND")
        else:
            self._rung_field_vars["math_op"].set(op)
        self._add_math_rung()

    def _add_aoi_template(self) -> None:
        name = ""
        if getattr(self, "aoi_name_entry", None) is not None:
            name = (self.aoi_name_entry.get() or "").strip()
        if not name and self._rung_field_vars.get("aoi_name"):
            name = (self._rung_field_vars["aoi_name"].get() or "").strip()
        name = name or "MotorStarter"
        try:
            before = len(self.program.get("rungs") or [])
            self.program = add_aoi_template_rungs(self.program, name)
            added = len(self.program.get("rungs") or []) - before
            self._after_element_add(f"Inserted AOI template {name} (+{added} rung{'s' if added != 1 else ''}).")
        except Exception as exc:
            self.status.configure(text=f"AOI template: {exc}")

    def _add_math_rung(self) -> None:
        contact = self._picked(self.contact_var)
        op = (self.math_op_entry.get() or "ADD").strip()
        dest = (self.math_dest_entry.get() or "").strip()
        a = (self.compare_a_entry.get() or "").strip()
        b = (self.compare_b_entry.get() or "").strip()
        if not contact or not dest:
            self.status.configure(text="Pick contact, set DEST (and A/B), then Add math.")
            return
        self.program = add_math_rung(
            self.program,
            contact_tag=contact,
            op=op,
            dest=dest,
            source_a=a or "0",
            source_b=b or "0",
            normally_closed=self.nc_var.get() == "NC",
            comment=self.comment_entry.get().strip(),
        )
        self._after_element_add(f"Added math {op.upper()} → {dest}.")

    def _add_latch(self, latch: bool) -> None:
        contact = self._picked(self.contact_var)
        coil = self._picked(self.coil_var)
        label = "OTL" if latch else "OTU"
        if not contact or not coil:
            self.status.configure(text=f"Pick contact and coil, then Add {label}.")
            return
        self.program = add_latch_rung(
            self.program,
            contact_tag=contact,
            coil_tag=coil,
            latch=latch,
            normally_closed=self.nc_var.get() == "NC",
            comment=self.comment_entry.get().strip(),
        )
        self._after_element_add(f"Added {label} ({'set' if latch else 'reset'}) {coil}.")

    def _add_otl_rung(self) -> None:
        self._add_latch(True)

    def _add_otu_rung(self) -> None:
        self._add_latch(False)

    def _add_oneshot_rung(self) -> None:
        """ONS / OSR / OSF one-shot rung (Studio/CCW-style educational)."""
        contact = self._picked(self.contact_var)
        block = (self.oneshot_block_var.get() or "ONS").upper()
        storage = (self.oneshot_storage_entry.get() or "").strip()
        output = (self.oneshot_output_entry.get() or "").strip()
        if not contact:
            self.status.configure(text="Pick a contact (the input to edge-detect), then Add one-shot.")
            return
        if not storage:
            self.status.configure(text="Enter a storage bit for the one-shot (e.g. OS1). Use a unique bit per one-shot.")
            return
        coil = self._picked(self.coil_var) if block == "ONS" else ""
        if block in {"OSR", "OSF"} and not output:
            self.status.configure(text=f"{block} needs an output bit (e.g. OS1_Pulse).")
            return
        try:
            self.program = add_oneshot_rung(
                self.program,
                contact_tag=contact,
                block=block,
                storage_tag=storage,
                output_tag=output if block != "ONS" else "",
                coil_tag=coil,
                normally_closed=self.nc_var.get() == "NC",
                comment=self.comment_entry.get().strip(),
            )
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return
        if block == "ONS":
            what = f"ONS {storage} on {contact}" + (f" → {coil} (TRUE one scan per press)" if coil else "")
        else:
            what = f"{block} {storage} → pulse bit {output}. Use {output} as a contact on another rung."
        self._after_element_add(f"Added one-shot: {what}")

    # --- Undo / redo (session history) -----------------------------------

    def _bind_edit_shortcuts(self, widget) -> None:
        for seq, fn in (
            ("<Control-z>", self._undo),
            ("<Control-Z>", self._redo),
            ("<Control-y>", self._redo),
            ("<Control-Shift-Z>", self._redo),
        ):
            try:
                widget.bind(seq, fn, add="+")
            except Exception:
                pass
        # v0.3.7 keyboard shortcuts (text-safe ones also fire while typing).
        for seq, fn, text_safe in self._shortcut_bindings():
            try:
                widget.bind(seq, self._kb(fn, text_safe=text_safe), add="+")
            except Exception:
                pass

    def _shortcut_bindings(self) -> list[tuple[str, object, bool]]:
        return [
            ("<Control-c>", self._copy_rung, False),
            ("<Control-v>", self._paste_rung, False),
            ("<Control-d>", self._duplicate_rung, False),
            ("<Control-C>", self._copy_instruction, False),
            ("<Control-V>", self._paste_instruction, False),
            ("<Delete>", self._delete_selected_rung, False),
            ("<Up>", lambda: self._select_rung_offset(-1), False),
            ("<Down>", lambda: self._select_rung_offset(1), False),
            ("<Home>", lambda: self._select_rung_edge(first=True), False),
            ("<End>", lambda: self._select_rung_edge(first=False), False),
            ("<Control-Up>", self._move_rung_up, False),
            ("<Control-Down>", self._move_rung_down, False),
            ("<Control-f>", self._open_find_replace, False),
            ("<Control-h>", lambda: self._open_find_replace(focus_replace=True), False),
            ("<Control-t>", self._open_tag_list, False),
            ("<Control-e>", self._edit_rung_comments, False),
            ("<F7>", self._open_verify_panel, True),
            ("<F5>", self._sim_toggle_run, True),
            ("<Shift-F5>", self._sim_stop, True),
            ("<F10>", self._sim_step, True),
            ("<F6>", self._sim_step_rung, True),
            ("<F9>", self._sim_pause, True),
            ("<F1>", self._show_shortcuts, True),
        ]

    def _kb(self, fn, *, text_safe: bool = False):
        """Key handler: skip while typing in an entry/text box (unless text-safe)."""

        def handler(_event=None):
            if not text_safe and self._focus_is_text_input():
                return None
            try:
                fn()
            except Exception as exc:  # never let a shortcut kill the Tk loop
                try:
                    self.status.configure(text=f"Shortcut failed: {exc}")
                except Exception:
                    pass
            return "break"

        return handler

    def _focus_is_text_input(self) -> bool:
        try:
            focus = self.focus_get()
        except Exception:
            return False
        return isinstance(focus, (tk.Text, tk.Entry))

    def _update_undo_buttons(self) -> None:
        if not hasattr(self, "_undo_btn") or not hasattr(self, "_history"):
            return
        self._mirror_status()
        undo_n, redo_n = self._history.depth()
        try:
            self._undo_btn.configure(
                text=f"↶ Undo ({undo_n})" if undo_n else "↶ Undo",
                state="normal" if undo_n else "disabled",
            )
            self._redo_btn.configure(
                text=f"↷ Redo ({redo_n})" if redo_n else "↷ Redo",
                state="normal" if redo_n else "disabled",
            )
        except Exception:
            pass

    def _restore_snapshot(self, snapshot: dict, status: str) -> None:
        self.program = program_from_dict(snapshot)
        ids = {r.get("id") for r in self.program.get("rungs") or []}
        if self._selected_rung_id not in ids:
            self._selected_rung_id = (self.program.get("rungs") or [{}])[-1].get("id") if ids else None
        self._scan_sim = None
        self._sim_flow = {}
        self._restoring = True
        try:
            self._commit(status=status)
        finally:
            self._restoring = False
        self._refresh_tag_menus()
        if self._tab != "hmi":
            self._load_editor()
        self._update_undo_buttons()
        if self._sim_running:
            try:
                self._rebuild_force_strip()
            except Exception:
                pass

    def _undo(self, event=None):
        if event is not None and self._focus_is_text_input():
            return None
        label = self._history.undo_label()
        state = self._history.undo()
        if state is None:
            self.status.configure(text="Nothing to undo.")
            return "break"
        self._restore_snapshot(state, f"Undo: {label}")
        return "break"

    def _redo(self, event=None):
        if event is not None and self._focus_is_text_input():
            return None
        label = self._history.redo_label()
        state = self._history.redo()
        if state is None:
            self.status.configure(text="Nothing to redo.")
            return "break"
        self._restore_snapshot(state, f"Redo: {label}")
        return "break"

    # --- Rich rung comments + instruction notes ----------------------------

    def _edit_rung_comments(self) -> None:
        """Multi-line rung comment + per-instruction notes for the selected rung."""
        rungs = self.program.get("rungs") or []
        if not rungs:
            self.status.configure(text="Add a rung first, then Comment… to document it.")
            return
        rung_id = self._selected_rung_id or rungs[-1]["id"]
        rung = next((r for r in rungs if r["id"] == rung_id), None)
        if rung is None:
            self.status.configure(text="Selected rung not found.")
            return
        index = rungs.index(rung) + 1
        owner = self._dialog_parent()
        dlg = ctk.CTkToplevel(owner, fg_color=BG)
        dlg.title(f"Rung {index} comment & instruction notes")
        dlg.geometry("720x560")
        dlg.transient(owner)
        section_label(dlg, f"RUNG {index} COMMENT", self.fonts.tiny).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            dlg,
            text="First line = rung title. Extra lines print under it (design intent, interlocks, why).",
            font=self.fonts.tiny,
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=14)
        box = ctk.CTkTextbox(dlg, height=130, font=self.fonts.small, fg_color=ENTRY, text_color=TEXT, wrap="word")
        box.pack(fill="x", padx=14, pady=(4, 10))
        box.insert("1.0", rung.get("comment") or "")
        section_label(dlg, "INSTRUCTION NOTES", self.fonts.tiny).pack(anchor="w", padx=14, pady=(4, 2))
        notes_frame = ctk.CTkScrollableFrame(dlg, fg_color=PANEL, height=240)
        notes_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        entries: list[tuple[tuple, ctk.CTkEntry, str]] = []
        for path, label, note in rung_instruction_list(rung):
            row = ctk.CTkFrame(notes_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, font=self.fonts.mono_small, text_color=TEXT, width=220, anchor="w").pack(side="left", padx=4)
            entry = ctk.CTkEntry(row, font=self.fonts.tiny, fg_color=ENTRY, border_color=BORDER, text_color=TEXT,
                                 placeholder_text="note (prints under the symbol)")
            entry.pack(side="left", fill="x", expand=True, padx=4)
            if note:
                entry.insert(0, note)
            entries.append((path, entry, note))
        btns = ctk.CTkFrame(dlg, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 12))

        def save() -> None:
            text = box.get("1.0", "end-1c")
            try:
                program = set_rung_comment(self.program, rung_id, text)
                changed = {path: e.get() for path, e, old in entries if (e.get() or "").strip() != (old or "").strip()}
                if changed:
                    program = set_instruction_notes(program, rung_id, changed)
            except KeyError:
                # Dialog is non-modal: the rung may have been deleted / replaced meanwhile.
                try:
                    dlg.destroy()
                except Exception:
                    pass
                self.status.configure(text=f"Rung {index} no longer exists — comment not saved.")
                self._mirror_status()
                return
            self.program = refresh_plc_text(program, self.project)
            self.program["text_edited"] = True
            self._selected_rung_id = rung_id
            try:
                dlg.destroy()
            except Exception:
                pass
            self._show_tab("ladder")
            self._commit(status=f"Updated rung {index} comment / notes")

        primary_button(btns, "Save", save, self.fonts.small, width=110).pack(side="right", padx=4)
        ghost_button(btns, "Cancel", dlg.destroy, self.fonts.small, width=90).pack(side="right", padx=4)
        try:
            dlg.after(60, lambda: (dlg.lift(), dlg.focus_force(), box.focus_set()))
        except Exception:
            pass

    def _add_series_contact(self) -> None:
        rungs = self.program.get("rungs") or []
        if not rungs:
            self.status.configure(text="Add a rung first, then add series contacts.")
            return
        rung_id = self._selected_rung_id or rungs[-1]["id"]
        contact = self.contact_var.get().strip()
        if not contact or contact.startswith("("):
            self.status.configure(text="Pick a contact tag from devices on this cabinet.")
            return
        target = next((r for r in rungs if r["id"] == rung_id), None)
        if target is None:
            self.status.configure(text="Selected rung not found.")
            return
        # v0.3.13 REG-2: build from elements when present (legacy series is empty
        # for compare/math/OTL/oneshot — appending only GUARD wiped the enable).
        self.program = append_series_contact(
            self.program,
            rung_id,
            contact,
            normally_closed=self.nc_var.get() == "NC",
        )
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = rung_id
        self._show_tab("ladder")
        self._commit(status=f"Added series contact {contact} on selected rung.")

    def _add_parallel_contact(self) -> None:
        """Add an OR-branch contact on the selected rung (viewer path for edit-matrix)."""
        rungs = self.program.get("rungs") or []
        if not rungs:
            self.status.configure(text="Add a rung first, then add a parallel contact.")
            return
        rung_id = self._selected_rung_id or rungs[-1]["id"]
        contact = self.contact_var.get().strip()
        if not contact or contact.startswith("("):
            self.status.configure(text="Pick a contact tag from devices on this cabinet.")
            return
        target = next((r for r in rungs if r["id"] == rung_id), None)
        if target is None:
            self.status.configure(text="Selected rung not found.")
            return
        self.program = append_parallel_contact(
            self.program,
            rung_id,
            contact,
            normally_closed=self.nc_var.get() == "NC",
        )
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = rung_id
        self._show_tab("ladder")
        self._commit(status=f"Added parallel contact {contact} on selected rung.")

    def _delete_selected_rung(self) -> None:
        rungs = self.program.get("rungs") or []
        if not rungs:
            self.status.configure(text="No rungs to delete.")
            return
        rung_id = self._selected_rung_id or rungs[-1]["id"]
        self.program = delete_rung(self.program, rung_id)
        self.program = refresh_plc_text(self.program, self.project)
        self.program["text_edited"] = True
        self._selected_rung_id = (self.program.get("rungs") or [{}])[-1].get("id") if self.program.get("rungs") else None
        self._show_tab("ladder")
        self._commit(status="Deleted rung.")

    def _wheel(self, event) -> None:
        self._note_manual_scroll()
        delta = -1 if getattr(event, "delta", 0) > 0 else 1
        # Windows often sends multiples of 120; step a bit faster for long ladders.
        steps = 1
        raw = abs(int(getattr(event, "delta", 0) or 0))
        if raw >= 120:
            steps = max(1, raw // 120)
        self.canvas.yview_scroll(delta * steps, "units")
        return "break"

    def _wheel_x(self, event) -> None:
        delta = -1 if getattr(event, "delta", 0) > 0 else 1
        self.canvas.xview_scroll(delta, "units")
        return "break"

    def _on_canvas_configure(self, _event=None) -> None:
        # Redraw on size change but keep the user's scroll position.
        self._draw_ladder(preserve_scroll=True)

    def _click_target_at(self, x: float, y: float) -> tuple[str, str] | None:
        for x0, y0, x1, y1, kind, tag in reversed(self._click_targets):
            if tag and tag != "?" and x0 <= x <= x1 and y0 <= y <= y1:
                return kind, tag
        return None

    def _on_canvas_right_click(self, event) -> None:
        """v0.3.20: right-click a part during simulation releases its force.
        v0.3.31: when not simulating, right-click an instruction to delete / replace / add next to it."""
        if not self._sim_session:
            target = self._instr_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
            if target is not None:
                self._instr_menu(target).tk_popup(event.x_root, event.y_root)
            return
        hit = self._click_target_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if hit is None:
            return
        sim = self._ensure_scan_sim()
        tag = hit[1]
        if tag not in sim.forces:
            self._sim_set_status(f"{tag} is not forced. Educational only - not a live PLC.")
            return
        sim.set_force(tag, None)
        self._sim_operator_changed(f"{tag} force released - the logic drives it again.")

    def _sim_operate_part(self, kind: str, tag: str) -> None:
        """v0.3.20: operator action on a ladder part while simulating."""
        if self._sim_blocked():
            return
        sim = self._ensure_scan_sim()
        base, member = split_member(tag)
        if kind in {"timer", "counter"}:
            if sim.reset_instruction(tag):
                self._sim_operator_changed(f"{tag} reset (ACC = 0).")
            return
        if kind == "contact" and member and (base in sim.timers or base in sim.counters):
            self._sim_set_status(f"{tag} is driven by {base} - click the {base} box to reset it.")
            return
        if tag in sim.numbers:
            self._sim_set_status(f"{tag} is a number, not an on/off bit.")
            return
        sim.toggle_force(tag)
        state = "ON" if sim.read(tag) else "OFF"
        if kind == "coil":
            msg = f"Coil {tag} forced {state} (overrides the logic) - right-click it to release."
        else:
            msg = f"{tag} switched {state} - right-click it to release the force."
        self._sim_operator_changed(msg)

    def _sim_operator_changed(self, msg: str) -> None:
        """Show an operator change at once. While running rung-by-rung (or paused),
        the logic follows when the rung runs; at full scan speed a scan runs now."""
        sim = self._ensure_scan_sim()
        if not self._sim_rung_mode() and not self._sim_running:
            self._sim_apply_scan_result(sim.scan_once(), mode="FORCE")
        else:
            self._sim_active_tags = set(sim.active_tags())
            self._sim_flash_on = True
            self._draw_ladder(preserve_scroll=True)
        self._refresh_force_strip()
        self._sim_set_status(msg + "  Educational only - not a live PLC.")
        self._explain_log([">> " + msg], "event")

    def _on_canvas_click(self, event) -> None:
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if self._sim_session:
            hit = self._click_target_at(x, y)
            if hit is not None:
                self._sim_operate_part(*hit)
                return
        target = self._instr_at(x, y)
        self._selected_instr = target
        for rung_id, x0, y0, x1, y1 in self._rung_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self._selected_rung_id = rung_id
                self._draw_ladder(preserve_scroll=True)
                if target is not None:
                    self.status.configure(text=f"Selected {target[2]} - Delete instr / Replace instr, or "
                                               "right-click it for more.")
                else:
                    self.status.configure(text=f"Selected rung {rung_id[:6]}...")
                return

    def export_ladder_artifact(self) -> None:
        """Write ladder-logic.txt/.html under saves/drawings/{slug}/ (separate from schematics)."""
        from cabinet_studio.services.drawings import default_drawings_folder
        from cabinet_studio.services.programming import write_ladder_logic

        self._flush_editor_to_program()
        self.project.program = program_to_dict(self.program)
        cabinet_path = getattr(self, "cabinet_path", None)
        if cabinet_path is None and getattr(self.master, "path", None):
            cabinet_path = self.master.path
        folder = default_drawings_folder(self.project, cabinet_path)
        try:
            written = write_ladder_logic(self.project, folder, program=self.program)
        except OSError as exc:
            self.status.configure(text=f"Could not export ladder: {exc}")
            return
        names = ", ".join(p.name for p in written)
        self.status.configure(text=f"Exported ladder artifact(s): {names} → {folder}")

    def print_ladder(self) -> None:
        """Open the system print dialog for a clean ladder page (HTML+SVG)."""
        self._flush_editor_to_program()
        rungs = list(self.program.get("rungs") or [])
        # v0.3.11: append subroutine rungs so they appear on the printout.
        routines = self.program.get("routines") if isinstance(self.program.get("routines"), dict) else {}
        for rname, rrungs in (routines or {}).items():
            if not isinstance(rrungs, list):
                continue
            rungs.append({
                "id": f"routine-{rname}",
                "comment": f"=== Subroutine {rname} ===",
                "elements": [{"kind": "sbr", "name": str(rname)}],
            })
            for rr in rrungs:
                if isinstance(rr, dict):
                    rungs.append(rr)
        title = html.escape(self.project.name or "Cabinet program")
        from cabinet_studio.services.ladder_print import ladder_program_to_svg_pages
        from cabinet_studio.services.ladder_templates import SAFETY_DESIGN_AID_NOTE as _SAFETY_AID_NOTE
        pages = ladder_program_to_svg_pages(
            rungs, width=1000, project_name=self.project.name or "Cabinet program"
        )
        from cabinet_studio.services.drawings import DISCLAIMER as _UL_AID
        sheets = []
        for pi, (svg_body, svg_w, svg_h) in enumerate(pages, start=1):
            # v0.3.13: SVG already carries UL + NFPA footer once — do not duplicate in HTML.
            sheets.append(
                f'<div class="sheet page">'
                f'<div class="titleblock">'
                f'<div><strong>Ladder Logic</strong> — {title}</div>'
                f'<div class="meta">Sheet {pi} of {len(pages)} · Educational design aid</div>'
                f'</div>'
                f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
                f'viewBox="0 0 {svg_w} {svg_h}" preserveAspectRatio="xMinYMin meet">'
                f'{svg_body}</svg>'
                f'</div>'
            )
        sheets_html = "\n".join(sheets)
        plc = self.program.get("plc_text") or format_plc_text(
            self.program.get("rungs") or [], cabinet_device_tags(self.project)
        )
        xref_html = format_cross_reference_html(self.program, cabinet_device_tags(self.project))
        _aid_footer = (
            f'<div class="footer">{html.escape(_UL_AID)} '
            f'{html.escape(_SAFETY_AID_NOTE)}</div>'
        )

        def _appendix_pages(title: str, body_chunks: list) -> str:
            """One .page div per chunk so continuation sheets get the UL footer (G-AID-2)."""
            parts = []
            for i, chunk in enumerate(body_chunks):
                if not str(chunk or "").strip():
                    continue
                heading = title if i == 0 else f"{title} (continued)"
                parts.append(
                    f'<div class="page"><h2>{html.escape(heading)}</h2>\n'
                    f"{chunk}{_aid_footer}</div>"
                )
            return "\n".join(parts)

        xref_block = ""
        if xref_html:
            import re as _re

            trs = _re.findall(r"<tr>.*?</tr>", xref_html, flags=_re.DOTALL)
            header_trs = [t for t in trs if "<th>" in t]
            data_trs = [t for t in trs if "<th>" not in t]
            from cabinet_studio.services.ladder_print import chunk_xref_rows as _chunk_xref

            chunks = []
            if not data_trs:
                chunks = [xref_html]
            else:
                # v0.3.15 N-4: weight rows by wrapped cell length so a sheet never overflows.
                for grp in _chunk_xref(data_trs):
                    chunks.append(
                        '<table class="xref"><thead>'
                        + "".join(header_trs)
                        + "</thead><tbody>"
                        + "".join(grp)
                        + "</tbody></table>"
                    )
            xref_block = _appendix_pages("Tag cross-reference", chunks)

        # v0.3.15 N-4: paginate by visual rows (hard-wrapped at a printable column
        # budget) so no chunk overflows onto a footer-less physical page. The UL
        # line is dropped from the printed body because each page footer carries
        # it — exactly once per printed page.
        from cabinet_studio.services.ladder_print import paginate_plain_text as _paginate

        plc_chunks = [
            "<pre>" + html.escape("\n".join(rows)) + "</pre>"
            # v0.3.16 (P3): the NFPA/ISO note is in every page footer too — drop the body copy.
            for rows in _paginate(plc, drop_lines=(_UL_AID, _SAFETY_AID_NOTE))
        ]
        plc_block = _appendix_pages("PLC text", plc_chunks)

        doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>Ladder - {title}</title>
<style>
  @page {{ size: letter; margin: 0.5in; }}
  body {{ font-family: Segoe UI, Arial, sans-serif; color: #111; background: #fff; margin: 0; }}
  h1 {{ font-size: 14pt; margin: 0 0 4px 0; }}
  .meta {{ color: #444; font-size: 9pt; margin-bottom: 6px; }}
  .titleblock {{ border-bottom: 1px solid #888; padding-bottom: 4px; margin-bottom: 6px; }}
  .footer {{ font-size: 8pt; color: #555; margin-top: 6px; border-top: 1px solid #aaa; padding-top: 4px; }}
  .sheet {{ background: #d8d4cc; padding: 6px; border: 1px solid #888; overflow: visible; }}
  .page {{ page-break-after: always; margin-bottom: 8px; break-inside: avoid; }}
  .page:last-child {{ page-break-after: auto; }}
  svg {{ display: block; max-width: 100%; height: auto; }}
  pre {{ font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 9pt; white-space: pre-wrap;
         line-height: 1.2;
         border-top: 1px solid #ccc; padding-top: 12px; margin-top: 16px; }}
  h2 {{ font-size: 12pt; margin: 18px 0 6px 0; }}
  table.xref {{ border-collapse: collapse; font-size: 8.5pt; width: 100%; }}
  table.xref th, table.xref td {{ border: 1px solid #999; padding: 2px 6px; text-align: left; vertical-align: top; }}
  table.xref th {{ background: #eee; }}
  @media print {{
    .noprint {{ display: none; }}
    body {{ margin: 0; }}
    .sheet {{ border: none; }}
  }}
</style></head><body>
<p class="noprint"><button onclick="window.print()">Print…</button>
  <button onclick="window.close()">Close</button></p>
{sheets_html}
{xref_block}
{plc_block}
<script>
window.addEventListener("load", function () {{
  setTimeout(function () {{ window.print(); }}, 250);
}});
</script>
</body></html>
"""
        tmp = _Path(tempfile.gettempdir()) / "cabinet_studio_ladder_print.html"
        tmp.write_text(doc, encoding="utf-8")
        opened = False
        try:
            # Windows: prefer default browser / associated app.
            os.startfile(str(tmp))  # type: ignore[attr-defined]
            opened = True
        except Exception:
            opened = webbrowser.open(tmp.as_uri())
        if opened:
            self.status.configure(text="Print dialog opened for ladder page.")
        else:
            self.status.configure(text=f"Could not open print page. Saved at {tmp}")

    def _ladder_svg(self, rungs: list) -> tuple[str, int, int]:
        """Build a print-oriented SVG (nested-OR-aware via ladder_print)."""
        from cabinet_studio.services.ladder_print import ladder_program_to_svg

        return ladder_program_to_svg(list(rungs or []), width=1000)

    def _svg_rung(self, rung: dict, index: int, left: float, right: float, y: float) -> list[str]:
        parallel = list(rung.get("parallel") or [])
        series = list(rung.get("series") or [])
        coil = (rung.get("coil_tag") or "").strip()
        coil_neg = bool(rung.get("coil_negated"))
        comment = (rung.get("comment") or "").strip()
        block_h = self._rung_block_height(rung)
        out: list[str] = [
            f'<line x1="{left}" y1="{y}" x2="{left}" y2="{y + block_h}" '
            f'stroke="{LADDER_RAIL}" stroke-width="4"/>',
            f'<line x1="{right}" y1="{y}" x2="{right}" y2="{y + block_h}" '
            f'stroke="{LADDER_RAIL}" stroke-width="4"/>',
        ]
        title = f"Rung {index}"
        if comment:
            title = f"Rung {index}: {comment[:90]}"
        out.append(
            f'<text x="{left + 10}" y="{y + 16}" fill="{LADDER_MUTED}" font-size="11" '
            f'font-family="Segoe UI, Arial">{html.escape(title)}</text>'
        )
        n_series = len(series)
        n_par = max((len(b) for b in parallel), default=0) if parallel else 0
        col_w = CONTACT_COL_W if n_par >= 2 else max(CONTACT_COL_W - 6, 130)
        series_w = max(
            MIN_SERIES_W,
            int((right - left - 220 - COIL_INSET - _rung_fb_space(rung)) // max(1, n_series + 1)),
        )
        par_zone_right = left + max(180, 24 + n_par * col_w + 40)
        series_start = par_zone_right + SERIES_AFTER_PARALLEL
        coil_x = right - COIL_INSET

        if parallel:
            count = len(parallel)
            start_y = y + TITLE_BAND + BRANCH_ROW_H / 2
            branch_ys = [start_y + bi * BRANCH_ROW_H for bi in range(count)]
            for bi, branch in enumerate(parallel):
                by = branch_ys[bi]
                out.append(
                    f'<line x1="{left}" y1="{by}" x2="{left + 24}" y2="{by}" '
                    f'stroke="{LADDER_WIRE}" stroke-width="2"/>'
                )
                cx = left + 80
                for contact in branch:
                    out.extend(self._svg_contact(cx, by, contact))
                    cx += col_w
                out.append(
                    f'<line x1="{cx - col_w + CONTACT_GAP / 2 + 2}" y1="{by}" '
                    f'x2="{par_zone_right}" y2="{by}" stroke="{LADDER_WIRE}" stroke-width="2"/>'
                )
            if len(branch_ys) > 1:
                out.append(
                    f'<line x1="{par_zone_right}" y1="{branch_ys[0]}" '
                    f'x2="{par_zone_right}" y2="{branch_ys[-1]}" '
                    f'stroke="{LADDER_WIRE}" stroke-width="2"/>'
                )
                bus_y = (branch_ys[0] + branch_ys[-1]) / 2
            else:
                bus_y = branch_ys[0]
            out.append(
                f'<line x1="{par_zone_right}" y1="{bus_y}" x2="{series_start - 10}" y2="{bus_y}" '
                f'stroke="{LADDER_WIRE}" stroke-width="2"/>'
            )
        else:
            bus_y = y + TITLE_BAND + BRANCH_ROW_H / 2
            out.append(
                f'<line x1="{left}" y1="{bus_y}" x2="{series_start - 10}" y2="{bus_y}" '
                f'stroke="{LADDER_WIRE}" stroke-width="2"/>'
            )

        x = series_start
        for contact in series:
            out.append(
                f'<line x1="{x - 10}" y1="{bus_y}" x2="{x - CONTACT_GAP / 2 - 2}" y2="{bus_y}" '
                f'stroke="{LADDER_WIRE}" stroke-width="2"/>'
            )
            out.extend(self._svg_contact(x, bus_y, contact))
            x += series_w

        if series:
            wire_from = x - series_w + CONTACT_GAP / 2 + 2
        elif parallel:
            wire_from = par_zone_right
        else:
            wire_from = left
        def _wire(x1: float, x2: float) -> str:
            return (
                f'<line x1="{x1}" y1="{bus_y}" x2="{x2}" y2="{bus_y}" '
                f'stroke="{LADDER_WIRE}" stroke-width="2"/>'
            )

        boxes, coil_slot = _actuator_layout(rung, right)
        cursor = wire_from
        for kind, data, cx, bw in boxes:
            out.append(_wire(cursor, cx - bw / 2))
            if kind == "timer":
                out.extend(self._svg_timer(cx, bus_y, data))
            else:
                out.extend(self._svg_counter(cx, bus_y, data))
            cursor = cx + bw / 2
        if coil_slot is not None:
            out.append(_wire(cursor, coil_slot - COIL_RADIUS))
            out.extend(self._svg_coil(coil_slot, bus_y, coil, coil_neg))
            out.append(_wire(coil_slot + COIL_RADIUS, right))
        else:
            out.append(_wire(cursor, right))
        if rung_has_seal_in(rung):
            out.append(
                f'<text x="{right - SEAL_IN_GAP}" y="{y + 16}" text-anchor="end" fill="{LADDER_COIL}" '
                f'font-size="10" font-weight="bold" font-family="Segoe UI, Arial">seal-in</text>'
            )
        return out

    def _svg_contact(self, x: float, y: float, contact: dict) -> list[str]:
        tag = (contact.get("tag") or "").strip()
        nc = bool(contact.get("normally_closed"))
        h = CONTACT_HALF_H
        gap = CONTACT_GAP
        out = [
            f'<line x1="{x - gap / 2}" y1="{y - h}" x2="{x - gap / 2}" y2="{y + h}" '
            f'stroke="{LADDER_SYMBOL}" stroke-width="3"/>',
            f'<line x1="{x + gap / 2}" y1="{y - h}" x2="{x + gap / 2}" y2="{y + h}" '
            f'stroke="{LADDER_SYMBOL}" stroke-width="3"/>',
        ]
        if nc:
            out.append(
                f'<line x1="{x - gap / 2 - 2}" y1="{y + h - 2}" x2="{x + gap / 2 + 2}" '
                f'y2="{y - h + 2}" stroke="{LADDER_SYMBOL}" stroke-width="2"/>'
            )
        tip = device_hover_detail(
            self._device_map.get(tag), tag, kind="contact", normally_closed=nc
        )
        out.insert(0, f"<g><title>{html.escape(tip)}</title>")
        out.append(
            f'<text x="{x}" y="{y - h - TAG_CLEAR_ABOVE + 10}" text-anchor="middle" '
            f'fill="{LADDER_LABEL}" font-size="11" font-weight="bold" '
            f'font-family="Consolas, monospace">{html.escape(tag or "?")}</text>'
        )
        out.append("</g>")
        return out

    def _svg_timer(self, x: float, y: float, timer: dict) -> list[str]:
        tag = html.escape((timer.get("tag") or "").strip() or "?")
        block = html.escape(str(timer.get("block") or "TON").upper())
        pt_ms = int(timer.get("pt_ms") or 0)
        w, h = TIMER_BOX_W, TIMER_BOX_H
        return [
            f"<g><title>Timer {block} {tag} PT={pt_ms}ms (educational)</title>",
            f'<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" fill="{LADDER_BG}" '
            f'stroke="{LADDER_TIMER}" stroke-width="2"/>',
            f'<text x="{x}" y="{y - h / 2 - 6}" text-anchor="middle" fill="{LADDER_TIMER}" '
            f'font-size="11" font-weight="bold" font-family="Consolas, monospace">{tag}</text>',
            f'<text x="{x}" y="{y - 4}" text-anchor="middle" fill="{LADDER_LABEL}" font-size="12" '
            f'font-weight="bold" font-family="Segoe UI, Arial">{block}</text>',
            f'<text x="{x}" y="{y + 14}" text-anchor="middle" fill="{LADDER_MUTED}" font-size="10" '
            f'font-family="Segoe UI, Arial">PT {pt_ms}ms</text>',
            "</g>",
        ]

    def _svg_counter(self, x: float, y: float, counter: dict) -> list[str]:
        tag = html.escape((counter.get("tag") or "").strip() or "?")
        block = html.escape(str(counter.get("block") or "CTU").upper())
        pv = int(counter.get("pv") or 0)
        if block in {"RES", "LOAD"}:
            w, h = COUNTER_OUT_W, COUNTER_OUT_H
            what = "ACC:=0" if block == "RES" else "ACC:=PRE"
            return [
                f"<g><title>Counter {block} {tag} ({what}, educational)</title>",
                f'<ellipse cx="{x}" cy="{y}" rx="{w / 2}" ry="{h / 2}" fill="{LADDER_BG}" '
                f'stroke="{LADDER_COUNTER}" stroke-width="2"/>',
                f'<text x="{x}" y="{y - h / 2 - 8}" text-anchor="middle" fill="{LADDER_COUNTER}" '
                f'font-size="11" font-weight="bold" font-family="Consolas, monospace">{tag}</text>',
                f'<text x="{x}" y="{y + 4}" text-anchor="middle" fill="{LADDER_LABEL}" font-size="12" '
                f'font-weight="bold" font-family="Segoe UI, Arial">{block}</text>',
                "</g>",
            ]
        w, h = COUNTER_BOX_W, COUNTER_BOX_H
        done = "ACC&gt;=PRE" if block == "CTU" else "ACC&lt;=0"
        return [
            f"<g><title>Counter {block} {tag} PRE={pv} DN when {done} (educational)</title>",
            f'<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" fill="{LADDER_BG}" '
            f'stroke="{LADDER_COUNTER}" stroke-width="2"/>',
            f'<text x="{x}" y="{y - h / 2 - 6}" text-anchor="middle" fill="{LADDER_COUNTER}" '
            f'font-size="11" font-weight="bold" font-family="Consolas, monospace">{tag}</text>',
            f'<text x="{x}" y="{y - 6}" text-anchor="middle" fill="{LADDER_LABEL}" font-size="12" '
            f'font-weight="bold" font-family="Segoe UI, Arial">{block}</text>',
            f'<text x="{x}" y="{y + 10}" text-anchor="middle" fill="{LADDER_MUTED}" font-size="10" '
            f'font-family="Segoe UI, Arial">PRE {pv}</text>',
            f'<text x="{x}" y="{y + 23}" text-anchor="middle" fill="{LADDER_MUTED}" font-size="9" '
            f'font-family="Segoe UI, Arial">DN: {done}</text>',
            "</g>",
        ]

    def _svg_coil(self, x: float, y: float, tag: str, negated: bool = False) -> list[str]:
        r = COIL_RADIUS
        out = [
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="{LADDER_BG}" stroke="{LADDER_COIL}" '
            f'stroke-width="3"/>'
        ]
        if negated:
            out.append(
                f'<line x1="{x - r + 3}" y1="{y + r - 3}" x2="{x + r - 3}" y2="{y - r + 3}" '
                f'stroke="{LADDER_COIL}" stroke-width="2"/>'
            )
        tip = device_hover_detail(self._device_map.get(tag), tag, kind="coil")
        out.insert(0, f"<g><title>{html.escape(tip)}</title>")
        out.append(
            f'<text x="{x}" y="{y - r - TAG_CLEAR_ABOVE + 10}" text-anchor="middle" '
            f'fill="{LADDER_COIL}" font-size="11" font-weight="bold" '
            f'font-family="Consolas, monospace">{html.escape(tag or "?")}</text>'
        )
        out.append("</g>")
        return out

    # --- Visual ladder -----------------------------------------------------

    def _draw_ladder(self, preserve_scroll: bool = False) -> None:
        if not hasattr(self, "canvas"):
            return
        y_frac = self.canvas.yview()[0] if preserve_scroll else 0.0
        x_frac = self.canvas.xview()[0] if preserve_scroll else 0.0
        self.canvas.delete("all")
        self._hide_hover_tip()
        self._rung_hitboxes = []
        self._hover_targets = []
        self._click_targets = []
        self._terminals = []
        self._rails = []
        self._bodies = []
        self._wire_segments = []
        self._timer_live = {}
        rungs = self.program.get("rungs") or []
        width = max(int(self.canvas.winfo_width()), 900)
        # content_w grows with the widest rung so parts are never crushed (horizontal scroll).
        need = RAIL_INSET * 2 + max((self._rung_needed_w(r) for r in rungs), default=0)
        content_w = max(width, 900, int(need))
        left = RAIL_INSET
        right = content_w - RAIL_INSET
        top = 36
        self.canvas.create_text(
            left,
            14,
            anchor="w",
            fill=LADDER_MUTED,
            font=(self.fonts.ui_family, 10),
            text="Ladder view  |  [ ] NO   [/] NC   ( ) coil   [TON] timer   [CTU] counter   [ONS/OSR/OSF] one-shot  |  Simulate: green = power flow / TRUE, red F = forced  |  Ctrl+Z / Ctrl+Y undo/redo  |  hover for details",
        )
        if not rungs:
            self.canvas.create_text(
                content_w // 2,
                120,
                fill=LADDER_LABEL,
                font=(self.fonts.ui_family, 16, "bold"),
                text="No rungs yet — answer the questions or click Build starter program",
            )
            self.canvas.create_text(
                content_w // 2,
                156,
                fill=LADDER_MUTED,
                font=(self.fonts.ui_family, 12),
                text="Use Build starter program / Build from drawings above (cabinet tags only), or Add rung.",
            )
            self.canvas.configure(scrollregion=(0, 0, content_w, 260))
            return

        y = top
        for index, rung in enumerate(rungs, start=1):
            block_h = self._rung_block_height(rung)
            selected = rung.get("id") == self._selected_rung_id
            highlighted = rung.get("id") == self._highlight_rung_id
            if self._sim_session and rung.get("id") == self._sim_cursor_rung_id:
                self.canvas.create_rectangle(
                    left - 26, y - 14, right + 26, y + block_h + 14,
                    outline=_SIM_CURSOR_OUTLINE, width=4, fill="" if (selected or highlighted) else _SIM_CURSOR_FILL,
                )
                self.canvas.create_text(
                    left - 22, y - 14, anchor="sw", fill=_SIM_CURSOR_OUTLINE,
                    font=(self.fonts.ui_family, 9, "bold"), text="▶ executing",
                )
            if selected or highlighted:
                self.canvas.create_rectangle(
                    left - 18,
                    y - 10,
                    right + 18,
                    y + block_h + 10,
                    outline="#e6b800" if highlighted and not selected else LADDER_SELECT,
                    width=3 if highlighted else 2,
                    fill="#fff3bf" if highlighted else "#cfd8f0",
                )
            self._draw_rung(rung, index, left, right, y)
            self._rung_hitboxes.append((rung["id"], left - 18, y - 10, right + 18, y + block_h + 10))
            y += block_h + INTER_RUNG_GAP

        self.canvas.configure(scrollregion=(0, 0, content_w, y + 48))
        if preserve_scroll:
            self.canvas.yview_moveto(y_frac)
            self.canvas.xview_moveto(x_frac)
        if self._alive(self.properties):
            self.properties.sync()

    def _rung_block_height(self, rung: dict) -> float:
        branches = _series_rows(self._rung_draw_elements(rung))
        # Title band (+ extra comment lines) + one full row per OR branch + caption clearance.
        return TITLE_BAND + comment_extra_height(rung.get("comment") or "") + branches * BRANCH_ROW_H + BOTTOM_PAD

    # --- v0.3.6 drawing helpers (comments, notes, live power flow) ---------

    def _draw_rung_title(self, rung: dict, index: int, left: float, right: float, y: float) -> float:
        """Rung title (first comment line) + extra comment lines; returns extra band px."""
        lines = comment_lines(rung.get("comment") or "")
        title = f"Rung {index}" + (f": {lines[0]}" if lines else "")
        self.canvas.create_text(
            left + 10, y + 14, anchor="w", fill=LADDER_MUTED,
            font=(self.fonts.ui_family, 10, "bold" if lines else "normal"), text=title,
        )
        for li, line in enumerate(lines[1:], start=1):
            self.canvas.create_text(
                left + 22, y + 14 + li * COMMENT_LINE_PX, anchor="w", fill=LADDER_NOTE,
                font=(self.fonts.ui_family, 9, "italic"), text=line,
            )
        rid = str(rung.get("id") or index)
        if self._sim_flow and rid in self._sim_energized:
            on = bool(self._sim_energized.get(rid))
            self.canvas.create_text(
                right - SEAL_IN_GAP - 70, y + 14, anchor="e",
                fill=LADDER_POWER if on else LADDER_MUTED,
                font=(self.fonts.ui_family, 9, "bold"),
                text="● energized" if on else "○ not energized",
            )
        return comment_extra_height(rung.get("comment") or "")

    def _flow(self, key: str | None) -> dict | None:
        if not key or not self._sim_flow:
            return None
        return self._sim_flow.get(key)

    def _wire(self, x1: float, y1: float, x2: float, y2: float, live: bool | None = None) -> None:
        """Rung wire; thick green when sim power flows through it."""
        if x1 == x2 and y1 == y2:
            return
        segments = self.__dict__.get("_wire_segments")
        if segments is not None:
            segments.append((x1, y1, x2, y2))
        if live and self._sim_flow:
            self.canvas.create_line(x1, y1, x2, y2, fill=LADDER_POWER, width=4)
        else:
            self.canvas.create_line(x1, y1, x2, y2, fill=LADDER_WIRE, width=2)

    def _draw_note(self, x: float, y: float, note: str) -> None:
        note = (note or "").strip()
        if not note:
            return
        short = note if len(note) <= 24 else note[:23] + "…"
        self.canvas.create_text(x, y, fill=LADDER_NOTE, font=(self.fonts.ui_family, 8, "italic"), text=short)

    def _forced_marker(self, x: float, y: float, tag: str) -> None:
        sim = self._scan_sim
        if sim is None or not tag or tag not in getattr(sim, "forces", {}):
            return
        val = "1" if sim.forces.get(tag) else "0"
        self.canvas.create_rectangle(x - 1, y - 9, x + 21, y + 7, fill=LADDER_FORCE, outline=LADDER_FORCE)
        self.canvas.create_text(x + 10, y - 1, fill="#ffffff", font=(self.fonts.ui_family, 8, "bold"), text=f"F{val}")


    def _draw_subroutine_box(self, cx: float, cy: float, el: dict, *, flow_key: str = "", rung_comment: str = "") -> None:
        """Educational JSR / SBR / RET box (CCW/Studio subroutine ideas)."""
        kind = str(el.get("kind") or "").lower()
        if kind == "jsr":
            label, sub = "JSR", str(el.get("target") or "")
            w, h = 100, 48
        elif kind == "sbr":
            label, sub = "SBR", str(el.get("name") or "")
            w, h = 100, 40
        else:
            label, sub = "RET", ""
            w, h = 64, 40
        flow = self._flow(flow_key) if flow_key else None
        live = bool(flow and flow.get("out"))
        color = LADDER_POWER if live else "#1a4a6e"
        dash = (4, 3) if kind == "sbr" else ()
        self.canvas.create_rectangle(
            cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2,
            outline=color, width=2, fill="#e8eef5", dash=dash,
        )
        self.canvas.create_text(cx, cy - (8 if sub else 0), fill=color, font=(self.fonts.ui_family, 11, "bold"), text=label)
        if sub:
            self.canvas.create_text(cx, cy + 10, fill=LADDER_LABEL, font=(self.fonts.ui_family, 10), text=sub)
        tip = f"{label} {sub}".strip() + (f" — {rung_comment}" if rung_comment else "")
        self.canvas.create_rectangle(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, outline="", fill="", tags=("tip",))
        # hover via existing tip system if any — status on click is enough

    def _draw_oneshot(self, x: float, y: float, el: dict, *, flow_key: str | None = None, rung_comment: str = "") -> float:
        """ONS (input-style box) / OSR / OSF (output-style box). Returns box width."""
        block = str(el.get("block") or "ONS").upper()
        storage = str(el.get("var") or "?").strip()
        output = str(el.get("output") or "").strip()
        flow = self._flow(flow_key)
        pulsing = bool(flow and flow.get("out")) if block == "ONS" else bool(
            self._scan_sim is not None and output and self._scan_sim.read(output)
        )
        powered = bool(flow and flow.get("in"))
        outline = LADDER_PULSE if pulsing else (LADDER_POWER if powered else LADDER_ONESHOT)
        fill = LADDER_ACTIVE_FILL if pulsing else (LADDER_TRUE_FILL if powered else self._lbg)
        w, h = (76, 44) if block == "ONS" else (100, 56)
        self.canvas.create_rectangle(x - w / 2, y - h / 2, x + w / 2, y + h / 2, outline=outline, width=3 if (pulsing or powered) else 2, fill=fill)
        if block == "ONS":
            self.canvas.create_text(x, y - h / 2 - 10, fill=outline, font=(self.fonts.mono_family, 9, "bold"), text=storage)
            self.canvas.create_text(x, y, fill=LADDER_LABEL, font=(self.fonts.ui_family, 11, "bold"), text="ONS")
            what = "Passes power for ONE scan when the rung goes false→true."
        else:
            edge = "rising" if block == "OSR" else "falling"
            self.canvas.create_text(x, y - h / 2 - 10, fill=outline, font=(self.fonts.mono_family, 9, "bold"), text=f"{block} ({edge})")
            self.canvas.create_text(x, y - 8, fill=LADDER_LABEL, font=(self.fonts.ui_family, 9, "bold"), text=f"S {storage}")
            self.canvas.create_text(x, y + 10, fill=LADDER_MUTED, font=(self.fonts.ui_family, 9), text=f"O {output or '?'}")
            what = f"Output bit {output or '?'} is TRUE for ONE scan on a {edge} rung edge; power passes through."
        tip = (
            f"One-shot {block}  storage bit {storage}"
            + (f"  output {output}" if output else "")
            + f"\n{what}\nUse a unique storage bit per one-shot. Educational scan — not a live PLC."
        )
        if el.get("desc"):
            tip += f"\nNote: {el.get('desc')}"
        if rung_comment:
            tip += f"\nRung: {rung_comment.splitlines()[0]}"
        self._hover_targets.append((x - w / 2 - 6, y - h / 2 - 6, x + w / 2 + 6, y + h / 2 + 6, tip))
        return float(w)


    # --- v0.3.24: one layout engine for every rung ------------------------------
    # Each instruction owns a slot [x, x + w]. It draws its own lead-in wire from
    # the slot's left edge to its left terminal and its lead-out wire from its
    # right terminal to the slot's right edge, and slots abut, so every wire meets
    # the next part. OR branches hang below the row they start on; outputs sit
    # against the right rail (Studio 5000 / CCW style).

    def _rung_draw_elements(self, rung: dict) -> list:
        """The rung as the scan sees it, so the drawing and power-flow keys agree."""
        if isinstance(rung.get("elements"), list) and rung.get("elements"):
            return list(rung["elements"])
        els = [dict(e) for e in program_rung_to_elements(rung)]
        for el in els:
            kind = str(el.get("kind") or "").lower()
            src = rung.get(kind) if kind in {"timer", "counter"} and isinstance(rung.get(kind), dict) else None
            if src:
                for k in ("pt_tag", "pv_tag", "desc"):
                    if src.get(k) and not el.get(k):
                        el[k] = src[k]
        return els

    def _tag_text_w(self, text: str) -> int:
        font = self.__dict__.get("_ladder_tag_font")
        if font is None:
            try:
                font = tkfont.Font(root=self, family=self.fonts.mono_family, size=10, weight="bold")
            except Exception:
                return 9 * len(text or "?")
            self.__dict__["_ladder_tag_font"] = font
        return int(font.measure(text or "?"))

    def _slot(self, el: dict) -> tuple[float, float]:
        """(slot width, half width of the drawn body) for one non-OR instruction."""
        kind = _el_kind(el)
        label = str(el.get("var") or "")
        if kind == "contact":
            half = CONTACT_GAP / 2
        elif kind == "coil":
            half = COIL_RADIUS
        elif kind == "timer":
            half = TIMER_BOX_W / 2
        elif kind == "counter":
            blk = str(el.get("block") or "CTU").upper()
            half = (COUNTER_OUT_W if blk in {"RES", "LOAD"} else COUNTER_BOX_W) / 2
        elif kind == "compare":
            half, label = 50, ""
        elif kind == "math":
            half, label = 55, str(el.get("dest") or "")
        elif kind in {"oneshot", "oneshot_out"}:
            blk = str(el.get("block") or "ONS").upper()
            half = 38 if blk == "ONS" else 50
            label = label if blk == "ONS" else f"{blk} (falling)"
        elif kind == "ret":
            half, label = 32, ""
        else:  # jsr / sbr / anything the drawer has no symbol for
            half, label = 50, ""
        note = str(el.get("desc") or "").strip()
        note_w = 6 * min(len(note), 24) + 12 if note else 0
        width = max(2 * half + 2 * SLOT_LEAD, self._tag_text_w(label) + 2 * SLOT_PAD if label else 0, note_w)
        return float(width), float(half)

    def _series_w(self, items: list) -> float:
        total = 0.0
        for el in items or []:
            if not isinstance(el, dict):
                continue
            total += self._or_w(el) if _el_kind(el) == "or" else self._slot(el)[0]
        return total

    def _or_w(self, el: dict) -> float:
        return 2 * OR_PAD + max([self._series_w(b) for b in _or_branches(el)] or [0.0])

    def _rung_needed_w(self, rung: dict) -> float:
        els = self._rung_draw_elements(rung)
        extra = 0.0 if any(_el_kind(e) in _OUTPUT_KINDS for e in els if isinstance(e, dict)) else 2 * COIL_RADIUS + 2 * SLOT_LEAD
        return self._series_w(els) + extra + 60

    def _draw_series(self, items: list, x: float, y: float, key_of, comment: str) -> float:
        for j, el in enumerate(items or []):
            if not isinstance(el, dict):
                continue
            if _el_kind(el) == "or":
                x = self._draw_or_group(el, x, y, key_of(j), comment)
            else:
                x = self._draw_slot(el, x, y, key_of(j), comment)
        return x

    def _draw_slot(self, el: dict, x: float, y: float, key: str, comment: str) -> float:
        w, half = self._slot(el)
        cx = x + w / 2
        flow = self._flow(key)
        self._wire(x, y, cx - half, y, live=bool(flow and flow.get("in")))
        self._wire(cx + half, y, x + w, y, live=bool(flow and flow.get("out")))
        self._terminals.append((cx - half, y))
        self._terminals.append((cx + half, y))
        self._bodies.append((cx - half, cx + half, y))
        self._draw_instruction(el, cx, y, key, comment)
        if key and key == self.__dict__.get("_sim_part_key"):
            h = TIMER_BOX_H / 2 + 6 if _el_kind(el) in {"timer", "counter"} else 32
            self.canvas.create_rectangle(cx - half - 6, y - h, cx + half + 6, y + h,
                                         outline=_PART_HILITE, width=3, dash=(6, 3))
        return x + w

    def _draw_or_group(self, el: dict, x: float, y: float, key: str, comment: str) -> float:
        branches = _or_branches(el) or [[]]
        x_join = x + self._or_w(el)
        flow = self._flow(key)
        pin = bool(flow and flow.get("in"))
        ys: list[float] = []
        lives: list[bool] = []
        by = y
        for bi, branch in enumerate(branches):
            ys.append(by)
            self._wire(x, by, x + OR_PAD, by, live=pin)
            end = self._draw_series(branch, x + OR_PAD, by, lambda j, bi=bi: f"{key}|b{bi}|{j}", comment)
            last = max((j for j, e in enumerate(branch) if isinstance(e, dict)), default=None)
            if last is None:
                live = pin
            else:
                lf = self._flow(f"{key}|b{bi}|{last}")
                live = bool(lf and lf.get("out"))
            self._wire(end, by, x_join, by, live=live)
            lives.append(live)
            by += _series_rows(branch) * BRANCH_ROW_H
        if len(ys) > 1:
            self._wire(x, ys[0], x, ys[-1], live=pin)
            for k in range(len(ys) - 1):
                # Power climbs the join bar from any live branch below this segment.
                self._wire(x_join, ys[k], x_join, ys[k + 1], live=any(lives[k + 1:]))
        return x_join

    def _draw_instruction(self, el: dict, cx: float, y: float, key: str, comment: str) -> None:
        kind = _el_kind(el)
        note = str(el.get("desc") or "")
        if kind == "contact":
            contact = {"tag": el.get("var") or "", "normally_closed": str(el.get("form", "NO")).upper() == "NC"}
            self._draw_contact(cx, y, contact, rung_comment=comment, flow_key=key, note=note)
        elif kind == "coil":
            tag = (el.get("var") or "").strip()
            form = str(el.get("form") or "").lower()
            self._draw_coil(cx, y, tag, form in {"negated", "not", "nc"}, rung_comment=comment, flow_key=key, note=note)
            letter = "S" if form in {"set", "s"} else ("R" if form in {"reset", "r"} else "")
            if letter:
                self.canvas.create_text(cx, y, fill=LADDER_COIL, font=(self.fonts.ui_family, 11, "bold"), text=letter)
        elif kind == "compare":
            self._draw_compare_box(cx, y, el, rung_comment=comment, flow_key=key)
            self._draw_note(cx, y + 28 + 22, note)
        elif kind == "math":
            self._draw_math_box(cx, y, el, rung_comment=comment, flow_key=key)
            self._draw_note(cx, y + 32 + 22, note)
        elif kind in {"oneshot", "oneshot_out"}:
            w = self._draw_oneshot(cx, y, el, flow_key=key, rung_comment=comment)
            self._draw_note(cx, y + (22 if w <= 76 else 28) + 14, note)
        elif kind == "timer":
            data = {"tag": el.get("var") or "", "block": el.get("block") or "TON",
                    "pt_ms": el.get("pt_ms") or 0, "pt_tag": el.get("pt_tag") or ""}
            self._draw_timer(cx, y, data, rung_comment=comment, flow_key=key)
            self._draw_note(cx, y + TIMER_BOX_H / 2 + 14, note)
        elif kind == "counter":
            data = {"tag": el.get("var") or "", "block": el.get("block") or "CTU",
                    "pv": el.get("pv") or 0, "pv_tag": el.get("pv_tag") or ""}
            self._draw_counter(cx, y, data, rung_comment=comment, flow_key=key)
            self._draw_note(cx, y + COUNTER_BOX_H / 2 + 14, note)
        elif kind in {"jsr", "sbr", "ret"}:
            self._draw_subroutine_box(cx, y, el, flow_key=key, rung_comment=comment)
            self._draw_note(cx, y + 24 + 14, note)
        else:
            flow = self._flow(key)
            live = bool(flow and flow.get("out"))
            self.canvas.create_rectangle(cx - 50, y - 22, cx + 50, y + 22, outline=LADDER_POWER if live else LADDER_MUTED,
                                         width=2, fill=self._lbg, dash=(4, 3))
            self.canvas.create_text(cx, y, fill=LADDER_LABEL, font=(self.fonts.ui_family, 10, "bold"),
                                    text=(kind or "?").upper()[:10])
            self._hover_targets.append((cx - 56, y - 28, cx + 56, y + 28,
                                        f"{(kind or '?').upper()} - passes power through (no symbol for this instruction yet)."))

    def _draw_rung(self, rung: dict, index: int, left: float, right: float, y: float) -> None:
        elements = self._rung_draw_elements(rung)
        comment = (rung.get("comment") or "").strip()
        rid = str(rung.get("id") or index)
        block_h = self._rung_block_height(rung)
        self.canvas.create_line(left, y, left, y + block_h, fill=LADDER_RAIL, width=4)
        self.canvas.create_line(right, y, right, y + block_h, fill=LADDER_RAIL, width=4)
        self._rails.append((left, y, y + block_h))
        self._rails.append((right, y, y + block_h))
        extra = self._draw_rung_title(rung, index, left, right, y)
        bus_y = y + TITLE_BAND + extra + BRANCH_ROW_H / 2
        sim_on = bool(self._sim_flow)

        def key_of(j: int) -> str:
            return f"{rid}|L|{j}"

        def out_of(j: int | None, default: bool) -> bool:
            if j is None:
                return default
            f = self._flow(key_of(j))
            return bool(f and f.get("out"))

        split = len(elements)
        while split > 0 and isinstance(elements[split - 1], dict) and _el_kind(elements[split - 1]) in _OUTPUT_KINDS:
            split -= 1
        inputs, outputs = elements[:split], elements[split:]
        last_in = max((j for j, e in enumerate(inputs) if isinstance(e, dict)), default=None)
        x = self._draw_series(inputs, left, bus_y, key_of, comment)
        in_live = out_of(last_in, sim_on)
        if outputs:
            ox = max(x, right - self._series_w(outputs))
            self._wire(x, bus_y, ox, bus_y, live=in_live)
            end = self._draw_series(outputs, ox, bus_y, lambda j: key_of(split + j), comment)
            if end < right:
                self._wire(end, bus_y, right, bus_y, live=out_of(len(elements) - 1, False))
        elif any(_el_kind(e) in _OUTPUT_KINDS for e in elements if isinstance(e, dict)):
            self._wire(x, bus_y, right, bus_y, live=in_live)
        else:
            # No output yet: an empty "?" coil shows where the rung ends.
            cx = right - SLOT_LEAD - COIL_RADIUS
            self._wire(x, bus_y, cx - COIL_RADIUS, bus_y, live=in_live)
            self._draw_coil(cx, bus_y, "", False, rung_comment=comment)
            self._wire(cx + COIL_RADIUS, bus_y, right, bus_y, live=False)
            self._terminals.append((cx - COIL_RADIUS, bus_y))
            self._terminals.append((cx + COIL_RADIUS, bus_y))
            self._bodies.append((cx - COIL_RADIUS, cx + COIL_RADIUS, bus_y))

        if isinstance(rung.get("elements"), list) and rung.get("elements"):
            coils_i = [i for i, e in enumerate(elements) if isinstance(e, dict) and _el_kind(e) == "coil"]
            if coils_i and (len(coils_i) > 1 or coils_i[0] < len(elements) - 1):
                self.canvas.create_text(right - SEAL_IN_GAP, y + 14, anchor="e", fill="#6b4c00",
                                        font=(self.fonts.ui_family, 9, "bold"), text="mid-rung")
        elif rung_has_seal_in(rung):
            self.canvas.create_text(right - SEAL_IN_GAP, y + 14, anchor="e", fill="#0b5e4a",
                                    font=(self.fonts.ui_family, 9, "bold"), text="seal-in")


    def _draw_contact(
        self,
        x: float,
        y: float,
        contact: dict,
        *,
        rung_comment: str = "",
        flow_key: str | None = None,
        note: str = "",
    ) -> None:
        tag = (contact.get("tag") or "").strip()
        nc = bool(contact.get("normally_closed"))
        h = CONTACT_HALF_H
        gap = CONTACT_GAP
        flow = self._flow(flow_key)
        live_sim = self.__dict__.get("_scan_sim_obj") if self._sim_session else None
        if flow is not None:
            # Studio-style: highlight when the instruction is TRUE (conducts), green.
            active = bool(flow.get("cond"))
            if live_sim is not None and tag:
                # Online-monitor style: the contact shows its bit now, even
                # before the rung-by-rung cursor re-runs this rung.
                value = live_sim.read(tag)
                active = (not value) if nc else bool(value)
            color = LADDER_POWER if active else LADDER_SYMBOL
            box_fill, box_outline = LADDER_TRUE_FILL, LADDER_POWER
        else:
            active = bool(tag) and tag in self._sim_active_tags and self._sim_flash_on
            color = LADDER_ACTIVE if active else LADDER_SYMBOL
            box_fill, box_outline = LADDER_ACTIVE_FILL, LADDER_ACTIVE
        width = 5 if active else 3
        if active:
            self.canvas.create_rectangle(
                x - gap / 2 - 8,
                y - h - 6,
                x + gap / 2 + 8,
                y + h + 6,
                fill=box_fill,
                outline=box_outline,
                width=2,
            )
        # Vertical bars for contact  | |
        self.canvas.create_line(x - gap / 2, y - h, x - gap / 2, y + h, fill=color, width=width)
        self.canvas.create_line(x + gap / 2, y - h, x + gap / 2, y + h, fill=color, width=width)
        if nc:
            # diagonal slash for NC  |/|
            self.canvas.create_line(
                x - gap / 2 - 2, y + h - 2, x + gap / 2 + 2, y - h + 2, fill=color, width=2
            )
        # Short tag only — full type / wires / I/O / why live on hover.
        self.canvas.create_text(
            x,
            y - h - TAG_CLEAR_ABOVE + 6,
            fill=color if active else LADDER_LABEL,
            font=(self.fonts.mono_family, 10, "bold"),
            text=tag or "?",
        )
        self._forced_marker(x + gap / 2 + 6, y - h - 2, tag)
        self._draw_note(x, y + h + 16, note)
        tip = device_hover_detail(
            self._device_map.get(tag),
            tag,
            kind="contact",
            normally_closed=nc,
            rung_comment=rung_comment,
        )
        if flow is not None:
            tip += (
                f"\nLive: instruction {'TRUE' if flow.get('cond') else 'FALSE'} · "
                f"power in {'ON' if flow.get('in') else 'off'} · out {'ON' if flow.get('out') else 'off'}"
            )
        if note:
            tip += f"\nNote: {note}"
        if self._sim_session:
            tip += "\nSimulating: click to switch on/off · right-click to release the force"
        pad = 14
        self._hover_targets.append((x - gap / 2 - pad, y - h - pad, x + gap / 2 + pad, y + h + pad, tip))
        self._click_targets.append((x - gap / 2 - pad, y - h - pad, x + gap / 2 + pad, y + h + pad, "contact", tag))

    def _draw_compare_box(self, x: float, y: float, el: dict, *, rung_comment: str = "", flow_key: str | None = None) -> None:
        op = str(el.get("op") or "EQU").upper()
        a = str(el.get("source_a") or "")
        b = str(el.get("source_b") or "")
        c = str(el.get("source_c") or "")
        w, h = 100, 56
        flow = self._flow(flow_key)
        true = bool(flow and flow.get("cond"))
        self.canvas.create_rectangle(
            x - w / 2, y - h / 2, x + w / 2, y + h / 2,
            outline=LADDER_POWER if true else "#0a5a7a", width=3 if true else 2,
            fill=LADDER_TRUE_FILL if true else self._lbg,
        )
        if op == "LIM":
            mid, bot = f"{b}≤{a}≤{c}"[:20], (c or b)
            tip_extra = f"LIM Low={b} Test={a} High={c}"
        elif op == "MEQ":
            mid, bot = f"{a}&{b}"[:20], f"=={c}&{b}"[:20]
            tip_extra = f"MEQ Source={a} Mask={b} Compare={c}"
        else:
            mid, bot = a, b
            tip_extra = f"Compare {op}  A={a}  B={b}"
        if self._scan_sim is not None:
            try:
                if op == "LIM":
                    live = (
                        f"{self._scan_sim.read_number(b):g}≤"
                        f"{self._scan_sim.read_number(a):g}≤"
                        f"{self._scan_sim.read_number(c):g}"
                    )
                elif op == "MEQ":
                    live = f"mask={int(self._scan_sim.read_number(b))}"
                else:
                    live = f"{self._scan_sim.read_number(a):g} vs {self._scan_sim.read_number(b):g}"
                self.canvas.create_text(
                    x, y + h / 2 + 8, fill=LADDER_MUTED, font=(self.fonts.ui_family, 8), text=live
                )
            except Exception:
                pass
        tip = tip_extra + chr(10) + "TRUE passes power (like a contact)."
        if flow is not None:
            tip += chr(10) + ("Live: TRUE" if true else "Live: FALSE")
        if el.get("desc"):
            tip += chr(10) + f"Note: {el.get('desc')}"
        self._hover_targets.append((x - w / 2 - 6, y - h / 2 - 6, x + w / 2 + 6, y + h / 2 + 6, tip))
        self.canvas.create_text(x, y - h / 2 - 8, fill="#0a5a7a", font=(self.fonts.mono_family, 10, "bold"), text=op)
        self.canvas.create_text(x, y - 4, fill=LADDER_LABEL, font=(self.fonts.mono_family, 9, "bold"), text=mid)
        self.canvas.create_text(x, y + 12, fill=LADDER_MUTED, font=(self.fonts.ui_family, 9), text=str(bot)[:22])

    def _draw_math_box(self, x: float, y: float, el: dict, *, rung_comment: str = "", flow_key: str | None = None) -> None:
        op = str(el.get("op") or "ADD").upper()
        dest = str(el.get("dest") or "")
        a = str(el.get("source_a") or "")
        b = str(el.get("source_b") or "")
        w, h = 110, 64
        if op == "MOV":
            detail = f"{a}→{dest}"
        elif op == "CPT":
            detail = str(el.get("expression") or a)[:22]
        elif op == "NOT":
            detail = f"~{a}"
        else:
            detail = f"{a},{b}"
        flow = self._flow(flow_key)
        en = bool(flow and flow.get("in"))
        self.canvas.create_rectangle(
            x - w / 2, y - h / 2, x + w / 2, y + h / 2,
            outline=LADDER_POWER if en else "#5a3a0a", width=3 if en else 2,
            fill=LADDER_TRUE_FILL if en else self._lbg,
        )
        if self._scan_sim is not None and dest:
            try:
                self.canvas.create_text(
                    x, y + h / 2 + 8, fill=LADDER_MUTED, font=(self.fonts.ui_family, 8),
                    text=f"{dest} = {self._scan_sim.read_number(dest):g}",
                )
            except Exception:
                pass
        self.canvas.create_text(x, y - h / 2 - 8, fill="#5a3a0a", font=(self.fonts.mono_family, 10, "bold"), text=dest)
        self.canvas.create_text(x, y - 4, fill=LADDER_LABEL, font=(self.fonts.ui_family, 11, "bold"), text=op)
        self.canvas.create_text(x, y + 14, fill=LADDER_MUTED, font=(self.fonts.ui_family, 8), text=detail[:22])

    def _draw_coil(
        self,
        x: float,
        y: float,
        tag: str,
        negated: bool = False,
        *,
        rung_comment: str = "",
        flow_key: str | None = None,
        note: str = "",
    ) -> None:
        r = COIL_RADIUS
        flow = self._flow(flow_key)
        pulse = bool(tag) and tag in self._sim_pulse_tags and self._sim_flash_on
        if flow is not None:
            active = bool(flow.get("in"))  # rung power reaching the coil
            outline = LADDER_PULSE if (pulse and active) else (LADDER_POWER if active else LADDER_COIL)
            fill = LADDER_TRUE_FILL if active else self._lbg
            pulse = pulse and active
        else:
            active = bool(tag) and tag in self._sim_active_tags and self._sim_flash_on
            outline = LADDER_PULSE if pulse else (LADDER_ACTIVE if active else LADDER_COIL)
            fill = LADDER_ACTIVE_FILL if (active or pulse) else self._lbg
        live_sim = self.__dict__.get("_scan_sim_obj") if self._sim_session else None
        if live_sim is not None and tag and tag in live_sim.forces:
            active = bool(live_sim.forces[tag])
            outline = LADDER_POWER if active else LADDER_COIL
            fill = LADDER_TRUE_FILL if active else self._lbg
        width = 5 if (active or pulse) else 3
        self.canvas.create_oval(x - r, y - r, x + r, y + r, outline=outline, width=width, fill=fill)
        if negated:
            self.canvas.create_line(x - r + 3, y + r - 3, x + r - 3, y - r + 3, fill=outline, width=2)
        self.canvas.create_text(
            x,
            y - r - TAG_CLEAR_ABOVE + 6,
            fill=outline,
            font=(self.fonts.mono_family, 10, "bold"),
            text=tag or "?",
        )
        self._forced_marker(x + r + 2, y - r - 2, tag)
        self._draw_note(x, y + r + 16, note)
        tip = device_hover_detail(
            self._device_map.get(tag),
            tag,
            kind="coil",
            normally_closed=False,
            rung_comment=rung_comment,
        )
        if flow is not None:
            tip += f"\nLive: rung power {'ON' if flow.get('in') else 'off'} · {tag} = {'1' if self._scan_sim and self._scan_sim.read(tag) else '0'}"
        if note:
            tip += f"\nNote: {note}"
        if self._sim_session:
            tip += "\nSimulating: click to force on/off · right-click to release the force"
        pad = 10
        self._hover_targets.append((x - r - pad, y - r - pad, x + r + pad, y + r + pad, tip))
        self._click_targets.append((x - r - pad, y - r - pad, x + r + pad, y + r + pad, "coil", tag))

    def _draw_timer(self, x: float, y: float, timer: dict, *, rung_comment: str = "", flow_key: str | None = None) -> None:
        """TON / TOF / RTO box: preset, live ACC in seconds, time left and a progress bar.

        The ACC text, status text and bar are registered in ``_timer_live`` so the
        simulator's timer tick can update them in place between rung redraws."""
        tag = (timer.get("tag") or "").strip() or "?"
        block = str(timer.get("block") or "TON").upper()
        pt_ms = int(timer.get("pt_ms") or 0)
        pt_tag = str(timer.get("pt_tag") or "").strip()
        w, h = TIMER_BOX_W, TIMER_BOX_H
        sim = self._scan_sim
        tmr = dict(sim.timers.get(tag) or {}) if sim is not None else {}
        if sim is not None and not tmr:
            tmr = {"block": block, "pt_ms": pt_ms, "acc_ms": 0}
        if tmr and not int(tmr.get("pt_ms") or 0):
            tmr["pt_ms"] = pt_ms
        acc = int(tmr.get("acc_ms") or 0)
        dn = bool(tmr.get("q"))
        tt = bool(tmr.get("tt"))
        tflow = self._flow(flow_key)
        enabled = bool(tflow and tflow.get("in")) or bool(tmr.get("en"))
        if tt or dn:
            outline, fill, width = LADDER_POWER, LADDER_TRUE_FILL, 4 if dn else 3
        elif enabled and tmr:
            outline, fill, width = LADDER_POWER, self._lbg, 3
        else:
            outline, fill, width = LADDER_TIMER, self._lbg, 2
        x0, y0, x1, y1 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
        box = self.canvas.create_rectangle(x0, y0, x1, y1, outline=outline, width=width, fill=fill)
        self.canvas.create_text(x, y0 - 10, fill=outline, font=(self.fonts.mono_family, 9, "bold"), text=tag)
        kind = {"TON": "on-delay", "TOF": "off-delay", "RTO": "retentive"}.get(block, "")
        self.canvas.create_text(x, y0 + 11, fill=LADDER_LABEL, font=(self.fonts.ui_family, 10, "bold"),
                                text=f"{block}  {kind}".strip())
        if pt_tag:
            pre = f"PRE {pt_tag}" + (f" = {int(tmr.get('pt_ms') or 0) / 1000:.1f} s" if tmr else "")
        else:
            pre = f"PRE {pt_ms / 1000:.1f} s"
        self.canvas.create_text(x, y0 + 26, fill=LADDER_MUTED, font=(self.fonts.ui_family, 8), text=pre[:24])
        acc_text, status, frac = timer_live_text(tmr) if tmr else ("ACC 0.0 s", "", 0.0)
        acc_id = self.canvas.create_text(x, y0 + 41, fill=LADDER_POWER if (tt or dn) else LADDER_LABEL,
                                         font=(self.fonts.mono_family, 10, "bold"), text=acc_text)
        status_id = self.canvas.create_text(x, y0 + 55, fill=LADDER_POWER if (tt or dn) else LADDER_MUTED,
                                            font=(self.fonts.ui_family, 8, "bold"), text=status if tmr else "")
        bx0, bx1, by0, by1 = x0 + 8, x1 - 8, y1 - 12, y1 - 6
        self.canvas.create_rectangle(bx0, by0, bx1, by1, outline=LADDER_MUTED, width=1, fill=self._lbg)
        bar_id = self.canvas.create_rectangle(bx0, by0, bx0 + (bx1 - bx0) * frac, by1, outline="",
                                              fill=LADDER_POWER if frac > 0 else self._lbg)
        self._timer_live.setdefault(tag, []).append(
            {"box": box, "acc": acc_id, "status": status_id, "bar": bar_id, "bar_x": (bx0, bx1, by0, by1)}
        )
        tip = (
            f"Timer {block} ({kind})  {tag}\n"
            + (f"Preset PRE = tag {pt_tag} (ms, read at run time)\n" if pt_tag else f"Preset PRE = {pt_ms} ms\n")
            + f"ACC = {acc} ms   DN = {dn}   TT = {tt}\n"
            + {"TON": "Times while the rung is true; DN turns on when ACC reaches PRE. False resets it.",
               "TOF": "Output DN is on while the rung is true; after it goes false, counts to PRE then DN turns off.",
               "RTO": "Times while the rung is true and HOLDS ACC when it goes false; reset it with RES."}.get(block, "")
            + "\nEducational scan — not a live PLC."
        )
        if rung_comment:
            tip += f"\nRung: {rung_comment}"
        if self._sim_session:
            tip += "\nSimulating: click to reset this timer"
        pad = 6
        self._hover_targets.append((x0 - pad, y0 - pad, x1 + pad, y1 + pad, tip))
        self._click_targets.append((x0 - pad, y0 - pad, x1 + pad, y1 + pad, "timer", tag))

    def _refresh_timer_items(self) -> None:
        """Update every drawn timer box from the simulator without a full redraw."""
        sim = self.__dict__.get("_scan_sim_obj")
        if sim is None or not hasattr(self, "canvas"):
            return
        for tag, parts in (self.__dict__.get("_timer_live") or {}).items():
            tmr = sim.timers.get(tag)
            if not tmr:
                continue
            acc_text, status, frac = timer_live_text(tmr)
            on = bool(tmr.get("tt") or tmr.get("q"))
            for p in parts:
                try:
                    bx0, bx1, by0, by1 = p["bar_x"]
                    self.canvas.itemconfigure(p["acc"], text=acc_text, fill=LADDER_POWER if on else LADDER_LABEL)
                    self.canvas.itemconfigure(p["status"], text=status, fill=LADDER_POWER if on else LADDER_MUTED)
                    self.canvas.coords(p["bar"], bx0, by0, bx0 + (bx1 - bx0) * frac, by1)
                    self.canvas.itemconfigure(p["bar"], fill=LADDER_POWER if frac > 0 else self._lbg)
                    self.canvas.itemconfigure(p["box"], outline=LADDER_POWER if (on or tmr.get("en")) else LADDER_TIMER,
                                              fill=LADDER_TRUE_FILL if on else self._lbg)
                except tk.TclError:
                    pass

    def _draw_counter(self, x: float, y: float, counter: dict, *, rung_comment: str = "", flow_key: str | None = None) -> None:
        """Draw educational CTU/CTD box (tag, PRE, live ACC/DN) or RES/LOAD output oval."""
        tag = (counter.get("tag") or "").strip() or "?"
        block = str(counter.get("block") or "CTU").upper()
        pv = int(counter.get("pv") or 0)
        pv_tag = str(counter.get("pv_tag") or "").strip()
        live = None
        if self._scan_sim is not None and tag in getattr(self._scan_sim, "counters", {}):
            live = self._scan_sim.counters[tag]
        acc = int(live.get("acc") or 0) if live else 0
        pre = int(live.get("pre") or 0) if live else pv
        dn = bool(live.get("dn")) if live else False
        cu = bool(live.get("cu")) if live else False
        cd = bool(live.get("cd")) if live else False
        flash = self._sim_flash_on and live is not None
        if block in {"RES", "LOAD"}:
            w, h = COUNTER_OUT_W, COUNTER_OUT_H
            outline = LADDER_COUNTER
            self.canvas.create_oval(x - w / 2, y - h / 2, x + w / 2, y + h / 2, outline=outline, width=3, fill=self._lbg)
            self.canvas.create_text(x, y - h / 2 - 10, fill=outline, font=(self.fonts.mono_family, 9, "bold"), text=tag)
            self.canvas.create_text(x, y, fill=LADDER_LABEL, font=(self.fonts.ui_family, 10, "bold"), text=block)
            what = "ACC := 0 (and OV/UN clear)" if block == "RES" else "ACC := PRE (CCW CTD LOAD)"
            tip = (
                f"Counter {block}  {tag}\n"
                f"While this rung is true: {what}\n"
                + (f"Live ACC = {acc} / PRE {pre}   DN = {dn}\n" if live else "")
                + "Educational scan — not a live PLC."
            )
            if rung_comment:
                tip += f"\nRung: {rung_comment}"
            if self._sim_session:
                tip += "\nSimulating: click to reset this counter"
            self._hover_targets.append((x - w / 2 - 6, y - h / 2 - 6, x + w / 2 + 6, y + h / 2 + 6, tip))
            self._click_targets.append((x - w / 2 - 6, y - h / 2 - 6, x + w / 2 + 6, y + h / 2 + 6, "counter", tag))
            return
        w, h = COUNTER_BOX_W, COUNTER_BOX_H
        active = flash and (dn or cu or cd)
        outline = LADDER_ACTIVE if active else LADDER_COUNTER
        fill = LADDER_ACTIVE_FILL if active else self._lbg
        width = 4 if active else 2
        self.canvas.create_rectangle(x - w / 2, y - h / 2, x + w / 2, y + h / 2, outline=outline, width=width, fill=fill)
        self.canvas.create_text(x, y - h / 2 - 10, fill=outline, font=(self.fonts.mono_family, 9, "bold"), text=tag)
        self.canvas.create_text(x, y - 14, fill=LADDER_LABEL, font=(self.fonts.ui_family, 10, "bold"), text=block)
        self.canvas.create_text(x, y + 2, fill=LADDER_MUTED, font=(self.fonts.ui_family, 8), text=(f"PRE {pv_tag}" if (pv_tag and not live) else f"PRE {pre}"))
        if live is not None:
            edge = "CU" if (block == "CTU" and cu) else ("CD" if (block == "CTD" and cd) else "")
            bits = "  ".join(b for b in (edge, "DN" if dn else "") if b)
            self.canvas.create_text(
                x,
                y + 16,
                fill=LADDER_ACTIVE if dn else LADDER_MUTED,
                font=(self.fonts.ui_family, 8, "bold" if dn else "normal"),
                text=f"ACC {acc}  {bits}".strip(),
            )
        done = "ACC >= PRE" if block == "CTU" else "ACC <= 0"
        edge_name = "CU (count up)" if block == "CTU" else "CD (count down)"
        tip = (
            f"Counter {block}  {tag}\n"
            f"Preset PRE = {pre}   ACC = {acc}\n"
            f"DN = {dn}  (DN when {done})   {edge_name} = {cu if block == 'CTU' else cd}\n"
            f"Counts once per rising edge of the rung. Use {tag}.DN as a contact.\n"
            "Educational scan (CCW / Micro800-style) — not a live PLC."
        )
        if rung_comment:
            tip += f"\nRung: {rung_comment}"
        if self._sim_session:
            tip += "\nSimulating: click to reset this counter"
        self._hover_targets.append((x - w / 2 - 6, y - h / 2 - 6, x + w / 2 + 6, y + h / 2 + 6, tip))
        self._click_targets.append((x - w / 2 - 6, y - h / 2 - 6, x + w / 2 + 6, y + h / 2 + 6, "counter", tag))

    def _on_canvas_motion(self, event) -> None:
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        tip = None
        for x0, y0, x1, y1, text in reversed(self._hover_targets):
            if x0 <= x <= x1 and y0 <= y <= y1:
                tip = text
                break
        key = tip or ""
        if key == (self._hover_key or ""):
            return
        self._hover_key = key
        if self._hover_after is not None:
            try:
                self.after_cancel(self._hover_after)
            except Exception:
                pass
            self._hover_after = None
        if not tip:
            self._hide_hover_tip()
            return
        # Slight delay so scrubbing the ladder does not flash popups.
        self._hover_after = self.after(180, lambda t=tip, ex=event.x_root, ey=event.y_root: self._show_hover_tip(t, ex, ey))

    def _show_hover_tip(self, text: str, root_x: int, root_y: int) -> None:
        self._hover_after = None
        self._hide_hover_tip(clear_key=False)
        tip = ctk.CTkToplevel(self)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        frame = ctk.CTkFrame(tip, fg_color=TIP_BG, corner_radius=6, border_width=1, border_color=TIP_BORDER)
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(
            frame,
            text=text,
            font=self.fonts.tiny,
            text_color=TIP_TEXT,
            justify="left",
            anchor="w",
            wraplength=360,
        ).pack(padx=10, pady=8)
        tip.update_idletasks()
        tip.geometry(f"+{root_x + 16}+{root_y + 16}")
        tip.deiconify()
        self._hover_tip = tip

    def _hide_hover_tip(self, _event=None, *, clear_key: bool = True) -> None:
        if self._hover_after is not None:
            try:
                self.after_cancel(self._hover_after)
            except Exception:
                pass
            self._hover_after = None
        if clear_key:
            self._hover_key = None
        if self._hover_tip is not None:
            try:
                self._hover_tip.destroy()
            except Exception:
                pass
            self._hover_tip = None

    # --- Educational ladder simulation (not a live PLC) --------------------

    def _sim_rungs(self) -> list[dict]:
        return list(self.program.get("rungs") or [])

    def _sim_set_status(self, text: str) -> None:
        for label in (self._sim_status, self._sim_status_float):
            if label is None:
                continue
            try:
                label.configure(text=text)
            except Exception:
                pass
        self._update_statusbar()

    # v0.3.20: every edit sets ``self._scan_sim = None``. During a sim session the
    # old simulator is kept as _sim_carry and the next read rebuilds from the
    # edited program, adopting tag values, timer/counter ACC and forces.
    @property
    def _scan_sim(self) -> ScanSimulator | None:
        sim = self.__dict__.get("_scan_sim_obj")
        if sim is None and self.__dict__.get("_sim_carry") is not None:
            sim = self._rebuild_sim_from_carry()
        return sim

    @_scan_sim.setter
    def _scan_sim(self, value: ScanSimulator | None) -> None:
        old = self.__dict__.get("_scan_sim_obj")
        if value is None and old is not None and self.__dict__.get("_sim_session"):
            self.__dict__["_sim_carry"] = old
        elif value is not None:
            self.__dict__["_sim_carry"] = None
        self.__dict__["_scan_sim_obj"] = value

    def _rebuild_sim_from_carry(self) -> ScanSimulator | None:
        carry = self.__dict__.get("_sim_carry")
        try:
            sim = ScanSimulator.from_program(
                self.program,
                project_name=getattr(self.project, "name", "") or "",
                devices=cabinet_device_tags(self.project),
                cycle_ms=100,
            )
            sim.adopt_state(carry)
        except Exception:
            return None  # keep the carry; retried after the next edit / tick
        self.__dict__["_sim_carry"] = None
        self.__dict__["_scan_sim_obj"] = sim
        self._force_sig = None
        return sim

    def _ensure_scan_sim(self, *, reset: bool = False) -> ScanSimulator:
        if reset:
            self.__dict__["_sim_carry"] = None
        if reset or self._scan_sim is None:
            self._scan_sim = ScanSimulator.from_program(
                self.program,
                project_name=getattr(self.project, "name", "") or "",
                devices=cabinet_device_tags(self.project),
                cycle_ms=100,
            )
        return self._scan_sim

    def _rebuild_force_strip(self) -> None:
        """Build clickable force toggles for educational scan inputs."""
        for child in self._force_strip.winfo_children():
            child.destroy()
        self._force_buttons = {}
        if not self._sim_rungs():
            ctk.CTkLabel(
                self._force_strip,
                text="No rungs yet — build a program first.",
                font=self.fonts.tiny,
                text_color=MUTED,
            ).pack(side="left", padx=6, pady=4)
            return
        sim = self._ensure_scan_sim()
        inputs = sim.input_tags()
        outputs = sim.output_tags()
        ctk.CTkLabel(
            self._force_strip,
            text="Force inputs (click to toggle):",
            font=self.fonts.tiny,
            text_color=MUTED,
        ).pack(side="left", padx=(6, 4), pady=4)
        if not inputs:
            ctk.CTkLabel(
                self._force_strip,
                text="(no input tags)",
                font=self.fonts.tiny,
                text_color=MUTED,
            ).pack(side="left", padx=4, pady=4)
        if sim.forces:
            ghost_button(
                self._force_strip, f"Clear forces ({len(sim.forces)})", self._sim_clear_forces, self.fonts.tiny, width=120
            ).pack(side="left", padx=(2, 6), pady=4)
        self._force_value_widgets = {}
        for tag in inputs:
            val = sim.read(tag)
            forced = tag in sim.forces
            btn = ctk.CTkButton(
                self._force_strip,
                text=f"{tag}={'1' if val else '0'}{'  F' if forced else ''}",
                border_width=2 if forced else 0,
                border_color=LADDER_FORCE,
                width=max(90, 12 * len(tag) + 36),
                height=26,
                font=self.fonts.tiny,
                fg_color=BLUE if val else ENTRY,
                hover_color=BLUE_HOVER,
                text_color=TEXT,
                command=lambda t=tag: self._sim_toggle_force(t),
            )
            btn.pack(side="left", padx=3, pady=4)
            self._force_buttons[tag] = btn
            self._force_value_widgets[f"in:{tag}"] = btn
        if outputs:
            ctk.CTkLabel(
                self._force_strip,
                text="  Coils:",
                font=self.fonts.tiny,
                text_color=MUTED,
            ).pack(side="left", padx=(10, 4), pady=4)
            for tag in outputs:
                if tag in sim.timers or tag in getattr(sim, "counters", {}):
                    continue
                val = sim.read(tag)
                lbl = ctk.CTkLabel(
                    self._force_strip,
                    text=f"{tag}={'ON' if val else 'off'}",
                    font=self.fonts.tiny,
                    text_color=LADDER_ACTIVE if val else MUTED,
                )
                lbl.pack(side="left", padx=4, pady=4)
                self._force_value_widgets[f"coil:{tag}"] = lbl
        if sim.timers:
            ctk.CTkLabel(
                self._force_strip,
                text="  Timers:",
                font=self.fonts.tiny,
                text_color=MUTED,
            ).pack(side="left", padx=(10, 4), pady=4)
            for tag, tmr in sorted(sim.timers.items()):
                text, dn = self._timer_strip_text(tag, tmr)
                lbl = ctk.CTkLabel(
                    self._force_strip,
                    text=text,
                    font=self.fonts.tiny,
                    text_color=LADDER_ACTIVE if dn else MUTED,
                )
                lbl.pack(side="left", padx=4, pady=4)
                self._force_value_widgets[f"tmr:{tag}"] = lbl
        counters = getattr(sim, "counters", {}) or {}
        if counters:
            ctk.CTkLabel(
                self._force_strip,
                text="  Counters:",
                font=self.fonts.tiny,
                text_color=MUTED,
            ).pack(side="left", padx=(10, 4), pady=4)
            for tag, ctr in sorted(counters.items()):
                text, dn = self._counter_strip_text(tag, ctr)
                lbl = ctk.CTkLabel(
                    self._force_strip,
                    text=text,
                    font=self.fonts.tiny,
                    text_color=LADDER_ACTIVE if dn else MUTED,
                )
                lbl.pack(side="left", padx=4, pady=4)
                self._force_value_widgets[f"ctr:{tag}"] = lbl
        self._force_sig = self._force_strip_sig(sim)

    @staticmethod
    def _timer_strip_text(tag: str, tmr: dict) -> tuple[str, bool]:
        acc = int(tmr.get("acc_ms") or 0)
        pt = int(tmr.get("pt_ms") or 0)
        dn = bool(tmr.get("q"))
        flag = "DN" if dn else ("TT" if tmr.get("tt") else "")
        return f"{tmr.get('block') or 'TON'}:{tag} {acc / 1000:.1f}/{pt / 1000:.1f}s {flag}".strip(), dn

    @staticmethod
    def _counter_strip_text(tag: str, ctr: dict) -> tuple[str, bool]:
        dn = bool(ctr.get("dn"))
        text = f"{ctr.get('block', 'CTU')}:{tag} ACC={int(ctr.get('acc') or 0)}/{int(ctr.get('pre') or 0)} {'DN' if dn else ''}"
        return text.strip(), dn

    def _force_strip_sig(self, sim: ScanSimulator) -> tuple:
        counters = getattr(sim, "counters", {}) or {}
        coils = [t for t in sim.output_tags() if t not in sim.timers and t not in counters]
        return (
            str(self._force_strip), id(sim), tuple(sim.input_tags()), tuple(coils),
            tuple(sorted(sim.timers)), tuple(sorted(counters)), len(sim.forces),
        )

    def _refresh_force_strip(self) -> None:
        """v0.3.20: update the I/O values in place; rebuild only when the tag set changes."""
        sim = self._scan_sim
        if sim is None or not self._sim_rungs():
            self._rebuild_force_strip_safe()
            return
        if self._force_sig != self._force_strip_sig(sim):
            self._rebuild_force_strip()
            return
        try:
            for key, widget in self._force_value_widgets.items():
                kind, tag = key.split(":", 1)
                if kind == "in":
                    val, forced = sim.read(tag), tag in sim.forces
                    widget.configure(
                        text=f"{tag}={'1' if val else '0'}{'  F' if forced else ''}",
                        border_width=2 if forced else 0,
                        fg_color=BLUE if val else ENTRY,
                    )
                elif kind == "coil":
                    val = sim.read(tag)
                    widget.configure(text=f"{tag}={'ON' if val else 'off'}", text_color=LADDER_ACTIVE if val else MUTED)
                elif kind == "tmr":
                    text, dn = self._timer_strip_text(tag, sim.timers.get(tag) or {})
                    widget.configure(text=text, text_color=LADDER_ACTIVE if dn else MUTED)
                elif kind == "ctr":
                    text, dn = self._counter_strip_text(tag, sim.counters.get(tag) or {})
                    widget.configure(text=text, text_color=LADDER_ACTIVE if dn else MUTED)
        except Exception:
            self._rebuild_force_strip()

    def _sim_clear_forces(self) -> None:
        # v0.3.18 NEW-10: every scan entry point respects sim_blockers().
        if self._sim_blocked():
            return
        sim = self._ensure_scan_sim()
        for tag in list(sim.forces):
            sim.set_force(tag, None)
            sim.vars[tag] = False
        self._sim_session = True
        self._sim_operator_changed("All forces released.")

    def _sim_toggle_force(self, tag: str) -> None:
        # v0.3.18 NEW-10: a force click runs a scan — blocked like Run / Step.
        if self._sim_blocked():
            return
        self._sim_session = True
        self._sim_operate_part("contact", tag)

    def _sim_apply_scan_result(self, result: dict, *, mode: str) -> None:
        try:
            self._watch.record(result)
            if self._tool_window_open("watch"):
                self._refresh_watch_panel()
        except Exception:
            pass
        self._sim_flow = dict(result.get("power_flow") or {})
        self._sim_energized = dict(result.get("energized_paths") or {})
        self._sim_active_tags = {t for t, v in (result.get("vars") or {}).items() if v}
        for tag, tmr in (result.get("timers") or {}).items():
            if tmr.get("q") or tmr.get("tt"):
                self._sim_active_tags.add(tag)
        try:
            # Member reads (C1.DN, T1.DN, T1.TT) light their contacts too.
            self._sim_active_tags |= self._ensure_scan_sim().active_tags()
        except Exception:
            pass
        self._sim_pulse_tags = set()
        for tag, val in (result.get("vars") or {}).items():
            if not val:
                continue
            upper = tag.upper().replace("-", "_")
            if (
                upper in {"PLACE_RELAY", "WELDER_RELAY", "WELDER", "PLACE"}
                or "WELDER" in upper
                or upper.startswith("PLACE_")
            ):
                self._sim_pulse_tags.add(tag)
        self._sim_flash_on = True
        sim = self._ensure_scan_sim()
        on_coils = [
            t
            for t in sorted(sim.output_tags())
            if result.get("vars", {}).get(t) and t not in sim.timers and t not in getattr(sim, "counters", {})
        ]
        coil_bit = (", ".join(on_coils) if on_coils else "none")
        timer_bits = []
        for tag, tmr in sorted((result.get("timers") or {}).items()):
            acc = int(tmr.get("acc_ms") or 0)
            pt = int(tmr.get("pt_ms") or 0)
            flag = "DN" if tmr.get("q") else ("TT" if tmr.get("tt") else "—")
            timer_bits.append(f"{tag}:{acc}/{pt}{flag}")
        timer_bit = (", ".join(timer_bits) if timer_bits else "")
        extra = f" · timers: {timer_bit}" if timer_bit else ""
        counter_bits = []
        for tag, ctr in sorted((result.get("counters") or {}).items()):
            flag = "DN" if ctr.get("dn") else "—"
            counter_bits.append(f"{tag}:{int(ctr.get('acc') or 0)}/{int(ctr.get('pre') or 0)}{flag}")
        if counter_bits:
            extra += " · counters: " + ", ".join(counter_bits)
        rungs = self._sim_rungs()
        idx = result.get("rung_index")
        rung_bit = ""
        if isinstance(idx, int) and 0 <= idx < len(rungs):
            self._sim_cursor_rung_id = rungs[idx].get("id")
            rung_bit = f" · rung {idx + 1}/{len(rungs)}"
        elif "rung_index" not in result:
            self._sim_cursor_rung_id = None
        self._sim_set_status(
            f"{self._sim_auto_prefix()}Sim {mode} scan #{result.get('scan_count', 0)}{rung_bit} · coils ON: "
            f"{coil_bit}{extra}  · educational only"
        )
        self.__dict__["_sim_auto_scans"] = self.__dict__.get("_sim_auto_scans", 0) + 1
        self._sim_parts_begin(result, mode)
        self._explain_scan(result)
        self._draw_ladder(preserve_scroll=True)
        self._follow_rung(self._follow_target())

    def _sim_blocked(self) -> bool:
        """v0.3.17: refuse to simulate while a CPT expression is empty / malformed."""
        try:
            from cabinet_studio.services.ladder_sim import sim_blockers

            blockers = sim_blockers(
                self.program,
                project_name=getattr(self.project, "name", "") or "",
                devices=cabinet_device_tags(self.project),
            )
        except Exception as exc:  # v0.3.18 (Deflector P3-2): fail closed
            blockers = [f"the program could not be checked before simulating ({type(exc).__name__})"]
        if not blockers:
            return False
        if self._sim_running:
            self._sim_cancel_timer()
            self._sim_running = False
        msg = "Sim BLOCKED - " + " | ".join(blockers)
        self._sim_set_status(msg)
        try:
            self.status.configure(text=msg)
        except Exception:
            pass
        return True

    def _sim_toggle_run(self) -> None:
        self._show_tab("ladder")
        if self._sim_running:
            self._sim_stop()
            return
        if not self._sim_rungs():
            self._sim_set_status("Sim: no rungs to run")
            return
        if self._sim_blocked():
            return
        if getattr(self, "_sim_engine", "scan") == "walk":
            self._sim_running = True
            if self._sim_index < 0:
                self._sim_index = 0
            self._sim_set_status("Sim RUN (legacy walk · educational only)")
            self._sim_apply_rung(flash_cycles=6, then_advance=True)
            return
        resume = self._sim_session and self._scan_sim is not None
        if not resume:
            self._ensure_scan_sim(reset=True)
            self._sim_session = True
        self._sim_resume_when_fixed = False
        self._rebuild_force_strip()
        if self._canvas_popout is not None and self._force_popout is None:
            self._pop_out_force_strip()
        self._sim_running = True
        pace = self._sim_speed_var.get()
        self._sim_set_status(
            f"Sim RUN ({pace}) - click switches on the ladder to operate them. Educational only - not a live PLC."
        )
        self._sim_scan_tick()

    def _sim_rung_ms(self) -> int:
        return int(_SIM_SPEEDS.get(self._sim_speed_var.get(), _SIM_SPEEDS[_SIM_DEFAULT_SPEED]))

    def _sim_rung_mode(self) -> bool:
        return self._sim_rung_ms() > 0

    def _on_sim_speed(self, choice: str | None = None) -> None:
        choice = choice or self._sim_speed_var.get()
        if choice not in _SIM_SPEEDS:
            return
        _save_ui_pref(_PROG_SIM_SPEED_PREF, choice)
        if self._sim_running:
            self._sim_cancel_timer()
            if not self._sim_rung_mode():
                self._sim_cursor_rung_id = None
            self._sim_after = self.after(50, self._sim_scan_tick)
        self._sim_set_status(f"Sim speed: {choice}. Educational only - not a live PLC.")

    def _sim_run(self) -> None:
        """Start, or resume after Pause / Step, without stopping a running sim."""
        if not self._sim_running:
            self._sim_toggle_run()

    def _sim_pause(self) -> None:
        """v0.3.20: freeze the sim where it is (values, timers, forces kept)."""
        if not self._sim_running and not self._sim_resume_when_fixed:
            self._sim_set_status("Sim is not running. Educational only - not a live PLC.")
            return
        self._sim_cancel_timer()
        self._sim_running = False
        self._sim_resume_when_fixed = False
        sim = self.__dict__.get("_scan_sim_obj")
        if sim is not None and sim.clock_ms is not None:
            sim.clock_ms = time.monotonic() * 1000.0
            sim.freeze_timers()
            self._refresh_timer_items()
        rungs = self._sim_rungs()
        where = ""
        for i, rung in enumerate(rungs):
            if rung.get("id") == self._sim_cursor_rung_id:
                where = f" at rung {i + 1}/{len(rungs)}"
        self._sim_set_status(
            f"Sim PAUSED{where} - change switches or edit rungs, then Run to continue. Educational only."
        )
        self._explain_where("you pressed Pause")

    def _sim_reset(self) -> None:
        """v0.3.20: everything off, timers/counters zero, forces cleared, back to rung 1."""
        if self._sim_blocked():
            return
        self._sim_parts_finish()
        self._sim_auto_cancel()
        self._ensure_scan_sim(reset=True)
        self._sim_session = True
        self._sim_cursor_rung_id = None
        self._sim_flow = {}
        self._sim_energized = {}
        self._sim_active_tags = set()
        self._sim_pulse_tags = set()
        self._rebuild_force_strip()
        self._draw_ladder(preserve_scroll=True)
        self._sim_set_status("Sim RESET - all bits off, timers and counters at 0, forces cleared. Educational only.")
        self.__dict__["_explain_last"] = {}
        self._explain_log(["SIM RESET - all bits OFF, timers and counters at 0, forces cleared.", ""])

    def _sim_step_rung(self) -> None:
        """v0.3.20: run just the next rung (timers count real seconds between steps)."""
        self._show_tab("ladder")
        self._sim_cancel_timer()
        self._sim_running = False
        self._sim_resume_when_fixed = False
        if not self._sim_rungs():
            self._sim_set_status("Sim: no rungs to step")
            return
        if self._sim_blocked():
            return
        self._sim_session = True
        sim = self._ensure_scan_sim()
        sim.clock_ms = time.monotonic() * 1000.0
        sim.tick_timers()
        result = sim.scan_rung(sim.rung_cursor)
        self._sim_apply_scan_result(result, mode="STEP RUNG")
        self._refresh_force_strip()

    def _sim_step(self) -> None:
        self._show_tab("ladder")
        self._sim_cancel_timer()
        self._sim_running = False
        self._sim_resume_when_fixed = False
        if not self._sim_rungs():
            self._sim_set_status("Sim: no rungs to step")
            return
        if self._sim_blocked():
            return
        if getattr(self, "_sim_engine", "scan") == "walk":
            rungs = self._sim_rungs()
            self._sim_index = (self._sim_index + 1) % len(rungs)
            self._sim_apply_rung(flash_cycles=8, then_advance=False)
            return
        self._sim_session = True
        sim = self._ensure_scan_sim()
        # A full-scan Step advances timers by one 100 ms scan, not wall time.
        sim.clock_ms = None
        sim._timer_clock.clear()
        result = sim.scan_once()
        self._sim_apply_scan_result(result, mode="STEP")
        self._rebuild_force_strip()

    def _sim_stop(self) -> None:
        self._sim_cancel_timer()
        self._sim_auto_cancel()
        self._sim_running = False
        self._sim_session = False
        self._sim_resume_when_fixed = False
        self.__dict__["_sim_carry"] = None
        self._sim_cursor_rung_id = None
        self._sim_index = -1
        self._sim_flash_on = False
        self._sim_flash_count = 0
        self._sim_active_tags = set()
        self._sim_pulse_tags = set()
        self._sim_flow = {}
        self._sim_energized = {}
        self._sim_set_status("Sim off (educational — not a live PLC)")
        self._explain_log(["SIM STOPPED.", ""])
        try:
            self._rebuild_force_strip()
        except Exception:
            pass
        self._draw_ladder(preserve_scroll=True)

    # ------------------------------------------------ v0.3.25 each part, left to right
    def _on_parts_toggle(self) -> None:
        on = bool(self._sim_parts_var.get())
        _save_ui_pref(_PROG_PARTS_PREF, on)
        if not on:
            self._sim_parts_finish()
            self._draw_ladder(preserve_scroll=True)
        self._sim_set_status(
            "Each part ON: every rung lights its parts one by one, left to right, within the rung time."
            if on else "Each part OFF: rungs light all at once.")

    def _sim_parts_begin(self, result: dict, mode: str) -> None:
        """Hide this rung's power flow, then reveal it one instruction at a time."""
        self._sim_parts_finish()
        idx = result.get("rung_index")
        var = self.__dict__.get("_sim_parts_var")
        if var is None or not var.get() or not isinstance(idx, int):
            return
        rungs = self._sim_rungs()
        if not 0 <= idx < len(rungs):
            return
        rung = rungs[idx]
        rid = str(rung.get("id") or idx)
        order = flow_order(self._rung_draw_elements(rung), lambda j: f"{rid}|L|{j}")
        if not order:
            return
        full = dict(self._sim_flow)
        self._sim_flow = {k: v for k, v in full.items() if not k.startswith(rid + "|")}
        self._sim_flow["__parts__"] = {}
        self._sim_parts = {"order": order, "n": 0, "full": full, "rid": rid, "idx": idx, "total": len(rungs),
                           "energized": self._sim_energized.pop(rid, None), "mode": mode}
        rung_ms = self._sim_rung_ms() or 1000
        self._sim_parts["step_ms"] = max(_SIM_PART_MIN_MS, int(rung_ms * 0.9) // len(order))
        self._sim_part_after = self.after(self._sim_parts["step_ms"] // 2, self._sim_part_tick)
        if self._explain_open():
            self._explain_log([explain_rung([], rid, idx + 1, len(rungs), rung.get("comment") or "",
                                            {}, None, None, {})[0] + "   (watching each part...)"])

    def _sim_part_tick(self) -> None:
        self._sim_part_after = None
        p = self._sim_parts
        if p is None:
            return
        if p["n"] >= len(p["order"]):
            self._sim_parts_finish()
            self._draw_ladder(preserve_scroll=True)
            return
        key, el, depth = p["order"][p["n"]]
        p["n"] += 1
        flow = p["full"].get(key) or {}
        if self._explain_open():
            self._explain_log(["   " + "    " * depth + f"{p['n']}. "
                               + explain_part(el, flow, self._ensure_scan_sim(), self._explain_wmap())])
        self._sim_flow[key] = flow
        self._sim_part_key = key
        if _el_kind(el) in _OUTPUT_KINDS:
            result = "energized (ON)" if flow.get("in") else "not energized (OFF)"
        elif _el_kind(el) == "or":
            result = "power reaches the branch" if flow.get("in") else "no power to the branch"
        else:
            result = "TRUE - power passes" if flow.get("out") else "FALSE - power stops here"
        self._sim_set_status(
            f"{self._sim_auto_prefix()}Sim {p['mode']} rung {p['idx'] + 1}/{p['total']} · part {p['n']}/"
            f"{len(p['order'])}: {_part_name(el)} → {result}  · educational only")
        self._draw_ladder(preserve_scroll=True)
        self._sim_part_after = self.after(p["step_ms"], self._sim_part_tick)

    def _sim_parts_finish(self) -> None:
        """Show the whole rung's result now (also used when the next rung starts or on Pause)."""
        if self.__dict__.get("_sim_part_after") is not None:
            try:
                self.after_cancel(self._sim_part_after)
            except Exception:
                pass
        self._sim_part_after = None
        p, self._sim_parts = self.__dict__.get("_sim_parts"), None
        self._sim_part_key = None
        if p is not None:
            self._sim_flow = p["full"]
            if p["energized"] is not None:
                self._sim_energized[p["rid"]] = p["energized"]
            if self._explain_open():
                self._explain_log(["   " + rung_summary(p["order"], p["full"], p["energized"],
                                                        self._ensure_scan_sim(), self._explain_wmap()), ""])

    # ------------------------------------------------ v0.3.25 Explain run
    def _open_explain_run(self) -> None:
        from cabinet_studio.ui.explain_run import ExplainRunWindow

        if self._explain_open():
            self._explain_win.lift()
            return
        self._explain_win = ExplainRunWindow(self, self.fonts)
        try:
            self._explain_win.transient(self.winfo_toplevel())
        except Exception:
            pass
        self.__dict__["_explain_last"] = {}
        if self._sim_session:
            self._explain_where("Sim is " + ("RUNNING" if self._sim_running else "PAUSED"))

    def _explain_open(self) -> bool:
        win = self.__dict__.get("_explain_win")
        try:
            return win is not None and bool(win.winfo_exists())
        except Exception:
            return False

    def _explain_log(self, lines: list[str], style: str | None = None) -> None:
        if self._explain_open():
            self._explain_win.add(lines, style)

    def _explain_wmap(self) -> dict[str, int]:
        return writers([self._rung_draw_elements(r) for r in self._sim_rungs()])

    def _explain_rung_lines(self, idx: int) -> list[str]:
        rungs = self._sim_rungs()
        rung = rungs[idx]
        rid = str(rung.get("id") or idx)
        return explain_rung(self._rung_draw_elements(rung), rid, idx + 1, len(rungs), rung.get("comment") or "",
                            self._sim_flow, self._sim_energized.get(rid), self._ensure_scan_sim(),
                            self._explain_wmap())

    def _explain_scan(self, result: dict) -> None:
        """Log the rung just scanned (parts mode logs part by part itself); full scans log changed rungs."""
        if not self._explain_open() or self.__dict__.get("_sim_parts") is not None:
            return
        rungs = self._sim_rungs()
        idx = result.get("rung_index")
        if isinstance(idx, int) and 0 <= idx < len(rungs):
            self._explain_log(self._explain_rung_lines(idx) + [""])
            return
        last = self.__dict__.setdefault("_explain_last", {})
        for i, rung in enumerate(rungs):
            rid = str(rung.get("id") or i)
            now = bool(self._sim_energized.get(rid))
            if last.get(rid) != now:
                last[rid] = now
                self._explain_log(self._explain_rung_lines(i) + [""])

    def _explain_blocked(self) -> None:
        if not self._explain_open():
            return
        try:
            from cabinet_studio.services.ladder_sim import sim_blockers

            problems = sim_blockers(self.program, project_name=getattr(self.project, "name", "") or "",
                                    devices=cabinet_device_tags(self.project))
        except Exception as exc:
            problems = [str(exc)]
        self._explain_log(["SIM PAUSED - the program can't run until this is fixed (it resumes by itself):"]
                          + [f"   - {p}" for p in problems or ["an edit left a rung incomplete"]] + [""], "wait")

    def _explain_where(self, why: str) -> None:
        """Pause / blocked: say where the sim stands and which rung is holding things up."""
        if not self._explain_open():
            return
        rungs = self._sim_rungs()
        at = next((i for i, r in enumerate(rungs) if r.get("id") == self._sim_cursor_rung_id), None)
        lines = [f"PAUSED - {why}" + (f" at rung {at + 1}/{len(rungs)}." if at is not None else ".")]
        if self._sim_flow:
            waiting = []
            for i, rung in enumerate(rungs):
                rid = str(rung.get("id") or i)
                if not self._sim_energized.get(rid):
                    order = flow_order(self._rung_draw_elements(rung), lambda j, rid=rid: f"{rid}|L|{j}")
                    waiting.append(f"   Rung {i + 1}: " + rung_summary(order, self._sim_flow, False,
                                                                       self._ensure_scan_sim(), self._explain_wmap()))
            lines += waiting or ["   Every rung is energized."]
        self._explain_log(lines + [""])

    # ------------------------------------------------ v0.3.25 Normal run
    def _sim_auto_prefix(self) -> str:
        auto = self.__dict__.get("_sim_auto")
        if not auto or not auto.get("label"):
            return ""
        return f"[Normal run {auto['i']}/{len(auto['plan'])}: {auto['label']}]  "

    def _sim_auto_start(self) -> None:
        """Reset, then operate the inputs in a normal order, one step per full pass of the rungs."""
        self._show_tab("ladder")
        if not self._sim_rungs():
            self._sim_set_status("Normal run: no rungs to run")
            return
        if self._sim_blocked():
            return
        old = self.__dict__.get("_scan_sim_obj")
        kept = {t: v for t, v in dict(getattr(old, "forces", None) or {}).items() if is_safety_tag(t)}
        self._sim_reset()
        sim = self._ensure_scan_sim()
        for tag, value in kept.items():
            sim.set_force(tag, value)
        plant = PlantModel(list(sim.input_tags()), list(sim.output_tags()))
        plan = normal_run_plan([self._rung_draw_elements(r) for r in self._sim_rungs()], sim.input_tags(),
                               skip=plant.handled)
        if not plan and not plant.handled:
            self._sim_set_status("Normal run: this program reads no inputs to operate. Click parts to switch them.")
            return
        self._sim_plant = plant if plant.handled else None
        self._explain_log(["PRETEND MACHINE: the field reacts to the outputs like a healthy machine."]
                          + ["   " + line for line in plant.describe()]
                          + ["   Safety inputs (E-stop, light curtain, guards) are yours to operate."], "note")
        self._sim_auto = {"plan": plan, "i": 0, "label": "", "t": 0.0}
        if plan:
            self._sim_auto_step()
        self._sim_run()
        self._sim_auto_after = self.after(_SIM_AUTO_POLL_MS, self._sim_auto_tick)

    def _sim_auto_ready(self) -> bool:
        if time.monotonic() - self._sim_auto["t"] < _SIM_AUTO_MIN_STEP_MS / 1000.0:
            return False
        need = len(self._sim_rungs()) if self._sim_rung_mode() else 10
        if self.__dict__.get("_sim_auto_scans", 0) < need or self._sim_parts is not None:
            return False
        sim = self.__dict__.get("_scan_sim_obj")
        return not (sim and any(t.get("tt") for t in sim.timers.values()))

    def _sim_auto_step(self) -> None:
        auto = self._sim_auto
        step = auto["plan"][auto["i"]]
        sim = self._ensure_scan_sim()
        for tag, value in step["set"].items():
            sim.set_force(tag, value)
        auto["i"] += 1
        auto["label"] = step["label"]
        auto["t"] = time.monotonic()
        self.__dict__["_sim_auto_scans"] = 0
        self._sim_operator_changed(f"Normal run step {auto['i']}/{len(auto['plan'])}: {step['label']}.")

    def _sim_auto_tick(self) -> None:
        self._sim_auto_after = None
        if (self._sim_auto is None and self._sim_plant is None) or not self._sim_session:
            self._sim_auto = None
            self._sim_plant = None
            return
        if self._sim_running and self._sim_plant is not None:
            self._sim_plant_step()
        auto = self._sim_auto
        if auto is not None and self._sim_running and self._sim_auto_ready():
            if auto["i"] >= len(auto["plan"]):
                self._sim_auto = None
                self._sim_set_status("Normal run complete - the machine keeps running like a healthy machine. "
                                     "Now test safety: click the E-stop, light curtain or guard inputs. "
                                     "Educational only - not a live PLC.")
                self._explain_log([">> Normal run complete - the machine keeps running. Test safety now."], "event")
                if self._sim_plant is None:
                    return
            else:
                self._sim_auto_step()
        self._sim_auto_after = self.after(_SIM_AUTO_POLL_MS, self._sim_auto_tick)

    def _sim_plant_step(self, now: float | None = None) -> list[tuple[str, bool, str]]:
        plant = self._sim_plant
        if plant is None:
            return []
        sim = self._ensure_scan_sim()
        changes = plant.step(time.monotonic() if now is None else now, sim.read)
        for tag, value, _why in changes:
            sim.set_force(tag, value)
        if changes:
            self._sim_operator_changed("Machine: " + "; ".join(why for _t, _v, why in changes) + ".")
        return changes

    def _sim_auto_cancel(self) -> None:
        if self.__dict__.get("_sim_auto_after") is not None:
            try:
                self.after_cancel(self._sim_auto_after)
            except Exception:
                pass
        self._sim_auto_after = None
        self._sim_auto = None
        self._sim_plant = None

    def _sim_cancel_timer(self) -> None:
        self._sim_parts_finish()
        if self._sim_after is not None:
            try:
                self.after_cancel(self._sim_after)
            except Exception:
                pass
            self._sim_after = None
        timer_after = self.__dict__.get("_sim_timer_after")
        if timer_after is not None:
            try:
                self.after_cancel(timer_after)
            except Exception:
                pass
            self.__dict__["_sim_timer_after"] = None

    def _sim_timer_tick(self) -> None:
        """v0.3.24: while a slow rung-by-rung run is going, keep timers counting in real
        time and update their boxes ten times a second (ACC, time left, bar)."""
        self.__dict__["_sim_timer_after"] = None
        if not self._sim_running or not self._sim_rung_mode():
            return
        sim = self.__dict__.get("_scan_sim_obj")
        if sim is not None:
            sim.clock_ms = time.monotonic() * 1000.0
            if sim.tick_timers():
                self._sim_active_tags |= sim.active_tags()
                self._draw_ladder(preserve_scroll=True)
                self._refresh_force_strip()
            else:
                self._refresh_timer_items()
                n = self.__dict__.get("_sim_timer_ticks", 0) + 1
                self.__dict__["_sim_timer_ticks"] = n
                if n % 3 == 0 and sim.timers:
                    self._refresh_force_strip()
        self.__dict__["_sim_timer_after"] = self.after(_SIM_TIMER_TICK_MS, self._sim_timer_tick)

    def _sim_ensure_timer_tick(self) -> None:
        if self.__dict__.get("_sim_timer_after") is None and self._sim_running and self._sim_rung_mode():
            self.__dict__["_sim_timer_after"] = self.after(_SIM_TIMER_TICK_MS, self._sim_timer_tick)

    def _sim_scan_tick(self) -> None:
        self._sim_after = None
        if not self._sim_running:
            return
        if not self._sim_rungs():
            self._sim_stop()
            return
        if self._sim_blocked():
            # v0.3.20: an edit made the program unrunnable. Nothing scans; the
            # sim waits and resumes by itself once the rung is fixed.
            if self._sim_session:
                self._sim_resume_when_fixed = True
                self._sim_set_status(
                    self._sim_status.cget("text") + "  -- paused; resumes when fixed"
                )
                self._explain_blocked()
                self._sim_after = self.after(_SIM_FIX_POLL_MS, self._sim_fix_watch)
            return
        if getattr(self, "_sim_engine", "scan") == "walk":
            self._sim_apply_rung(flash_cycles=6, then_advance=True)
            return
        sim = self._ensure_scan_sim()
        sim.clock_ms = time.monotonic() * 1000.0
        if self._sim_rung_mode():
            sim.tick_timers()
            result = sim.scan_rung(sim.rung_cursor)
            self._sim_apply_scan_result(result, mode="RUN")
            self._refresh_force_strip()
            delay = self._sim_rung_ms()
            self._sim_ensure_timer_tick()
        else:
            result = sim.scan_once()
            self._sim_apply_scan_result(result, mode="RUN")
            if int(result.get("scan_count") or 0) % 5 == 0:
                self._refresh_force_strip()
            delay = _SIM_SCAN_TICK_MS
        self._sim_after = self.after(delay, self._sim_scan_tick)

    def _sim_fix_watch(self) -> None:
        """Poll while a live edit blocks the sim; resume once the program is runnable."""
        self._sim_after = None
        if not self._sim_resume_when_fixed or not self._sim_session:
            return
        try:
            from cabinet_studio.services.ladder_sim import sim_blockers

            blocked = bool(sim_blockers(
                self.program,
                project_name=getattr(self.project, "name", "") or "",
                devices=cabinet_device_tags(self.project),
            ))
        except Exception:
            blocked = True
        if blocked:
            self._sim_after = self.after(_SIM_FIX_POLL_MS, self._sim_fix_watch)
            return
        self._sim_resume_when_fixed = False
        self._sim_running = True
        self._sim_set_status("Sim resumed - the program is runnable again. Educational only - not a live PLC.")
        self._sim_scan_tick()

    def _sim_collect_tags(self, rung: dict) -> tuple[set[str], set[str]]:
        return simulation_rung_tags(rung)

    def _sim_apply_rung(self, *, flash_cycles: int, then_advance: bool) -> None:
        """Legacy walk fallback (kept for compatibility; scan engine is default)."""
        rungs = self._sim_rungs()
        if not rungs:
            self._sim_stop()
            return
        if self._sim_index < 0 or self._sim_index >= len(rungs):
            self._sim_index = 0
        rung = rungs[self._sim_index]
        self._selected_rung_id = rung.get("id")
        self._sim_active_tags, self._sim_pulse_tags = self._sim_collect_tags(rung)
        coil = (rung.get("coil_tag") or "").strip() or "?"
        comment = (rung.get("comment") or "").strip()
        rung_name = comment.split(".")[0].strip() if comment else coil
        if len(rung_name) > 36:
            rung_name = rung_name[:33] + "..."
        bit = f"Rung {self._sim_index + 1}/{len(rungs)} · {rung_name} → {coil}"
        on_bits: list[str] = []
        for tag in sorted(self._sim_pulse_tags):
            upper = tag.upper().replace("-", "_")
            if upper in {"PLACE_RELAY", "PLACE"} or upper.startswith("PLACE_"):
                on_bits.append("Place ON")
            elif upper in {"WELDER_RELAY", "WELDER"} or "WELDER" in upper:
                on_bits.append("Welder ON")
            else:
                on_bits.append(f"{tag} ON")
        seen: set[str] = set()
        on_bits = [b for b in on_bits if not (b in seen or seen.add(b))]
        on_strip = ("  ·  " + "  ·  ".join(on_bits)) if on_bits else ""
        mode = "RUN" if self._sim_running or then_advance else "STEP"
        self._sim_set_status(f"Sim {mode} (legacy walk): {bit}{on_strip}  · educational only")
        self._sim_flash_count = max(1, flash_cycles)
        self._sim_flash_on = True
        self._draw_ladder(preserve_scroll=True)
        self._sim_cancel_timer()
        self._sim_after = self.after(
            220, lambda adv=then_advance: self._sim_flash_tick(advance_when_done=adv)
        )

    def _sim_flash_tick(self, *, advance_when_done: bool) -> None:
        self._sim_after = None
        self._sim_flash_on = not self._sim_flash_on
        self._sim_flash_count -= 1
        self._draw_ladder(preserve_scroll=True)
        if self._sim_flash_count > 0:
            self._sim_after = self.after(
                180, lambda adv=advance_when_done: self._sim_flash_tick(advance_when_done=adv)
            )
            return
        self._sim_flash_on = True
        self._draw_ladder(preserve_scroll=True)
        if not advance_when_done and not self._sim_running:
            return
        rungs = self._sim_rungs()
        if not rungs:
            self._sim_stop()
            return
        self._sim_index = (self._sim_index + 1) % len(rungs)
        if self._sim_index == 0 and not self._sim_running:
            self._sim_set_status("Sim pass complete (educational — not a live PLC)")
            return
        if self._sim_running or advance_when_done:
            self._sim_after = self.after(
                350, lambda: self._sim_apply_rung(flash_cycles=6, then_advance=self._sim_running)
            )

    def export_plcopen_xml(self) -> None:
        """Export current ladder as PLCopen XML (interchange, not a vendor download)."""
        from pathlib import Path
        from tkinter import filedialog

        self._flush_editor_to_program()
        xml = export_program_to_plcopen_xml(
            self.program,
            project_name=getattr(self.project, "name", "") or "Cabinet",
            devices=cabinet_device_tags(self.project),
        )
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export PLCopen XML",
            defaultextension=".xml",
            filetypes=[("PLCopen XML", "*.xml"), ("All files", "*.*")],
            initialfile=f"{(self.project.name or 'cabinet').replace(' ', '_')}_ladder.xml",
        )
        if not path:
            self.status.configure(text="PLCopen export cancelled.")
            return
        Path(path).write_text(xml, encoding="utf-8")
        self.status.configure(text=f"Exported PLCopen XML → {path}")

    def import_plcopen_xml(self) -> None:
        """Import PLCopen XML into the educational ladder (replaces rungs after confirm)."""
        from pathlib import Path
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            parent=self,
            title="Import PLCopen XML",
            filetypes=[("PLCopen XML", "*.xml"), ("All files", "*.*")],
        )
        if not path:
            self.status.configure(text="PLCopen import cancelled.")
            return
        # v0.3.17: validate + parse + verify FIRST; only a file that would really import
        # reaches the Replace confirm. A refused file never wipes the existing program.
        try:
            xml = Path(path).read_text(encoding="utf-8")
            program, import_warnings = import_plcopen_xml_to_program_checked(xml)
            program = program_from_dict(program)
            program["plc_text"] = format_plc_text(
                program.get("rungs") or [], cabinet_device_tags(self.project)
            )
            program["text_edited"] = False
        except ValueError as exc:
            # v0.3.16 verify-and-refuse: nothing imported, existing program untouched.
            import re as _re

            detail = _re.sub(r"\s*Nothing was imported\.?", "", str(exc)).strip()
            msg = f"PLCopen import REFUSED - nothing was imported. {detail}"
            self.status.configure(text=msg)
            self._show_import_banner(msg, refused=True)
            return
        except Exception as exc:
            msg = f"PLCopen import failed - nothing was imported: {exc}"
            self.status.configure(text=msg)
            self._show_import_banner(msg, refused=True)
            return
        if not self._confirm_replace_program():
            return
        extra = [w for w in import_warnings[1:] if w]
        status = f"Imported PLCopen XML from {Path(path).name}. {PLCOPEN_IMPORT_WARNING}"
        if extra:
            # v0.3.17: per-rung warnings (hint ignored, no left rail …) are loud on the status line.
            status = f"Imported PLCopen XML from {Path(path).name} WITH {len(extra)} WARNING(S): " + " ".join(extra)
        self._apply_built_program(program, status=status)
        self._show_import_banner(" ".join(import_warnings), refused=False)
        self._scan_sim = None
        self._refresh_tag_menus()
        try:
            self._rebuild_force_strip()
        except Exception:
            pass


    def _show_import_banner(self, text: str, *, refused: bool) -> None:
        """v0.3.16: persistent, non-modal PLCopen import warning (stays until next import)."""
        self._last_import_banner = str(text or "")
        try:
            banner = getattr(self, "_import_banner", None)
            if banner is None or not banner.winfo_exists():
                banner = ctk.CTkLabel(
                    self,
                    text="",
                    font=self.fonts.small,
                    text_color=ORANGE,
                    anchor="w",
                    justify="left",
                    wraplength=1100,
                )
                self._import_banner = banner
                try:
                    banner.pack(fill="x", padx=16, pady=(0, 6), before=self._rung_shell)
                except Exception:
                    banner.pack(fill="x", padx=16, pady=(0, 6))
            prefix = "\u26a0 PLCopen import refused: " if refused else "\u26a0 PLCopen import: "
            banner.configure(text=prefix + self._last_import_banner)
        except Exception:
            pass


    # --- v0.3.7 editor tools: copy/paste, verify, tags/X-ref, find/replace ----

    _SHORTCUT_HELP = (
        ("Ctrl+C / Ctrl+V", "Copy selected rung / paste after selection"),
        ("Ctrl+D", "Duplicate selected rung"),
        ("Ctrl+Shift+C / Ctrl+Shift+V", "Copy an instruction / paste it into the selected rung"),
        ("Delete", "Delete selected rung (undoable)"),
        ("↑ / ↓, Home / End", "Select previous / next, first / last rung"),
        ("Ctrl+↑ / Ctrl+↓", "Move selected rung up / down"),
        ("Ctrl+Z / Ctrl+Y", "Undo / redo"),
        ("Ctrl+F / Ctrl+H", "Find tag / find & replace"),
        ("Ctrl+T", "Tag list + where-used cross-reference"),
        ("Ctrl+E", "Edit rung comment & instruction notes"),
        ("F7", "Verify (error check)"),
        ("F5 / Shift+F5 / F10", "Simulate run-stop / stop / step one scan"),
        ("F6 / F9", "Step one rung / pause the sim"),
        ("Click / right-click (simulating)", "Switch a contact or coil on-off; reset a timer or counter / release a force"),
        ("F1", "This list"),
    )

    def _selected_or_last_rung_id(self) -> str | None:
        rungs = self.program.get("rungs") or []
        ids = [r["id"] for r in rungs]
        if self._selected_rung_id in ids:
            return self._selected_rung_id
        return ids[-1] if ids else None

    def _apply_tool_edit(self, program: dict, status: str, *, select: str | None = None) -> None:
        """Shared tail for copy/paste/move/replace edits (undoable, live redraw)."""
        self.program = refresh_plc_text(program, self.project)
        self.program["text_edited"] = True
        if select:
            self._selected_rung_id = select
        self._scan_sim = None
        self._refresh_tag_menus()
        self._show_tab("ladder")
        self._commit(status=status)
        if self._sim_running:
            try:
                self._rebuild_force_strip()
            except Exception:
                pass

    def _set_ladder_clip(self, clip: dict) -> None:
        self._ladder_clip = clip
        try:
            self.clipboard_clear()
            self.clipboard_append(clip_to_text(clip))
        except Exception:
            pass

    def _get_ladder_clip(self, kind: str) -> dict | None:
        clip = None
        try:
            clip = clip_from_text(self.clipboard_get())
        except Exception:
            clip = None
        if clip is None or clip.get("kind") != kind:
            local = self._ladder_clip
            clip = local if isinstance(local, dict) and local.get("kind") == kind else None
        return clip

    def _copy_rung(self) -> None:
        rid = self._selected_or_last_rung_id()
        if not rid:
            self.status.configure(text="No rung to copy.")
            self._mirror_status()
            return
        self._set_ladder_clip(copy_rungs(self.program, [rid]))
        index = [r["id"] for r in self.program["rungs"]].index(rid) + 1
        self.status.configure(text=f"Copied rung {index}. Ctrl+V pastes it after the selected rung.")
        self._mirror_status()

    def _paste_rung(self) -> None:
        clip = self._get_ladder_clip("rungs")
        if clip is None:
            self.status.configure(text="Nothing to paste — Copy rung first (Ctrl+C).")
            self._mirror_status()
            return
        try:
            program, new_ids = paste_rungs(self.program, clip, after_id=self._selected_or_last_rung_id())
        except ValueError as exc:
            self.status.configure(text=str(exc))
            self._mirror_status()
            return
        n = len(new_ids)
        self._apply_tool_edit(program, f"Pasted {n} rung{'s' if n != 1 else ''}.", select=new_ids[-1])

    def _duplicate_rung(self) -> None:
        rid = self._selected_or_last_rung_id()
        if not rid:
            self.status.configure(text="No rung to duplicate.")
            self._mirror_status()
            return
        program, new_id = duplicate_rung(self.program, rid)
        self._apply_tool_edit(program, "Duplicated rung (check one-shot storage bits / timer names — Verify F7).", select=new_id)

    def _move_rung(self, delta: int) -> None:
        rid = self._selected_or_last_rung_id()
        if not rid:
            return
        ids = [r["id"] for r in self.program["rungs"]]
        i = ids.index(rid)
        j = max(0, min(len(ids) - 1, i + delta))
        if i == j:
            self.status.configure(text="Rung is already at the " + ("top." if delta < 0 else "bottom."))
            self._mirror_status()
            return
        self._apply_tool_edit(move_rung(self.program, rid, delta), f"Moved rung {i + 1} → {j + 1}.", select=rid)

    def _move_rung_up(self) -> None:
        self._move_rung(-1)

    def _move_rung_down(self) -> None:
        self._move_rung(1)

    def _copy_instruction(self) -> None:
        """Pick one instruction on the selected rung to copy (small non-modal chooser)."""
        rid = self._selected_or_last_rung_id()
        if not rid:
            self.status.configure(text="Add a rung first, then Copy instr….")
            self._mirror_status()
            return
        rung = next(r for r in self.program["rungs"] if r["id"] == rid)
        items = rung_instruction_list(rung)
        win, fresh = self._tool_window("copy_instr", "Copy instruction", "420x360")
        if not fresh:
            self._clear_children(win)
        index = [r["id"] for r in self.program["rungs"]].index(rid) + 1
        section_label(win, f"RUNG {index} — PICK AN INSTRUCTION TO COPY", self.fonts.tiny).pack(anchor="w", padx=12, pady=(10, 4))
        body = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._copy_instr_buttons = []
        for path, label, _note in items:
            b = ghost_button(body, label, lambda p=path, l=label: self._copy_instruction_path(rid, p, l), self.fonts.small, width=360)
            b.pack(fill="x", pady=2)
            self._copy_instr_buttons.append(b)
        ghost_button(win, "Cancel", lambda: self._close_tool_window("copy_instr"), self.fonts.small, width=90).pack(
            side="right", padx=12, pady=(0, 10)
        )

    def _copy_instruction_path(self, rung_id: str, path: tuple, label: str = "") -> None:
        try:
            clip = copy_instruction(self.program, rung_id, path)
        except (KeyError, ValueError) as exc:
            self.status.configure(text=str(exc))
            self._mirror_status()
            return
        self._set_ladder_clip(clip)
        self._close_tool_window("copy_instr")
        self.status.configure(text=f"Copied instruction {label}. Select a rung, then Paste instr (Ctrl+Shift+V).")
        self._mirror_status()

    def _paste_instruction(self) -> None:
        clip = self._get_ladder_clip("instruction")
        rid = self._selected_or_last_rung_id()
        if clip is None or not rid:
            self.status.configure(text="Nothing to paste — Copy instr… first (and select a rung).")
            self._mirror_status()
            return
        try:
            program = paste_instruction(self.program, clip, rid)
        except (KeyError, ValueError) as exc:
            self.status.configure(text=str(exc))
            self._mirror_status()
            return
        self._apply_tool_edit(program, "Pasted instruction into the selected rung.", select=rid)

    # ------------------------------------------------ v0.3.29 drag instructions between rungs
    def _rung_at(self, x: float, y: float) -> str | None:
        for rung_id, x0, y0, x1, y1 in self._rung_hitboxes:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return rung_id
        return None

    def _rung_targets(self, rung_id: str) -> list[tuple[float, str]]:
        """(center x, tag) of the drawn instructions inside one rung, left to right."""
        box = next((b for b in self._rung_hitboxes if b[0] == rung_id), None)
        if box is None:
            return []
        _rid, rx0, ry0, rx1, ry1 = box
        out = []
        for x0, y0, x1, y1, _kind, tag in self._click_targets:
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            if rx0 <= cx <= rx1 and ry0 <= cy <= ry1:
                out.append((cx, tag))
        return sorted(out)

    def _ladder_drag_press(self, event) -> None:
        self._ladder_drag = None
        if self._sim_session:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        hit = self._click_target_at(x, y)
        rid = self._rung_at(x, y)
        if hit is None or rid is None:
            return
        tag = hit[1]
        same = [cx for cx, t in self._rung_targets(rid) if t == tag]
        nth = min(range(len(same)), key=lambda i: abs(same[i] - x)) if same else 0
        self._ladder_drag = {"tag": tag, "rung": rid, "nth": nth, "x": x, "y": y, "ghost": None}

    def _ladder_drag_motion(self, event) -> None:
        d = getattr(self, "_ladder_drag", None)
        if not d:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if d["ghost"] is None and abs(x - d["x"]) + abs(y - d["y"]) < 8:
            return
        if d["ghost"] is not None:
            self.canvas.delete(d["ghost"])
        d["ghost"] = self.canvas.create_rectangle(x - 26, y - 14, x + 26, y + 14, outline="#2f6bff", width=2, dash=(4, 3))

    def _ladder_drag_release(self, event) -> None:
        d, self._ladder_drag = getattr(self, "_ladder_drag", None), None
        if not d or d["ghost"] is None:
            return
        self.canvas.delete(d["ghost"])
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        dst = self._rung_at(x, y)
        if dst is None:
            self.status.configure(text=f"Drop {d['tag']} onto a rung to move it there.")
            self._mirror_status()
            return
        self.drag_instruction(d["rung"], d["tag"], d["nth"], dst, x)

    def drag_instruction(self, src_rung_id: str, tag: str, nth: int, dst_rung_id: str, drop_x: float) -> bool:
        """Move an instruction to where it was dropped; the rung re-connects in series.
        Refused (nothing changes) if the move would add verify errors."""
        rungs = {r["id"]: r for r in self.program.get("rungs") or []}
        if dst_rung_id not in rungs:
            return False
        drawn = list(self._rung_targets(dst_rung_id))
        position = 0
        for el in program_rung_to_elements(rungs[dst_rung_id]):
            el_tag = element_tag(el)
            hit = next((i for i, (_cx, t) in enumerate(drawn) if t == el_tag), None) if el_tag else None
            if hit is not None:
                cx, _t = drawn.pop(hit)
                if cx > drop_x:
                    break
            position += 1
        try:
            program = move_instruction(self.program, src_rung_id, tag, nth, dst_rung_id, position)
        except (KeyError, ValueError) as exc:
            self.status.configure(text=f"Not moved: {exc}")
            self._mirror_status()
            return False
        devices = cabinet_device_tags(self.project)

        def errors(prog) -> int:
            return sum(1 for i in verify_program(prog, devices) if i.get("severity") == "error")

        if errors(program) > errors(self.program):
            self.status.configure(text=f"Not moved: putting {tag} there would break the program (Verify finds "
                                       "new errors). Nothing changed.")
            self._mirror_status()
            return False
        where = "along its rung" if src_rung_id == dst_rung_id else "to the rung you dropped it on"
        self._apply_tool_edit(program, f"Moved {tag} {where} - the rung re-connected in series. "
                                       "Ctrl+Z undoes it.", select=dst_rung_id)
        return True

    # ------------------------------------------------ v0.3.31 edit one instruction in place
    def _instr_at(self, x: float, y: float) -> tuple[str, str, str, int] | None:
        """(rung id, kind, tag, nth same-tag instruction in that rung) under the pointer."""
        rid = self._rung_at(x, y)
        if rid is None:
            return None
        box = next(b for b in self._rung_hitboxes if b[0] == rid)
        hit = None
        same = []
        for t in self._click_targets:
            x0, y0, x1, y1, kind, tag = t
            if not tag or tag == "?" or not (box[1] <= (x0 + x1) / 2 <= box[3] and box[2] <= (y0 + y1) / 2 <= box[4]):
                continue
            if x0 <= x <= x1 and y0 <= y <= y1:
                hit = t
        if hit is None:
            return None
        same = sorted((t for t in self._click_targets if t[5] == hit[5]
                       and box[1] <= (t[0] + t[2]) / 2 <= box[3] and box[2] <= (t[1] + t[3]) / 2 <= box[4]),
                      key=lambda t: (t[0], t[1]))
        return rid, hit[4], hit[5], same.index(hit)

    def _editor_contact(self) -> dict | None:
        tag = (self.contact_var.get() or "").strip()
        if not tag or tag.startswith("("):
            return None
        return {"kind": "contact", "var": tag, "form": "NC" if self.nc_var.get() == "NC" else "NO"}

    def _editor_coil(self) -> dict | None:
        tag = (self.coil_var.get() or "").strip()
        if not tag or tag.startswith("("):
            return None
        return {"kind": "coil", "var": tag, "form": "normal"}

    def _instr_edit(self, verb: str, target: tuple[str, str, str, int] | None, new_el: dict | None = None,
                    *, after: bool = False) -> bool:
        if target is None:
            self.status.configure(text="Click an instruction on the ladder first, or right-click it.")
            self._mirror_status()
            return False
        rid, _kind, tag, nth = target
        try:
            if verb == "delete":
                program = delete_instruction(self.program, rid, tag, nth)
                msg = f"Deleted {tag} from the rung - the rung re-connected. Ctrl+Z undoes it."
            elif new_el is None:
                raise ValueError("Pick the new Contact or Coil in the rung editor first.")
            elif verb == "replace":
                program = replace_instruction(self.program, rid, tag, nth, new_el)
                msg = f"Replaced {tag} with {new_el['var']} in the same spot."
            else:
                program = insert_instruction(self.program, rid, tag, nth, new_el, after=after)
                msg = f"Added {new_el['var']} {'after' if after else 'before'} {tag}."
        except (KeyError, ValueError) as exc:
            self.status.configure(text=f"Not changed: {exc}")
            self._mirror_status()
            return False
        self._selected_instr = None
        self._apply_tool_edit(program, msg, select=rid)
        return True

    def _toggle_contact_form(self, target) -> bool:
        rid, _kind, tag, nth = target
        rung = next(r for r in self.program.get("rungs") or [] if r["id"] == rid)
        from cabinet_studio.services.ladder_tools import _instruction_slot

        els = program_rung_to_elements(rung)
        items, i, _chain = _instruction_slot(els, tag, nth)
        el = dict(items[i])
        el["form"] = "NO" if str(el.get("form") or "NO").upper() == "NC" else "NC"
        return self._instr_edit("replace", target, el)

    def _instr_menu(self, target) -> tk.Menu:
        rid, kind, tag, _nth = target
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=f"Delete {tag}", command=lambda: self._instr_edit("delete", target))
        contact, coil = self._editor_contact(), self._editor_coil()
        if kind == "contact":
            menu.add_command(label="Change NO / NC", command=lambda: self._toggle_contact_form(target))
            menu.add_command(label=f"Replace with contact {contact['var'] if contact else '(pick in editor)'}",
                             command=lambda: self._instr_edit("replace", target, self._editor_contact()))
        if kind == "coil":
            menu.add_command(label=f"Replace with coil {coil['var'] if coil else '(pick in editor)'}",
                             command=lambda: self._instr_edit("replace", target, self._editor_coil()))
        name = contact["var"] if contact else "(pick in editor)"
        menu.add_command(label=f"Add contact {name} before",
                         command=lambda: self._instr_edit("insert", target, self._editor_contact()))
        if kind == "contact":
            menu.add_command(label=f"Add contact {name} after",
                             command=lambda: self._instr_edit("insert", target, self._editor_contact(), after=True))
        return menu

    def _delete_selected_instr(self) -> None:
        self._instr_edit("delete", self.__dict__.get("_selected_instr"))

    def _replace_selected_instr(self) -> None:
        target = self.__dict__.get("_selected_instr")
        new_el = self._editor_coil() if target and target[1] == "coil" else self._editor_contact()
        self._instr_edit("replace", target, new_el)

    def _select_rung_offset(self, delta: int) -> None:
        ids = [r["id"] for r in self.program.get("rungs") or []]
        if not ids:
            return
        cur = ids.index(self._selected_rung_id) if self._selected_rung_id in ids else (len(ids) if delta < 0 else -1)
        nxt = max(0, min(len(ids) - 1, cur + delta))
        self._select_rung(ids[nxt])

    def _select_rung_edge(self, *, first: bool) -> None:
        ids = [r["id"] for r in self.program.get("rungs") or []]
        if ids:
            self._select_rung(ids[0] if first else ids[-1])

    def _select_rung(self, rung_id: str, *, status: str | None = None) -> None:
        ids = [r["id"] for r in self.program.get("rungs") or []]
        if rung_id not in ids:
            return
        self._selected_rung_id = rung_id
        self._draw_ladder(preserve_scroll=True)
        self._scroll_to_rung(rung_id)
        self.status.configure(text=status or f"Selected rung {ids.index(rung_id) + 1} of {len(ids)}.")
        self._mirror_status()

    def _scroll_to_rung(self, rung_id: str) -> None:
        try:
            region = [float(v) for v in str(self.canvas.cget("scrollregion")).split()]
            total = region[3] - region[1] if len(region) == 4 else 0
        except Exception:
            total = 0
        if total <= 0:
            return
        for rid, _x0, y0, _x1, y1 in self._rung_hitboxes:
            if rid != rung_id:
                continue
            top, bottom = self.canvas.canvasy(0), self.canvas.canvasy(self.canvas.winfo_height())
            if y0 < top or y1 > bottom:
                try:
                    self.canvas.yview_moveto(max(0.0, (y0 - 24 - region[1]) / total))
                except Exception:
                    pass
            return

    # Tool windows (non-modal, no grab — work in the ladder while they stay open)

    def _tool_window(self, key: str, title: str, geometry: str):
        win = self._tool_windows.get(key)
        try:
            if win is not None and win.winfo_exists():
                win.deiconify()
                win.lift()
                return win, False
        except Exception:
            pass
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title(f"{title} - {self.project.name}")
        win.geometry(geometry)
        try:
            win.transient(self._rung_editor_owner())
        except Exception:
            pass
        win.protocol("WM_DELETE_WINDOW", lambda k=key: self._close_tool_window(k))
        win.bind("<Escape>", lambda _e=None, k=key: self._close_tool_window(k))
        self._bind_edit_shortcuts(win)
        self._tool_windows[key] = win
        return win, True

    def _tool_window_open(self, key: str) -> bool:
        win = self._tool_windows.get(key)
        try:
            return bool(win is not None and win.winfo_exists())
        except Exception:
            return False

    def _close_tool_window(self, key: str) -> None:
        win = self._tool_windows.pop(key, None)
        if key == "verify":
            self._verify_list = None
            self._verify_summary_lbl = None
        elif key == "tags":
            self._tag_rows_frame = self._tag_xref_frame = self._tag_xref_label = self._tag_count_lbl = None
        elif key == "find":
            self._find_results = None
            self._find_result_lbl = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def _close_all_tool_windows(self) -> None:
        for key in list(getattr(self, "_tool_windows", {}) or {}):
            self._close_tool_window(key)

    def _refresh_open_tool_panels(self) -> None:
        if not hasattr(self, "_tool_windows"):
            return
        if self._tool_window_open("verify"):
            self._refresh_verify_panel(set_status=False)
        if self._tool_window_open("tags"):
            self._refresh_tag_xref()

    def _goto_ref(self, rung_id: str, text: str = "", path: tuple | list | None = None) -> None:
        self._show_tab("ladder")
        self._highlight_rung_id = rung_id or None
        self._highlight_path = tuple(path) if path else None
        self._select_rung(rung_id, status=text or None)
        self._draw_ladder(preserve_scroll=True)
        # Scroll the highlighted rung into view.
        for rid, _x0, y0, _x1, y1 in self._rung_hitboxes:
            if rid == rung_id:
                try:
                    bbox = self.canvas.bbox("all") or (0, 0, 1, 1)
                    total = max(1, bbox[3])
                    self.canvas.yview_moveto(max(0.0, (y0 - 40) / total))
                except Exception:
                    pass
                break

    # Verify panel

    def _run_verify(self) -> list[dict]:
        self._verify_issues = verify_program(self.program, cabinet_device_tags(self.project))
        return self._verify_issues

    def _open_verify_panel(self) -> None:
        win, fresh = self._tool_window("verify", "Verify", "820x420")
        if fresh:
            top = ctk.CTkFrame(win, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4))
            section_label(top, "VERIFY — EDUCATIONAL ERROR CHECK", self.fonts.tiny).pack(side="left")
            ghost_button(top, "Close", lambda: self._close_tool_window("verify"), self.fonts.small, width=80).pack(side="right", padx=4)
            ghost_button(top, "Re-verify", self._refresh_verify_panel, self.fonts.small, width=100).pack(side="right", padx=4)
            self._verify_summary_lbl = ctk.CTkLabel(win, text="", font=self.fonts.small, text_color=TEXT, anchor="w")
            self._verify_summary_lbl.pack(fill="x", padx=14)
            self._verify_list = ctk.CTkScrollableFrame(win, fg_color=PANEL)
            self._verify_list.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self._refresh_verify_panel()

    def _refresh_verify_panel(self, set_status: bool = True) -> None:
        issues = self._run_verify()
        summary = verify_summary(issues)
        if set_status:
            self.status.configure(text=summary)
            self._mirror_status()
        if self._verify_summary_lbl is None or self._verify_list is None:
            return
        try:
            self._verify_summary_lbl.configure(text=summary + "   (click a line to jump to the rung)")
            self._clear_children(self._verify_list)
        except Exception:
            return
        colors = {
            "error": (PALETTE["ERROR_ROW"], PALETTE["ERROR_ROW_HOVER"]),
            "warning": (PALETTE["WARNING_ROW"], PALETTE["WARNING_ROW_HOVER"]),
            "info": (ENTRY, HOVER),
        }
        if not issues:
            ctk.CTkLabel(self._verify_list, text="No issues found.", font=self.fonts.small, text_color=MUTED).pack(anchor="w", padx=8, pady=6)
        for issue in issues[:300]:
            fg, hover = colors.get(issue["severity"], colors["info"])
            where = f"R{issue['rung_index']}  " if issue["rung_index"] else ""
            row = ctk.CTkFrame(self._verify_list, fg_color="transparent")
            row.pack(fill="x", padx=2, pady=1)
            ctk.CTkButton(
                row,
                text=f"{issue['severity'].upper():8} {where}{issue['message']}",
                anchor="w", font=self.fonts.tiny, height=26, fg_color=fg, hover_color=hover, text_color=TEXT,
                command=(lambda i=issue: self._goto_ref(
                    i["rung_id"], f"{i['code']}: {i['message']}", path=i.get("path") or ()))
                if issue["rung_id"] else (lambda i=issue: self.status.configure(text=i["message"])),
            ).pack(side="left", fill="x", expand=True)
            if issue.get("fix"):
                ghost_button(row, "Fix", lambda i=issue: self._apply_issue_fix(i), self.fonts.tiny, width=50).pack(side="right", padx=2)

    # Tag list + cross-reference

    def _open_tag_list(self) -> None:
        win, fresh = self._tool_window("tags", "Tags & cross-reference", "980x620")
        if fresh:
            top = ctk.CTkFrame(win, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4))
            section_label(top, "TAG DATABASE", self.fonts.tiny).pack(side="left", padx=(0, 8))
            self._tag_filter_var = ctk.StringVar(master=win, value="")
            filt = ctk.CTkEntry(top, textvariable=self._tag_filter_var, width=180, font=self.fonts.tiny,
                                placeholder_text="filter tags…", fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            filt.pack(side="left", padx=4)
            filt.bind("<KeyRelease>", lambda _e: self._refresh_tag_list())
            ghost_button(top, "Refresh", self._refresh_tag_list, self.fonts.tiny, width=80).pack(side="left", padx=4)
            self._tag_count_lbl = ctk.CTkLabel(top, text="", font=self.fonts.tiny, text_color=MUTED)
            self._tag_count_lbl.pack(side="left", padx=8)
            ghost_button(top, "Close", lambda: self._close_tool_window("tags"), self.fonts.tiny, width=70).pack(side="right", padx=4)
            add = ctk.CTkFrame(win, fg_color="transparent")
            add.pack(fill="x", padx=12, pady=(0, 4))
            ctk.CTkLabel(add, text="New / describe tag", font=self.fonts.tiny, text_color=MUTED).pack(side="left", padx=(0, 4))
            self._new_tag_name = ctk.CTkEntry(add, width=140, font=self.fonts.tiny, placeholder_text="tag",
                                              fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            self._new_tag_name.pack(side="left", padx=2)
            self._new_tag_desc = ctk.CTkEntry(add, width=360, font=self.fonts.tiny, placeholder_text="description",
                                              fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            self._new_tag_desc.pack(side="left", padx=2)
            ghost_button(add, "Add / set", self._add_tag_description, self.fonts.tiny, width=80).pack(side="left", padx=4)
            ctk.CTkLabel(add, text="Alias → base", font=self.fonts.tiny, text_color=MUTED).pack(side="left", padx=(12, 4))
            self._new_alias_name = ctk.CTkEntry(add, width=100, font=self.fonts.tiny, placeholder_text="alias",
                                                fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            self._new_alias_name.pack(side="left", padx=2)
            self._new_alias_base = ctk.CTkEntry(add, width=120, font=self.fonts.tiny, placeholder_text="base tag",
                                                fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            self._new_alias_base.pack(side="left", padx=2)
            ghost_button(add, "Set alias", self._add_tag_alias, self.fonts.tiny, width=80).pack(side="left", padx=4)
            hdr = ctk.CTkFrame(win, fg_color="transparent")
            hdr.pack(fill="x", padx=16)
            for text, w in (("Tag", 130), ("Class", 64), ("Type", 60), ("Alias of", 90), ("Address", 70), ("Description (Enter to save)", 280), ("Used", 70)):
                ctk.CTkLabel(hdr, text=text, width=w, anchor="w", font=self.fonts.tiny, text_color=MUTED).pack(side="left", padx=2)
            self._tag_rows_frame = ctk.CTkScrollableFrame(win, fg_color=PANEL, height=300)
            self._tag_rows_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))
            self._tag_xref_label = ctk.CTkLabel(win, text="WHERE USED — click Used on a tag", font=self.fonts.tiny,
                                                text_color=MUTED, anchor="w")
            self._tag_xref_label.pack(fill="x", padx=14)
            self._tag_xref_frame = ctk.CTkScrollableFrame(win, fg_color=PANEL, height=130)
            self._tag_xref_frame.pack(fill="x", padx=12, pady=(0, 12))
            self._tag_xref_tag = ""
        self._refresh_tag_list()

    def _tag_rows(self) -> list[dict]:
        return tag_table(self.program, cabinet_device_tags(self.project))

    def _refresh_tag_list(self) -> None:
        frame = self._tag_rows_frame
        if frame is None:
            return
        rows = self._tag_rows()
        q = (self._tag_filter_var.get() if self._tag_filter_var is not None else "").strip().lower()
        shown = [r for r in rows if not q or q in r["name"].lower() or q in (r["description"] or "").lower()]
        try:
            self._clear_children(frame)
        except Exception:
            return
        self._tag_desc_entries: dict[str, ctk.CTkEntry] = {}
        for r in shown[:400]:
            line = ctk.CTkFrame(frame, fg_color="transparent")
            line.pack(fill="x", pady=1)
            for text, w in ((r["name"], 130), (r["class"], 64), (r["type"], 60), (r.get("alias_of") or "", 90), (r["address"], 70)):
                ctk.CTkLabel(line, text=text, width=w, anchor="w", font=self.fonts.tiny, text_color=TEXT).pack(side="left", padx=2)
            ent = ctk.CTkEntry(line, width=280, font=self.fonts.tiny, fg_color=ENTRY, border_color=BORDER, text_color=TEXT,
                               placeholder_text=r["device_description"] or "description")
            ent.pack(side="left", padx=2)
            if r["user_description"]:
                ent.insert(0, r["user_description"])
            ent.bind("<Return>", lambda _e, n=r["name"], e=ent: self._save_tag_entry(n, e))
            ent.bind("<FocusOut>", lambda _e, n=r["name"], e=ent: self._save_tag_entry(n, e))
            self._tag_desc_entries[r["name"]] = ent
            ghost_button(line, f"{r['uses']} use{'s' if r['uses'] != 1 else ''}", lambda n=r["name"]: self._show_tag_xref(n),
                         self.fonts.tiny, width=80).pack(side="left", padx=2)
        if self._tag_count_lbl is not None:
            extra = f" (showing {min(len(shown), 400)})" if len(shown) != len(rows) or len(shown) > 400 else ""
            self._tag_count_lbl.configure(text=f"{len(rows)} tags{extra}")
        self._refresh_tag_xref()

    def _save_tag_entry(self, tag: str, entry) -> None:
        try:
            if not entry.winfo_exists():
                return
            text = entry.get()
        except Exception:
            return
        self._save_tag_description(tag, text)

    def _save_tag_description(self, tag: str, text: str) -> None:
        current = (self.program.get("tag_descriptions") or {}).get(tag, "")
        if " ".join((text or "").split()) == current:
            return
        try:
            program = set_tag_description(self.program, tag, text)
        except ValueError as exc:
            self.status.configure(text=str(exc))
            return
        self.program = program
        self._commit(status=f"Description saved for {tag}." if (text or "").strip() else f"Description cleared for {tag}.")

    def _add_tag_description(self) -> None:
        name = (self._new_tag_name.get() or "").strip()
        desc = (self._new_tag_desc.get() or "").strip()
        if not name or " " in name:
            self.status.configure(text="Enter a tag name (no spaces) and a description.")
            return
        self._save_tag_description(name, desc)
        try:
            self._new_tag_name.delete(0, "end")
            self._new_tag_desc.delete(0, "end")
        except Exception:
            pass
        self._refresh_tag_list()

    def _show_tag_xref(self, tag: str) -> None:
        self._tag_xref_tag = tag
        self._refresh_tag_xref()

    def _refresh_tag_xref(self) -> None:
        frame = self._tag_xref_frame
        tag = getattr(self, "_tag_xref_tag", "")
        if frame is None or not tag:
            return
        refs = cross_reference(self.program, tag)
        try:
            self._clear_children(frame)
            self._tag_xref_label.configure(text=f"WHERE USED — {tag}: {len(refs)} reference(s)")
        except Exception:
            return
        if not refs:
            ctk.CTkLabel(frame, text="Not used in any rung.", font=self.fonts.tiny, text_color=MUTED).pack(anchor="w", padx=6)
        for ref in refs:
            ghost_button(
                frame, f"Rung {ref['rung_index']}:  {ref['label']}   ({ref['access']})",
                lambda r=ref: self._goto_ref(r["rung_id"], f"{r['tag']} — rung {r['rung_index']}: {r['label']}"),
                self.fonts.tiny, width=520,
            ).pack(anchor="w", pady=1)

    # Find / replace

    def _open_find_replace(self, focus_replace: bool = False) -> None:
        win, fresh = self._tool_window("find", "Find / Replace tags", "720x460")
        if fresh:
            grid = ctk.CTkFrame(win, fg_color="transparent")
            grid.pack(fill="x", padx=12, pady=(12, 4))
            ctk.CTkLabel(grid, text="Find tag", font=self.fonts.tiny, text_color=MUTED, width=80, anchor="w").grid(row=0, column=0, sticky="w")
            self._find_entry = ctk.CTkEntry(grid, width=220, font=self.fonts.small, fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            self._find_entry.grid(row=0, column=1, padx=4, pady=2)
            ctk.CTkLabel(grid, text="Replace with", font=self.fonts.tiny, text_color=MUTED, width=80, anchor="w").grid(row=1, column=0, sticky="w")
            self._replace_entry = ctk.CTkEntry(grid, width=220, font=self.fonts.small, fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            self._replace_entry.grid(row=1, column=1, padx=4, pady=2)
            self._find_case_var = tk.BooleanVar(master=win, value=False)
            self._find_whole_var = tk.BooleanVar(master=win, value=True)
            ctk.CTkCheckBox(grid, text="Match case", variable=self._find_case_var, font=self.fonts.tiny, text_color=TEXT,
                            checkbox_width=18, checkbox_height=18).grid(row=0, column=2, padx=8, sticky="w")
            ctk.CTkCheckBox(grid, text="Whole tag (T1 also finds T1.DN)", variable=self._find_whole_var, font=self.fonts.tiny,
                            text_color=TEXT, checkbox_width=18, checkbox_height=18).grid(row=1, column=2, padx=8, sticky="w")
            btns = ctk.CTkFrame(win, fg_color="transparent")
            btns.pack(fill="x", padx=12, pady=4)
            primary_button(btns, "Find all", self._find_all, self.fonts.small, width=100).pack(side="left", padx=4)
            ghost_button(btns, "Replace all", lambda: self._replace_tags(selected_only=False), self.fonts.small, width=110).pack(side="left", padx=4)
            ghost_button(btns, "Replace in selected rung", lambda: self._replace_tags(selected_only=True), self.fonts.small, width=180).pack(side="left", padx=4)
            ghost_button(btns, "Close", lambda: self._close_tool_window("find"), self.fonts.small, width=80).pack(side="right", padx=4)
            self._find_result_lbl = ctk.CTkLabel(win, text="", font=self.fonts.tiny, text_color=MUTED, anchor="w")
            self._find_result_lbl.pack(fill="x", padx=14)
            self._find_results = ctk.CTkScrollableFrame(win, fg_color=PANEL)
            self._find_results.pack(fill="both", expand=True, padx=12, pady=(2, 12))
            self._find_entry.bind("<Return>", lambda _e: self._find_all())
            self._replace_entry.bind("<Return>", lambda _e: self._replace_tags(selected_only=False))
            pick = self._picked(self.contact_var) if hasattr(self, "contact_var") else ""
            if pick:
                self._find_entry.insert(0, pick)
        target = self._replace_entry if focus_replace else self._find_entry
        try:
            win.after(40, target.focus_set)
        except Exception:
            pass

    def _find_all(self) -> list[dict]:
        if self._find_results is None:
            return []
        query = (self._find_entry.get() or "").strip()
        refs = find_tag_refs(self.program, query, match_case=bool(self._find_case_var.get()),
                             whole=bool(self._find_whole_var.get())) if query else []
        try:
            self._clear_children(self._find_results)
            self._find_result_lbl.configure(text=f"{len(refs)} match(es) for “{query}”" if query else "Type a tag to find.")
        except Exception:
            return refs
        for ref in refs[:300]:
            ghost_button(
                self._find_results, f"Rung {ref['rung_index']}:  {ref['label']}   [{ref['tag']}]",
                lambda r=ref: self._goto_ref(r["rung_id"], f"Found {r['tag']} — rung {r['rung_index']}: {r['label']}"),
                self.fonts.tiny, width=560,
            ).pack(anchor="w", pady=1)
        self.status.configure(text=f"Find: {len(refs)} match(es) for {query}." if query else "Find: enter a tag.")
        self._mirror_status()
        return refs

    def _replace_tags(self, *, selected_only: bool) -> int:
        if self._find_results is None:
            return 0
        old = (self._find_entry.get() or "").strip()
        new = (self._replace_entry.get() or "").strip()
        rid = self._selected_or_last_rung_id() if selected_only else None
        if selected_only and not rid:
            self.status.configure(text="Select a rung first.")
            return 0
        try:
            program, count = replace_tag(self.program, old, new, match_case=bool(self._find_case_var.get()),
                                         rung_ids=[rid] if rid else None)
        except ValueError as exc:
            self.status.configure(text=str(exc))
            self._find_result_lbl.configure(text=str(exc))
            self._mirror_status()
            return 0
        if not count:
            self._find_result_lbl.configure(text=f"No references of “{old}” to replace.")
            self.status.configure(text=f"Replace: no references of {old}.")
            self._mirror_status()
            return 0
        scope = "selected rung" if selected_only else "program"
        self._apply_tool_edit(program, f"Replaced {count} reference(s) of {old} → {new} in the {scope}.", select=self._selected_rung_id)
        try:
            self._find_entry.delete(0, "end")
            self._find_entry.insert(0, new)
        except Exception:
            pass
        self._find_all()
        self.status.configure(text=f"Replaced {count} reference(s) of {old} → {new} in the {scope}. Undo with Ctrl+Z.")
        self._mirror_status()
        return count

    def _show_shortcuts(self) -> None:
        win, fresh = self._tool_window("shortcuts", "Keyboard shortcuts", "560x440")
        if not fresh:
            return
        section_label(win, "KEYBOARD SHORTCUTS (ladder focus — not while typing)", self.fonts.tiny).pack(anchor="w", padx=12, pady=(10, 6))
        body = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        for keys, what in self._SHORTCUT_HELP:
            line = ctk.CTkFrame(body, fg_color="transparent")
            line.pack(fill="x", pady=1)
            ctk.CTkLabel(line, text=keys, width=200, anchor="w", font=self.fonts.mono_small, text_color=CYAN).pack(side="left", padx=4)
            ctk.CTkLabel(line, text=what, anchor="w", font=self.fonts.tiny, text_color=TEXT).pack(side="left", padx=4)
        ghost_button(win, "Close", lambda: self._close_tool_window("shortcuts"), self.fonts.small, width=90).pack(side="right", padx=12, pady=(0, 10))


    # --- v0.3.8 JSR / SBR / RET, watch/trend, verify fixes, aliases -------------

    def _add_jsr_rung(self) -> None:
        target = (self._rung_field_vars.get("jsr_target").get() if self._rung_field_vars.get("jsr_target") else "Motor").strip()
        contact = self._picked(self.contact_var) or "PB_Start"
        nc = self.nc_var.get() == "NC"
        if not target or target.lower() == "main":
            self.status.configure(text="Enter a subroutine name (not Main), then Add JSR.")
            return
        try:
            program = ensure_routine(self.program, target)
            if not (program.get("routines") or {}).get(target):
                # An empty routine is not exported, so the JSR would point at nothing on re-import.
                program = add_rung_to_routine(program, target, [{"kind": "sbr", "name": target}, {"kind": "ret"}],
                                              comment=f"SBR {target}")
            program = add_rung_from_elements(
                program,
                [
                    {"kind": "contact", "var": contact, "form": "NC" if nc else "NO"},
                    {"kind": "jsr", "target": target},
                ],
                comment=f"Call {target}",
            )
        except Exception as exc:
            self.status.configure(text=str(exc))
            return
        self.program = program
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._commit(status=f"Added JSR {target} (educational subroutine call).")

    def _add_sbr_routine(self) -> None:
        name = (self._rung_field_vars.get("sbr_name").get() if self._rung_field_vars.get("sbr_name") else
                self._rung_field_vars.get("jsr_target").get() if self._rung_field_vars.get("jsr_target") else "Motor")
        name = str(name or "").strip() or "Motor"
        try:
            program = ensure_routine(self.program, name)
            # Seed an SBR label + RET so the routine is visible/printable.
            if not (program.get("routines") or {}).get(name):
                program = add_rung_to_routine(
                    program, name,
                    [{"kind": "sbr", "name": name}, {"kind": "ret"}],
                    comment=f"SBR {name}",
                )
            elif not program["routines"][name]:
                program = add_rung_to_routine(
                    program, name,
                    [{"kind": "sbr", "name": name}, {"kind": "ret"}],
                    comment=f"SBR {name}",
                )
        except Exception as exc:
            self.status.configure(text=str(exc))
            return
        self.program = program
        self._commit(status=f"Subroutine {name} ready — use Add JSR to call it from Main.")

    def _add_ret_rung(self) -> None:
        contact = self._picked(self.contact_var)
        els = []
        if contact:
            els.append({"kind": "contact", "var": contact, "form": "NC" if self.nc_var.get() == "NC" else "NO"})
        els.append({"kind": "ret"})
        try:
            program = add_rung_from_elements(self.program, els, comment="Return")
        except Exception as exc:
            self.status.configure(text=str(exc))
            return
        self.program = program
        self._selected_rung_id = self.program["rungs"][-1]["id"]
        self._commit(status="Added RET (returns from the current routine when energized).")

    def _apply_issue_fix(self, issue: dict) -> None:
        try:
            program = apply_verify_fix(self.program, issue)
        except Exception as exc:
            self.status.configure(text=f"Fix failed: {exc}")
            return
        self.program = program
        self._commit(status=f"Applied fix: {issue.get('code')} — { (issue.get('fix') or {}).get('action') }")
        self._goto_ref(issue.get("rung_id") or "", f"Fixed {issue.get('code')}", path=issue.get("path") or ())
        self._refresh_verify_panel()

    def _add_tag_alias(self) -> None:
        alias = (self._new_alias_name.get() if self._new_alias_name else "").strip()
        base = (self._new_alias_base.get() if self._new_alias_base else "").strip()
        if not alias:
            self.status.configure(text="Enter an alias name and the base tag it points to.")
            return
        try:
            program = set_tag_alias(self.program, alias, base)
        except Exception as exc:
            self.status.configure(text=str(exc))
            return
        self.program = program
        self._commit(status=f"Alias {alias} → {base}" if base else f"Cleared alias {alias}")
        try:
            self._new_alias_name.delete(0, "end")
            self._new_alias_base.delete(0, "end")
        except Exception:
            pass
        self._refresh_tag_list()

    def _open_hmi_editor(self) -> None:
        from cabinet_studio.ui.hmi_editor import open_hmi_editor

        self._hmi_editor = open_hmi_editor(self, self.fonts, self.project, on_change=self.on_change,
                                           existing=getattr(self, "_hmi_editor", None),
                                           sim_provider=lambda: (self._ensure_scan_sim(), bool(self._sim_running)))

    def _open_device_panel(self) -> None:
        from cabinet_studio.ui.device_panel import open_device_panel

        self._flush_editor_to_program()
        self.project.program = program_to_dict(self.program)
        cabinet_path = getattr(self, "cabinet_path", None) or getattr(self.master, "path", None)
        self._device_panel = open_device_panel(self, self.fonts, self.project, on_change=self.on_change,
                                               save_path=cabinet_path,
                                               existing=getattr(self, "_device_panel", None))

    def _open_watch_panel(self) -> None:
        win, fresh = self._tool_window("watch", "Watch / Trend", "760x560")
        if fresh:
            top = ctk.CTkFrame(win, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4))
            section_label(top, "WATCH / TREND — SIMULATE SAMPLES", self.fonts.tiny).pack(side="left")
            ghost_button(top, "Close", lambda: self._close_tool_window("watch"), self.fonts.small, width=80).pack(side="right", padx=4)
            ghost_button(top, "Export CSV", self._watch_export_csv, self.fonts.small, width=100).pack(side="right", padx=4)
            ghost_button(top, "Clear", self._watch_clear, self.fonts.small, width=80).pack(side="right", padx=4)
            self._watch_pause_btn = ghost_button(top, "Pause", self._watch_toggle_pause, self.fonts.small, width=90)
            self._watch_pause_btn.pack(side="right", padx=4)
            add = ctk.CTkFrame(win, fg_color="transparent")
            add.pack(fill="x", padx=12, pady=4)
            self._watch_tag_var = ctk.StringVar(master=win, value=self._picked(self.contact_var) or "PB_Start")
            ctk.CTkEntry(add, textvariable=self._watch_tag_var, width=140, font=self.fonts.tiny,
                         fg_color=ENTRY, border_color=BORDER, text_color=TEXT).pack(side="left", padx=4)
            self._watch_label_var = ctk.StringVar(master=win, value="")
            ctk.CTkEntry(add, textvariable=self._watch_label_var, width=120, font=self.fonts.tiny,
                         fg_color=ENTRY, border_color=BORDER, text_color=TEXT,
                         placeholder_text="series label").pack(side="left", padx=2)
            ghost_button(add, "Add tag", self._watch_add_tag, self.fonts.tiny, width=80).pack(side="left", padx=2)
            ghost_button(add, "Add coil", lambda: self._watch_add_picked("coil"), self.fonts.tiny, width=80).pack(side="left", padx=2)
            ghost_button(add, "Add ACC", self._watch_add_acc, self.fonts.tiny, width=80).pack(side="left", padx=2)
            self._watch_list = ctk.CTkScrollableFrame(win, fg_color=PANEL, height=120)
            self._watch_list.pack(fill="x", padx=12, pady=4)
            self._watch_plot = tk.Canvas(win, background=c("PLOT_BG"), highlightthickness=0, height=280)
            self._watch_plot.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self._sync_watch_pause_btn()
        self._refresh_watch_panel()

    def _watch_add_tag(self) -> None:
        tag = (self._watch_tag_var.get() if self._watch_tag_var is not None else "").strip()
        if not tag:
            return
        label = (self._watch_label_var.get() if self._watch_label_var is not None else "").strip() or None
        self._watch.add_tag(tag, label=label)
        self._refresh_watch_panel()
        shown = self._watch.series_label(tag)
        self.status.configure(text=f"Watching {shown} ({tag}) — press Run / Step to sample.")

    def _watch_add_picked(self, which: str) -> None:
        tag = self._picked(self.coil_var if which == "coil" else self.contact_var)
        if tag:
            if self._watch_tag_var is not None:
                self._watch_tag_var.set(tag)
            label = (self._watch_label_var.get() if self._watch_label_var is not None else "").strip() or None
            self._watch.add_tag(tag, label=label)
            self._refresh_watch_panel()

    def _watch_add_acc(self) -> None:
        tag = (self._rung_field_vars.get("timer_tag").get() if self._rung_field_vars.get("timer_tag") else "T1")
        tag = f"{str(tag).strip()}.ACC"
        if self._watch_tag_var is not None:
            self._watch_tag_var.set(tag)
        label = (self._watch_label_var.get() if self._watch_label_var is not None else "").strip() or None
        self._watch.add_tag(tag, label=label)
        self._refresh_watch_panel()

    def _watch_clear(self) -> None:
        self._watch.clear()
        self._refresh_watch_panel()

    def _watch_remove(self, tag: str) -> None:
        self._watch.remove_tag(tag)
        self._refresh_watch_panel()

    def _watch_toggle_pause(self) -> None:
        paused = self._watch.toggle_pause()
        self._sync_watch_pause_btn()
        self._refresh_watch_panel()
        self.status.configure(text="Watch paused — Simulate still runs, samples frozen." if paused else "Watch resumed — sampling again.")

    def _sync_watch_pause_btn(self) -> None:
        btn = self._watch_pause_btn
        if btn is None:
            return
        try:
            btn.configure(text="Resume" if self._watch.paused else "Pause")
        except Exception:
            pass

    def _watch_export_csv(self) -> None:
        if not self._watch.tags:
            self.status.configure(text="Add watch tags before Export CSV.")
            return
        from tkinter import filedialog
        from pathlib import Path as _Path
        default = f"{self.project.name or 'cabinet'}_watch.csv".replace(" ", "_")
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            title="Export Watch / Trend CSV",
            defaultextension=".csv",
            initialfile=default,
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        out = self._watch.export_csv(path)
        self.status.configure(text=f"Watch CSV exported → {_Path(out).name} ({len(self._watch.samples)} samples).")

    def _refresh_watch_panel(self) -> None:
        if self._watch_list is None:
            return
        try:
            self._clear_children(self._watch_list)
        except Exception:
            return
        latest = self._watch.latest()
        colors = ["#3ddc97", "#5b9cff", "#f0c14a", "#e86a6a", "#c084fc", "#2dd4bf", "#fb923c", "#f472b6"]
        if not self._watch.tags:
            ctk.CTkLabel(self._watch_list, text="Add tags (+ optional series label), then Simulate / Step — samples plot below.",
                         font=self.fonts.tiny, text_color=MUTED).pack(anchor="w", padx=6, pady=4)
        for ti, tag in enumerate(self._watch.tags):
            row = ctk.CTkFrame(self._watch_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            color = colors[ti % len(colors)]
            swatch = tk.Canvas(row, width=14, height=14, highlightthickness=0, background=c(PANEL))
            swatch.pack(side="left", padx=(4, 2))
            swatch.create_rectangle(1, 1, 13, 13, fill=color, outline="")
            val = latest.get(tag)
            shown = "—" if val is None else (f"{val:.4g}" if abs(val) >= 0.001 else f"{val:.4f}")
            label = self._watch.series_label(tag)
            text = f"{label} = {shown}" if label == tag else f"{label} [{tag}] = {shown}"
            ctk.CTkLabel(row, text=text, width=360, anchor="w",
                         font=self.fonts.tiny, text_color=TEXT).pack(side="left", padx=4)
            ghost_button(row, "Remove", lambda t=tag: self._watch_remove(t), self.fonts.tiny, width=70).pack(side="right", padx=4)
        self._draw_watch_plot()

    def _draw_watch_plot(self) -> None:
        canvas = self._watch_plot
        if canvas is None:
            return
        try:
            canvas.delete("all")
            w = max(320, int(canvas.winfo_width() or 640))
            h = max(180, int(canvas.winfo_height() or 280))
        except Exception:
            return
        canvas.create_rectangle(0, 0, w, h, fill=c("PLOT_BG"), outline="")
        pause_note = "  ·  PAUSED" if self._watch.paused else ""
        if not self._watch.samples or not self._watch.tags:
            msg = "No samples yet — press ▶ Simulate or Step"
            if self._watch.paused:
                msg = "Paused — Resume to sample, or Clear"
            canvas.create_text(w / 2, h / 2, fill=c("PLOT_TEXT"), text=msg)
            return
        pad_l, pad_r, pad_t, pad_b = 36, 12, 16, 36
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b
        n = len(self._watch.samples)
        colors = ["#3ddc97", "#5b9cff", "#f0c14a", "#e86a6a", "#c084fc", "#2dd4bf", "#fb923c", "#f472b6"]
        # Global y range across watched tags
        vals = [v for s in self._watch.samples for v in s.values()]
        ymin, ymax = (min(vals), max(vals)) if vals else (0.0, 1.0)
        if abs(ymax - ymin) < 1e-9:
            ymax = ymin + 1.0
            ymin = ymin - 0.0
        # grid
        for i in range(5):
            yy = pad_t + plot_h * i / 4
            canvas.create_line(pad_l, yy, w - pad_r, yy, fill=c("PLOT_GRID"))
            v = ymax - (ymax - ymin) * i / 4
            canvas.create_text(pad_l - 4, yy, anchor="e", fill=c("PLOT_TEXT"), text=f"{v:.3g}", font=(self.fonts.ui_family, 8))
        for ti, tag in enumerate(self._watch.tags):
            series = self._watch.series(tag)
            color = colors[ti % len(colors)]
            if len(series) < 2:
                # single point
                if series:
                    x = pad_l
                    y = pad_t + plot_h * (1 - (series[0] - ymin) / (ymax - ymin))
                    canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline="")
                continue
            pts = []
            for i, val in enumerate(series):
                x = pad_l + plot_w * i / max(1, n - 1)
                y = pad_t + plot_h * (1 - (val - ymin) / (ymax - ymin))
                pts.extend([x, y])
            canvas.create_line(*pts, fill=color, width=2, smooth=False)
        # Legend with color swatch + label + last value (clearer than bare tag)
        lx = pad_l + 4
        ly = h - 14
        for ti, tag in enumerate(self._watch.tags):
            color = colors[ti % len(colors)]
            label = self._watch.series_label(tag)
            last = self._watch.series(tag)
            last_s = f"{last[-1]:.4g}" if last else "—"
            entry = f"{label}={last_s}"
            canvas.create_rectangle(lx, ly - 6, lx + 10, ly + 4, fill=color, outline="")
            canvas.create_text(lx + 14, ly, anchor="w", fill=color, text=entry, font=(self.fonts.ui_family, 9))
            lx += max(90, 8 * len(entry) + 28)
            if lx > w - 40:
                break
        scan_txt = ""
        if self._watch.scan_numbers:
            scan_txt = f"scans {self._watch.scan_numbers[0]}…{self._watch.scan_numbers[-1]}{pause_note}"
        canvas.create_text(w - 8, 10, anchor="ne", fill=c("PLOT_TEXT"),
                           text=scan_txt,
                           font=(self.fonts.ui_family, 8))



    # --- v0.3.7 floating Force / I/O strip ------------------------------------

    def force_strip_is_floating(self) -> bool:
        return self._force_popout is not None

    def _toggle_force_popout(self) -> None:
        if self._force_popout is not None:
            self._dock_force_strip()
        else:
            self._pop_out_force_strip()

    def _pop_out_force_strip(self) -> None:
        """Float Force inputs / coil / timer / counter status in a movable, non-modal window."""
        if self._force_popout is not None:
            return
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title(f"Force / I/O - {self.project.name}")
        win.minsize(*_PROG_FORCE_MIN)
        apply_saved_geometry(
            win, _PROG_FORCE_GEOM_KEY, default_w=_PROG_FORCE_DEFAULT[0], default_h=_PROG_FORCE_DEFAULT[1],
            min_w=_PROG_FORCE_MIN[0], min_h=_PROG_FORCE_MIN[1],
        )
        win.protocol("WM_DELETE_WINDOW", self._dock_force_strip)
        self._force_popout = win
        self._force_geom_flush = bind_geometry_autosave(win, _PROG_FORCE_GEOM_KEY, min_w=_PROG_FORCE_MIN[0], min_h=_PROG_FORCE_MIN[1])
        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(6, 0))
        section_label(top, "SIMULATION + I/O (educational)", self.fonts.tiny).pack(side="left")
        ghost_button(top, "Dock I/O", self._dock_force_strip, self.fonts.tiny, width=86).pack(side="right", padx=4)
        ctk.CTkCheckBox(
            top, text="Keep on top", variable=self._sim_on_top_var, command=self._on_sim_on_top_toggle,
            font=self.fonts.tiny, checkbox_width=16, checkbox_height=16,
        ).pack(side="right", padx=8)
        controls = SimToolbar(win, self, label=None)
        controls.pack(fill="x", padx=8, pady=(4, 0))
        self._sim_toolbars.append(controls)
        self._sim_status_float = ctk.CTkLabel(
            win, text=self._sim_status.cget("text"), font=self.fonts.tiny, text_color=MUTED, anchor="w",
            justify="left", wraplength=1000,
        )
        self._sim_status_float.pack(fill="x", padx=12, pady=(4, 0))
        strip = ctk.CTkScrollableFrame(win, fg_color=PANEL, orientation="horizontal", height=64)
        strip.pack(fill="both", expand=True, padx=8, pady=6)
        self._bind_edit_shortcuts(win)
        self._apply_force_on_top()
        try:
            self._force_home_strip.pack_forget()
        except Exception:
            pass
        self._force_hint = ctk.CTkLabel(
            self._force_wrap, text="Force / I/O strip is floating — drag it anywhere.", font=self.fonts.tiny, text_color=MUTED
        )
        self._force_hint.pack(side="left", padx=8, pady=4)
        self._force_toggle_btn.configure(text="Dock I/O")
        self._force_strip = strip
        self._rebuild_force_strip_safe()
        _save_ui_pref(_PROG_FORCE_FLOAT_PREF, True)

    def _close_force_window(self) -> None:
        win = self._force_popout
        if win is None:
            return
        if self._force_geom_flush:
            try:
                self._force_geom_flush()
            except Exception:
                pass
            self._force_geom_flush = None
        else:
            remember_window_geometry(win, _PROG_FORCE_GEOM_KEY, min_w=_PROG_FORCE_MIN[0], min_h=_PROG_FORCE_MIN[1])
        self._force_popout = None
        self._sim_status_float = None
        self._force_strip = self._force_home_strip
        self._force_sig = None
        try:
            win.destroy()
        except Exception:
            pass

    def _apply_force_on_top(self) -> None:
        """v0.3.20: the floating sim panel rides above the ladder pop-out (transient
        to it) and, with Keep on top, above every window."""
        win = self._force_popout
        if win is None:
            return
        try:
            win.wm_transient(self._rung_editor_owner())
        except Exception:
            pass
        try:
            win.attributes("-topmost", bool(self._sim_on_top_var.get()))
            win.lift()
        except Exception:
            pass

    def _on_sim_on_top_toggle(self) -> None:
        _save_ui_pref(_PROG_SIM_ON_TOP_PREF, bool(self._sim_on_top_var.get()))
        self._apply_force_on_top()
        self._apply_ai_on_top()

    # v0.3.21: AI assistant beside the live simulation
    def _open_ai_assistant(self) -> None:
        win = self._ai_window
        if win is not None and win.winfo_exists():
            win.deiconify()
            self._apply_ai_on_top()
            return
        self._ai_window = AiAssistantWindow(
            self, self.fonts, mode="sim", context_fn=self._ai_context, apply_fn=self._ai_apply,
            title=f"AI assistant - {self.project.name}",
        )
        self._apply_ai_on_top()

    def _apply_ai_on_top(self) -> None:
        win = self._ai_window
        if win is None:
            return
        try:
            if not win.winfo_exists():
                self._ai_window = None
                return
            win.wm_transient(self._rung_editor_owner())
            win.attributes("-topmost", bool(self._sim_on_top_var.get()))
            win.lift()
        except Exception:
            pass

    def _ai_context(self) -> dict:
        rungs = self.program.get("rungs") or []
        ids = [r.get("id") for r in rungs]
        sim = self.__dict__.get("_scan_sim_obj") if self._sim_session else None
        if sim is None and self._sim_session:
            sim = self._scan_sim
        try:
            from cabinet_studio.services.ladder_sim import sim_blockers

            blockers = sim_blockers(self.program, project_name=getattr(self.project, "name", "") or "",
                                    devices=cabinet_device_tags(self.project))
        except Exception:
            blockers = []
        return {
            "program": self.program,
            "sim": sim,
            "selected_index": ids.index(self._selected_rung_id) if self._selected_rung_id in ids else None,
            "cursor_index": ids.index(self._sim_cursor_rung_id) if self._sim_cursor_rung_id in ids else None,
            "blockers": blockers,
            "project_name": getattr(self.project, "name", "") or "",
        }

    def _ai_apply(self, new_program: dict, rung_id: str, summary: str) -> None:
        self.program = new_program
        self._selected_rung_id = rung_id
        self._commit(status=f"AI change applied: {summary[:120]}")

    def _dock_force_strip(self) -> None:
        if self._force_popout is None:
            return
        self._close_force_window()
        _save_ui_pref(_PROG_FORCE_FLOAT_PREF, False)
        if self._force_hint is not None:
            try:
                self._force_hint.destroy()
            except Exception:
                pass
            self._force_hint = None
        try:
            self._force_toggle_btn.configure(text="Float I/O")
            self._force_home_strip.pack(side="left", fill="both", expand=True, padx=4, pady=2)
        except Exception:
            pass
        self._rebuild_force_strip_safe()

    def _rebuild_force_strip_safe(self) -> None:
        try:
            if self._sim_running or self._scan_sim is not None:
                self._rebuild_force_strip()
            else:
                self._clear_children(self._force_strip)
                ctk.CTkLabel(
                    self._force_strip, text="Force inputs appear when Run / Step runs (educational scan).",
                    font=self.fonts.tiny, text_color=MUTED,
                ).pack(side="left", padx=6, pady=4)
        except Exception:
            pass

    def close(self) -> None:
        if self._error_after is not None:
            try:
                self.after_cancel(self._error_after)
            except Exception:
                pass
            self._error_after = None
        self._sim_stop()
        if self._wizard is not None:
            self._wizard.cancel()
        self._save_pane_widths()
        self._close_all_tool_windows()
        self._hide_hover_tip()
        self._close_rung_editor_window()  # remembers geometry + floating preference
        self._close_force_window()  # keeps the floating-I/O preference for next open
        if self._ai_window is not None:
            try:
                self._ai_window.destroy()
            except Exception:
                pass
            self._ai_window = None
        if self._canvas_popout is not None:
            self._dock_ladder_canvas()
        self._flush_editor_to_program()
        self.project.program = program_to_dict(self.program)
        if self.on_change:
            self.on_change("Programming closed - back to cabinet")
        try:
            self.state("normal")
        except Exception:
            pass
        self.destroy()
