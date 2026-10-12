"""AI assistant window: chat with the selected AI about the interview or the live simulation.

Rung changes the AI proposes appear as cards; nothing changes until Apply, and
Apply runs the same verify + simulator checks as a manual edit.
"""

from __future__ import annotations

import re
import tkinter as tk

import customtkinter as ctk

from cabinet_studio.services import ai_assist as aa
from cabinet_studio.services import ai_providers as ap
from cabinet_studio.services.ai_build import interview_suggestion
from cabinet_studio.services.ladder_sim import sim_blockers
from cabinet_studio.ui.ai_settings import AiSettingsDialog, run_async
from cabinet_studio.ui.dialogs import ask_choice
from cabinet_studio.ui.theme import (
    BG, BORDER, CYAN, DANGER_TEXT, ENTRY, MUTED, ORANGE, PANEL, TEXT, bind_theme_redraw, c, ghost_button,
    primary_button, section_label,
)

SIM_QUICK = (
    ("Why is this rung off?", "why"),
    ("Explain this rung", "explain"),
    ("What should I test next?", "test"),
    ("Suggest a fix", "fix"),
)
INTERVIEW_QUICK = (
    ("Explain this question", "explain_q"),
    ("What do you recommend?", "recommend"),
)
_RUNG_REF = re.compile(r"\bR(\d{1,4})\b")


class AiAssistantWindow(ctk.CTkToplevel):
    """mode="sim": context_fn() -> {program, sim, selected_index, cursor_index, blockers, project_name}
    mode="interview": context_fn() -> {answers, questions, index}
    apply_fn(new_program, rung_id, summary) applies an approved proposal (sim mode only)."""

    def __init__(self, master, fonts, *, mode: str, context_fn, apply_fn=None, title: str = "AI assistant") -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.mode = mode
        self.context_fn = context_fn
        self.apply_fn = apply_fn
        self.history: list[dict[str, str]] = []
        self.proposals: list[aa.Proposal] = []
        self._busy = False
        self._settings_win = None
        self.title(title)
        self.geometry("640x680")
        self.minsize(520, 480)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        section_label(head, "AI ASSISTANT" + (" - LIVE SIMULATION" if mode == "sim" else " - INTERVIEW"),
                      fonts.tiny).pack(side="left")
        ghost_button(head, "Clear", self.clear, fonts.tiny, width=60).pack(side="right", padx=3)
        self.copy_btn = ghost_button(head, "Copy all", self.copy_all, fonts.tiny, width=70)
        self.copy_btn.pack(side="right", padx=3)
        ghost_button(head, "AI settings…", self.open_settings, fonts.tiny, width=96).pack(side="right", padx=3)
        self.ai_label = ctk.CTkLabel(head, text="", font=fonts.small, text_color=CYAN)
        self.ai_label.pack(side="right", padx=8)

        self.transcript = ctk.CTkTextbox(self, font=fonts.small, fg_color=PANEL, text_color=TEXT,
                                         border_color=BORDER, border_width=1, wrap="word")
        self.transcript.pack(fill="both", expand=True, padx=12, pady=4)
        self._tag_colours()
        bind_theme_redraw(self, self._tag_colours)
        self.transcript.configure(state="disabled")
        inner = self.transcript._textbox
        inner.bind("<Button-1>", lambda _e: inner.focus_set(), add="+")
        for seq in ("<Control-c>", "<Control-C>"):
            inner.bind(seq, lambda _e: (self.copy_selection(), "break")[1])
        inner.bind("<Control-a>", lambda _e: (self.select_all(), "break")[1])
        self._copy_menu = tk.Menu(self, tearoff=0)
        self._copy_menu.add_command(label="Copy", command=self.copy_selection)
        self._copy_menu.add_command(label="Copy all", command=self.copy_all)
        self._copy_menu.add_command(label="Select all", command=self.select_all)
        inner.bind("<Button-3>", lambda e: self._copy_menu.tk_popup(e.x_root, e.y_root))

        self.cards = ctk.CTkScrollableFrame(self, fg_color=BG, height=0)
        self.cards.pack(fill="x", padx=12)

        quick = ctk.CTkFrame(self, fg_color="transparent")
        quick.pack(fill="x", padx=12, pady=(4, 0))
        self.quick_buttons: dict[str, ctk.CTkButton] = {}
        for label, kind in (SIM_QUICK if mode == "sim" else INTERVIEW_QUICK):
            b = ghost_button(quick, label, lambda k=kind, t=label: self.ask_quick(k, t), fonts.tiny, width=10)
            b.pack(side="left", padx=3, pady=2)
            self.quick_buttons[kind] = b

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=6)
        self.entry = ctk.CTkEntry(row, font=fonts.body, fg_color=ENTRY, border_color=BORDER, text_color=TEXT,
                                  placeholder_text="Ask anything about this " + ("ladder / simulation" if mode == "sim" else "question"))
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.entry.bind("<Return>", lambda _e: self.ask_typed())
        self.ask_btn = primary_button(row, "Ask", self.ask_typed, fonts.body, width=80)
        self.ask_btn.pack(side="left")
        self.status = ctk.CTkLabel(self, text="", font=fonts.tiny, text_color=MUTED, anchor="w")
        self.status.pack(fill="x", padx=14)
        ctk.CTkLabel(self, text="Design aid only. " + aa.SAFETY_NOTE, font=fonts.tiny, text_color=MUTED,
                     anchor="w", justify="left", wraplength=600).pack(fill="x", padx=14, pady=(0, 8))
        self.refresh_label()
        self._say("note", "Pick a quick question or type your own. "
                  + ("The AI sees the ladder and the live simulator state each time you ask. "
                     "Rung changes it proposes appear below with an Apply button - nothing changes until you click it."
                     if mode == "sim" else "The AI sees your answers so far."))

    # -------------------------------------------------------------- helpers
    def _tag_colours(self) -> None:
        self.transcript.tag_config("you", foreground=c(CYAN))
        self.transcript.tag_config("ai", foreground=c(TEXT))
        self.transcript.tag_config("note", foreground=c(ORANGE))

    def refresh_label(self) -> None:
        self.settings = ap.load_settings()
        self.ai_label.configure(text="AI: " + self.settings.label())

    def open_settings(self) -> None:
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        self._settings_win = AiSettingsDialog(self, self.fonts, on_saved=lambda _s: self.refresh_label())

    def clear(self) -> None:
        self.history.clear()
        self.proposals.clear()
        self._render_cards()
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")

    def transcript_text(self) -> str:
        return self.transcript.get("1.0", "end")

    def _to_clipboard(self, text: str) -> None:
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status.configure(text="Copied to clipboard.")

    def selected_text(self) -> str:
        try:
            return self.transcript.get("sel.first", "sel.last")
        except tk.TclError:
            return ""

    def copy_selection(self) -> None:
        self._to_clipboard(self.selected_text() or self.transcript_text().strip())

    def copy_all(self) -> None:
        self._to_clipboard(self.transcript_text().strip())

    def select_all(self) -> None:
        self.transcript._textbox.tag_add("sel", "1.0", "end-1c")

    def _say(self, who: str, text: str) -> None:
        prefix = {"you": "You: ", "ai": f"{self.settings.label() if self.settings.provider != ap.BUILTIN else 'Cabinet Studio AI'}: ",
                  "note": ""}[who]
        self.transcript.configure(state="normal")
        self.transcript.insert("end", prefix + text.strip() + "\n\n", who)
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.status.configure(text=text)
        state = "disabled" if busy else "normal"
        self.ask_btn.configure(state=state)
        for b in self.quick_buttons.values():
            b.configure(state=state)

    # -------------------------------------------------------------- asking
    def ask_typed(self) -> None:
        q = (self.entry.get() or "").strip()
        if not q or self._busy:
            return
        self.entry.delete(0, "end")
        self._ask(q, kind="free", shown=q)

    def ask_quick(self, kind: str, label: str) -> None:
        if self._busy:
            return
        ctx = self.context_fn()
        if self.mode == "sim":
            idx = ctx.get("selected_index")
            ref = f"the selected rung R{idx + 1}" if idx is not None else "the program"
            prompts = {
                "why": f"Why is {ref} not energizing right now? Point to the exact instruction(s) blocking power and what I should click.",
                "explain": f"Explain what {ref} does in plain words, and its state right now.",
                "test": "From the program and current state, give a short numbered test plan: what to click next to exercise logic I have not tested yet.",
                "fix": f"Look for logic problems in {ref} (and anything it depends on). Propose fixes as cabinet-rung blocks if needed.",
            }
        else:
            prompts = {
                "explain_q": "Explain this question in plain words and why it matters for the cabinet.",
                "recommend": "Which answer do you recommend for this machine, and why?",
            }
        self._ask(prompts[kind], kind=kind, shown=label)

    def _ask(self, question: str, *, kind: str, shown: str) -> None:
        self.refresh_label()
        self._say("you", shown)
        ctx = self.context_fn()
        if self.settings.provider == ap.BUILTIN:
            self._answer(self._builtin(kind, question, ctx), question, from_ai=False)
            return
        if self.mode == "sim":
            system = aa.sim_system()
            messages = aa.sim_messages(self.history, question, **ctx)
        else:
            system = aa.interview_system()
            messages = aa.interview_question_messages(ctx["answers"], ctx["questions"], ctx["index"],
                                                      self.history, question)
        settings = self.settings
        self._set_busy(True, f"Asking {settings.label()} ...")

        def done(reply, err):
            try:
                self._set_busy(False)
                if err is not None:
                    self._say("note", f"AI unavailable: {err}  Showing the Built-in answer instead.")
                    self._answer(self._builtin(kind, question, self.context_fn()), question, from_ai=False)
                else:
                    self._answer(reply, question, from_ai=True)
            except tk.TclError:
                pass

        run_async(self, lambda: ap.chat(system, messages, settings), done)

    def _answer(self, text: str, question: str, *, from_ai: bool) -> None:
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": text}]
        self.history = self.history[-12:]
        shown = aa._PROPOSAL_RE.sub("[proposed rung change - see the card below]", text) if from_ai else text
        self._say("ai", shown)
        if from_ai and self.mode == "sim" and self.apply_fn is not None:
            found = aa.parse_proposals(text, self.context_fn()["program"])
            if found:
                self.proposals = found
                self._render_cards()

    def _builtin(self, kind: str, question: str, ctx: dict) -> str:
        if self.mode != "sim":
            key = ctx["questions"][ctx["index"]][0]
            tip = interview_suggestion(ctx["answers"], key)
            gloss = aa.glossary_answer(question) if kind == "free" else ""
            return tip + (f"\n\n{gloss}" if gloss else "")
        program, sim = ctx["program"], ctx["sim"]
        if kind == "test":
            return aa.test_checklist(program)
        if kind == "fix":
            return aa.builtin_answer(program, sim, "check for problems")
        if kind == "free":
            return aa.builtin_answer(program, sim, question, selected_index=ctx.get("selected_index"),
                                     cursor_index=ctx.get("cursor_index"))
        idx = ctx.get("selected_index")
        if idx is None:
            idx = ctx.get("cursor_index")
        return aa.explain_rung(program, idx if idx is not None else -1, sim)

    # -------------------------------------------------------------- proposals
    def _render_cards(self) -> None:
        for child in self.cards.winfo_children():
            child.destroy()
        self.cards.configure(height=min(220, 90 * len(self.proposals)) if self.proposals else 0)
        for i, prop in enumerate(self.proposals):
            card = ctk.CTkFrame(self.cards, fg_color=PANEL, border_width=1,
                                border_color=ORANGE if prop.safety else BORDER, corner_radius=4)
            card.pack(fill="x", pady=3)
            ctk.CTkLabel(card, text=f"Proposal {i + 1}: {prop.summary()}", font=self.fonts.tiny, text_color=TEXT,
                         anchor="w", justify="left", wraplength=560).pack(fill="x", padx=8, pady=(6, 2))
            if prop.problems:
                ctk.CTkLabel(card, text="Refused (not applied): " + "; ".join(prop.problems), font=self.fonts.tiny,
                             text_color=DANGER_TEXT, anchor="w", justify="left", wraplength=560).pack(fill="x", padx=8)
            if prop.safety:
                ctk.CTkLabel(card, text="Touches e-stop / guard / safety tags. " + aa.SAFETY_NOTE, font=self.fonts.tiny,
                             text_color=ORANGE, anchor="w", justify="left", wraplength=560).pack(fill="x", padx=8)
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=(2, 6))
            apply_btn = primary_button(row, "Apply", lambda p=prop: self.apply_proposal(p), self.fonts.tiny, width=80)
            apply_btn.pack(side="left", padx=2)
            if not prop.ok:
                apply_btn.configure(state="disabled")
            ghost_button(row, "Dismiss", lambda p=prop: self.dismiss(p), self.fonts.tiny, width=80).pack(side="left", padx=2)

    def dismiss(self, prop: aa.Proposal) -> None:
        self.proposals = [p for p in self.proposals if p is not prop]
        self._render_cards()

    def apply_proposal(self, prop: aa.Proposal, *, confirm_safety=None) -> bool:
        if prop.safety:
            answer = confirm_safety() if confirm_safety else ask_choice(
                self, self.fonts, "Safety-related change",
                "This change touches e-stop / guard / safety logic. " + aa.SAFETY_NOTE + " Apply it to the design anyway?",
                [("yes", "Apply anyway", "ghost"), ("no", "Cancel", "primary")],
            )
            if answer != "yes":
                return False
        ctx = self.context_fn()
        name = ctx.get("project_name") or ""
        try:
            new, rid = aa.apply_proposal(ctx["program"], prop,
                                         sim_blockers_fn=lambda p: sim_blockers(p, project_name=name))
        except ValueError as exc:
            self._say("note", str(exc))
            return False
        self.apply_fn(new, rid, prop.summary())
        self._say("note", f"Applied: {prop.summary()}")
        self.dismiss(prop)
        return True
