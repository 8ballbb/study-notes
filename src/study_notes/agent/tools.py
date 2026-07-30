import json
from datetime import date
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from study_notes.agent.context import EngineContext
from study_notes.models import Provenance
from study_notes.slop_check import slop_check
from study_notes.tools import frames as fr
from study_notes.tools import search, youtube


def _ok(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def build_tool_server(ctx: EngineContext):
    # NOTE: `@tool(...)` returns an `SdkMcpTool` dataclass instance (its
    # `handler` attribute holds the coroutine function), not a directly
    # awaitable/callable object. We define plain `async def` functions,
    # register them with the SDK via `tool(...)(fn)`, and keep the plain
    # functions themselves in `fns` so tests (and other in-process callers)
    # can `await tools[name](args)` directly.

    frames_dir = ctx.config.vault_path / ctx.config.attachments_dir / ctx.config.frames_subdir

    async def fetch_youtube_transcript(args: dict) -> dict:
        r = youtube.fetch_youtube_transcript(args["url"], whisper_model=ctx.config.whisper_model)
        return _ok({"url": r.url, "video_id": r.video_id, "title": r.title,
                    "upload_date": r.upload_date,
                    "segments": [{"start": s.start, "text": s.text} for s in r.segments]})

    async def list_categories(args: dict) -> dict:
        return _ok(search.list_categories(ctx.index))

    async def vault_search(args: dict) -> dict:
        return _ok(search.vault_search(ctx.index, args["query"], args["category"]))

    async def prepare_video(args: dict) -> dict:
        work = frames_dir / "_work"
        video = fr.download_video(args["url"], work)
        return _ok({"video_id": video.stem, "video_path": str(video)})

    async def select_keyframes(args: dict) -> dict:
        vp = Path(args["video_path"])
        out = vp.parent / f"cands_{args['start'].replace(':', '')}_{args['end'].replace(':', '')}"
        res = fr.select_keyframes(vp, args["start"], args["end"], int(args["budget"]), out)
        return _ok({
            "candidates": [{"candidate_path": str(c["path"]), "timestamp": c["timestamp"],
                            "index": c["index"]} for c in res["candidates"]],
            "montage_path": str(res["montage_path"]),
        })

    async def keep_frame(args: dict) -> dict:
        name = fr.keep_frame(Path(args["candidate_path"]), args["prefix"],
                             args["timestamp"], args["video_id"], frames_dir)
        return _ok({"embed_path":
                    f"{ctx.config.attachments_dir}/{ctx.config.frames_subdir}/{args['video_id']}/{name}"})

    async def vault_write(args: dict) -> dict:
        sd = args.get("source_date") or None
        prov = Provenance(origin=args["source"], input_type=args["source_type"],
                          captured_at=date.today(),
                          source_date=date.fromisoformat(sd) if sd else None)
        path = ctx.writer.write_markdown(args["title"], args["category"],
                                         args["markdown"], prov)
        return _ok({"path": path})

    async def check_slop(args: dict) -> dict:
        return _ok([{"pattern": f.pattern, "snippet": f.snippet}
                    for f in slop_check(args["text"])])

    fns = {
        "fetch_youtube_transcript": fetch_youtube_transcript, "list_categories": list_categories,
        "vault_search": vault_search, "prepare_video": prepare_video,
        "select_keyframes": select_keyframes, "keep_frame": keep_frame,
        "vault_write": vault_write, "check_slop": check_slop,
    }

    sdk_tools = [
        tool("fetch_youtube_transcript", "Fetch a YouTube transcript with timestamps.",
             {"url": str})(fetch_youtube_transcript),
        tool("list_categories", "List existing vault categories.", {})(list_categories),
        tool("vault_search", "Find related notes within a category.",
             {"query": str, "category": str})(vault_search),
        tool("prepare_video", "Download the video once so frames can be selected.",
             {"url": str})(prepare_video),
        tool("select_keyframes",
             "Phase 1: select visually-distinct candidate frames in a time window.",
             {"video_path": str, "start": str, "end": str, "budget": int})(select_keyframes),
        tool("keep_frame", "Keep a chosen candidate frame (embed it in the vault).",
             {"candidate_path": str, "prefix": str, "timestamp": str, "video_id": str})(keep_frame),
        tool("vault_write", "Write a finished note (markdown) into a category, non-destructively.",
             {"title": str, "category": str, "markdown": str, "source": str,
              "source_type": str, "source_date": str})(vault_write),
        tool("check_slop", "Flag AI-slop writing patterns in a draft.", {"text": str})(check_slop),
    ]

    server = create_sdk_mcp_server(name="study-notes", version="1.0.0", tools=sdk_tools)
    return server, fns
