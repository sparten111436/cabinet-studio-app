"""v0.3.22 GitHub Models + Microsoft Azure OpenAI providers (no network: ai_providers._http is faked)."""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.error

import pytest

from cabinet_studio.services import ai_providers as ap

MSGS = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}, {"role": "user", "content": "q2"}]
OK_REPLY = {"choices": [{"message": {"content": "OK"}}]}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CABINET_STUDIO_AI_SETTINGS", str(tmp_path / "ai.json"))
    for env in list(os.environ):
        if env == "GITHUB_TOKEN" or env.startswith("AZURE_"):
            monkeypatch.delenv(env, raising=False)


class _Recorder:
    def __init__(self, reply):
        self.reply = reply
        self.calls: list[dict] = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        return self.reply(url) if callable(self.reply) else self.reply


def _azure(**kw) -> ap.AiSettings:
    s = ap.AiSettings(provider="azure_openai", azure_endpoint=kw.pop("endpoint", "https://contoso.openai.azure.com/"),
                      azure_deployment=kw.pop("deployment", "gpt4o-prod"), **kw)
    s.set_key("azure_openai", "AZ-KEY")
    return s


# ------------------------------------------------------------------ registry
def test_providers_registered():
    assert ap.PROVIDERS["github"]["label"] == "GitHub Models (Copilot)"
    assert ap.PROVIDERS["github"]["env"] == ("GITHUB_TOKEN",)
    assert all("/" in m for m in ap.PROVIDERS["github"]["models"])
    assert ap.PROVIDERS["azure_openai"]["label"] == "Microsoft Azure OpenAI"
    assert ap.PROVIDERS["azure_openai"]["env"] == ("AZURE_OPENAI_API_KEY",)
    assert "GitHub" in ap.PRIVACY_NOTE and "Azure" in ap.PRIVACY_NOTE
    assert ap.AiSettings().azure_api_version == ap.DEFAULT_AZURE_API_VERSION == "2024-10-21"


# ------------------------------------------------------------------ GitHub Models
def test_github_chat_request_shape(monkeypatch):
    rec = _Recorder(OK_REPLY)
    monkeypatch.setattr(ap, "_http", rec)
    s = ap.AiSettings(provider="github")
    s.set_key("github", "ghp_TOKEN")
    assert ap.chat("SYS", MSGS, s) == "OK"
    (call,) = rec.calls
    assert call["method"] == "POST" and call["url"] == "https://models.github.ai/inference/chat/completions"
    h = call["headers"]
    assert h["Authorization"] == "Bearer ghp_TOKEN"
    assert h["Accept"] == "application/vnd.github+json" and h["X-GitHub-Api-Version"] == ap.GITHUB_API_VERSION
    body = call["body"]
    assert body["model"] == "openai/gpt-4o-mini"
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert [m["role"] for m in body["messages"][1:]] == ["user", "assistant", "user"]


def test_github_list_models_parses_catalog(monkeypatch):
    catalog = [
        {"id": "openai/gpt-4.1", "name": "GPT-4.1", "publisher": "OpenAI",
         "supported_input_modalities": ["text", "image"], "supported_output_modalities": ["text"]},
        {"id": "openai/text-embedding-3-small", "supported_output_modalities": ["embeddings"]},
        {"id": "meta/Llama-3.3-70B-Instruct", "supported_output_modalities": ["text"]},
        {"name": "no id"},
        "junk",
    ]
    rec = _Recorder(catalog)
    monkeypatch.setattr(ap, "_http", rec)
    s = ap.AiSettings(provider="github")
    s.set_key("github", "ghp_T")
    assert ap.list_models(s) == ["openai/gpt-4.1", "meta/Llama-3.3-70B-Instruct"]
    assert rec.calls[0]["method"] == "GET" and rec.calls[0]["url"] == "https://models.github.ai/catalog/models"
    assert rec.calls[0]["headers"]["Authorization"] == "Bearer ghp_T"


def test_github_retired_service_reply_is_explained(monkeypatch):
    def not_json(*a, **k):
        raise ap.AiError("The AI service sent a reply that is not JSON.")

    monkeypatch.setattr(ap, "_http", not_json)
    s = ap.AiSettings(provider="github")
    s.set_key("github", "ghp_T")
    with pytest.raises(ap.AiError, match="retired GitHub Models"):
        ap.chat("SYS", MSGS, s)


def test_github_needs_token(monkeypatch):
    monkeypatch.setattr(ap, "_http", lambda *a, **k: pytest.fail("network used"))
    with pytest.raises(ap.AiError, match="No API key for GitHub Models"):
        ap.chat("SYS", MSGS, ap.AiSettings(provider="github"))


# ------------------------------------------------------------------ Azure OpenAI
def test_azure_url_and_api_key_header(monkeypatch):
    rec = _Recorder(OK_REPLY)
    monkeypatch.setattr(ap, "_http", rec)
    assert ap.chat("SYS", MSGS, _azure(azure_api_version="2024-10-21")) == "OK"
    (call,) = rec.calls
    assert call["url"] == ("https://contoso.openai.azure.com/openai/deployments/gpt4o-prod/chat/completions"
                           "?api-version=2024-10-21")
    assert call["headers"] == {"api-key": "AZ-KEY"}
    assert "Authorization" not in call["headers"]
    assert call["body"]["messages"][0] == {"role": "system", "content": "SYS"}


def test_azure_endpoint_normalised_and_deployment_quoted():
    s = _azure(endpoint="contoso.openai.azure.com/openai/", deployment="my dep", azure_api_version="")
    assert ap.azure_chat_url(s) == ("https://contoso.openai.azure.com/openai/deployments/my%20dep/chat/completions"
                                    "?api-version=2024-10-21")


@pytest.mark.parametrize("endpoint,deployment,needle", [
    ("", "dep", "No Azure OpenAI endpoint"),
    ("https://contoso.openai.azure.com", "", "No Azure OpenAI deployment"),
    ("ftp://contoso", "dep", "must start with https"),
])
def test_azure_missing_config_is_friendly(monkeypatch, endpoint, deployment, needle):
    monkeypatch.setattr(ap, "_http", lambda *a, **k: pytest.fail("network used"))
    with pytest.raises(ap.AiError, match=needle):
        ap.chat("SYS", MSGS, _azure(endpoint=endpoint, deployment=deployment))


def test_azure_list_models_is_the_configured_deployment(monkeypatch):
    monkeypatch.setattr(ap, "_http", lambda *a, **k: pytest.fail("network used"))
    assert ap.list_models(_azure()) == ["gpt4o-prod"]
    with pytest.raises(ap.AiError, match="deployment"):
        ap.list_models(_azure(deployment=""))


# ------------------------------------------------------------------ env fallbacks
def test_env_fallbacks(monkeypatch):
    rec = _Recorder(OK_REPLY)
    monkeypatch.setattr(ap, "_http", rec)
    monkeypatch.setenv("GITHUB_TOKEN", "gh-env")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-env")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://envres.openai.azure.com/")
    assert ap.AiSettings(provider="github").key_for() == "gh-env"
    s = ap.AiSettings(provider="azure_openai", azure_deployment="d1")
    assert s.key_for() == "az-env" and s.azure_endpoint_for() == "https://envres.openai.azure.com"
    ap.chat("SYS", MSGS, s)
    assert rec.calls[-1]["url"].startswith("https://envres.openai.azure.com/openai/deployments/d1/")
    assert rec.calls[-1]["headers"]["api-key"] == "az-env"
    saved = ap.AiSettings(provider="azure_openai", azure_endpoint="https://saved.openai.azure.com")
    assert saved.azure_endpoint_for() == "https://saved.openai.azure.com"  # saved value beats env


# ------------------------------------------------------------------ settings + labels
def test_settings_round_trip_azure_fields_and_keys_encrypted(tmp_path):
    s = _azure(azure_api_version="2024-10-21")
    s.set_key("github", "ghp_SECRET_GH")
    s.set_key("azure_openai", "AZ_SECRET_KEY")
    s.models["github"] = "openai/gpt-4.1"
    ap.save_settings(s)
    raw = (tmp_path / "ai.json").read_text(encoding="utf-8")
    assert "SECRET" not in raw
    if sys.platform == "win32":
        assert raw.count('"dpapi:') == 2
    data = json.loads(raw)
    assert data["azure_endpoint"] == "https://contoso.openai.azure.com/"
    assert data["azure_deployment"] == "gpt4o-prod" and data["azure_api_version"] == "2024-10-21"
    back = ap.load_settings()
    assert back.provider == "azure_openai" and back.model_for() == "gpt4o-prod"
    assert back.azure_endpoint == s.azure_endpoint and back.azure_api_version == "2024-10-21"
    assert back.key_for("github") == "ghp_SECRET_GH" and back.key_for() == "AZ_SECRET_KEY"
    assert back.model_for("github") == "openai/gpt-4.1"


def test_old_settings_file_without_azure_fields_loads(tmp_path):
    (tmp_path / "ai.json").write_text(json.dumps({"provider": "openai", "models": {"openai": "gpt-4o"}}),
                                      encoding="utf-8")
    s = ap.load_settings()
    assert s.provider == "openai" and s.model_for() == "gpt-4o"
    assert s.azure_endpoint == "" and s.azure_deployment == "" and s.azure_api_version == "2024-10-21"


def test_labels():
    assert ap.AiSettings(provider="github").label() == "GitHub Models · gpt-4o-mini"
    assert ap.AiSettings(provider="github", models={"github": "meta/Llama-3.3-70B-Instruct"}).label() == \
        "GitHub Models · Llama-3.3-70B-Instruct"
    assert _azure().label() == "Azure OpenAI · gpt4o-prod"
    assert ap.AiSettings(provider="azure_openai").label() == "Azure OpenAI · (no deployment)"
    assert ap.AiSettings(provider="openai").label() == "OpenAI · gpt-4o-mini"


def test_http_401_is_friendly(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b'{"error":{"message":"Bad credentials"}}'))

    monkeypatch.setattr(ap.urllib.request, "urlopen", boom)
    s = _azure()
    with pytest.raises(ap.AiError, match="rejected \\(401\\).*Bad credentials"):
        ap.chat("SYS", MSGS, s)
    g = ap.AiSettings(provider="github")
    g.set_key("github", "ghp_bad")
    with pytest.raises(ap.AiError, match="rejected \\(401\\)"):
        ap.list_models(g)


# ------------------------------------------------------------------ headless UI
def _buttons(widget, text):
    import customtkinter as ctk

    found = []
    for child in widget.winfo_children():
        if isinstance(child, ctk.CTkButton) and child.cget("text") == text:
            found.append(child)
        found.extend(_buttons(child, text))
    return found


def _click(dlg, text):
    (btn,) = _buttons(dlg, text)
    assert str(btn.cget("state")) == "normal", text
    btn.invoke()
    dlg.update_idletasks()


@pytest.mark.skipif(not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and os.name != "nt",
                    reason="No display for CustomTkinter")
def test_settings_dialog_github_then_azure(tmp_path, monkeypatch):
    ctk = pytest.importorskip("customtkinter")
    from cabinet_studio.ui import ai_settings
    from cabinet_studio.ui.theme import Fonts, choose_families

    def reply(url):
        if url.endswith("/catalog/models"):
            return [{"id": "openai/gpt-4.1", "supported_output_modalities": ["text"]},
                    {"id": "openai/gpt-4o-mini", "supported_output_modalities": ["text"]}]
        return OK_REPLY

    rec = _Recorder(reply)
    monkeypatch.setattr(ap, "_http", rec)
    monkeypatch.setattr(ai_settings, "SYNC", True)
    saved: list[ap.AiSettings] = []

    root = ctk.CTk()
    root.withdraw()
    try:
        dlg = ai_settings.AiSettingsDialog(root, Fonts(*choose_families(root)), on_saved=saved.append)
        dlg.update_idletasks()
        assert "no third-party API" in dlg.microsoft_note.cget("text")
        assert all(str(e.cget("state")) == "disabled" for e in dlg.azure_entries.values())

        # GitHub: token, refresh models, test, save.
        dlg.provider_var.set(ap.PROVIDERS["github"]["label"])
        dlg._show_provider()
        assert dlg.key_label.cget("text") == "Token" and "models:read" in dlg.key_note.cget("text")
        assert all(str(e.cget("state")) == "disabled" for e in dlg.azure_entries.values())
        dlg.key_entry.insert(0, "ghp_UI_TOKEN")
        _click(dlg, "Refresh models")
        assert rec.calls[-1]["url"] == ap.GITHUB_CATALOG_URL
        assert dlg.model_box.get() in {"openai/gpt-4.1", "openai/gpt-4o-mini"}
        _click(dlg, "Test connection")
        assert "Connected" in dlg.status.cget("text"), dlg.status.cget("text")
        assert rec.calls[-1]["headers"]["Authorization"] == "Bearer ghp_UI_TOKEN"
        _click(dlg, "Save")
        data = json.loads((tmp_path / "ai.json").read_text(encoding="utf-8"))
        assert data["provider"] == "github" and "ghp_UI_TOKEN" not in json.dumps(data)
        assert saved[-1].label().startswith("GitHub Models · ")

        # Azure: endpoint / deployment / api-version + key, test, save.
        dlg.provider_var.set(ap.PROVIDERS["azure_openai"]["label"])
        dlg._show_provider()
        assert all(str(e.cget("state")) == "normal" for e in dlg.azure_entries.values())
        assert str(dlg.model_box.cget("state")) == "disabled"
        assert "AZURE_OPENAI_API_KEY" in dlg.key_note.cget("text")
        dlg.azure_entries["endpoint"].insert(0, "https://contoso.openai.azure.com")
        dlg.azure_entries["deployment"].insert(0, "gpt4o-prod")
        dlg.azure_entries["api_version"].delete(0, "end")
        dlg.azure_entries["api_version"].insert(0, "2024-10-21")
        dlg.key_entry.insert(0, "AZ_UI_KEY")
        _click(dlg, "Refresh models")
        assert dlg.model_box.get() == "gpt4o-prod"
        _click(dlg, "Test connection")
        assert "Connected to Azure OpenAI · gpt4o-prod" in dlg.status.cget("text"), dlg.status.cget("text")
        assert rec.calls[-1]["url"] == ("https://contoso.openai.azure.com/openai/deployments/gpt4o-prod/"
                                        "chat/completions?api-version=2024-10-21")
        assert rec.calls[-1]["headers"]["api-key"] == "AZ_UI_KEY"
        _click(dlg, "Save")
        raw = (tmp_path / "ai.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["provider"] == "azure_openai"
        assert data["azure_endpoint"] == "https://contoso.openai.azure.com"
        assert data["azure_deployment"] == "gpt4o-prod" and data["azure_api_version"] == "2024-10-21"
        assert set(data["keys"]) == {"github", "azure_openai"} and "AZ_UI_KEY" not in raw and "ghp_UI" not in raw
        back = ap.load_settings()
        assert back.key_for("azure_openai") == "AZ_UI_KEY" and back.key_for("github") == "ghp_UI_TOKEN"
        assert saved[-1].label() == "Azure OpenAI · gpt4o-prod"

        # Switching back to a non-Azure provider disables the Azure rows again.
        dlg.provider_var.set(ap.PROVIDERS["openai"]["label"])
        dlg._show_provider()
        assert dlg.key_label.cget("text") == "API key"
        assert all(str(e.cget("state")) == "disabled" for e in dlg.azure_entries.values())
        _click(dlg, "Close")
    finally:
        root.destroy()
