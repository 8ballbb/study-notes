"""Feature 3: YouTube chapters (fetched by yt-dlp, previously discarded) are surfaced
on TranscriptResult so the orchestrator can use them as topic anchors. Token-free."""

from study_notes.tools.youtube import Chapter, _chapters_from_info, _segments_to_result


def test_chapters_parsed_from_info():
    info = {
        "chapters": [
            {"title": "Intro", "start_time": 0.0, "end_time": 65.0},
            {"title": "Backpressure", "start_time": 65.0, "end_time": 300.0},
        ]
    }
    assert _chapters_from_info(info) == [
        Chapter(title="Intro", start="00:00:00", end="00:01:05"),
        Chapter(title="Backpressure", start="00:01:05", end="00:05:00"),
    ]


def test_chapters_absent_returns_empty():
    assert _chapters_from_info({}) == []
    assert _chapters_from_info({"chapters": None}) == []


def test_whisper_fallback_result_carries_chapters():
    # chapters come from the yt-dlp info dict, independent of captions vs Whisper —
    # the fallback must surface them too, not silently drop chapter-aware segmentation
    whisper_out = {"segments": [{"start": 0.0, "text": "hello"}]}
    chapters = [Chapter(title="Intro", start="00:00:00", end="00:01:05")]
    result = _segments_to_result("u", "vid", "T", None, whisper_out, chapters)
    assert result.chapters == chapters


def test_whisper_fallback_result_defaults_chapters_empty():
    whisper_out = {"segments": [{"start": 0.0, "text": "hi"}]}
    result = _segments_to_result("u", "vid", "T", None, whisper_out)
    assert result.chapters == []
