import json
import subprocess

_SERVER = "study-notes-tools"
_PREFIX = f"mcp__{_SERVER}__"
TOOL_NAMES = [
    f"{_PREFIX}fetch_youtube_transcript",
    f"{_PREFIX}list_categories",
    f"{_PREFIX}vault_search",
    f"{_PREFIX}extract_frame",
    f"{_PREFIX}check_slop",
    f"{_PREFIX}vault_write",
]
WRITE_TOOL = f"{_PREFIX}vault_write"


class ClaudeRunError(Exception):
    """The `claude -p` run failed or returned an error envelope."""


def mcp_config_dict(config_path: str) -> dict:
    return {
        "mcpServers": {
            _SERVER: {
                "command": "uv",
                "args": ["run", "python", "-m", "study_notes.mcp_server"],
                "env": {"STUDY_NOTES_CONFIG": config_path},
            }
        }
    }


def build_command(*, input_prompt: str, model: str, system_prompt: str,
                  mcp_config_path: str, add_dirs: list[str], dry_run: bool) -> list[str]:
    tools = [t for t in TOOL_NAMES if not (dry_run and t == WRITE_TOOL)]
    cmd = [
        "claude", "-p", input_prompt,
        "--model", model,
        "--append-system-prompt", system_prompt,
        "--mcp-config", mcp_config_path,
        "--allowedTools", ",".join(tools),
        "--output-format", "json",
    ]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    return cmd


def parse_result(stdout: str) -> str:
    try:
        env = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise ClaudeRunError(f"could not parse claude output: {e}") from e
    if env.get("is_error"):
        raise ClaudeRunError(f"claude reported an error: {env.get('result')!r}")
    return env.get("result", "")


def run(cmd: list[str]) -> str:
    last: Exception | None = None
    for _ in range(2):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            try:
                return parse_result(proc.stdout)
            except ClaudeRunError as e:
                last = e
        else:
            last = ClaudeRunError(
                f"claude exited {proc.returncode}: {proc.stderr[-500:]}")
    raise last if last else ClaudeRunError("claude run failed")
