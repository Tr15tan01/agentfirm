"""Model Gateway adapters, routing fallback/circuit breaker, SSRF guard and tool enforcement."""

from __future__ import annotations

import json
import socket
import uuid
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from agentfirm.runtime.gateway.adapters import ADAPTERS
from agentfirm.runtime.gateway.types import Message, ModelRequest, ModelResponse, ProviderError

from .conftest import register


def req(schema: dict[str, Any] | None = None, temperature: float | None = 0.3) -> ModelRequest:
    return ModelRequest(task="test.echo", messages=[Message("system", "be careful"), Message("user", "hello")], json_schema=schema, temperature=temperature, max_tokens=500)


# ── Adapters (wire format) ───────────────────────────────────────────────────


@respx.mock
async def test_openai_request_shape_and_usage():
    route = respx.post("https://api.openai.com/v1/chat/completions").respond(
        200, json={"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 11, "completion_tokens": 4}}
    )
    async with httpx.AsyncClient() as c:
        resp = await ADAPTERS["openai"].complete(c, req({"type": "object"}), model="gpt-5-mini", api_key="sk-test", base_url=None)
    sent = json.loads(route.calls[0].request.content)
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"
    assert sent["model"] == "gpt-5-mini" and sent["max_completion_tokens"] == 500 and sent["temperature"] == 0.3
    assert sent["response_format"]["type"] == "json_schema" and sent["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert (resp.text, resp.tokens_in, resp.tokens_out) == ('{"ok": true}', 11, 4)


@respx.mock
async def test_openai_retries_without_temperature_when_model_rejects_it():
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature' does not support 0.3"}}),
            httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}], "usage": {}}),
        ]
    )
    async with httpx.AsyncClient() as c:
        resp = await ADAPTERS["openai"].complete(c, req(), model="o-reasoner", api_key="k", base_url=None)
    assert resp.text == "hi"
    assert "temperature" not in json.loads(route.calls[1].request.content)


@respx.mock
async def test_gemini_request_shape():
    route = respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent").respond(
        200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}], "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 2}}
    )
    async with httpx.AsyncClient() as c:
        resp = await ADAPTERS["gemini"].complete(c, req({"type": "object"}), model="gemini-2.5-flash", api_key="g-key", base_url=None)
    r = route.calls[0].request
    sent = json.loads(r.content)
    assert r.headers["x-goog-api-key"] == "g-key" and "key=" not in str(r.url), "key goes in a header, never the URL"
    assert sent["systemInstruction"]["parts"][0]["text"].startswith("be careful")
    assert sent["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert sent["generationConfig"]["responseMimeType"] == "application/json"
    assert (resp.tokens_in, resp.tokens_out) == (7, 2)


@respx.mock
async def test_gemini_safety_block_is_not_retriable():
    respx.post(url__regex=r".*generateContent").respond(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    async with httpx.AsyncClient() as c:
        with pytest.raises(ProviderError) as e:
            await ADAPTERS["gemini"].complete(c, req(), model="m", api_key="k", base_url=None)
    assert not e.value.retriable and "SAFETY" in str(e.value)


@respx.mock
@pytest.mark.parametrize("provider", ["gn7t", "tea800"])
async def test_inhouse_providers_are_openai_compatible_and_need_base_url(provider):
    async with httpx.AsyncClient() as c:
        with pytest.raises(ProviderError, match="base_url"):
            await ADAPTERS[provider].complete(c, req(), model="m", api_key=None, base_url=None)
        route = respx.post("https://llm.internal.example/v1/chat/completions").respond(200, json={"choices": [{"message": {"content": "{}"}}]})
        await ADAPTERS[provider].complete(c, req({"type": "object"}), model="local-70b", api_key=None, base_url="https://llm.internal.example/v1/")
    sent = json.loads(route.calls[0].request.content)
    assert sent["max_tokens"] == 500 and sent["response_format"] == {"type": "json_object"}
    assert "authorization" not in route.calls[0].request.headers
    assert "JSON" in sent["messages"][-1]["content"]


@respx.mock
@pytest.mark.parametrize(("status", "retriable"), [(429, True), (500, True), (503, True), (401, False), (400, False)])
async def test_http_errors_classified(status, retriable):
    respx.post("https://api.openai.com/v1/chat/completions").respond(status, json={"error": {"message": "nope"}})
    async with httpx.AsyncClient() as c:
        with pytest.raises(ProviderError) as e:
            await ADAPTERS["openai"].complete(c, req(temperature=None), model="m", api_key="k", base_url=None)
    assert e.value.retriable is retriable


def test_credit_conversion():
    from agentfirm.runtime.gateway.gateway import credits_for

    assert credits_for(ModelResponse(text="", tokens_in=10, tokens_out=10, cost_usd=Decimal("0.000001"))) == 1
    assert credits_for(ModelResponse(text="", tokens_in=0, tokens_out=0, cost_usd=Decimal("0.0301"))) == 4  # ceil($0.0301 / $0.01)
    assert credits_for(ModelResponse(text="", tokens_in=3000, tokens_out=3000)) == 3  # self-hosted: 1 credit / 2k tokens


# ── Routing: fallback and circuit breaker (simulated mode, real route table) ──


async def test_fallback_to_next_route_and_circuit_breaker(client):
    from agentfirm.runtime.gateway import simulated
    from agentfirm.runtime.gateway.gateway import ModelGateway

    a = await register(client, org="Route Co")
    org = uuid.UUID(a.org_id)
    gw = ModelGateway(retries=0, breaker_threshold=2)
    calls: list[ModelResponse] = []

    async def on_call(resp, capability):  # type: ignore[no-untyped-def]
        calls.append(resp)

    first = await gw.complete(capability="text", request=req(), org_id=org, agent_version_id=None, on_call=on_call)
    assert first.fallback_index == 0 and first.simulated
    simulated.FAILING_PROVIDERS.add(first.provider)
    try:
        for _ in range(2):
            r = await gw.complete(capability="text", request=req(), org_id=org, agent_version_id=None, on_call=on_call)
            assert r.fallback_index >= 1 and r.provider != first.provider
        assert not gw._available(first.provider), "breaker opens after repeated failures"
    finally:
        simulated.FAILING_PROVIDERS.discard(first.provider)
    assert len(calls) == 3, "only successful calls are charged"


# ── SSRF guard ───────────────────────────────────────────────────────────────


def _resolver(*ips: str):  # type: ignore[no-untyped-def]
    return lambda host: [(socket.AF_INET6 if ":" in ip else socket.AF_INET, 0, 0, "", (ip, 0)) for ip in ips]


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "::1", "fd00::1", "::ffff:127.0.0.1", "2002:a00:1::", "224.0.0.1"],
)
async def test_ssrf_blocks_non_public_addresses(ip):
    from agentfirm.runtime.tools.web import BlockedURL, assert_public_url

    with pytest.raises(BlockedURL):
        await assert_public_url("https://innocent.example/", resolver=_resolver(ip))


async def test_ssrf_blocks_if_any_resolved_address_is_private_and_bad_schemes():
    from agentfirm.runtime.tools.web import BlockedURL, assert_public_url

    with pytest.raises(BlockedURL):
        await assert_public_url("https://mixed.example/", resolver=_resolver("93.184.216.34", "10.0.0.1"))
    for url in ("file:///etc/passwd", "gopher://x.example/", "http://[::1]/", "http://2130706433/"):
        with pytest.raises(BlockedURL):
            await assert_public_url(url, resolver=_resolver("127.0.0.1"))
    await assert_public_url("https://example.com/", resolver=_resolver("93.184.216.34"))


@respx.mock
async def test_fetch_refuses_redirect_into_private_network():
    from agentfirm.core.config import get_settings
    from agentfirm.runtime.tools.web import BlockedURL, fetch

    respx.get("https://public.example/start").respond(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    meta = respx.get("http://169.254.169.254/latest/meta-data/").respond(200, text="secret")
    s = get_settings()
    s.web_mode = "live"
    try:
        async with httpx.AsyncClient(follow_redirects=False) as c:
            with pytest.raises(BlockedURL):
                await fetch("https://public.example/start", client=c, resolver=_resolver("93.184.216.34"))
    finally:
        s.web_mode = "fixture"
    assert not meta.called, "the metadata endpoint must never be contacted"


@respx.mock
async def test_fetch_strips_markup_and_caps_size():
    from agentfirm.core.config import get_settings
    from agentfirm.runtime.tools.web import WebError, fetch

    respx.get("https://public.example/page").respond(
        200, headers={"content-type": "text/html"}, text="<html><head><title>T</title><script>evil()</script></head><body><!-- hidden --><p>Visible &amp; text</p></body></html>"
    )
    respx.get("https://public.example/huge").respond(200, headers={"content-type": "text/html"}, content=b"x" * 50_000)
    respx.get("https://public.example/bin").respond(200, headers={"content-type": "application/octet-stream"}, content=b"\x00")
    s = get_settings()
    s.web_mode, cap = "live", s.fetch_max_bytes
    s.fetch_max_bytes = 10_000
    try:
        async with httpx.AsyncClient() as c:
            page = await fetch("https://public.example/page", client=c, resolver=_resolver("93.184.216.34"))
            assert (page["title"], page["text"]) == ("T", "Visible & text")
            assert "evil" not in page["text"] and "hidden" not in page["text"]
            for path in ("huge", "bin"):
                with pytest.raises(WebError):
                    await fetch(f"https://public.example/{path}", client=c, resolver=_resolver("93.184.216.34"))
    finally:
        s.web_mode, s.fetch_max_bytes = "fixture", cap


# ── Tool enforcement (checks that run before any side effect) ────────────────


def _ctx(agent: str, perms: set[str], step_tools: frozenset[str] | None, approved: set[str] | None = None):  # type: ignore[no-untyped-def]
    from agentfirm.agents.registry import registry
    from agentfirm.runtime.context import ExecutionContext

    async def emit(*_a, **_k):  # type: ignore[no-untyped-def]
        return 0

    ctx = ExecutionContext(
        org_id=uuid.uuid4(), task_id=uuid.uuid4(), execution_id=uuid.uuid4(), requested_by=uuid.uuid4(), agent_version_id=uuid.uuid4(),
        manifest=registry().agents[agent], registry=registry(), permissions=frozenset(perms), budget_credits=10, credits_used=0,
        gateway=None, sink=SimpleNamespace(emit=emit), objective="x", approved_tools=approved or set(),  # type: ignore[arg-type]
    )
    ctx.enter_step("s", step_tools)
    return ctx


async def test_tool_enforcement_order():
    from agentfirm.runtime.errors import StepError
    from agentfirm.runtime.tools.runtime import invoke

    all_perms = {"agents:use", "tasks:create", "tasks:control", "knowledge:manage", "approvals:decide", "billing:manage", "workspace:read"}
    cases = [
        (_ctx("creative", all_perms, None), "social.publish", "not granted"),
        (_ctx("creative", all_perms, frozenset({"ideas.board_read"})), "artifact.write", "does not declare"),
        (_ctx("marketing", all_perms, frozenset({"social.publish"})), "social.publish", "requires an approved approval"),
        (_ctx("creative", {"workspace:read"}, frozenset({"ideas.board_write"})), "ideas.board_write", "lacks"),
    ]
    for ctx, key, msg in cases:
        with pytest.raises(StepError, match=msg):
            await invoke(ctx, key, {})

    over = _ctx("creative", all_perms, frozenset({"ideas.board_read"}))
    over.tool_counts = defaultdict(int, {"ideas.board_read": 10})
    with pytest.raises(StepError, match="Call cap"):
        await invoke(over, "ideas.board_read", {})
    broke = _ctx("creative", all_perms, frozenset({"ideas.board_read"}))
    broke.credits_used = 10
    with pytest.raises(StepError, match="budget"):
        await invoke(broke, "ideas.board_read", {})


async def test_parallel_steps_keep_separate_step_scope():
    import asyncio

    ctx = _ctx("research", set(), None)

    async def node(name: str) -> tuple[str, str]:
        ctx.enter_step(name, frozenset({name}))
        await asyncio.sleep(0.01)
        return name, ctx.current_step

    results = await asyncio.gather(*(asyncio.create_task(node(n)) for n in ("retrieve_web", "retrieve_internal")))
    assert all(a == b for a, b in results)
