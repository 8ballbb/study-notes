"""Feature 2: auto-linking. Token-free tests for the pure body-editing and
candidate-selection logic. The full `run_link` disk+DB pass is exercised by a
db-marked test elsewhere."""

from study_notes.linker import apply_related_section, related_stems
from study_notes.vault_index import strip_related_section


class _StubIndex:
    """Returns a fixed hit list regardless of query — enough to exercise selection."""

    def __init__(self, hits):
        self._hits = hits

    def find_related(self, query, category=None, k=5):
        return self._hits[:k]


def test_apply_related_section_appends_block():
    out = apply_related_section("Body text.", ["Alpha", "Beta"])
    assert out == "Body text.\n\n## Related\n- [[Alpha]]\n- [[Beta]]"


def test_apply_related_section_is_idempotent():
    once = apply_related_section("Body text.", ["Alpha", "Beta"])
    twice = apply_related_section(once, ["Alpha", "Beta"])
    assert once == twice


def test_apply_related_section_replaces_stale_links():
    once = apply_related_section("Body text.", ["Alpha", "Beta"])
    updated = apply_related_section(once, ["Gamma"])
    assert updated == "Body text.\n\n## Related\n- [[Gamma]]"


def test_apply_related_section_empty_strips_block():
    once = apply_related_section("Body text.", ["Alpha"])
    assert apply_related_section(once, []) == "Body text."


def test_strip_related_removes_heading_and_everything_after():
    # reserved heading: the block and any trailing content after it are dropped
    assert strip_related_section("Prose.\n\n## Related\n- [[A]]\n- [[B]]") == "Prose."


def test_strip_related_noop_without_heading():
    assert strip_related_section("Just prose.\n") == "Just prose."


def test_strip_related_keeps_prose_related_section():
    # a legitimate "## Related" section over prose (not the managed wikilink block)
    # must survive — only the auto-generated bullet block is stripped
    text = "Prose.\n\n## Related\nSee the broader consensus literature for context."
    assert strip_related_section(text) == text.rstrip()


def test_related_stems_excludes_self_and_caps():
    idx = _StubIndex(
        [
            ("notes/A/self.md", 0.9),
            ("notes/B/other.md", 0.8),
            ("notes/A/self.md", 0.7),  # dup of self
            ("notes/C/third.md", 0.6),
        ]
    )
    stems = related_stems(idx, "notes/A/self.md", "Self", "content", k=5)  # type: ignore[arg-type]
    assert stems == ["other", "third"]


def test_related_stems_collapses_same_stem_across_categories():
    # two related notes sharing a filename in different categories collapse to one link:
    # an Obsidian `[[stem]]` resolves by basename, so they're indistinguishable anyway
    idx = _StubIndex(
        [
            ("notes/A/Raft.md", 0.9),
            ("notes/B/Raft.md", 0.8),  # same stem, different category
            ("notes/C/Paxos.md", 0.7),
        ]
    )
    stems = related_stems(idx, "notes/Z/Self.md", "Self", "content", k=5)  # type: ignore[arg-type]
    assert stems == ["Raft", "Paxos"]
