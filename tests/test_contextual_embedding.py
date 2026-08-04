"""Feature 1: the text handed to the embedder carries a one-line source frame
(Anthropic contextual retrieval) while the stored/displayed content is untouched.
Token-free — exercises the pure `_embed_text` helper, no DB."""

from datetime import date

from study_notes.models import Note, Provenance
from study_notes.vault_index import _embed_text


def _note(title, category, content, origin):
    prov = Provenance(origin=origin, input_type="youtube", captured_at=date(2026, 8, 4))
    return Note(path="p.md", title=title, category=category, content=content, provenance=prov)


def test_embed_text_prepends_source_frame():
    note = _note(
        "Backpressure", "Distributed Systems", "The queue fills up.", "https://youtu.be/abc"
    )
    out = _embed_text(note)
    assert out.startswith("Part of https://youtu.be/abc. Topic area: Distributed Systems.")
    assert "Backpressure" in out
    assert out.endswith("The queue fills up.")


def test_embed_text_preserves_content_verbatim():
    # the frame is additive: the raw body must survive unmodified for retrieval
    note = _note("T", "C", "body line one\nbody line two", "src")
    assert "body line one\nbody line two" in _embed_text(note)


def test_embed_text_strips_related_block():
    # the auto-linker's `## Related` wikilinks are navigation, not retrieval signal
    note = _note("T", "C", "Real prose here.\n\n## Related\n- [[Other]]", "src")
    out = _embed_text(note)
    assert "Real prose here." in out
    assert "## Related" not in out and "[[Other]]" not in out
