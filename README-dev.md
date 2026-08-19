# Dev setup

## PostgreSQL + pgvector (Docker via a lima-based daemon)

The database runs in a container defined by `docker-compose.yml`
(`pgvector/pgvector:pg17` — Postgres 17 with pgvector preinstalled). Any Docker
daemon that bind-mounts `$HOME` works — **Colima** or **Rancher Desktop** (Docker
Desktop too, with `$HOME` file-sharing enabled). If you have none yet, Colima is
the simplest:

    brew install colima docker docker-compose
    colima start                  # or just launch Rancher Desktop instead
    docker compose up -d          # starts Postgres + pgvector

This creates two databases: `study_notes` (main) and `study_notes_test` (tests,
created by `docker/initdb/01-create-test-db.sql`). Connection URL:

    postgresql://postgres:postgres@localhost:5432/study_notes

Stop / reset:

    docker compose down           # stop
    docker compose down -v        # stop and wipe the data volume

## Tests

    export STUDY_NOTES_TEST_DB="postgresql://postgres:postgres@localhost:5432/study_notes_test"
    uv run pytest -m "not slow and not docker and not e2e and not browser and not network"   # fast, token-free (~3.5s); needs DB container up
    uv run pytest -m docker                # frame tests — needs Docker daemon + jrottenberg/ffmpeg:6.1-alpine
    uv run pytest -m e2e                   # real agentic ingest — slow + spends Claude tokens; ask before running
    uv run pytest -m browser              # Playwright browser tests — run manually
    uv run pytest -m network             # hits live network (YouTube) — run manually; YouTube blocks CI IPs
    uv run pytest -m slow                 # downloads BGE-M3

## ffmpeg (frame extraction) — via Docker

ffmpeg runs in a throwaway container (no host install). Pre-pull the image:

    docker pull jrottenberg/ffmpeg:6.1-alpine

Because the Docker VM (Colima/Rancher Desktop) only mounts your home directory,
frame I/O must live under `$HOME` (the vault frames dir does). Tests that touch ffmpeg are marked
`docker` and use a work dir under the repo.

## Running the tool

    docker compose up -d                      # Postgres
    uv run study-notes reindex                # build the index from your vault
    uv run study-notes add https://youtu.be/<id>
    uv run study-notes add paper.pdf --category "Machine Learning"
    uv run study-notes add https://youtu.be/<id> --dry-run   # preview, no writes
    uv run study-notes add https://youtu.be/<id> --force     # re-ingest

Requires Claude Code installed and authenticated (the run rides that auth).

## Engine

`study-notes add <url>` runs the in-process Agent-SDK orchestrator (no MCP
subprocess). The `[models]` section in `config.toml` sets per-role models:
`orchestrator` (decomposition, judgment, integration), `extractor` (content
extraction), and `enricher` (web research and context enrichment).
