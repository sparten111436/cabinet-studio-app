"""AI settings: pick the AI (Built-in, OpenAI, Anthropic, Gemini, GitHub, Azure, Ollama), model and key."""

from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import replace

import customtkinter as ctk

from cabinet_studio.services import ai_providers as ap
from cabinet_studio.ui.theme import BG, BORDER, CYAN, ENTRY, MUTED, ORANGE, PANEL, TEXT, ghost_button, primary_button, section_label

# Headless tests flip this so background calls finish inside the click.
SYNC = False


def run_async(widget, fn, on_done) -> None:
    """Run ``fn()`` off the UI thread; call ``on_done(result, error)`` back on it."""
    if SYNC:
        try:
            result, error = fn(), None
        except Exception as exc:  # noqa: BLE001
            result, error = None, exc
        on_done(result, error)
        return
    box: dict = {}

    def work():
        try:
            box["result"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc
        box["done"] = True

    threading.Thread(target=work, daemon=True).start()

    def poll():
        if not box.get("done"):
            try:
                widget.after(120, poll)
            except tk.TclError:
                pass
            return
        try:
            on_done(box.get("result"), box.get("error"))
        except tk.TclError:
            pass

    widget.after(120, poll)


_LABELS = {pid: info["label"] for pid, info in ap.PROVIDERS.items()}
_BY_LABEL = {v: k for k, v in _LABELS.items()}
AZURE = "azure_openai"
MICROSOFT_NOTE = ("Microsoft Copilot itself has no third-party API. GitHub Models (Copilot) and Azure OpenAI "
                  "are the official Microsoft routes. GitHub retired GitHub Models on 2026-07-30, so Azure "
                  "OpenAI is the one to use for new setups.")
_KEY_HINTS = {
    "github": "Paste a GitHub token with the models:read permission (or set GITHUB_TOKEN).",
    AZURE: "Paste a key from the resource's Keys and Endpoint page (or set AZURE_OPENAI_API_KEY).",
    "groq": "Free key, no card: console.groq.com/keys (or set GROQ_API_KEY).",
    "xai": "Key from console.x.ai > API Keys (or set XAI_API_KEY).",
}


class AiSettingsDialog(ctk.CTkToplevel):
    """Non-modal settings window; ``on_saved(settings)`` runs after Save."""

    def __init__(self, master, fonts, on_saved=None) -> None:
        super().__init__(master, fg_color=BG)
        self.fonts = fonts
        self.on_saved = on_saved
        self.settings = ap.load_settings()
        self._pending_keys: dict[str, str] = {}
        self._models = dict(self.settings.models)
        self.title("AI settings")
        self.minsize(560, 620)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        section_label(self, "CHOOSE THE AI", fonts.tiny).pack(anchor="w", padx=18, pady=(14, 4))
        self.provider_var = tk.StringVar(master=self, value=_LABELS[self.settings.provider])
        self.provider_menu = ctk.CTkOptionMenu(
            self, values=list(_LABELS.values()), variable=self.provider_var,
            command=lambda _v: self._show_provider(), font=fonts.body, width=320,
        )
        self.provider_menu.pack(anchor="w", padx=18, pady=(0, 8))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=4)
        ctk.CTkLabel(row, text="Model", font=fonts.small, text_color=MUTED, width=80, anchor="w").pack(side="left")
        self.model_box = ctk.CTkComboBox(row, values=[""], font=fonts.body, width=300,
                                         fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
        self.model_box.pack(side="left", padx=(0, 6))
        self.refresh_btn = ghost_button(row, "Refresh models", self._refresh_models, fonts.small, width=120)
        self.refresh_btn.pack(side="left")

        krow = ctk.CTkFrame(self, fg_color="transparent")
        krow.pack(fill="x", padx=18, pady=4)
        self.key_label = ctk.CTkLabel(krow, text="API key", font=fonts.small, text_color=MUTED, width=80, anchor="w")
        self.key_label.pack(side="left")
        self.key_entry = ctk.CTkEntry(krow, font=fonts.body, width=300, show="•",
                                      fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
        self.key_entry.pack(side="left", padx=(0, 6))
        self.show_var = tk.BooleanVar(master=self, value=False)
        ctk.CTkCheckBox(krow, text="Show", variable=self.show_var, font=fonts.tiny, width=60,
                        command=lambda: self.key_entry.configure(show="" if self.show_var.get() else "•")).pack(side="left")
        self.clear_key_btn = ghost_button(krow, "Clear key", self._clear_key, fonts.small, width=80)
        self.clear_key_btn.pack(side="left", padx=4)
        self.key_note = ctk.CTkLabel(self, text="", font=fonts.tiny, text_color=MUTED, anchor="w")
        self.key_note.pack(fill="x", padx=104, pady=(0, 4))

        self.azure_entries: dict[str, ctk.CTkEntry] = {}
        azure_values = {"endpoint": self.settings.azure_endpoint, "deployment": self.settings.azure_deployment,
                        "api_version": self.settings.azure_api_version or ap.DEFAULT_AZURE_API_VERSION}
        for key, text, hint in (("endpoint", "Endpoint", "https://<resource>.openai.azure.com"),
                                ("deployment", "Deployment", "deployment name from the Azure portal"),
                                ("api_version", "API version", ap.DEFAULT_AZURE_API_VERSION)):
            arow = ctk.CTkFrame(self, fg_color="transparent")
            arow.pack(fill="x", padx=18, pady=2)
            ctk.CTkLabel(arow, text=text, font=fonts.small, text_color=MUTED, width=80, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(arow, font=fonts.body, width=300, placeholder_text=hint,
                                 fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
            if azure_values[key]:
                entry.insert(0, azure_values[key])
            entry.pack(side="left")
            self.azure_entries[key] = entry

        orow = ctk.CTkFrame(self, fg_color="transparent")
        orow.pack(fill="x", padx=18, pady=4)
        ctk.CTkLabel(orow, text="Ollama URL", font=fonts.small, text_color=MUTED, width=80, anchor="w").pack(side="left")
        self.ollama_entry = ctk.CTkEntry(orow, font=fonts.body, width=300, fg_color=ENTRY, border_color=BORDER, text_color=TEXT)
        self.ollama_entry.insert(0, self.settings.ollama_url)
        self.ollama_entry.pack(side="left")

        ctk.CTkLabel(self, text=ap.PRIVACY_NOTE, font=fonts.tiny, text_color=ORANGE, anchor="w",
                     justify="left", wraplength=520).pack(fill="x", padx=18, pady=(10, 2))
        self.microsoft_note = ctk.CTkLabel(self, text=MICROSOFT_NOTE, font=fonts.tiny, text_color=MUTED, anchor="w",
                                           justify="left", wraplength=520)
        self.microsoft_note.pack(fill="x", padx=18, pady=(0, 2))
        ctk.CTkLabel(self, text=f"Keys are encrypted for this Windows user in {ap.ai_settings_path()} "
                                "(never in project files).",
                     font=fonts.tiny, text_color=MUTED, anchor="w", justify="left", wraplength=520).pack(fill="x", padx=18)

        self.status = ctk.CTkLabel(self, text="", font=fonts.small, text_color=CYAN, anchor="w",
                                   justify="left", wraplength=520)
        self.status.pack(fill="x", padx=18, pady=(10, 4))
        nav = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        nav.pack(side="bottom", fill="x")
        ghost_button(nav, "Close", self.destroy, fonts.body, width=90).pack(side="left", padx=12, pady=10)
        self.test_btn = ghost_button(nav, "Test connection", self._test, fonts.body, width=140)
        self.test_btn.pack(side="left", padx=6, pady=10)
        primary_button(nav, "Save", self._save, fonts.body, width=110).pack(side="right", padx=12, pady=10)
        self._current = self.settings.provider
        self._show_provider(initial=True)
        self.after(30, self._lift)

    def _lift(self) -> None:
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    # -------------------------------------------------------------- form state
    def _pid(self) -> str:
        return _BY_LABEL.get(self.provider_var.get(), ap.BUILTIN)

    def _stash_form(self) -> None:
        pid = self._current
        model = (self.model_box.get() or "").strip()
        if model and pid not in (ap.BUILTIN, AZURE):
            self._models[pid] = model
        typed = (self.key_entry.get() or "").strip()
        if typed:
            self._pending_keys[pid] = typed

    def _show_provider(self, initial: bool = False) -> None:
        if not initial:
            self._stash_form()
        pid = self._pid()
        self._current = pid
        info = ap.PROVIDERS[pid]
        azure = pid == AZURE
        if azure:
            deployment = self._azure_value("deployment")
            models, chosen = [deployment], deployment or "(uses Deployment below)"
        else:
            models = list(info["models"])
            chosen = self._models.get(pid) or (models[0] if models else "")
            if chosen not in models:
                models.insert(0, chosen)
        self._set_models(models, chosen)
        self.key_entry.delete(0, "end")
        builtin = pid == ap.BUILTIN
        self.model_box.configure(state="disabled" if builtin or azure else "normal")
        self.refresh_btn.configure(state="disabled" if builtin else "normal")
        self.key_entry.configure(state="normal" if info["needs_key"] else "disabled")
        self.clear_key_btn.configure(state="normal" if info["needs_key"] else "disabled")
        self.ollama_entry.configure(state="normal" if pid == "ollama" else "disabled")
        for entry in self.azure_entries.values():
            entry.configure(state="normal" if azure else "disabled")
        self.key_label.configure(text="Token" if pid == "github" else "API key")
        if info["needs_key"]:
            saved = pid in self._pending_keys or self.settings.has_key(pid)
            env = ", ".join(info["env"])
            hint = _KEY_HINTS.get(pid, f"Paste your key (or set {env}).")
            self.key_note.configure(text=("A key is saved - leave blank to keep it." if saved else hint))
        elif pid == "ollama":
            self.key_note.configure(text="No key needed. Install Ollama and pull a model (e.g. ollama pull llama3.1).")
        else:
            self.key_note.configure(text="No key needed. Explains rungs and suggests tests offline.")
        self.status.configure(text="")

    def _set_models(self, values: list[str], chosen: str) -> None:
        state = self.model_box.cget("state")
        self.model_box.configure(values=values, state="normal")
        self.model_box.set(chosen)
        self.model_box.configure(state=state)

    def _azure_value(self, key: str) -> str:
        return (self.azure_entries[key].get() or "").strip()

    def _form_settings(self) -> ap.AiSettings:
        self._stash_form()
        s = replace(self.settings, provider=self._pid(), models=dict(self._models),
                    keys=dict(self.settings.keys),
                    ollama_url=(self.ollama_entry.get() or ap.DEFAULT_OLLAMA_URL).strip(),
                    azure_endpoint=self._azure_value("endpoint"),
                    azure_deployment=self._azure_value("deployment"),
                    azure_api_version=self._azure_value("api_version") or ap.DEFAULT_AZURE_API_VERSION)
        for pid, key in self._pending_keys.items():
            s.set_key(pid, key)
        return s

    def _clear_key(self) -> None:
        pid = self._pid()
        self._pending_keys.pop(pid, None)
        self.settings.keys.pop(pid, None)
        self.key_entry.delete(0, "end")
        self.key_note.configure(text="Key cleared - Save to keep this change.")

    # -------------------------------------------------------------- actions
    def _busy(self, text: str) -> None:
        self.status.configure(text=text, text_color=MUTED)
        self.test_btn.configure(state="disabled")

    def _done(self, text: str, ok: bool) -> None:
        try:
            self.status.configure(text=text, text_color=CYAN if ok else ORANGE)
            self.test_btn.configure(state="normal")
        except tk.TclError:
            pass

    def _test(self) -> None:
        s = self._form_settings()
        self._busy(f"Testing {s.label()} ...")
        run_async(self, lambda: ap.test_connection(s),
                  lambda res, err: self._done(str(err) if err else res, err is None))

    def _refresh_models(self) -> None:
        s = self._form_settings()
        pid = s.provider
        self._busy("Asking for the model list ...")

        def done(res, err):
            if err:
                self._done(f"Could not list models: {err}", False)
                return
            if res:
                cur = self.model_box.get()
                self._set_models(res, cur if cur in res else res[0])
            self._done(f"{len(res or [])} model(s) available for {ap.PROVIDERS[pid]['label']}.", True)

        run_async(self, lambda: ap.list_models(s, pid), done)

    def _save(self) -> None:
        s = self._form_settings()
        try:
            ap.save_settings(s)
        except OSError as exc:
            self._done(f"Could not save settings: {exc}", False)
            return
        self.settings = s
        self._pending_keys.clear()
        self._done(f"Saved. Using {s.label()}.", True)
        if self.on_saved:
            self.on_saved(s)
