"""Answer checking for quiz-style questions.

Kept free of aiogram imports so it can be reused by the Telegram handlers,
the content validator and the terminal demo alike.

Supported question types:
  mc    - multiple choice; `answer` is the index into `options`
  tf    - TRUE / FALSE
  tfng  - TRUE / FALSE / NOT GIVEN   (facts in the passage)
  ynng  - YES / NO / NOT GIVEN       (writer's views and claims)
  gap   - typed answer; `answer` plus optional `accept` list of variants
"""
from __future__ import annotations

import re

CHOICE_TYPES = {"tf", "tfng", "ynng"}
QUESTION_TYPES = {"mc", "gap", "multi"} | CHOICE_TYPES

# Real papers ask for these by letter ("Choose TWO letters, A-E"), so the
# answer is typed rather than tapped. A toggling keyboard would have to hold
# a partial selection in the FSM, in both the practice flow and the test.
MULTI_LETTERS = "ABCDEFGH"


def parse_multi(given: str, option_count: int) -> set[int] | None:
    """Read 'AC', 'a, c' or '1 3' as a set of option indices.

    Returns None when nothing recognisable was selected, which the grader
    treats as wrong rather than as an empty-and-therefore-matching answer.
    """
    picked: set[int] = set()
    for token in re.findall(r"[A-Za-z]|\d+", str(given)):
        if token.isdigit():
            index = int(token) - 1  # learners count from 1
        else:
            index = MULTI_LETTERS.find(token.upper())
        if not 0 <= index < option_count:
            return None
        picked.add(index)
    return picked or None

CHOICE_LABELS: dict[str, tuple[str, ...]] = {
    "tf": ("TRUE", "FALSE"),
    "tfng": ("TRUE", "FALSE", "NOT GIVEN"),
    "ynng": ("YES", "NO", "NOT GIVEN"),
}


def normalize_choice(value: str) -> str:
    """Callback data carries NOT_GIVEN; questions store 'NOT GIVEN'."""
    return value.replace("_", " ").strip().upper()


# Generated passages come back with typographic punctuation — non-breaking
# hyphens, curly quotes, ellipsis characters. A learner types the plain ASCII
# equivalent, so a gap answer of "water‑cooler" would never match "water-cooler"
# without folding these first.
_PUNCTUATION = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "‘": "'", "’": "'", "‛": "'",
    "“": '"', "”": '"',
    " ": " ", " ": " ", " ": " ",
})


def normalize_gap(value: str) -> str:
    """Fold case, punctuation and spacing so typed answers match fairly."""
    folded = str(value).translate(_PUNCTUATION).lower().strip()
    return " ".join(folded.split())


_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}


def _spoken_number(words: list[str]) -> int | None:
    """Read 'twenty-five' or 'two hundred and fifty' as an integer.

    Returns None for anything that is not purely a number, so ordinary words
    are left alone rather than being coerced into digits.
    """
    total = current = 0
    seen = False
    for word in words:
        if word == "and" and seen:
            continue
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word in _SCALES:
            scale = _SCALES[word]
            # 'hundred' multiplies what precedes it; 'thousand' closes a group.
            current = (current or 1) * scale
            if scale >= 1000:
                total += current
                current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def numeric_form(value: str) -> str:
    """Rewrite spelled-out numbers as digits: 'twenty-five' -> '25'.

    IELTS answer keys write quantities either way, and a learner who types
    'five' should not be marked wrong against an answer of '5'. Non-numeric
    text passes through untouched.
    """
    text = normalize_gap(value).replace("-", " ")
    parts = text.split()
    if not parts:
        return text

    out: list[str] = []
    run: list[str] = []
    for part in parts:
        if part in _UNITS or part in _TENS or part in _SCALES or (
            part == "and" and run
        ):
            run.append(part)
            continue
        if run:
            number = _spoken_number(run)
            out.append(str(number) if number is not None else " ".join(run))
            run = []
        out.append(part)
    if run:
        number = _spoken_number(run)
        out.append(str(number) if number is not None else " ".join(run))
    return " ".join(out)


def is_correct(question: dict, given: str) -> bool:
    qtype = question["type"]

    if qtype == "mc":
        return given.isdigit() and int(given) == question["answer"]

    if qtype == "multi":
        # All or nothing: a real paper gives no credit for one of two right.
        wanted = {int(i) for i in question["answer"]}
        return parse_multi(given, len(question.get("options", []))) == wanted

    if qtype in CHOICE_TYPES:
        return normalize_choice(given) == normalize_choice(str(question["answer"]))

    # gap fill: case- and punctuation-insensitive, plus accepted variants.
    # Numbers are compared in digit form so 'five' matches '5' either way round.
    variants = [question["answer"], *question.get("accept", [])]
    accepted = {normalize_gap(v) for v in variants}
    accepted.update(numeric_form(v) for v in variants)
    return normalize_gap(given) in accepted or numeric_form(given) in accepted


def correct_answer_text(question: dict) -> str:
    if question["type"] == "mc":
        return question["options"][question["answer"]]
    if question["type"] == "multi":
        options = question.get("options", [])
        return " + ".join(
            f"{MULTI_LETTERS[i]}. {options[i]}"
            for i in sorted(question["answer"])
            if i < len(options)
        )
    return str(question["answer"])
