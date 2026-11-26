"""Web search back-ends. Each returns [{"title", "url", "snippet"}] or raises WebError.

* Brave: the Brave Search API (paid after a small monthly credit).
* Gemini: Google Search grounding through the Gemini API. The model runs the search itself and
  returns the sources it used plus the passages it took from each. These are *grounding* results,
  not a ranked result list: a call may return fewer sources than `count` or none at all.
  Cost is per search query the model performs (free allowance and price: see Google's pricing page).
"""

from __future__ import annotations

from typing import Any

import httpx

from agentfirm.runtime.gateway.adapters import gemini_api_root

from .web import WebError, html_to_text

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
GEMINI_NO_SAMPLING_NOTE = "No temperature is sent: Gemini 3.5+ models reject sampling parameters."


async def brave_search(client: httpx.AsyncClient, api_key: str, query: str, count: int) -> list[dict[str, str]]:
    resp = await client.get(BRAVE_URL, params={"q": query, "count": count}, headers={"X-Subscription-Token": api_key, "Accept": "application/json"})
    if resp.status_code >= 400:
        raise WebError(f"brave search HTTP {resp.status_code}")
    items = (resp.json().get("web") or {}).get("results", [])
    return [{"title": i.get("title", ""), "url": i.get("url", ""), "snippet": html_to_text(i.get("description", ""))[1]} for i in items][:count]


async def gemini_grounded_search(
    client: httpx.AsyncClient, api_key: str, model: str, query: str, count: int, base_url: str | None = None
) -> list[dict[str, str]]:
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": f"Search the web for: {query}\nState the key facts found in short, factual sentences."}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 1024},
    }
    resp = await client.post(f"{gemini_api_root(base_url)}/models/{model}:generateContent", json=body, headers={"x-goog-api-key": api_key})
    if resp.status_code >= 400:
        raise WebError(f"gemini grounding HTTP {resp.status_code}")
    data = resp.json()
    cand = (data.get("candidates") or [{}])[0]
    meta = cand.get("groundingMetadata") or {}
    chunks = meta.get("groundingChunks") or []
    answer = "".join(p.get("text", "") for p in ((cand.get("content") or {}).get("parts") or []))
    passages: dict[int, list[str]] = {}
    for sup in meta.get("groundingSupports") or []:
        text = (sup.get("segment") or {}).get("text", "").strip()
        for idx in sup.get("groundingChunkIndices") or []:
            if text:
                passages.setdefault(idx, []).append(text)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, ch in enumerate(chunks):
        web = ch.get("web") or {}
        url = web.get("uri") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        snippet = " ".join(passages.get(i, []))[:600] or answer[:300]
        results.append({"title": web.get("title") or url, "url": url, "snippet": snippet})
    return results[:count]
