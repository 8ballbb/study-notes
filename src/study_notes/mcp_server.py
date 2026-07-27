import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from study_notes.config import Config, load_config
from study_notes.tools import frames, search, youtube
from study_notes.tools.vault_write import VaultWriter

mcp = FastMCP("study-notes-tools")


@dataclass
class Context:
    config: Config
    writer: VaultWriter


_ctx: Context | None = None


def _validate_write_action(action: str, target_note: str | None) -> None:
    if action not in ("new_note", "merge"):
        raise ValueError(f"invalid action: {action!r} (expected 'new_note' or 'merge')")
    if action == "merge" and not target_note:
        raise ValueError("action='merge' requires target_note")
    if action == "new_note" and target_note:
        raise ValueError("target_note is only valid with action='merge'")


def build_context(config: Config) -> Context:
    from study_notes.db import connect
    from study_notes.embedding import BGEM3Embedder
    from study_notes.vault_index import VaultIndex

    index = VaultIndex(connect(config.database_url),
                       BGEM3Embedder(config.embedding_model))
    return Context(config=config, writer=VaultWriter(config, index))


def _context() -> Context:
    global _ctx
    if _ctx is None:
        cfg_path = os.environ.get("STUDY_NOTES_CONFIG", "config.toml")
        _ctx = build_context(load_config(Path(cfg_path)))
    return _ctx


@mcp.tool()
def fetch_youtube_transcript(url: str) -> dict:
    """Fetch a YouTube video's English transcript with timestamps and metadata."""
    r = youtube.fetch_youtube_transcript(url)
    return {
        "url": r.url, "video_id": r.video_id, "title": r.title,
        "upload_date": r.upload_date,
        "segments": [{"start": s.start, "text": s.text} for s in r.segments],
    }


@mcp.tool()
def list_categories() -> list[dict]:
    """List existing vault categories with their descriptions."""
    return search.list_categories(_context().writer.index)


@mcp.tool()
def vault_search(query: str, category: str, k: int = 5) -> list[dict]:
    """Find notes related to `query` WITHIN a single category (never crosses categories)."""
    return search.vault_search(_context().writer.index, query, category, k)


@mcp.tool()
def extract_frame(video_url: str, timestamp: str, prefix: str) -> dict:
    """Download a video and save the frame at `timestamp` (HH:MM:SS) into the vault frames dir.

    Requires `config.vault_path` to be under the host home dir (Colima mount).
    The video is downloaded into the frames dir (same mount as the output frame)
    and deleted after extraction, leaving only the JPEG.
    """
    ctx = _context()
    frames_dir = ctx.config.vault_path / ctx.config.attachments_dir / ctx.config.frames_subdir
    frames_dir.mkdir(parents=True, exist_ok=True)
    video = frames.download_video(video_url, frames_dir)  # same dir as the frame
    out = frames_dir / frames.frame_filename(prefix, timestamp)
    try:
        frames.extract_frame(video, timestamp, out)
    finally:
        video.unlink(missing_ok=True)  # drop the large video, keep the frame
    rel = f"{ctx.config.attachments_dir}/{ctx.config.frames_subdir}/{out.name}"
    return {"embed_path": rel}


@mcp.tool()
def vault_write(title: str, category: str, summary: list[str], cards: list[dict],
                source: str, source_type: str, source_date: str | None,
                action: str = "new_note", target_note: str | None = None) -> dict:
    """Write a study note non-destructively. action: 'new_note' or 'merge' (into target_note).

    On merge, the note's category is taken from `target_note`'s location; the
    `category` argument is used only for `new_note`.
    """
    _validate_write_action(action, target_note)
    from study_notes.models import Card, Provenance, Topic

    prov = Provenance(
        origin=source, input_type=source_type, captured_at=date.today(),
        source_date=date.fromisoformat(source_date) if source_date else None,
    )
    topic = Topic(
        title=title, tags=[], summary=summary,
        cards=[Card(question=c["question"], answer=c["answer"],
                    cloze=c.get("cloze", False), timestamp=c.get("timestamp"))
               for c in cards],
        provenance=prov,
    )
    w = _context().writer
    if action == "merge":
        path = w.write_merge(target_note, topic, on=date.today())
    else:
        path = w.write_new(topic, category=category)
    return {"path": path}


@mcp.tool()
def check_slop(text: str) -> list[dict]:
    """Flag AI-slop writing patterns in a drafted note. Returns findings to fix before writing."""
    from study_notes.slop_check import slop_check

    return [{"pattern": f.pattern, "snippet": f.snippet} for f in slop_check(text)]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
