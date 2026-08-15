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


class TestMultiSelectShape:
    BASE = {
        "type": "multi", "q": "Which TWO?",
        "options": ["a", "b", "c", "d"], "answer": [0, 2],
        "explanation": "e",
    }

    def test_a_valid_multi_passes(self):
        assert validate_question(self.BASE) == []

    def test_one_answer_is_not_a_multi_select(self):
        q = {**self.BASE, "answer": [1]}
        assert any("2+ indices" in p for p in validate_question(q))

    def test_a_repeated_option_is_rejected(self):
        q = {**self.BASE, "answer": [1, 1]}
        assert any("listed twice" in p for p in validate_question(q))

    def test_an_out_of_range_index_is_rejected(self):
        q = {**self.BASE, "answer": [0, 9]}
        assert any("out of range" in p for p in validate_question(q))

    def test_selecting_everything_is_not_a_question(self):
        q = {**self.BASE, "answer": [0, 1, 2, 3]}
        assert any("cannot be every option" in p for p in validate_question(q))

    def test_too_few_options_is_rejected(self):
        q = {**self.BASE, "options": ["a", "b"], "answer": [0, 1]}
        assert any("at least 3 options" in p for p in validate_question(q))


class TestWordBank:
    """"Complete the summary using the list below" — the list must be usable."""

    BASE = {
        "type": "gap", "q": "Fluid removes metabolic ____.",
        "answer": "waste", "accept": [], "explanation": "e",
        "bank": ["waste", "fuel", "oxygen", "protein"],
    }

    def test_a_valid_bank_passes(self):
        assert validate_question(self.BASE) == []

    def test_a_gap_without_a_bank_is_still_fine(self):
        q = {k: v for k, v in self.BASE.items() if k != "bank"}
        assert validate_question(q) == []

    def test_an_answer_outside_the_bank_is_rejected(self):
        """Otherwise the question cannot be answered as posed."""
        q = {**self.BASE, "answer": "rubbish"}
        assert any("not among the words offered" in p for p in validate_question(q))

    def test_the_answer_may_differ_in_case(self):
        q = {**self.BASE, "answer": "Waste"}
        assert validate_question(q) == []

    def test_too_short_a_bank_is_rejected(self):
        q = {**self.BASE, "bank": ["waste", "fuel"]}
        assert any("at least 3 words" in p for p in validate_question(q))

    def test_a_repeated_word_is_rejected(self):
        q = {**self.BASE, "bank": ["waste", "fuel", "fuel", "oxygen"]}
        assert any("repeats a word" in p for p in validate_question(q))

    def test_an_empty_entry_is_rejected(self):
        q = {**self.BASE, "bank": ["waste", "  ", "oxygen"]}
        assert any("empty entry" in p for p in validate_question(q))


class TestSharedOptionGroups:
    """A broken group reference marks the wrong option correct without crashing."""

    def make(self, **overrides):
        exercise = {
            "id": "r1", "title": "T", "passage": "p",
            "groups": [{
                "id": "headings", "prompt": "Choose a heading.",
                "options": ["Growth", "Costs", "History", "Future"],
                "exhaustive": True,
            }],
            "questions": [
                {"type": "match", "group": "headings", "q": "Paragraph A",
                 "answer": 0, "explanation": "e",
                 "options": ["Growth", "Costs", "History", "Future"]},
                {"type": "match", "group": "headings", "q": "Paragraph B",
                 "answer": 1, "explanation": "e",
                 "options": ["Growth", "Costs", "History", "Future"]},
            ],
        }
        exercise.update(overrides)
        return exercise

    def test_a_valid_group_passes(self):
        assert validate_exercise("reading", self.make()) == []

    def test_a_dangling_reference_is_caught(self):
        ex = self.make()
        ex["questions"][0]["group"] = "typo"
        assert any("unknown group" in p for p in validate_exercise("reading", ex))

    def test_an_unused_group_is_caught(self):
        """Almost always a typo in a question, not harmless dead weight."""
        ex = self.make()
        for q in ex["questions"]:
            q.pop("group")
        assert any("nothing refers to" in p for p in validate_exercise("reading", ex))

    def test_an_exhaustive_group_may_not_reuse_an_answer(self):
        ex = self.make()
        ex["questions"][1]["answer"] = 0
        assert any("reuses an answer" in p for p in validate_exercise("reading", ex))

    def test_a_non_exhaustive_group_may_reuse(self):
        ex = self.make()
        ex["groups"][0]["exhaustive"] = False
        ex["questions"][1]["answer"] = 0
        assert validate_exercise("reading", ex) == []

    def test_fewer_options_than_questions_is_caught(self):
        ex = self.make()
        ex["groups"][0]["options"] = ["Growth"]
        assert any("at least 3 options" in p for p in validate_exercise("reading", ex))

    def test_duplicate_group_ids_are_caught(self):
        ex = self.make()
        ex["groups"].append(dict(ex["groups"][0]))
        assert any("duplicate group id" in p for p in validate_exercise("reading", ex))

    def test_a_repeated_option_is_caught(self):
        ex = self.make()
        ex["groups"][0]["options"] = ["Growth", "Growth", "History", "Future"]
        assert any("repeats an option" in p for p in validate_exercise("reading", ex))

    def test_a_group_needs_a_prompt(self):
        ex = self.make()
        ex["groups"][0].pop("prompt")
        assert any("no prompt" in p for p in validate_exercise("reading", ex))

    def test_exercises_without_groups_are_untouched(self):
        ex = self.make()
        ex.pop("groups")
        for q in ex["questions"]:
            q.pop("group")
            q["type"] = "mc"
        assert validate_exercise("reading", ex) == []


class TestGroupExpansion:
    """Storing the list once must leave every question self-contained."""

    RAW = {
        "id": "r1", "title": "T", "passage": "p",
        "groups": [{
            "id": "people", "prompt": "Who said this?",
            "options": ["Dr Lee", "Prof Ito", "Ms Adams"],
        }],
        "questions": [
            {"type": "match", "group": "people", "q": "Statement 1",
             "answer": 2, "explanation": "e"},
            {"type": "match", "group": "people", "q": "Statement 2",
             "answer": 0, "explanation": "e"},
        ],
    }

    def expanded(self):
        import copy

        from app.services.content import expand_groups

        return expand_groups(copy.deepcopy(self.RAW))

    def test_options_reach_every_question(self):
        ex = self.expanded()
        assert all(q["options"] == ["Dr Lee", "Prof Ito", "Ms Adams"]
                   for q in ex["questions"])

    def test_only_the_first_question_carries_the_group_header(self):
        """The list is shown once, above the group, not before every question."""
        ex = self.expanded()
        assert "group_prompt" in ex["questions"][0]
        assert "group_prompt" not in ex["questions"][1]

    def test_an_expanded_exercise_validates_and_grades(self):
        from app.services.grading import correct_answer_text, is_correct

        ex = self.expanded()
        assert validate_exercise("reading", ex) == []
        assert is_correct(ex["questions"][0], "2")
        assert not is_correct(ex["questions"][0], "1")
        assert correct_answer_text(ex["questions"][0]) == "Ms Adams"

    def test_a_dangling_reference_leaves_the_question_alone(self):
        import copy

        from app.services.content import expand_groups

        raw = copy.deepcopy(self.RAW)
        raw["questions"][0]["group"] = "typo"
        ex = expand_groups(raw)
        assert "options" not in ex["questions"][0]  # the validator reports it


class TestTaskOneData:
    """Task 1 describes data the bot cannot draw, so the data must be in words."""

    def make(self, prompt, task=1):
        return {
            "id": "w1", "title": "T", "prompt": prompt, "min_words": 150,
            "task": task, "tips": ["t"],
        }

    def test_a_prompt_carrying_its_figures_passes(self):
        ex = self.make(
            "The table shows ownership.\nCar 52% 61% 64%\nTV 88% 94% 91%"
        )
        assert validate_exercise("writing", ex) == []

    def test_pointing_at_an_unseen_chart_is_rejected(self):
        ex = self.make("The chart below shows car ownership from 2000 to 2020.")
        assert any("cannot show" in p for p in validate_exercise("writing", ex))

    def test_a_letter_task_needs_no_figures(self):
        """General Training Task 1 is a letter — the rule must not fire."""
        ex = self.make(
            "You recently bought a laptop that arrived damaged. Write a letter "
            "to the shop explaining what happened."
        )
        assert validate_exercise("writing", ex) == []

    def test_task_two_is_never_checked_for_data(self):
        ex = self.make("Some people think the chart below is misleading.", task=2)
        ex["min_words"] = 250
        assert validate_exercise("writing", ex) == []

    def test_a_process_described_in_words_passes(self):
        ex = self.make(
            "The stages below describe water treatment.\n1. Intake\n2. Screening\n"
            "3. Sedimentation\n4. Filtration"
        )
        assert validate_exercise("writing", ex) == []
