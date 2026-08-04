"""Feature 3: YouTube chapters (fetched by yt-dlp, previously discarded) are surfaced
on TranscriptResult so the orchestrator can use them as topic anchors. Token-free."""

from study_notes.tools.youtube import Chapter, _chapters_from_info


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
