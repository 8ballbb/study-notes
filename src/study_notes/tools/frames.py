import re
import shutil
import subprocess
from pathlib import Path

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


def extract_frame(video_path: Path, timestamp: str, out_path: Path) -> Path:
    if video_path.parent != out_path.parent:
        raise FrameExtractionError(
            "video_path and out_path must share a directory (single Docker mount)"
        )
    work = video_path.parent
    proc = _docker_ffmpeg(work, [
        "-ss", timestamp, "-i", f"/work/{video_path.name}",
        "-frames:v", "1", "-q:v", "2", f"/work/{out_path.name}", "-y",
    ])
    if proc.returncode != 0 or not out_path.exists():
        raise FrameExtractionError(
            f"ffmpeg failed for {video_path} @ {timestamp}: "
            f"{proc.stderr.decode(errors='replace')[-300:]}"
        )
    return out_path


def download_video(url: str, out_dir: Path) -> Path:
    import yt_dlp

    from study_notes.tools._ytdlp import quiet_opts, stdout_to_stderr

    out_dir.mkdir(parents=True, exist_ok=True)
    opts = quiet_opts({
        # single progressive mp4 stream -> no ffmpeg merge step needed
        "format": "best[ext=mp4]/mp4/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
    })
    with stdout_to_stderr(), yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    matches = sorted(out_dir.glob(f"{info.get('id', '')}*"))
    if not matches:
        raise FrameExtractionError(f"video download produced no file for {url}")
    return matches[0]


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def select_keyframes(video_path: Path, start: str, end: str, budget: int,
                     out_dir: Path) -> list[dict]:
    """Phase 1: visually-distinct candidate frames (mpdecimate), window-scoped, budget-capped."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = video_path.parent
    rel = out_dir.name
    proc = _docker_ffmpeg(work, [
        "-ss", start, "-to", end, "-i", f"/work/{video_path.name}",
        "-vf", "mpdecimate,scale=512:-1,showinfo", "-vsync", "vfr", "-q:v", "3",
        f"/work/{rel}/cand_%03d.jpg", "-y",
    ])
    if proc.returncode != 0:
        raise FrameExtractionError(
            f"select_keyframes failed: {proc.stderr.decode(errors='replace')[-300:]}")
    times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)",
                                          proc.stderr.decode(errors="replace"))]
    frames = sorted(out_dir.glob("cand_*.jpg"))
    cands = [{"path": p, "timestamp": _fmt_ts(times[i] if i < len(times) else 0.0)}
             for i, p in enumerate(frames)]
    if len(cands) > budget:  # uniform subsample down to budget
        step = len(cands) / budget
        cands = [cands[int(i * step)] for i in range(budget)]
    return cands


def keep_frame(candidate_path: Path, prefix: str, timestamp: str, frames_dir: Path) -> str:
    frames_dir.mkdir(parents=True, exist_ok=True)
    name = frame_filename(prefix, timestamp)
    try:
        shutil.copyfile(candidate_path, frames_dir / name)
    except OSError as e:
        raise FrameExtractionError(f"keep_frame failed for {candidate_path}: {e}") from e
    return name
