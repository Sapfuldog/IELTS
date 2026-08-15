"""Voice answers: what is measured, and what is left as a judgement.

The model itself is not exercised here — loading it takes tens of seconds and
needs a download. What is testable without it is the part that decides how a
learner is treated: the measurements, and the honesty flag on a transcript the
recogniser was unsure about.
"""
from __future__ import annotations

from app.services.transcription import PAUSE_SECONDS, Transcript


class Segment:
    def __init__(self, start, end, text, avg_logprob=-0.2):
        self.start, self.end, self.text = start, end, text
        self.avg_logprob = avg_logprob


def measure(segments):
    from app.services.transcription import _measure

    return _measure(segments)


class TestMeasurements:
    def test_words_and_duration_are_taken_from_the_audio(self):
        t = measure([Segment(0.0, 6.0, "I live in a small town by the sea")])
        assert t.words == 9
        assert t.duration == 6.0

    def test_pace_is_words_per_minute(self):
        t = measure([Segment(0.0, 30.0, " ".join(["word"] * 60))])
        assert round(t.words_per_minute) == 120

    def test_a_long_gap_counts_as_hesitation(self):
        t = measure([Segment(0.0, 3.0, "First part"), Segment(6.0, 9.0, "second part")])
        assert t.long_pauses == 1
        assert t.longest_pause == 3.0

    def test_ordinary_phrasing_is_not_flagged(self):
        """Short gaps are sentence rhythm; counting them would flag fluent speakers."""
        gap = PAUSE_SECONDS / 2
        t = measure([Segment(0.0, 3.0, "First"), Segment(3.0 + gap, 6.0, "second")])
        assert t.long_pauses == 0

    def test_silence_produces_an_empty_transcript_not_a_crash(self):
        t = measure([])
        assert t.text == "" and t.duration == 0.0 and t.words_per_minute == 0.0


class TestHonesty:
    def test_a_confident_transcript_is_not_flagged(self):
        assert not measure([Segment(0.0, 5.0, "clear speech", -0.2)]).uncertain

    def test_a_doubtful_transcript_is_flagged(self):
        """Accented English is what the recogniser gets wrong and what this bot
        exists for, so the learner has to be told."""
        assert measure([Segment(0.0, 5.0, "unclear", -1.2)]).uncertain

    def test_observations_state_facts_without_a_verdict(self):
        notes = " ".join(measure([Segment(0.0, 10.0, "a b c d e")]).observations())
        assert "words per minute" in notes
        # No band, no praise, no criticism — those are the agent's job.
        for verdict in ("good", "poor", "band", "should"):
            assert verdict not in notes.lower()

    def test_pauses_are_reported_when_present(self):
        t = Transcript(text="x", duration=10, words=5, long_pauses=2, longest_pause=3.4)
        assert "2 pause(s)" in " ".join(t.observations())


class TestDeliveryEvidence:
    """What the marker is told about a recording it cannot hear."""

    def clear(self):
        return Transcript(text="x", duration=95, words=210, long_pauses=1,
                          longest_pause=2.0, confidence=-0.25)

    def unclear(self):
        return Transcript(text="x", duration=60, words=70, long_pauses=6,
                          longest_pause=5.0, confidence=-0.9)

    def test_clarity_is_reported(self):
        assert "easily recognised" in self.clear().delivery_evidence()
        assert "hard to make out" in self.unclear().delivery_evidence()

    def test_pace_is_reported(self):
        assert "natural" in self.clear().delivery_evidence()
        assert "very slow" in self.unclear().delivery_evidence()

    def test_hesitation_is_reported(self):
        assert "6 hesitation pause" in self.unclear().delivery_evidence()

    def test_it_says_what_it_is_not(self):
        """The marker never hears the audio, so it must not infer sounds."""
        assert "not a transcript of sounds" in self.clear().delivery_evidence()


class TestPronunciationCriterion:
    """The fourth criterion exists only when there is a recording behind it."""

    def _criteria(self, delivery):
        from app.services.agent import _SPEAKING_CRITERIA

        return _SPEAKING_CRITERIA + (["Pronunciation"] if delivery else [])

    def test_a_typed_answer_is_marked_on_three(self):
        assert "Pronunciation" not in self._criteria(None)

    def test_a_spoken_answer_is_marked_on_four(self):
        assert "Pronunciation" in self._criteria("evidence")

    async def test_the_agent_asks_for_pronunciation_only_with_audio(self, agent_config):
        from app.services.agent import TutorAgent

        seen = {}

        async def _ask(prompt, schema, max_tokens=4096):
            seen["criteria"] = list(schema["properties"]["criteria"]["properties"])
            seen["prompt"] = prompt
            return {
                "criteria": {c: 6.0 for c in seen["criteria"]},
                "comment": "", "comment_ru": "", "strengths": [], "strengths_ru": [],
                "improvements": [], "improvements_ru": [], "corrections": [],
            }

        agent = TutorAgent(agent_config)
        agent._ask = _ask
        task = {"part": 1, "questions": ["Q?"]}

        await agent.evaluate("speaking", task, "answer")
        assert "Pronunciation" not in seen["criteria"]

        await agent.evaluate("speaking", task, "answer", "Speech evidence: clear.")
        assert "Pronunciation" in seen["criteria"]
        assert "say nothing about individual sounds" in seen["prompt"]
