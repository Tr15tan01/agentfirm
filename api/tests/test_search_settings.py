"""Super-admin web-search settings, Brave + Gemini grounding back-ends, and the fallback chain."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import respx

from agentfirm.core.config import get_settings
from agentfirm.runtime.tools import search_providers as sp
from agentfirm.runtime.tools import web
from agentfirm.runtime.tools.web import WebError

from .conftest import register

GEMINI_URL = r"https://generativelanguage\.googleapis\.com/v1beta/models/.*:generateContent"


@pytest.fixture
async def admin(client, owner_db):
    acc = await register(client, org="Platform Ops", name="Root")
    await owner_db.execute("UPDATE users SET is_super_admin = true WHERE id = $1", uuid.UUID(acc.user_id))
    return acc


GROUNDED = {
    "candidates": [
        {
            "content": {"parts": [{"text": "Bitcoin rose 3% today. Ether was flat."}]},
            "groundingMetadata": {
                "groundingChunks": [
                    {"web": {"uri": "https://example.com/btc", "title": "example.com"}},
                    {"web": {"uri": "https://news.example.org/eth", "title": "news.example.org"}},
                    {"web": {"uri": "https://example.com/btc", "title": "dup"}},
                ],
                "groundingSupports": [
                    {"segment": {"text": "Bitcoin rose 3% today."}, "groundingChunkIndices": [0]},
                    {"segment": {"text": "Ether was flat."}, "groundingChunkIndices": [1]},
                ],
            },
        }
    ]
}


@respx.mock
async def test_gemini_grounding_returns_sources_with_their_passages_and_sends_no_sampling():
    route = respx.post(url__regex=GEMINI_URL).respond(200, json=GROUNDED)
    async with httpx.AsyncClient() as c:
        out = await sp.gemini_grounded_search(c, "g-key", "gemini-3.5-flash-lite", "crypto today", 5)
    assert [r["url"] for r in out] == ["https://example.com/btc", "https://news.example.org/eth"], "duplicates dropped"
    assert out[0]["snippet"] == "Bitcoin rose 3% today."
    sent = json.loads(route.calls[0].request.content)
    assert sent["tools"] == [{"google_search": {}}] and "temperature" not in sent["generationConfig"]
    assert route.calls[0].request.headers["x-goog-api-key"] == "g-key"


@respx.mock
async def test_gemini_grounding_without_sources_returns_empty_and_http_errors_raise():
    respx.post(url__regex=GEMINI_URL).respond(200, json={"candidates": [{"content": {"parts": [{"text": "From memory."}]}}]})
    async with httpx.AsyncClient() as c:
        assert await sp.gemini_grounded_search(c, "k", "gemini-3.6-flash", "q", 5) == []
    respx.post(url__regex=GEMINI_URL).respond(403)
    async with httpx.AsyncClient() as c:
        with pytest.raises(WebError, match="403"):
            await sp.gemini_grounded_search(c, "k", "gemini-3.6-flash", "q", 5)


@respx.mock
async def test_brave_parses_results():
    respx.get(sp.BRAVE_URL).respond(200, json={"web": {"results": [{"title": "T", "url": "https://a.example", "description": "<b>hi</b> there"}]}})
    async with httpx.AsyncClient() as c:
        out = await sp.brave_search(c, "b-key", "q", 3)
    assert out == [{"title": "T", "url": "https://a.example", "snippet": "hi there"}]


async def test_search_settings_require_super_admin(client, admin):
    tenant = await register(client, org="Other", name="Tenant")
    assert (await client.get("/v1/admin/search", headers=tenant.h)).status_code in (401, 403, 404)
    assert (await client.put("/v1/admin/search/brave-key", headers=tenant.h, json={"api_key": "x" * 12})).status_code in (401, 403, 404)


async def test_cannot_choose_a_provider_without_its_key_then_can(client, admin):
    r = await client.put("/v1/admin/search", headers=admin.h, json={"provider": "brave", "fallback": "none"})
    assert r.status_code == 422 and "Brave API key" in r.text
    r = await client.put("/v1/admin/search/brave-key", headers=admin.h, json={"api_key": "BSA-secret-key-1234"})
    assert r.status_code == 200
    body = r.json()
    assert body["brave"] == {"configured": True, "last4": "1234", "source": "admin"}
    assert "BSA-secret" not in r.text, "key must never be returned"
    r = await client.put("/v1/admin/search", headers=admin.h, json={"provider": "brave", "fallback": "none"})
    assert r.status_code == 200 and r.json()["provider"] == "brave" and r.json()["using_environment_defaults"] is False
    same = await client.put("/v1/admin/search", headers=admin.h, json={"provider": "brave", "fallback": "brave"})
    assert same.status_code == 422


async def test_gemini_needs_the_gemini_provider_key(client, admin):
    # The test database is shared across the session, so another test may already have saved a Gemini key.
    if not (await client.get("/v1/admin/search", headers=admin.h)).json()["gemini"]["configured"]:
        r = await client.put("/v1/admin/search", headers=admin.h, json={"provider": "gemini", "fallback": "none"})
        assert r.status_code == 422 and "Gemini API key" in r.text
    prov = next(p for p in (await client.get("/v1/admin/providers", headers=admin.h)).json() if p["key"] == "gemini")
    await client.put(f"/v1/admin/providers/{prov['id']}/credential", headers=admin.h, json={"api_key": "AIza-test-key-9876"})
    r = await client.put("/v1/admin/search", headers=admin.h, json={"provider": "gemini", "fallback": "brave", "gemini_model": "gemini-3.6-flash"})
    assert r.status_code == 200, r.text
    assert r.json()["gemini"]["configured"] is True and r.json()["gemini_model"] == "gemini-3.6-flash"


@respx.mock
async def test_test_button_reports_success_and_failure(client, admin):
    await client.put("/v1/admin/search/brave-key", headers=admin.h, json={"api_key": "BSA-secret-key-1234"})
    respx.get(sp.BRAVE_URL).respond(200, json={"web": {"results": [{"title": "One", "url": "https://a.example", "description": "d"}]}})
    ok = (await client.post("/v1/admin/search/test", headers=admin.h, json={"provider": "brave"})).json()
    assert ok["ok"] is True and ok["results"] == 1 and ok["sample"] == ["One"]
    respx.get(sp.BRAVE_URL).respond(401)
    bad = (await client.post("/v1/admin/search/test", headers=admin.h, json={"provider": "brave"})).json()
    assert bad["ok"] is False and "401" in bad["error"]


@respx.mock
async def test_runtime_search_uses_admin_choice_and_falls_back(client, admin):
    # Brave primary (key saved above in this session), Gemini fallback (key saved above).
    await client.put("/v1/admin/search/brave-key", headers=admin.h, json={"api_key": "BSA-secret-key-1234"})
    prov = next(p for p in (await client.get("/v1/admin/providers", headers=admin.h)).json() if p["key"] == "gemini")
    await client.put(f"/v1/admin/providers/{prov['id']}/credential", headers=admin.h, json={"api_key": "AIza-test-key-9876"})
    assert (await client.put("/v1/admin/search", headers=admin.h, json={"provider": "brave", "fallback": "gemini"})).status_code == 200

    s = get_settings()
    s.web_mode = "live"
    try:
        brave = respx.get(sp.BRAVE_URL).respond(429)
        gem = respx.post(url__regex=GEMINI_URL).respond(200, json=GROUNDED)
        out = await web.search("crypto", count=5)
        assert brave.called and gem.called and out[0]["url"] == "https://example.com/btc", "429 from Brave falls through to Gemini"

        gem.respond(500)
        with pytest.raises(WebError) as e:
            await web.search("crypto", count=5)
        assert "429" in str(e.value) and "500" in str(e.value), "both failures reported"

        await client.put("/v1/admin/search", headers=admin.h, json={"provider": "none", "fallback": "none"})
        with pytest.raises(WebError, match="not configured"):
            await web.search("crypto")
    finally:
        s.web_mode = "fixture"
