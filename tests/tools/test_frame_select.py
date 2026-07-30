from pathlib import Path

from PIL import Image
import numpy as np


def _sharp(tmp: Path, name: str, seed: int) -> Path:
    rng = np.random.default_rng(seed)
    arr = (rng.integers(0, 256, size=(64, 64, 3))).astype("uint8")
    p = tmp / name
    Image.fromarray(arr).save(p)
    return p


def _blurred(tmp: Path, name: str, seed: int) -> Path:
    from PIL import ImageFilter
    rng = np.random.default_rng(seed)
    arr = (rng.integers(0, 256, size=(64, 64, 3))).astype("uint8")
    p = tmp / name
    Image.fromarray(arr).filter(ImageFilter.GaussianBlur(6)).save(p)
    return p


def test_laplacian_variance_sharp_beats_blurred(tmp_path):
    from study_notes.tools.frame_select import laplacian_variance
    sharp = laplacian_variance(Image.open(_sharp(tmp_path, "s.png", 1)))
    blur = laplacian_variance(Image.open(_blurred(tmp_path, "b.png", 1)))
    assert sharp > blur


def test_dhash_identical_zero_distance(tmp_path):
    from study_notes.tools.frame_select import dhash, hamming
    a = Image.open(_sharp(tmp_path, "a.png", 7))
    assert hamming(dhash(a), dhash(a.copy())) == 0


def test_dhash_distinct_images_have_distance(tmp_path):
    from study_notes.tools.frame_select import dhash, hamming
    a = dhash(Image.open(_sharp(tmp_path, "a.png", 1)))
    b = dhash(Image.open(_sharp(tmp_path, "b.png", 2)))
    assert hamming(a, b) > 10


def test_refine_drops_blurry_and_dedups_keeping_last(tmp_path):
    from study_notes.tools.frame_select import refine_candidates
    sharp1 = _sharp(tmp_path, "t1.png", 1)
    # near-duplicate of sharp1 (same seed, tiny brightness shift) at a later ts
    dup = _sharp(tmp_path, "t2.png", 1)
    blur = _blurred(tmp_path, "t3.png", 9)
    distinct = _sharp(tmp_path, "t4.png", 5)
    cands = [
        {"path": sharp1, "timestamp": "00:00:01"},
        {"path": dup, "timestamp": "00:00:02"},
        {"path": blur, "timestamp": "00:00:03"},
        {"path": distinct, "timestamp": "00:00:05"},
    ]
    out = refine_candidates(cands, budget=10)
    stamps = [c["timestamp"] for c in out]
    assert "00:00:03" not in stamps          # blurry dropped
    assert "00:00:01" not in stamps          # dedup kept the LAST of the run
    assert "00:00:02" in stamps and "00:00:05" in stamps


def test_refine_respects_budget(tmp_path):
    from study_notes.tools.frame_select import refine_candidates
    cands = [{"path": _sharp(tmp_path, f"f{i}.png", i), "timestamp": f"00:00:0{i}"}
             for i in range(1, 6)]
    out = refine_candidates(cands, budget=2)
    assert len(out) == 2
