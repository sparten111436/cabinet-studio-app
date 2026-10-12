"""v0.3.24 Groq + xAI (Grok) OpenAI-compatible providers (no network: ai_providers._http is faked)."""

from __future__ import annotations

import pytest

from cabinet_studio.services import ai_providers as ap

OK_REPLY = {"choices": [{"message": {"content": "OK"}}]}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CABINET_STUDIO_AI_SETTINGS", str(tmp_path / "ai.json"))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)


@pytest.mark.parametrize("pid,base", [("groq", "https://api.groq.com/openai/v1"), ("xai", "https://api.x.ai/v1")])
def test_chat_and_list_models(monkeypatch, pid, base):
    calls = []

    def fake(method, url, headers, body, timeout):
        calls.append((method, url, headers, body))
        if url.endswith("/models"):
            return {"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "whisper-large-v3"}]}
        return OK_REPLY

    monkeypatch.setattr(ap, "_http", fake)
    s = ap.AiSettings(provider=pid)
    s.set_key(pid, "KEY-1")
    assert "OK" in ap.chat("sys", [{"role": "user", "content": "q"}], s)
    method, url, headers, body = calls[-1]
    assert (method, url) == ("POST", base + "/chat/completions")
    assert headers["Authorization"] == "Bearer KEY-1"
    assert body["model"] == ap.PROVIDERS[pid]["models"][0]
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert ap.list_models(s) == ["model-a", "model-b"]


def test_missing_key_is_reported(monkeypatch):
    monkeypatch.setattr(ap, "_http", lambda *a: OK_REPLY)
    with pytest.raises(ap.AiError):
        ap.chat("sys", [{"role": "user", "content": "q"}], ap.AiSettings(provider="groq"))
