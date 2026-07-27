import io
from contextlib import redirect_stderr, redirect_stdout

from study_notes.tools._ytdlp import quiet_opts, stdout_to_stderr


def test_stdout_to_stderr_keeps_stdout_clean():
    # Simulates yt-dlp writing progress to stdout while inside the context.
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        with stdout_to_stderr():
            print("[download] 100% of 78KiB")
    assert out.getvalue() == ""            # nothing leaked to the MCP stdio channel
    assert "[download]" in err.getvalue()  # it went to stderr instead


def test_quiet_opts_sets_all_suppression_flags_and_preserves_caller_opts():
    o = quiet_opts({"format": "mp4", "outtmpl": "x"})
    assert o["quiet"] is True
    assert o["no_warnings"] is True
    assert o["noprogress"] is True
    assert o["logger"] is not None
    assert o["format"] == "mp4" and o["outtmpl"] == "x"
