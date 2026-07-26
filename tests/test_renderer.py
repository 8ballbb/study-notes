from datetime import date

from study_notes.models import Card, Provenance, Topic
from study_notes.renderer import render_card, render_note, render_update_section


def _topic():
    prov = Provenance(origin="https://youtube.com/watch?v=abc", input_type="youtube",
                      captured_at=date(2026, 7, 26), source_date=date(2025, 11, 14))
    return Topic(
        title="Raft Consensus",
        tags=["consensus", "youtube"],
        summary=["Leader election picks one leader per term.", "Logs replicate from leader."],
        cards=[
            Card("What is a term in Raft?", "A logical clock period with one leader."),
            Card("What triggers a new term?", "A failed election or leader timeout.", timestamp="00:14:32"),
        ],
        provenance=prov,
    )


def test_render_card_inline_for_short():
    c = Card("Q short", "A short")
    assert render_card(c) == "Q short::A short"


def test_render_card_multiline_with_frame():
    c = Card("What triggers a new term?", "A failed election or leader timeout.", timestamp="00:14:32")
    out = render_card(c, frame_path="06 - Attachments/frames/raft_00-14-32.jpg")
    assert out == (
        "What triggers a new term?\n"
        "?\n"
        "A failed election or leader timeout.\n"
        "![[06 - Attachments/frames/raft_00-14-32.jpg]]"
    )


def test_render_note_has_frontmatter_and_sections():
    md = render_note(_topic(), category="Distributed Systems",
                     frame_paths={1: "06 - Attachments/frames/raft_00-14-32.jpg"})
    assert md.startswith("---\n")
    assert "title: Raft Consensus" in md
    assert "category: Distributed Systems" in md
    assert "type: study-note" in md
    assert "source: https://youtube.com/watch?v=abc" in md
    assert "source_type: youtube" in md
    assert "source_date: 2025-11-14" in md
    assert "captured_at: 2026-07-26" in md
    assert "supersedes: []" in md
    assert "## Core ideas" in md
    assert "- Leader election picks one leader per term." in md
    assert "## Study cards" in md
    assert "What is a term in Raft?::A logical clock period with one leader." in md
    assert "![[06 - Attachments/frames/raft_00-14-32.jpg]]" in md


def test_render_update_section_is_dated():
    section = render_update_section(_topic(), on=date(2026, 7, 26))
    assert section.startswith("## Update (2026-07-26)")
    assert "What is a term in Raft?" in section


def test_frontmatter_quotes_title_with_colon():
    topic = _topic()
    topic.title = "Raft: In Search of an Understandable Consensus Algorithm"
    md = render_note(topic, category="Distributed Systems")
    assert 'title: "Raft: In Search of an Understandable Consensus Algorithm"' in md


def test_frontmatter_source_date_none_has_no_trailing_space():
    topic = _topic()
    topic.provenance = Provenance(origin=topic.provenance.origin,
                                  input_type=topic.provenance.input_type,
                                  captured_at=topic.provenance.captured_at,
                                  source_date=None)
    md = render_note(topic, category="Distributed Systems")
    assert "source_date:\n" in md
    assert "source_date: \n" not in md


def test_render_card_multiline_without_frame():
    c = Card("Q?", "line one\nline two")
    assert render_card(c) == "Q?\n?\nline one\nline two"


def test_render_note_exact_output():
    prov = Provenance(origin="http://example.com", input_type="manual",
                      captured_at=date(2026, 1, 1), source_date=date(2026, 1, 2))
    topic = Topic(
        title="Test Note",
        tags=["a", "b"],
        summary=["First idea."],
        cards=[Card("Q1", "A1")],
        provenance=prov,
    )
    md = render_note(topic, category="General")
    expected = (
        "---\n"
        "title: Test Note\n"
        "category: General\n"
        "type: study-note\n"
        "tags: [a, b]\n"
        "source: http://example.com\n"
        "source_type: manual\n"
        "source_date: 2026-01-02\n"
        "captured_at: 2026-01-01\n"
        "supersedes: []\n"
        "---\n"
        "\n"
        "## Core ideas\n"
        "- First idea.\n"
        "\n"
        "## Study cards\n"
        "Q1::A1\n"
    )
    assert md == expected
