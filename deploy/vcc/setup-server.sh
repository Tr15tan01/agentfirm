#!/usr/bin/env bash
# One-time server preparation for running AgentFirm under VPS Control Center (no Docker).
#
# Installs and configures, on this Ubuntu 24.04 server:
#   - PostgreSQL 16 (listening on 127.0.0.1 only) + pgvector when available, the agentfirm database,
#     and its roles: agentfirm_owner (schema owner: migrations, backups) and agentfirm_app (API/worker,
#     subject to row-level security)
#   - Redis (127.0.0.1 only, password required)
#   - Python 3.13 (deadsnakes PPA; Ubuntu 24.04 ships 3.12) and the PostgreSQL client for backups
# and generates every secret, then writes ready-to-paste environment files for the four applications
# to /root/agentfirm-env/ (root-only). Safe to re-run: existing secrets, roles and data are kept.
#
# Usage: sudo bash setup-server.sh --domain app.example.com [--api-port 8200]
set -euo pipefail

DOMAIN=""; API_PORT=8200
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:?}"; shift 2 ;;
    --api-port) API_PORT="${2:?}"; shift 2 ;;
    -h|--help) sed -n 2,15p "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$DOMAIN" ] || { echo "--domain is required (the public name of the app, e.g. app.example.com)" >&2; exit 2; }
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "invalid --domain" >&2; exit 2; }
[[ "$API_PORT" =~ ^[0-9]+$ ]] || { echo "invalid --api-port" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)" >&2; exit 2; }
# shellcheck source=/dev/null
. /etc/os-release
[ "${VERSION_ID:-}" = "24.04" ] || echo "warning: tested on Ubuntu 24.04, this is ${PRETTY_NAME:-unknown}" >&2

OUT=/root/agentfirm-env
SECRETS="$OUT/secrets.env"
install -d -m 700 "$OUT"
step() { printf '\n==> %s\n' "$*"; }

step "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -q
apt-get install -y -q software-properties-common openssl gettext-base postgresql-16 postgresql-client-16 redis-server
if ! command -v python3.13 >/dev/null; then
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -y -q
fi
apt-get install -y -q python3.13 python3.13-venv python3.13-dev
PGVECTOR=0
if apt-get install -y -q postgresql-16-pgvector; then PGVECTOR=1; else
  echo "pgvector package not available: knowledge search will use full-text search only" >&2
fi

step "Secrets (kept if they already exist)"
if [ ! -f "$SECRETS" ]; then
  umask 077
  {
    echo "OWNER_PW=$(openssl rand -hex 24)"
    echo "APP_PW=$(openssl rand -hex 24)"
    echo "REDIS_PW=$(openssl rand -hex 24)"
    echo "MASTER_KEY=$(openssl rand -base64 32)"
    echo "METRICS_TOKEN=$(openssl rand -hex 32)"
    # Ed25519 signing key for access tokens, as one line with literal \n (the API turns them back).
    printf "JWT_PEM='%s'\n" "$(openssl genpkey -algorithm ed25519 | awk 'BEGIN{ORS="\\n"} {print}')"
  } > "$SECRETS"
  umask 022
  echo "generated $SECRETS"
else
  echo "keeping $SECRETS"
fi
# shellcheck source=/dev/null
. "$SECRETS"

step "PostgreSQL"
PGCONF=/etc/postgresql/16/main
# Local connections only (Ubuntu's default, enforced here in case it was changed).
sed -i "s/^#\?listen_addresses.*/listen_addresses = 'localhost'/" "$PGCONF/postgresql.conf"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
cat > "$PGCONF/conf.d/50-agentfirm.conf" <<CONF
# Written by AgentFirm setup-server.sh (sized for ${MEM_MB} MB RAM shared with other services).
shared_buffers = $((MEM_MB / 8))MB
effective_cache_size = $((MEM_MB / 3))MB
work_mem = 8MB
maintenance_work_mem = 128MB
max_connections = 100
password_encryption = scram-sha-256
log_min_duration_statement = 500
CONF
systemctl enable --now postgresql
systemctl restart postgresql
psql_su() { runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q "$@"; }
# Passwords go in via psql variables (:'name'), never on a command line other users could read.
psql_su -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" <<'SQL'
SELECT format('CREATE ROLE agentfirm_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L', :'owner_pw')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agentfirm_owner') \gexec
SELECT format('CREATE ROLE agentfirm_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L', :'app_pw')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agentfirm_app') \gexec
SELECT format('ALTER ROLE agentfirm_owner PASSWORD %L', :'owner_pw') \gexec
SELECT format('ALTER ROLE agentfirm_app PASSWORD %L', :'app_pw') \gexec
SELECT 'CREATE DATABASE agentfirm OWNER agentfirm_owner'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'agentfirm') \gexec
SQL
psql_su -d agentfirm -c "ALTER SCHEMA public OWNER TO agentfirm_owner"
if [ "$PGVECTOR" = 1 ]; then psql_su -d agentfirm -c "CREATE EXTENSION IF NOT EXISTS vector"; fi

step "Redis"
REDIS_CONF=/etc/redis/redis.conf
sed -i 's/^bind .*/bind 127.0.0.1 -::1/; s/^#\? *protected-mode .*/protected-mode yes/' "$REDIS_CONF"
grep -q '^include /etc/redis/agentfirm.conf' "$REDIS_CONF" || echo 'include /etc/redis/agentfirm.conf' >> "$REDIS_CONF"
install -m 640 -o redis -g redis /dev/null /etc/redis/agentfirm.conf
printf 'requirepass %s\nmaxmemory 256mb\nmaxmemory-policy volatile-lru\n' "$REDIS_PW" > /etc/redis/agentfirm.conf
systemctl enable --now redis-server
systemctl restart redis-server

step "Checks"
PGPASSWORD="$APP_PW" psql -h 127.0.0.1 -U agentfirm_app -d agentfirm -tAc "select 'postgres ok as ' || current_user"
REDISCLI_AUTH="$REDIS_PW" redis-cli -h 127.0.0.1 ping
python3.13 --version
pg_dump --version

step "Environment files for VPS Control Center"
export DOMAIN API_PORT OWNER_PW APP_PW REDIS_PW MASTER_KEY METRICS_TOKEN JWT_PEM
# shellcheck disable=SC2016  # literal names for envsubst
VARS='${DOMAIN} ${API_PORT} ${OWNER_PW} ${APP_PW} ${REDIS_PW} ${MASTER_KEY} ${METRICS_TOKEN} ${JWT_PEM}'
HERE="$(cd "$(dirname "$0")" && pwd)"
umask 077
for app in migrate api worker web; do
  envsubst "$VARS" < "$HERE/env/$app.env" > "$OUT/agentfirm-$app.env"
done
umask 022
ls -l "$OUT"
cat <<EOF

Done. Next (see docs/ops/deploy-vps-control-center.md):
  1. Fill in the R2 values (and Brave/Paddle when you have them) in $OUT/agentfirm-api.env and agentfirm-worker.env
  2. In VPS Control Center create the four applications and paste each file under Environment > Import:
       sudo cat $OUT/agentfirm-migrate.env    (and -api, -worker, -web)
  3. Deploy in this order: agentfirm-migrate, agentfirm-api, agentfirm-worker, agentfirm-web
Keep a copy of $SECRETS in your password manager: without MASTER_KEY, stored provider keys cannot be decrypted.
EOF
