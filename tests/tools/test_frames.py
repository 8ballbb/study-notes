import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from study_notes.tools.frames import (
    FrameExtractionError,
    _docker_ffmpeg,
    extract_frame,
    frame_filename,
)


def test_frame_filename_slugifies_timestamp():
    assert frame_filename("raft", "00:14:32") == "raft_00-14-32.jpg"


needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


@pytest.fixture
def work_dir():
    # Must be under the repo ($HOME) so Colima can bind-mount it — NOT tmp_path.
    d = Path("tests/.work") / uuid4().hex
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_video(work_dir):
    _docker_ffmpeg(
        work_dir,
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=10",
            "/work/sample.mp4",
            "-y",
        ],
    )
    return work_dir / "sample.mp4"


@pytest.mark.docker
@needs_docker
def test_extract_frame_writes_image(sample_video, work_dir):
    out = work_dir / "frame.jpg"
    result = extract_frame(sample_video, "00:00:01", out)
    assert result == out
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.docker
@needs_docker
def test_extract_frame_bad_input_raises(work_dir):
    with pytest.raises(FrameExtractionError):
        extract_frame(work_dir / "nope.mp4", "00:00:01", work_dir / "out.jpg")


def test_extract_frame_requires_shared_dir(tmp_path):
    # video and output in different dirs -> rejected before touching docker
    with pytest.raises(FrameExtractionError):
        extract_frame(tmp_path / "a" / "v.mp4", "00:00:01", tmp_path / "b" / "f.jpg")
