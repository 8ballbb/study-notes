import re
from dataclasses import dataclass


MAX_EM_DASHES = 4


@dataclass(frozen=True)
class SlopFinding:
    pattern: str
    snippet: str


_RULES: list[tuple[str, re.Pattern]] = [
    ("throat-clearing",
     re.compile(r"\b(here'?s the thing|let me be clear|i'?ll be honest|to be honest)\b", re.I)),
    ("binary-contrast",
     re.compile(r"\bit'?s not (just )?[^.\n]{1,50}?,?\s*it'?s\b", re.I)),
    ("faux-insight",
     re.compile(r"\b(what (most people|nobody|everyone) (gets? wrong)|what nobody tells you|"
                r"the part (everyone|most people) miss(es)?)\b", re.I)),
    ("importance-puffery",
     re.compile(r"\b(stands as a testament|a testament to|marks a pivotal moment|"
                r"plays? a (vital|crucial|pivotal) role)\b", re.I)),
    ("weasel-attribution",
     re.compile(r"\b(experts agree|studies show|research shows|widely regarded as|"
                r"it is (widely )?believed)\b", re.I)),
    ("summary-recap",
     re.compile(r"(?:^|[.\n])\s*(in conclusion|ultimately|in summary|to sum up)\b", re.I)),
    ("rhetorical-setup",
     re.compile(r"\b(what if i told you|think about it|plot twist)\b", re.I)),
    ("negative-listing",
     re.compile(r"\bnot (a |an )?[^.\n]{1,30}\.\s*not (a |an )?[^.\n]{1,30}\.", re.I)),
    ("emoji-heading",
     re.compile(r"(?:^|\n)#{1,6} .*[\U0001F000-\U0001FAFF☀-➿]")),
    ("cliche-word",
     re.compile(r"\b(delve|delving|tapestry|leverage|leveraging|seamless(ly)?|elevate|elevates|"
                r"boasts|underscore|underscores)\b|in the realm of|it'?s important to note|"
                r"a rich tapestry", re.I)),
    ("hedging",
     re.compile(r"\b(it'?s worth noting|it is worth noting|arguably|to some extent|"
                r"in many ways)\b", re.I)),
]


def slop_check(text: str) -> list[SlopFinding]:
    findings: list[SlopFinding] = []
    for name, rx in _RULES:
        for m in rx.finditer(text):
            findings.append(SlopFinding(pattern=name, snippet=m.group(0).strip()[:80]))
    em = text.count("—")
    if em > MAX_EM_DASHES:
        findings.append(SlopFinding(pattern="em-dash-overuse", snippet=f"{em} em dashes"))
    return findings
