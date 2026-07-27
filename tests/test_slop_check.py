from study_notes.slop_check import SlopFinding, slop_check


def test_clean_text_has_no_findings():
    clean = (
        "## Core ideas\n"
        "- Raft elects one leader per term.\n"
        "- A log entry commits once a majority replicate it.\n"
    )
    assert slop_check(clean) == []


def test_detects_common_slop_patterns():
    slop = (
        "Here's the thing. It's not about the model, it's about the eval. "
        "Studies show this marks a pivotal moment. In conclusion, think about it."
    )
    patterns = {f.pattern for f in slop_check(slop)}
    assert {"throat-clearing", "binary-contrast", "weasel-attribution",
            "importance-puffery", "summary-recap", "rhetorical-setup"} <= patterns


def test_detects_emoji_heading():
    findings = slop_check("## Overview \U0001F680\nsome text")
    assert any(f.pattern == "emoji-heading" for f in findings)


def test_findings_carry_snippet():
    findings = slop_check("Here's the thing about caching.")
    assert findings and all(isinstance(f, SlopFinding) and f.snippet for f in findings)
