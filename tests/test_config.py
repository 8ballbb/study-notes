from pathlib import Path

from study_notes.config import Config, load_config

FIXTURE = Path(__file__).parent / "fixtures" / "config_ok.toml"


def test_load_config_reads_all_fields():
    cfg = load_config(FIXTURE)
    assert isinstance(cfg, Config)
    assert cfg.vault_path == Path("/tmp/vault")
    assert cfg.notes_root == "Notes"
    assert cfg.attachments_dir == "Attachments"
    assert cfg.frames_subdir == "frames"
    assert cfg.database_url == "postgresql://localhost/study_notes_test"
    assert cfg.embedding_model == "BAAI/bge-m3"
    assert cfg.models["orchestrator"] == "claude-opus-4-8"
    assert cfg.prompts["note_writing"] == "prompts/note-writing.md"
    assert cfg.dry_run is False


def test_load_config_missing_file_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.toml"))
