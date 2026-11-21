"""AgentFirm load test (Phase 7). Each simulated user is a workspace owner doing what users do:
browse tasks and agents, open a run, check billing and usage, and now and then start a task
(which the worker really executes, with simulated models).

Run against a production-like stack (one API process, one worker), e.g.:
  AGENTFIRM_LOGIN_RATE_PER_MINUTE=100000 uvicorn agentfirm.main:app --port 8000   # registration burst only
  locust -f deploy/loadtest/locustfile.py --host http://localhost:8000 --headless -u 50 -r 5 -t 3m --csv out
429 from plan concurrency limits is expected behaviour, not an error. Sign-up (Argon2, deliberately
slow) and each user's first task are reported separately: they all happen in the ramp-up burst.
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task

PASSWORD = "Load-test-Pass-9!"  # noqa: S105 - throwaway accounts on a test stack


class Owner(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        r = self.client.post(
            "/v1/auth/register",
            json={"email": f"load.{uuid.uuid4().hex[:12]}@example.com", "name": "Load", "password": PASSWORD, "organization_name": "Load Co"},
            name="POST /v1/auth/register",
        )
        r.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        self.tasks_ids: list[str] = []
        self.start_task(name="POST /v1/tasks (first, during sign-up burst)")

    @task(30)
    def list_tasks(self) -> None:
        r = self.client.get("/v1/tasks", name="GET /v1/tasks")
        if r.ok:
            self.tasks_ids = [t["id"] for t in r.json()[:20]] or self.tasks_ids

    @task(20)
    def open_task(self) -> None:
        if self.tasks_ids:
            self.client.get(f"/v1/tasks/{random.choice(self.tasks_ids)}", name="GET /v1/tasks/{id}")

    @task(10)
    def task_events(self) -> None:
        if self.tasks_ids:
            self.client.get(f"/v1/tasks/{random.choice(self.tasks_ids)}/events", name="GET /v1/tasks/{id}/events")

    @task(10)
    def agents(self) -> None:
        self.client.get("/v1/agents", name="GET /v1/agents")

    @task(10)
    def billing(self) -> None:
        self.client.get("/v1/billing/account", name="GET /v1/billing/account")

    @task(5)
    def usage(self) -> None:
        self.client.get("/v1/usage?range=30d", name="GET /v1/usage")

    @task(5)
    def start_task(self, name: str = "POST /v1/tasks") -> None:
        with self.client.post(
            "/v1/tasks",
            json={"objective": "Brainstorm names for a language-learning app", "agents": ["creative"]},
            name=name,
            catch_response=True,
        ) as r:
            if r.status_code == 429:
                r.success()  # plan concurrency limit doing its job
            elif r.status_code == 201:
                self.tasks_ids.insert(0, r.json()["id"])
