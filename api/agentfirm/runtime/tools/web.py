"""Web search and fetching.

* `live`: search via the configured provider (Brave Search API by default — open
  decision, swappable) and fetch with an SSRF-guarded HTTP client.
* `fixture`: a local corpus (tests, evals, offline development).

SSRF guard: only http(s); hostname resolved and EVERY address checked against private,
loopback, link-local, multicast, reserved and cloud-metadata ranges; redirects followed
manually (max 3) with the same check; response size capped; text/HTML/PDF only.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from agentfirm.core.config import get_settings


class WebError(Exception):
    pass


class BlockedURL(WebError):
    pass


@dataclass
class FixtureCorpus:
    """search: query-substring → results; pages: url → text. `default_results` when nothing matches."""

    results: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)
    default_results: list[dict[str, str]] = field(default_factory=list)
    fail_search_times: int = 0
    empty: bool = False

    def search(self, query: str) -> list[dict[str, str]]:
        if self.fail_search_times > 0:
            self.fail_search_times -= 1
            raise WebError("fixture: search timeout")
        if self.empty:
            return []
        q = query.lower()
        for key, res in self.results.items():
            if key.lower() in q:
                return res
        return self.default_results


FIXTURES = FixtureCorpus()


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Anything that is not globally routable: private, loopback, link-local (incl. cloud
    metadata 169.254.169.254), CGNAT, documentation, reserved, multicast, IPv4-mapped/6to4 forms."""
    if isinstance(ip, ipaddress.IPv6Address):
        for embedded in (ip.ipv4_mapped, ip.sixtofour, (ip.teredo or (None, None))[1]):
            if embedded is not None and _blocked_ip(embedded):
                return True
    return not ip.is_global or ip.is_multicast


#: Default DNS resolver (overridable in tests; production always uses getaddrinfo).
RESOLVER = lambda h: socket.getaddrinfo(h, None)  # noqa: E731


async def assert_public_url(url: str, resolver=None) -> None:  # type: ignore[no-untyped-def]
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedURL(f"Only public http(s) URLs are allowed: {url[:120]}")
    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
        addrs = [literal]
    except ValueError:
        resolve = resolver or RESOLVER
        try:
            infos = await asyncio.to_thread(resolve, host)
        except OSError as exc:
            raise WebError(f"DNS resolution failed for {host}") from exc
        addrs = [ipaddress.ip_address(i[4][0]) for i in infos]
    if not addrs or any(_blocked_ip(a) for a in addrs):
        raise BlockedURL(f"Blocked non-public address for {host}")


TAG = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
WS = re.compile(r"\s+")


NON_CONTENT = re.compile(r"<(script|style|title|head|noscript|template|svg)\b[^>]*>.*?</\1\s*>", re.I | re.S)
COMMENT = re.compile(r"<!--.*?-->", re.S)


def html_to_text(raw: str) -> tuple[str, str]:
    """(title, visible text). Script/style/head content and comments are dropped, so hidden
    markup can't masquerade as page text (it still reaches models only as untrusted data)."""
    m = TITLE.search(raw)
    title = html.unescape(m.group(1).strip()) if m else ""
    body = NON_CONTENT.sub(" ", COMMENT.sub(" ", raw))
    return title, WS.sub(" ", html.unescape(TAG.sub(" ", body))).strip()


async def fetch(url: str, *, client: httpx.AsyncClient | None = None, resolver=None) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    s = get_settings()
    if s.web_mode == "fixture":
        if url not in FIXTURES.pages:
            raise WebError(f"fixture: no page for {url}")
        raw = FIXTURES.pages[url]
        title, text = html_to_text(raw) if "<" in raw else ("", raw)  # same processing as live pages
        return {"url": url, "title": title or url, "text": text}
    owns = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(20, connect=5), follow_redirects=False, headers={"user-agent": "AgentFirmBot/0.4 (+https://agentfirm.app/bot)"}
    )
    try:
        current = url
        for _ in range(4):
            await assert_public_url(current, resolver)
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    current = urljoin(current, resp.headers.get("location", ""))
                    continue
                if resp.status_code >= 400:
                    raise WebError(f"HTTP {resp.status_code} for {current[:120]}")
                ctype = resp.headers.get("content-type", "")
                if not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml", "application/pdf")):
                    raise WebError(f"Unsupported content type {ctype[:60]}")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > s.fetch_max_bytes:
                        raise WebError("Response too large")
                if "pdf" in ctype:
                    from .docs import pdf_text

                    return {"url": current, "title": current, "text": pdf_text(bytes(body))}
                title, text = html_to_text(body.decode(resp.encoding or "utf-8", errors="replace"))
                return {"url": current, "title": title or current, "text": text}
        raise WebError("Too many redirects")
    finally:
        if owns:
            await client.aclose()


async def search(query: str, *, count: int = 8, client: httpx.AsyncClient | None = None) -> list[dict[str, str]]:
    s = get_settings()
    if s.web_mode == "fixture":
        return FIXTURES.search(query)[:count]
    if s.search_provider == "none" or not s.brave_api_key:
        raise WebError("Web search is not configured (set AGENTFIRM_BRAVE_API_KEY or choose another provider)")
    owns = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count},
            headers={"X-Subscription-Token": s.brave_api_key, "Accept": "application/json"},
        )
        if resp.status_code >= 400:
            raise WebError(f"search HTTP {resp.status_code}")
        items = (resp.json().get("web") or {}).get("results", [])
        return [{"title": i.get("title", ""), "url": i.get("url", ""), "snippet": html_to_text(i.get("description", ""))[1]} for i in items][:count]
    finally:
        if owns:
            await client.aclose()


NORM = re.compile(r"[^a-z0-9]+")


def contains_excerpt(text: str, excerpt: str) -> bool:
    """Whitespace/punctuation-insensitive containment, used for citation verification."""
    return NORM.sub(" ", excerpt.lower()).strip() in NORM.sub(" ", text.lower())
