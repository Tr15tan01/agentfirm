"""GitHub REST connector (fixture-backed in AGENTFIRM_CONNECTOR_MODE=fixture).

Agents may only touch repositories listed on the connection, may only write to branches
named `agent/*`, and never write to the default or a protected branch: checked here, in
code, before any request (the token's own scope is the second line of defence).
"""

from __future__ import annotations

import base64
import re
from typing import TYPE_CHECKING, Any

from agentfirm.agents.contracts import ErrorCode

from ..errors import StepError
from . import fixture_mode, http_error, load, request
from . import fixtures as fx

if TYPE_CHECKING:
    from ..context import ExecutionContext

BRANCH = re.compile(r"^agent/[A-Za-z0-9._/-]{1,100}$")
MAX_FILES = 2000
MAX_FILE_BYTES = 200_000


def _check_branch(branch: str) -> None:
    if not BRANCH.match(branch) or ".." in branch:
        raise StepError(ErrorCode.POLICY_VIOLATION, f"Agents may only write to agent/* branches (got {branch!r})")


def _check_paths(files: dict[str, str]) -> None:
    for p, content in files.items():
        if p.startswith("/") or ".." in p.split("/") or p.startswith(".git/") or p.startswith(".github/workflows/"):
            raise StepError(ErrorCode.POLICY_VIOLATION, f"Refusing to write {p!r} (absolute, traversal, .git or CI workflow path)")
        if len(content.encode()) > MAX_FILE_BYTES:
            raise StepError(ErrorCode.INVALID_INPUT, f"{p} is larger than 200 kB")


class _Live:
    def __init__(self, ctx: ExecutionContext, conn: Any, repository: str) -> None:
        if repository not in conn.config["repositories"]:
            raise StepError(ErrorCode.PERMISSION_DENIED, f"{repository} is not one of the repositories this workspace connected")
        self.repo, self.name = repository, conn.name
        self.base = f"{conn.config['api_base']}/repos/{repository}"
        self.h = {"authorization": f"Bearer {conn.secret}", "accept": "application/vnd.github+json", "x-github-api-version": "2022-11-28"}

    async def _req(self, method: str, path: str, **kw: Any) -> Any:
        resp = await request(method, f"{self.base}{path}", name=self.name, headers=self.h, **kw)
        if resp.status_code >= 300:
            raise http_error(self.name, resp)
        return resp.json() if resp.content else {}

    async def info(self) -> dict[str, Any]:
        return await self._req("GET", "")

    async def tree(self, ref: str) -> list[str]:
        t = await self._req("GET", f"/git/trees/{ref}", params={"recursive": "1"})
        return [e["path"] for e in t.get("tree", []) if e.get("type") == "blob"][:MAX_FILES]

    async def read(self, path: str, ref: str) -> str:
        f = await self._req("GET", f"/contents/{path}", params={"ref": ref})
        if isinstance(f, list) or f.get("encoding") != "base64":
            raise StepError(ErrorCode.INVALID_INPUT, f"{path} is not a file")
        return base64.b64decode(f["content"]).decode("utf-8", errors="replace")

    async def pull(self, number: int) -> dict[str, Any]:
        pr = await self._req("GET", f"/pulls/{number}")
        files = await self._req("GET", f"/pulls/{number}/files", params={"per_page": "100"})
        return {
            "title": pr["title"],
            "body": pr.get("body") or "",
            "head": pr["head"]["ref"],
            "base": pr["base"]["ref"],
            "files": [{"path": f["filename"], "patch": (f.get("patch") or "")[:20_000]} for f in files],
        }

    async def write(self, branch: str, base: str, files: dict[str, str], message: str) -> dict[str, Any]:
        info = await self.info()
        if branch == info.get("default_branch"):
            raise StepError(ErrorCode.POLICY_VIOLATION, "Refusing to write to the default branch")
        try:
            existing = await self._req("GET", f"/branches/{branch}")
            if existing.get("protected"):
                raise StepError(ErrorCode.POLICY_VIOLATION, f"{branch} is protected")
            parent = existing["commit"]["sha"]
            create = False
        except StepError as exc:
            if "404" not in exc.message:
                raise
            parent = (await self._req("GET", f"/git/ref/heads/{base}"))["object"]["sha"]
            create = True
        base_tree = (await self._req("GET", f"/git/commits/{parent}"))["tree"]["sha"]
        tree = [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]
        new_tree = await self._req("POST", "/git/trees", json={"base_tree": base_tree, "tree": tree})
        commit = await self._req("POST", "/git/commits", json={"message": message, "tree": new_tree["sha"], "parents": [parent]})
        if create:
            await self._req("POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        else:
            await self._req("PATCH", f"/git/refs/heads/{branch}", json={"sha": commit["sha"], "force": False})
        return {"branch": branch, "commit": commit["sha"], "files": sorted(files)}

    async def open_pr(self, head: str, base: str, title: str, body: str) -> dict[str, Any]:
        pr = await self._req("POST", "/pulls", json={"head": head, "base": base, "title": title, "body": body, "draft": False})
        return {"number": pr["number"], "url": pr["html_url"]}


class _Fixture:
    def __init__(self, repository: str) -> None:
        if repository != fx.WORLD.repository:
            raise StepError(ErrorCode.PERMISSION_DENIED, f"{repository} is not one of the repositories this workspace connected")
        self.repo = repository

    async def info(self) -> dict[str, Any]:
        return {"default_branch": "main"}

    async def tree(self, ref: str) -> list[str]:
        return sorted(fx.WORLD.branches.get(ref, fx.WORLD.branches["main"]))

    async def read(self, path: str, ref: str) -> str:
        files = fx.WORLD.branches.get(ref, fx.WORLD.branches["main"])
        if path not in files:
            raise StepError(ErrorCode.TOOL_ERROR, f"{path}: not found (404)")
        return files[path]

    async def pull(self, number: int) -> dict[str, Any]:
        if number <= len(fx.WORLD.pull_requests):
            pr = fx.WORLD.pull_requests[number - 1]
            return {**pr, "files": [{"path": p, "patch": f"+{c[:2000]}"} for p, c in pr.get("changes", {}).items()]}
        return {
            "title": "Add webhook signature check",
            "body": "",
            "head": "feature/signatures",
            "base": "main",
            "files": [
                {"path": "app/webhooks.py", "patch": "+    sig = request.headers.get('x-signature')\n+    if sig == SECRET:  # compared with ==\n+        pass"}
            ],
        }

    async def write(self, branch: str, base: str, files: dict[str, str], message: str) -> dict[str, Any]:
        if branch in fx.WORLD.protected:
            raise StepError(ErrorCode.POLICY_VIOLATION, f"{branch} is protected")
        cur = fx.WORLD.branches.setdefault(branch, dict(fx.WORLD.branches.get(base, fx.WORLD.branches["main"])))
        cur.update(files)
        sha = f"f{abs(hash((branch, tuple(sorted(cur.items()))))) % 16**12:012x}"
        return {"branch": branch, "commit": sha, "files": sorted(files)}

    async def open_pr(self, head: str, base: str, title: str, body: str) -> dict[str, Any]:
        base_files = fx.WORLD.branches.get(base, {})
        changes = {p: c for p, c in fx.WORLD.branches.get(head, {}).items() if base_files.get(p) != c}
        fx.WORLD.pull_requests.append({"title": title, "body": body, "head": head, "base": base, "changes": changes})
        n = len(fx.WORLD.pull_requests)
        return {"number": n, "url": f"https://github.example/{self.repo}/pull/{n}"}


async def client(ctx: ExecutionContext, repository: str | None) -> _Live | _Fixture:
    if fixture_mode():
        return _Fixture(repository or fx.WORLD.repository)
    conn = await load(ctx, "github")
    return _Live(ctx, conn, repository or conn.config["default_repository"])


async def default_repository(ctx: ExecutionContext) -> str:
    if fixture_mode():
        return fx.WORLD.repository
    return (await load(ctx, "github")).config["default_repository"]


__all__ = ["BRANCH", "_check_branch", "_check_paths", "client", "default_repository"]
