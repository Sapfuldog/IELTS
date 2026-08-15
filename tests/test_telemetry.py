"""Flagging questions whose answers suggest a broken key.

The judgement being tested is restraint: a flag on a genuinely hard question
wastes someone's time reviewing it, and a threshold set on two answers would
flag half the bank.
"""
from __future__ import annotations

from app.services.telemetry import BROKEN_BELOW, MIN_ATTEMPTS, flag


def row(pass_rate, attempts=10, q_index=0, exercise_id="r1"):
    return {
        "section": "reading", "exercise_id": exercise_id, "q_index": q_index,
        "attempts": attempts, "correct": round(pass_rate * attempts),
        "pass_rate": pass_rate,
    }


class TestFlagging:
    def test_a_question_nobody_passes_is_flagged(self):
        flags = flag([row(0.0)])
        assert len(flags) == 1
        assert flags[0].suspect_key
        assert "key is wrong" in flags[0].reason

    def test_a_question_everybody_passes_is_flagged_differently(self):
        flags = flag([row(1.0)])
        assert len(flags) == 1
        assert not flags[0].suspect_key
        assert "distinguishes nobody" in flags[0].reason

    def test_a_merely_hard_question_is_left_alone(self):
        """Band 8 items are hard; hard is not broken."""
        assert flag([row(0.25)]) == []

    def test_an_ordinary_question_is_left_alone(self):
        assert flag([row(0.6)]) == []


class TestRestraint:
    def test_too_few_answers_says_nothing(self):
        """Two learners guessing wrong is noise, not evidence."""
        assert flag([row(0.0, attempts=MIN_ATTEMPTS - 1)]) == []

    def test_enough_answers_does(self):
        assert len(flag([row(0.0, attempts=MIN_ATTEMPTS)])) == 1

    def test_the_threshold_can_be_raised(self):
        assert flag([row(0.0, attempts=5)], min_attempts=20) == []


class TestOrdering:
    def test_the_worst_come_first(self):
        flags = flag([row(1.0, q_index=1), row(0.0, q_index=2)])
        assert flags[0].q_index == 2

    def test_the_boundary_counts_as_broken(self):
        assert flag([row(BROKEN_BELOW)])[0].suspect_key


class TestDescription:
    def test_it_names_the_question_and_the_evidence(self):
        text = flag([row(0.0, attempts=12, q_index=3)])[0].describe()
        assert "reading/r1 Q4" in text  # one-based for humans
        assert "12 answers" in text
