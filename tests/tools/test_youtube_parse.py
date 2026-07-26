from pathlib import Path

from study_notes.tools.youtube import TranscriptSegment, parse_vtt

FIXTURE = Path(__file__).parent / "fixtures" / "sample.en.vtt"


def test_parse_vtt_extracts_timed_segments():
    segs = parse_vtt(FIXTURE.read_text())
    assert all(isinstance(s, TranscriptSegment) for s in segs)
    # tags stripped, ms dropped
    assert segs[0] == TranscriptSegment(start="00:00:00", text="Welcome to the lecture on consensus")
    # consecutive duplicate line (rolling caption) removed
    assert [s.text for s in segs] == [
        "Welcome to the lecture on consensus",
        "A leader is elected for each term",
    ]
    assert segs[1].start == "00:00:05"


def test_parse_vtt_empty_returns_empty():
    assert parse_vtt("WEBVTT\n\n") == []
