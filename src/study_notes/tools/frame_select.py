"""Local, key-free image refinement for keyframe candidates (numpy + Pillow)."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BLUR_FLOOR = 100.0   # variance-of-Laplacian below this = blur/transition
DUP_DISTANCE = 10    # dHash (64-bit) Hamming distance below this = near-duplicate
MONTAGE_COLS = 3

_THUMB = 256


def laplacian_variance(img: Image.Image) -> float:
    a = np.asarray(img.convert("L"), dtype=np.float64)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    lap = (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1]
           + a[1:-1, :-2] + a[1:-1, 2:])
    return float(lap.var())


def dhash(img: Image.Image, size: int = 8) -> int:
    a = np.asarray(img.convert("L").resize((size + 1, size)), dtype=np.int16)
    diff = a[:, 1:] > a[:, :-1]
    bits = 0
    for v in diff.flatten():
        bits = (bits << 1) | int(v)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _load(path: Path):
    """Return (sharpness, dhash) or None if the image cannot be read."""
    try:
        with Image.open(path) as im:
            im.load()
            return laplacian_variance(im), dhash(im)
    except Exception:
        return None


def refine_candidates(candidates: list[dict], budget: int) -> list[dict]:
    scored = []
    for c in candidates:
        m = _load(c["path"])
        if m is not None:
            scored.append({**c, "sharp": m[0], "hash": m[1]})
    if not scored:
        return []
    # Blur filter — but never drop everything: if none clear the floor, keep the sharpest.
    sharp = [c for c in scored if c["sharp"] >= BLUR_FLOOR]
    if not sharp:
        sharp = [max(scored, key=lambda c: c["sharp"])]
    sharp.sort(key=lambda c: c["timestamp"])
    # Settled dedup: collapse consecutive near-duplicate runs, keep the LAST (settled).
    deduped = []
    for c in sharp:
        if deduped and hamming(deduped[-1]["hash"], c["hash"]) < DUP_DISTANCE:
            deduped[-1] = c  # keep the later, settled frame of the run
        else:
            deduped.append(c)
    # Budget cap: greedy farthest-point on dHash so we keep the most distinct set.
    if budget > 0 and len(deduped) > budget:
        chosen = [max(deduped, key=lambda c: c["sharp"])]
        while len(chosen) < budget:
            nxt = max((c for c in deduped if c not in chosen),
                      key=lambda c: min(hamming(c["hash"], s["hash"]) for s in chosen))
            chosen.append(nxt)
        deduped = sorted(chosen, key=lambda c: c["timestamp"])
    return [{"path": c["path"], "timestamp": c["timestamp"]} for c in deduped]


def build_montage(candidates: list[dict], out_path: Path,
                  cols: int = MONTAGE_COLS) -> Path:
    thumbs = []
    for c in candidates:
        with Image.open(c["path"]) as im:
            im = im.convert("RGB")
            im.thumbnail((_THUMB, _THUMB))
            cell = Image.new("RGB", (_THUMB, _THUMB + 18), (20, 20, 20))
            cell.paste(im, ((_THUMB - im.width) // 2, 0))
            ImageDraw.Draw(cell).text(
                (4, _THUMB + 3), f"[{c['index']}] {c['timestamp']}", fill=(255, 255, 255))
            thumbs.append(cell)
    if not thumbs:
        Image.new("RGB", (_THUMB, _THUMB), (20, 20, 20)).save(out_path)
        return out_path
    rows = (len(thumbs) + cols - 1) // cols
    cw, ch = thumbs[0].size
    sheet = Image.new("RGB", (cols * cw, rows * ch), (20, 20, 20))
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * cw, (i // cols) * ch))
    sheet.save(out_path, quality=85)
    return out_path
