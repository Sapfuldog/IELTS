"""Score conversion. Every case here corresponds to a published IELTS rule."""
from __future__ import annotations

import pytest

from app.services import banding


class TestRounding:
    """IELTS rounds .25 up to .5 and .75 up to the next whole band."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (6.0, 6.0),
            (6.125, 6.0),
            (6.25, 6.5),   # the rule that Python's round() gets wrong
            (6.4, 6.5),
            (6.5, 6.5),
            (6.75, 7.0),   # and this one
            (6.9, 7.0),
            (8.875, 9.0),
            (9.0, 9.0),
        ],
    )
    def test_half_band_rounding(self, raw, expected):
        assert banding.round_band(raw) == expected

    def test_never_exceeds_nine(self):
        assert banding.round_band(12.0) == 9.0

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            banding.round_band(-1.0)


class TestRawToBand:
    @pytest.mark.parametrize(
        "correct,listening,reading",
        [(40, 9.0, 9.0), (35, 8.0, 8.0), (30, 7.0, 7.0), (23, 6.0, 6.0)],
    )
    def test_full_paper(self, correct, listening, reading):
        assert banding.raw_to_band("listening", correct) == listening
        assert banding.raw_to_band("reading", correct) == reading

    def test_tables_differ(self):
        """Listening and Reading are not the same table — 15/40 splits them."""
        assert banding.raw_to_band("listening", 15) == 4.5
        assert banding.raw_to_band("reading", 15) == 5.0

    def test_short_set_is_scaled(self):
        assert banding.raw_to_band("listening", 4, 4) == 9.0
        assert banding.raw_to_band("listening", 3, 4) == 7.0

    def test_zero_and_clamping(self):
        assert banding.raw_to_band("reading", 0, 10) == 0.0
        assert banding.raw_to_band("reading", 99, 10) == 9.0

    def test_unscored_section_rejected(self):
        with pytest.raises(ValueError):
            banding.raw_to_band("writing", 5, 10)

    def test_zero_total_rejected(self):
        with pytest.raises(ValueError):
            banding.raw_to_band("reading", 0, 0)


class TestOverall:
    def test_average_then_round(self):
        bands = {"listening": 6.5, "reading": 6.0, "writing": 5.5, "speaking": 6.0}
        assert banding.overall_band(bands) == 6.0

    def test_quarter_rounds_up(self):
        assert banding.overall_band({"a": 6.5, "b": 6.0, "c": 6.0, "d": 6.5}) == 6.5

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            banding.overall_band({})


class TestDescribe:
    """A band takes the label of the whole band below it, per the official scale."""

    @pytest.mark.parametrize(
        "band,word",
        [
            (9.0, "Expert"),
            (8.0, "Very good"),
            (7.5, "Good"),
            (7.0, "Good"),
            (6.5, "Competent"),
            (6.0, "Competent"),
            (5.0, "Modest"),
            (4.5, "Limited"),
            (4.0, "Limited"),      # regression: was labelled "Extremely limited"
            (3.0, "Extremely limited"),
            (2.0, "Intermittent"),
        ],
    )
    def test_official_labels(self, band, word):
        assert banding.describe(band).startswith(word)
