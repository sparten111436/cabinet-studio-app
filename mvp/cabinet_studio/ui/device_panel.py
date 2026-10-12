"""PLC / Device window: export import-ready files for the selected PLC or HMI, assign I/O, and a live
Ethernet tag link for testing (connect, info, tag compare, watch, careful writes).

Network work runs on a background thread; results come back through a queue polled with after(),
so the window never freezes. Program download / upload is done in the maker's software.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk

import customtkinter as ctk

from cabinet_studio.services import device_link as dl
from cabinet_studio.services.io_assign import assign_io, detect_profile, summary_text, write_io_csv
from cabinet_studio.services.plc_export import device_choices, export_folder, write_hmi_exports, write_plc_exports
from cabinet_studio.ui.hover_tip import attach
from cabinet_studio.ui.theme import BG, MUTED, ORANGE, PANEL, TEXT, ghost_button, primary_button, section_label
from cabinet_studio.ui.util import center_on_parent

HONEST = ("Full program download into Allen-Bradley, Siemens and Omron PLCs is done in the maker's software "
          "(Studio 5000 / CCW, TIA Portal, Sysmac Studio / CX-Programmer). Cabinet Studio writes import-ready "
          "files and offers a live Ethernet tag link for testing. Safety tags are never written; the software is "
          "never the safety function (NFPA 79 / ISO 13849).")
DOWNLOAD_TEXT = ("Program download / upload is not done over the wire by Cabinet Studio.\n\n"
                 "1. Click 'Export files' - the program, tag tables, I/O list and README.txt are written to the "
                 "plc folder next to your drawings.\n"
                 "2. Open README.txt and follow the steps for your PLC maker to import them.\n"
                 "3. Download from the maker's software, standing at the machine.\n\n"
                 "To upload (read back) a program, use the maker's software 'Upload' and then export PLCopen XML or "
                 "L5X from it; Cabinet Studio can import PLCopen XML on the Programming page.")
NO_DEVICE = "(no PLC or HMI in the cabinet)"
POLL_MS = 80
WATCH_MS = 1000


def open_device_panel(master, fonts, project, *, on_change=None, save_path=None, existing=None):
    try:
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return existing
    except Exception:
        pass
    return DevicePanel(master, fonts, project, on_change=on_change, save_path=save_path)


class DevicePanel(ctk.CTkToplevel):
    def __init__(self, master, fonts, project, *, on_change=None, save_path=None) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.project = project
        self.on_change = on_change
        self.save_path = save_path
        self.link: dl.DeviceLink | None = None
        self.watch: list[str] = []
        self.watching = False
        self.busy = False
        self._q: queue.Queue = queue.Queue()
        self._closed = False
        self.choices = device_choices(project)
        self.title("PLC / Device")
        self.minsize(980, 640)
        self.protocol("WM_DELETE_WINDOW", self.close)
        center_on_parent(self, 1080, 720, master)
        self._build()
        self._on_device(self.device_var.get())
        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------ layout

    def _btn(self, parent, text, cmd, tip, *, primary=False, width=110):
        btn = (primary_button if primary else ghost_button)(parent, text, cmd, self.fonts.small, width=width)
        attach(btn, tip, text)
        btn.pack(side="left", padx=3, pady=3)
        return btn

    def _build(self) -> None:
        f = self.fonts
        head = ctk.CTkFrame(self, fg_color=BG)
        head.pack(fill="x", padx=12, pady=(10, 2))
        section_label(head, "PLC / DEVICE", f.tiny).pack(side="left", padx=(0, 8))
        labels = [c[0] for c in self.choices] or [NO_DEVICE]
        self.device_var = tk.StringVar(value=labels[0])
        self.device_menu = ctk.CTkOptionMenu(head, values=labels, variable=self.device_var, command=self._on_device,
                                             width=360, font=f.small, dynamic_resizing=False)
        self.device_menu.pack(side="left", padx=4)
        attach(self.device_menu, "Pick the PLC or HMI to work with. Exports and the live link follow its maker "
                                 "and model.", "Device")
        close = ghost_button(head, "Close", self.close, f.small, width=80)
        close.pack(side="right", padx=3)
        attach(close, "Disconnects (if connected) and closes this window.", "Close")
        ctk.CTkLabel(self, text=HONEST, font=f.small, text_color=ORANGE, wraplength=1020, justify="left",
                     anchor="w").pack(fill="x", padx=14, pady=(0, 4))

        files = ctk.CTkFrame(self, fg_color=PANEL)
        files.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(files, text="Files:", font=f.small, text_color=MUTED).pack(side="left", padx=(8, 2))
        self.assign_btn = self._btn(files, "Assign I/O", self.assign,
                                    "Gives every pushbutton, sensor, light, coil and so on a PLC input or output "
                                    "address in this PLC's own format. Addresses already given are kept.",
                                    primary=True)
        self.iolist_btn = self._btn(files, "I/O list CSV", self.export_io_csv,
                                    "Writes the I/O list (tag, device, address, module, terminal, wire #) as a "
                                    "spreadsheet file in the plc folder.")
        self.export_btn = self._btn(files, "Export files", self.export,
                                    "Writes import-ready files for the selected PLC or HMI (program, tag tables, "
                                    "I/O list) and a README with step-by-step import instructions.", primary=True)
        self.folder_btn = self._btn(files, "Open folder", self.open_folder,
                                    "Opens the folder with the exported files in Windows Explorer.")
        self.download_btn = self._btn(files, "Download / upload program", self.show_download_help,
                                      "Explains how to put the program into the real PLC with the maker's "
                                      "software. Cabinet Studio does not download over the wire.", width=190)

        conn = ctk.CTkFrame(self, fg_color=PANEL)
        conn.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(conn, text="Live link:", font=f.small, text_color=MUTED).pack(side="left", padx=(8, 2))
        self.driver_var = tk.StringVar(value=dl.DRIVER_CHOICES[0])
        self.driver_menu = ctk.CTkOptionMenu(conn, values=list(dl.DRIVER_CHOICES), variable=self.driver_var,
                                             width=290, font=f.small, dynamic_resizing=False)
        self.driver_menu.pack(side="left", padx=3)
        attach(self.driver_menu, "How to talk to the PLC. Chosen from the PLC maker; Simulated PLC needs no "
                                 "network and is for practice.", "Driver")
        ctk.CTkLabel(conn, text="IP", font=f.small, text_color=TEXT).pack(side="left", padx=(6, 2))
        self.ip_entry = ctk.CTkEntry(conn, width=130, font=f.small, placeholder_text="192.168.1.10")
        self.ip_entry.pack(side="left", padx=2)
        attach(self.ip_entry, "The PLC's IP address on the machine network.", "IP address")
        ctk.CTkLabel(conn, text="Slot", font=f.small, text_color=TEXT).pack(side="left", padx=(6, 2))
        self.slot_entry = ctk.CTkEntry(conn, width=44, font=f.small)
        self.slot_entry.insert(0, "0")
        self.slot_entry.pack(side="left", padx=2)
        attach(self.slot_entry, "ControlLogix: the CPU slot in the rack (usually 0). Siemens: CPU slot (1 for "
                                "S7-1200/1500, 2 for S7-300). Others ignore it.", "Slot")
        self.connect_btn = self._btn(conn, "Connect", self.connect,
                                     "Connects to the PLC and reads its name, model and firmware. For an HMI it "
                                     "only checks that the panel answers on the network.", primary=True, width=90)
        self.disconnect_btn = self._btn(conn, "Disconnect", self.disconnect, "Closes the connection.", width=90)
        self.info_btn = self._btn(conn, "Read info", self.read_info,
                                  "Reads the controller's model, firmware and mode again.", width=90)
        self.compare_btn = self._btn(conn, "Compare tags", self.compare,
                                     "Uploads the PLC's tag list and compares it to this project: tags missing in "
                                     "the PLC, extra tags, and type mismatches.", width=110)

        mid = ctk.CTkFrame(self, fg_color=BG)
        mid.pack(fill="both", expand=True, padx=12, pady=3)
        left = ctk.CTkFrame(mid, fg_color=PANEL)
        left.pack(side="left", fill="y", padx=(0, 6))
        ctk.CTkLabel(left, text="Watch", font=f.small, text_color=MUTED).pack(anchor="w", padx=8, pady=(6, 0))
        wrow = ctk.CTkFrame(left, fg_color="transparent")
        wrow.pack(fill="x", padx=4)
        self.watch_var = tk.StringVar(value="")
        self.watch_menu = ctk.CTkComboBox(wrow, values=[""], variable=self.watch_var, width=200, font=f.small)
        self.watch_menu.pack(side="left", padx=3, pady=3)
        attach(self.watch_menu, "Type or pick a tag (or an address such as %M10.0 or D100) to watch.", "Watch tag")
        self.add_watch_btn = self._btn(wrow, "Add", self.add_watch, "Adds the tag to the watch list.", width=56)
        wrow2 = ctk.CTkFrame(left, fg_color="transparent")
        wrow2.pack(fill="x", padx=4)
        self.remove_watch_btn = self._btn(wrow2, "Remove", self.remove_watch,
                                          "Removes the tag in the box from the watch list.", width=70)
        self.add_io_btn = self._btn(wrow2, "Add all I/O", self.add_all_io,
                                    "Adds every I/O point from the I/O list to the watch list.", width=90)
        self.watch_btn = self._btn(wrow2, "Start watch", self.toggle_watch,
                                   "Reads the watched tags about once a second. Click again to stop.", width=96)
        self.watch_box = ctk.CTkTextbox(left, width=340, font=f.small)
        self.watch_box.pack(fill="both", expand=True, padx=6, pady=6)

        ctk.CTkLabel(left, text="Write (non-safety, non-I/O tags only)", font=f.small,
                     text_color=MUTED).pack(anchor="w", padx=8)
        wr = ctk.CTkFrame(left, fg_color="transparent")
        wr.pack(fill="x", padx=4)
        self.write_tag = ctk.CTkEntry(wr, width=150, font=f.small, placeholder_text="HMI_Start")
        self.write_tag.pack(side="left", padx=3)
        attach(self.write_tag, "Tag to write, for example an HMI_ bit or a setpoint. Safety tags and physical "
                               "I/O are always refused.", "Write tag")
        self.write_value = ctk.CTkEntry(wr, width=70, font=f.small, placeholder_text="1")
        self.write_value.pack(side="left", padx=3)
        attach(self.write_value, "Value: 1 / 0 for a bit, or a number.", "Value")
        self.safe_var = tk.BooleanVar(value=False)
        self.safe_check = ctk.CTkCheckBox(left, text="I am at the machine and it is safe", variable=self.safe_var,
                                          font=f.small)
        self.safe_check.pack(anchor="w", padx=8, pady=3)
        attach(self.safe_check, "Writing changes a running machine. Tick this only when you can see the machine "
                                "and nobody can be hurt.", "Safety confirmation")
        self.write_btn = self._btn(left, "Write", self.write, "Writes the value to the PLC tag after the safety "
                                   "checks.", width=80)

        self.out = ctk.CTkTextbox(mid, font=f.small)
        self.out.pack(side="left", fill="both", expand=True)
        self.status_label = ctk.CTkLabel(self, text="Ready.", font=f.small, text_color=MUTED, anchor="w")
        self.status_label.pack(fill="x", padx=14, pady=(0, 8))

    # ------------------------------------------------------------------ helpers

    def status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def say(self, text: str) -> None:
        self.out.insert("end", text.rstrip() + "\n\n")
        self.out.see("end")

    def selected_item(self):
        for label, item in self.choices:
            if label == self.device_var.get():
                return item
        return None

    def _is_hmi(self) -> bool:
        item = self.selected_item()
        return item is not None and item.type_id == "hmi"

    def _plc_id(self):
        item = self.selected_item()
        return item.id if item is not None and item.type_id == "plc" else None

    def _on_device(self, _label=None) -> None:
        item = self.selected_item()
        if item is None:
            self.status("Add a PLC (and HMI) to the cabinet to use this window.")
            return
        self.ip_entry.delete(0, "end")
        self.ip_entry.insert(0, (item.fields.get("ip_address") or "").strip())
        if item.type_id == "plc":
            fam = detect_profile(item).family
            self.driver_var.set(dl.DRIVER_CHOICES[dl.FAMILY_TO_CHOICE.get(fam, 0)])
            self.watch_menu.configure(values=self._tag_values())
        self.status(f"Selected {self.device_var.get()}.")

    def _tag_values(self) -> list[str]:
        try:
            return dl.DeviceLink(dl.FakeDriver(), self.project, self._plc_id()).project_tags() or [""]
        except Exception:
            return [""]

    def _changed(self, message: str) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(message)
        except TypeError:
            self.on_change()

    def _run(self, label: str, work, done) -> None:
        """Run work() on a thread; done(result) on the Tk thread. Errors become plain words."""
        if self.busy:
            self.status("Still busy with the last request...")
            return
        self.busy = True
        self.status(label + "...")
        ip = self.ip_entry.get().strip()

        def job():
            try:
                self._q.put((done, work(), None))
            except Exception as exc:  # noqa: BLE001 - every failure is reported in plain words
                self._q.put((done, None, dl.plain_error(exc, ip)))

        threading.Thread(target=job, daemon=True).start()

    def _poll(self) -> None:
        if self._closed:
            return
        try:
            while True:
                done, result, err = self._q.get_nowait()
                self.busy = False
                if err:
                    self.say("Problem: " + err)
                    self.status("Problem - see the message.")
                    if done == self._watch_done:
                        self._set_watch(False)
                else:
                    done(result)
        except queue.Empty:
            pass
        try:
            self.after(POLL_MS, self._poll)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ files

    def assign(self) -> None:
        if self._is_hmi() or self.selected_item() is None:
            self.say("Assign I/O works on a PLC. Pick a PLC in the device list.")
            return
        report = assign_io(self.project, self._plc_id(), write=True)
        self._changed("Assigned PLC I/O addresses")
        self.say(summary_text(report))
        self.watch_menu.configure(values=self._tag_values())
        self.status(f"Assigned {len(report.rows)} I/O point(s).")

    def export_io_csv(self) -> None:
        report = assign_io(self.project, self._plc_id(), write=False)
        if report.profile is None:
            self.say(summary_text(report))
            return
        path = write_io_csv(report, export_folder(self.project, self.save_path) / "io-list.csv")
        self.say(f"I/O list written: {path}")
        self.status("I/O list CSV written.")

    def export(self) -> None:
        if self._is_hmi():
            result = write_hmi_exports(self.project, save_path=self.save_path)
        else:
            result = write_plc_exports(self.project, plc_id=self._plc_id(), save_path=self.save_path)
        self.last_folder = result.folder
        self.say(result.summary())
        self.status("Export finished." if not result.refused else "Export finished with items not written.")

    def open_folder(self) -> None:
        folder = getattr(self, "last_folder", None) or export_folder(self.project, self.save_path,
                                                                      "hmi" if self._is_hmi() else "plc")
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception as exc:
            self.say(f"Could not open the folder ({exc}). It is: {folder}")

    def show_download_help(self) -> None:
        self.say(DOWNLOAD_TEXT)

    # ------------------------------------------------------------------ live link

    def connect(self) -> None:
        if self.selected_item() is None:
            self.say("Add a PLC to the cabinet first.")
            return
        ip = self.ip_entry.get().strip()
        if self._is_hmi():
            self._run("Checking the HMI", lambda: dl.hmi_probe(ip), self._probe_done)
            return
        try:
            slot = int(self.slot_entry.get().strip() or 0)
            driver = dl.make_driver(self.driver_var.get(), ip, slot, tag_map=self._tag_map())
        except (ValueError, dl.DeviceError) as exc:
            self.say("Problem: " + (str(exc) if isinstance(exc, dl.DeviceError) else "Slot must be a number."))
            return
        if self.link is not None:
            self.link.close()
        self.link = dl.DeviceLink(driver, self.project, self._plc_id())
        self._run(f"Connecting to {ip or 'the simulated PLC'}", self.link.connect, self._connected)

    def _tag_map(self) -> dict[str, str]:
        try:
            return {r.tag: r.address for r in assign_io(self.project, self._plc_id(), write=False).rows}
        except Exception:
            return {}

    def _probe_done(self, ports) -> None:
        self.say(dl.probe_text(self.ip_entry.get().strip(), ports))
        self.status("HMI check done.")

    def _connected(self, info) -> None:
        self.say("Connected.\n" + "\n".join(f"{k}: {v}" for k, v in (info or {}).items()))
        self.status(f"Connected with {self.link.driver.name}.")

    def _need_link(self) -> bool:
        if self.link is None or not self.link.connected:
            self.say("Not connected. Click Connect first.")
            return False
        return True

    def disconnect(self) -> None:
        self._set_watch(False)
        if self.link is not None:
            self.link.close()
        self.status("Disconnected.")

    def read_info(self) -> None:
        if self._need_link():
            self._run("Reading controller info", self.link.info, self._connected)

    def compare(self) -> None:
        if self._need_link():
            self._run("Uploading the tag list", self.link.compare_tags, lambda r: self.say(r.text()))

    def add_watch(self) -> None:
        tag = self.watch_var.get().strip()
        if tag and tag not in self.watch:
            self.watch.append(tag)
        self._show_watch({})

    def remove_watch(self) -> None:
        tag = self.watch_var.get().strip()
        if tag in self.watch:
            self.watch.remove(tag)
        self._show_watch({})

    def add_all_io(self) -> None:
        for tag in self._tag_map():
            if tag not in self.watch:
                self.watch.append(tag)
        self._show_watch({})

    def _show_watch(self, values: dict) -> None:
        self.watch_box.delete("1.0", "end")
        for tag in self.watch:
            self.watch_box.insert("end", f"{tag:<28} {values.get(tag, '')}\n")

    def _set_watch(self, on: bool) -> None:
        self.watching = on
        try:
            self.watch_btn.configure(text="Stop watch" if on else "Start watch")
        except tk.TclError:
            pass

    def toggle_watch(self) -> None:
        if self.watching:
            self._set_watch(False)
            self.status("Watch stopped.")
            return
        if not self._need_link():
            return
        if not self.watch:
            self.say("Add a tag to the watch list first.")
            return
        self._set_watch(True)
        self._tick()

    def _tick(self) -> None:
        if self._closed or not self.watching:
            return
        if not self.busy:
            tags = list(self.watch)
            self._run("Reading", lambda: self.link.read(tags), self._watch_done)
        try:
            self.after(WATCH_MS, self._tick)
        except tk.TclError:
            pass

    def _watch_done(self, values) -> None:
        self._show_watch(values or {})
        self.status("Watching - values update about once a second.")

    def write(self) -> None:
        tag = self.write_tag.get().strip()
        raw = self.write_value.get().strip()
        if self.link is None:
            self.say("Not connected. Click Connect first.")
            return
        if not self.safe_var.get():
            self.say("Not written: tick 'I am at the machine and it is safe' first.")
            return
        reason = self.link.write_refusal(tag)
        if reason:
            self.say("Not written: " + reason)
            return
        try:
            value = float(raw) if "." in raw else int(raw)
        except ValueError:
            self.say("Not written: the value must be a number (1 / 0 for a bit).")
            return
        self._run(f"Writing {tag}", lambda: self.link.write(tag, value, confirmed=True),
                  lambda _r: self.say(f"Wrote {value} to {tag}."))

    def close(self) -> None:
        self._closed = True
        self.watching = False
        try:
            if self.link is not None:
                self.link.close()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
