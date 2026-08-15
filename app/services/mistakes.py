"""Turn a learner's mistakes into flashcards.

Their own errors are the most useful study material they have, and until now
the bot showed them once and threw them away. Two sources feed in: gap answers
the grader marked wrong, and the corrections the agent returns after marking
Writing and Speaking.

Everything here is deliberately conservative about what counts as a mistake.
The grader still marks a defensible synonym wrong, and the model still
occasionally "corrects" something that was already right, so cards made here
are proposals the learner can dismiss — never verdicts.
"""
from __future__ import annotations

import logging

from app.db import Database
from app.services.grading import normalize_gap

logger = logging.getLogger(__name__)

# Below this a "mistake" is more likely a slip of the thumb than a gap in
# knowledge, and above it the answer is a sentence rather than a word worth
# studying as a card.
MIN_LENGTH = 2
MAX_WORDS = 4


def _worth_studying(answer: str) -> bool:
    text = answer.strip()
    if len(text) < MIN_LENGTH or len(text.split()) > MAX_WORDS:
        return False
    return any(ch.isalpha() for ch in text)


async def from_gap_answer(
    db: Database,
    user_id: int,
    question: dict,
    given: str,
    origin_id: str | None = None,
) -> bool:
    """Record a missed gap-fill answer as a card. True if one was created."""
    answer = str(question.get("answer", ""))
    if not _worth_studying(answer):
        return False
    # An empty or wildly different answer still teaches the target word, but a
    # blank one carries no information about what the learner thought.
    given = given.strip()
    if normalize_gap(given) == normalize_gap(answer):
        return False

    return await db.add_card(
        user_id,
        answer,
        source="gap",
        origin_id=origin_id,
        context=question.get("q"),
        example=question.get("explanation"),
        learner_answer=given or None,
    )


async def from_corrections(
    db: Database,
    user_id: int,
    corrections: list[dict],
    source: str,
    origin_id: str | None = None,
) -> int:
    """Record the agent's corrections as cards. Returns how many were new."""
    created = 0
    for item in corrections or []:
        right = str(item.get("right", "")).strip()
        wrong = str(item.get("wrong", "")).strip()
        if not right or not wrong or not _worth_studying(right):
            continue
        if normalize_gap(right) == normalize_gap(wrong):
            continue
        created += await db.add_card(
            user_id,
            right,
            source=source,
            origin_id=origin_id,
            definition=item.get("note") or None,
            translation=item.get("note_ru") or None,
            context=wrong,
            learner_answer=wrong,
        )
    if created:
        logger.info("Created %d card(s) from %s corrections", created, source)
    return created
