#!/usr/bin/env python3
"""Fill the exercise bank up to a target size.

The mock test assembles a section towards 40 questions, but can only use what
the bank holds. This tops it up so a sitting is the length of a real paper —
and it is the manual form of the scheduled generation in sprint 5.1, so what
is learned here about pacing and rejection rates carries over.

Nothing is saved unless it passes the same validation the bot applies, plus
the key audit. A run that produces nothing is a normal outcome, not a failure.

Usage:
    python scripts/top_up_bank.py                 # top up reading and listening
    python scripts/top_up_bank.py reading 40      # one section, explicit target
Exits 0 if every section reached its target.
"""
from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_config  # noqa: E402
from app.services import content  # noqa: E402
from app.services.agent import TutorAgent  # noqa: E402
from app.services.validation import validate_exercise  # noqa: E402

TOPICS = [
    "urban transport", "renewable energy", "the history of writing",
    "sleep and memory", "ocean plastics", "remote work", "food security",
    "museums and heritage", "language learning", "volcanoes",
    "the gig economy", "urban beekeeping", "space debris", "coffee growing",
    "public libraries", "migration of birds", "ancient roads", "vertical farming",
]

# Give up on a section after this many failures in a row: a model that cannot
# produce a usable exercise now will not start halfway through the run.
MAX_CONSECUTIVE_FAILURES = 3


def questions_in(section: str) -> int:
    """How much a section holds: questions, or cards for vocabulary."""
    key = "cards" if section == "vocabulary" else "questions"
    return sum(len(e.get(key, [])) for e in content.get_all(section))


async def top_up(agent: TutorAgent, section: str, target: int) -> bool:
    have = questions_in(section)
    unit = "cards" if section == "vocabulary" else "questions"
    print(f"\n{section}: {have} {unit}, target {target}")
    if have >= target:
        print("  already there")
        return True

    failures = 0
    while have < target and failures < MAX_CONSECUTIVE_FAILURES:
        topic = random.choice(TOPICS)
        # Grammar coverage is driven by the syllabus rather than left to
        # chance: drawing topics at random leaves whole areas untouched while
        # repeating others, and a learner cannot tell what they have not met.
        point = random.choice(content.grammar_syllabus())
        print(f"  writing one on {topic!r} ({point['topic']})…", end=" ", flush=True)
        exercise = await agent.generate(
            section, topic=topic, questions=6,
            target_band=point["band"], grammar=point,
        )

        if exercise is None:
            failures += 1
            print(f"rejected ({failures}/{MAX_CONSECUTIVE_FAILURES})")
            continue

        problems = validate_exercise(section, exercise)
        if problems:
            # generate() already validates, so this only fires if the two ever
            # disagree — worth knowing about rather than silently trusting.
            failures += 1
            print(f"failed a second check: {problems[0]}")
            continue

        content.add_generated(section, exercise)
        failures = 0
        key = "cards" if section == "vocabulary" else "questions"
        added = len(exercise.get(key, []))
        have = questions_in(section)
        name = exercise.get("title") or exercise.get("topic") or exercise["id"]
        print(f"ok — {name[:45]!r} (+{added}, now {have})")

    reached = have >= target
    print(f"  {'reached' if reached else 'stopped at'} {have}/{target}")
    return reached


async def main() -> int:
    args = sys.argv[1:]
    sections = [args[0]] if args else ["listening", "reading", "vocabulary"]
    default_target = {"vocabulary": 120}
    target = int(args[1]) if len(args) > 1 else None

    agent = TutorAgent(load_config())
    if not agent.available:
        print("No API key configured — nothing to generate with.")
        return 1

    results = [
        await top_up(agent, section, target or default_target.get(section, 40))
        for section in sections
    ]
    print()
    for section in sections:
        total, generated = content.count(section)
        unit = "cards" if section == "vocabulary" else "questions"
        print(f"{section:<11} {total} sets ({generated} generated), "
              f"{questions_in(section)} {unit}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
