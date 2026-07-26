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
