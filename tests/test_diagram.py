"""Diagram layout and validation. The drawing itself is checked only for being
a real PNG — how it looks is not something a test can judge."""
from __future__ import annotations

import pytest

from app.services.diagram import PER_ROW, is_blank, layout, render
from app.services.validation import check_diagram

STEPS = ["Reservoir", "___1___", "Filtration", "___2___", "Chlorination", "Storage"]


class TestBlanks:
    @pytest.mark.parametrize("label", ["___1___", "__2__", "_10_"])
    def test_numbered_underscores_are_blanks(self, label):
        assert is_blank(label)

    @pytest.mark.parametrize("label", ["Reservoir", "___", "Stage 1", ""])
    def test_everything_else_is_not(self, label):
        assert not is_blank(label)


class TestLayout:
    def test_stages_wrap_instead_of_running_off_the_screen(self):
        placed, _ = layout(STEPS)
        rows = {p.top for p in placed}
        assert len(rows) == 2, "six stages should wrap onto two rows"

    def test_the_first_row_holds_the_row_limit(self):
        placed, _ = layout(STEPS)
        top = min(p.top for p in placed)
        assert sum(1 for p in placed if p.top == top) == PER_ROW

    def test_the_canvas_grows_with_the_rows(self):
        _, small = layout(STEPS[:3])
        _, large = layout(STEPS)
        assert large[1] > small[1]
        assert large[0] == small[0], "three across either way, so the same width"

    def test_a_single_stage_still_has_a_canvas(self):
        placed, (width, height) = layout(["Only"])
        assert len(placed) == 1 and width > 0 and height > 0

    def test_blanks_are_marked(self):
        placed, _ = layout(STEPS)
        assert [p.is_blank for p in placed] == [False, True, False, True, False, False]


class TestRendering:
    def test_a_real_png_comes_out(self):
        png = render("The water treatment process", STEPS)
        assert png is not None
        assert png[:4] == b"\x89PNG"
        assert len(png) > 1000

    def test_a_title_is_not_required(self):
        assert render("", STEPS) is not None


class TestValidation:
    def make(self, **overrides):
        exercise = {
            "diagram": {"title": "Water treatment", "steps": list(STEPS)},
            "questions": [
                {"type": "gap", "q": "1", "answer": "pump", "explanation": "e"},
                {"type": "gap", "q": "2", "answer": "tank", "explanation": "e"},
            ],
        }
        exercise.update(overrides)
        return exercise

    def test_a_valid_diagram_passes(self):
        assert check_diagram(self.make(), "reading") == []

    def test_no_diagram_is_not_a_problem(self):
        assert check_diagram({"questions": []}, "reading") == []

    def test_blanks_must_be_numbered_from_one(self):
        ex = self.make()
        ex["diagram"]["steps"] = ["A", "___2___", "B", "___3___", "C"]
        assert any("numbered 1.." in p for p in check_diagram(ex, "reading"))

    def test_a_diagram_with_no_blanks_is_pointless(self):
        ex = self.make()
        ex["diagram"]["steps"] = ["A", "B", "C"]
        assert any("no blanks" in p for p in check_diagram(ex, "reading"))

    def test_more_blanks_than_questions_is_caught(self):
        """A gap nobody asks about reads as a broken exercise."""
        ex = self.make()
        ex["questions"] = ex["questions"][:1]
        assert any("only 1 gap question" in p for p in check_diagram(ex, "reading"))

    def test_a_title_is_required(self):
        ex = self.make()
        ex["diagram"].pop("title")
        assert any("no title" in p for p in check_diagram(ex, "reading"))

    def test_too_few_steps_is_not_a_process(self):
        ex = self.make()
        ex["diagram"]["steps"] = ["A", "___1___"]
        assert any("at least 3 steps" in p for p in check_diagram(ex, "reading"))
