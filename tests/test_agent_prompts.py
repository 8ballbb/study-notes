from pathlib import Path


def test_orchestrator_prompt_covers_flow():
    t = Path("prompts/orchestrator.md").read_text().lower()
    for kw in [
        "decompose",
        "extractor",
        "enricher",
        "list_categories",
        "vault_search",
        "vault_write",
        "source",
        "verify",
    ]:
        assert kw in t, kw


def test_note_writing_guide_is_toolbox_not_qa_default():
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "understand" in t and "concise" in t
    assert "compose" in t or "toolbox" in t  # formats combine, not one-per-note


def test_orchestrator_prompt_gates_frames_on_visual():
    t = Path("prompts/orchestrator.md").read_text().lower()
    assert "prepare_video" in t
    assert "visual" in t


def test_note_writing_guide_covers_two_phase_visuals():
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "select_keyframes" in t
    assert "read" in t
    assert "embed" in t


def test_note_writing_guide_targets_visuals_text_first():
    # Text-first funnel: draft from text, target cue moments in narrow windows,
    # with a backstop for strongly-visual topics that lack explicit cues.
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "draft" in t
    assert "cue" in t
    assert "narrow" in t
    assert "backstop" in t


def test_orchestrator_forwards_exact_video_path():
    # The lead must pass the exact video_path returned by prepare_video, not a guess.
    t = Path("prompts/orchestrator.md").read_text().lower()
    assert "video_path" in t
    assert "verbatim" in t


def test_orchestrator_forwards_video_id_to_extractor():
    # The lead must pass the video_id (from prepare_video) to each extractor too,
    # since keep_frame requires it for the per-video frame folder.
    t = Path("prompts/orchestrator.md").read_text().lower()
    assert "video_id" in t


def test_orchestrator_prompt_uses_structure_as_segment_anchors():
    # Long sources segment on chapters/headings (Feature 3), not one thin summary.
    t = Path("prompts/orchestrator.md").read_text().lower()
    assert "chapters" in t
    assert "headings" in t


def test_orchestrator_prompt_covers_webpage():
    # Non-YouTube http/https sources must be routed to fetch_webpage.
    t = Path("prompts/orchestrator.md").read_text().lower()
    assert "fetch_webpage" in t


def test_enrichment_guide_requires_sources():
    t = Path("prompts/enrichment.md").read_text().lower()
    assert "websearch" in t or "web search" in t
    assert "source" in t and ("cite" in t or "url" in t)


def test_note_writing_has_montage_flow_and_voice():
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "montage" in t  # contact-sheet selection
    assert "index" in t  # pick the best index
    assert "video_id" in t  # keep_frame gets video_id
    assert "mental picture" in t  # Feynman-plain voice cue


def test_orchestrator_gate_counts_presenter_plus_slides_as_visual():
    # A presenter who also shows slides must count as visual, not be skipped as a talking-head.
    t = Path("prompts/orchestrator.md").read_text().lower()
    assert "slides" in t
    assert "presenter" in t
    assert "when in doubt" in t  # bias toward treating the source as visual


def test_note_writing_backstop_keyed_on_visual_source():
    # Backstop now fires whenever a video_path was given (source is visual), not only when
    # separately told the topic is "strongly visual".
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "backstop" in t
    assert "video_path" in t


def test_interactive_capture_prompt_overrides_no_ask_and_uses_ask_user():
    t = Path("prompts/interactive-capture.md").read_text().lower()
    assert "ask_user" in t
    assert "override" in t  # overrides orchestrator.md's "do not ask the user"
    assert "approve" in t  # per-note approval


def test_refine_prompt_uses_rewrite_note_and_ask_user():
    t = Path("prompts/refine.md").read_text().lower()
    assert "rewrite_note" in t
    assert "ask_user" in t
    assert "title" in t  # instructs not to change the title


def test_query_prompt_is_grounded_and_cited():
    t = Path("prompts/query.md").read_text().lower()
    assert "only" in t  # answer only from provided notes
    assert "[[" in t  # cite with wikilinks


def test_note_writing_guide_anchors_claims_to_source():
    # Feature: each claim can deep-link back to its exact source moment.
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "anchor" in t
    assert "?t=" in t or "youtu.be" in t  # the deep-link form


def test_orchestrator_preserves_segment_deeplinks_in_slice():
    # The lead must keep each segment's url in the slice so the extractor can anchor claims.
    t = Path("prompts/orchestrator.md").read_text().lower()
    assert "anchor" in t
    assert "url" in t
