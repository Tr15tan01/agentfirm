"""Project Engineer agent program (manifest: agents/manifests/engineer.yaml).

Rules enforced in code: writes only to `agent/*` branches; a change is "verified" only if a
real sandbox run passed (fixture runs are labelled and never count as verification); no PR
is proposed while tests fail or were not run; deterministic security checks run alongside
the model review; a deploy needs a passing preflight and an approval of the exact target.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from pydantic import BaseModel, Field

from agentfirm.agents.contracts import AgentResult, ArtifactRef, ErrorCode, HandoffRequest

from ..context import ExecutionContext, untrusted
from ..errors import StepError
from ..gateway import simulated
from .base import approval_state, art_ref, fixture_note, slug, wants

SYSTEM = (
    "You are AgentFirm's Project Engineer. Make the smallest correct change, keep the existing style, "
    "add tests, and never claim something works unless a test run showed it."
)
SECURITY_PATTERNS = [
    (r"(?:api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}['\"]", "high", "Hard-coded credential"),
    (r"\b(?:eval|exec)\(", "high", "Dynamic code execution"),
    (r"verify\s*=\s*False", "high", "TLS verification disabled"),
    (r"(?:execute|query)\(\s*f?['\"].*(?:\{|%s|\+)", "high", "SQL built from strings (injection risk)"),
    (r"==\s*(?:SECRET|secret|signature|token)\b|(?:sig|signature|token)\s*==", "medium", "Secret compared with == (use hmac.compare_digest)"),
    (r"\bpickle\.loads?\(", "medium", "Unpickling untrusted data"),
    (r"subprocess\.\w+\([^)]*shell\s*=\s*True", "medium", "Shell command with shell=True"),
]


class FileChange(BaseModel):
    path: str
    content: str


class Change(BaseModel):
    files: list[FileChange]
    message: str = Field(max_length=300)


class Plan(BaseModel):
    summary: str
    steps: list[str]
    files_to_change: list[str] = Field(default_factory=list)
    tests_to_add: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    needs_research: str | None = None


class Issue(BaseModel):
    severity: str = Field(pattern="^(high|medium|low)$")
    file: str = ""
    issue: str
    recommendation: str = ""


class Review(BaseModel):
    issues: list[Issue] = Field(default_factory=list)
    summary: str = ""


class RootCause(BaseModel):
    cause: str
    evidence: list[str]
    confidence: float = Field(ge=0, le=1)


class Requirements(BaseModel):
    needs: list[str]
    constraints: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Option(BaseModel):
    name: str
    summary: str
    pros: list[str]
    cons: list[str]


class Options(BaseModel):
    options: list[Option]
    recommendation: str


def security_scan(files: dict[str, str]) -> list[dict[str, str]]:
    out = []
    for path, content in files.items():
        for pat, sev, what in SECURITY_PATTERNS:
            for m in re.finditer(pat, content):
                line = content.count("\n", 0, m.start()) + 1
                out.append({"severity": sev, "file": f"{path}:{line}", "issue": what, "recommendation": "", "source": "static check"})
    return out


def _relevant(tree: list[str], text: str, limit: int = 8) -> list[str]:
    words = {w for w in re.findall(r"[a-z]{4,}", text.lower())} | {w[:-1] for w in re.findall(r"[a-z]{5,}s\b", text.lower())}
    scored = sorted(
        ((sum(w in p.lower() for w in words), p) for p in tree if p.endswith((".py", ".ts", ".tsx", ".js", ".txt", ".toml", ".json", ".md"))),
        key=lambda t: (-t[0], t[1]),
    )
    picked = [p for s, p in scored if s > 0][:limit]
    for p in tree:  # always include the tests and dependency manifests next to what we read
        if (p.startswith("tests/") and any(w in p for w in words)) or p.rsplit("/", 1)[-1] in ("requirements.txt", "package.json", "pyproject.toml"):
            if p not in picked:
                picked.append(p)
    return picked[: limit + 4] or tree[:limit]


def _diff(before: dict[str, str], after: dict[str, str]) -> str:
    out = []
    for path in sorted(after):
        out.extend(difflib.unified_diff((before.get(path) or "").splitlines(keepends=True), after[path].splitlines(keepends=True), f"a/{path}", f"b/{path}"))
    return "".join(out)


def _files_block(files: dict[str, str]) -> str:
    return "\n\n".join(untrusted(f"repo:{p}", c, 8000) for p, c in files.items())


def _branch(ctx: ExecutionContext, prefix: str) -> str:
    return f"agent/{prefix}-{slug(ctx.objective, 30)}-{str(ctx.execution_id)[:8]}"


async def _inspect(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    repo = ctx.parameters.get("repository")
    tree_out = await ctx.tool("repo.read", repository=repo) if repo else await ctx.tool("repo.read")
    tree = tree_out["tree"]
    paths = list(ctx.parameters.get("files") or []) or _relevant(tree, ctx.objective)
    files = (await ctx.tool("repo.read", repository=tree_out["repository"], paths=paths))["files"]
    return {"repository": tree_out["repository"], "tree": tree, "files": files}


async def _run_tests(ctx: ExecutionContext, d: dict[str, Any], label: str) -> dict[str, Any]:
    """Run the test suite on the branch. Never raises: an unavailable sandbox is a result."""
    try:
        out = await ctx.tool("sandbox.exec", repository=d["repository"], ref=d.get("branch") or "main", command="python -m pytest -q")
    except StepError as exc:
        await ctx.log("warn", f"{label}: tests could not run — {exc.message}")
        return {"ran": False, "reason": exc.message}
    return {
        "ran": True,
        "fixture": bool(out.get("fixture")),
        "passed": out.get("passed", 0),
        "failed": out.get("failed", 0),
        "exit_code": out.get("exit_code"),
        "output": out.get("output", "")[-4000:],
        "failing": out.get("failing", []),
    }


def _tests_ok(t: dict[str, Any] | None) -> bool:
    return bool(t and t.get("ran") and t.get("exit_code") == 0 and not t.get("failed"))


def _test_md(t: dict[str, Any] | None) -> str:
    if not t:
        return "Tests were not run."
    if not t.get("ran"):
        return f"**Tests were not run** — {t.get('reason')}. The change is unverified."
    head = "**Fixture sandbox — no code was executed; this is not a real test run.**\n\n" if t.get("fixture") else ""
    verdict = "✅ all tests passed" if _tests_ok(t) else f"❌ {t.get('failed')} failing" + (f": {', '.join(t['failing'])}" if t.get("failing") else "")
    return f"{head}{verdict} ({t.get('passed')} passed, exit code {t.get('exit_code')})\n\n```\n{t.get('output', '')[-2000:]}\n```"


async def _write_change(ctx: ExecutionContext, d: dict[str, Any], change: Change, prefix: str) -> dict[str, Any]:
    files = {f.path: f.content for f in change.files}
    branch = d.get("branch") or _branch(ctx, prefix)
    out = await ctx.tool(
        "repo.write_branch", repository=d["repository"], branch=branch, base=ctx.parameters.get("base_branch") or "main", files=files, message=change.message
    )
    before = {p: d.get("files", {}).get(p, "") for p in files}
    return {"branch": branch, "commit": out.get("commit"), "changed": files, "diff": _diff(before, files), "message": change.message}


# ── implement_change ─────────────────────────────────────────────────────────


async def inspect(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    return await _inspect(ctx, d)


async def plan(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    p = await ctx.structured(
        "plan",
        "reasoning",
        Plan,
        system=SYSTEM + " Plan the change. If choosing a library or vendor needs outside evidence, say what in needs_research.",
        user=f"Request: {ctx.objective}\nRepository files:\n{_files_block(d['files'])}",
        sim={"objective": ctx.objective, "files": list(d["files"])},
    )
    handoffs = []
    if p.needs_research:
        h = await ctx.tool(
            "agents.delegate", to_agent="research", objective=p.needs_research[:500], reason="Library/vendor choice needs cited evidence", blocking=False
        )
        handoffs.append(h["handoff"])
    return {"plan": p.model_dump(), "handoffs": handoffs}


async def implement(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    c = await ctx.structured(
        "implement",
        "code",
        Change,
        system=SYSTEM + " Return complete new contents for every file you change, including tests.",
        user=f"Plan: {d['plan']}\nFiles:\n{_files_block(d['files'])}",
        sim={"objective": ctx.objective, "files": d["files"], "plan": d["plan"]},
    )
    return await _write_change(ctx, d, c, "change")


async def test(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    t = await _run_tests(ctx, d, "test")
    return {"tests": t, "fixture:test": bool(t.get("fixture"))}


async def review(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    static = security_scan(d.get("changed", {}))
    r = await ctx.structured(
        "review",
        "reasoning",
        Review,
        system=SYSTEM + " Review this diff for correctness, security and missing tests.",
        user=f"Diff:\n{untrusted('diff', d.get('diff', ''), 20000)}\nTests: {_test_md(d.get('tests'))}",
        sim={"diff": d.get("diff", "")},
    )
    return {"review": {"issues": static + [i.model_dump() | {"source": "model review"} for i in r.issues], "summary": r.summary}}


async def open_pr(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if approval_state(d, "pull_request") != "approved":
        return {"pr": None}
    p = d.get("plan", {})
    body = f"{p.get('summary', '')}\n\n## Test evidence\n{_test_md(d.get('tests'))}\n\n_Opened by AgentFirm after approval._"
    out = await ctx.tool(
        "repo.open_pull_request",
        repository=d["repository"],
        head=d["branch"],
        base=ctx.parameters.get("base_branch") or "main",
        title=d.get("message") or ctx.objective[:100],
        body=body,
    )
    return {"pr": out, "fixture:open_pr": bool(out.get("fixture")) or "github.example" in str(out.get("url"))}


async def report_change(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    p = d.get("plan", {})
    plan_md = (
        f"# Implementation plan\n\n{p.get('summary', '')}\n\n"
        + "\n".join(f"{n}. {s}" for n, s in enumerate(p.get("steps", []), 1))
        + ("\n\n**Risks:** " + "; ".join(p["risks"]) if p.get("risks") else "")
    )
    arts = [art_ref(await ctx.tool("artifact.write", name="implementation_plan.md", content=plan_md, deliverable="implementation_plan"))]
    arts += await _change_artifacts(ctx, d)
    return {"artifacts": arts}


async def _change_artifacts(ctx: ExecutionContext, d: dict[str, Any]) -> list[dict[str, Any]]:
    arts = []
    if d.get("diff"):
        arts.append(art_ref(await ctx.tool("artifact.write", name="code_change.diff", content=d["diff"], deliverable="code_change")))
    tests = d.get("verify") or d.get("tests")
    arts.append(art_ref(await ctx.tool("artifact.write", name="test_report.md", content=f"# Test report\n\n{_test_md(tests)}", deliverable="test_report")))
    return arts


# ── debug ────────────────────────────────────────────────────────────────────


async def reproduce(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    t = await _run_tests(ctx, d, "reproduce")
    return {"baseline_tests": t, "fixture:reproduce": bool(t.get("fixture"))}


async def root_cause(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    rc = await ctx.structured(
        "root_cause",
        "reasoning",
        RootCause,
        system=SYSTEM + " Find the root cause from the code. Cite file and line evidence.",
        user=f"Problem: {ctx.objective}\nBaseline tests: {_test_md(d.get('baseline_tests'))}\nFiles:\n{_files_block(d['files'])}",
        sim={"objective": ctx.objective, "files": d["files"]},
    )
    return {"root_cause": rc.model_dump()}


async def fix(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    c = await ctx.structured(
        "fix",
        "code",
        Change,
        system=SYSTEM + " Fix the root cause and add a regression test. Return full file contents.",
        user=f"Root cause: {d['root_cause']}\nFiles:\n{_files_block(d['files'])}",
        sim={"objective": ctx.objective, "files": d["files"], "plan": {"summary": d["root_cause"]["cause"]}},
    )
    return await _write_change(ctx, d, c, "fix")


async def verify(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    t = await _run_tests(ctx, d, "verify")
    return {"verify": t, "fixture:verify": bool(t.get("fixture"))}


async def report_debug(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    return {"artifacts": await _change_artifacts(ctx, d)}


# ── review ───────────────────────────────────────────────────────────────────


async def read_pr(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    m = re.search(r"```(?:diff)?\n(.+?)```", ctx.objective, re.S)
    if m:
        return {"diff": m.group(1)[:40_000], "repository": None, "manifest_files": {}}
    n = re.search(r"(?:#|pull request |PR )(\d{1,6})", ctx.objective, re.I)
    repo = ctx.parameters.get("repository")
    out = (
        await ctx.tool("repo.read", repository=repo, pull_request=int(n.group(1)) if n else 999_999)
        if repo
        else await ctx.tool("repo.read", pull_request=int(n.group(1)) if n else 999_999)
    )
    pr = out["pull_request"]
    diff = "\n".join(f"--- {f['path']}\n{f['patch']}" for f in pr["files"])
    manifests: dict[str, str] = {}
    tree = (await ctx.tool("repo.read", repository=out["repository"]))["tree"]
    wanted = [p for p in tree if p.rsplit("/", 1)[-1] in ("requirements.txt", "package.json")][:5]
    if wanted:
        manifests = (await ctx.tool("repo.read", repository=out["repository"], paths=wanted))["files"]
    return {"diff": diff[:40_000], "pr_title": pr["title"], "repository": out["repository"], "manifest_files": manifests}


async def audit(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out = await ctx.tool("deps.audit", files=d.get("manifest_files") or {})
    return {"vulnerabilities": out.get("vulnerabilities", []), "fixture:audit": bool(out.get("fixture"))}


async def analyse_review(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    added = "\n".join(line[1:] for line in d.get("diff", "").splitlines() if line.startswith("+") and not line.startswith("+++"))
    static = security_scan({"diff": added})
    r = await ctx.structured(
        "review",
        "reasoning",
        Review,
        system=SYSTEM + " Review the change for security issues first, then correctness. Severity high/medium/low.",
        user=f"Diff:\n{untrusted('diff', d.get('diff', ''), 30000)}",
        sim={"diff": d.get("diff", "")},
    )
    vulns = [
        {
            "severity": v.get("severity", "medium"),
            "file": f"{v['package']}=={v['version']}",
            "issue": f"{v['id']}: {v.get('summary') or 'known vulnerability'}",
            "recommendation": f"upgrade to ≥ {v['fixed']}" if v.get("fixed") else "upgrade",
            "source": "OSV",
        }
        for v in d.get("vulnerabilities", [])
    ]
    return {"review": {"issues": static + vulns + [i.model_dump() | {"source": "model review"} for i in r.issues], "summary": r.summary}}


def _review_md(rv: dict[str, Any]) -> str:
    order = {"high": 0, "medium": 1, "low": 2}
    issues = sorted(rv.get("issues", []), key=lambda i: order.get(i["severity"], 3))
    rows = "\n".join(f"| {i['severity']} | `{i['file']}` | {i['issue']} | {i.get('recommendation', '')} | {i.get('source', '')} |" for i in issues)
    return f"# Review\n\n{rv.get('summary', '')}\n\n| Severity | Where | Issue | Recommendation | Found by |\n|---|---|---|---|---|\n{rows or '| — | — | No issues found | | |'}"


async def report_review(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    md = _review_md(d.get("review", {}))
    return {"review_md": md, "artifacts": [art_ref(await ctx.tool("artifact.write", name="review_report.md", content=md, deliverable="review_report"))]}


# ── design ───────────────────────────────────────────────────────────────────


async def requirements(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    r = await ctx.structured(
        "requirements",
        "classify",
        Requirements,
        system=SYSTEM + " Extract requirements, constraints and open questions.",
        user=ctx.objective,
        sim={"objective": ctx.objective},
    )
    return {"requirements": r.model_dump()}


async def design_context(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out |= await _inspect(ctx, d)
    except StepError as exc:
        await ctx.log("info", f"No repository context: {exc.message}")
    chunks = (await ctx.tool("knowledge.retrieve", query=ctx.objective, top_k=4)).get("chunks", [])
    return out | {"knowledge": [{"title": c["title"], "content": c["content"][:1500]} for c in chunks]}


async def options(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    o = await ctx.structured(
        "options",
        "reasoning",
        Options,
        system=SYSTEM + " Propose 2-3 designs with trade-offs and recommend one.",
        user=f"Requirements: {d.get('requirements')}\nExisting code:\n{_files_block(d.get('files', {}))}",
        sim={"objective": ctx.objective},
    )
    return {"options": o.model_dump()}


async def document(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    doc = await ctx.text(
        "document",
        "text",
        system=SYSTEM + " Write the design document in Markdown: context, requirements, options, decision, consequences, open questions.",
        user=f"Requirements: {d.get('requirements')}\nOptions: {d.get('options')}",
        sim={"objective": ctx.objective, "options": d.get("options")},
    )
    return {"design_md": doc, "artifacts": [art_ref(await ctx.tool("artifact.write", name="design_doc.md", content=doc, deliverable="design_doc"))]}


# ── deploy ───────────────────────────────────────────────────────────────────


def _environment(ctx: ExecutionContext) -> str:
    env = ctx.parameters.get("environment")
    if env in ("preview", "production"):
        return env
    return "production" if wants(ctx.objective, r"\bproduction\b", r"\bprod\b", r"\bship (?:the )?release\b", r"\blive\b") else "preview"


async def preflight(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    m = re.search(r"\bthe ([\w./-]+) branch\b", ctx.objective, re.I)
    ref = ctx.parameters.get("base_branch") or (m.group(1) if m else "main")
    tree = await ctx.tool("repo.read", repository=ctx.parameters.get("repository")) if ctx.parameters.get("repository") else await ctx.tool("repo.read")
    t = await _run_tests(ctx, {"repository": tree["repository"], "branch": ref}, "preflight")
    if not t.get("ran") or not _tests_ok(t):
        raise StepError(ErrorCode.UPSTREAM_DATA_INVALID, f"Preflight failed, so nothing was deployed: {_test_md(t)[:400]}")
    return {"repository": tree["repository"], "deploy_ref": ref, "environment": _environment(ctx), "preflight": t, "fixture:preflight": bool(t.get("fixture"))}


async def deploy(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    if approval_state(d) != "approved":
        return {"deployment": None}
    tool = "deploy.production" if d["environment"] == "production" else "deploy.preview"
    out = await ctx.tool(tool, repository=d["repository"], ref=d["deploy_ref"])
    return {"deployment": out, "fixture:deploy": bool(out.get("fixture"))}


async def smoke(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    dep = d.get("deployment") or {}
    ok = dep.get("status") == "deployed" and bool(dep.get("url"))
    if dep and not ok:
        raise StepError(ErrorCode.UPSTREAM_DATA_INVALID, f"The deploy target didn't confirm the deployment: {str(dep)[:200]}")
    return {"smoke": {"checked": "deployment status and URL reported by the deploy connector", "ok": ok}}


async def report_deploy(ctx: ExecutionContext, d: dict[str, Any]) -> dict[str, Any]:
    dep = d.get("deployment")
    md = (
        f"# Deployment report\n\n- Environment: **{d.get('environment')}**\n- Ref: `{d.get('deploy_ref')}`\n- Preflight: {_test_md(d.get('preflight'))}\n"
        f"- Result: {('deployed to ' + dep['url']) if dep and dep.get('url') else 'not deployed'}"
    )
    return {"deploy_md": md, "artifacts": [art_ref(await ctx.tool("artifact.write", name="deployment_report.md", content=md))]}


# ── Program ──────────────────────────────────────────────────────────────────


class EngineerProgram:
    key = "engineer"
    handlers = {
        "implement_change": {
            "inspect": inspect,
            "plan": plan,
            "implement": implement,
            "test": test,
            "review": review,
            "open_pr": open_pr,
            "report": report_change,
        },
        "debug": {"inspect": inspect, "reproduce": reproduce, "root_cause": root_cause, "fix": fix, "verify": verify, "report": report_debug},
        "review": {"read": read_pr, "audit": audit, "analyse": analyse_review, "report": report_review},
        "design": {"requirements": requirements, "context": design_context, "options": options, "document": document},
        "deploy": {"preflight": preflight, "deploy": deploy, "smoke": smoke, "report": report_deploy},
    }

    def approval_scope(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> list[str] | None:
        if step == "pull_request":
            asked = wants(ctx.objective, r"\bpull request\b", r"\bopen (?:a |the )?PR\b", r"\bPR\b")
            return ["repo.open_pull_request"] if asked and _tests_ok(data.get("tests")) else []
        if step == "approval":  # deploy
            return ["deploy.production" if data.get("environment") == "production" else "deploy.preview"]
        return None

    def approval_facts(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> dict[str, Any]:
        """Facts a standing approval's conditions can check (ADR 0006)."""
        return {"environment": data.get("environment"), "repository": data.get("repository")}

    def approval_preview(self, ctx: ExecutionContext, step: str, data: dict[str, Any]) -> str | None:
        if step == "pull_request":
            return f"Open a pull request in {data.get('repository')} from {data.get('branch')} into main.\n\nTests: {_test_md(data.get('tests')).replace('**', '')}\n\n{data.get('diff', '')[:6000]}"
        if step == "approval":
            return f"Deploy {data.get('deploy_ref')} of {data.get('repository')} to {str(data.get('environment')).upper()}.\n\nPreflight: {_test_md(data.get('preflight')).replace('**', '')[:1500]}"
        return None

    def finalize(self, ctx: ExecutionContext, data: dict[str, Any]) -> AgentResult:
        parts: list[str] = []
        status = "completed"
        tests = data.get("verify") or data.get("tests")
        if data.get("plan") and "diff" in data:
            parts.append(
                f"## Change on `{data.get('branch')}`\n\n{data['plan'].get('summary', '')}\n\nFiles: {', '.join(f'`{p}`' for p in data.get('changed', {}))}"
            )
        if data.get("root_cause"):
            rc = data["root_cause"]
            parts.append(f"## Root cause\n\n{rc['cause']} (confidence {rc['confidence']:.0%})\n\n" + "\n".join(f"- {e}" for e in rc["evidence"]))
            if data.get("diff"):
                parts.append(f"Fix committed to `{data.get('branch')}`.")
        if "diff" in data or data.get("root_cause"):
            parts.append(f"## Tests\n\n{_test_md(tests)}")
            if not _tests_ok(tests):
                status = "partial"  # an unverified or failing change is never reported as done
        if data.get("review"):
            parts.append(data.get("review_md") or _review_md(data["review"]))
        if data.get("design_md"):
            parts.append(data["design_md"])
        if data.get("deploy_md"):
            parts.append(data["deploy_md"])
            if approval_state(data) == "rejected":
                parts.append(f"Deployment was rejected by the approver: {data.get('approval_note:approval') or 'no note'}.")
        pr_state = approval_state(data, "pull_request")
        if data.get("pr"):
            parts.append(f"Pull request opened: {data['pr'].get('url')}")
        elif pr_state == "rejected":
            parts.append(f"The pull request was not opened: the approver rejected it ({data.get('approval_note:pull_request') or 'no note'}).")
        elif pr_state == "not_requested" and wants(ctx.objective, r"\bpull request\b", r"\bPR\b") and not _tests_ok(tests):
            parts.append("I didn't propose a pull request because the tests are not passing.")
        artifacts = [ArtifactRef(id=a["id"], name=a["name"], kind=a["kind"]) for a in data.get("artifacts", [])]
        handoffs = [HandoffRequest(**h) for h in data.get("handoffs", [])]
        return AgentResult(
            execution_id=ctx.execution_id,
            status=status,
            summary="\n\n".join(parts) + fixture_note(data) or "Nothing produced.",
            artifacts=artifacts,
            handoffs=handoffs,
        )


# ── Simulator builders (offline/dev only) ────────────────────────────────────


def _sim_change(objective: str, files: dict[str, str]) -> dict[str, Any]:
    low = objective.lower()
    if "webhook" in low or "charged twice" in low or "double" in low or "duplicate" in low:
        return {
            "message": "Process each webhook event once (idempotency)",
            "files": [
                {
                    "path": "app/webhooks.py",
                    "content": 'def handle_webhook(event: dict, store) -> str:\n    if store.seen(event["id"]):\n        return "duplicate"\n    store.charge(event["customer"], event["amount"])\n    store.mark_seen(event["id"])\n    return "ok"\n',
                },
                {
                    "path": "tests/test_webhooks.py",
                    "content": (files.get("tests/test_webhooks.py", "") + "\n\ndef test_retry_is_not_charged_twice():\n    ...\n"),
                },
            ],
        }
    if "paginat" in low:
        return {
            "message": "Paginate the task list",
            "files": [
                {
                    "path": "app/tasks.py",
                    "content": 'def list_tasks(db, limit: int = 50, cursor: str | None = None):\n    limit = max(1, min(limit, 200))\n    return db.page("tasks", order="created_at DESC", limit=limit, after=cursor)\n',
                },
                {
                    "path": "tests/test_tasks.py",
                    "content": files.get("tests/test_tasks.py", "")
                    + "\n\ndef test_limit_is_capped():\n    ...\n\ndef test_cursor_returns_next_page():\n    ...\n",
                },
            ],
        }
    target = next((p for p in files if p.startswith("app/") and p.endswith(".py") and files[p]), "app/change.py")
    test_path = "tests/test_" + target.rsplit("/", 1)[-1]
    return {
        "message": f"{objective[:80]}",
        "files": [
            {"path": target, "content": files.get(target, "") + "\n# Reviewed and updated by AgentFirm (simulated change)\n"},
            {"path": test_path, "content": files.get(test_path, "") + "\n\ndef test_change_behaviour():\n    ...\n"},
        ],
    }


@simulated.register("engineer.plan")
def _sim_plan(req):  # type: ignore[no-untyped-def]
    o = req.sim_context["objective"]
    research = f"Compare maintained options for: {o}" if re.search(r"\b(best|library|vendor|pick|choose)\b", o, re.I) else None
    return {
        "summary": f"Implement: {o}",
        "steps": ["Read the affected module", "Make the change", "Add tests", "Run the suite"],
        "files_to_change": [p for p in req.sim_context["files"] if p.startswith("app/")][:2],
        "tests_to_add": ["regression test"],
        "risks": ["Behaviour change for existing callers"],
        "needs_research": research,
    }


@simulated.register("engineer.implement")
def _sim_implement(req):  # type: ignore[no-untyped-def]
    return _sim_change(req.sim_context["objective"], req.sim_context["files"])


@simulated.register("engineer.fix")
def _sim_fix(req):  # type: ignore[no-untyped-def]
    return _sim_change(req.sim_context["objective"], req.sim_context["files"])


@simulated.register("engineer.review")
def _sim_review(req):  # type: ignore[no-untyped-def]
    diff = req.sim_context.get("diff", "")
    issues = [{"severity": "low", "file": "", "issue": "Add a test for the error path", "recommendation": "Cover the failure branch"}] if diff else []
    return {"issues": issues, "summary": "Change is small and focused." if diff else "Nothing to review."}


@simulated.register("engineer.root_cause")
def _sim_root(req):  # type: ignore[no-untyped-def]
    files = req.sim_context["files"]
    if "app/webhooks.py" in files:
        return {
            "cause": "handle_webhook charges on every delivery; provider retries are not de-duplicated by event id.",
            "evidence": ["app/webhooks.py:3 charges without checking event id"],
            "confidence": 0.8,
        }
    first = next(iter(files), "unknown")
    return {"cause": f"Behaviour in {first} does not match the reported expectation.", "evidence": [f"{first}: logic reviewed"], "confidence": 0.4}


@simulated.register("engineer.requirements")
def _sim_req(req):  # type: ignore[no-untyped-def]
    return {
        "needs": [req.sim_context["objective"]],
        "constraints": ["Multi-tenant: every row carries org_id with RLS"],
        "open_questions": ["Expected volume per tenant?"],
    }


@simulated.register("engineer.options")
def _sim_options(req):  # type: ignore[no-untyped-def]
    return {
        "options": [
            {
                "name": "Shared tables with org_id + RLS",
                "summary": "One schema; isolation by row-level security.",
                "pros": ["Simple migrations", "Matches platform pattern"],
                "cons": ["Noisy-neighbour risk"],
            },
            {
                "name": "Schema per tenant",
                "summary": "One Postgres schema per organisation.",
                "pros": ["Strong isolation"],
                "cons": ["Migrations multiply", "Connection pooling harder"],
            },
        ],
        "recommendation": "Shared tables with org_id + RLS",
    }


@simulated.register("engineer.document")
def _sim_doc(req):  # type: ignore[no-untyped-def]
    o = req.sim_context.get("options") or {}
    return (
        f"# Design: {req.sim_context['objective']}\n\n## Options\n"
        + "\n".join(f"- **{x['name']}** — {x['summary']}" for x in o.get("options", []))
        + f"\n\n## Decision\n{o.get('recommendation', '')}\n\n## Open questions\n- Expected volume per tenant?"
    )
