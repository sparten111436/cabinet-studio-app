"""The one simulation toolbar (v0.3.22).

Same controls and labels everywhere it appears: the Programming toolbar, the
ladder pop-out and the floating I/O window. Every button is a registered command
(``sim.*``) so menus, buttons and F-keys all run the same code.
"""

from __future__ import annotations

import customtkinter as ctk

from cabinet_studio.ui.hover_tip import attach as attach_tip
from cabinet_studio.ui.theme import BLUE, BLUE_HOVER, ENTRY, HOVER, MUTED, PANEL, TEXT

SIM_BUTTONS = (
    ("sim.run", "Run", 64, True),
    ("sim.pause", "Pause", 64, False),
    ("sim.step_rung", "Step rung", 82, False),
    ("sim.step_scan", "Step scan", 82, False),
    ("sim.stop", "Stop", 60, False),
    ("sim.reset", "Reset", 60, False),
    ("sim.normal_run", "Normal run", 88, False),
)

SIM_HELP = {
    "sim.run": "Starts scanning the program over and over like a real PLC. Click any contact to switch that input.",
    "sim.pause": "Freezes the scan and timers where they are. Explain run tells you which rung is waiting.",
    "sim.step_rung": "Runs ONE rung, then stops - watch power flow left to right through each part.",
    "sim.step_scan": "Runs every rung once (one full PLC scan), then stops.",
    "sim.stop": "Stops the simulation and lets go of every input you switched.",
    "sim.reset": "Clears all bits, timers and counters back to zero - a fresh power-up.",
    "sim.normal_run": "Pretends the machine is running perfectly: makes stops and guards safe, presses Reset and "
                      "Start for you, and the pretend machine answers the outputs (motor running feedback, "
                      "cylinders reaching their sensors, parts passing eyes). Then test safety yourself: click "
                      "the E-stop or light curtain and watch the machine and the stack light react.",
    "sim.follow": "Scrolls the ladder so the rung being scanned stays on screen.",
    "sim.parts": "Lights each part of a rung one at a time, left to right, so you can follow the logic.",
    "tools.ask_ai": "Ask the AI about this program in plain words.",
}


class SimToolbar(ctk.CTkFrame):
    """viewer provides: commands, fonts, _sim_speed_var, _on_sim_speed, _follow_var, _sim_speeds."""

    def __init__(self, master, viewer, *, show_ai: bool = True, label: str | None = "SIMULATE") -> None:
        super().__init__(master, fg_color="transparent", corner_radius=0)
        fonts = viewer.fonts
        reg = viewer.commands
        if label:
            ctk.CTkLabel(self, text=label, font=fonts.tiny, text_color=MUTED).pack(side="left", padx=(6, 6))
        self.buttons = {}
        for cmd_id, text, width, primary in SIM_BUTTONS:
            btn = reg.button(self, cmd_id, text=text, width=width, primary=primary, font=fonts.small)
            btn.pack(side="left", padx=2, pady=3)
            self.buttons[cmd_id] = btn
        self.speed_menu = ctk.CTkOptionMenu(
            self, values=list(viewer._sim_speeds), variable=viewer._sim_speed_var, command=viewer._on_sim_speed,
            font=fonts.tiny, dropdown_font=fonts.tiny, width=150, height=26, fg_color=ENTRY,
            button_color=BLUE, button_hover_color=BLUE_HOVER, dropdown_fg_color=PANEL,
            dropdown_hover_color=HOVER, dropdown_text_color=TEXT, text_color=TEXT,
        )
        self.speed_menu.pack(side="left", padx=(6, 4), pady=3)
        self.follow = ctk.CTkCheckBox(
            self, text="Follow rung", variable=viewer._follow_var,
            command=lambda: viewer.commands.get("sim.follow").callback(),
            font=fonts.tiny, text_color=TEXT, checkbox_width=16, checkbox_height=16,
        )
        self.follow._cs_command_id = "sim.follow"
        self.follow.pack(side="left", padx=(6, 4))
        self.parts = ctk.CTkCheckBox(
            self, text="Each part", variable=viewer._sim_parts_var,
            command=lambda: viewer.commands.get("sim.parts").callback(),
            font=fonts.tiny, text_color=TEXT, checkbox_width=16, checkbox_height=16,
        )
        self.parts._cs_command_id = "sim.parts"
        self.parts.pack(side="left", padx=(6, 4))
        if show_ai:
            btn = reg.button(self, "tools.ask_ai", text="Ask AI", width=64, primary=True, font=fonts.small)
            btn.pack(side="left", padx=(6, 2), pady=3)
            self.buttons["tools.ask_ai"] = btn
        for cmd_id, widget in [*self.buttons.items(), ("sim.follow", self.follow), ("sim.parts", self.parts)]:
            attach_tip(widget, SIM_HELP.get(cmd_id, ""))
