import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from study_notes.tools.frames import keep_frame, select_keyframes


def test_keep_frame_copies_into_frames_dir(tmp_path):
    cand = tmp_path / "cand_001.jpg"; cand.write_bytes(b"\xff\xd8\xff")
    frames_dir = tmp_path / "frames"; frames_dir.mkdir()
    name = keep_frame(cand, "raft", "00:01:23", frames_dir)
    assert name == "raft_00-01-23.jpg"
    assert (frames_dir / name).exists()


needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


@pytest.fixture
def work_dir():
    d = Path("tests/.work") / uuid4().hex
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def scenes_video(work_dir):
    from study_notes.tools.frames import _docker_ffmpeg
    _docker_ffmpeg(work_dir, [
        "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2,format=yuv420p",
        "-f", "lavfi", "-i", "color=c=green:s=320x240:d=2,format=yuv420p",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2,format=yuv420p",
        "-filter_complex", "[0][1][2]concat=n=3:v=1", "/work/scenes.mp4", "-y",
    ])
    return work_dir / "scenes.mp4"


@pytest.mark.docker
@needs_docker
def test_select_keyframes_dedups_distinct_scenes(scenes_video, work_dir):
    out = work_dir / "cands"; out.mkdir()
    cands = select_keyframes(scenes_video, "00:00:00", "00:00:06", budget=10, out_dir=out)
    assert 2 <= len(cands) <= 4          # ~3 distinct held scenes (deduped)
    assert all(c["path"].exists() for c in cands)
    assert all(c["timestamp"].count(":") == 2 for c in cands)


@pytest.mark.docker
@needs_docker
def test_select_keyframes_respects_budget(scenes_video, work_dir):
    out = work_dir / "c2"; out.mkdir()
    cands = select_keyframes(scenes_video, "00:00:00", "00:00:06", budget=2, out_dir=out)
    assert len(cands) <= 2
