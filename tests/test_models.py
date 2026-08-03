from datetime import date

from study_notes.models import Card, Category, Note, Placement, Provenance, Topic


def test_card_defaults():
    c = Card(question="Q", answer="A")
    assert c.cloze is False
    assert c.timestamp is None


def test_topic_holds_cards_and_provenance():
    prov = Provenance(
        origin="https://x",
        input_type="youtube",
        captured_at=date(2026, 7, 26),
        source_date=date(2025, 11, 14),
    )
    topic = Topic(
        title="Raft",
        tags=["consensus"],
        summary=["idea one"],
        cards=[Card("Q", "A", timestamp="00:14:32")],
        provenance=prov,
    )
    assert topic.cards[0].timestamp == "00:14:32"
    assert topic.provenance.input_type == "youtube"


def test_placement_actions():
    cat = Category(name="Distributed Systems", description="d")
    p = Placement(category=cat, action="merge", target_note="Notes/Distributed Systems/Raft.md")
    assert p.action == "merge"
    assert p.category.name == "Distributed Systems"


def test_note_shape():
    prov = Provenance(
        origin="f.pdf", input_type="pdf", captured_at=date(2026, 7, 26), source_date=None
    )
    n = Note(path="a/b.md", title="T", category="Cat", content="# body", provenance=prov)
    assert n.path == "a/b.md"
