"""Selectable AI back ends for the interview and the live simulation assistant.

Built-in (offline rules) is always available and is the fallback. OpenAI,
Anthropic, Google Gemini, GitHub Models, Microsoft Azure OpenAI and a local
Ollama server are reached with plain HTTPS (stdlib ``urllib``) so the frozen exe
needs no extra packages.

Microsoft Copilot itself has no third-party API; GitHub Models and Azure OpenAI
are the Microsoft routes. Endpoints were checked against the official docs on
2026-10-06:

* GitHub Models - https://docs.github.com/en/rest/models/inference and
  https://docs.github.com/en/rest/models/catalog (last published versions:
  ``POST https://models.github.ai/inference/chat/completions``,
  ``GET https://models.github.ai/catalog/models``, Bearer token with
  ``models:read``, ``Accept: application/vnd.github+json``,
  ``X-GitHub-Api-Version: 2026-03-10``). Those pages now state that GitHub
  RETIRED GitHub Models on 2026-07-30 and the endpoints only answer a plain
  ``OK``; the provider is kept for accounts that still have access and fails
  with a clear message otherwise.
* Azure OpenAI - https://learn.microsoft.com/en-us/azure/foundry/openai/reference
  (``{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=``,
  ``api-key`` header, latest dated GA data-plane version ``2024-10-21``) and
  https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle
  (the newer version-less ``/openai/v1`` GA API is not used here).

Settings live per Windows user in ``%APPDATA%\\CabinetStudio\\ai_settings.json``
(never in a project file or the synced ``saves\\`` folder). API keys are
encrypted with Windows DPAPI (current user only).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUILTIN = "builtin"

# id -> label, needs a key, env vars checked when no key is saved, starter model list
PROVIDERS: dict[str, dict[str, Any]] = {
    BUILTIN: {
        "label": "Cabinet Studio AI (free, offline)",
        "needs_key": False,
        "env": (),
        "models": ["rules"],
    },
    "openai": {
        "label": "OpenAI (ChatGPT)",
        "needs_key": True,
        "env": ("OPENAI_API_KEY",),
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "needs_key": True,
        "env": ("ANTHROPIC_API_KEY",),
        "models": ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-1"],
    },
    "gemini": {
        "label": "Google (Gemini)",
        "needs_key": True,
        "env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "models": ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    },
    "github": {
        "label": "GitHub Models (Copilot)",
        "needs_key": True,
        "env": ("GITHUB_TOKEN",),
        "models": ["openai/gpt-4o-mini", "openai/gpt-4.1", "meta/Llama-3.3-70B-Instruct"],
    },
    "azure_openai": {
        "label": "Microsoft Azure OpenAI",
        "needs_key": True,
        "env": ("AZURE_OPENAI_API_KEY",),
        "models": [],  # Azure calls a deployment (AiSettings.azure_deployment), not a model id
    },
    "ollama": {
        "label": "Ollama (local, offline)",
        "needs_key": False,
        "env": (),
        "models": ["llama3.1", "qwen2.5", "mistral"],
    },
    "groq": {
        "label": "Groq (free key)",
        "needs_key": True,
        "env": ("GROQ_API_KEY",),
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    },
    "xai": {
        "label": "xAI (Grok)",
        "needs_key": True,
        "env": ("XAI_API_KEY",),
        "models": ["grok-4", "grok-3-mini"],
    },
}

OPENAI_COMPAT_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "xai": "https://api.x.ai/v1",
}

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_S = 90
MAX_TOKENS = 1600

GITHUB_CHAT_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_CATALOG_URL = "https://models.github.ai/catalog/models"
GITHUB_API_VERSION = "2026-03-10"
GITHUB_RETIRED_HINT = ("GitHub retired GitHub Models on 2026-07-30 (docs.github.com/en/github-models); "
                       "use Microsoft Azure OpenAI instead.")
AZURE_ENDPOINT_ENV = "AZURE_OPENAI_ENDPOINT"
DEFAULT_AZURE_API_VERSION = "2024-10-21"

_SHORT_LABELS = {"github": "GitHub Models", "azure_openai": "Azure OpenAI"}

PRIVACY_NOTE = (
    "Cloud AIs (OpenAI, Anthropic, Google, GitHub Models, Microsoft Azure OpenAI, Groq, xAI) receive your "
    "interview answers, ladder program and "
    "live simulation state when you ask a question, and bill your own account. "
    "Ollama and Built-in keep everything on this PC."
)


class AiError(Exception):
    """A friendly, user-facing AI failure (the caller falls back to Built-in)."""


# ------------------------------------------------------------------ key protection
def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out))
    if not ok:
        raise OSError("Windows could not protect/unprotect the API key.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect_key(key: str) -> str:
    raw = (key or "").strip().encode("utf-8")
    if not raw:
        return ""
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(raw, True)).decode("ascii")
    return "b64:" + base64.b64encode(raw).decode("ascii")


def unprotect_key(stored: str) -> str:
    stored = (stored or "").strip()
    try:
        if stored.startswith("dpapi:") and sys.platform == "win32":
            return _dpapi(base64.b64decode(stored[6:]), False).decode("utf-8")
        if stored.startswith("b64:"):
            return base64.b64decode(stored[4:]).decode("utf-8")
    except Exception:
        return ""
    return ""


# ------------------------------------------------------------------ settings
def ai_settings_path() -> Path:
    override = os.environ.get("CABINET_STUDIO_AI_SETTINGS")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "CabinetStudio" / "ai_settings.json"


@dataclass
class AiSettings:
    provider: str = BUILTIN
    models: dict[str, str] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)  # protected (dpapi:/b64:)
    ollama_url: str = DEFAULT_OLLAMA_URL
    timeout_s: int = DEFAULT_TIMEOUT_S
    azure_endpoint: str = ""
    azure_deployment: str = ""
    azure_api_version: str = DEFAULT_AZURE_API_VERSION

    def model_for(self, provider: str | None = None) -> str:
        pid = provider or self.provider
        if pid == "azure_openai":
            return (self.azure_deployment or "").strip()
        return (self.models.get(pid) or PROVIDERS.get(pid, PROVIDERS[BUILTIN])["models"][0]).strip()

    def azure_endpoint_for(self) -> str:
        """Saved endpoint, else AZURE_OPENAI_ENDPOINT; normalised to https://host (no trailing /openai)."""
        url = (self.azure_endpoint or os.environ.get(AZURE_ENDPOINT_ENV, "")).strip().rstrip("/")
        if url.lower().endswith("/openai"):
            url = url[: -len("/openai")]
        if url and "://" not in url:
            url = "https://" + url
        return url

    def key_for(self, provider: str | None = None) -> str:
        pid = provider or self.provider
        key = unprotect_key(self.keys.get(pid, ""))
        if key:
            return key
        for env in PROVIDERS.get(pid, {}).get("env", ()):
            if os.environ.get(env):
                return os.environ[env].strip()
        return ""

    def has_key(self, provider: str | None = None) -> bool:
        return bool(self.key_for(provider))

    def set_key(self, provider: str, key: str) -> None:
        if (key or "").strip():
            self.keys[provider] = protect_key(key)
        else:
            self.keys.pop(provider, None)

    def label(self) -> str:
        if self.provider == BUILTIN or self.provider not in PROVIDERS:
            return PROVIDERS[BUILTIN]["label"]
        name = _SHORT_LABELS.get(self.provider) or PROVIDERS[self.provider]["label"].split(" (")[0]
        model = self.model_for()
        if self.provider == "github":
            model = model.split("/")[-1]
        return f"{name} · {model or '(no deployment)'}"


def load_settings() -> AiSettings:
    try:
        data = json.loads(ai_settings_path().read_text(encoding="utf-8"))
    except Exception:
        return AiSettings()
    if not isinstance(data, dict):
        return AiSettings()
    provider = str(data.get("provider") or BUILTIN)
    return AiSettings(
        provider=provider if provider in PROVIDERS else BUILTIN,
        models={str(k): str(v) for k, v in (data.get("models") or {}).items() if k in PROVIDERS},
        keys={str(k): str(v) for k, v in (data.get("keys") or {}).items() if k in PROVIDERS},
        ollama_url=str(data.get("ollama_url") or DEFAULT_OLLAMA_URL),
        timeout_s=int(data.get("timeout_s") or DEFAULT_TIMEOUT_S),
        azure_endpoint=str(data.get("azure_endpoint") or ""),
        azure_deployment=str(data.get("azure_deployment") or ""),
        azure_api_version=str(data.get("azure_api_version") or DEFAULT_AZURE_API_VERSION),
    )


def save_settings(settings: AiSettings) -> None:
    path = ai_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "provider": settings.provider,
        "models": settings.models,
        "keys": settings.keys,
        "ollama_url": settings.ollama_url,
        "timeout_s": settings.timeout_s,
        "azure_endpoint": settings.azure_endpoint,
        "azure_deployment": settings.azure_deployment,
        "azure_api_version": settings.azure_api_version,
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ HTTP
def _http(method: str, url: str, headers: dict[str, str], body: dict | None, timeout: float) -> dict:
    """One JSON request. Tests replace this function; nothing else touches the network."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            err = payload.get("error")
            detail = (err.get("message") if isinstance(err, dict) else err) or payload.get("message") or ""
        except Exception:
            pass
        if exc.code in (401, 403):
            raise AiError(f"The API key was rejected ({exc.code}). Check it in AI settings. {detail}".strip()) from None
        if exc.code == 404:
            raise AiError(f"Model or address not found (404). Pick another model. {detail}".strip()) from None
        if exc.code == 429:
            raise AiError(f"Rate limit or quota reached (429). {detail}".strip()) from None
        raise AiError(f"AI service error {exc.code}. {detail}".strip()) from None
    except urllib.error.URLError as exc:
        raise AiError(f"Could not reach the AI service ({exc.reason}). Check the internet / Ollama.") from None
    except TimeoutError:
        raise AiError("The AI took too long to answer (timeout).") from None
    except json.JSONDecodeError:
        raise AiError("The AI service sent a reply that is not JSON.") from None


def _need_key(settings: AiSettings, pid: str) -> str:
    key = settings.key_for(pid)
    if not key:
        raise AiError(f"No API key for {PROVIDERS[pid]['label']}. Add one in AI settings.")
    return key


def _openai_text(out: Any, name: str) -> str:
    try:
        return out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AiError(f"{name} sent an unexpected reply.") from None


def _github_headers(settings: AiSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {_need_key(settings, 'github')}",
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}


def _github_http(method: str, url: str, headers: dict[str, str], body: dict | None, timeout: float) -> Any:
    try:
        return _http(method, url, headers, body, timeout)
    except AiError as exc:
        if "not JSON" in str(exc) or "(404)" in str(exc):
            raise AiError(f"{exc} {GITHUB_RETIRED_HINT}") from None
        raise


def _azure_target(settings: AiSettings) -> tuple[str, str, str]:
    endpoint = settings.azure_endpoint_for()
    if not endpoint:
        raise AiError("No Azure OpenAI endpoint. Enter https://<resource>.openai.azure.com in AI settings "
                      f"(or set {AZURE_ENDPOINT_ENV}).")
    if not endpoint.lower().startswith(("https://", "http://")):
        raise AiError(f"The Azure OpenAI endpoint must start with https:// (got {endpoint}).")
    deployment = (settings.azure_deployment or "").strip()
    if not deployment:
        raise AiError("No Azure OpenAI deployment name. Enter the deployment you created in the Azure portal "
                      "(Azure AI Foundry > Deployments) in AI settings.")
    version = (settings.azure_api_version or "").strip() or DEFAULT_AZURE_API_VERSION
    return endpoint, deployment, version


def azure_chat_url(settings: AiSettings) -> str:
    endpoint, deployment, version = _azure_target(settings)
    return (f"{endpoint}/openai/deployments/{urllib.parse.quote(deployment, safe='')}/chat/completions?"
            + urllib.parse.urlencode({"api-version": version}))


def chat(system: str, messages: list[dict[str, str]], settings: AiSettings | None = None) -> str:
    """Send a conversation; return the reply text. Raises AiError (never for Built-in callers)."""
    s = settings or load_settings()
    pid = s.provider
    if pid == BUILTIN or pid not in PROVIDERS:
        raise AiError("Built-in rules selected (no AI service).")
    model = s.model_for(pid)
    msgs = [{"role": m["role"], "content": str(m["content"])} for m in messages if m.get("content")]
    t = float(s.timeout_s or DEFAULT_TIMEOUT_S)
    if pid == "openai":
        out = _http("POST", "https://api.openai.com/v1/chat/completions",
                    {"Authorization": f"Bearer {_need_key(s, pid)}"},
                    {"model": model, "messages": [{"role": "system", "content": system}] + msgs}, t)
        text = _openai_text(out, "OpenAI")
    elif pid in OPENAI_COMPAT_URLS:
        out = _http("POST", OPENAI_COMPAT_URLS[pid] + "/chat/completions",
                    {"Authorization": f"Bearer {_need_key(s, pid)}"},
                    {"model": model, "messages": [{"role": "system", "content": system}] + msgs}, t)
        text = _openai_text(out, PROVIDERS[pid]["label"].split(" (")[0])
    elif pid == "github":
        headers = _github_headers(s)
        out = _github_http("POST", GITHUB_CHAT_URL, headers,
                           {"model": model, "messages": [{"role": "system", "content": system}] + msgs}, t)
        text = _openai_text(out, "GitHub Models")
    elif pid == "azure_openai":
        url = azure_chat_url(s)
        out = _http("POST", url, {"api-key": _need_key(s, pid)},
                    {"messages": [{"role": "system", "content": system}] + msgs}, t)
        text = _openai_text(out, "Azure OpenAI")
    elif pid == "anthropic":
        out = _http("POST", "https://api.anthropic.com/v1/messages",
                    {"x-api-key": _need_key(s, pid), "anthropic-version": "2023-06-01"},
                    {"model": model, "max_tokens": MAX_TOKENS, "system": system, "messages": msgs}, t)
        text = "".join(b.get("text", "") for b in out.get("content") or [] if isinstance(b, dict))
    elif pid == "gemini":
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{urllib.parse.quote(model, safe='')}:generateContent")
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in msgs]
        out = _http("POST", url, {"x-goog-api-key": _need_key(s, pid)},
                    {"system_instruction": {"parts": [{"text": system}]}, "contents": contents}, t)
        try:
            parts = out["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            raise AiError("Gemini sent an unexpected reply (it may have blocked the request).") from None
    else:  # ollama
        base = (s.ollama_url or DEFAULT_OLLAMA_URL).rstrip("/")
        out = _http("POST", f"{base}/api/chat", {},
                    {"model": model, "stream": False,
                     "messages": [{"role": "system", "content": system}] + msgs}, t)
        text = ((out.get("message") or {}).get("content")) or ""
    text = (text or "").strip()
    if not text:
        raise AiError("The AI returned an empty answer.")
    return text


def list_models(settings: AiSettings, provider: str | None = None) -> list[str]:
    """Ask the provider which models this key can use (falls back to the starter list)."""
    pid = provider or settings.provider
    t = float(min(settings.timeout_s or DEFAULT_TIMEOUT_S, 30))
    if pid == "openai":
        out = _http("GET", "https://api.openai.com/v1/models", {"Authorization": f"Bearer {_need_key(settings, pid)}"}, None, t)
        names = sorted(m.get("id", "") for m in out.get("data") or [])
        return [n for n in names if n.startswith(("gpt", "o", "chatgpt"))] or names
    if pid in OPENAI_COMPAT_URLS:
        out = _http("GET", OPENAI_COMPAT_URLS[pid] + "/models",
                    {"Authorization": f"Bearer {_need_key(settings, pid)}"}, None, t)
        names = sorted(m.get("id", "") for m in out.get("data") or [] if m.get("id"))
        return [n for n in names if not any(w in n for w in ("whisper", "tts", "guard", "image"))] or names
    if pid == "anthropic":
        out = _http("GET", "https://api.anthropic.com/v1/models",
                    {"x-api-key": _need_key(settings, pid), "anthropic-version": "2023-06-01"}, None, t)
        return [m.get("id", "") for m in out.get("data") or [] if m.get("id")]
    if pid == "github":
        out = _github_http("GET", GITHUB_CATALOG_URL, _github_headers(settings), None, t)
        items = out.get("data") if isinstance(out, dict) else out  # documented shape: a JSON array
        names = []
        for m in items or []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            outputs = m.get("supported_output_modalities")
            if outputs is not None and "text" not in outputs:
                continue
            if "embedding" in str(m["id"]).lower():
                continue
            names.append(str(m["id"]))
        return names
    if pid == "azure_openai":
        # The data-plane API has no "list deployments" call (that is the Azure Resource Manager control
        # plane, which needs Entra ID sign-in, not the resource key), so only the configured one is offered.
        deployment = (settings.azure_deployment or "").strip()
        if not deployment:
            raise AiError("No Azure OpenAI deployment name. Enter it in AI settings - Azure cannot list "
                          "deployments with an API key.")
        return [deployment]
    if pid == "gemini":
        out = _http("GET", "https://generativelanguage.googleapis.com/v1beta/models",
                    {"x-goog-api-key": _need_key(settings, pid)}, None, t)
        return [m.get("name", "").split("/", 1)[-1] for m in out.get("models") or []
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    if pid == "ollama":
        base = (settings.ollama_url or DEFAULT_OLLAMA_URL).rstrip("/")
        out = _http("GET", f"{base}/api/tags", {}, None, t)
        return [m.get("name", "") for m in out.get("models") or [] if m.get("name")]
    return list(PROVIDERS[BUILTIN]["models"])


def test_connection(settings: AiSettings) -> str:
    if settings.provider == BUILTIN:
        return "Built-in rules are always available (offline)."
    reply = chat("You are a connection test. Reply with the single word OK.",
                 [{"role": "user", "content": "Reply with OK."}], settings)
    return f"Connected to {settings.label()} - it replied: {reply[:60]}"
