#!/usr/bin/env python3
"""Validate every exercise file in app/content/.

Catches the mistakes that are easy to make when adding content by hand:
broken JSON, duplicate ids, answer indexes pointing outside the options list,
choice answers that aren't a legal label, missing fields.

Usage:  python scripts/validate_content.py
Exits 0 if everything is valid, 1 otherwise — so it works in CI too.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import content  # noqa: E402
from app.services.grading import (  # noqa: E402
    CHOICE_LABELS,
    CHOICE_TYPES,
    QUESTION_TYPES,
    is_correct,
    normalize_choice,
)

errors: list[str] = []
counts: dict[str, int] = {}
translated: dict[str, tuple[int, int]] = {}  # section -> (with translation, total)


def err(where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def check_translation(where: str, value, *, required_len: int | None = None) -> bool:
    """Translations are optional, but a present one must be usable."""
    if value is None:
        return False
    if required_len is not None:
        if not isinstance(value, list):
            err(where, "translation list expected")
            return False
        if len(value) != required_len:
            err(where, f"translation list has {len(value)} entries, expected {required_len}")
            return False
        if any(not str(v).strip() for v in value):
            err(where, "empty entry in translation list")
            return False
        return True
    if not str(value).strip():
        err(where, "translation is empty")
        return False
    return True


def check_questions(where: str, questions: list[dict]) -> int:
    for i, q in enumerate(questions, 1):
        loc = f"{where} Q{i}"
        qtype = q.get("type")
        if qtype not in QUESTION_TYPES:
            err(loc, f"unknown type {qtype!r} (allowed: {sorted(QUESTION_TYPES)})")
            continue
        if not q.get("q"):
            err(loc, "missing question text")
        if "answer" not in q:
            err(loc, "missing 'answer'")
            continue

        if qtype == "mc":
            options = q.get("options")
            if not isinstance(options, list) or len(options) < 2:
                err(loc, "multiple choice needs at least 2 options")
                continue
            if not isinstance(q["answer"], int):
                err(loc, "mc answer must be an integer index")
            elif not 0 <= q["answer"] < len(options):
                err(loc, f"answer index {q['answer']} out of range (0-{len(options) - 1})")
        elif qtype in CHOICE_TYPES:
            allowed = CHOICE_LABELS[qtype]
            if normalize_choice(str(q["answer"])) not in allowed:
                err(loc, f"answer {q['answer']!r} must be one of {allowed}")
        else:  # gap
            if not str(q["answer"]).strip():
                err(loc, "gap answer is empty")
            for variant in q.get("accept", []):
                if not str(variant).strip():
                    err(loc, "empty string in 'accept' list")

        if not q.get("explanation"):
            err(loc, "missing explanation (shown to the learner after answering)")

        # The stated correct answer must actually pass the grader.
        if qtype == "mc":
            probe = str(q["answer"])
        else:
            probe = str(q["answer"])
        if not is_correct(q, probe):
            err(loc, "the declared correct answer does not pass is_correct()")

    return len(questions)


def check_quiz_section(section: str) -> None:
    items = content.get_all(section)
    seen: set[str] = set()
    total_q = 0
    with_tr = 0
    for ex in items:
        eid = ex.get("id", "<no id>")
        where = f"{section}/{eid}"
        if eid in seen:
            err(where, "duplicate id")
        seen.add(eid)
        if not ex.get("title"):
            err(where, "missing title")
        body = "passage" if section == "reading" else "audio_text"
        if not ex.get(body):
            err(where, f"missing '{body}'")
        with_tr += check_translation(where, ex.get("translation"))
        questions = ex.get("questions")
        if not questions:
            err(where, "no questions")
            continue
        total_q += check_questions(where, questions)
    counts[section] = len(items)
    translated[section] = (with_tr, len(items))
    print(f"  {section:<11} {len(items)} exercises, {total_q} questions, {with_tr}/{len(items)} translated")


def check_writing() -> None:
    items = content.get_all("writing")
    seen: set[str] = set()
    with_tr = 0
    for ex in items:
        eid = ex.get("id", "<no id>")
        where = f"writing/{eid}"
        if eid in seen:
            err(where, "duplicate id")
        seen.add(eid)
        for field in ("title", "prompt", "min_words", "task"):
            if not ex.get(field):
                err(where, f"missing '{field}'")
        if ex.get("task") not in (1, 2):
            err(where, "'task' must be 1 or 2")
        if not ex.get("tips"):
            err(where, "missing tips")
        with_tr += check_translation(where, ex.get("translation"))
    counts["writing"] = len(items)
    translated["writing"] = (with_tr, len(items))
    print(f"  {'writing':<11} {len(items)} tasks, {with_tr}/{len(items)} translated")


def check_speaking() -> None:
    items = content.get_all("speaking")
    seen: set[str] = set()
    total_q = 0
    with_tr = 0
    for ex in items:
        eid = ex.get("id", "<no id>")
        where = f"speaking/{eid}"
        if eid in seen:
            err(where, "duplicate id")
        seen.add(eid)
        if ex.get("part") not in (1, 2, 3):
            err(where, "'part' must be 1, 2 or 3")
        if not ex.get("topic"):
            err(where, "missing topic")
        if not ex.get("questions"):
            err(where, "no questions")
        if ex.get("part") == 2 and not ex.get("cue_card"):
            err(where, "Part 2 sets need a cue_card")
        if not ex.get("tips"):
            err(where, "missing tips")
        n_q = len(ex.get("questions", []))
        total_q += n_q
        # Parallel list — a mismatch would silently mislabel questions.
        with_tr += check_translation(
            where, ex.get("questions_translation"), required_len=n_q
        )
        if ex.get("cue_card"):
            check_translation(f"{where} cue_card", ex.get("cue_card_translation"))
    counts["speaking"] = len(items)
    translated["speaking"] = (with_tr, len(items))
    print(f"  {'speaking':<11} {len(items)} sets, {total_q} prompts, {with_tr}/{len(items)} translated")


def check_vocabulary() -> None:
    items = content.get_all("vocabulary")
    seen: set[str] = set()
    total_cards = 0
    with_tr = 0
    for ex in items:
        eid = ex.get("id", "<no id>")
        where = f"vocabulary/{eid}"
        if eid in seen:
            err(where, "duplicate id")
        seen.add(eid)
        if not ex.get("topic"):
            err(where, "missing topic")
        cards = ex.get("cards") or []
        if not cards:
            err(where, "no cards")
        for j, card in enumerate(cards, 1):
            for field in ("word", "definition", "example"):
                if not card.get(field):
                    err(f"{where} card{j}", f"missing '{field}'")
            with_tr += check_translation(f"{where} card{j}", card.get("translation"))
        total_cards += len(cards)
    counts["vocabulary"] = len(items)
    translated["vocabulary"] = (with_tr, total_cards)
    print(f"  {'vocabulary':<11} {len(items)} decks, {total_cards} cards, {with_tr}/{total_cards} translated")


def main() -> int:
    print("Validating content…\n")
    for section in ("reading", "listening"):
        check_quiz_section(section)
    check_writing()
    check_speaking()
    check_vocabulary()

    print()
    if errors:
        print(f"❌ {len(errors)} problem(s) found:\n")
        for e in errors:
            print(f"  • {e}")
        return 1

    print(f"✅ All content valid — {sum(counts.values())} exercises across {len(counts)} sections.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
