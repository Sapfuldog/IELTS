"""Content validation, including every shape that once reached production broken."""
from __future__ import annotations

import pytest

from app.services import content
from app.services.validation import (
    check_key_against_explanation,
    validate_exercise,
    validate_question,
)

SECTIONS = ("reading", "listening", "writing", "speaking", "vocabulary")


class TestShippedContent:
    @pytest.mark.parametrize("section", SECTIONS)
    def test_everything_shipped_is_valid(self, section):
        for exercise in content.get_all(section):
            problems = validate_exercise(section, exercise)
            assert problems == [], f"{exercise.get('id')}: {problems}"


class TestQuestions:
    def test_valid_question_passes(self):
        q = {
            "type": "mc",
            "q": "Where?",
            "options": ["Rooftops", "Underground"],
            "answer": 0,
            "explanation": "The passage says rooftops.",
        }
        assert validate_question(q) == []

    def test_index_out_of_range(self):
        q = {
            "type": "mc", "q": "Where?", "options": ["a", "b"], "answer": 5,
            "explanation": "e",
        }
        assert any("out of range" in p for p in validate_question(q))

    def test_unknown_type(self):
        assert any("unknown type" in p for p in validate_question({"type": "essay"}))

    def test_choice_label_must_be_legal(self):
        q = {"type": "tf", "q": "?", "answer": "MAYBE", "explanation": "e"}
        assert any("must be one of" in p for p in validate_question(q))

    def test_explanation_required(self):
        q = {"type": "gap", "q": "?", "answer": "x", "accept": []}
        assert any("explanation" in p for p in validate_question(q))


class TestKeyAudit:
    """The off-by-one that shipped: a key self-consistent but factually wrong."""

    def test_flags_key_contradicting_its_explanation(self):
        q = {
            "type": "mc",
            "q": "Which is a benefit?",
            "options": [
                "It eliminates any warm-up.",
                "It can increase VO2 max in sedentary adults.",
                "It suits individuals with severe heart disease.",
            ],
            "answer": 2,
            "explanation": "The passage states it can increase VO2 max in sedentary adults.",
        }
        assert "the answer index looks wrong" in check_key_against_explanation(q)

    def test_accepts_a_key_its_explanation_supports(self):
        q = {
            "type": "mc",
            "q": "Which is a benefit?",
            "options": ["Warm-up removed", "Increases VO2 max"],
            "answer": 1,
            "explanation": "The passage says it increases VO2 max.",
        }
        assert check_key_against_explanation(q) is None

    def test_silent_without_an_explanation(self):
        q = {"type": "mc", "options": ["a", "b"], "answer": 0, "explanation": ""}
        assert check_key_against_explanation(q) is None


class TestSpeakingShape:
    """`intro` missing and `tips` as a string both crashed the handler."""

    def test_intro_is_required(self):
        ex = {
            "id": "s1", "topic": "Hometown", "part": 1, "questions": ["Q?"],
            "tips": ["Give reasons."],
        }
        assert any("intro" in p for p in validate_exercise("speaking", ex))

    def test_tips_must_be_a_list(self):
        ex = {
            "id": "s1", "topic": "Hometown", "part": 1, "intro": "Short interview.",
            "questions": ["Q?"], "tips": "One long blob.",
        }
        assert any("must be a list" in p for p in validate_exercise("speaking", ex))

    def test_translation_length_must_match(self):
        ex = {
            "id": "s1", "topic": "T", "part": 1, "intro": "i",
            "questions": ["a", "b"], "questions_translation": ["а"],
            "tips": ["t"],
        }
        assert any("match the question count" in p for p in validate_exercise("speaking", ex))


class TestWritingShape:
    def test_tips_must_be_a_list(self):
        ex = {
            "id": "w1", "title": "T", "prompt": "P", "min_words": 250,
            "task": 2, "tips": "blob",
        }
        assert any("must be a list" in p for p in validate_exercise("writing", ex))

    def test_task_must_be_one_or_two(self):
        ex = {
            "id": "w1", "title": "T", "prompt": "P", "min_words": 250,
            "task": 3, "tips": ["t"],
        }
        assert any("must be 1 or 2" in p for p in validate_exercise("writing", ex))
