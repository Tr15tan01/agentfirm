"""Application settings (environment variables prefixed AGENTFIRM_)."""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTFIRM_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://agentfirm_app:app_dev_pw@localhost:5432/agentfirm"
    migrations_database_url: str = "postgresql+asyncpg://agentfirm_owner:owner_dev_pw@localhost:5432/agentfirm"
    redis_url: str | None = None

    jwt_private_key: str | None = None
    jwt_issuer: str = "agentfirm-api"
    jwt_audience: str = "agentfirm"
    access_token_ttl_seconds: int = 600
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14

    master_key: str | None = Field(default=None, description="base64 32-byte key wrapping provider credentials")

    login_max_failures: int = 10
    login_lock_seconds: int = 900
    login_rate_per_minute: int = 10

    cors_origins: list[str] = ["http://localhost:3000"]
    keys_dir: Path = Path(".keys")

    # ── Agent Engine (Phase 4) ───────────────────────────────────────────────
    #: "live" calls real providers with stored credentials. "simulated" resolves the same
    #: routes but answers with a deterministic local simulator (dev, CI, evals without keys).
    #: Simulated output is labelled as such in every model.called event; refused in production.
    gateway_mode: Literal["live", "simulated"] = "simulated"
    simulated_latency_ms: int = 0
    #: "live" uses the configured search provider and real HTTP fetches (SSRF-guarded);
    #: "fixture" serves search/fetch from a local corpus (tests, evals, offline dev).
    web_mode: Literal["live", "fixture"] = "fixture"
    #: "live" uses the organisation's connections (Settings → Integrations); "fixture" serves
    #: GitHub/calendar/ads/email/GN7T/etc. from an in-memory fixture world (tests, evals, dev).
    connector_mode: Literal["live", "fixture"] = "fixture"
    #: Code execution for the Engineer agent: "docker" runs commands in a locked-down container,
    #: "fixture" returns scripted results (never executes anything), "disabled" refuses.
    sandbox_backend: Literal["docker", "fixture", "disabled"] = "fixture"
    sandbox_image: str = "python:3.13-slim"
    sandbox_memory: str = "1g"
    sandbox_cpus: str = "1"
    search_provider: Literal["brave", "none"] = "brave"
    brave_api_key: str | None = None
    fetch_max_bytes: int = 2_000_000
    artifact_store: Literal["local", "r2"] = "local"
    artifacts_dir: Path = Path("var/artifacts")
    r2_endpoint: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    worker_lease_seconds: int = 60
    worker_poll_seconds: float = 2.0
    worker_concurrency: int = 4
    usd_per_credit: float = 0.01
    #: Logs: "json" (one object per line, production) or "text" (local development).
    #: Connection pool per process (API and worker each have one). Postgres max_connections must
    #: cover (pool_size + max_overflow) x processes + the checkpointer pool + admin headroom.
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout: float = 10.0
    log_format: Literal["json", "text"] = "text"
    log_level: str = "INFO"
    #: Bearer token for GET /metrics (Prometheus). Unset → /metrics is not served.
    metrics_token: str | None = None
    #: Worker metrics port (private network only; 0 = off).
    worker_metrics_port: int = 0
    #: Billing provider (Paddle Billing). "live" calls Paddle with the API key below; "fixture"
    #: simulates checkout and webhooks locally (dev/CI/demo; refused in production);
    #: "disabled" turns paid plans and top-ups off (free plan and admin grants still work).
    paddle_mode: Literal["live", "fixture", "disabled"] = "fixture"
    paddle_environment: Literal["sandbox", "production"] = "sandbox"
    paddle_api_key: str | None = None  # server-side API key (never sent to the browser)
    paddle_webhook_secret: str | None = None  # notification destination secret (pdl_ntfset_…)
    #: Approved default payment link page that loads Paddle.js (our /billing/checkout page).
    paddle_checkout_url: str | None = None
    paddle_webhook_tolerance_seconds: int = 300

    def model_post_init(self, __context: object) -> None:
        if self.is_production and self.gateway_mode != "live":
            raise RuntimeError("AGENTFIRM_GATEWAY_MODE must be 'live' in production")
        if self.is_production and self.web_mode != "live":
            raise RuntimeError("AGENTFIRM_WEB_MODE must be 'live' in production")
        if self.is_production and self.connector_mode != "live":
            raise RuntimeError("AGENTFIRM_CONNECTOR_MODE must be 'live' in production")
        if self.is_production and self.sandbox_backend == "fixture":
            raise RuntimeError("AGENTFIRM_SANDBOX_BACKEND must be 'docker' or 'disabled' in production")
        if self.is_production and self.paddle_mode == "fixture":
            raise RuntimeError("AGENTFIRM_PADDLE_MODE must be 'live' or 'disabled' in production")
        if self.paddle_mode == "live" and not (self.paddle_api_key and self.paddle_webhook_secret):
            raise RuntimeError("AGENTFIRM_PADDLE_MODE=live needs AGENTFIRM_PADDLE_API_KEY and AGENTFIRM_PADDLE_WEBHOOK_SECRET")

    @property
    def psycopg_dsn(self) -> str:
        """Same database/role as the API, in libpq form (LangGraph checkpointer uses psycopg)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def resolved_private_key(self) -> str:
        """Ed25519 PEM. In development a key is generated once under keys_dir; production must provide one."""
        if self.jwt_private_key:
            return self.jwt_private_key.replace("\\n", "\n")
        if self.is_production:
            raise RuntimeError("AGENTFIRM_JWT_PRIVATE_KEY is required in production")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        path = self.keys_dir / "jwt_ed25519.pem"
        if not path.exists():
            self.keys_dir.mkdir(parents=True, exist_ok=True)
            pem = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            path.write_bytes(pem)
            os.chmod(path, 0o600)
        return path.read_text()

    def resolved_master_key(self) -> bytes:
        if self.master_key:
            key = base64.b64decode(self.master_key)
        elif self.is_production:
            raise RuntimeError("AGENTFIRM_MASTER_KEY is required in production")
        else:
            path = self.keys_dir / "master.key"
            if not path.exists():
                self.keys_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64encode(os.urandom(32)))
                os.chmod(path, 0o600)
            key = base64.b64decode(path.read_bytes())
        if len(key) != 32:
            raise RuntimeError("Master key must be 32 bytes (base64-encoded)")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
