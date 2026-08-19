import pytest

from study_notes.cli import main, parse_args


def test_parse_add_with_flags():
    ns = parse_args(["add", "https://youtu.be/x", "--category", "Web APIs", "--dry-run", "--force"])
    assert ns.command == "add"
    assert ns.input == "https://youtu.be/x"
    assert ns.category == "Web APIs"
    assert ns.dry_run is True and ns.force is True


def test_parse_reindex():
    ns = parse_args(["reindex"])
    assert ns.command == "reindex"


def test_parse_link():
    ns = parse_args(["link"])
    assert ns.command == "link"


def test_parse_add_only():
    ns = parse_args(["add", "https://youtu.be/x", "--only", "the part about backpressure"])
    assert ns.only == "the part about backpressure"


def test_parse_add_only_defaults_none():
    ns = parse_args(["add", "https://youtu.be/x"])
    assert ns.only is None


def test_parse_login_with_url():
    ns = parse_args(["login", "https://x.com"])
    assert ns.command == "login"
    assert ns.url == "https://x.com"


def test_parse_login_without_url():
    ns = parse_args(["login"])
    assert ns.command == "login"
    assert ns.url is None


def test_add_only_with_dry_run_is_rejected():
    # contradictory: --only writes a confirmed slice, --dry-run writes nothing
    with pytest.raises(SystemExit):
        parse_args(["add", "https://youtu.be/x", "--only", "x", "--dry-run"])


def _write_config(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'vault_path = "{vault}"\n'
        'notes_root = "Notes"\n'
        'attachments_dir = "Attachments"\n'
        'frames_subdir = "frames"\n'
        '[database]\nurl = "unused"\n'
        '[embedding]\nmodel = "fake"\n'
        '[models]\norchestrator = "m"\n'
        '[prompts]\norchestrator = "prompts/orchestrator.md"\n'
        "[run]\ndry_run = false\n"
    )
    return cfg


def test_refine_rejects_path_outside_vault(tmp_path):
    # the vault-boundary guard returns 1 before any engine/db/token spend
    cfg = _write_config(tmp_path)
    assert main(["--config", str(cfg), "refine", "../../etc/hosts"]) == 1
