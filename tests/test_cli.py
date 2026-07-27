from pathlib import Path

from study_notes.cli import build_system_prompt, parse_args


def test_parse_add_with_flags():
    ns = parse_args(["add", "https://youtu.be/x", "--category", "Web APIs",
                     "--dry-run", "--force"])
    assert ns.command == "add"
    assert ns.input == "https://youtu.be/x"
    assert ns.category == "Web APIs"
    assert ns.dry_run is True and ns.force is True


def test_parse_reindex():
    ns = parse_args(["reindex"])
    assert ns.command == "reindex"


def test_build_system_prompt_concatenates_procedure_and_antislop(tmp_path):
    from study_notes.config import Config
    proc = tmp_path / "procedure.md"; proc.write_text("PROCEDURE-BODY")
    slop = tmp_path / "anti-slop.md"; slop.write_text("ANTISLOP-BODY")
    cfg = Config(vault_path=tmp_path, notes_root="r", attachments_dir="a",
                 frames_subdir="frames", database_url="u", embedding_model="m",
                 models={}, prompts={"procedure": str(proc), "anti_slop": str(slop)},
                 dry_run=False)
    sp = build_system_prompt(cfg, dry_run=False)
    assert "PROCEDURE-BODY" in sp and "ANTISLOP-BODY" in sp
