"""GN7T (read-only data), SMTP (approved email) and OSV (dependency advisories).

GN7T contract (ASSUMED until its spec is provided, ADR 0004 / R-1):
    GET  {base_url}/v1/datasets                 → [{"name", "columns": [..]}]
    POST {base_url}/v1/query  {"query", "read_only": true, "max_rows"} → {"columns": [..], "rows": [[..]]}
    Authorization: Bearer <api key>
Read-only is enforced HERE as well (single SELECT/WITH statement, no write keywords), not
only by the flag we send.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, NoReturn

from agentfirm.agents.contracts import ErrorCode

from ..errors import StepError
from . import fixture_mode, http_error, load, request
from . import fixtures as fx

if TYPE_CHECKING:
    from ..context import ExecutionContext

MAX_ROWS = 10_000
WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|merge|upsert|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|vacuum|set|lock|comment|refresh)\b", re.I
)
FROM = re.compile(r"\bfrom\s+\"?([A-Za-z_][A-Za-z0-9_]*)\"?", re.I)


def assert_read_only(query: str) -> str:
    q = re.sub(r"--[^\n]*|/\*.*?\*/", " ", query, flags=re.S).strip().rstrip(";").strip()
    if ";" in q:
        raise StepError(ErrorCode.POLICY_VIOLATION, "Only a single read-only statement is allowed")
    if not re.match(r"^(select|with)\b", q, re.I) or WRITE_WORDS.search(re.sub(r"'[^']*'", "''", q)):
        raise StepError(ErrorCode.POLICY_VIOLATION, "GN7T queries must be read-only SELECT statements")
    return q


def _gn7t_live_unavailable(operation: str) -> NoReturn:
    # GN7T's documented API offers chat completions and model listing only (no query or dataset route).
    # Fail clearly instead of calling a route that does not exist; fixture mode is unaffected.
    raise StepError(ErrorCode.TOOL_ERROR, f"GN7T: live {operation} is not available. GN7T has no query endpoint yet, so BI data access is disabled in live mode.")


async def gn7t_datasets(ctx: ExecutionContext) -> list[dict[str, Any]]:
    if fixture_mode():
        return [{"name": n, "columns": list(rows[0]) if rows else [], "rows": len(rows), "fixture": True} for n, rows in fx.WORLD.datasets.items()]
    _gn7t_live_unavailable("dataset listing")


async def gn7t_query(ctx: ExecutionContext, query: str, max_rows: int) -> dict[str, Any]:
    q = assert_read_only(query)
    max_rows = min(max_rows, MAX_ROWS)
    if fixture_mode():
        m = FROM.search(q)
        name = m.group(1) if m else ""
        if name not in fx.WORLD.datasets:
            raise StepError(ErrorCode.TOOL_ERROR, f"GN7T: unknown dataset {name!r}. Available: {sorted(fx.WORLD.datasets)}")
        rows = fx.WORLD.datasets[name][:max_rows]
        return {"dataset": name, "columns": list(rows[0]) if rows else [], "rows": rows, "row_count": len(rows), "query": q, "fixture": True}
    _gn7t_live_unavailable("queries")


def _send_smtp(cfg: dict[str, Any], password: str, msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], 465, context=context, timeout=30) as smtp:
            smtp.login(cfg["username"], password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
            smtp.starttls(context=context)  # required: we never send credentials in clear text
            smtp.login(cfg["username"], password)
            smtp.send_message(msg)


async def send_email(ctx: ExecutionContext, *, to: list[str], cc: list[str], subject: str, body: str, idempotency_key: str) -> dict[str, Any]:
    if fixture_mode():
        fx.WORLD.sent_emails.append({"to": to, "cc": cc, "subject": subject, "body": body})
        return {"sent": True, "to": to, "fixture": True}
    conn = await load(ctx, "smtp")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = conn.config["from_address"], ", ".join(to), subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Message-ID"] = f"<{idempotency_key.replace(':', '.')}@agentfirm>"
    msg.set_content(body)
    try:
        await asyncio.to_thread(_send_smtp, conn.config, conn.secret or "", msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise StepError(ErrorCode.PERMISSION_DENIED, f"{conn.name}: the mail server rejected the credentials; reconnect it.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise StepError(ErrorCode.TOOL_ERROR, f"{conn.name}: sending failed ({exc.__class__.__name__})", retriable=False) from exc
    return {"sent": True, "to": to, "via": conn.name}


PIN = re.compile(r"^\s*([A-Za-z0-9_.\-\[\]]+)\s*==\s*([A-Za-z0-9_.+\-]+)\s*$")


def parse_manifests(files: dict[str, str]) -> list[tuple[str, str, str]]:
    """(ecosystem, name, version) for exactly pinned dependencies in requirements*.txt / package.json."""
    import json

    out: list[tuple[str, str, str]] = []
    for path, content in files.items():
        base = path.rsplit("/", 1)[-1]
        if base.startswith("requirements") and base.endswith(".txt"):
            for line in content.splitlines():
                if m := PIN.match(line.split("#", 1)[0]):
                    out.append(("PyPI", m.group(1).split("[")[0].lower(), m.group(2)))
        elif base == "package.json":
            try:
                deps = json.loads(content)
            except ValueError:
                continue
            for section in ("dependencies", "devDependencies"):
                for name, ver in (deps.get(section) or {}).items():
                    if re.match(r"^\d+\.\d+\.\d+$", str(ver)):
                        out.append(("npm", name, ver))
    return out[:500]


async def osv_audit(packages: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    if not packages:
        return []
    if fixture_mode():
        found = []
        for eco, name, ver in packages:
            for adv in fx.WORLD.advisories.get(f"{name}=={ver}", []):
                found.append({"package": name, "ecosystem": eco, "version": ver, **adv, "fixture": True})
        return found
    resp = await request(
        "POST",
        "https://api.osv.dev/v1/querybatch",
        name="OSV",
        json={"queries": [{"package": {"name": n, "ecosystem": e}, "version": v} for e, n, v in packages]},
    )
    if resp.status_code >= 300:
        raise http_error("OSV", resp)
    found = []
    for (eco, name, ver), res in zip(packages, resp.json().get("results", []), strict=False):
        for v in res.get("vulns") or []:
            found.append({"package": name, "ecosystem": eco, "version": ver, "id": v["id"], "summary": "", "severity": "unknown", "fixed": None})
    return found
