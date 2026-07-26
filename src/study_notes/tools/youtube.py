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
