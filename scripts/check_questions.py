#!/usr/bin/env python3
"""Report questions that learners' answers suggest are broken.

The validator proves a question is self-consistent and the key audit proves
the key does not contradict its own explanation. A key that is confidently,
uniformly wrong passes both — the passage reads well, the explanation matches
the option it names, and that option is simply not the right one.

Answers reveal it. A question almost nobody gets right is far more likely to
have a bad key than to be hard. This report says which ones to look at; it
does not decide, and nothing is withdrawn automatically.

Usage:
    python scripts/check_questions.py            # questions with 5+ answers
    python scripts/check_questions.py 3          # lower the threshold
Exits 0 when nothing is flagged.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config  # noqa: E402
from app.db import Database  # noqa: E402
from app.services import content, telemetry  # noqa: E402


async def main() -> int:
    minimum = int(sys.argv[1]) if len(sys.argv) > 1 else telemetry.MIN_ATTEMPTS
    db = Database(load_config().db_path)
    await db.init()

    stats = await db.question_stats(min_attempts=1)
    if not stats:
        print("No answers recorded yet — nothing to judge.")
        return 0

    answered = sum(row["attempts"] for row in stats)
    ready = [row for row in stats if row["attempts"] >= minimum]
    print(f"{len(stats)} question(s) answered {answered} time(s) in total.")
    print(f"{len(ready)} have the {minimum}+ answers needed to say anything.\n")

    flags = telemetry.flag(stats, min_attempts=minimum)
    if not flags:
        print("Nothing looks broken.")
        return 0

    suspect = [f for f in flags if f.suspect_key]
    if suspect:
        print("⚠️  Probably a wrong answer key — check these first:\n")
        for item in suspect:
            print(f"  {item.describe()}")
            _show(item)
        print()

    trivial = [f for f in flags if not f.suspect_key]
    if trivial:
        print("Everyone answers these correctly, so they measure nothing:\n")
        for item in trivial:
            print(f"  {item.describe()}")

    return 1


def _show(flag: telemetry.Flag) -> None:
    """Print the question itself, so the report can be acted on directly."""
    exercise = content.get_exercise(flag.section, flag.exercise_id)
    if exercise is None:
        print("      (the exercise is no longer in the bank)")
        return
    questions = exercise.get("questions") or []
    if flag.q_index >= len(questions):
        print("      (the exercise has changed since these answers)")
        return
    question = questions[flag.q_index]
    from app.services.grading import correct_answer_text

    print(f"      Q: {question.get('q', '')[:100]}")
    print(f"      keyed answer: {correct_answer_text(question)!r}")
    if question.get("explanation"):
        print(f"      explanation: {question['explanation'][:100]}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
