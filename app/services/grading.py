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

CHOICE_TYPES = {"tf", "tfng", "ynng"}
QUESTION_TYPES = {"mc", "gap"} | CHOICE_TYPES

CHOICE_LABELS: dict[str, tuple[str, ...]] = {
    "tf": ("TRUE", "FALSE"),
    "tfng": ("TRUE", "FALSE", "NOT GIVEN"),
    "ynng": ("YES", "NO", "NOT GIVEN"),
}


def normalize_choice(value: str) -> str:
    """Callback data carries NOT_GIVEN; questions store 'NOT GIVEN'."""
    return value.replace("_", " ").strip().upper()


def is_correct(question: dict, given: str) -> bool:
    qtype = question["type"]

    if qtype == "mc":
        return given.isdigit() and int(given) == question["answer"]

    if qtype in CHOICE_TYPES:
        return normalize_choice(given) == normalize_choice(str(question["answer"]))

    # gap fill: case-insensitive, plus any explicitly accepted variants
    accepted = {str(question["answer"]).lower().strip()}
    accepted.update(a.lower().strip() for a in question.get("accept", []))
    return given.lower().strip() in accepted


def correct_answer_text(question: dict) -> str:
    if question["type"] == "mc":
        return question["options"][question["answer"]]
    return str(question["answer"])
