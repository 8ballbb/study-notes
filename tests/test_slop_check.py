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


def test_detects_faux_insight_and_negative_listing():
    findings = slop_check(
        "What most people get wrong is the eval. Not slow. Not unreliable. Just wrong."
    )
    patterns = {f.pattern for f in findings}
    assert "faux-insight" in patterns
    assert "negative-listing" in patterns


def test_flags_cliche_words():
    from study_notes.slop_check import slop_check
    pats = {f.pattern for f in slop_check("We delve into the rich tapestry of it.")}
    assert "cliche-word" in pats


def test_flags_em_dash_overuse():
    from study_notes.slop_check import slop_check
    text = "A — b — c — d — e — f."  # 5 em dashes > MAX_EM_DASHES
    assert any(f.pattern == "em-dash-overuse" for f in slop_check(text))


def test_flags_hedging():
    from study_notes.slop_check import slop_check
    assert any(f.pattern == "hedging" for f in slop_check("It's worth noting this is arguably true."))


def test_clean_technical_prose_not_flagged():
    from study_notes.slop_check import slop_check
    clean = ("A neuron sums the previous layer's activations, each scaled by a weight, then adds "
             "a bias and applies the sigmoid. The network has about 13,000 parameters.")
    assert slop_check(clean) == []
