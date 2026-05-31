#!/usr/bin/env bash
# Single-command deploy for Clariose (zai.gold).
#
# Sequence:
#   1. backend:  npm ci (if --install) → prisma db push → npm run build
#                (postbuild auto-reloads PM2 clariose-backend)
#   2. frontend: npm ci (if --install) → npm run build
#                (postbuild auto-reloads PM2 clariose-frontend)
#   3. pm2 startOrReload ecosystem.config.cjs --update-env (bootstraps either
#      side if PM2 hadn't registered them yet — covers a fresh box).
#   4. pm2 save (so the process list survives reboots / pm2 resurrect).
#
# Flags:
#   --install     Run `npm ci` (or `npm install` if no lockfile) before building.
#   --backend     Only deploy the backend.
#   --frontend    Only deploy the frontend.
#   --no-migrate  Skip `prisma db push` (use when schema is unchanged).
#
# Daily workflow: just `scripts/deploy.sh` from the repo root.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DO_INSTALL=0
DO_BACKEND=1
DO_FRONTEND=1
DO_MIGRATE=1

for arg in "$@"; do
  case "$arg" in
    --install)    DO_INSTALL=1 ;;
    --backend)    DO_FRONTEND=0 ;;
    --frontend)   DO_BACKEND=0 ;;
    --no-migrate) DO_MIGRATE=0 ;;
    -h|--help)    sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "deploy.sh: unknown flag '$arg'" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }

if ! command -v pm2 >/dev/null 2>&1; then
  echo "deploy.sh: pm2 not on PATH — install with 'npm i -g pm2' first" >&2
  exit 1
fi

# `npm ci` requires a package-lock.json. On a freshly-restructured project
# the first run will fall back to `npm install` to generate the lockfile.
install_deps() {
  if [[ -f package-lock.json ]]; then
    npm ci
  else
    log "no package-lock.json yet → npm install (will generate one)"
    npm install
  fi
}

if [[ $DO_BACKEND -eq 1 ]]; then
  log "backend: cd backend"
  cd "$REPO_ROOT/backend"
  if [[ $DO_INSTALL -eq 1 ]]; then log "backend: install deps"; install_deps; fi
  if [[ $DO_MIGRATE -eq 1 ]]; then
    log "backend: prisma generate"
    npm run prisma:generate --silent
    # This project tracks schema via `prisma db push`, not migrations
    # (no prisma/migrations/ dir). `migrate deploy` would silently no-op
    # and let prod schema drift behind dev.
    log "backend: prisma db push"
    npx prisma db push --skip-generate --accept-data-loss
  fi
  log "backend: npm run build (postbuild reloads PM2)"
  npm run build
fi

if [[ $DO_FRONTEND -eq 1 ]]; then
  log "frontend: cd frontend"
  cd "$REPO_ROOT/frontend"
  if [[ $DO_INSTALL -eq 1 ]]; then log "frontend: install deps"; install_deps; fi
  log "frontend: npm run build (postbuild reloads PM2)"
  npm run build
fi

log "pm2 startOrReload ecosystem.config.cjs --update-env"
cd "$REPO_ROOT"
pm2 startOrReload ecosystem.config.cjs --update-env

log "pm2 save"
pm2 save

log "done."
pm2 list | grep -E 'clariose-|name' || true
