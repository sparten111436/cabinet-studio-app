"""Apply Cabinet Studio v3 ladder IR + scan sim + PLCopen on the mvp tree.

Run from mvp root (or pass --root). Creates *.bak-v3-* backups before edits.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
HERE = Path(__file__).resolve().parent


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    bak = path.with_name(path.name + f".bak-v3-{STAMP}")
    shutil.copy2(path, bak)
    return bak


def write_new(dest: Path, src: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        backup(dest)
    shutil.copy2(src, dest)
    print(f"wrote {dest}")


VIEWER_IMPORT_OLD = """from cabinet_studio.services.programming import (
    LEARNING_NOTE,
    PROGRAM_QUESTIONS,
    add_rung,
    build_starter_program,
    cabinet_device_tags,
    default_design_answers,
    delete_rung,
    device_hover_detail,
    devices_by_tag,
    edit_rung,
    empty_program,
    flatten_contacts,
    format_hmi_text,
    format_plc_text,
    program_from_dict,
    program_looks_edited,
    program_questions_for_project,
    program_to_dict,
    refresh_plc_text,
    rung_has_seal_in,
    simulation_rung_tags,
)
"""

VIEWER_IMPORT_NEW = """from cabinet_studio.services.ladder_ir import program_to_ladder_ir
from cabinet_studio.services.ladder_sim import ScanSimulator
from cabinet_studio.services.plcopen_xml import (
    export_program_to_plcopen_xml,
    import_plcopen_xml_to_program,
)
from cabinet_studio.services.programming import (
    LEARNING_NOTE,
    PROGRAM_QUESTIONS,
    add_rung,
    build_starter_program,
    cabinet_device_tags,
    default_design_answers,
    delete_rung,
    device_hover_detail,
    devices_by_tag,
    edit_rung,
    empty_program,
    flatten_contacts,
    format_hmi_text,
    format_plc_text,
    program_from_dict,
    program_looks_edited,
    program_questions_for_project,
    program_to_dict,
    refresh_plc_text,
    rung_has_seal_in,
    simulation_rung_tags,
)
"""

SIM_INIT_OLD = """        self._sim_running = False
        self._sim_after: str | None = None
        self._sim_index = -1
        self._sim_flash_on = False
        self._sim_flash_count = 0
        self._sim_active_tags: set[str] = set()
        self._sim_pulse_tags: set[str] = set()
        self._sim_status_var = None  # set after widgets
"""

SIM_INIT_NEW = """        self._sim_running = False
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
"""

SIM_BAR_OLD = """        primary_button(sim_bar, \"\\u25b6  Simulate\", self._sim_toggle_run, fonts.body, width=140).pack(side=\"left\", padx=6, pady=6)
        ghost_button(sim_bar, \"Step\", self._sim_step, fonts.body, width=90).pack(side=\"left\", padx=4, pady=6)
        ghost_button(sim_bar, \"Stop\", self._sim_stop, fonts.body, width=90).pack(side=\"left\", padx=4, pady=6)
        self._sim_status = ctk.CTkLabel(
            sim_bar,
            text=\"Sim off (educational — not a live PLC). Run the ladder program here.\",
            font=fonts.small,
            text_color=MUTED,
            anchor=\"w\",
        )
        self._sim_status.pack(side=\"left\", padx=12, pady=8)
"""

# We'll match more flexibly with regex for the play button character.

TOOLS_EXPORT_OLD = """        ghost_button(tools, \"Print\", self.print_ladder, fonts.small, width=90).pack(side=\"left\", padx=4)
        ghost_button(tools, \"Export Ladder\", self.export_ladder_artifact, fonts.small, width=120).pack(side=\"left\", padx=4)
"""

TOOLS_EXPORT_NEW = """        ghost_button(tools, \"Print\", self.print_ladder, fonts.small, width=90).pack(side=\"left\", padx=4)
        ghost_button(tools, \"Export Ladder\", self.export_ladder_artifact, fonts.small, width=120).pack(side=\"left\", padx=4)
        ghost_button(tools, \"Export PLCopen\", self.export_plcopen_xml, fonts.small, width=130).pack(side=\"left\", padx=4)
        ghost_button(tools, \"Import PLCopen\", self.import_plcopen_xml, fonts.small, width=130).pack(side=\"left\", padx=4)
"""

SIM_SECTION_MARKER = "    # --- Educational ladder simulation (not a live PLC) --------------------"

SIM_SECTION_NEW = r'''    # --- Educational ladder simulation (not a live PLC) --------------------

    def _sim_rungs(self) -> list[dict]:
        return list(self.program.get("rungs") or [])

    def _sim_set_status(self, text: str) -> None:
        try:
            self._sim_status.configure(text=text)
        except Exception:
            pass

    def _ensure_scan_sim(self, *, reset: bool = False) -> ScanSimulator:
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
        for tag in inputs:
            val = sim.read(tag)
            btn = ctk.CTkButton(
                self._force_strip,
                text=f"{tag}={'1' if val else '0'}",
                width=max(90, 12 * len(tag) + 36),
                height=26,
                font=self.fonts.tiny,
                fg_color="#2f6bff" if val else ENTRY,
                hover_color="#2457d6",
                text_color=TEXT,
                command=lambda t=tag: self._sim_toggle_force(t),
            )
            btn.pack(side="left", padx=3, pady=4)
            self._force_buttons[tag] = btn
        if outputs:
            ctk.CTkLabel(
                self._force_strip,
                text="  Coils:",
                font=self.fonts.tiny,
                text_color=MUTED,
            ).pack(side="left", padx=(10, 4), pady=4)
            for tag in outputs:
                val = sim.read(tag)
                ctk.CTkLabel(
                    self._force_strip,
                    text=f"{tag}={'ON' if val else 'off'}",
                    font=self.fonts.tiny,
                    text_color=LADDER_ACTIVE if val else MUTED,
                ).pack(side="left", padx=4, pady=4)

    def _sim_toggle_force(self, tag: str) -> None:
        sim = self._ensure_scan_sim()
        sim.toggle_force(tag)
        # One scan so coils update immediately after forcing an input.
        result = sim.scan_once()
        self._sim_apply_scan_result(result, mode="FORCE")
        self._rebuild_force_strip()

    def _sim_apply_scan_result(self, result: dict, *, mode: str) -> None:
        self._sim_active_tags = {t for t, v in (result.get("vars") or {}).items() if v}
        # Pulse weld-place style coils when ON
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
        on_coils = [
            t for t in sorted(self._ensure_scan_sim().output_tags()) if result.get("vars", {}).get(t)
        ]
        coil_bit = (", ".join(on_coils) if on_coils else "none")
        self._sim_set_status(
            f"Sim {mode} scan #{result.get('scan_count', 0)} · coils ON: {coil_bit}  · educational only"
        )
        self._draw_ladder(preserve_scroll=True)

    def _sim_toggle_run(self) -> None:
        self._show_tab("ladder")
        if self._sim_running:
            self._sim_stop()
            return
        if not self._sim_rungs():
            self._sim_set_status("Sim: no rungs to run")
            return
        self._ensure_scan_sim(reset=True)
        self._rebuild_force_strip()
        self._sim_running = True
        self._sim_set_status("Sim RUN (educational scan) — toggle Force inputs")
        self._sim_scan_tick()

    def _sim_step(self) -> None:
        self._show_tab("ladder")
        self._sim_cancel_timer()
        self._sim_running = False
        if not self._sim_rungs():
            self._sim_set_status("Sim: no rungs to step")
            return
        sim = self._ensure_scan_sim()
        result = sim.scan_once()
        self._sim_apply_scan_result(result, mode="STEP")
        self._rebuild_force_strip()

    def _sim_stop(self) -> None:
        self._sim_cancel_timer()
        self._sim_running = False
        self._sim_index = -1
        self._sim_flash_on = False
        self._sim_flash_count = 0
        self._sim_active_tags = set()
        self._sim_pulse_tags = set()
        if self._scan_sim is not None:
            # Keep forces so Warren can resume; clear live highlights only.
            pass
        self._sim_set_status("Sim off (educational — not a live PLC)")
        try:
            self._rebuild_force_strip()
        except Exception:
            pass
        self._draw_ladder(preserve_scroll=True)

    def _sim_cancel_timer(self) -> None:
        if self._sim_after is not None:
            try:
                self.after_cancel(self._sim_after)
            except Exception:
                pass
            self._sim_after = None

    def _sim_scan_tick(self) -> None:
        self._sim_after = None
        if not self._sim_running:
            return
        if not self._sim_rungs():
            self._sim_stop()
            return
        sim = self._ensure_scan_sim()
        result = sim.scan_once()
        self._sim_apply_scan_result(result, mode="RUN")
        # Refresh force labels lightly every few scans
        if int(result.get("scan_count") or 0) % 5 == 0:
            self._rebuild_force_strip()
        self._sim_after = self.after(120, self._sim_scan_tick)

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
        mode = "RUN" if self._sim_running or then_advance else "STEP"
        self._sim_set_status(f"Sim {mode} (legacy walk): {bit}  · educational only")
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
        if not self._confirm_replace_program():
            return
        try:
            xml = Path(path).read_text(encoding="utf-8")
            program = import_plcopen_xml_to_program(xml)
            # Refresh plc_text from imported rungs
            program = program_from_dict(program)
            program["plc_text"] = format_plc_text(program.get("rungs") or [], cabinet_device_tags(self.project))
            program["text_edited"] = False
        except Exception as exc:
            self.status.configure(text=f"PLCopen import failed: {exc}")
            return
        self._apply_built_program(program, status=f"Imported PLCopen XML from {Path(path).name}")
        self._scan_sim = None
        self._rebuild_force_strip()


'''


def patch_viewer(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    original = text
    backup(path)

    if "from cabinet_studio.services.ladder_sim import ScanSimulator" not in text:
        if VIEWER_IMPORT_OLD not in text:
            raise SystemExit("programming_viewer import block not found — abort")
        text = text.replace(VIEWER_IMPORT_OLD, VIEWER_IMPORT_NEW, 1)

    if "self._scan_sim" not in text:
        if SIM_INIT_OLD not in text:
            raise SystemExit("sim init block not found — abort")
        text = text.replace(SIM_INIT_OLD, SIM_INIT_NEW, 1)

    if "export_plcopen_xml" not in text:
        if TOOLS_EXPORT_OLD not in text:
            # try without escaping differences
            alt = '        ghost_button(tools, "Print", self.print_ladder, fonts.small, width=90).pack(side="left", padx=4)\n        ghost_button(tools, "Export Ladder", self.export_ladder_artifact, fonts.small, width=120).pack(side="left", padx=4)\n'
            if alt not in text:
                raise SystemExit("tools export buttons not found — abort")
            text = text.replace(alt, alt + '        ghost_button(tools, "Export PLCopen", self.export_plcopen_xml, fonts.small, width=130).pack(side="left", padx=4)\n        ghost_button(tools, "Import PLCopen", self.import_plcopen_xml, fonts.small, width=130).pack(side="left", padx=4)\n', 1)
        else:
            text = text.replace(TOOLS_EXPORT_OLD, TOOLS_EXPORT_NEW, 1)

    # Insert force strip after sim_status pack
    if "_force_strip" not in text:
        pattern = re.compile(
            r'(self\._sim_status\.pack\(side="left", padx=12, pady=8\)\n)',
            re.M,
        )
        insert = (
            r'\1\n'
            r'        # v3 force / I/O strip for educational scan simulator\n'
            r'        self._force_wrap = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=4, border_width=1, border_color=BORDER)\n'
            r'        self._force_wrap.pack(fill="x", padx=12, pady=(0, 6))\n'
            r'        self._force_strip = ctk.CTkFrame(self._force_wrap, fg_color="transparent")\n'
            r'        self._force_strip.pack(fill="x", padx=4, pady=2)\n'
            r'        ctk.CTkLabel(\n'
            r'            self._force_strip,\n'
            r'            text="Force inputs appear when Simulate / Step runs (educational scan).",\n'
            r'            font=fonts.tiny,\n'
            r'            text_color=MUTED,\n'
            r'        ).pack(side="left", padx=6, pady=4)\n'
        )
        text2, n = pattern.subn(insert, text, count=1)
        if n != 1:
            raise SystemExit("could not insert force strip after sim status")
        text = text2

    # Replace sim section through close()
    marker = SIM_SECTION_MARKER
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit("sim section marker not found")
    close_idx = text.find("\n    def close(self) -> None:", idx)
    if close_idx < 0:
        raise SystemExit("close() not found after sim section")
    text = text[:idx] + SIM_SECTION_NEW + text[close_idx + 1 :]

    # Update meta label to mention v3 educational ladder
    text = text.replace(
        'text=f"{project.name}  |  Learning program - not a live PLC download"',
        'text=f"{project.name}  |  v3 Educational Ladder + scan sim — not a live PLC download"',
        1,
    )

    # After bind_project / apply program, reset scan sim
    if "self._scan_sim = None" not in text.split("def bind_project")[1][:800]:
        text = text.replace(
            "    def bind_project(self, project: Project) -> None:\n",
            "    def bind_project(self, project: Project) -> None:\n"
            "        self._scan_sim = None\n",
            1,
        )

    if text == original:
        print("viewer: no changes?")
    path.write_text(text, encoding="utf-8")
    print(f"patched {path}")


def bump_version(init_path: Path) -> None:
    backup(init_path)
    text = init_path.read_text(encoding="utf-8")
    text2 = re.sub(r'__version__\s*=\s*"[^"]*"', '__version__ = "0.3.0"', text, count=1)
    if text2 == text:
        if '__version__ = "0.3.0"' in text:
            print("version already 0.3.0")
            return
        raise SystemExit("could not bump version")
    init_path.write_text(text2, encoding="utf-8")
    print(f"version -> 0.3.0 in {init_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True, help="mvp root containing cabinet_studio/")
    args = ap.parse_args()
    root: Path = args.root
    pkg = root / "cabinet_studio"
    if not pkg.is_dir():
        print(f"missing {pkg}", file=sys.stderr)
        return 1

    services = pkg / "services"
    write_new(services / "ladder_ir.py", HERE / "cabinet_studio" / "services" / "ladder_ir.py")
    write_new(services / "ladder_sim.py", HERE / "cabinet_studio" / "services" / "ladder_sim.py")
    write_new(services / "plcopen_xml.py", HERE / "cabinet_studio" / "services" / "plcopen_xml.py")

    tests = root / "tests"
    write_new(tests / "test_ladder_ir.py", HERE / "tests" / "test_ladder_ir.py")
    write_new(tests / "test_ladder_sim.py", HERE / "tests" / "test_ladder_sim.py")
    write_new(tests / "test_plcopen_xml.py", HERE / "tests" / "test_plcopen_xml.py")

    bump_version(pkg / "__init__.py")
    patch_viewer(pkg / "ui" / "programming_viewer.py")

    # Light note in programming.py module docstring / helper export (optional sync)
    prog = services / "programming.py"
    if prog.exists():
        backup(prog)
        ptxt = prog.read_text(encoding="utf-8")
        if "def program_ladder_ir" not in ptxt:
            ptxt = ptxt.rstrip() + "\n\n\n" + (
                "def program_ladder_ir(program, *, project_name: str = \"\", devices=None):\n"
                "    \"\"\"v3 helper: project.program → educational ladder IR (does not mutate).\"\"\"\n"
                "    from cabinet_studio.services.ladder_ir import program_to_ladder_ir\n"
                "\n"
                "    return program_to_ladder_ir(program, project_name=project_name, devices=devices)\n"
            )
            prog.write_text(ptxt, encoding="utf-8")
            print(f"appended program_ladder_ir helper to {prog}")

    print("OK apply_v3_ladder complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
