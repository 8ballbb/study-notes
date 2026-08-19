"""Feature 4: partial/region capture directive. Token-free — checks the prompt
directive wiring; the full locate-confirm-extract handshake is an e2e concern."""

from pathlib import Path

from study_notes.orchestrator import _input_prompt


def test_only_directive_present_when_set():
    p = _input_prompt(
        "https://youtu.be/x", "youtube", None, None, False, "the part about backpressure"
    )
    assert "capture ONLY the region matching: 'the part about backpressure'" in p
    assert "ask_user" in p


def test_only_directive_absent_by_default():
    p = _input_prompt("https://youtu.be/x", "youtube", None, None, False)
    assert "capture ONLY" not in p


def test_partial_capture_prompt_exists_and_covers_flow():
    t = Path("prompts/partial-capture.md").read_text().lower()
    assert "ask_user" in t
    assert "confirm" in t
