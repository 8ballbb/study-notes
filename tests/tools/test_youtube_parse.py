from pathlib import Path

from study_notes.tools.youtube import TranscriptSegment, parse_vtt

FIXTURE = Path(__file__).parent / "fixtures" / "sample.en.vtt"


def test_parse_vtt_extracts_timed_segments():
    segs = parse_vtt(FIXTURE.read_text())
    assert all(isinstance(s, TranscriptSegment) for s in segs)
    # tags stripped, ms dropped
    assert segs[0] == TranscriptSegment(
        start="00:00:00", text="Welcome to the lecture on consensus"
    )
    # consecutive duplicate line (rolling caption) removed
    assert [s.text for s in segs] == [
        "Welcome to the lecture on consensus",
        "A leader is elected for each term",
    ]
    assert segs[1].start == "00:00:05"


def test_parse_vtt_empty_returns_empty():
    assert parse_vtt("WEBVTT\n\n") == []


def test_youtube_deeplink_builds_timestamped_url():
    from study_notes.tools.youtube import youtube_deeplink

    assert youtube_deeplink("dQw4w9WgXcQ", "00:12:04") == "https://youtu.be/dQw4w9WgXcQ?t=724"
    assert youtube_deeplink("abc", "00:00:00") == "https://youtu.be/abc?t=0"
    assert youtube_deeplink("abc", "01:02:03") == "https://youtu.be/abc?t=3723"
