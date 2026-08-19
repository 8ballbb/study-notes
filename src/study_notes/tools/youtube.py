import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_CUE_TIME = re.compile(r"(\d{2}:\d{2}:\d{2})\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}")
_TAG = re.compile(r"<[^>]+>")


@dataclass
class TranscriptSegment:
    start: str  # "HH:MM:SS"
    text: str


@dataclass
class Chapter:
    title: str
    start: str  # "HH:MM:SS"
    end: str  # "HH:MM:SS"


@dataclass
class TranscriptResult:
    url: str
    video_id: str
    title: str
    upload_date: str | None  # "YYYY-MM-DD"
    segments: list["TranscriptSegment"]
    chapters: list["Chapter"] = field(default_factory=list)


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


class TranscriptUnavailable(Exception):
    """No usable English captions were found for the video."""


def _fmt_upload_date(raw: str | None) -> str | None:
    if not raw or len(raw) != 8:
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def _chapters_from_info(info: dict) -> list[Chapter]:
    """yt-dlp exposes `chapters` (start_time/end_time in seconds) when a video has them.
    Normalize to the same HH:MM:SS format the transcript segments use."""
    return [
        Chapter(
            title=c.get("title", ""),
            start=_secs_to_hhmmss(c.get("start_time", 0.0)),
            end=_secs_to_hhmmss(c.get("end_time", 0.0)),
        )
        for c in (info.get("chapters") or [])
    ]


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
        chapters=_chapters_from_info(info),
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


def _secs_to_hhmmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _hhmmss_to_secs(hhmmss: str) -> int:
    parts = [int(p) for p in hhmmss.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def youtube_deeplink(video_id: str, hhmmss: str) -> str:
    """A deep link that opens the video at a given moment: `youtu.be/<id>?t=<secs>`.
    Used to anchor a note's claims back to the exact source moment they came from."""
    return f"https://youtu.be/{video_id}?t={_hhmmss_to_secs(hhmmss)}"


def _segments_to_result(
    url: str,
    video_id: str,
    title: str,
    upload_date: str | None,
    whisper_out: dict,
    chapters: list[Chapter] | None = None,
) -> TranscriptResult:
    segs = [
        TranscriptSegment(start=_secs_to_hhmmss(s["start"]), text=s["text"].strip())
        for s in whisper_out.get("segments", [])
        if s.get("text", "").strip()
    ]
    if not segs:
        raise TranscriptUnavailable(url)
    return TranscriptResult(
        url=url,
        video_id=video_id,
        title=title,
        upload_date=upload_date,
        segments=segs,
        chapters=chapters or [],
    )


def transcribe_audio_local(wav_path: Path, model: str) -> dict:
    import mlx_whisper
    import soundfile as sf

    audio, _ = sf.read(str(wav_path), dtype="float32")  # 16 kHz mono
    return mlx_whisper.transcribe(audio, path_or_hf_repo=model)


def fetch_youtube_transcript(
    url: str, *, tmp_dir: Path | None = None, whisper_model: str | None = None
) -> TranscriptResult:
    import yt_dlp

    from study_notes.tools._ytdlp import quiet_opts, stdout_to_stderr

    if tmp_dir is not None:
        ctx: tempfile.TemporaryDirectory[str] | None = None
        work = Path(tmp_dir)
    else:
        ctx = tempfile.TemporaryDirectory()
        work = Path(ctx.name)
    try:
        opts = quiet_opts(
            {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en", "en-US", "en-orig"],
                "subtitlesformat": "vtt",
                "skip_download": True,
                "outtmpl": str(work / "%(id)s.%(ext)s"),
            }
        )
        with stdout_to_stderr(), yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        vid = info.get("id", "")
        candidates = list(work.glob(f"{vid}*.vtt"))
        if candidates:
            return _result_from_info(url=url, info=info, vtt_path=_pick_vtt(candidates, vid))
        if whisper_model:
            # Any failure in the local-Whisper fallback (download, ffmpeg, model)
            # degrades gracefully to TranscriptUnavailable.
            try:
                from study_notes.tools.frames import _docker_ffmpeg

                aopts = quiet_opts(
                    {"format": "bestaudio/best", "outtmpl": str(work / "%(id)s.%(ext)s")}
                )
                with stdout_to_stderr(), yt_dlp.YoutubeDL(aopts) as ydl:
                    ainfo = ydl.extract_info(url, download=True)
                aid = ainfo.get("id", "")
                src = sorted(work.glob(f"{aid}*")) if aid else []
                if src:
                    wav = work / "audio16k.wav"
                    _docker_ffmpeg(
                        work,
                        [
                            "-i",
                            f"/work/{src[0].name}",
                            "-vn",
                            "-ac",
                            "1",
                            "-ar",
                            "16000",
                            f"/work/{wav.name}",
                            "-y",
                        ],
                    )
                    out = transcribe_audio_local(wav, whisper_model)
                    return _segments_to_result(
                        url,
                        aid,
                        ainfo.get("title", ""),
                        _fmt_upload_date(ainfo.get("upload_date")),
                        out,
                        _chapters_from_info(ainfo),
                    )
            except Exception as e:
                logging.getLogger(__name__).warning("whisper fallback failed for %s: %s", url, e)
        raise TranscriptUnavailable(url)
    finally:
        if ctx is not None:
            ctx.cleanup()
