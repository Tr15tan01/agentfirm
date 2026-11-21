#!/usr/bin/env bash
# Zero-surprise deploy on the VPS (run by CI as 'deploy', or by hand):
#   1. pull the new images   2. back up the database   3. run migrations
#   4. roll out web/api/worker   5. wait for health   6. on failure: roll back to the previous tag
# Usage: deploy.sh <image-tag>      Rollback by hand: deploy.sh <previous-tag> --no-migrate
set -euo pipefail
cd "$(dirname "$0")"
NEW="${1:?image tag (git SHA)}"; MIGRATE=1; [ "${2:-}" = "--no-migrate" ] && MIGRATE=0
ENV_FILE=.env.production
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 2; }
PREV="$(cat .current_tag 2>/dev/null || true)"
compose() { IMAGE_TAG="$1" docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml "${@:2}"; }
log() { echo "{\"event\":\"deploy.$1\",\"tag\":\"$NEW\",\"previous\":\"${PREV:-none}\"${2:+,$2}}"; }

# Prometheus reads the metrics token from a file (never on a command line).
set -a
# shellcheck source=/dev/null
. "./$ENV_FILE"
set +a
umask 077; printf '%s' "$AGENTFIRM_METRICS_TOKEN" > observability/metrics_token; umask 022

log start
compose "$NEW" pull --quiet web api worker backup migrate

# Data services first (no-op when already running; needed on the very first deploy).
compose "$NEW" up -d --wait postgres redis

if [ "$MIGRATE" = 1 ]; then
  # Fresh backup first: migrations must be restorable. (Expand/contract: a release's migrations
  # never break the previous release's code, so rolling back the app never needs a down-migration.)
  compose "$NEW" run --rm --no-deps backup /opt/backup/backup.sh
  compose "$NEW" run --rm migrate
  # Publish the agent manifests shipped in this release as immutable versions (idempotent:
  # unchanged versions are skipped; a changed manifest without a version bump fails the deploy).
  compose "$NEW" run --rm migrate python -m agentfirm.agents.publishing
  log migrated
fi

compose "$NEW" up -d --remove-orphans caddy postgres redis prometheus alertmanager node-exporter postgres-exporter grafana
compose "$NEW" up -d --no-deps web api worker backup

healthy() {
  for _ in $(seq 1 30); do
    if compose "$NEW" exec -T api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).status == 200 else 1)" 2>/dev/null \
      && [ "$(docker inspect -f '{{.State.Health.Status}}' "$(compose "$NEW" ps -q web)")" = "healthy" ] \
      && curl -fsS -m 5 "https://${APP_DOMAIN}/healthz" >/dev/null; then
      return 0
    fi
    sleep 4
  done
  return 1
}

if healthy; then
  echo "$NEW" > .current_tag
  [ -n "$PREV" ] && echo "$PREV" > .previous_tag
  docker image prune -f --filter "until=168h" >/dev/null
  log finished
else
  log unhealthy
  if [ -n "$PREV" ]; then
    compose "$PREV" up -d --no-deps web api worker backup
    log rolled_back "\"to\":\"$PREV\""
  fi
  exit 1
fi
