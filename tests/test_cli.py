from study_notes.cli import parse_args


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
