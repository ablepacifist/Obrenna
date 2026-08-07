"""Answer extraction and grading.

Deliberately deterministic (no model-as-judge): a score change must mean the
model under test changed, not that the judge drifted. The cost is that
extraction has to be robust to how chatty models actually answer, which is
what most of this module is.

Extraction prefers an explicitly marked final answer ("the answer is 42",
"Answer: C") over positional heuristics, because a chain-of-thought response
is full of intermediate numbers and the last one is not reliably the result --
that mistake alone can make a correct model look ~random on math suites.
"""

from __future__ import annotations

import re

# "the answer is 42", "answer: 42", "final answer = 42", "**Answer:** 42"
_ANSWER_LEAD = re.compile(
    r"(?:final\s+answer|answer|result|solution|total)\b\s*(?:is|:|=|\*\*:?)?\s*",
    re.IGNORECASE,
)
# \boxed{42} — common in math-tuned models.
_BOXED = re.compile(r"\\boxed\{\s*([^}]+?)\s*\}")
# A number, optionally signed, with thousands separators and/or decimals.
_NUMBER = re.compile(r"[-+]?\$?\s*\d[\d,]*(?:\.\d+)?")
# A standalone choice letter: "C", "(C)", "C)", "C." — not a letter inside a word.
_CHOICE = re.compile(r"(?:^|[^A-Za-z])\(?([A-Ha-h])\)?(?=[)\.\s:,]|$)")


def _clean_number(raw: str) -> str:
    """Normalise a matched number to a comparable form."""
    s = raw.replace(",", "").replace("$", "").replace(" ", "").lstrip("+")
    # Trailing period is sentence punctuation, not a decimal point.
    s = s.rstrip(".")
    if not s or s in {"-", "+"}:
        return ""
    try:
        val = float(s)
    except ValueError:
        return ""
    # Render integers without a trailing .0 so "42" == "42.0".
    if val == int(val):
        return str(int(val))
    return repr(round(val, 6))


def extract_number(text: str) -> str:
    """Best-effort final numeric answer from a free-form response."""
    if not text:
        return ""

    # 1. \boxed{...} wins outright when present.
    boxed = _BOXED.findall(text)
    if boxed:
        nums = _NUMBER.findall(boxed[-1])
        if nums:
            return _clean_number(nums[-1])

    # 2. The LAST explicit "answer is ..." marker. Last, not first: models
    #    often restate the question ("to find the answer, ...") before solving.
    best = ""
    for match in _ANSWER_LEAD.finditer(text):
        tail = text[match.end():match.end() + 120]
        nums = _NUMBER.findall(tail)
        if nums:
            best = _clean_number(nums[0])
    if best:
        return best

    # 3. Fall back to the last number anywhere. Weakest signal, but better
    #    than scoring a correct-but-unmarked answer as wrong.
    nums = _NUMBER.findall(text)
    return _clean_number(nums[-1]) if nums else ""


def extract_choice(text: str) -> str:
    """Best-effort multiple-choice letter from a free-form response."""
    if not text:
        return ""

    boxed = _BOXED.findall(text)
    if boxed:
        m = _CHOICE.search(boxed[-1])
        if m:
            return m.group(1).upper()

    for match in _ANSWER_LEAD.finditer(text):
        tail = text[match.end():match.end() + 40]
        m = _CHOICE.search(tail)
        if m:
            return m.group(1).upper()

    # Fall back to the last standalone letter in the response.
    matches = _CHOICE.findall(text)
    return matches[-1].upper() if matches else ""


def grade(response: str, *, grader: str, expected: str, required_terms: list[str] | None = None) -> tuple[bool, str]:
    """Grade one response. Returns ``(correct, extracted)``.

    ``extracted`` is recorded on the result so a failing case can be triaged
    as "model got it wrong" vs "extractor missed it" without re-running.
    """
    text = response or ""

    if grader == "numeric":
        got = extract_number(text)
        want = _clean_number(expected) or expected.strip()
        return (got != "" and got == want), got

    if grader == "mcq":
        got = extract_choice(text)
        return (got != "" and got == expected.strip().upper()), got

    if grader == "contains":
        terms = required_terms or ([expected] if expected else [])
        haystack = text.lower()
        missing = [t for t in terms if t.lower() not in haystack]
        got = "all terms" if not missing else f"missing: {', '.join(missing)}"
        return (not missing and bool(terms)), got

    raise ValueError(f"unknown grader: {grader!r}")
