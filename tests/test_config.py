from pathlib import Path

import pytest

from study_notes.config import Config, ConfigError, load_config

FIXTURE = Path(__file__).parent / "fixtures" / "config_ok.toml"


def _config_with_vault(tmp_path, vault_value):
    """Copy the OK fixture but swap in a custom vault_path value."""
    lines = FIXTURE.read_text().splitlines()
    out = [
        f'vault_path = "{vault_value}"' if line.strip().startswith("vault_path") else line
        for line in lines
    ]
    p = tmp_path / "config.toml"
    p.write_text("\n".join(out) + "\n")
    return p


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
    assert cfg.frames["budget"] == 4
    assert cfg.whisper_model == "mlx-community/whisper-small"
    assert cfg.browser["profile"]
    assert cfg.paywall["rules"][0]["via"] == "https://freedium-mirror.cfd/{url}"
    assert "medium.com" in cfg.paywall["rules"][0]["hosts"]
    assert cfg.browser["timeout_ms"] == 30000


def test_load_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.toml"))


def test_placeholder_vault_path_raises(tmp_path):
    p = _config_with_vault(tmp_path, "REPLACE_ME")
    with pytest.raises(ConfigError, match="placeholder"):
        load_config(p)


def test_vault_path_is_expanded(tmp_path):
    p = _config_with_vault(tmp_path, "~/some-vault")
    cfg = load_config(p)
    assert cfg.vault_path == Path.home() / "some-vault"


def test_relative_vault_path_resolves_against_config_dir(tmp_path):
    p = _config_with_vault(tmp_path, "vault")
    cfg = load_config(p)
    assert cfg.vault_path == (tmp_path / "vault").resolve()
