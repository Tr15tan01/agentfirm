#!/usr/bin/env python3
"""Install AgentFirm on this server under VPS Control Center, in one command.

    sudo python3 install-agentfirm.py --domain agentfirm.example.com

Run it as root on the server where VPS Control Center runs. It:
  1. fetches AgentFirm from GitHub into /root/agentfirm (or updates it)
  2. runs AgentFirm's deploy/vcc/setup-server.sh: PostgreSQL 16, Redis, Python 3.13, generated secrets
  3. asks once for Cloudflare R2 (optional: Enter skips it; add it later with --reconfigure) and an optional
     Brave Search key, and writes them into the generated environment files (kept in
     /root/agentfirm-env/extra.env, root-only, for re-runs)
  4. signs in to VPS Control Center with your account (typed here, used for this run only, never stored)
  5. makes sure Python 3.13 and Node.js 22 are available to builds
  6. creates (or updates) the four applications: agentfirm-migrate, -api, -worker, -web
  7. imports their environment variables (stored encrypted by VPS Control Center)
  8. deploys them in order, migrate -> api -> worker -> web, and stops at the first failure

Afterwards, add the domain to agentfirm-web in the dashboard (Domains tab). Safe to run again: existing
applications are updated, secrets and data are kept, and everything is deployed again.

Options: --repo URL, --branch NAME, --server NAME, --panel-url URL, --skip-setup, --no-deploy, --reconfigure.
Standard library only; works with Ubuntu's python3.
"""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "https://github.com/Tr15tan01/agentfirm"
CHECKOUT = Path("/root/agentfirm")
ENV_DIR = Path("/root/agentfirm-env")
EXTRA = ENV_DIR / "extra.env"
VCC_ENV = Path("/etc/vps-control-center/api.env")
API_PORT, WEB_PORT = 8200, 3200

UVICORN = ("uvicorn agentfirm.main:app --host 127.0.0.1 --port {port} --proxy-headers "
           "--forwarded-allow-ips 127.0.0.1 --no-server-header --timeout-graceful-shutdown 20")
APPS = [  # from AgentFirm's docs/ops/deploy-vps-control-center.md
    {"slug": "agentfirm-migrate", "name": "agentfirm-migrate", "type": "python_job", "env": "migrate",
     "port_mode": "none",
     "config": {"runtime_version": "3.13", "working_dir": "api", "start_command": "alembic current",
                "build_commands": ['pip install ".[r2]"', "alembic upgrade head",
                                   "python -m agentfirm.agents.publishing"],
                "schedule": "monthly", "has_migrations": True}},
    {"slug": "agentfirm-api", "name": "agentfirm-api", "type": "fastapi", "env": "api",
     "port_mode": "manual", "port": API_PORT,
     "config": {"runtime_version": "3.13", "working_dir": "api", "start_command": UVICORN,
                "build_commands": ['pip install ".[r2]"'], "health_check_path": "/readyz",
                "restart_policy": "always", "memory_max_mb": 1024}},
    {"slug": "agentfirm-worker", "name": "agentfirm-worker", "type": "python_worker", "env": "worker",
     "port_mode": "none",
     "config": {"runtime_version": "3.13", "working_dir": "api", "start_command": "python -m agentfirm.worker",
                "build_commands": ['pip install ".[r2]"'], "restart_policy": "always", "memory_max_mb": 1536}},
    {"slug": "agentfirm-web", "name": "agentfirm-web", "type": "nextjs", "env": "web",
     "port_mode": "manual", "port": WEB_PORT,
     "config": {"runtime_version": "22", "working_dir": "web", "package_manager": "npm",
                "start_command": "next start --hostname 127.0.0.1 --port {port}",
                "build_commands": ["npm ci", "npm run build"], "health_check_path": "/login",
                "restart_policy": "always", "memory_max_mb": 768, "nextjs_standalone": False}},
]


# ---- output ----------------------------------------------------------------------------------------------------
def step(msg: str) -> None:
    print(f"\n\033[1;36m==> {msg}\033[0m", flush=True)


def ok(msg: str) -> None:
    print(f"    \033[32mok\033[0m {msg}", flush=True)


def die(msg: str) -> None:
    print(f"\n\033[1;31merror:\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


# ---- VPS Control Center API ----------------------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: object = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


class Panel:
    """Minimal client: cookie session, CSRF double-submit, refresh on 401."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf(self) -> str:
        return next((c.value for c in self.jar if c.name == "vcc_csrf"), "")

    def _raw(self, method: str, path: str, body: object = None) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + "/api/v1" + path, data=data, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("Origin", self.base)
        req.add_header("User-Agent", "install-agentfirm/1.0")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if method not in ("GET", "HEAD"):
            req.add_header("X-CSRF-Token", self._csrf())
        try:
            with self.opener.open(req, timeout=60) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"error": {"code": "http_error", "message": raw[:300].decode(errors="replace")}}
            return exc.code, payload
        except urllib.error.URLError as exc:
            die(f"cannot reach VPS Control Center at {self.base}: {exc.reason}")
            raise

    def call(self, method: str, path: str, body: object = None, *, retry: bool = True) -> object:
        status, payload = self._raw(method, path, body)
        if status == 401 and retry and path != "/auth/refresh":
            rs, _ = self._raw("POST", "/auth/refresh", {})
            if rs < 300:
                return self.call(method, path, body, retry=False)
        if status >= 400:
            err = (payload or {}).get("error") or {} if isinstance(payload, dict) else {}
            raise ApiError(status, err.get("code", str(status)), err.get("message", f"HTTP {status}"),
                           err.get("details"))
        return payload

    def login(self) -> None:
        self.call("GET", "/auth/csrf")
        email = input("    VPS Control Center email: ").strip()
        password = getpass.getpass("    Password (not shown): ")
        try:
            res = self.call("POST", "/auth/login", {"email": email, "password": password})
        except ApiError as exc:
            die(f"sign-in failed: {exc.message}")
        if isinstance(res, dict) and res.get("mfa_required"):
            code = input("    Two-factor code: ").strip().replace(" ", "")
            try:
                self.call("POST", "/auth/mfa/verify", {"ticket": res["mfa_ticket"], "code": code})
            except ApiError as exc:
                die(f"two-factor check failed: {exc.message}")
        me = self.call("GET", "/auth/me")
        ok(f"signed in as {me.get('email')}")  # type: ignore[union-attr]

    def operation(self, server_id: str, op_type: str, params: dict | None = None, timeout: int = 120) -> dict:
        op = self.call("POST", f"/servers/{server_id}/operations", {"type": op_type, "params": params or {}})
        deadline = time.time() + timeout
        while True:
            op = self.call("GET", f"/servers/{server_id}/operations/{op['id']}")  # type: ignore[index]
            if op["status"] not in ("queued", "dispatched", "running", "pending"):  # type: ignore[index]
                return op  # type: ignore[return-value]
            if time.time() > deadline:
                die(f"the agent did not finish '{op_type}' within {timeout} s (is the server online?)")
            time.sleep(2)


# ---- helpers ----------------------------------------------------------------------------------------------------
def env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def set_env_lines(path: Path, values: dict[str, str], drop: tuple[str, ...] = ()) -> None:
    lines, seen = [], set()
    for line in path.read_text().splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
        if key in drop:
            continue
        if key in values:
            lines.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            lines.append(line)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)


def run(cmd: list[str], **kw) -> None:
    print("    $ " + " ".join(cmd), flush=True)
    if subprocess.call(cmd, **kw) != 0:
        die(f"command failed: {' '.join(cmd)}")


R2_KEYS = ("AGENTFIRM_R2_ENDPOINT", "AGENTFIRM_R2_BUCKET", "AGENTFIRM_R2_ACCESS_KEY_ID",
           "AGENTFIRM_R2_SECRET_ACCESS_KEY")


def ask_extra(reconfigure: bool) -> dict[str, str]:
    if EXTRA.exists() and not reconfigure:
        vals = {k: v for k, v in (ln.split("=", 1) for ln in EXTRA.read_text().splitlines() if "=" in ln)}
        ok(f"using the storage and search settings saved in {EXTRA} (change them with --reconfigure)")
        return vals
    print("    AgentFirm keeps uploaded documents and agent output files in a Cloudflare R2 bucket.")
    print("    You can add R2 later: press Enter to skip it now.")
    account = input("    R2 account ID or endpoint URL (Enter = later): ").strip()
    vals: dict[str, str] = {}
    if account:
        endpoint = account if account.startswith("https://") else f"https://{account}.r2.cloudflarestorage.com"
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+/?", endpoint):
            die("that does not look like an R2 account ID or endpoint")
        bucket = input("    Bucket name [agentfirm-artifacts]: ").strip() or "agentfirm-artifacts"
        key_id = input("    Access key ID: ").strip()
        secret = getpass.getpass("    Secret access key (not shown): ").strip()
        if not (key_id and secret):
            die("the R2 access key ID and secret are required (or press Enter at the first question to skip R2)")
        vals.update({"AGENTFIRM_ARTIFACT_STORE": "r2", "AGENTFIRM_R2_ENDPOINT": endpoint.rstrip("/"),
                     "AGENTFIRM_R2_BUCKET": bucket, "AGENTFIRM_R2_ACCESS_KEY_ID": key_id,
                     "AGENTFIRM_R2_SECRET_ACCESS_KEY": secret})
    else:
        vals["AGENTFIRM_ARTIFACT_STORE"] = "local"
        print("    \033[33mWithout R2, file uploads and agent output files won't work yet\033[0m (the API and the")
        print("    worker run as separate users and cannot share a folder). Chats and tasks without files work.")
        print("    Add R2 later with: python3 install-agentfirm.py --domain ... --skip-setup --reconfigure")
    brave = getpass.getpass("    Brave Search API key (optional, Enter to skip; not shown): ").strip()
    vals["AGENTFIRM_SEARCH_PROVIDER"] = "brave" if brave else "none"
    if brave:
        vals["AGENTFIRM_BRAVE_API_KEY"] = brave
    old = os.umask(0o077)
    EXTRA.write_text("".join(f"{k}={v}\n" for k, v in vals.items()))
    os.umask(old)
    ok(f"saved to {EXTRA} (root only) for future runs")
    return vals


def apply_extra(extra: dict[str, str]) -> None:
    """Write the storage and search choices into the API's and the worker's environment files."""
    for name in ("api", "worker"):
        values, drop = dict(extra), []
        if extra.get("AGENTFIRM_ARTIFACT_STORE") == "local":
            # The only folder each application may write to that survives deployments.
            values["AGENTFIRM_ARTIFACTS_DIR"] = f"/srv/vcc/apps/agentfirm-{name}/shared/artifacts"
            drop += R2_KEYS
        else:
            drop.append("AGENTFIRM_ARTIFACTS_DIR")
        if "AGENTFIRM_BRAVE_API_KEY" not in extra:
            drop.append("AGENTFIRM_BRAVE_API_KEY")
        set_env_lines(ENV_DIR / f"agentfirm-{name}.env", values, drop=tuple(drop))


def pick_server(panel: Panel, name: str | None) -> dict:
    servers = [s for s in panel.call("GET", "/servers") if s["status"] != "revoked"]  # type: ignore[union-attr]
    if name:
        match = [s for s in servers if s["name"] == name]
    else:
        host = socket.gethostname()
        match = [s for s in servers if s.get("hostname") in (host, socket.getfqdn())] or \
                (servers if len(servers) == 1 else [])
    if len(match) != 1:
        names = ", ".join(s["name"] for s in servers) or "none"
        die(f"cannot tell which server this is (servers: {names}); pass --server NAME")
    s = match[0]
    if (s.get("agent") or {}).get("state") != "online":
        die(f"server {s['name']} is not online in VPS Control Center")
    ok(f"server {s['name']}")
    return s


def ensure_runtimes(panel: Panel, server: dict) -> None:
    op = panel.operation(server["id"], "system.info")
    if op["status"] != "succeeded":
        die(f"could not refresh the server's information: {op.get('error')}")
    facts = (panel.call("GET", f"/servers/{server['id']}") or {}).get("facts") or {}  # type: ignore[union-attr]
    rv = facts.get("runtime_versions") or {}
    if "3.13" not in (rv.get("python") or []):
        die("Python 3.13 is not visible to VPS Control Center "
            "(setup-server.sh installs it; re-run without --skip-setup)")
    ok("Python 3.13")
    system_node = ((facts.get("runtimes") or {}).get("node") or "").lstrip("v")
    if "22" in (rv.get("node") or {}) or system_node.startswith("22."):
        ok("Node.js 22")
        return
    print("    installing Node.js 22 (downloaded from nodejs.org and checksum-verified by the agent)...", flush=True)
    op = panel.operation(server["id"], "runtime.install", {"kind": "node", "version": "22"}, timeout=900)
    if op["status"] != "succeeded":
        die(f"installing Node.js 22 failed: {(op.get('error') or {}).get('message')}")
    ok("Node.js 22 installed")


def upsert_apps(panel: Panel, server: dict, repo: str, branch: str) -> dict[str, dict]:
    existing = {a["slug"]: a for a in panel.call("GET", f"/applications?server_id={server['id']}")}  # type: ignore[union-attr]
    out = {}
    for spec in APPS:
        cfg = {**spec["config"], "repo_url": repo, "branch": branch}
        app = existing.get(spec["slug"])
        try:
            if app:
                if app["type"] != spec["type"]:
                    die(f"an application '{spec['slug']}' already exists with type {app['type']} "
                        f"(expected {spec['type']}); delete it in the dashboard or rename it, then run again")
                app = panel.call("PATCH", f"/applications/{app['id']}", cfg)
                ok(f"{spec['slug']}: updated")
            else:
                body = {"name": spec["name"], "slug": spec["slug"], "type": spec["type"], "server_id": server["id"],
                        "port_mode": spec["port_mode"], **cfg}
                if spec.get("port"):
                    body["port"] = spec["port"]
                app = panel.call("POST", "/applications", body)
                ok(f"{spec['slug']}: created" + (f" (port {app['port']})" if app.get("port") else ""))  # type: ignore[union-attr]
        except ApiError as exc:
            die(f"{spec['slug']}: {exc.message}" + (f" {json.dumps(exc.details)}" if exc.details else ""))
        out[spec["slug"]] = app  # type: ignore[assignment]
    return out


def import_env(panel: Panel, apps: dict[str, dict]) -> None:
    for spec in APPS:
        path = ENV_DIR / f"agentfirm-{spec['env']}.env"
        if not path.exists():
            die(f"{path} is missing (run without --skip-setup)")
        res = panel.call("POST", f"/applications/{apps[spec['slug']]['id']}/env/import",
                         {"content": path.read_text(), "overwrite": True})
        n = len((res or {}).get("written") or []) if isinstance(res, dict) else 0
        ok(f"{spec['slug']}: {n or 'all'} variables imported (stored encrypted)")


def deploy(panel: Panel, app: dict) -> None:
    try:
        dep = panel.call("POST", f"/applications/{app['id']}/deployments", {})
    except ApiError as exc:
        die(f"{app['slug']}: could not start the deployment: {exc.message}")
    dep_id, after, status, shown = dep["id"], 0, dep["status"], set()  # type: ignore[index]
    print(f"    deployment #{dep['number']} of {app['slug']}", flush=True)  # type: ignore[index]
    while True:
        ev = panel.call("GET", f"/deployments/{dep_id}/events?after={after}")
        for item in ev["items"]:  # type: ignore[index]
            if item.get("stream") == "system" or item.get("level") in ("error", "warning"):
                print(f"      {item.get('message', '')}", flush=True)
                shown.add(item.get("seq"))
        after, status = ev["next_after"], ev["status"]  # type: ignore[index]
        if ev["done"]:  # type: ignore[index]
            break
        time.sleep(2)
    if status != "succeeded":
        tail = [i for i in panel.call("GET", f"/deployments/{dep_id}/events?after={max(0, after - 40)}")["items"]  # type: ignore[index]
                if i.get("seq") not in shown]
        if tail:
            print("    last lines of the build output:")
            for item in tail:
                print(f"      {item.get('message', '')}")
        die(f"{app['slug']} deployment {status} (full log: dashboard > Applications > {app['slug']} > Deployments). "
            "Fix the cause, then run this script again with --skip-setup")
    ok(f"{app['slug']} deployed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--domain", required=True, help="public name of AgentFirm, e.g. agentfirm.example.com")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--server", help="server name in VPS Control Center (default: this machine)")
    ap.add_argument("--panel-url", help="VPS Control Center address (default: from its configuration)")
    ap.add_argument("--skip-setup", action="store_true", help="do not run setup-server.sh again")
    ap.add_argument("--no-deploy", action="store_true", help="create and configure only")
    ap.add_argument("--reconfigure", action="store_true", help="ask again for R2 and the search key")
    a = ap.parse_args()

    if os.geteuid() != 0:
        die("run as root: sudo python3 install-agentfirm.py --domain ...")
    if not re.fullmatch(r"([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", a.domain.lower()):
        die(f"invalid domain: {a.domain}")
    if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+?(\.git)?", a.repo):
        die("--repo must be https://github.com/OWNER/REPO")
    panel_url = a.panel_url or (env_value(VCC_ENV, "VCC_PUBLIC_URL") or "")
    if not panel_url.startswith(("https://", "http://localhost")):
        die("VPS Control Center was not found on this server (pass --panel-url https://...)")

    step(f"AgentFirm source ({a.repo}, {a.branch})")
    if (CHECKOUT / ".git").is_dir():
        run(["git", "-C", str(CHECKOUT), "fetch", "-q", "origin", a.branch])
        run(["git", "-C", str(CHECKOUT), "checkout", "-q", "-B", a.branch, f"origin/{a.branch}"])
    else:
        run(["git", "clone", "-q", "--branch", a.branch, a.repo, str(CHECKOUT)])
    ok(str(CHECKOUT))

    if not a.skip_setup:
        step("Server preparation: PostgreSQL 16, Redis, Python 3.13, secrets (AgentFirm's setup-server.sh)")
        run(["bash", str(CHECKOUT / "deploy/vcc/setup-server.sh"), "--domain", a.domain.lower(),
             "--api-port", str(API_PORT)])
        print(f"\n    \033[33mKeep a copy of {ENV_DIR}/secrets.env in your password manager\033[0m "
              "(AgentFirm's master key).")

    step("File storage (R2) and web search")
    apply_extra(ask_extra(a.reconfigure))
    left = [f.name for f in ENV_DIR.glob("agentfirm-*.env") if "=CHANGE_ME" in f.read_text()]
    if left:
        die(f"placeholder values remain in {', '.join(left)} (look for CHANGE_ME)")
    ok("environment files complete")

    step(f"Signing in to VPS Control Center ({panel_url})")
    panel = Panel(panel_url)
    panel.login()
    server = pick_server(panel, a.server)

    step("Runtimes")
    ensure_runtimes(panel, server)

    step("Applications")
    apps = upsert_apps(panel, server, a.repo, a.branch)

    step("Environment variables")
    import_env(panel, apps)

    if a.no_deploy:
        print("\nConfigured. Deploy from the dashboard in this order: migrate, api, worker, web.")
        return
    for spec in APPS:
        step(f"Deploying {spec['slug']}")
        deploy(panel, apps[spec["slug"]])

    web = apps["agentfirm-web"]
    print(f"""
\033[1;32mAgentFirm is deployed.\033[0m Next:
  1. DNS: an A record for {a.domain} pointing at this server.
  2. Dashboard > Applications > agentfirm-web > Domains > Add domain: {a.domain}
     (HTTPS on, maximum upload size 26 MB).
  3. Open https://{a.domain} and sign up.
  4. Make yourself super-admin (on this server):
       cd /srv/vcc/apps/agentfirm-migrate/current/api && \\
       env "$(grep ^AGENTFIRM_MIGRATIONS_DATABASE_URL= {ENV_DIR}/agentfirm-migrate.env)" \\
         .venv/bin/python -m scripts.create_superadmin YOUR-SIGN-UP-EMAIL
  5. Sign out and in again; Admin > Models: add your AI provider keys.
Updates later: run this script again, or deploy migrate, api, worker, web in that order from the dashboard.
(agentfirm-web: {panel_url}/applications/{web['id']})""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        die("interrupted")
    except ApiError as exc:
        die(f"VPS Control Center answered {exc.status}: {exc.message}")
