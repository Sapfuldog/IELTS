"""Answer checking, including the two ways it used to mark correct answers wrong."""
from __future__ import annotations

import pytest

from app.services.grading import (
    correct_answer_text,
    is_correct,
    normalize_choice,
    normalize_gap,
    numeric_form,
)


class TestChoices:
    def test_callback_underscores_are_folded(self):
        assert normalize_choice("NOT_GIVEN") == "NOT GIVEN"

    @pytest.mark.parametrize("given", ["TRUE", "true", " True "])
    def test_case_and_space_insensitive(self, given):
        assert is_correct({"type": "tf", "answer": "TRUE"}, given)

    def test_wrong_choice_fails(self):
        assert not is_correct({"type": "tfng", "answer": "TRUE"}, "NOT_GIVEN")


class TestMultipleChoice:
    def test_index_match(self):
        q = {"type": "mc", "options": ["a", "b"], "answer": 1}
        assert is_correct(q, "1")
        assert not is_correct(q, "0")

    def test_answer_text_lookup(self):
        q = {"type": "mc", "options": ["Rooftops", "Underground"], "answer": 0}
        assert correct_answer_text(q) == "Rooftops"


class TestGapPunctuation:
    """Generated content arrives with typographic punctuation the learner cannot type."""

    def test_non_breaking_hyphen_matches_plain(self):
        q = {"type": "gap", "answer": "water‑cooler"}
        assert is_correct(q, "water-cooler")

    def test_curly_apostrophe_matches_plain(self):
        q = {"type": "gap", "answer": "the manager’s office"}
        assert is_correct(q, "the manager's office")

    def test_case_and_surrounding_space(self):
        q = {"type": "gap", "answer": "library"}
        assert is_correct(q, "  LIBRARY ")

    def test_accept_variants(self):
        q = {"type": "gap", "answer": "underground", "accept": ["the tube", "metro"]}
        assert is_correct(q, "Metro")

    def test_wrong_word_still_fails(self):
        assert not is_correct({"type": "gap", "answer": "library"}, "museum")

    def test_normalize_collapses_whitespace(self):
        assert normalize_gap("  two   words ") == "two words"


class TestGapNumbers:
    """A key written as digits must accept words, and the other way round."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("five", "5"),
            ("twenty-five", "25"),
            ("forty two", "42"),
            ("two hundred", "200"),
            ("one thousand five hundred", "1500"),
            ("five books", "5 books"),
        ],
    )
    def test_spelled_numbers_become_digits(self, text, expected):
        assert numeric_form(text) == expected

    def test_ordinary_words_untouched(self):
        assert numeric_form("the library") == "the library"

    @pytest.mark.parametrize("typed", ["5", "five", "Five", " five "])
    def test_digit_key_accepts_words(self, typed):
        assert is_correct({"type": "gap", "answer": "5"}, typed)

    @pytest.mark.parametrize("typed", ["25", "twenty five", "twenty-five"])
    def test_word_key_accepts_digits(self, typed):
        assert is_correct({"type": "gap", "answer": "twenty-five"}, typed)

    def test_ordinal_is_not_a_cardinal(self):
        assert not is_correct({"type": "gap", "answer": "5"}, "fifth")

    def test_wrong_number_fails(self):
        assert not is_correct({"type": "gap", "answer": "twenty-five"}, "24")
