"""Properties / I-O pane: the selected rung and its instructions, editable through
the existing safe editor functions, with live values while the sim runs."""

from __future__ import annotations

import json

import customtkinter as ctk

from cabinet_studio.services.ladder_ir import program_rung_to_elements
from cabinet_studio.services.programming import rung_instruction_list
from cabinet_studio.ui.theme import BORDER, CYAN, ENTRY, MUTED, PANEL, TEXT, ghost_button, section_label

# Element fields that hold a tag the user may rename on this rung (via replace_tag).
TAG_FIELDS = {"contact": "var", "coil": "var", "timer": "var", "counter": "var", "oneshot": "var"}


def element_at(rung: dict, path: tuple) -> dict | None:
    els = program_rung_to_elements(rung)
    node_list, el, i = els, None, 0
    while i < len(path):
        if path[i] >= len(node_list):
            return None
        el = node_list[path[i]]
        i += 1
        if i < len(path):
            branches = el.get("branches") or []
            if path[i] >= len(branches):
                return None
            node_list = branches[path[i]]
            i += 1
    return el


def operand_text(el: dict) -> str:
    kind = str(el.get("kind") or "").lower()
    if kind == "compare":
        parts = [el.get("source_a", ""), el.get("source_b", ""), el.get("source_c", "")]
        return "A,B,C = " + ", ".join(str(p) for p in parts if str(p))
    if kind == "math":
        return f"dest {el.get('dest', '')} ← {el.get('source_a', '')}, {el.get('source_b', '')}"
    if kind == "jsr":
        return f"target {el.get('target', '')}"
    if kind == "sbr":
        return f"routine {el.get('name', '')}"
    if kind == "oneshot" and el.get("output"):
        return f"output {el.get('output')}"
    return ""


class PropertiesPane(ctk.CTkFrame):
    def __init__(self, master, viewer) -> None:
        super().__init__(master, fg_color=PANEL, corner_radius=0)
        self.viewer = viewer
        fonts = viewer.fonts
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=6, pady=(6, 2))
        section_label(head, "PROPERTIES", fonts.tiny).pack(side="left", padx=4)
        self.collapse_btn = ghost_button(head, "▶", lambda: viewer._set_pane_visible("properties", False),
                                         fonts.tiny, width=28)
        self.collapse_btn.pack(side="right")
        self.body = ctk.CTkScrollableFrame(self, fg_color=PANEL, corner_radius=0)
        self.body.pack(fill="both", expand=True, padx=2, pady=(0, 4))
        self._sig = None
        self.rows: list[dict] = []
        self.rung_id: str | None = None
        self.comment_box = None
        self.preset_entry = None
        self.live_labels: list[tuple[ctk.CTkLabel, dict]] = []
        self.sync()

    # -- build ---------------------------------------------------------------

    def _rung(self):
        v = self.viewer
        rid = v._selected_or_last_rung_id()
        rung = next((r for r in v.program.get("rungs") or [] if r.get("id") == rid), None)
        return rid, rung

    def sync(self) -> None:
        """Rebuild when the selected rung (or its data) changed; always refresh live values."""
        rid, rung = self._rung()
        descs = self.viewer.program.get("tag_descriptions") or {}
        sig = (rid, json.dumps(rung, sort_keys=True, default=str), json.dumps(descs, sort_keys=True))
        if sig != self._sig:
            self._sig = sig
            self._build(rid, rung)
        self.update_live()

    def _clear(self) -> None:
        for child in list(self.body.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        self.rows = []
        self.live_labels = []
        self.comment_box = self.preset_entry = None

    def _label(self, text: str, *, muted: bool = False, color=None) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(self.body, text=text, font=self.viewer.fonts.tiny, anchor="w", justify="left",
                           text_color=color or (MUTED if muted else TEXT), wraplength=250)
        lbl.pack(fill="x", padx=8, pady=(4, 0))
        return lbl

    def _entry(self, parent, value: str, width: int = 120) -> ctk.CTkEntry:
        e = ctk.CTkEntry(parent, width=width, height=26, font=self.viewer.fonts.tiny, fg_color=ENTRY,
                         border_color=BORDER, text_color=TEXT)
        e.insert(0, value)
        return e

    def _build(self, rid, rung) -> None:
        self._clear()
        self.rung_id = rid
        v = self.viewer
        fonts = v.fonts
        if rung is None:
            self._label("No rung selected. Click a rung on the ladder, or insert one from the palette.", muted=True)
            return
        ids = [r["id"] for r in v.program.get("rungs") or []]
        self._label(f"Rung {ids.index(rid) + 1} of {len(ids)}   ·   MainRoutine", color=CYAN)
        self._label("Comment", muted=True)
        self.comment_box = ctk.CTkTextbox(self.body, height=56, font=fonts.tiny, fg_color=ENTRY, text_color=TEXT,
                                          border_color=BORDER, border_width=1, wrap="word")
        self.comment_box.insert("1.0", rung.get("comment") or "")
        self.comment_box.pack(fill="x", padx=8, pady=2)
        ghost_button(self.body, "Apply comment",
                     lambda: v.apply_rung_comment(rid, self.comment_box.get("1.0", "end")), fonts.tiny,
                     width=110).pack(anchor="w", padx=8, pady=(0, 4))

        box = rung.get("timer") if isinstance(rung.get("timer"), dict) else None
        cbox = rung.get("counter") if isinstance(rung.get("counter"), dict) else None
        if box or (cbox and str(cbox.get("block") or "CTU").upper() in {"CTU", "CTD"}):
            is_timer = bool(box)
            data = box or cbox
            self._label(f"{'Timer' if is_timer else 'Counter'} {data.get('block', '')} {data.get('tag', '')}  "
                        f"preset ({'ms' if is_timer else 'count'})", muted=True)
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)
            self.preset_entry = self._entry(row, str(data.get("pt_ms" if is_timer else "pv", "")), 90)
            self.preset_entry.pack(side="left")
            ghost_button(row, "Apply preset", lambda: v.apply_preset(rid, self.preset_entry.get()), fonts.tiny,
                         width=100).pack(side="left", padx=6)

        self._label("Instructions", muted=True)
        for path, label, note in rung_instruction_list(rung):
            el = element_at(rung, path) or {}
            kind = str(el.get("kind") or "").lower()
            frame = ctk.CTkFrame(self.body, fg_color="transparent", border_width=1, border_color=BORDER,
                                 corner_radius=4)
            frame.pack(fill="x", padx=6, pady=3)
            top = ctk.CTkFrame(frame, fg_color="transparent")
            top.pack(fill="x", padx=4, pady=(3, 0))
            ctk.CTkLabel(top, text=label, font=fonts.tiny, text_color=TEXT, anchor="w").pack(side="left")
            live = ctk.CTkLabel(top, text="", font=fonts.tiny, text_color=MUTED, anchor="e")
            live.pack(side="right")
            self.live_labels.append((live, el))
            extra = operand_text(el)
            if extra:
                ctk.CTkLabel(frame, text=extra, font=fonts.tiny, text_color=MUTED, anchor="w").pack(fill="x", padx=6)
            row = {"path": path, "kind": kind, "tag": "", "tag_entry": None, "desc_entry": None}
            tag = str(el.get(TAG_FIELDS.get(kind, ""), "") or "") if kind in TAG_FIELDS else ""
            grid = ctk.CTkFrame(frame, fg_color="transparent")
            grid.pack(fill="x", padx=4, pady=2)
            if tag:
                row["tag"] = tag
                ctk.CTkLabel(grid, text="Tag", width=64, font=fonts.tiny, text_color=MUTED, anchor="w").grid(
                    row=0, column=0, sticky="w")
                row["tag_entry"] = self._entry(grid, tag, 150)
                row["tag_entry"].grid(row=0, column=1, sticky="w", pady=1)
                ctk.CTkLabel(grid, text="Description", width=64, font=fonts.tiny, text_color=MUTED,
                             anchor="w").grid(row=2, column=0, sticky="w")
                desc = (v.program.get("tag_descriptions") or {}).get(tag.split(".")[0], "")
                row["desc_entry"] = self._entry(grid, desc, 150)
                row["desc_entry"].grid(row=2, column=1, sticky="w", pady=1)
            ctk.CTkLabel(grid, text="Note", width=64, font=fonts.tiny, text_color=MUTED, anchor="w").grid(
                row=1, column=0, sticky="w")
            row["note_entry"] = self._entry(grid, note, 150)
            row["note_entry"].grid(row=1, column=1, sticky="w", pady=1)
            row["note"] = note
            row["desc"] = row["desc_entry"].get() if row["desc_entry"] is not None else ""
            ghost_button(frame, "Apply", lambda r=row: self.apply_row(r), fonts.tiny, width=70).pack(
                anchor="e", padx=4, pady=(0, 4))
            self.rows.append(row)

    # -- edits (all through viewer → existing safe service functions) ---------

    def apply_row(self, row: dict) -> None:
        # Each apply redraws this pane, so read every entry before the first edit.
        v = self.viewer
        rid = self.rung_id
        note = row["note_entry"].get().strip()
        desc = row["desc_entry"].get().strip() if row["desc_entry"] is not None else None
        new = row["tag_entry"].get().strip() if row["tag_entry"] is not None else ""
        if note != (row.get("note") or ""):
            v.apply_instruction_note(rid, row["path"], note)
        if desc is not None and desc != (row.get("desc") or ""):
            v.apply_tag_description(row["tag"].split(".")[0], desc)
        if new and new != row["tag"]:
            v.apply_operand_rename(rid, row["tag"], new)

    # -- live values ---------------------------------------------------------

    def update_live(self) -> None:
        sim = self.viewer._scan_sim if self.viewer._sim_session else None
        for lbl, el in self.live_labels:
            try:
                lbl.configure(text=self._live_text(sim, el) if sim is not None else "")
            except Exception:
                pass

    @staticmethod
    def _live_text(sim, el: dict) -> str:
        kind = str(el.get("kind") or "").lower()
        try:
            if kind in {"contact", "coil", "oneshot"} and el.get("var"):
                return "ON" if sim.read(str(el["var"])) else "OFF"
            if kind == "timer" and el.get("var"):
                t = str(el["var"])
                return f"ACC {sim.read_number(t + '.ACC'):g} / {sim.read_number(t + '.PRE'):g}"
            if kind == "counter" and el.get("var"):
                t = str(el["var"])
                return f"ACC {sim.read_number(t + '.ACC'):g} / {sim.read_number(t + '.PRE'):g}"
            if kind == "math" and el.get("dest"):
                return f"{el['dest']} = {sim.read_number(str(el['dest'])):g}"
            if kind == "compare":
                a = sim.read_number(str(el.get("source_a") or 0))
                b = sim.read_number(str(el.get("source_b") or 0))
                return f"A {a:g}  B {b:g}"
        except Exception:
            return ""
        return ""
