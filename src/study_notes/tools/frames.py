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
