"""Every English string a learner is shown has a Russian version available.

This is an audit turned into a rule. Coverage was complete once, by hand;
without a test the next set added slips through untranslated, and nobody
notices because the bot works perfectly well in English.

Russian is always behind a spoiler or a tap — a learner shown the translation
unasked never practises reading the English.
"""
from __future__ import annotations

import pytest

from app.services import content

QUIZ = ("reading", "listening")


class TestQuizSections:
    @pytest.mark.parametrize("section", QUIZ)
    def test_every_passage_is_translated(self, section):
        missing = [e["id"] for e in content.get_all(section) if not e.get("translation")]
        assert missing == [], f"no translation: {missing}"


class TestSpeaking:
    def test_every_intro_is_translated(self):
        missing = [e["id"] for e in content.get_all("speaking") if not e.get("intro_ru")]
        assert missing == [], f"no intro_ru: {missing}"

    def test_tips_are_translated_one_for_one(self):
        """A mismatch silently pairs a tip with the wrong translation."""
        wrong = [
            e["id"]
            for e in content.get_all("speaking")
            if len(e.get("tips_ru") or []) != len(e.get("tips") or [])
        ]
        assert wrong == [], f"tips_ru does not match tips: {wrong}"

    def test_questions_are_translated_one_for_one(self):
        wrong = [
            e["id"]
            for e in content.get_all("speaking")
            if len(e.get("questions_translation") or []) != len(e.get("questions") or [])
        ]
        assert wrong == [], f"questions_translation mismatch: {wrong}"

    def test_a_cue_card_is_translated_when_present(self):
        missing = [
            e["id"]
            for e in content.get_all("speaking")
            if e.get("cue_card") and not e.get("cue_card_translation")
        ]
        assert missing == [], f"cue card without translation: {missing}"


class TestWriting:
    def test_every_task_is_translated(self):
        missing = [e["id"] for e in content.get_all("writing") if not e.get("translation")]
        assert missing == [], f"no translation: {missing}"

    def test_the_question_is_translated_when_present(self):
        missing = [
            e["id"]
            for e in content.get_all("writing")
            if e.get("question") and not e.get("question_ru")
        ]
        assert missing == [], f"question without question_ru: {missing}"

    def test_must_cover_is_translated_one_for_one(self):
        wrong = [
            e["id"]
            for e in content.get_all("writing")
            if e.get("must_cover")
            and len(e.get("must_cover_ru") or []) != len(e["must_cover"])
        ]
        assert wrong == [], f"must_cover_ru mismatch: {wrong}"


class TestVocabulary:
    def test_every_card_is_translated(self):
        missing = [
            f"{deck['id']}/{card['word']}"
            for deck in content.get_all("vocabulary")
            for card in deck.get("cards", [])
            if not card.get("translation")
        ]
        assert missing == [], f"cards without a translation: {missing[:5]}"
