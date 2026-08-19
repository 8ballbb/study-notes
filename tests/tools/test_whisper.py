from study_notes.tools.youtube import TranscriptResult, _segments_to_result


def test_segments_to_result_maps_seconds_to_hhmmss():
    out = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "hello"},
            {"start": 83.5, "end": 86.0, "text": "world"},
        ]
    }
    r = _segments_to_result("u", "vid", "T", "2025-11-14", out)
    assert isinstance(r, TranscriptResult)
    assert r.segments[0].start == "00:00:00" and r.segments[0].text == "hello"
    assert r.segments[1].start == "00:01:23" and r.segments[1].text == "world"
    assert r.title == "T" and r.upload_date == "2025-11-14"


def test_segments_to_result_empty_raises():
    import pytest

    from study_notes.tools.youtube import TranscriptUnavailable

    with pytest.raises(TranscriptUnavailable):
        _segments_to_result("u", "v", "T", None, {"segments": []})
