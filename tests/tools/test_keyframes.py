import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from study_notes.tools.frames import keep_frame, select_keyframes


def test_keep_frame_copies_into_frames_dir(tmp_path):
    cand = tmp_path / "cand_001.jpg"
    cand.write_bytes(b"\xff\xd8\xff")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    name = keep_frame(cand, "raft", "00:01:23", "vidabc", frames_dir)
    assert name == "raft_00-01-23.jpg"
    assert (frames_dir / "vidabc" / name).exists()


def test_keep_frame_writes_under_video_id(tmp_path):
    import numpy as np
    from PIL import Image

    from study_notes.tools.frames import keep_frame

    src = tmp_path / "cand.jpg"
    Image.fromarray(np.random.default_rng(1).integers(0, 256, (64, 64, 3)).astype("uint8")).save(
        src
    )
    frames_dir = tmp_path / "frames"
    name = keep_frame(src, "liver", "00:00:05", "vid123", frames_dir)
    assert (frames_dir / "vid123" / name).exists()


def test_keep_frame_skips_perceptual_duplicate(tmp_path):
    import numpy as np
    from PIL import Image

    from study_notes.tools.frames import keep_frame

    arr = np.random.default_rng(2).integers(0, 256, (64, 64, 3)).astype("uint8")
    a = tmp_path / "a.jpg"
    Image.fromarray(arr).save(a)
    b = tmp_path / "b.jpg"
    Image.fromarray(arr).save(b)  # identical -> duplicate
    frames_dir = tmp_path / "frames"
    n1 = keep_frame(a, "liver", "00:00:05", "vid1", frames_dir)
    n2 = keep_frame(b, "liver", "00:00:09", "vid1", frames_dir)
    assert n1 == n2  # dedup returned the existing frame, no second file
    assert len(list((frames_dir / "vid1").glob("*.jpg"))) == 1


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

    # Static (non-time-varying) geq luma patterns rather than flat colors: refine_candidates
    # scores sharpness (variance-of-Laplacian) and dHash on grayscale luma, both of which are
    # exactly zero for a solid-color frame, so flat scenes would all look like identical blurry
    # duplicates to the real algorithm. These per-scene sinusoidal patterns give each held frame
    # genuine texture (distinct hash, sharpness above the blur floor) while staying constant
    # within a scene so mpdecimate still collapses each scene down to one held frame.
    lum1 = "128+127*sin(X/2)*sin(Y/2)"
    lum2 = "128+127*sin(X/2+3)*cos(Y/1.5)"
    lum3 = "128+127*cos(X/1.3)*sin(Y/2.2+1)"
    _docker_ffmpeg(
        work_dir,
        [
            "-f",
            "lavfi",
            "-i",
            f"nullsrc=size=320x240:d=2,format=yuv420p,geq=lum='{lum1}':cb=128:cr=128",
            "-f",
            "lavfi",
            "-i",
            f"nullsrc=size=320x240:d=2,format=yuv420p,geq=lum='{lum2}':cb=128:cr=128",
            "-f",
            "lavfi",
            "-i",
            f"nullsrc=size=320x240:d=2,format=yuv420p,geq=lum='{lum3}':cb=128:cr=128",
            "-filter_complex",
            "[0][1][2]concat=n=3:v=1",
            "/work/scenes.mp4",
            "-y",
        ],
    )
    return work_dir / "scenes.mp4"


@pytest.mark.docker
@needs_docker
def test_select_keyframes_dedups_distinct_scenes(scenes_video, work_dir):
    out = work_dir / "cands"
    out.mkdir()
    res = select_keyframes(scenes_video, "00:00:00", "00:00:06", budget=10, out_dir=out)
    cands = res["candidates"]
    assert 2 <= len(cands) <= 4  # ~3 distinct held scenes (deduped)
    assert all(c["path"].exists() for c in cands)
    assert all(c["timestamp"].count(":") == 2 for c in cands)
    assert res["montage_path"].exists()
    assert all("index" in c for c in cands)


@pytest.mark.docker
@needs_docker
def test_select_keyframes_respects_budget(scenes_video, work_dir):
    out = work_dir / "c2"
    out.mkdir()
    res = select_keyframes(scenes_video, "00:00:00", "00:00:06", budget=2, out_dir=out)
    cands = res["candidates"]
    assert len(cands) <= 2
    assert res["montage_path"].exists()
    assert all("index" in c for c in cands)


@pytest.mark.docker
@needs_docker
def test_select_keyframes_timestamps_are_absolute(scenes_video, work_dir):
    out = work_dir / "cands_abs"
    out.mkdir()
    res = select_keyframes(scenes_video, "00:00:02", "00:00:06", budget=10, out_dir=out)
    cands = res["candidates"]
    assert cands
    # window starts at 2s, so every reported timestamp must be >= 00:00:02
    assert all(c["timestamp"] >= "00:00:02" for c in cands)
    assert res["montage_path"].exists()
    assert all("index" in c for c in cands)


def test_select_keyframes_rejects_out_dir_outside_video_dir(tmp_path):
    from study_notes.tools.frames import FrameExtractionError

    video = tmp_path / "vid" / "v.mp4"
    video.parent.mkdir()
    video.write_bytes(b"x")
    out = tmp_path / "elsewhere"
    out.mkdir()
    with pytest.raises(FrameExtractionError):
        select_keyframes(video, "00:00:00", "00:00:02", budget=5, out_dir=out)
