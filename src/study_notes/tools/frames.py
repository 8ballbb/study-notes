import re
import shutil
import subprocess
from pathlib import Path

from study_notes.tools import frame_select

FFMPEG_IMAGE = "jrottenberg/ffmpeg:6.1-alpine"


class FrameExtractionError(Exception):
    """Docker ffmpeg could not extract the requested frame."""


def frame_filename(prefix: str, timestamp: str) -> str:
    return f"{prefix}_{timestamp.replace(':', '-')}.jpg"


def _docker_ffmpeg(work_dir: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", "-v", f"{work_dir.resolve()}:/work", FFMPEG_IMAGE, *args],
        capture_output=True,
    )


def download_video(url: str, out_dir: Path) -> Path:
    import yt_dlp

    from study_notes.tools._ytdlp import quiet_opts, stdout_to_stderr

    out_dir.mkdir(parents=True, exist_ok=True)
    opts = quiet_opts(
        {
            # Single progressive mp4 stream (no ffmpeg merge step). Cap at 480p: frames are
            # downscaled to 512px anyway, so taller streams are wasted download time/bytes.
            "format": "best[height<=480][ext=mp4]/best[height<=480]/best[ext=mp4]/mp4/best",
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        }
    )
    with stdout_to_stderr(), yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    matches = sorted(out_dir.glob(f"{info.get('id', '')}*"))
    if not matches:
        raise FrameExtractionError(f"video download produced no file for {url}")
    return matches[0]


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _ts_secs(hhmmss: str) -> int:
    parts = [int(p) for p in hhmmss.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def select_keyframes(video_path: Path, start: str, end: str, budget: int, out_dir: Path) -> dict:
    """Phase 1: visually-distinct candidate frames (mpdecimate), window-scoped, budget-capped."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_dir.parent.resolve() != video_path.parent.resolve():
        raise FrameExtractionError(
            "out_dir must be a direct subdirectory of the video's directory (single Docker mount)"
        )
    work = video_path.parent
    rel = out_dir.name
    start_s = _ts_secs(start)
    dur = max(0, _ts_secs(end) - start_s)
    proc = _docker_ffmpeg(
        work,
        [
            "-ss",
            start,
            "-t",
            str(dur),
            "-i",
            f"/work/{video_path.name}",
            "-vf",
            "mpdecimate,scale=512:-1,showinfo",
            "-vsync",
            "vfr",
            "-q:v",
            "3",
            f"/work/{rel}/cand_%03d.jpg",
            "-y",
        ],
    )
    if proc.returncode != 0:
        raise FrameExtractionError(
            f"select_keyframes failed: {proc.stderr.decode(errors='replace')[-300:]}"
        )
    times = [
        float(t) for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr.decode(errors="replace"))
    ]
    frames = sorted(out_dir.glob("cand_*.jpg"))
    cands = [
        {"path": p, "timestamp": _fmt_ts(start_s + (times[i] if i < len(times) else 0.0))}
        for i, p in enumerate(frames)
    ]
    refined = frame_select.refine_candidates(cands, budget)
    for i, c in enumerate(refined):
        c["index"] = i
    montage_path = out_dir / "montage.jpg"
    frame_select.build_montage(refined, montage_path)
    return {"candidates": refined, "montage_path": montage_path}


def keep_frame(
    candidate_path: Path, prefix: str, timestamp: str, video_id: str, frames_dir: Path
) -> str:
    from PIL import Image

    target_dir = frames_dir / video_id
    target_dir.mkdir(parents=True, exist_ok=True)
    # Perceptual dedup: if a near-identical frame is already kept for this video, reuse it.
    try:
        with Image.open(candidate_path) as im:
            im.load()
            new_hash = frame_select.dhash(im)
        for existing in sorted(target_dir.glob("*.jpg")):
            with Image.open(existing) as ex:
                ex.load()
                if (
                    frame_select.hamming(new_hash, frame_select.dhash(ex))
                    < frame_select.DUP_DISTANCE
                ):
                    return existing.name
    except Exception:
        pass  # hash failure must never lose a frame — fall through and keep it
    name = frame_filename(prefix, timestamp)
    try:
        shutil.copyfile(candidate_path, target_dir / name)
    except OSError as e:
        raise FrameExtractionError(f"keep_frame failed for {candidate_path}: {e}") from e
    return name
