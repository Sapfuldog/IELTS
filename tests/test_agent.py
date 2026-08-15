"""The agent, with the network stubbed out at `_ask`.

Nothing here may reach OpenRouter or Anthropic: `agent_config` carries a fake
key so `available` is True, and every test replaces `_ask` before calling in.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.services.agent import Evaluation, TutorAgent

BROKEN = {
    "title": "Night Shifts",
    "level": "B2",
    "passage": "Working nights disrupts the body clock.",
    "translation": "Ночная работа сбивает биоритмы.",
    "questions": [
        {
            "type": "mc",
            "q": "What is disrupted?",
            "options": ["The body clock", "The weather"],
            "answer": "Nothing at all",  # matches no option
            "explanation": "The passage says the body clock.",
        }
    ],
}
FIXED = {
    **BROKEN,
    "questions": [{**BROKEN["questions"][0], "answer": "The body clock"}],
}


def stub(agent: TutorAgent, *payloads):
    """Return each payload in turn, recording the prompts it was asked with."""
    calls: list[str] = []

    async def _ask(prompt, schema, max_tokens=4096):
        calls.append(prompt)
        return payloads[min(len(calls) - 1, len(payloads) - 1)]

    agent._ask = _ask
    return calls


class TestAvailability:
    def test_no_key_means_unavailable(self, offline_config):
        assert TutorAgent(offline_config).available is False

    async def test_generate_returns_none_without_a_key(self, offline_config):
        assert await TutorAgent(offline_config).generate("reading") is None

    async def test_evaluate_returns_none_without_a_key(self, offline_config):
        assert await TutorAgent(offline_config).evaluate("writing", {}, "text") is None


class TestAnswerResolution:
    """Asked for an index the model answers 1-based; asking for text avoids it."""

    def test_option_text_becomes_an_index(self):
        ex = {
            "questions": [
                {"type": "mc", "options": ["A) Twin", "B) Double"], "answer": "Double"}
            ]
        }
        TutorAgent._clean_options(ex)
        assert ex["questions"][0]["options"] == ["Twin", "Double"]
        assert ex["questions"][0]["answer"] == 1

    def test_a_bare_letter_is_understood(self):
        ex = {"questions": [{"type": "mc", "options": ["Yes", "No"], "answer": "B"}]}
        TutorAgent._clean_options(ex)
        assert ex["questions"][0]["answer"] == 1

    def test_unmatched_answer_is_left_alone_to_fail_validation(self):
        ex = {"questions": [{"type": "mc", "options": ["Yes", "No"], "answer": "Maybe"}]}
        TutorAgent._clean_options(ex)
        assert ex["questions"][0]["answer"] == "Maybe"

    def test_speaking_questions_are_strings_not_objects(self):
        """This shape crashed _clean_options and killed speaking generation."""
        ex = {"questions": ["Where is your hometown?", "What is it like?"]}
        TutorAgent._clean_options(ex)  # must not raise
        assert ex["questions"][0].startswith("Where")


class TestSelfCorrection:
    async def test_bad_generation_is_retried_with_the_real_reason(self, agent_config):
        agent = TutorAgent(agent_config)
        calls = stub(agent, BROKEN, FIXED)

        exercise = await agent.generate("reading", topic="shift work")

        assert len(calls) == 2, "a rejected exercise must be retried"
        assert exercise is not None
        assert exercise["questions"][0]["answer"] == 0
        assert "rejected by the validator" in calls[1]
        assert "mc answer must be an integer index" in calls[1]

    async def test_gives_up_rather_than_storing_a_bad_exercise(self, agent_config):
        agent = TutorAgent(agent_config)
        calls = stub(agent, BROKEN)

        assert await agent.generate("reading") is None
        assert len(calls) == 2, "it should use every attempt before giving up"

    async def test_generated_exercise_is_marked_and_identified(self, agent_config):
        agent = TutorAgent(agent_config)
        stub(agent, FIXED)
        exercise = await agent.generate("reading")
        assert exercise["generated"] is True
        assert exercise["id"].startswith("gen-r")


class TestMarking:
    async def test_criteria_are_averaged_and_rounded(self, agent_config):
        agent = TutorAgent(agent_config)
        stub(agent, {
            "criteria": {
                "Task Achievement": 6.0,
                "Coherence and Cohesion": 7.0,
                "Lexical Resource": 6.5,
                "Grammatical Range and Accuracy": 6.5,
            },
            "comment": "Solid.", "comment_ru": "Неплохо.",
            "strengths": ["Clear position"], "strengths_ru": ["Чёткая позиция"],
            "improvements": ["Vary sentences"], "improvements_ru": ["Разнообразьте"],
        })
        result = await agent.evaluate("writing", {"task": 2, "prompt": "p"}, "essay")
        assert result.band == 6.5
        assert result.criteria["Coherence and Cohesion"] == 7.0

    async def test_speaking_is_not_marked_on_pronunciation(self, agent_config):
        """Answers are typed, so a pronunciation band would be invented."""
        agent = TutorAgent(agent_config)
        captured = {}

        async def _ask(prompt, schema, max_tokens=4096):
            captured["schema"] = schema
            captured["prompt"] = prompt
            return {
                "criteria": {
                    "Fluency and Coherence": 6.0,
                    "Lexical Resource": 6.0,
                    "Grammatical Range and Accuracy": 6.0,
                },
                "comment": "", "comment_ru": "",
                "strengths": [], "strengths_ru": [],
                "improvements": [], "improvements_ru": [],
            }

        agent._ask = _ask
        await agent.evaluate("speaking", {"part": 1, "questions": ["Q?"]}, "answer")
        assert "Pronunciation" not in captured["schema"]["properties"]["criteria"]["properties"]
        assert "Do not comment on pronunciation" in captured["prompt"]


class TestEvaluationRendering:
    def test_russian_sits_under_each_english_point(self):
        html = Evaluation(
            band=6.5,
            criteria={"Task Achievement": 6.5},
            strengths=["Clear position"],
            strengths_ru=["Чёткая позиция"],
            comment="Good.", comment_ru="Хорошо.",
        ).as_html()
        assert "Clear position" in html and "Чёткая позиция" in html

    def test_band_can_be_suppressed(self):
        """A band on a single short answer is noise, so per-answer feedback omits it."""
        evaluation = Evaluation(band=4.0, criteria={"Fluency and Coherence": 4.0},
                                improvements=["Add detail"])
        assert "Estimated band" not in evaluation.as_html(show_band=False)
        assert "Add detail" in evaluation.as_html(show_band=False)

    def test_html_is_escaped(self):
        html = Evaluation(band=6.0, comment="use <b> & co").as_html()
        assert "&lt;b&gt;" in html and "&amp;" in html


class TestRefusedAndEmptyAnswers:
    """A classifier can decline with HTTP 200 and no usable content."""

    async def test_a_refusal_is_not_treated_as_an_answer(self, agent_config):
        from app.services.agent import FeedbackUnavailable

        agent = TutorAgent(agent_config)

        class Response:
            stop_reason = "refusal"
            content = []

        async def _create(**kwargs):
            return Response()

        agent._client = type("C", (), {"messages": type("M", (), {"create": staticmethod(_create)})()})()
        agent._config = dataclasses.replace(
            agent_config, openrouter_api_key=None, anthropic_api_key="sk-ant-test"
        )
        with pytest.raises(FeedbackUnavailable):
            await agent._ask_anthropic("prompt", {}, 100)

    async def test_an_empty_reply_is_not_parsed_as_json(self, agent_config):
        from app.services.agent import FeedbackUnavailable

        agent = TutorAgent(agent_config)

        class Block:
            type = "text"
            text = "   "

        class Response:
            stop_reason = "end_turn"
            content = [Block()]

        async def _create(**kwargs):
            return Response()

        agent._client = type("C", (), {"messages": type("M", (), {"create": staticmethod(_create)})()})()
        agent._config = dataclasses.replace(
            agent_config, openrouter_api_key=None, anthropic_api_key="sk-ant-test"
        )
        with pytest.raises(FeedbackUnavailable):
            await agent._ask_anthropic("prompt", {}, 100)

    def test_marking_leaves_room_for_thinking(self):
        """max_tokens caps thinking plus reply, so a tight cap truncates."""
        from app.services.agent import MARKING_TOKENS

        assert MARKING_TOKENS >= 8000


class TestBandTargeting:
    """Generation can be aimed at a band, not just a CEFR level."""

    async def test_the_target_reaches_the_prompt_with_its_description(self, agent_config):
        agent = TutorAgent(agent_config)
        calls = stub(agent, FIXED)
        await agent.generate("reading", target_band=8)
        assert "band 8" in calls[0]
        assert "inference across paragraphs" in calls[0]

    async def test_bands_ask_for_different_material(self, agent_config):
        agent = TutorAgent(agent_config)
        easy = stub(agent, FIXED)
        await agent.generate("reading", target_band=5)
        agent2 = TutorAgent(agent_config)
        hard = stub(agent2, FIXED)
        await agent2.generate("reading", target_band=8)
        assert easy[0] != hard[0]
        assert "word for word" in easy[0]

    async def test_no_target_leaves_the_prompt_alone(self, agent_config):
        agent = TutorAgent(agent_config)
        calls = stub(agent, FIXED)
        await agent.generate("reading")
        assert "Pitch it at IELTS band" not in calls[0]

    async def test_speaking_is_not_band_targeted(self, agent_config):
        """Only the quiz sections have a passage whose difficulty can be aimed."""
        agent = TutorAgent(agent_config)
        calls = stub(agent, {
            "topic": "T", "part": 1, "intro": "i", "cue_card": "",
            "cue_card_translation": "", "questions": ["Q?"],
            "questions_translation": ["В?"], "tips": ["t"],
        })
        await agent.generate("speaking", target_band=8)
        assert "Pitch it at IELTS band" not in calls[0]
