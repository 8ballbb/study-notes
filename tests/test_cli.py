from study_notes.cli import parse_args


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
