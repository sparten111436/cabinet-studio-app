"""AI selection + live AI tips for the 'New build with AI' interview dialog.

Kept outside the protected ``ui/ai_build.py``; that dialog only calls
``attach_interview_ai`` once and ``refresh_interview_ai_tip`` per question.
"""

from __future__ import annotations

import tkinter as tk

from cabinet_studio.services import ai_providers as ap
from cabinet_studio.services.ai_assist import interview_system, interview_tip_messages
from cabinet_studio.services.ai_build import AI_BUILD_QUESTIONS
from cabinet_studio.ui.ai_assistant import AiAssistantWindow
from cabinet_studio.ui.ai_settings import AiSettingsDialog, run_async
from cabinet_studio.ui.theme import ghost_button


def attach_interview_ai(dialog) -> None:
    """Add the 'AI: ...' picker under the heading and an 'Ask AI' button to the nav bar."""
    dialog._ai_tip_token = 0
    dialog._ai_chat = None
    dialog._ai_settings_win = None
    dialog.ai_pick_btn = ghost_button(dialog.heading.master, "", lambda: open_interview_ai_settings(dialog),
                                      dialog.fonts.small, width=300)
    dialog.ai_pick_btn.pack(anchor="w", pady=(4, 0), after=dialog.heading)
    dialog.ask_ai_btn = ghost_button(dialog.nav, "Ask AI", lambda: open_interview_ai_chat(dialog),
                                     dialog.fonts.body, width=100)
    dialog.ask_ai_btn.pack(side="right", padx=6, pady=12)
    _refresh_pick(dialog)


def _refresh_pick(dialog) -> None:
    dialog.ai_pick_btn.configure(text=f"AI: {ap.load_settings().label()}  (change)")


def open_interview_ai_settings(dialog) -> None:
    win = dialog._ai_settings_win
    if win is not None and win.winfo_exists():
        win.lift()
        return

    def saved(_s):
        _refresh_pick(dialog)
        if getattr(dialog, "_phase", "") == "interview":
            refresh_interview_ai_tip(dialog)

    dialog._ai_settings_win = AiSettingsDialog(dialog, dialog.fonts, on_saved=saved)


def _context(dialog) -> dict:
    return {"answers": dict(dialog.answers), "questions": AI_BUILD_QUESTIONS,
            "index": min(dialog.index, len(AI_BUILD_QUESTIONS) - 1)}


def open_interview_ai_chat(dialog) -> None:
    win = dialog._ai_chat
    if win is not None and win.winfo_exists():
        win.deiconify()
        win.lift()
        return
    dialog._ai_chat = AiAssistantWindow(dialog, dialog.fonts, mode="interview",
                                        context_fn=lambda: _context(dialog), title="AI assistant - interview")
    try:
        dialog._ai_chat.transient(dialog)
        dialog._ai_chat.lift()
    except tk.TclError:
        pass


def refresh_interview_ai_tip(dialog) -> None:
    """The built-in tip is already showing; if an AI is selected, replace it when the AI answers."""
    settings = ap.load_settings()
    if settings.provider == ap.BUILTIN:
        return
    dialog._ai_tip_token += 1
    token, index = dialog._ai_tip_token, dialog.index
    ctx = _context(dialog)
    builtin = dialog.ai_tip.cget("text")
    dialog.ai_tip.configure(text=f"{builtin}   (asking {settings.label()}…)")

    def done(reply, err):
        if token != dialog._ai_tip_token or dialog.index != index or getattr(dialog, "_phase", "") != "interview":
            return
        if err is not None:
            dialog.ai_tip.configure(text=f"{builtin}   (AI unavailable: {str(err)[:90]})")
        else:
            dialog.ai_tip.configure(text=f"AI tip ({settings.label()}): {reply.strip()[:600]}")

    run_async(dialog, lambda: ap.chat(interview_system(),
                                      interview_tip_messages(ctx["answers"], AI_BUILD_QUESTIONS, ctx["index"]),
                                      settings), done)
