#!/usr/bin/env python3
"""Play through an exercise in the terminal — no Telegram token needed.

Uses exactly the same content files and grading logic as the bot, so it is a
genuine test of the exercise flow.

Usage:
    python scripts/demo.py                       # list everything available
    python scripts/demo.py reading r3            # play a Reading passage
    python scripts/demo.py listening l4          # play a Listening exercise
    python scripts/demo.py writing w3            # show a Writing task
    python scripts/demo.py speaking s6           # show a Speaking cue card
    python scripts/demo.py vocabulary v3         # flip through flashcards
    python scripts/demo.py reading r3 --auto     # non-interactive self-test
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import content  # noqa: E402
from app.services.grading import (  # noqa: E402
    CHOICE_LABELS,
    CHOICE_TYPES,
    correct_answer_text,
    is_correct,
)

SECTIONS = ("reading", "listening", "writing", "speaking", "vocabulary")
WRAP = 78


def wrap(text: str) -> str:
    out = []
    for para in text.split("\n"):
        out.append(textwrap.fill(para, WRAP) if para.strip() else "")
    return "\n".join(out)


def rule(char: str = "─") -> None:
    print(char * WRAP)


def list_all() -> None:
    print("\nAvailable exercises\n")
    for section in SECTIONS:
        items = content.get_all(section)
        print(f"  {section.upper()}  ({len(items)})")
        for ex in items:
            label = ex.get("title") or ex.get("topic") or ""
            extra = ""
            if section in ("reading", "listening"):
                extra = f" — {len(ex['questions'])} questions"
            elif section == "writing":
                extra = f" — Task {ex['task']}"
            elif section == "speaking":
                extra = f" — Part {ex['part']}"
            elif section == "vocabulary":
                extra = f" — {len(ex['cards'])} cards"
            print(f"    {ex['id']:<5} {label}{extra}")
        print()
    print("Run:  python scripts/demo.py <section> <id>\n")


def prompt_for(q: dict, auto: bool) -> str:
    """Return the learner's answer — or the correct one in --auto mode."""
    if auto:
        return str(q["answer"])

    if q["type"] == "mc":
        for i, opt in enumerate(q["options"]):
            print(f"    {chr(65 + i)}. {opt}")
        raw = input("\n  Your answer (A/B/C…): ").strip().upper()
        return str(ord(raw[0]) - 65) if raw[:1].isalpha() else raw
    if q["type"] in CHOICE_TYPES:
        labels = CHOICE_LABELS[q["type"]]
        print("    " + "  /  ".join(labels))
        return input("\n  Your answer: ").strip()
    return input("\n  Your answer: ").strip()


def show_translation(exercise: dict, auto: bool) -> None:
    """In the bot this sits behind a spoiler; the terminal asks before printing."""
    translation = exercise.get("translation")
    if not translation:
        return
    if not auto:
        input("  🇷🇺 (press Enter to show the translation, or Ctrl+C to skip) ")
        print("\n" + wrap(translation) + "\n")


def play_quiz(section: str, exercise: dict, auto: bool) -> int:
    rule("═")
    print(f"  {exercise['title']}  [{exercise.get('level', '')}]")
    rule("═")

    if section == "reading":
        print("\n" + wrap(exercise["passage"]) + "\n")
    else:
        print("\n🎧 TRANSCRIPT (hidden behind a spoiler in the bot):\n")
        print(wrap(exercise["audio_text"]) + "\n")
    show_translation(exercise, auto)

    correct = 0
    questions = exercise["questions"]
    for i, q in enumerate(questions, 1):
        rule()
        print(f"\n  Question {i}/{len(questions)}\n")
        print("  " + wrap(q["q"]).replace("\n", "\n  ") + "\n")
        given = prompt_for(q, auto)
        ok = is_correct(q, given)
        correct += ok
        print()
        if ok:
            print("  ✅ Correct!")
        else:
            print(f"  ❌ Not quite. Answer: {correct_answer_text(q)}")
        print("  💡 " + wrap(q["explanation"]).replace("\n", "\n     "))
        print()

    rule("═")
    pct = correct / len(questions) * 100
    print(f"  Score: {correct}/{len(questions)}  ({pct:.0f}%)")
    rule("═")
    return correct


def show_writing(task: dict) -> None:
    rule("═")
    print(f"  Writing Task {task['task']}: {task['title']}")
    print(f"  Minimum {task['min_words']} words")
    rule("═")
    print("\n" + wrap(task["prompt"]) + "\n")
    rule()
    print("\n  TIPS\n")
    for t in task["tips"]:
        print("  • " + wrap(t).replace("\n", "\n    "))
    print()


def show_speaking(ex: dict) -> None:
    rule("═")
    print(f"  Speaking Part {ex['part']}: {ex['topic']}")
    rule("═")
    print("\n" + wrap(ex["intro"]) + "\n")
    if ex.get("cue_card"):
        rule()
        print("\n  CUE CARD\n")
        print("  " + wrap(ex["cue_card"]).replace("\n", "\n  ") + "\n")
    rule()
    print("\n  QUESTIONS\n")
    for i, q in enumerate(ex["questions"], 1):
        print(f"  {i}. " + wrap(q).replace("\n", "\n     "))
    print()
    rule()
    print("\n  TIPS\n")
    for t in ex["tips"]:
        print("  • " + wrap(t).replace("\n", "\n    "))
    print()


def show_vocab(vset: dict, auto: bool) -> None:
    rule("═")
    print(f"  {vset['topic']}  ({len(vset['cards'])} cards)")
    rule("═")
    for i, card in enumerate(vset["cards"], 1):
        print(f"\n  🃏 {i}/{len(vset['cards'])}   {card['word']}")
        if not auto:
            input("     (press Enter to reveal) ")
        if card.get("translation"):
            print(f"     🇷🇺 {card['translation']}")
        print(f"     → {card['definition']}")
        print(f"     💬 {card['example']}")
    print()


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    auto = "--auto" in argv

    if len(args) < 2:
        list_all()
        return 0

    section, exercise_id = args[0], args[1]
    if section not in SECTIONS:
        print(f"Unknown section {section!r}. Choose from: {', '.join(SECTIONS)}")
        return 1

    exercise = content.get_exercise(section, exercise_id)
    if exercise is None:
        ids = ", ".join(e["id"] for e in content.get_all(section))
        print(f"No exercise {exercise_id!r} in {section}. Available: {ids}")
        return 1

    print()
    if section in ("reading", "listening"):
        correct = play_quiz(section, exercise, auto)
        if auto and correct != len(exercise["questions"]):
            print("\n❌ SELF-TEST FAILED: declared answers were not all graded correct.")
            return 1
    elif section == "writing":
        show_writing(exercise)
    elif section == "speaking":
        show_speaking(exercise)
    else:
        show_vocab(exercise, auto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
