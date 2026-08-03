#!/usr/bin/env bash
# scripts/setup.sh — one-command setup for study-notes (macOS · Apple Silicon).
#
# Idempotent and safe to re-run: it prints its plan, asks ONCE, then installs and
# starts only what's missing, and finishes by running scripts/doctor.sh. It
# installs nothing until you confirm. The one thing it can't bootstrap for you is
# Homebrew itself, and it won't guess your Obsidian vault location.
#
#     ./scripts/setup.sh        # or:  make setup

set -euo pipefail
cd "$(dirname "$0")/.."

say()  { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- Homebrew is the one prerequisite we can't install for you ---
if ! have brew; then
  echo "Homebrew is required but not installed. Install it from https://brew.sh, then re-run this script."
  exit 1
fi

# --- show the plan, confirm once ---
cat <<'PLAN'
study-notes setup will do the following, skipping anything already present:

  1. brew install (as needed): uv, docker, docker-compose (+ colima only if no daemon)
  2. ensure a Docker daemon is up               (Colima or Rancher Desktop; else start Colima)
  3. uv sync --group dev                       (Python app + dev deps)
  4. docker compose up -d                     (Postgres 17 + pgvector)
  5. docker pull jrottenberg/ffmpeg:6.1-alpine (video frame extraction)
  6. uv run playwright install chromium       (webpage ingestion — a few hundred MB)
  7. ensure config.toml's vault_path is a real folder under $HOME
  8. ./scripts/doctor.sh                       (verify everything)

PLAN
printf "Proceed? [y/N] "
read -r reply
case "${reply:-}" in [yY]|[yY][eE][sS]) ;; *) echo "Aborted — nothing was changed."; exit 0 ;; esac

# --- 1. Homebrew packages ---
say "Homebrew packages"
for pkg in uv docker docker-compose; do
  if have "$pkg" || brew list "$pkg" >/dev/null 2>&1; then
    echo "  ok: $pkg"
  else
    echo "  installing $pkg…"; brew install "$pkg"
  fi
done

# --- 2. Docker runtime (any lima-based daemon: Colima or Rancher Desktop) ---
say "Docker runtime"
if docker info >/dev/null 2>&1; then
  echo "  ok: a Docker daemon is already running (context: $(docker context show 2>/dev/null || echo default))"
else
  echo "  no Docker daemon reachable — installing & starting Colima (default runtime)…"
  have colima || brew install colima
  colima start
fi

# --- 3. Python app + dev deps ---
say "Python dependencies"
uv sync --group dev

# --- 4/5. Database + ffmpeg image ---
say "Database + ffmpeg image"
docker compose up -d
if docker image inspect jrottenberg/ffmpeg:6.1-alpine >/dev/null 2>&1; then
  echo "  ok: ffmpeg image present"
else
  echo "  pulling ffmpeg image…"; docker pull jrottenberg/ffmpeg:6.1-alpine
fi

# --- 6. Playwright Chromium (webpage ingestion) ---
say "Playwright Chromium (webpage ingestion)"
uv run playwright install chromium

# --- 7. config.toml vault_path ---
say "Config"
if [ ! -f config.toml ]; then
  echo "  config.toml is missing — see the README 'Configuration' section to create one."
else
  vault="$(sed -nE 's/^[[:space:]]*vault_path[[:space:]]*=[[:space:]]*"?([^"]*)"?.*/\1/p' config.toml | head -1)"
  vault="${vault/#\~/$HOME}"
  if [ -z "$vault" ] || [ "$vault" = "REPLACE_ME" ]; then
    echo "  vault_path is still the REPLACE_ME placeholder — edit config.toml and set it to your"
    echo "  Obsidian vault (an absolute path under \$HOME). Skipping vault creation."
  elif [ -d "$vault" ]; then
    echo "  vault ok: $vault"
  else
    echo "  creating vault folder: $vault"
    mkdir -p "$vault/Notes"
    echo "  (if your Obsidian vault lives elsewhere, edit vault_path in config.toml to point at it.)"
  fi
fi

# --- 8. verify ---
say "Verifying with the doctor"
./scripts/doctor.sh

cat <<'NEXT'

Setup complete. Next:
  - Ingest something:            uv run study-notes add <youtube-url | article-url | file>
  - For a paywalled site, log in once:   uv run study-notes login <site-url>
NEXT
