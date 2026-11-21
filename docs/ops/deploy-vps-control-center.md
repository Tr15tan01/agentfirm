# Deploying AgentFirm with VPS Control Center (no Docker)

AgentFirm runs as **four applications** in VPS Control Center, all from the same GitHub repository. PostgreSQL and
Redis run on the same server. Nothing listens publicly except Nginx (managed by VPS Control Center).

```
Internet ──HTTPS──▶ Nginx (VPS Control Center domain) ──▶ agentfirm-web  127.0.0.1:3200  (Next.js, sign-in cookies)
                                                               │
                                                               ▼
                                                         agentfirm-api   127.0.0.1:8200  (FastAPI)
                                                               │
                         agentfirm-worker (runs agent tasks) ──┤
                                                               ▼
                              PostgreSQL 16 + Redis on 127.0.0.1 (this server)
agentfirm-migrate: runs migrations + publishes agent versions while it builds; holds the only owner password
```

What was verified before this guide was written:
- **Server setup:** `setup-server.sh` was run on Ubuntu 24.04.
- **Install and build:** the API was installed from a clean copy and built with the same build commands as below. The migrations and agent publishing ran on an empty database. The web app was built with its env file.
- **Production mode:** all three services ran in production mode with the env files below, behind the Nginx site file that VPS Control Center itself generates, over HTTPS. Checked through it:
  - sign-up, sign-in and sign-out;
  - API calls and uploads;
  - live task updates;
  - Paddle webhooks;
  - rate limits.
- **Backup:** the control center's PostgreSQL backup command was run against the database.

It has **not** been run inside a real VPS Control Center installation; that first deploy is yours.

---

## 1. Before you start

| You need | Notes |
|---|---|
| VPS Control Center installed on the server | Its own install guide; give the panel its own name, e.g. `panel.example.com` |
| Ubuntu 24.04, **at least 8 GB RAM and 60 GB disk** | The panel, two databases and AgentFirm share the server; every application keeps up to 7 releases on disk |
| The AgentFirm code in a **GitHub** repository | VPS Control Center deploys only from github.com. A private repo is fine (deploy keys, step 4) |
| A DNS **A record** for the app, e.g. `app.example.com` → the server's IP | Cloudflare: **DNS only** (grey cloud). Through the orange-cloud proxy, every visitor would appear to come from Cloudflare's address and share one rate limit |
| Cloudflare R2: bucket `agentfirm-artifacts` + an API token for that bucket only | Agent output files. Required: the API and worker run as different users and can't share a folder |
| Cloudflare R2: a second, empty bucket for backups + its own token | Used by VPS Control Center's backup plan (step 9) |
| API keys for the AI providers you will use (OpenAI, Gemini, GN7T) | Entered later in AgentFirm's admin screen, not in env files |
| Optional: a Brave Search API key | Web search for the Research agent |

## 2. Put the code on GitHub

From the unzipped AgentFirm folder on your computer (the `.gitignore` keeps `.env` files and keys out):

```bash
git init && git add . && git commit -m "AgentFirm"
git branch -M main
git remote add origin git@github.com:YOUR-ORG/agentfirm.git
git push -u origin main
```

## 3. Prepare the server (once)

Copy the zip to the server and run the setup script as root:

```bash
scp agentfirm.zip you@server:/tmp/
ssh you@server
sudo apt-get install -y unzip && cd /tmp && unzip -q agentfirm.zip
sudo bash /tmp/agentfirm/deploy/vcc/setup-server.sh --domain app.example.com
```

The script does the following, and is safe to run again:
- **Installs PostgreSQL 16** with pgvector, listening on 127.0.0.1 only and sized to your RAM, then creates:
  - the `agentfirm` database;
  - `agentfirm_owner`, the schema owner;
  - `agentfirm_app`, a restricted role on which row-level security applies.
- **Installs Redis**, on 127.0.0.1 with a password.
- **Installs Python 3.13** and the PostgreSQL client.
- **Generates every secret** and writes four ready-to-import environment files to `/root/agentfirm-env/`.

**Store `/root/agentfirm-env/secrets.env` in your password manager now.** It holds the master key. Without it,
the AI provider keys and integration secrets saved in AgentFirm can't be decrypted after a restore.

Then edit the API and worker files to add your R2 values (and Brave key, or set `AGENTFIRM_SEARCH_PROVIDER=none`):

```bash
sudo nano /root/agentfirm-env/agentfirm-api.env
sudo nano /root/agentfirm-env/agentfirm-worker.env     # the same R2 / Brave lines
```

## 4. Repository access (private repositories)

In VPS Control Center, each application gets its own read-only deploy key, so you'll add four keys to the
repository. For each application, after creating it in step 5:
1. **Settings › Repository access › Generate deploy key**.
2. On GitHub: repository **Settings › Deploy keys › Add** (read-only).
3. Back in VPS Control Center: **Test access**.

## 5. Create the four applications

**Applications › New** for each. Choose the server, your repository, branch `main`, and tick "use a deploy key"
if the repository is private. Everything else:

| Field | agentfirm-migrate | agentfirm-api | agentfirm-worker | agentfirm-web |
|---|---|---|---|---|
| Type | Python scheduled job | FastAPI | Python worker | Next.js |
| Slug | `agentfirm-migrate` | `agentfirm-api` | `agentfirm-worker` | `agentfirm-web` |
| Runtime | Python 3.13 | Python 3.13 | Python 3.13 | Node.js 22 |
| Working directory | `api` | `api` | `api` | `web` |
| Port | — | `8200` | — | `3200` |
| Build commands (one per line) | `pip install ".[r2]"`<br>`alembic upgrade head`<br>`python -m agentfirm.agents.publishing` | `pip install ".[r2]"` | `pip install ".[r2]"` | `npm ci`<br>`npm run build` |
| Start command | `alembic current` | `uvicorn agentfirm.main:app --host 127.0.0.1 --port {port} --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header --timeout-graceful-shutdown 20` | `python -m agentfirm.worker` | `next start --hostname 127.0.0.1 --port {port}` |
| Health-check path | — | `/readyz` | — | `/login` |
| Schedule | `monthly` (it only prints the schema version; the real work happens in its build) | — | — | — |
| Restart policy | — | always | always | always |
| Memory limit (MB) | empty | `1024` | `1536` | `768` |
| "Runs database migrations" | **ticked** | — | — | — |

Notes:
- **Node.js 22:** install it first under **Servers › the server › Runtimes › Install latest**. Python 3.13 was
  installed by the setup script.
- **Port 8200:** if you choose another API port, re-run the setup script with `--api-port N`, or change
  `AGENTFIRM_API_URL` in the web application's environment.

## 6. Environment variables

For each application, open **Environment › Import** and paste the matching file:

```bash
sudo cat /root/agentfirm-env/agentfirm-migrate.env
sudo cat /root/agentfirm-env/agentfirm-api.env
sudo cat /root/agentfirm-env/agentfirm-worker.env
sudo cat /root/agentfirm-env/agentfirm-web.env
```

VPS Control Center stores them encrypted and treats them as secret by default. The full reference is at the end of this guide.

## 7. Deploy, in this order

1. **agentfirm-migrate.** Its build creates or updates the database schema and publishes the six agents. In the log,
   expect `Running upgrade … -> 0009` the first time, then six `created` lines. A failed migration stops here,
   before anything goes live.
2. **agentfirm-api.** The health check waits for `/readyz`, which reports whether the database and Redis are reachable.
3. **agentfirm-worker**
4. **agentfirm-web.** The build takes about a minute.

For every later update, deploy in the same order. On the Community edition deploys are manual. On Pro, if you turn on
automatic deploys, turn them on for **agentfirm-migrate only** and deploy the others by hand afterwards, so
new code never runs before its migration.

## 8. Domain, first sign-in, super-admin

1. **Domains › Add domain**: `app.example.com`, application **agentfirm-web**, HTTPS on, **Maximum upload size (MB)
   26** (documents are limited to 15 MB by the app; the extra covers upload overhead), www: none.
2. Open `https://app.example.com`, **sign up**: this creates your user and first workspace.
3. Make yourself super-admin. There is deliberately no web page for this. On the server:

   ```bash
   cd /srv/vcc/apps/agentfirm-migrate/current/api
   sudo env "$(sudo grep ^AGENTFIRM_MIGRATIONS_DATABASE_URL= /root/agentfirm-env/agentfirm-migrate.env)" \
        .venv/bin/python -m scripts.create_superadmin you@example.com
   ```
4. Sign out and in again, then go to **Admin › Models**. Add your provider keys and choose a model for each task
   type. Until a key is added, tasks fail with "model unavailable" (they never produce made-up output).

## 9. Backups (VPS Control Center)

1. **Backups › Add destination**: your **backup** R2 bucket, endpoint `https://<account id>.r2.cloudflarestorage.com`,
   region `auto`, and its token. Save the repository password it shows **once** in your password manager.
2. **New plan**:
   - **agentfirm-migrate:** include its environment, and add a **database dump**: PostgreSQL, variable
     `AGENTFIRM_BACKUP_DATABASE_URL`. That variable is in the migrate app's env file and uses the owner role,
     so the dump is complete.
   - **agentfirm-api:** include its environment (it holds the master and token-signing keys).
   - **Schedule:** daily (or more often), with retention to your liking.
3. **Back up now**, then **Test restore**. The plan is only marked *Verified* after a restore test succeeds.

The backups contain your secrets (the environment files). They're encrypted with the repository password, so keep
that password as safe as the keys themselves.

To restore the database from a run, first stop agentfirm-api, agentfirm-worker and agentfirm-web. Then, with the dump
from the run's staging folder:

```bash
DB="$(sudo grep ^AGENTFIRM_BACKUP_DATABASE_URL= /root/agentfirm-env/agentfirm-migrate.env | cut -d= -f2-)"
# The pgvector extension belongs to the database superuser: leave it out, the restore keeps the one in place.
pg_restore -l agentfirm-migrate-postgresql.dump | grep -v " EXTENSION " > /tmp/restore.list
pg_restore --clean --if-exists --no-owner --role=agentfirm_owner -L /tmp/restore.list -d "$DB" agentfirm-migrate-postgresql.dump
psql "$DB" -f /srv/vcc/apps/agentfirm-migrate/current/deploy/backup/verify.sql   # row counts, orphans, RLS policies
```

Start the three applications again. This exact sequence was tested: it restored into an empty database and the row
counts and all 29 row-level security policies matched.

## 10. Monitoring

VPS Control Center already alerts on application failures, restarts, CPU, memory, disk, failed deploys and backups,
and expiring certificates. It probes `/readyz` and `/login` every minute. For AgentFirm-specific alerts (tasks stuck
in the queue, AI providers failing, Paddle webhook errors), you can optionally:
- install Prometheus (`apt install prometheus`);
- point it at `http://127.0.0.1:8200/metrics` with the bearer token `AGENTFIRM_METRICS_TOKEN`;
- load `deploy/observability/alerts.yml`.

## 11. Paddle (when you're ready to charge)

Follow the "Going live with Paddle" checklist in the README. With VPS Control Center the notification destination
is **`https://app.example.com/api/paddle/webhook`**. The web app passes it to the API byte for byte, and the API
verifies Paddle's signature.

Then:
- **agentfirm-api and agentfirm-worker:** set `AGENTFIRM_PADDLE_MODE=live` and add `AGENTFIRM_PADDLE_ENVIRONMENT`,
  `AGENTFIRM_PADDLE_API_KEY` and `AGENTFIRM_PADDLE_WEBHOOK_SECRET`.
- **agentfirm-web:** add `NEXT_PUBLIC_PADDLE_ENV` and `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`.
- **Redeploy** api, worker and web. The web app reads its values at build time.

## 12. Differences from the Docker setup

- **Engineer agent:** its "run the tests" step reports that it's unavailable (`AGENTFIRM_SANDBOX_BACKEND=disabled`).
  Running AI-written code safely needs a container, so it stays off rather than running directly on the server.
- **Admin pages:** there's no IP allowlist for `/admin`, because VPS Control Center's Nginx sites can't carry custom
  rules. The API still checks super-admin rights on every admin call.
- **Migrations** run in agentfirm-migrate's build instead of a separate container. The API, worker and web never hold
  the owner password.

---

## Environment variable reference

`setup-server.sh` fills in everything except the values marked **you**.

### agentfirm-migrate

| Variable | Value | Why |
|---|---|---|
| `AGENTFIRM_ENV` | `production` | |
| `AGENTFIRM_MIGRATIONS_DATABASE_URL` | `postgresql+asyncpg://agentfirm_owner:…@127.0.0.1:5432/agentfirm` | Migrations and agent publishing run as the schema owner |
| `AGENTFIRM_BACKUP_DATABASE_URL` | `postgresql://agentfirm_owner:…@127.0.0.1:5432/agentfirm` | For the backup plan's dump (`pg_dump` needs the plain `postgresql://` form) |

### agentfirm-api

| Variable | Value | Why |
|---|---|---|
| `AGENTFIRM_ENV` | `production` | Refuses to start with simulated models, fixture data or test payments |
| `AGENTFIRM_DATABASE_URL` | `postgresql+asyncpg://agentfirm_app:…@127.0.0.1:5432/agentfirm` | Restricted role: row-level security applies |
| `AGENTFIRM_REDIS_URL` | `redis://:…@127.0.0.1:6379/0` | Rate limits and live-update wake-ups |
| `AGENTFIRM_JWT_PRIVATE_KEY` | Ed25519 key, one line with `\n` | Signs 10-minute access tokens |
| `AGENTFIRM_MASTER_KEY` | 32 random bytes, base64 | Encrypts stored provider keys and integration secrets. **Never lose or change it casually** (see `scripts/rotate_master_key.py`) |
| `AGENTFIRM_CORS_ORIGINS` | `["https://app.example.com"]` | |
| `AGENTFIRM_GATEWAY_MODE` / `_WEB_MODE` / `_CONNECTOR_MODE` | `live` | Real AI providers, web and integrations |
| `AGENTFIRM_SANDBOX_BACKEND` | `disabled` | No Docker for running code |
| `AGENTFIRM_LOG_FORMAT` | `json` | Readable in the Logs tab and journald |
| `AGENTFIRM_METRICS_TOKEN` | random | `/metrics` answers 404 without it |
| `AGENTFIRM_DB_POOL_SIZE` / `_MAX_OVERFLOW` | `10` / `5` | Database connections per process |
| `AGENTFIRM_ARTIFACT_STORE` | `r2` | |
| `AGENTFIRM_R2_ENDPOINT`, `_R2_BUCKET`, `_R2_ACCESS_KEY_ID`, `_R2_SECRET_ACCESS_KEY` | **you** | Agent output files |
| `AGENTFIRM_SEARCH_PROVIDER` / `AGENTFIRM_BRAVE_API_KEY` | `brave` + **you**, or `none` | Research agent's web search |
| `AGENTFIRM_PADDLE_MODE` | `disabled` (later `live`) | Free plan and admin credit grants work without Paddle |
| `AGENTFIRM_PADDLE_CHECKOUT_URL` | `https://app.example.com/billing/checkout` | |
| `AGENTFIRM_PADDLE_ENVIRONMENT`, `_PADDLE_API_KEY`, `_PADDLE_WEBHOOK_SECRET` | **you**, when Paddle goes live | |

### agentfirm-worker

The same as agentfirm-api, **without** `AGENTFIRM_JWT_PRIVATE_KEY`, `AGENTFIRM_CORS_ORIGINS` and
`AGENTFIRM_METRICS_TOKEN` (the worker doesn't need them). It adds:

| Variable | Value | Why |
|---|---|---|
| `AGENTFIRM_WORKER_CONCURRENCY` | `4` | Tasks run at the same time by this worker |

### agentfirm-web (no secrets)

| Variable | Value | Why |
|---|---|---|
| `AGENTFIRM_API_URL` | `http://127.0.0.1:8200` | Where the web app reaches the API |
| `NEXT_PUBLIC_AGENTFIRM_API` | `http` | Live data instead of demo data (read at build time) |
| `NEXT_PUBLIC_AGENTFIRM_AUTH` | `api` | Sign-in through the Python API |
| `NEXT_TELEMETRY_DISABLED` | `1` | |
| `NEXT_PUBLIC_PADDLE_ENV`, `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN` | **you**, when Paddle goes live | Paddle checkout in the browser (redeploy after changing) |

VPS Control Center sets `PORT`, `HOST` and `NODE_ENV=production` itself; don't add them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| migrate build fails at `alembic upgrade head` with "password authentication failed" | The env file doesn't match the database: re-run `setup-server.sh` (it re-applies the passwords from `secrets.env`) and re-import the migrate env |
| migrate build fails: "already published with different content" | An agent manifest changed without a version bump. Bump `version:` in `api/agentfirm/agents/manifests/<agent>.yaml` |
| API health check fails, Logs show `AGENTFIRM_…_MODE must be 'live' in production` | A mode variable is missing or wrong in the API env |
| `/readyz` says `redis: error` | `systemctl status redis-server`; the password in `AGENTFIRM_REDIS_URL` must match `/etc/redis/agentfirm.conf` |
| Web build is killed or fails with "JavaScript heap out of memory" | `next build` needs about 2 GB free: stop other builds, add swap, or check VPS Control Center's build memory setting (`VCC_BUILD_MEMORY_MAX_MB`, unlimited by default) |
| Signed out right after signing in | Use the HTTPS address. Cookies are Secure in production, so plain HTTP doesn't work |
| Everything shows "Demo data" | `NEXT_PUBLIC_AGENTFIRM_API=http` was missing at build time: add it, redeploy the web app |
| Task view doesn't update live | Deploy the current release: it passes Nginx's no-buffering header through (`x-accel-buffering`) |
| Tasks fail "model unavailable" | Add provider keys under Admin › Models |
