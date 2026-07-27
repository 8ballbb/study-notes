"""yt-dlp output suppression.

yt-dlp writes progress (`[download] ...`) to stdout even with `quiet=True`. When
a tool runs inside an stdio MCP server, stdout IS the JSON-RPC channel, so any
such write corrupts the protocol and the tool call hangs. These helpers ensure
yt-dlp emits nothing to stdout.
"""
import contextlib
import sys


class _QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def quiet_opts(opts: dict) -> dict:
    """Return opts extended with flags that keep yt-dlp off stdout."""
    return {
        **opts,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
    }


@contextlib.contextmanager
def stdout_to_stderr():
    """Redirect stdout to stderr so nothing leaks to an MCP stdio channel."""
    with contextlib.redirect_stdout(sys.stderr):
        yield
