"""HMI editor / creator: design the operator touch screen for this cabinet.

Screens on the left, the panel drawn to scale in the middle (bezel, screen and
grid from the HMI library), properties on the right. Click a palette button to
drop an object in the first free spot, drag it to move, drag its corner square
to resize. "Run interview" builds a first design from the cabinet devices and
ladder tags. Save writes the design into the project (shown on the drawings).
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from cabinet_studio.services import hmi_design as hd
from cabinet_studio.services.hmi_library import hmi_by_id, hmi_id_from_label, hmi_label, load_hmi_catalog, recommend_hmi
from cabinet_studio.services.hmi_runtime import BANNER, HmiRuntime
from cabinet_studio.services.hmi_symbols import ANIMATIONS, GRAPHICS, symbol_shapes, tk_draw_shapes
from cabinet_studio.ui.dialogs import ask_choice
from cabinet_studio.ui.hover_tip import attach
from cabinet_studio.ui.theme import BG, BORDER, CYAN, MUTED, ORANGE, PANEL, TEXT, c, ghost_button, primary_button, section_label
from cabinet_studio.ui.util import center_on_parent

PALETTE_ORDER = ("momentary", "toggle", "lamp", "numeric_display", "numeric_entry", "trend", "text", "alarm_banner",
                 "nav", "estop_status")
GRAPHIC_ORDER = tuple(GRAPHICS)
ANIM_BY_LABEL = {label: key for key, label in ANIMATIONS.items()}
RUN_MS = 100
NO_PARTS = "(no machine parts found)"
BUTTON_KINDS = ("momentary", "toggle")
HANDLE = 9
UNDO_LIMIT = 60


def open_hmi_editor(master, fonts, project, *, edit_hook=None, on_change=None, existing=None, sim_provider=None):
    """Bring an open editor to the front, or open a new one.

    ``sim_provider()`` -> (ScanSimulator, running) lets Run with simulator share the Programming page sim."""
    try:
        if existing is not None and existing.winfo_exists():
            existing.bring_to_front()
            return existing
    except Exception:
        pass
    return HmiEditor(master, fonts, project, edit_hook=edit_hook, on_change=on_change, sim_provider=sim_provider)


class HmiEditor(ctk.CTkToplevel):
    def __init__(self, master, fonts, project, *, edit_hook=None, on_change=None, sim_provider=None) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.project = project
        self.sim_provider = sim_provider
        self.runtime = None
        self._run_job = None
        self._pressed: hd.HmiObject | None = None
        # edit_hook(apply_fn, message): the owner snapshots undo, runs apply_fn, marks the project changed.
        self.edit_hook = edit_hook
        self.on_change = on_change
        saved = hd.load_design(project)
        self.design = saved or hd.HmiDesign(recommend_hmi(project)[0], [hd.HmiScreen("Main")])
        self.screen_name = self.design.screens[0].name if self.design.screens else ""
        self.selected_id: str | None = None
        self.dirty = False
        self._undo: list[str] = []
        self._drag: dict | None = None
        self._geom: dict | None = None
        self._interview: HmiInterview | None = None
        self._alarm_win = None
        self.title("HMI editor")
        self.minsize(1100, 700)
        self.protocol("WM_DELETE_WINDOW", self.close)
        center_on_parent(self, 1280, 800, master)
        self._build()
        self._refresh_all()
        self.status("Ready. Click Run interview to build screens for you." if saved is None
                    else "Loaded the saved HMI design.")
        self.after(30, self.bring_to_front)

    # ------------------------------------------------------------------ layout

    def _btn(self, parent, text, cmd, tip, *, primary=False, width=120):
        maker = primary_button if primary else ghost_button
        btn = maker(parent, text, cmd, self.fonts.small, width=width)
        attach(btn, tip, text)
        return btn

    def _build(self) -> None:
        f = self.fonts
        top = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        top.pack(fill="x", padx=12, pady=(10, 4))
        section_label(top, "HMI EDITOR", f.tiny).pack(side="left", padx=(0, 10))
        self.interview_btn = self._btn(top, "Run interview", self.run_interview,
                                       "Answer a few easy questions and the app builds the HMI screens for you "
                                       "from the devices on this cabinet. You can change everything after.",
                                       primary=True, width=130)
        self.interview_btn.pack(side="left", padx=3)
        self.validate_btn = self._btn(top, "Validate", self.validate,
                                      "Checks for unknown tags, objects on top of each other, missing tags, "
                                      "and lists every tag the HMI writes into the PLC.", width=90)
        self.validate_btn.pack(side="left", padx=3)
        self.undo_btn = self._btn(top, "Undo", self.undo, "Takes back your last change.", width=70)
        self.undo_btn.pack(side="left", padx=3)
        self.delete_btn = self._btn(top, "Delete object", self.delete_selected,
                                    "Removes the selected object (the one with the dashed outline).", width=110)
        self.delete_btn.pack(side="left", padx=3)
        self.run_btn = self._btn(top, "Run with simulator", self.toggle_run,
                                 "Makes the screen live against the ladder simulator: press buttons, watch lamps, "
                                 "numbers and machine graphics move. Uses the Programming page simulator when it "
                                 "is open. SIMULATION only - nothing is sent to a real PLC. Press Stop to edit again.",
                                 primary=True, width=150)
        self.run_btn.pack(side="left", padx=(12, 3))
        self.close_btn = self._btn(top, "Close", self.close, "Closes the HMI editor. It asks first if you have "
                                   "changes that are not saved.", width=80)
        self.close_btn.pack(side="right", padx=3)
        self.save_btn = self._btn(top, "Save", self.save, "Saves the HMI into this cabinet. The HMI screen layout, "
                                  "door cutout and HMI wiring sheets then appear in the drawings. Save the cabinet "
                                  "file too to keep it.", primary=True, width=90)
        self.save_btn.pack(side="right", padx=3)
        labels = [hmi_label(e) for e in load_hmi_catalog()]
        self.model_var = tk.StringVar(value=self._model_label())
        self.model_menu = ctk.CTkOptionMenu(top, values=labels, variable=self.model_var, command=self.change_model,
                                            width=360, font=f.small, dynamic_resizing=False)
        self.model_menu.pack(side="right", padx=8)
        attach(self.model_menu, "Pick the touch screen model from the HMI library. Your objects keep their places "
                                "and grow or shrink to fit the new screen.", "HMI model")
        ctk.CTkLabel(top, text="Model:", font=f.small, text_color=MUTED).pack(side="right")

        self.sim_banner = ctk.CTkLabel(self, text=f"{BANNER}.  Buttons write the simulator only.  "
                                                  "E-stop and safety are never written by the HMI.",
                                       font=f.small, fg_color="#b3261e", text_color="#ffffff", corner_radius=4)
        quick = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        quick.pack(fill="x", padx=12, pady=(0, 4))
        self._quick_row = quick
        section_label(quick, "QUICK BUILD", f.tiny).pack(side="left", padx=(0, 10))
        self.autobuild_btn = self._btn(quick, "Auto-build (1 click)", self.auto_build,
                                       "Builds every screen in one click from the cabinet devices and ladder tags: "
                                       "a faceplate per motor / valve / stack light, alarms, trends and the go-to "
                                       "bar. Uses the suggested answers (or your last interview answers).",
                                       primary=True, width=150)
        self.autobuild_btn.pack(side="left", padx=3)
        self.bind_btn = self._btn(quick, "Bind tags for me", self.bind_tags,
                                  "Fills in every empty PLC tag with the best match by name and type. Buttons get "
                                  "HMI_ memory bits. Check the result with Validate.", width=130)
        self.bind_btn.pack(side="left", padx=3)
        self.nav_btn = self._btn(quick, "Rebuild nav bar", self.rebuild_nav_bar,
                                 "Puts a row of Go-to buttons for every other screen along the bottom of each "
                                 "screen. Use it after adding or renaming screens.", width=120)
        self.nav_btn.pack(side="left", padx=3)
        self.alarms_btn = self._btn(quick, "Alarm list", self.show_alarms,
                                    "Shows the alarms made from the E-stop, safety, fault and overload tags, with a "
                                    "priority (1 = High). They also print on the HMI ALARM LIST sheet.", width=90)
        self.alarms_btn.pack(side="left", padx=3)
        self.csv_btn = self._btn(quick, "Export tag CSV", self.export_csv,
                                 "Saves a spreadsheet (CSV) of every HMI tag - name, type, read/write, PLC address - "
                                 "to import into FactoryTalk View, TIA Portal or NB-Designer (match the columns in "
                                 "their tag import).", width=120)
        self.csv_btn.pack(side="left", padx=3)
        self.export_btn = self._btn(quick, self._export_text(), self.export_for_maker,
                                    "Writes import-ready files for the picked HMI maker into the drawings folder "
                                    "(hmi sub-folder): tag list, alarm list, screen spec (JSON) and a picture of "
                                    "every screen (SVG). Import the tags in the maker's software and rebuild the "
                                    "screens there - this app does not download into the HMI.", width=150)
        self.export_btn.pack(side="left", padx=3)
        self.theme_var = tk.StringVar(value=self.design.theme)
        self.theme_menu = ctk.CTkOptionMenu(quick, values=list(hd.THEMES), variable=self.theme_var,
                                            command=self.change_theme, width=250, font=f.small,
                                            dynamic_resizing=False)
        self.theme_menu.pack(side="right", padx=3)
        attach(self.theme_menu, "Screen style. ISA-101 gray is the easy-on-the-eyes industry style: gray screen, "
                                "color only when something is wrong.", "Theme")
        ctk.CTkLabel(quick, text="Theme:", font=f.small, text_color=MUTED).pack(side="right")

        body = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        left = ctk.CTkFrame(body, width=210, fg_color=PANEL, corner_radius=0)
        left.pack(side="left", fill="y", padx=(6, 0), pady=6)
        left.pack_propagate(False)
        section_label(left, "SCREENS", f.tiny).pack(anchor="w", padx=4, pady=(4, 2))
        self.screen_list = ctk.CTkScrollableFrame(left, fg_color=PANEL, height=150)
        self.screen_list.pack(fill="x", padx=2)
        self.screen_entry = ctk.CTkEntry(left, font=f.small, placeholder_text="Screen name")
        self.screen_entry.pack(fill="x", padx=4, pady=(4, 2))
        attach(self.screen_entry, "Type a screen name here, then press Add screen or Rename.", "Screen name")
        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=2)
        self.add_screen_btn = self._btn(row, "Add screen", self.add_screen,
                                        "Adds a new empty screen named from the box above.", width=64)
        self.add_screen_btn.pack(side="left", padx=1)
        self.rename_btn = self._btn(row, "Rename", self.rename_screen,
                                    "Gives the current screen the name typed in the box above. Go-to buttons follow.",
                                    width=60)
        self.rename_btn.pack(side="left", padx=1)
        self.delete_screen_btn = self._btn(row, "Delete", self.delete_screen,
                                           "Deletes the current screen and everything on it (Undo brings it back).",
                                           width=60)
        self.delete_screen_btn.pack(side="left", padx=1)
        fp_box = ctk.CTkFrame(left, fg_color="transparent")
        fp_box.pack(side="bottom", fill="x", padx=2, pady=(4, 2))
        section_label(fp_box, "FACEPLATES (ONE CLICK)", f.tiny).pack(anchor="w", padx=2, pady=(4, 2))
        self._parts = hd.equipment(self.project)
        part_names = [p["tag"] for p in self._parts] or [NO_PARTS]
        self.part_var = tk.StringVar(value=part_names[0])
        self.part_menu = ctk.CTkOptionMenu(fp_box, values=part_names, variable=self.part_var,
                                           command=self._part_picked, font=f.small, dynamic_resizing=False)
        self.part_menu.pack(fill="x", padx=2, pady=1)
        attach(self.part_menu, "Pick a machine part found on this cabinet (motor, valve, stack light, counter).",
               "Machine part")
        self.fp_var = tk.StringVar(value=hd.FACEPLATES[self._parts[0]["faceplate"] if self._parts
                                                       else "motor"]["name"])
        self.fp_menu = ctk.CTkOptionMenu(fp_box, values=[v["name"] for v in hd.FACEPLATES.values()],
                                         variable=self.fp_var, font=f.small, dynamic_resizing=False)
        self.fp_menu.pack(fill="x", padx=2, pady=1)
        attach(self.fp_menu, "  ".join(f"{v['name']}: {v['help']}" for v in hd.FACEPLATES.values()), "Faceplate")
        self.faceplate_btn = self._btn(fp_box, "Add faceplate", self.add_faceplate,
                                       "Drops a ready-made group (lamps, buttons, numbers) for the picked machine part, "
                                       "already tied to its tags. Drag any piece to move the whole group.",
                                       primary=True, width=190)
        self.faceplate_btn.pack(fill="x", padx=2, pady=(2, 0))
        section_label(left, "ADD TO SCREEN", f.tiny).pack(anchor="w", padx=4, pady=(10, 2))
        self.palette_buttons: dict[str, ctk.CTkButton] = {}
        pal = ctk.CTkScrollableFrame(left, fg_color=PANEL)
        pal.pack(fill="both", expand=True, padx=2, pady=(0, 4))
        for kind in PALETTE_ORDER:
            spec = hd.OBJECT_KINDS[kind]
            btn = ghost_button(pal, spec["name"], lambda k=kind: self.add_from_palette(k), f.small, width=180)
            btn.pack(fill="x", pady=1)
            attach(btn, spec["help"] + " Click to drop it in the first free spot, then drag it.", spec["name"])
            self.palette_buttons[kind] = btn
        section_label(pal, "MACHINE GRAPHICS", f.tiny).pack(anchor="w", padx=2, pady=(10, 2))
        for kind in GRAPHIC_ORDER:
            spec = GRAPHICS[kind]
            btn = ghost_button(pal, spec["name"], lambda k=kind: self.add_from_palette(k), f.small, width=180)
            btn.pack(fill="x", pady=1)
            attach(btn, spec["help"] + " Click to drop it, then drag or resize it. Pick its tag on the right; it "
                   "animates in Run with simulator and prints still.", spec["name"])
            self.palette_buttons[kind] = btn

        right = ctk.CTkFrame(body, width=270, fg_color=PANEL, corner_radius=0)
        right.pack(side="right", fill="y", padx=(0, 6), pady=6)
        right.pack_propagate(False)
        section_label(right, "PROPERTIES", f.tiny).pack(anchor="w", padx=6, pady=(4, 2))
        self.prop_title = ctk.CTkLabel(right, text="Nothing selected", font=f.small, text_color=CYAN, anchor="w",
                                       justify="left", wraplength=250)
        self.prop_title.pack(fill="x", padx=6)
        ctk.CTkLabel(right, text="Words on the object", font=f.tiny, text_color=MUTED, anchor="w").pack(fill="x",
                                                                                                        padx=6)
        self.label_entry = ctk.CTkEntry(right, font=f.small)
        self.label_entry.pack(fill="x", padx=6, pady=(0, 4))
        attach(self.label_entry, "The words the operator sees on this object.", "Label")
        ctk.CTkLabel(right, text="PLC tag", font=f.tiny, text_color=MUTED, anchor="w").pack(fill="x", padx=6)
        self.tag_combo = ctk.CTkComboBox(right, values=self._tag_values(), font=f.small)
        self.tag_combo.pack(fill="x", padx=6, pady=(0, 2))
        self.suggest_btn = self._btn(right, "Suggest tag", self.suggest_tag,
                                     "Picks the best PLC tag for this object from its words and type. Press Apply "
                                     "changes to keep it.", width=250)
        self.suggest_btn.pack(fill="x", padx=6, pady=(0, 4))
        attach(self.tag_combo, "Pick the PLC tag this object reads or writes. Tags come from the cabinet devices "
                               "and the ladder. Names starting HMI_ are HMI memory bits you add to the PLC program.",
               "PLC tag")
        ctk.CTkLabel(right, text="Color", font=f.tiny, text_color=MUTED, anchor="w").pack(fill="x", padx=6)
        self.color_var = tk.StringVar(value="Green")
        self.color_menu = ctk.CTkOptionMenu(right, values=list(hd.COLORS), variable=self.color_var, font=f.small)
        self.color_menu.pack(fill="x", padx=6, pady=(0, 4))
        attach(self.color_menu, "Color of the object. Green = running / OK, Red = stop / fault, Amber = warning.",
               "Color")
        ctk.CTkLabel(right, text="Button action", font=f.tiny, text_color=MUTED, anchor="w").pack(fill="x", padx=6)
        self.mode_var = tk.StringVar(value=hd.OBJECT_KINDS["momentary"]["name"])
        self.mode_menu = ctk.CTkOptionMenu(right, values=[hd.OBJECT_KINDS[k]["name"] for k in BUTTON_KINDS],
                                           variable=self.mode_var, font=f.small)
        self.mode_menu.pack(fill="x", padx=6, pady=(0, 4))
        attach(self.mode_menu, "Momentary = on only while pressed. Toggle = press on, press again off. "
                               "Only for buttons.", "Button action")
        ctk.CTkLabel(right, text="Go to screen", font=f.tiny, text_color=MUTED, anchor="w").pack(fill="x", padx=6)
        self.target_var = tk.StringVar(value="")
        self.target_menu = ctk.CTkOptionMenu(right, values=[""], variable=self.target_var, font=f.small)
        self.target_menu.pack(fill="x", padx=6, pady=(0, 4))
        attach(self.target_menu, "For Go-to-screen buttons: which screen it opens.", "Go to screen")
        ctk.CTkLabel(right, text="Animate with tag", font=f.tiny, text_color=MUTED, anchor="w").pack(fill="x", padx=6)
        self.anim_var = tk.StringVar(value=ANIMATIONS["none"])
        self.anim_menu = ctk.CTkOptionMenu(right, values=list(ANIMATIONS.values()), variable=self.anim_var,
                                           font=f.small, dynamic_resizing=False)
        self.anim_menu.pack(fill="x", padx=6, pady=(0, 4))
        attach(self.anim_menu, "For machine graphics: how the picture moves from its PLC tag in Run with simulator. "
                               "Spins / moves while ON, fills from a 0-100 number, needle follows a number, "
                               "red when abnormal. Prints always show it still.", "Animation")
        run_row = ctk.CTkFrame(right, fg_color="transparent")
        run_row.pack(fill="x", padx=6, pady=(2, 2))
        self.value_entry = ctk.CTkEntry(run_row, font=f.small, width=110, placeholder_text="Number")
        self.value_entry.pack(side="left")
        attach(self.value_entry, "In Run with simulator: type a number for the selected Number entry.", "Number")
        self.send_btn = self._btn(run_row, "Send number", self.send_number,
                                  "In Run with simulator: writes the number into the selected Number entry's tag "
                                  "in the simulator (never a real PLC).", width=130)
        self.send_btn.pack(side="right")
        self.apply_btn = self._btn(right, "Apply changes", self.apply_properties,
                                   "Puts the words, tag, color and action above onto the selected object.",
                                   primary=True, width=250)
        self.apply_btn.pack(fill="x", padx=6, pady=(6, 4))
        self.help_label = ctk.CTkLabel(right, text="", font=f.tiny, text_color=MUTED, anchor="w", justify="left",
                                       wraplength=250)
        self.help_label.pack(fill="x", padx=6, pady=(4, 0))
        ctk.CTkLabel(right, text=hd.SAFETY_NOTE, font=f.tiny, text_color=ORANGE, anchor="w", justify="left",
                     wraplength=250).pack(side="bottom", fill="x", padx=6, pady=6)

        self.canvas = tk.Canvas(body, background=c("DESK"), highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Delete>", lambda _e: self.delete_selected())
        self.bind("<Control-z>", lambda _e: self.undo())

        self.status_label = ctk.CTkLabel(self, text="", font=f.small, text_color=TEXT, anchor="w", justify="left",
                                         wraplength=1200)
        self.status_label.pack(fill="x", padx=16, pady=(0, 10))

    # ------------------------------------------------------------------ helpers

    def bring_to_front(self) -> None:
        try:
            if self.state() in ("iconic", "withdrawn"):
                self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(60, lambda: self.winfo_exists() and self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _model_label(self) -> str:
        entry = hmi_by_id(self.design.model_id)
        return hmi_label(entry) if entry else self.design.model_id

    def _tag_values(self) -> list[str]:
        tags = [t["tag"] for t in hd.project_tags(self.project)]
        extra = ["HMI_Start", "HMI_Stop", "HMI_Reset", "HMI_AlarmActive", "HMI_AlarmAck", "HMI_ManualMode"]
        return [""] + tags + [t for t in extra if t not in tags]

    def _screen(self) -> hd.HmiScreen | None:
        return self.design.screen(self.screen_name) or (self.design.screens[0] if self.design.screens else None)

    def _selected(self) -> hd.HmiObject | None:
        screen = self._screen()
        if screen is None:
            return None
        return next((o for o in screen.objects if o.id == self.selected_id), None)

    def _snapshot(self) -> None:
        self._undo.append(hd.design_to_json(self.design))
        del self._undo[:-UNDO_LIMIT]

    def _changed(self, message: str) -> None:
        self.dirty = True
        self._refresh_all()
        self.status(message + " (not saved yet - press Save)")

    def _refresh_all(self) -> None:
        screen = self._screen()
        self.screen_name = screen.name if screen else ""
        for child in self.screen_list.winfo_children():
            child.destroy()
        for s in self.design.screens:
            current = s.name == self.screen_name
            maker = primary_button if current else ghost_button
            btn = maker(self.screen_list, s.name, lambda n=s.name: self.select_screen(n), self.fonts.small, width=180)
            btn.pack(fill="x", pady=1)
            attach(btn, f"Show the {s.name} screen ({len(s.objects)} objects).", s.name)
        names = [s.name for s in self.design.screens] or [""]
        self.target_menu.configure(values=names)
        self.model_var.set(self._model_label())
        self.theme_var.set(self.design.theme)
        self.export_btn.configure(text=self._export_text())
        self.undo_btn.configure(state="normal" if self._undo and self.runtime is None else "disabled")
        self._load_properties()
        self._draw()

    # ------------------------------------------------------------------ screens

    def select_screen(self, name: str) -> None:
        self.screen_name = name
        self.selected_id = None
        self._refresh_all()
        self.status(f"Showing the {name} screen.")

    def _unique(self, name: str) -> str:
        taken = {s.name for s in self.design.screens}
        base, n = name, 2
        while name in taken:
            name = f"{base} {n}"
            n += 1
        return name

    def add_screen(self) -> None:
        name = self._unique(self.screen_entry.get().strip() or f"Screen {len(self.design.screens) + 1}")
        self._snapshot()
        self.design.screens.append(hd.HmiScreen(name))
        self.screen_name = name
        self.selected_id = None
        self.screen_entry.delete(0, "end")
        self._changed(f"Added screen {name}.")

    def rename_screen(self) -> None:
        screen = self._screen()
        new = self.screen_entry.get().strip()
        if screen is None or not new or new == screen.name:
            self.status("Type the new name in the box under the screen list, then press Rename.")
            return
        new = self._unique(new)
        self._snapshot()
        old = screen.name
        screen.name = new
        for s in self.design.screens:
            for o in s.objects:
                if o.kind == "nav" and o.target == old:
                    o.target = new
                    if o.label == f"Go to {old}":
                        o.label = f"Go to {new}"
        self.screen_name = new
        self.screen_entry.delete(0, "end")
        self._changed(f"Renamed {old} to {new}.")

    def delete_screen(self) -> None:
        screen = self._screen()
        if screen is None or len(self.design.screens) <= 1:
            self.status("The HMI needs at least one screen.")
            return
        self._snapshot()
        self.design.screens.remove(screen)
        self.screen_name = self.design.screens[0].name
        self.selected_id = None
        self._changed(f"Deleted screen {screen.name}. Undo brings it back.")

    # ------------------------------------------------------------------ objects

    def add_from_palette(self, kind: str) -> None:
        screen = self._screen()
        if screen is None:
            return
        self._snapshot()
        obj = hd.add_object(self.design, screen, kind)
        if obj is None:
            self._undo.pop()
            self.status("This screen is full. Make room, add a screen, or pick a bigger HMI model.")
            return
        if kind == "nav":
            other = next((s.name for s in self.design.screens if s.name != screen.name), "")
            obj.target = other
            if other:
                obj.label = f"Go to {other}"
        bound = ""
        if hd.is_graphic(kind):
            obj.tag, why = hd.suggest_tag(obj, self.project)
            bound = f" {why}" if obj.tag else ""
        self.selected_id = obj.id
        self._changed(f"Added {hd.OBJECT_KINDS[kind]['name']}. Drag it where you want it; pick its tag on the right."
                      + bound)

    def delete_selected(self) -> None:
        obj = self._selected()
        if obj is None:
            self.status("Click an object first, then Delete object.")
            return
        self._snapshot()
        self._screen().objects.remove(obj)
        self.selected_id = None
        self._changed(f"Deleted {obj.label}.")

    def undo(self) -> None:
        if not self._undo:
            self.status("Nothing to undo.")
            return
        self.design = hd.design_from_json(self._undo.pop())
        if self.design.screen(self.screen_name) is None and self.design.screens:
            self.screen_name = self.design.screens[0].name
        self._changed("Undone.")

    def change_model(self, label: str) -> None:
        model_id = hmi_id_from_label(label)
        if not model_id or model_id == self.design.model_id:
            return
        self._snapshot()
        hd.rescale_to_model(self.design, model_id)
        self._changed(f"HMI model is now {label}. Objects were resized to fit.")

    # ------------------------------------------------------------------ quick build

    def auto_build(self) -> None:
        self._snapshot()
        answers = hd.default_answers(self.project, dict(self.design.answers))
        self.design = hd.generate_design(self.project, answers, theme=self.design.theme)
        self.screen_name = self.design.screens[0].name
        self.selected_id = None
        n = sum(len(s.objects) for s in self.design.screens)
        self._changed(f"Auto-built {len(self.design.screens)} screen(s) with {n} objects on a "
                      f"{self._model_label()}.")

    def bind_tags(self) -> None:
        self._snapshot()
        count = hd.bind_all(self.design, self.project)
        if not count:
            self._undo.pop()
            self.status("Every object that needs a tag already has one (or nothing on the cabinet matches).")
            return
        self._changed(f"Filled in {count} tag(s). Press Validate to check them.")

    def rebuild_nav_bar(self) -> None:
        self._snapshot()
        hd.rebuild_nav(self.design)
        self._changed("Go-to buttons rebuilt along the bottom of every screen.")

    def show_alarms(self) -> list[dict[str, str]]:
        rows = hd.alarm_rows(self.design, self.project)
        try:
            if self._alarm_win is not None and self._alarm_win.winfo_exists():
                self._alarm_win.destroy()
        except Exception:
            pass
        win = ctk.CTkToplevel(self, fg_color=BG)
        win.title("HMI alarm list")
        win.transient(self)
        center_on_parent(win, 640, 420, self)
        box = ctk.CTkTextbox(win, font=("Consolas", 12))
        box.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        lines = [f"{'Priority':<11}{'Tag':<16}Message"] + [f"{r['priority']:<11}{r['tag']:<16}{r['message']}"
                                                           for r in rows]
        if not rows:
            lines.append("No alarms yet - no E-stop, safety, fault or overload tags on this cabinet.")
        lines += ["", "Safety alarms only REPORT hardwired safety devices.", hd.SAFETY_NOTE]
        box.insert("end", "\n".join(lines))
        box.configure(state="disabled")
        win.close_btn = ghost_button(win, "Close", win.destroy, self.fonts.small, width=100)
        win.close_btn.pack(pady=(0, 10))
        attach(win.close_btn, "Close the alarm list.", "Close")
        self._alarm_win = win
        self.status(f"{len(rows)} alarm(s). They print on the HMI ALARM LIST sheet after Save.")
        return rows

    def export_csv(self) -> None:
        from tkinter import filedialog

        name = "".join(ch if ch.isalnum() else "-" for ch in self.project.name).strip("-") or "cabinet"
        path = filedialog.asksaveasfilename(parent=self, title="Save HMI tag list", defaultextension=".csv",
                                            initialfile=f"{name}-hmi-tags.csv",
                                            filetypes=[("CSV spreadsheet", "*.csv")])
        if not path:
            return
        count = hd.export_tag_csv(self.design, self.project, path)
        self.status(f"Saved {count} HMI tags to {path}.")

    def change_theme(self, name: str) -> None:
        if name not in hd.THEMES or name == self.design.theme:
            return
        self._snapshot()
        self.design.theme = name
        self._changed(f"Theme is now {name}.")

    def _part_picked(self, tag: str) -> None:
        part = next((p for p in self._parts if p["tag"] == tag), None)
        if part:
            self.fp_var.set(hd.FACEPLATES[part["faceplate"]]["name"])

    def add_faceplate(self) -> None:
        screen = self._screen()
        tag = self.part_var.get()
        if screen is None or tag == NO_PARTS:
            self.status("No machine parts on this cabinet yet. Add motors, valves or lights to the cabinet first.")
            return
        fp = next(k for k, v in hd.FACEPLATES.items() if v["name"] == self.fp_var.get())
        part = next((p for p in self._parts if p["tag"] == tag), {"tag": tag})
        controls = self.design.answers.get("hmi_start_stop", hd.START_ON_HMI) == hd.START_ON_HMI
        self._snapshot()
        placed = hd.add_faceplate(self.design, screen, fp, part, controls=controls)
        if not placed:
            self._undo.pop()
            self.status("No room for that faceplate here. Add a screen or pick a bigger HMI model.")
            return
        self.selected_id = placed[0].id
        self._changed(f"Added the {hd.FACEPLATES[fp]['name']} faceplate for {tag}. Drag it to move the group.")

    def suggest_tag(self) -> None:
        obj = self._selected()
        if obj is None:
            self.status("Click an object first.")
            return
        tag, why = hd.suggest_tag(obj, self.project)
        if tag:
            self.tag_combo.set(tag)
        self.status(why + (" Press Apply changes to keep it." if tag else ""))

    def _load_properties(self) -> None:
        obj = self._selected()
        for w in (self.label_entry, self.tag_combo):
            w.configure(state="normal")
        self.label_entry.delete(0, "end")
        self.tag_combo.set("")
        state = "normal" if obj else "disabled"
        for w in (self.label_entry, self.tag_combo, self.color_menu, self.apply_btn, self.delete_btn,
                  self.suggest_btn):
            w.configure(state=state)
        running = self.runtime is not None
        self.send_btn.configure(state="normal" if running and obj is not None and obj.kind == "numeric_entry"
                                else "disabled")
        if obj is None:
            self.prop_title.configure(text="Nothing selected. Click an object on the screen.")
            self.mode_menu.configure(state="disabled")
            self.target_menu.configure(state="disabled")
            self.anim_menu.configure(state="disabled")
            self.help_label.configure(text="")
            return
        spec = hd.OBJECT_KINDS[obj.kind]
        self.prop_title.configure(text=spec["name"])
        self.label_entry.insert(0, obj.label)
        self.tag_combo.set(obj.tag)
        self.tag_combo.configure(values=self._tag_values())
        self.tag_combo.configure(state="normal" if self._taggable(obj) else "disabled")
        self.anim_menu.configure(state="normal" if hd.is_graphic(obj.kind) and not running else "disabled")
        self.anim_var.set(ANIMATIONS.get(obj.anim or "none", ANIMATIONS["none"]))
        if running:
            for w in (self.label_entry, self.tag_combo, self.color_menu, self.apply_btn, self.delete_btn,
                      self.suggest_btn):
                w.configure(state="disabled")
        self.color_var.set(obj.color if obj.color in hd.COLORS else spec["color"])
        self.mode_menu.configure(state="normal" if obj.kind in BUTTON_KINDS else "disabled")
        if obj.kind in BUTTON_KINDS:
            self.mode_var.set(spec["name"])
        self.target_menu.configure(state="normal" if obj.kind == "nav" else "disabled")
        self.target_var.set(obj.target)
        self.help_label.configure(text=spec["help"])

    def apply_properties(self) -> None:
        obj = self._selected()
        if obj is None:
            self.status("Click an object first.")
            return
        self._snapshot()
        obj.label = self.label_entry.get().strip() or hd.OBJECT_KINDS[obj.kind]["name"]
        if self._taggable(obj):
            obj.tag = self.tag_combo.get().strip()
        if hd.is_graphic(obj.kind):
            obj.anim = ANIM_BY_LABEL.get(self.anim_var.get(), obj.anim)
        obj.color = self.color_var.get()
        if obj.kind in BUTTON_KINDS:
            obj.kind = next(k for k in BUTTON_KINDS if hd.OBJECT_KINDS[k]["name"] == self.mode_var.get())
        if obj.kind == "nav":
            obj.target = self.target_var.get()
        self._changed(f"Updated {obj.label}.")

    @staticmethod
    def _taggable(obj: hd.HmiObject) -> bool:
        return obj.kind in hd.TAGGED_KINDS or obj.kind == "alarm_banner" or hd.is_graphic(obj.kind)

    # ------------------------------------------------------------------ run with simulator

    def _edit_widgets(self) -> list:
        return [self.interview_btn, self.undo_btn, self.delete_btn, self.autobuild_btn, self.bind_btn, self.nav_btn,
                self.add_screen_btn, self.rename_btn, self.delete_screen_btn, self.faceplate_btn, self.model_menu,
                self.theme_menu, *self.palette_buttons.values()]

    def toggle_run(self) -> None:
        if self.runtime is None:
            self.start_run()
        else:
            self.stop_run()

    def start_run(self) -> None:
        try:
            self.runtime = HmiRuntime(self.project, self.design, sim_provider=self.sim_provider)
            _sim = self.runtime.sim
        except Exception as exc:  # noqa: BLE001 - a ladder that will not simulate must not crash the editor
            self.runtime = None
            self.status(f"Could not start the simulator: {exc}")
            return
        self._drag = None
        for w in self._edit_widgets():
            w.configure(state="disabled")
        self.run_btn.configure(text="Stop")
        self.sim_banner.pack(fill="x", padx=12, pady=(0, 4), before=self._quick_row)
        self._load_properties()
        where = "the Programming page simulator" if self.runtime.shared else "its own copy of the ladder"
        self.status(f"{BANNER}. Running against {where}. Press buttons on the screen; press Stop to edit.")
        self._run_tick()

    def stop_run(self) -> None:
        if self._run_job is not None:
            try:
                self.after_cancel(self._run_job)
            except Exception:
                pass
            self._run_job = None
        if self.runtime is not None and self._pressed is not None:
            self.runtime.release(self._pressed)
        self._pressed = None
        self.runtime = None
        for w in self._edit_widgets():
            w.configure(state="normal")
        self.run_btn.configure(text="Run with simulator")
        self.sim_banner.pack_forget()
        self._load_properties()
        self._draw()
        self.status("Stopped the simulation. Back to editing.")

    def _run_tick(self) -> None:
        self._run_job = None
        if self.runtime is None:
            return
        try:
            self.runtime.tick()
        except Exception as exc:  # noqa: BLE001
            self.stop_run()
            self.status(f"Simulation stopped: {exc}")
            return
        self._draw()
        self._run_job = self.after(RUN_MS, self._run_tick)

    def send_number(self) -> None:
        obj = self._selected()
        if self.runtime is None or obj is None:
            self.status("Start Run with simulator and click a Number entry first.")
            return
        why = self.runtime.enter_number(obj, self.value_entry.get().strip())
        self.status(why or f"Sent {self.value_entry.get().strip()} to {obj.tag} (simulator only).")
        self._draw()

    def _run_press(self, obj: hd.HmiObject | None) -> None:
        self.selected_id = obj.id if obj else None
        self._load_properties()
        if obj is None:
            return
        if obj.kind == "nav" and obj.target:
            self.select_screen(obj.target)
            return
        if obj.kind in BUTTON_KINDS:
            why = self.runtime.press(obj)
            if why:
                self.status(why)
            else:
                self._pressed = obj if obj.kind == "momentary" else None
                self.status(f"{obj.label}: {obj.tag} = {'ON' if self.runtime.read_bool(obj.tag) else 'OFF'} "
                            f"(simulator).")
        self._draw()

    def _run_release(self) -> None:
        obj, self._pressed = self._pressed, None
        if obj is not None and self.runtime is not None:
            self.runtime.release(obj)
            self.status(f"{obj.label} released: {obj.tag} = OFF (simulator).")
            self._draw()

    # ------------------------------------------------------------------ export

    def _maker(self) -> str:
        entry = hmi_by_id(self.design.model_id)
        return entry["maker"] if entry else "HMI"

    def _export_text(self) -> str:
        return f"Export for {self._maker()}"

    def export_for_maker(self) -> list:
        from cabinet_studio.services.hmi_export import export_for_maker

        try:
            result = export_for_maker(self.design, self.project)
        except OSError as exc:
            self.status(f"Could not write the export: {exc}")
            return []
        self.status(f"Wrote {len(result['files'])} file(s) for {result['maker']} to {result['folder']}. "
                    f"Tag file: {result['format']}. Import the tags in the maker's software and rebuild the "
                    "screens there - nothing is downloaded into the HMI.")
        return result["files"]

    # ------------------------------------------------------------------ checks / save

    def validate(self) -> list[str]:
        issues = hd.validate_design(self.design, self.project)
        writes = hd.write_tags(self.design)
        write_txt = ", ".join(sorted({t for _s, _l, t in writes})) or "none"
        if issues:
            shown = "; ".join(issues[:6]) + (f"; ... and {len(issues) - 6} more" if len(issues) > 6 else "")
            self.status(f"{len(issues)} thing(s) to fix: {shown}. HMI writes: {write_txt}.")
        else:
            self.status(f"All good - no problems found. HMI writes these PLC tags: {write_txt}.")
        return issues

    def save(self) -> None:
        design = hd.design_from_json(hd.design_to_json(self.design))

        def apply() -> None:
            hd.save_design(self.project, design)

        message = "HMI design saved. HMI sheets are now in the drawings."
        if self.edit_hook is not None:
            self.edit_hook(apply, message)
        else:
            apply()
            if self.on_change:
                self.on_change(message)
        self.dirty = False
        issues = hd.validate_design(self.design, self.project)
        self.status(message + (f" Note: Validate found {len(issues)} thing(s) to check." if issues else ""))

    def close(self) -> None:
        if self.runtime is not None:
            self.stop_run()
        if self.dirty:
            answer = ask_choice(self, self.fonts, "HMI editor", "Save your HMI changes before closing?",
                                [("save", "Save", "primary"), ("discard", "Close without saving", "ghost"),
                                 ("cancel", "Keep editing", "ghost")])
            if answer in (None, "cancel"):
                return
            if answer == "save":
                self.save()
        if self._interview is not None:
            try:
                self._interview.destroy()
            except Exception:
                pass
        self.destroy()

    # ------------------------------------------------------------------ interview

    def run_interview(self) -> None:
        try:
            if self._interview is not None and self._interview.winfo_exists():
                self._interview.lift()
                return
        except Exception:
            pass
        self._interview = HmiInterview(self, self.fonts, self.project, self._interview_done,
                                       answers=dict(self.design.answers))

    def _interview_done(self, answers: dict[str, str]) -> None:
        self._interview = None
        self._snapshot()
        self.design = hd.generate_design(self.project, answers)
        self.screen_name = self.design.screens[0].name
        self.selected_id = None
        self._changed(f"Built {len(self.design.screens)} screen(s) on a {self._model_label()}. "
                      "Change anything you like, then Save.")

    # ------------------------------------------------------------------ canvas

    def _draw(self) -> None:
        cv = self.canvas
        cv.delete("all")
        entry = hmi_by_id(self.design.model_id)
        screen = self._screen()
        if entry is None or screen is None:
            return
        from cabinet_studio.services.hmi_library import screen_area_in

        W = max(cv.winfo_width(), 200)
        H = max(cv.winfo_height(), 200)
        bw, bh = entry["bezel_w_mm"], entry["bezel_h_mm"]
        scale = min((W - 40) / bw, (H - 60) / bh)
        bx, by = (W - bw * scale) / 2, (H - bh * scale) / 2 + 10
        sw_in, sh_in = screen_area_in(entry)
        sw, sh = sw_in * 25.4 * scale, sh_in * 25.4 * scale
        sx, sy = bx + (bw * scale - sw) / 2, by + (bh * scale - sh) / 2
        cols, rows = hd.grid_size(self.design.model_id)
        cw, ch = sw / cols, sh / rows
        self._geom = {"sx": sx, "sy": sy, "cw": cw, "ch": ch, "cols": cols, "rows": rows}
        cv.create_text(W / 2, 14, text=f"{screen.name}  -  {hmi_label(entry)}  -  {entry['resolution_px'][0]}x"
                                       f"{entry['resolution_px'][1]} px", fill="#e7e7ee", font=("Segoe UI", 10))
        cv.create_rectangle(bx, by, bx + bw * scale, by + bh * scale, fill="#23252b", outline="#000000", width=2)
        theme = hd.THEMES.get(self.design.theme, hd.THEMES[hd.DEFAULT_THEME])
        cv.create_rectangle(sx, sy, sx + sw, sy + sh, fill=theme["screen"], outline="#000000")
        grid_ink = "#3a3d44" if self.design.theme == "Dark" else "#c4c7ce"
        for i in range(1, cols):
            cv.create_line(sx + i * cw, sy, sx + i * cw, sy + sh, fill=grid_ink)
        for j in range(1, rows):
            cv.create_line(sx, sy + j * ch, sx + sw, sy + j * ch, fill=grid_ink)
        sel = self._selected()
        sel_group = sel.group if sel is not None and sel.group and sel.group != "nav" else ""
        rt = self.runtime
        for obj in screen.objects:
            x0, y0 = sx + obj.x * cw + 1, sy + obj.y * ch + 1
            x1, y1 = sx + (obj.x + obj.w) * cw - 1, sy + (obj.y + obj.h) * ch - 1
            if hd.is_graphic(obj.kind):
                state = rt.anim_state(obj) if rt is not None else None
                tk_draw_shapes(cv, symbol_shapes(obj.kind, x0, y0, x1 - x0, y1 - y0, state, self.design.theme),
                               tag=f"obj:{obj.id}")
                if rt is None:
                    cv.create_rectangle(x0, y0, x1, y1, outline=grid_ink, dash=(2, 4))
                    if obj.tag:
                        cv.create_text(x0 + 2, y1 - 2, text=obj.tag, anchor="sw", fill="#555555",
                                       font=("Segoe UI", 7))
                if obj.id == self.selected_id and rt is None:
                    cv.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3, outline="#e0301e", width=2, dash=(5, 3))
                    cv.create_rectangle(x1 - HANDLE, y1 - HANDLE, x1 + 2, y1 + 2, fill="#e0301e", outline="")
                continue
            color = hd.COLORS.get(obj.color, "#7a7f8c")
            fill, outline, ink = hd.theme_colors(self.design.theme, obj.color)
            live_on = rt is not None and obj.kind in {"lamp", "momentary", "toggle", "estop_status", "alarm_banner"} \
                and rt.read_bool(obj.tag)
            if obj.kind in {"text", "numeric_display", "numeric_entry", "trend"}:
                fill, outline = ("#ffffff", "#555555") if self.design.theme != "Dark" else (theme["fill"], "#8a8f9c")
                ink = "#000000" if self.design.theme != "Dark" else "#ffffff"
            if obj.kind == "lamp":
                fill, outline = theme["fill"] or "#ffffff", theme["outline"] or "#000000"
                ink = theme["ink"] or "#000000"
            if rt is not None and obj.kind in BUTTON_KINDS and live_on:
                outline = "#e0301e" if self.design.theme.startswith("ISA") else "#ffffff"
            if rt is not None and obj.kind in {"estop_status", "alarm_banner"} and live_on:
                fill, ink = "#d23a2a", "#ffffff"
            cv.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=4 if live_on else 2,
                                tags=(f"obj:{obj.id}",))
            if obj.kind == "lamp":
                lamp_fill = color if rt is None or live_on else "#5a5a5a"
                cv.create_oval(x0 + 3, y0 + 3, x0 + min(x1 - x0, y1 - y0) - 3, y1 - 3, fill=lamp_fill,
                               outline="#000", tags=(f"lamp:{obj.id}",))
            if obj.kind == "trend" and x1 - x0 > 30 and y1 - y0 > 30:
                pts = []
                for i in range(9):
                    pts += [x0 + 6 + (x1 - x0 - 12) * i / 8, y1 - 6 - (y1 - y0 - 30) * ((i * 37) % 9) / 9]
                cv.create_line(*pts, fill=color, width=2)
            if sel_group and obj.group == sel_group and obj.id != self.selected_id:
                cv.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline="#e0301e", width=1, dash=(2, 3))
            text = obj.label + (f"\n[{obj.tag}]" if obj.tag else "")
            if rt is not None and obj.tag:
                if obj.kind in {"numeric_display", "numeric_entry", "trend"}:
                    text = f"{obj.label}\n{rt.read_num(obj.tag):g}"
                elif obj.kind in {"lamp", "momentary", "toggle", "estop_status"}:
                    text = f"{obj.label}\n{'ON' if live_on else 'OFF'}"
            tx = x0 + (min(x1 - x0, y1 - y0) + 2 if obj.kind == "lamp" else 4)
            cv.create_text(tx, (y0 + y1) / 2, text=text, anchor="w", fill=ink, width=max(20, x1 - tx - 2),
                           font=("Segoe UI", 8))
            if obj.id == self.selected_id and rt is None:
                cv.create_rectangle(x0 - 3, y0 - 3, x1 + 3, y1 + 3, outline="#e0301e", width=2, dash=(5, 3))
                cv.create_rectangle(x1 - HANDLE, y1 - HANDLE, x1 + 2, y1 + 2, fill="#e0301e", outline="")
        if rt is not None:
            cv.create_rectangle(sx, sy - 22, sx + sw, sy - 2, fill="#b3261e", outline="", tags=("sim_banner",))
            cv.create_text(sx + sw / 2, sy - 12, text=BANNER, fill="#ffffff", font=("Segoe UI", 9, "bold"),
                           tags=("sim_banner",))

    def _hit(self, x: float, y: float) -> tuple[hd.HmiObject | None, bool]:
        g, screen = self._geom, self._screen()
        if g is None or screen is None:
            return None, False
        sel = self._selected()
        if sel is not None:
            x1 = g["sx"] + (sel.x + sel.w) * g["cw"]
            y1 = g["sy"] + (sel.y + sel.h) * g["ch"]
            if x1 - HANDLE - 3 <= x <= x1 + 4 and y1 - HANDLE - 3 <= y <= y1 + 4:
                return sel, True
        for obj in reversed(screen.objects):
            x0, y0 = g["sx"] + obj.x * g["cw"], g["sy"] + obj.y * g["ch"]
            if x0 <= x <= x0 + obj.w * g["cw"] and y0 <= y <= y0 + obj.h * g["ch"]:
                return obj, False
        return None, False

    def _press(self, event) -> None:
        if self.runtime is not None:
            self._run_press(self._hit(event.x, event.y)[0])
            return
        obj, resize = self._hit(event.x, event.y)
        self.selected_id = obj.id if obj else None
        self._drag = None
        if obj is not None:
            members = [obj]
            if not resize and obj.group and obj.group != "nav":
                members = hd.group_objects(self._screen(), obj.group) or [obj]
            self._drag = {"x": event.x, "y": event.y, "resize": resize, "orig": (obj.x, obj.y, obj.w, obj.h),
                          "members": [(o, o.x, o.y) for o in members], "before": hd.design_to_json(self.design)}
        self._load_properties()
        self._draw()

    def _motion(self, event) -> None:
        obj, d, g = self._selected(), self._drag, self._geom
        if obj is None or d is None or g is None:
            return
        dc = round((event.x - d["x"]) / g["cw"])
        dr = round((event.y - d["y"]) / g["ch"])
        x, y, w, h = d["orig"]
        if d["resize"]:
            obj.w, obj.h = max(1, w + dc), max(1, h + dr)
            hd.clamp_object(self.design, obj)
        else:
            members = d["members"]
            dc = max(dc, -min(ox for _o, ox, _oy in members))
            dc = min(dc, g["cols"] - max(ox + o.w for o, ox, _oy in members))
            dr = max(dr, -min(oy for _o, _ox, oy in members))
            dr = min(dr, g["rows"] - max(oy + o.h for o, _ox, oy in members))
            for o, ox, oy in members:
                o.x, o.y = ox + dc, oy + dr
        self._draw()

    def _release(self, _event) -> None:
        if self.runtime is not None:
            self._run_release()
            return
        obj, d = self._selected(), self._drag
        self._drag = None
        if obj is None or d is None:
            return
        if (obj.x, obj.y, obj.w, obj.h) != d["orig"]:
            self._undo.append(d["before"])
            del self._undo[:-UNDO_LIMIT]
            others = [o for o in self._screen().objects if o is not obj and hd.overlaps(o, obj)]
            self._changed(("Resized " if d["resize"] else "Moved ") + obj.label
                          + (" - it now overlaps another object." if others else "."))


class HmiInterview(ctk.CTkToplevel):
    """One question at a time with a suggested answer; Accept all takes every suggestion."""

    def __init__(self, master, fonts, project, on_done, answers: dict[str, str] | None = None) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.project = project
        self.on_done = on_done
        self.answers: dict[str, str] = {k: v for k, v in (answers or {}).items() if k in hd.QUESTION_KEYS}
        self.index = 0
        self.title("HMI interview")
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        center_on_parent(self, 620, 400, master)
        f = fonts
        section_label(self, "HMI INTERVIEW", f.tiny).pack(anchor="w", padx=18, pady=(14, 2))
        self.step_label = ctk.CTkLabel(self, text="", font=f.tiny, text_color=MUTED, anchor="w")
        self.step_label.pack(fill="x", padx=18)
        self.prompt = ctk.CTkLabel(self, text="", font=f.heading, text_color=TEXT, anchor="w", justify="left",
                                   wraplength=580)
        self.prompt.pack(fill="x", padx=18, pady=(6, 2))
        self.help = ctk.CTkLabel(self, text="", font=f.small, text_color=MUTED, anchor="w", justify="left",
                                 wraplength=580)
        self.help.pack(fill="x", padx=18)
        self.choice_var = tk.StringVar(value="")
        self.choice_menu = ctk.CTkOptionMenu(self, values=[""], variable=self.choice_var, font=f.body, width=560,
                                             dynamic_resizing=False)
        self.choice_menu.pack(padx=18, pady=10, anchor="w")
        attach(self.choice_menu, "Pick an answer. The suggested one is already chosen.", "Answer")
        self.reason = ctk.CTkLabel(self, text="", font=f.small, text_color=CYAN, anchor="w", justify="left",
                                   wraplength=580)
        self.reason.pack(fill="x", padx=18)
        nav = ctk.CTkFrame(self, fg_color=BG)
        nav.pack(side="bottom", fill="x", padx=14, pady=12)

        def btn(text, cmd, tip, primary=False, width=110):
            b = (primary_button if primary else ghost_button)(nav, text, cmd, f.small, width=width)
            attach(b, tip, text)
            return b

        self.back_btn = btn("Back", self.back, "Go back to the previous question.")
        self.back_btn.pack(side="left", padx=3)
        self.cancel_btn = btn("Cancel", self.cancel, "Close the interview without changing your HMI.")
        self.cancel_btn.pack(side="left", padx=3)
        self.next_btn = btn("Next", self.next, "Keep this answer and go to the next question.", primary=True)
        self.next_btn.pack(side="right", padx=3)
        self.accept_btn = btn("Accept all", self.accept_all, "Use the suggested answer for every question that is "
                              "left and build the HMI now.", width=120)
        self.accept_btn.pack(side="right", padx=3)
        self._show()
        self.after(30, self._raise)

    def _raise(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _show(self) -> None:
        key = hd.QUESTION_KEYS[self.index]
        q = hd.hmi_question(self.project, self.answers, key)
        self.step_label.configure(text=f"Question {self.index + 1} of {len(hd.QUESTION_KEYS)}")
        self.prompt.configure(text=q["prompt"])
        self.help.configure(text=q["help"])
        self.choice_menu.configure(values=q["choices"])
        current = self.answers.get(key)
        self.choice_var.set(current if current in q["choices"] else q["default"])
        self.reason.configure(text=f"Suggested: {q['default']}. {q['reason']}")
        last = self.index == len(hd.QUESTION_KEYS) - 1
        self.next_btn.configure(text="Build HMI" if last else "Next")
        self.back_btn.configure(state="normal" if self.index else "disabled")

    def _keep(self) -> None:
        key = hd.QUESTION_KEYS[self.index]
        old = self.answers.get(key)
        self.answers[key] = self.choice_var.get()
        # Later answers depend on earlier ones (maker -> size -> model).
        if key in ("hmi_maker", "hmi_size") and old != self.answers[key]:
            for later in ("hmi_size", "hmi_model") if key == "hmi_maker" else ("hmi_model",):
                self.answers.pop(later, None)

    def next(self) -> None:
        self._keep()
        if self.index == len(hd.QUESTION_KEYS) - 1:
            self._finish()
            return
        self.index += 1
        self._show()

    def back(self) -> None:
        if self.index:
            self.index -= 1
            self._show()

    def accept_all(self) -> None:
        self._keep()
        self._finish()

    def _finish(self) -> None:
        answers = hd.default_answers(self.project, self.answers)
        self.destroy()
        self.on_done(answers)

    def cancel(self) -> None:
        self.destroy()
        master = self.master
        if getattr(master, "_interview", None) is self:
            master._interview = None
