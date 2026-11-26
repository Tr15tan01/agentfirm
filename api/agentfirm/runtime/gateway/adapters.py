"""Provider adapters. Each adapter only translates one provider's HTTP API to
ModelRequest/ModelResponse — routing, retries, fallbacks and metering live in the gateway.

Assumptions (documented in ADR 0003, verify with each provider):
* OpenAI: Chat Completions API (`/v1/chat/completions`), JSON-schema structured output.
* Gemini: `models/{model}:generateContent` with `x-goog-api-key`, JSON mime type. Gemini 3.5+ models
  reject `temperature`/`top_p`/`top_k` and prefilled model turns, so those are never sent to them.
* GN7T: OpenAI-compatible chat completions at `{base_url}/chat/completions`, where the admin sets
  `base_url` to `https://<host>/api/v1/openai/v1`. GN7T refuses every `response_format` other than
  `text`, so JSON is requested only through the system prompt (verified against GN7T's
  docs/inference.md, not the earlier ADR assumption).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from .types import ModelRequest, ModelResponse, ProviderError

RETRIABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class Adapter(Protocol):
    async def complete(self, client: httpx.AsyncClient, req: ModelRequest, *, model: str, api_key: str | None, base_url: str | None) -> ModelResponse: ...


GN7T_CANONICAL_PATH = "/api/v1/openai/v1"
#: Paths people commonly save instead of GN7T's real one; all map to the canonical path.
_GN7T_PATH_ALIASES = {"", "/api", "/api/v1", "/v1", "/openai/v1", "/api/v1/openai"}


def gn7t_api_root(base_url: str | None) -> str:
    """GN7T serves its OpenAI-compatible API at https://<host>/api/v1/openai/v1 (and nowhere else).
    A bare host, or one of the usual near-misses (/v1, /api/v1 …), is completed to that path; a custom
    path (a reverse proxy mounting GN7T elsewhere) is kept as it is."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    parts = urlparse(base)
    if parts.path.rstrip("/") in _GN7T_PATH_ALIASES:
        return f"{parts.scheme}://{parts.netloc}{GN7T_CANONICAL_PATH}"
    return base


_HINTS: dict[str, dict[int, str]] = {
    "gn7t": {
        401: "GN7T rejected the API key. Create one under API Keys in GN7T (it looks like gn7t_<id>_<secret>) and save it here.",
        403: "GN7T refused access: the key's owner may lack permission for this model, or the plan quota is used up.",
        404: "Not found: the base URL should end with /api/v1/openai/v1, and the model must exist on GN7T (use Import models to see real model ids).",
        422: "GN7T could not process the request, usually because the input is longer than the model's context allows. GN7T models are small; give it short tasks.",
        429: "GN7T is rate limiting: too many simultaneous requests for this key's plan.",
    }
}


def _raise_for(resp: httpx.Response, provider: str) -> None:
    if resp.status_code < 400:
        return
    detail = resp.text[:300]
    hint = _HINTS.get(provider, {}).get(resp.status_code)
    msg = f"{provider} HTTP {resp.status_code}: {detail}" + (f" — {hint}" if hint else "")
    raise ProviderError(msg, retriable=resp.status_code in RETRIABLE_STATUS, status=resp.status_code)


def describe_connect_error(provider: str, url: str, exc: httpx.HTTPError) -> str:
    """A message an admin can act on, instead of a bare exception class name."""
    host = urlparse(url).netloc or url
    kind = type(exc).__name__
    if isinstance(exc, httpx.ConnectTimeout | httpx.ReadTimeout | httpx.PoolTimeout):
        return f"{provider}: {host} did not answer in time ({kind}). The server may be overloaded, or generation is slower than the timeout."
    if isinstance(exc, httpx.ConnectError):
        return f"{provider}: cannot connect to {host} ({kind}: {exc}). Check the base URL, DNS, and that this server can reach it (private .internal names only resolve on that network)."
    return f"{provider}: request to {host} failed ({kind}: {exc})"


def _schema_instruction(schema: dict[str, Any]) -> str:
    return "Respond with a single JSON object that validates against this JSON Schema. No prose.\n" + json.dumps(schema)


#: Gemini models that reject sampling parameters (see module docstring). Matched as prefixes.
GEMINI_NO_SAMPLING = ("gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash")


class OpenAICompatible:
    """OpenAI Chat Completions, also used for GN7T and other OpenAI-compatible servers.

    `native_json_schema`: send OpenAI's json_schema response_format. Servers that refuse any
    response_format (GN7T) get the schema in the system prompt instead.
    """

    def __init__(
        self,
        provider: str,
        default_base_url: str | None,
        *,
        native_json_schema: bool,
        max_tokens_param: str,
        require_key: bool = False,
        normalize_base: Callable[[str | None], str] | None = None,
    ) -> None:
        self.provider = provider
        self.default_base_url = default_base_url
        self.native_json_schema = native_json_schema
        self.max_tokens_param = max_tokens_param
        self.require_key = require_key
        self.normalize_base = normalize_base

    async def complete(self, client: httpx.AsyncClient, req: ModelRequest, *, model: str, api_key: str | None, base_url: str | None) -> ModelResponse:
        url = (self.normalize_base(base_url) if self.normalize_base else (base_url or self.default_base_url or "")).rstrip("/")
        if not url:
            raise ProviderError(f"{self.provider}: base_url not configured", retriable=False)
        if self.require_key and not api_key:
            raise ProviderError(f"{self.provider}: API key not configured. Save one under Admin → Models.", retriable=False)
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        body: dict[str, Any] = {"model": model, "messages": messages, self.max_tokens_param: req.max_tokens}
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.json_schema is not None:
            if self.native_json_schema:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": req.task.replace(".", "_")[:60], "schema": req.json_schema, "strict": False},
                }
            else:
                body["messages"] = [*messages, {"role": "system", "content": _schema_instruction(req.json_schema)}]
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            resp = await client.post(f"{url}/chat/completions", json=body, headers=headers)
            if resp.status_code == 400 and "temperature" in resp.text and "temperature" in body:
                # Some reasoning models only accept their default temperature.
                body.pop("temperature")
                resp = await client.post(f"{url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(describe_connect_error(self.provider, url, exc), retriable=True) from exc
        _raise_for(resp, self.provider)
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.provider}: unexpected response shape", retriable=True) from exc
        usage = data.get("usage") or {}
        return ModelResponse(text=text, tokens_in=int(usage.get("prompt_tokens", 0)), tokens_out=int(usage.get("completion_tokens", 0)))


GEMINI_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


def gemini_api_root(base_url: str | None) -> str:
    """Gemini's REST API lives under /v1beta. A stored bare host (no path) gets that version added,
    so a base URL saved as https://generativelanguage.googleapis.com still reaches the right endpoint."""
    base = (base_url or "").rstrip("/") or GEMINI_DEFAULT_BASE
    if urlparse(base).path in ("", "/"):
        base += "/v1beta"
    return base


class Gemini:
    provider = "gemini"
    default_base_url = GEMINI_DEFAULT_BASE

    async def complete(self, client: httpx.AsyncClient, req: ModelRequest, *, model: str, api_key: str | None, base_url: str | None) -> ModelResponse:
        if not api_key:
            raise ProviderError("gemini: API key not configured", retriable=False)
        system = "\n\n".join(m.content for m in req.messages if m.role == "system")
        if req.json_schema is not None:
            system = f"{system}\n\n{_schema_instruction(req.json_schema)}".strip()
        contents = [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]} for m in req.messages if m.role != "system"]
        cfg: dict[str, Any] = {"maxOutputTokens": req.max_tokens}
        if req.temperature is not None:
            cfg["temperature"] = req.temperature
        if req.json_schema is not None:
            cfg["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": contents, "generationConfig": cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if model.startswith(GEMINI_NO_SAMPLING):
            cfg.pop("temperature", None)
        if contents and contents[-1]["role"] == "model":
            # These models reject a conversation that ends with a model turn; ask for the next step.
            contents.append({"role": "user", "parts": [{"text": "Continue."}]})
        base = gemini_api_root(base_url)
        resp = await client.post(f"{base}/models/{model}:generateContent", json=body, headers={"x-goog-api-key": api_key})
        _raise_for(resp, "gemini")
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError(f"gemini: no candidate ({reason or 'unexpected shape'})", retriable=reason is None) from exc
        usage = data.get("usageMetadata") or {}
        return ModelResponse(text=text, tokens_in=int(usage.get("promptTokenCount", 0)), tokens_out=int(usage.get("candidatesTokenCount", 0)))


ADAPTERS: dict[str, Adapter] = {
    "openai": OpenAICompatible("openai", "https://api.openai.com/v1", native_json_schema=True, max_tokens_param="max_completion_tokens"),
    "gemini": Gemini(),
    "gn7t": OpenAICompatible("gn7t", None, native_json_schema=False, max_tokens_param="max_tokens", require_key=True, normalize_base=gn7t_api_root),
}
