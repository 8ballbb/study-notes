from datetime import date

import pytest
from claude_agent_sdk import ResultMessage

from study_notes import query as qmod
from study_notes.config import Config
from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _index(db_conn):
    return VaultIndex(db_conn, FakeEmbedder(dim=1024))


def _note(path, title, category, content):
    return Note(
        path=path,
        title=title,
        category=category,
        content=content,
        provenance=Provenance(
            origin="u", input_type="youtube", captured_at=date(2026, 7, 18), source_date=None
        ),
    )


def _config(tmp_path):
    qmd = tmp_path / "query.md"
    qmd.write_text("Answer from notes only.")
    return Config(
        vault_path=tmp_path,
        notes_root="Notes",
        attachments_dir="Attachments",
        frames_subdir="frames",
        database_url="unused",
        embedding_model="fake",
        models={"orchestrator": "fake-model"},
        prompts={"query": str(qmd)},
        dry_run=False,
    )


def test_answer_question_grounds_in_retrieved_notes(tmp_path, db_conn, monkeypatch):
    idx = _index(db_conn)
    idx.upsert_category("DS")
    idx.upsert_note(_note("ds/raft.md", "Raft", "DS", "leader election and log replication"))

    seen = {}

    async def fake_query(*, prompt, options):
        seen["prompt"] = prompt
        seen["system"] = options.system_prompt
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result="Raft elects a leader by term voting [[Raft]]",
        )

    monkeypatch.setattr(qmod, "sdk_query", fake_query)

    out = qmod.answer_question(_config(tmp_path), idx, "how does raft pick a leader?")

    assert "Raft" in seen["prompt"]  # retrieved note inlined
    assert "leader election" in seen["prompt"]  # its content inlined
    assert seen["system"] == "Answer from notes only."  # query.md used as system prompt
    assert out == "Raft elects a leader by term voting [[Raft]]"


def test_answer_question_no_hits_returns_message(tmp_path, db_conn, monkeypatch):
    idx = _index(db_conn)  # empty vault

    async def fake_query(*, prompt, options):  # must NOT be called
        raise AssertionError("synthesis should be skipped when there are no hits")
        yield  # pragma: no cover

    monkeypatch.setattr(qmod, "sdk_query", fake_query)

    out = qmod.answer_question(_config(tmp_path), idx, "anything?")
    assert "No matching notes" in out


def test_answer_question_raises_on_synthesis_error(tmp_path, db_conn, monkeypatch):
    idx = _index(db_conn)
    idx.upsert_category("DS")
    idx.upsert_note(_note("ds/raft.md", "Raft", "DS", "leader election"))

    async def fake_query(*, prompt, options):
        yield ResultMessage(
            subtype="error_max_turns",
            duration_ms=1,
            duration_api_ms=1,
            is_error=True,
            num_turns=1,
            session_id="s",
            result="boom",
        )

    monkeypatch.setattr(qmod, "sdk_query", fake_query)
    with pytest.raises(qmod.QueryError):  # error result must not be swallowed
        qmod.answer_question(_config(tmp_path), idx, "how does raft elect?")


def test_answer_question_raises_when_no_result(tmp_path, db_conn, monkeypatch):
    idx = _index(db_conn)
    idx.upsert_category("DS")
    idx.upsert_note(_note("ds/raft.md", "Raft", "DS", "leader election"))

    async def fake_query(*, prompt, options):
        return
        yield  # pragma: no cover  (empty async generator: no ResultMessage)

    monkeypatch.setattr(qmod, "sdk_query", fake_query)
    with pytest.raises(qmod.QueryError):
        qmod.answer_question(_config(tmp_path), idx, "q")
