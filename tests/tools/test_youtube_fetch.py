from pathlib import Path

import pytest

from study_notes.tools.youtube import (
    TranscriptResult,
    TranscriptUnavailable,
    _result_from_info,
)


def test_result_from_info_maps_metadata_and_parses_vtt(tmp_path):
    # Simulate what yt-dlp produced: an info dict + a written .en.vtt file.
    vtt = tmp_path / "vid123.en.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello there\n"
    )
    info = {"id": "vid123", "title": "My Talk", "upload_date": "20251114"}
    result = _result_from_info(
        url="https://youtu.be/vid123", info=info, vtt_path=vtt
    )
    assert isinstance(result, TranscriptResult)
    assert result.video_id == "vid123"
    assert result.title == "My Talk"
    assert result.upload_date == "2025-11-14"
    assert result.segments[0].start == "00:00:01"
    assert result.segments[0].text == "hello there"


def test_result_from_info_missing_vtt_raises(tmp_path):
    info = {"id": "vid123", "title": "My Talk", "upload_date": "20251114"}
    with pytest.raises(TranscriptUnavailable):
        _result_from_info(url="u", info=info, vtt_path=tmp_path / "missing.en.vtt")


@pytest.mark.network
def test_fetch_youtube_transcript_live():
    # A stable, caption-bearing video. Skipped unless network tests are run.
    from study_notes.tools.youtube import fetch_youtube_transcript

    res = fetch_youtube_transcript("https://www.youtube.com/watch?v=aircAruvnKk")
    assert res.segments
    assert res.title
