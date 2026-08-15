"""Validate a single exercise against the rules every section relies on.

Lives here rather than in the validator script because two callers need it:
`scripts/validate_content.py` checks hand-written files, and the generator in
`app.services.agent` checks what the model produces before it is allowed into
the bank. A generated exercise has to clear exactly the same bar as one
written by hand — otherwise the bank slowly fills with plausible-looking
questions whose stated answer is wrong.

Every function returns a list of human-readable problems; empty means valid.
"""
from __future__ import annotations

import re

from app.services.grading import (
    CHOICE_LABELS,
    CHOICE_TYPES,
    QUESTION_TYPES,
    is_correct,
    normalize_choice,
)

# Words too common to say anything about which option an explanation means.
_NOISE = {
    "the", "a", "an", "of", "to", "in", "is", "are", "it", "that", "and",
    "for", "by", "as", "with", "can", "this", "passage", "text", "script",
    "states", "says", "mentions", "according", "answer", "correct", "because",
}


def _content_words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", str(text).lower())
        if word not in _NOISE and len(word) > 2
    }


def check_key_against_explanation(question: dict) -> str | None:
    """Catch a multiple-choice key that points at the wrong option.

    Everything else here checks that a question is *self-consistent*, which a
    key off by one position still is. The explanation, though, describes the
    right answer in words — so if the keyed option shares nothing with the
    explanation while another option does, the key is on the wrong line.
    Deliberately conservative: it only fires on zero overlap, because a
    borderline complaint on good content is worse than missing one.
    """
    options = question.get("options") or []
    answer = question.get("answer")
    if not isinstance(answer, int) or not 0 <= answer < len(options):
        return None
    explanation = _content_words(question.get("explanation", ""))
    if not explanation:
        return None

    overlaps = [len(_content_words(option) & explanation) for option in options]
    if overlaps[answer] > 0:
        return None
    best = max(range(len(overlaps)), key=overlaps.__getitem__)
    if overlaps[best] == 0:
        return None
    return (
        f"the key selects {options[answer]!r} but the explanation describes "
        f"{options[best]!r} — the answer index looks wrong"
    )

QUIZ_SECTIONS = {"reading": "passage", "listening": "audio_text"}


def validate_question(q: dict, where: str = "question") -> list[str]:
    problems: list[str] = []
    qtype = q.get("type")
    if qtype not in QUESTION_TYPES:
        return [f"{where}: unknown type {qtype!r} (allowed: {sorted(QUESTION_TYPES)})"]
    if not q.get("q"):
        problems.append(f"{where}: missing question text")
    if "answer" not in q:
        return problems + [f"{where}: missing 'answer'"]

    if qtype == "mc":
        options = q.get("options")
        if not isinstance(options, list) or len(options) < 2:
            return problems + [f"{where}: multiple choice needs at least 2 options"]
        if not isinstance(q["answer"], int):
            problems.append(f"{where}: mc answer must be an integer index")
        elif not 0 <= q["answer"] < len(options):
            problems.append(
                f"{where}: answer index {q['answer']} out of range (0-{len(options) - 1})"
            )
    elif qtype in CHOICE_TYPES:
        allowed = CHOICE_LABELS[qtype]
        if normalize_choice(str(q["answer"])) not in allowed:
            problems.append(f"{where}: answer {q['answer']!r} must be one of {allowed}")
    else:  # gap
        if not str(q["answer"]).strip():
            problems.append(f"{where}: gap answer is empty")
        for variant in q.get("accept", []):
            if not str(variant).strip():
                problems.append(f"{where}: empty string in 'accept' list")

    if not q.get("explanation"):
        problems.append(f"{where}: missing explanation (shown after answering)")

    # The load-bearing check: whatever the question calls correct must actually
    # be graded correct. A model that writes a good passage but an off-by-one
    # answer index fails here and nowhere else.
    if not problems and not is_correct(q, str(q["answer"])):
        problems.append(f"{where}: the declared correct answer does not pass is_correct()")

    if not problems:
        mismatch = check_key_against_explanation(q)
        if mismatch:
            problems.append(f"{where}: {mismatch}")

    return problems


def _check_tips(section: str, exercise: dict) -> list[str]:
    """Tips must be a list of strings — the handlers bullet them one by one.

    A single string passes a truthiness check but iterates character by
    character at render time, so the learner gets '• T', '• h', '• e'. Typing
    this here is what stops generated content from drifting from the shape the
    handwritten files use.
    """
    tips = exercise.get("tips")
    if tips is None:
        return []
    if isinstance(tips, str) or not isinstance(tips, list):
        return [f"{section}: 'tips' must be a list of strings, got {type(tips).__name__}"]
    return [
        f"{section}: empty entry in 'tips'"
        for tip in tips
        if not str(tip).strip()
    ]


def validate_exercise(section: str, exercise: dict) -> list[str]:
    """Check one exercise. Returns [] when it is safe to use."""
    problems: list[str] = []
    if not isinstance(exercise, dict):
        return [f"{section}: expected an object, got {type(exercise).__name__}"]
    if not exercise.get("id"):
        problems.append(f"{section}: missing id")

    if section in QUIZ_SECTIONS:
        body = QUIZ_SECTIONS[section]
        if not exercise.get("title"):
            problems.append(f"{section}: missing title")
        if not exercise.get(body):
            problems.append(f"{section}: missing '{body}'")
        questions = exercise.get("questions") or []
        if not questions:
            problems.append(f"{section}: no questions")
        for i, q in enumerate(questions, 1):
            problems += validate_question(q, f"{section} Q{i}")

    elif section == "writing":
        for field in ("title", "prompt", "min_words", "task", "tips"):
            if not exercise.get(field):
                problems.append(f"writing: missing '{field}'")
        if exercise.get("task") not in (1, 2):
            problems.append("writing: 'task' must be 1 or 2")
        problems += _check_tips("writing", exercise)

    elif section == "speaking":
        if exercise.get("part") not in (1, 2, 3):
            problems.append("speaking: 'part' must be 1, 2 or 3")
        # The handler indexes intro directly, so a missing one is a crash.
        for field in ("topic", "intro", "tips"):
            if not exercise.get(field):
                problems.append(f"speaking: missing '{field}'")
        problems += _check_tips("speaking", exercise)
        if not exercise.get("questions"):
            problems.append("speaking: no questions")
        if exercise.get("part") == 2 and not exercise.get("cue_card"):
            problems.append("speaking: Part 2 sets need a cue_card")
        translation = exercise.get("questions_translation")
        if translation is not None and len(translation) != len(exercise.get("questions", [])):
            problems.append("speaking: questions_translation must match the question count")

    elif section == "vocabulary":
        if not exercise.get("topic"):
            problems.append("vocabulary: missing topic")
        cards = exercise.get("cards") or []
        if not cards:
            problems.append("vocabulary: no cards")
        for j, card in enumerate(cards, 1):
            for field in ("word", "definition", "example"):
                if not card.get(field):
                    problems.append(f"vocabulary card{j}: missing '{field}'")

    else:
        problems.append(f"unknown section {section!r}")

    return problems
