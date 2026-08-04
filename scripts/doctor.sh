#!/usr/bin/env bash
# scripts/doctor.sh — check the study-notes dev/runtime environment.
#
# READ-ONLY: it reports what is present or missing and the exact command to fix
# each gap. It installs, starts, and changes NOTHING. Run it first on a new
# machine (or when something breaks):
#
#     ./scripts/doctor.sh
#
# Exit code 0 = all required checks pass; 1 = something required is missing.
# Working with Claude Code? It is instructed (see CLAUDE.md) to run this, report
# the gaps, and ASK before installing or starting anything.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

pass=0 fail=0 warn=0

req() { # name | test-cmd | fix-hint   (required — counts as failure if missing)
  if eval "$2" >/dev/null 2>&1; then printf '  [ok]   %s\n' "$1"; pass=$((pass + 1))
  else printf '  [MISS] %s\n           fix: %s\n' "$1" "$3"; fail=$((fail + 1)); fi
}
opt() { # name | test-cmd | fix-hint   (optional — warns, never fails)
  if eval "$2" >/dev/null 2>&1; then printf '  [ok]   %s\n' "$1"; pass=$((pass + 1))
  else printf '  [opt]  %s\n           get: %s\n' "$1" "$3"; warn=$((warn + 1)); fi
}

echo "study-notes — environment check (read-only; nothing is installed or changed)"
echo
echo "Prerequisites"
req "Homebrew"                "command -v brew"    "install from https://brew.sh"
req "uv (Python package manager)" "command -v uv"  "brew install uv"
req "Docker CLI"              "command -v docker"  "brew install docker"
req "Docker daemon (Colima / Rancher Desktop / Docker Desktop)" "docker info" "start your Docker runtime, e.g. 'colima start' or launch Rancher Desktop"

echo
echo "Services (Docker)"
req "Postgres container 'study_notes_db'" "docker ps --format '{{.Names}}' | grep -qx study_notes_db" "docker compose up -d"
req "Postgres accepting connections"      "docker exec study_notes_db pg_isready -U postgres -q"      "docker compose up -d   (then wait ~5s for the healthcheck)"
req "ffmpeg image (frame extraction)"     "docker image inspect jrottenberg/ffmpeg:6.1-alpine"       "docker pull jrottenberg/ffmpeg:6.1-alpine"

echo
echo "Python app"
req "venv + dependencies (import study_notes)" "uv run python -c 'import study_notes'" "uv sync --group dev"

echo
echo "Webpage ingestion"
req "Playwright package"     "uv run python -c 'import playwright'"     "uv sync --group dev"
req "trafilatura package"    "uv run python -c 'import trafilatura'"    "uv pip install -e ."
opt "Playwright Chromium (for webpage ingestion)" "test -d \"$HOME/Library/Caches/ms-playwright\"" "uv run playwright install chromium"

echo
echo "Config"
if [ -f config.toml ]; then
  printf '  [ok]   config.toml present\n'; pass=$((pass + 1))
else
  printf '  [MISS] config.toml present\n           fix: create config.toml at the repo root (see README "Configuration")\n'; fail=$((fail + 1))
fi
vault="$(sed -nE 's/^[[:space:]]*vault_path[[:space:]]*=[[:space:]]*"?([^"]*)"?.*/\1/p' config.toml 2>/dev/null | head -1)"
vault="${vault/#\~/$HOME}"
if [ -z "$vault" ] || [ "$vault" = "REPLACE_ME" ]; then
  printf '  [MISS] vault_path is still the REPLACE_ME placeholder\n'
  printf '           fix: set vault_path in config.toml to your Obsidian vault (absolute, or relative to config.toml; must resolve under $HOME)\n'
  fail=$((fail + 1))
else
  case "$vault" in /*) ;; *) vault="$PWD/$vault" ;; esac  # relative -> resolve against repo root (config.toml lives here)
  if [ -d "$vault" ] && [ "${vault#"$HOME"}" != "$vault" ]; then
    printf '  [ok]   vault_path set, exists, and under $HOME (%s)\n' "$vault"; pass=$((pass + 1))
  else
    printf '  [MISS] vault_path set, exists, and under $HOME\n'
    printf '           fix: set vault_path in config.toml to an existing folder under $HOME\n'
    printf '                (the Docker VM only bind-mounts $HOME); e.g. mkdir -p "$HOME/vault"\n'
    fail=$((fail + 1))
  fi
fi

echo
echo "Optional"
opt "Claude Code CLI"         "command -v claude"  "install Claude Code — https://claude.com/claude-code"

echo
if [ "$fail" -eq 0 ]; then
  echo "All required checks passed (${pass} ok). Try:  uv run study-notes add <youtube-url>"
  echo "Paywalled webpages need a one-time login first:  uv run study-notes login <url>"
  exit 0
else
  echo "${fail} required item(s) missing (${pass} ok). Fix the [MISS] items above."
  echo "Working with Claude Code? It can set these up for you — it will ask first."
  exit 1
fi
