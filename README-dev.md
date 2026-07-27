# Dev setup

## PostgreSQL + pgvector (Docker via Colima)

The database runs in a container defined by `docker-compose.yml`
(`pgvector/pgvector:pg17` — Postgres 17 with pgvector preinstalled). On a Mac
without Docker Desktop, use Colima as the runtime:

    brew install colima docker docker-compose
    colima start
    docker compose up -d          # starts Postgres + pgvector

This creates two databases: `study_notes` (main) and `study_notes_test` (tests,
created by `docker/initdb/01-create-test-db.sql`). Connection URL:

    postgresql://postgres:postgres@localhost:5432/study_notes

Stop / reset:

    docker compose down           # stop
    docker compose down -v        # stop and wipe the data volume

## Tests

    export STUDY_NOTES_TEST_DB="postgresql://postgres:postgres@localhost:5432/study_notes_test"
    uv run pytest -m "not slow and not integration"   # fast unit tests
    uv run pytest -m integration                       # needs the DB container up
    uv run pytest -m slow                               # downloads BGE-M3

## ffmpeg (frame extraction) — via Docker

ffmpeg runs in a throwaway container (no host install). Pre-pull the image:

    docker pull jrottenberg/ffmpeg:6.1-alpine

Because Colima only mounts your home directory, frame I/O must live under
`$HOME` (the vault frames dir does). Tests that touch ffmpeg are marked
`docker` and use a work dir under the repo.

## MCP server (for Claude Code)

Run standalone (stdio):

    STUDY_NOTES_CONFIG=config.toml uv run python -m study_notes.mcp_server

Register with Claude Code via an MCP config JSON (used by Plan 3's orchestrator):

    {
      "mcpServers": {
        "study-notes-tools": {
          "command": "uv",
          "args": ["run", "python", "-m", "study_notes.mcp_server"],
          "env": { "STUDY_NOTES_CONFIG": "config.toml" }
        }
      }
    }
