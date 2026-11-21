"""Code execution for the Engineer agent.

* `docker`   — the branch's files are written to a fresh temp directory and the command runs
               in a throwaway container: no network, read-only root, non-root user, all
               capabilities dropped, memory/CPU/PID limits, wall-clock timeout.
* `fixture`  — never executes anything. Returns a scripted result derived from the files
               (counts `def test_` functions) and labels it `fixture`, so the agent reports
               "not a real test run". Tests/evals/dev only; production refuses this backend.
* `disabled` — refuses; the agent reports that it could not verify its change.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from agentfirm.agents.contracts import ErrorCode
from agentfirm.core.config import get_settings

from ..errors import StepError
from . import fixtures as fx

MAX_OUTPUT = 20_000
TEST_FN = re.compile(r"^\s*(?:async\s+)?def (test_\w+)", re.M)


def docker_command(workdir: str, command: str) -> list[str]:
    s = get_settings()
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=256m",  # noqa: S108  # nosec B108 - tmpfs inside the sandbox container, not the host
        "--memory",
        s.sandbox_memory,
        "--cpus",
        s.sandbox_cpus,
        "--pids-limit",
        "256",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10001:10001",
        "-e",
        "HOME=/tmp",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-v",
        f"{workdir}:/workspace:rw",
        "-w",
        "/workspace",
        s.sandbox_image,
        "sh",
        "-lc",
        command,
    ]


def _summarise(output: str, exit_code: int) -> dict[str, Any]:
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", output))
    failed = sum(int(n) for n in re.findall(r"(\d+) failed", output))
    return {"exit_code": exit_code, "passed": passed, "failed": failed, "output": output[-MAX_OUTPUT:]}


def _materialise(root: Path, files: dict[str, str]) -> None:
    base = root.resolve()
    for rel, content in files.items():
        target = (base / rel).resolve()
        if base not in target.parents:
            raise StepError(ErrorCode.POLICY_VIOLATION, f"Refusing to materialise {rel!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    base.chmod(0o777)  # the container runs as an unprivileged uid


async def run(files: dict[str, str], command: str, timeout_s: int) -> dict[str, Any]:
    backend = get_settings().sandbox_backend
    if backend == "disabled":
        raise StepError(ErrorCode.TOOL_ERROR, "Code execution is disabled on this deployment; changes could not be tested.")
    if backend == "fixture":
        script = fx.WORLD.sandbox
        if script.unavailable:
            raise StepError(ErrorCode.TOOL_ERROR, "Sandbox unavailable: no test run was possible.")
        tests = [m for path, c in files.items() if path.startswith("tests/") for m in TEST_FN.findall(c)]
        failed = min(script.fail_tests, len(tests)) if script.fail_tests else 0
        out = f"[fixture sandbox — no code was executed]\n$ {command}\n{len(tests) - failed} passed" + (f", {failed} failed" if failed else "")
        result = _summarise(out, 1 if failed else 0) | {"fixture": True, "failing": tests[:failed]}
        script.runs.append({"command": command, **result})
        return result
    if shutil.which("docker") is None:
        raise StepError(ErrorCode.TOOL_ERROR, "Sandbox unavailable: docker is not installed on this worker.")
    with tempfile.TemporaryDirectory(prefix="af-sandbox-") as tmp:
        await asyncio.to_thread(_materialise, Path(tmp), files)
        proc = await asyncio.create_subprocess_exec(*docker_command(tmp, command), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError as exc:
            proc.kill()
            raise StepError(ErrorCode.TOOL_TIMEOUT, f"Command exceeded {timeout_s}s", retriable=False) from exc
        if proc.returncode == 125:
            raise StepError(ErrorCode.TOOL_ERROR, "Sandbox unavailable: the container could not start.")
        return _summarise(out.decode(errors="replace"), proc.returncode or 0)
