"""Import the model list a provider really offers, so super-admins don't type model IDs by hand.

Each provider has its own list endpoint (verified against the providers' docs):
* OpenAI:  GET {base}/models                       (Bearer key)
* Gemini:  GET {base}/models?pageSize=…            (x-goog-api-key; only models that support generateContent or embedContent)
* GN7T:    GET {base_url}/models (base_url = https://<host>/api/v1/openai/v1)   (Bearer key)

Imported models are returned with *inferred* capabilities only. They are created disabled, and a
super-admin reviews, enables and prices them. Nothing here changes routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from .adapters import gemini_api_root
from .types import ProviderError

OPENAI_BASE = "https://api.openai.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
MAX_IMPORT = 500
MAX_PAGES = 10


@dataclass
class FetchedModel:
    name: str
    capabilities: list[str] = field(default_factory=lambda: ["text"])


def _is_embedding(name: str) -> bool:
    return "embedding" in name.lower()


def _check(resp: httpx.Response, provider: str) -> None:
    if resp.status_code >= 400:
        raise ProviderError(f"{provider} model list failed: HTTP {resp.status_code}", retriable=resp.status_code >= 500, status=resp.status_code)


async def fetch_models(client: httpx.AsyncClient, provider: str, api_key: str | None, base_url: str | None) -> list[FetchedModel]:
    if provider == "gemini":
        return await _gemini(client, api_key, base_url)
    base = (base_url or (OPENAI_BASE if provider == "openai" else "")).rstrip("/")
    if not base:
        raise ProviderError(f"{provider}: base_url not configured", retriable=False)
    headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await client.get(f"{base}/models", headers=headers)
    _check(resp, provider)
    data = resp.json().get("data") or []
    found = []
    for item in data[:MAX_IMPORT]:
        mid = str(item.get("id", "")).strip()
        if mid:
            found.append(FetchedModel(mid, ["embeddings"] if _is_embedding(mid) else ["text"]))
    return found


async def _gemini(client: httpx.AsyncClient, api_key: str | None, base_url: str | None) -> list[FetchedModel]:
    if not api_key:
        raise ProviderError("gemini: API key not configured", retriable=False)
    base = gemini_api_root(base_url)
    found: list[FetchedModel] = []
    token: str | None = None
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {"pageSize": 200}
        if token:
            params["pageToken"] = token
        resp = await client.get(f"{base}/models", params=params, headers={"x-goog-api-key": api_key})
        _check(resp, "gemini")
        body = resp.json()
        for m in body.get("models") or []:
            methods = set(m.get("supportedGenerationMethods") or [])
            name = str(m.get("name", "")).removeprefix("models/")
            if not name:
                continue
            if "generateContent" in methods:
                found.append(FetchedModel(name, ["text"]))
            elif "embedContent" in methods:
                found.append(FetchedModel(name, ["embeddings"]))
            if len(found) >= MAX_IMPORT:
                return found
        token = body.get("nextPageToken")
        if not token:
            break
    return found
