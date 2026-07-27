import re
from dataclasses import dataclass

_CUE_TIME = re.compile(
    r"(\d{2}:\d{2}:\d{2})\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}"
)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class TranscriptSegment:
    start: str  # "HH:MM:SS"
    text: str


@dataclass
class TranscriptResult:
    url: str
    video_id: str
    title: str
    upload_date: str | None  # "YYYY-MM-DD"
    segments: list["TranscriptSegment"]


def parse_vtt(text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    lines = text.splitlines()
    i = 0
    last_text: str | None = None
    while i < len(lines):
        m = _CUE_TIME.search(lines[i])
        if not m:
            i += 1
            continue
        start = m.group(1)
        i += 1
        parts: list[str] = []
        while i < len(lines) and lines[i].strip():
            parts.append(_TAG.sub("", lines[i]).strip())
            i += 1
        cue = " ".join(p for p in parts if p).strip()
        if cue and cue != last_text:
            segments.append(TranscriptSegment(start=start, text=cue))
            last_text = cue
    return segments


import tempfile
from pathlib import Path


class TranscriptUnavailable(Exception):
    """No usable English captions were found for the video."""


def _fmt_upload_date(raw: str | None) -> str | None:
    if not raw or len(raw) != 8:
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def _result_from_info(url: str, info: dict, vtt_path: Path) -> TranscriptResult:
    if not vtt_path.exists():
        raise TranscriptUnavailable(url)
    segments = parse_vtt(vtt_path.read_text())
    if not segments:
        raise TranscriptUnavailable(url)
    return TranscriptResult(
        url=url,
        video_id=info.get("id", ""),
        title=info.get("title", ""),
        upload_date=_fmt_upload_date(info.get("upload_date")),
        segments=segments,
    )


def _pick_vtt(candidates: list[Path], video_id: str) -> Path:
    """Prefer an exact 'en' track (usually manual) over 'en-US'/'en-orig' (auto)."""
    order = {"en": 0, "en-US": 1, "en-orig": 2}

    def key(p: Path) -> tuple[int, str]:
        stem = p.name
        if stem.startswith(f"{video_id}.") and stem.endswith(".vtt"):
            lang = stem[len(video_id) + 1 : -4]
        else:
            lang = stem
        return (order.get(lang, 99), p.name)

    return sorted(candidates, key=key)[0]


def fetch_youtube_transcript(url: str, *, tmp_dir: Path | None = None) -> TranscriptResult:
    import yt_dlp

    from study_notes.tools._ytdlp import quiet_opts, stdout_to_stderr

    ctx = tempfile.TemporaryDirectory() if tmp_dir is None else None
    work = Path(tmp_dir) if tmp_dir is not None else Path(ctx.name)
    try:
        opts = quiet_opts({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en-orig"],
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": str(work / "%(id)s.%(ext)s"),
        })
        with stdout_to_stderr(), yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        vid = info.get("id", "")
        candidates = list(work.glob(f"{vid}*.vtt"))
        if not candidates:
            raise TranscriptUnavailable(url)
        return _result_from_info(url=url, info=info, vtt_path=_pick_vtt(candidates, vid))
    finally:
        if ctx is not None:
            ctx.cleanup()
