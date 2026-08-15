"""The tutor agent: writes new exercises and marks the open-ended ones.

Two jobs, one model, one place that talks to Claude:

* `generate` produces a new exercise for a section. What comes back is not
  trusted — it goes through `app.services.validation`, and if it fails the
  agent is told exactly what was wrong and gets one more attempt. That loop is
  the whole point: a model writing IELTS questions gets the passage right far
  more often than it gets every answer key right, and an exercise whose stated
  answer is wrong is worse than no exercise at all.
* `evaluate` marks Writing and Speaking against the band descriptors and
  returns per-criterion bands, so the result can be stored and averaged into a
  test score rather than being free text.

Without a working API key both fall back cleanly: `available` is False, and
callers use the static bank and the rule-based estimator instead.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from app.config import Config
from app.services.validation import validate_exercise

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

# A reading exercise carries a passage, a Russian translation and several
# questions with explanations; 4096 tokens is not enough and the truncated
# JSON fails to parse.
GENERATION_TOKENS = 24000
# max_tokens caps thinking *plus* the reply, and current models think by
# default, so a tight limit truncates the answer mid-sentence.
MARKING_TOKENS = 16000


class TruncatedResponse(RuntimeError):
    """The model ran out of output budget mid-JSON."""


class FeedbackUnavailable(RuntimeError):
    """The API answered, but with nothing usable to show the learner."""

# --- Response schemas -----------------------------------------------------
# Structured outputs need every object closed (`additionalProperties: false`)
# with all of its properties required, so optional fields are modelled as
# always-present-but-possibly-empty instead.

# The model states the correct option as text and the index is worked out
# here. Asked for an index directly it answers 1-based while the bot is
# 0-based, which silently marks the option after the right one as correct —
# an error nothing downstream can detect, because the key stays self-consistent.
_MC_QUESTION = {
    "type": "object",
    "properties": {
        "type": {"enum": ["mc"]},
        "q": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["type", "q", "options", "answer", "explanation"],
    "additionalProperties": False,
}

_CHOICE_QUESTION = {
    "type": "object",
    "properties": {
        "type": {"enum": ["tf", "tfng", "ynng"]},
        "q": {"type": "string"},
        "answer": {"enum": ["TRUE", "FALSE", "YES", "NO", "NOT GIVEN"]},
        "explanation": {"type": "string"},
    },
    "required": ["type", "q", "answer", "explanation"],
    "additionalProperties": False,
}

_GAP_QUESTION = {
    "type": "object",
    "properties": {
        "type": {"enum": ["gap"]},
        "q": {"type": "string"},
        "answer": {"type": "string"},
        "accept": {"type": "array", "items": {"type": "string"}},
        # Optional word bank: empty means the learner supplies the word from
        # the text, non-empty turns it into "choose from the list below".
        "bank": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["type", "q", "answer", "accept", "bank", "explanation"],
    "additionalProperties": False,
}

_MULTI_QUESTION = {
    "type": "object",
    "properties": {
        "type": {"enum": ["multi"]},
        "q": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        # Same reasoning as mc: the exact texts, never letters or numbers.
        "answer": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["type", "q", "options", "answer", "explanation"],
    "additionalProperties": False,
}

# Matching formats: the option list lives on the exercise and questions point
# at it by id. `answer` is again the option's exact text, resolved to an index
# by _resolve_answer once app.services.content has expanded the group.
_MATCH_QUESTION = {
    "type": "object",
    "properties": {
        "type": {"enum": ["match"]},
        "q": {"type": "string"},
        "group": {"type": "string"},
        "answer": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["type", "q", "group", "answer", "explanation"],
    "additionalProperties": False,
}

_GROUP = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "prompt": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        # True for headings — one per paragraph, no reuse.
        "exhaustive": {"type": "boolean"},
    },
    "required": ["id", "prompt", "options", "exhaustive"],
    "additionalProperties": False,
}

# A labelling diagram. Always present in the reply because structured outputs
# require every property; empty `steps` means the exercise simply has none.
_DIAGRAM = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "steps"],
    "additionalProperties": False,
}

_QUESTION = {
    "anyOf": [
        _MC_QUESTION, _CHOICE_QUESTION, _GAP_QUESTION, _MULTI_QUESTION,
        _MATCH_QUESTION,
    ]
}


def _quiz_schema(body_field: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "level": {"enum": ["A2", "B1", "B2", "C1"]},
            # Stored on the exercise so a test can assemble a spread of
            # difficulty rather than drawing uniformly at random.
            "target_band": {"enum": [5, 6, 7, 8]},
            body_field: {"type": "string"},
            "translation": {"type": "string"},
            "groups": {"type": "array", "items": _GROUP},
            "diagram": _DIAGRAM,
            "questions": {"type": "array", "items": _QUESTION},
        },
        "required": [
            "title", "level", "target_band", body_field, "translation",
            "groups", "diagram", "questions",
        ],
        "additionalProperties": False,
    }


_WRITING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "task": {"enum": [1, 2]},
        "prompt": {"type": "string"},
        "min_words": {"type": "integer"},
        # The handlers bullet these, so tips is a list, never one blob of text.
        "tips": {"type": "array", "items": {"type": "string"}},
        "translation": {"type": "string"},
    },
    "required": ["title", "task", "prompt", "min_words", "tips", "translation"],
    "additionalProperties": False,
}

_SPEAKING_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "part": {"enum": [1, 2, 3]},
        # `intro` is not optional: app/handlers/speaking.py indexes it directly.
        "intro": {"type": "string"},
        "cue_card": {"type": "string"},
        "cue_card_translation": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "questions_translation": {"type": "array", "items": {"type": "string"}},
        "tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "topic", "part", "intro", "cue_card", "cue_card_translation",
        "questions", "questions_translation", "tips",
    ],
    "additionalProperties": False,
}


_VOCABULARY_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "definition": {"type": "string"},
                    "example": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["word", "definition", "example", "translation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["topic", "cards"],
    "additionalProperties": False,
}

_SCHEMAS = {
    "reading": _quiz_schema("passage"),
    "listening": _quiz_schema("audio_text"),
    "writing": _WRITING_SCHEMA,
    "speaking": _SPEAKING_SCHEMA,
    "vocabulary": _VOCABULARY_SCHEMA,
}

_BRIEFS = {
    "reading": (
        "Write one IELTS Academic Reading practice exercise: a 220-320 word "
        "passage on {topic}, then {n} questions about it. Mix question types "
        "(mc, tfng, ynng, gap). Use 'tfng' only for factual statements and "
        "'ynng' only for the writer's views. Every answer must be decidable "
        "from the passage alone. For multiple choice, 'answer' is the exact "
        "text of the correct option, copied verbatim from your own options "
        "list — never a number or a letter.\n"
        "Include one 'multi' question (choose TWO of 4-5 options; 'answer' "
        "lists both correct option texts) and one 'gap' with a 'bank' of 4-6 "
        "candidate words, one of which is the answer. Leave 'bank' empty on "
        "any other gap question.\n"
        "Write the passage in clearly separated paragraphs and add a matching "
        "task: one entry in 'groups' with id 'headings', exhaustive true, and "
        "two more headings than there are paragraphs you ask about, then one "
        "'match' question per paragraph ('Paragraph A', 'Paragraph B', …) "
        "whose 'answer' is that heading's exact text. Every heading must be a "
        "plausible fit for some paragraph — headings nothing could match are "
        "not distractors, they are padding."
    ),
    "listening": (
        "Write one IELTS Listening practice exercise: a 150-250 word spoken "
        "script on {topic} (a conversation or short talk, written the way "
        "people actually speak, no stage directions), then {n} questions. Mix "
        "types (mc, tf, gap). Gap answers must be words said verbatim in the "
        "script. For multiple choice, 'answer' is the exact text of the "
        "correct option, copied verbatim from your own options list — never "
        "a number or a letter.\n"
        "If the topic involves a process or a route, add a labelling diagram: "
        "'diagram.steps' is 4-7 stages in order, of which 2-3 are blanks "
        "written exactly as '___1___', '___2___' numbered from 1, and each "
        "blank has a matching 'gap' question whose text starts with that "
        "number. Keep stage names under four words — they go inside a box. "
        "If the topic does not suit a diagram, leave 'title' empty and "
        "'steps' an empty list rather than inventing one.\n"
        "Leave 'groups' an empty list: matching headings needs paragraphs, "
        "which a spoken script does not have."
    ),
    "writing": (
        "Write one IELTS Writing task on {topic}. Task 1 describes visual "
        "data in at least 150 words; Task 2 argues a position in at least "
        "250 words. 'tips' is 2-3 separate pieces of concrete advice for "
        "this specific prompt, one per list entry."
    ),
    "vocabulary": (
        "Write one IELTS vocabulary deck of {n} words on {topic}. Draw from "
        "the Academic Word List where it fits the topic: these are the words "
        "that recur across academic writing, so they repay study more than "
        "topic-specific nouns. For each card give a short learner-friendly "
        "definition, one example sentence using the word naturally in an "
        "IELTS-like context, and a Russian translation of the word itself."
    ),
    "speaking": (
        "Write one IELTS Speaking question set on {topic}.\n"
        "'questions' must never be empty — it always holds {n} questions the "
        "examiner asks aloud, one per list entry, and "
        "'questions_translation' holds their Russian versions in the same "
        "order and the same number.\n"
        "Part 1: short personal questions. Part 2: put the task and its "
        "bullet points in 'cue_card', and put the examiner's follow-up "
        "questions in 'questions'. Part 3: abstract discussion questions.\n"
        "'intro' is one sentence telling the candidate what this part "
        "involves. 'tips' is 3 separate pieces of advice, one per list entry. "
        "Leave cue_card and cue_card_translation as empty strings unless this "
        "is Part 2."
    ),
}

# What actually separates a band 6 text from a band 8 one, so the brief can ask
# for a level instead of hoping the model picks one.
_BAND_GUIDANCE = {
    5: "everyday vocabulary and short simple sentences; answers stated almost "
       "word for word in the text",
    6: "some less common vocabulary and a mix of sentence lengths; answers "
       "stated clearly but paraphrased",
    7: "topic-specific and abstract vocabulary, longer sentences with "
       "subordinate clauses; answers require combining two statements",
    8: "dense academic register, idiomatic and figurative language; answers "
       "require inference across paragraphs and distinguishing close "
       "distractors",
}

_SYSTEM = (
    "You are an experienced IELTS materials writer. You produce practice "
    "content that is accurate, unambiguous and pitched at the requested CEFR "
    "level. Every question must have exactly one defensible answer that a "
    "careful candidate can find in the material you wrote. 'translation' "
    "fields are natural Russian renderings for a learner; keep the English "
    "and the Russian in step."
)


def _strip_label(option: str) -> str:
    """Drop an 'A)' or 'B.' prefix the model added; the keyboard letters them."""
    return re.sub(r"^\s*[A-Ea-e]\s*[\).\]]\s*", "", str(option)).strip()


def _resolve_answer(question: dict) -> int | str:
    """Turn the stated correct option into its index in `options`.

    Matching is done on the text, so the model's own numbering never enters
    into it. Anything that does not match a real option is returned unchanged
    and fails validation, which sends the exercise back for another attempt
    rather than storing a key that points at the wrong line.
    """
    answer = question.get("answer")
    options = question.get("options", [])

    if question.get("type") == "multi":
        # A list of option texts becomes a list of indices, same as mc.
        if not isinstance(answer, list):
            return answer
        return [_resolve_one(str(item), options) for item in answer]

    if isinstance(answer, int):
        return answer  # already an index; validation checks the range
    return _resolve_one(str(answer), options)


def _resolve_one(answer: str, options: list) -> int | str:
    """One option text (or bare letter) to its index, or the text unchanged."""

    wanted = _strip_label(str(answer)).casefold()
    for index, option in enumerate(options):
        if option.strip().casefold() == wanted:
            return index
    # A letter on its own ("B") is unambiguous even though it is not an option.
    if len(wanted) == 1 and "a" <= wanted <= "e":
        index = ord(wanted) - ord("a")
        if index < len(options):
            return index
    return str(answer)


@dataclass
class Evaluation:
    """A marked Writing or Speaking response."""

    band: float
    criteria: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    comment: str = ""
    strengths_ru: list[str] = field(default_factory=list)
    improvements_ru: list[str] = field(default_factory=list)
    comment_ru: str = ""
    # [{"wrong": ..., "right": ..., "note": ..., "note_ru": ...}] — becomes flashcards
    corrections: list[dict] = field(default_factory=list)

    def as_html(
        self,
        heading: str = "🤖 <b>Examiner feedback</b>",
        show_band: bool = True,
    ) -> str:
        """English first, Russian underneath each point where it exists.

        `show_band=False` keeps the advice and drops the number. A band
        describes sustained performance, so putting one on a single two-line
        answer reads as precision the mark does not have.
        """
        from app.formatting import esc

        def pairs(english: list[str], russian: list[str], marker: str) -> list[str]:
            out: list[str] = []
            for i, item in enumerate(english):
                out.append(f"{marker} {esc(item)}")
                if i < len(russian) and russian[i].strip():
                    out.append(f"    <i>{esc(russian[i])}</i>")
            return out

        lines = [heading]
        if show_band:
            lines += ["", f"<b>Estimated band: {self.band}</b>"]
            lines += [
                f"• {esc(name)}: <b>{value}</b>"
                for name, value in self.criteria.items()
            ]
        if self.comment:
            lines += ["", esc(self.comment)]
            if self.comment_ru:
                lines.append(f"<i>{esc(self.comment_ru)}</i>")
        if self.strengths:
            lines += ["", "<b>What worked / Что удалось</b>"]
            lines += pairs(self.strengths, self.strengths_ru, "✅")
        if self.improvements:
            lines += ["", "<b>What to fix next / Что исправить</b>"]
            lines += pairs(self.improvements, self.improvements_ru, "🔧")
        return "\n".join(lines)


_WRITING_CRITERIA = [
    "Task Achievement",
    "Coherence and Cohesion",
    "Lexical Resource",
    "Grammatical Range and Accuracy",
]
# Pronunciation is the fourth official Speaking criterion, but answers reach
# the bot as text. Asking for it anyway produced a confident number with
# nothing behind it, which then moved the average — so it is left out, and the
# band is the mean of what can actually be judged from writing.
_SPEAKING_CRITERIA = [
    "Fluency and Coherence",
    "Lexical Resource",
    "Grammatical Range and Accuracy",
]


def _evaluation_schema(criteria: list[str]) -> dict:
    """Feedback comes back in English and Russian side by side.

    The learner is preparing for an English exam but is not yet fluent, so
    advice they cannot read is advice they cannot act on. The `_ru` fields are
    parallel to their English counterparts, entry for entry.
    """
    return {
        "type": "object",
        "properties": {
            "criteria": {
                "type": "object",
                "properties": {c: {"type": "number"} for c in criteria},
                "required": criteria,
                "additionalProperties": False,
            },
            "comment": {"type": "string"},
            "comment_ru": {"type": "string"},
            "strengths": {"type": "array", "items": {"type": "string"}},
            "strengths_ru": {"type": "array", "items": {"type": "string"}},
            "improvements": {"type": "array", "items": {"type": "string"}},
            "improvements_ru": {"type": "array", "items": {"type": "string"}},
            # Structured rather than prose, because these become flashcards.
            # The same corrections buried in `improvements` cannot be turned
            # into study material without parsing English back out of them.
            "corrections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "wrong": {"type": "string"},
                        "right": {"type": "string"},
                        "note": {"type": "string"},
                        "note_ru": {"type": "string"},
                    },
                    "required": ["wrong", "right", "note", "note_ru"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "criteria", "comment", "comment_ru",
            "strengths", "strengths_ru", "improvements", "improvements_ru",
            "corrections",
        ],
        "additionalProperties": False,
    }


class TutorAgent:
    """Talks to Claude on behalf of the bot. Safe to construct without a key."""

    def __init__(self, config: Config):
        self._config = config
        self._client = None

    @property
    def available(self) -> bool:
        return self._config.ai_enabled

    async def _ask(self, prompt: str, schema: dict, max_tokens: int = 4096) -> dict:
        """One structured-output call. Raises on API failure.

        The two backends differ only in how the schema is attached and where
        the text comes back, so everything above this method — the retry loop,
        the schemas, the marking — is provider-agnostic.
        """
        if self._config.ai_provider == "openrouter":
            return await self._ask_openrouter(prompt, schema, max_tokens)
        return await self._ask_anthropic(prompt, schema, max_tokens)

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic  # imported lazily

            self._client = AsyncAnthropic(api_key=self._config.anthropic_api_key)
        return self._client

    async def _ask_anthropic(self, prompt: str, schema: dict, max_tokens: int) -> dict:
        response = await self._get_client().messages.create(
            model=self._config.anthropic_model,
            max_tokens=max_tokens,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        # A safety classifier can decline a request: HTTP 200, but the content
        # is empty or partial. Reading it unconditionally would reach the
        # learner as a blank message.
        if getattr(response, "stop_reason", None) == "refusal":
            raise FeedbackUnavailable("the model declined to answer this request")
        text = "".join(
            b.text for b in response.content if getattr(b, "type", "") == "text"
        )
        if not text.strip():
            raise FeedbackUnavailable("the model returned no text")
        return json.loads(text)

    async def _ask_openrouter(self, prompt: str, schema: dict, max_tokens: int) -> dict:
        """OpenRouter speaks the OpenAI chat-completions shape."""
        import httpx  # already present, the Anthropic SDK depends on it

        payload = {
            "model": self._config.openrouter_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "exercise",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._config.openrouter_api_key}",
                    # OpenRouter attributes traffic with these; both optional.
                    "HTTP-Referer": "https://github.com/ielts-telegram-bot",
                    "X-Title": "IELTS practice bot",
                },
                json=payload,
            )
        if response.status_code != 200:
            # Surface the body: OpenRouter explains refusals and bad model ids
            # there, and the status alone rarely says which one it was.
            raise RuntimeError(
                f"OpenRouter returned HTTP {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        if "choices" not in body:
            raise RuntimeError(f"Unexpected OpenRouter response: {str(body)[:300]}")
        choice = body["choices"][0]
        if choice.get("finish_reason") == "length":
            # Truncated output is invalid JSON, and the parse error that
            # follows says nothing about the real cause. Name it here.
            raise TruncatedResponse(
                f"the model hit the {max_tokens}-token limit before closing the "
                "JSON; raise max_tokens or ask for shorter content"
            )
        content = choice.get("message", {}).get("content") or ""
        if not content.strip():
            raise FeedbackUnavailable("the model returned no text")
        return json.loads(content)

    # --- Generation -------------------------------------------------------

    async def generate(
        self,
        section: str,
        topic: str = "everyday life",
        level: str = "B2",
        questions: int = 5,
        part: int | None = None,
        target_band: int | None = None,
    ) -> dict | None:
        """Produce one validated exercise, or None if it could not be made."""
        if not self.available:
            return None
        if section not in _SCHEMAS:
            raise ValueError(f"cannot generate for section {section!r}")

        brief = _BRIEFS[section].format(topic=topic, n=questions)
        prompt = f"{brief}\n\nCEFR level: {level}."
        if target_band and section in ("reading", "listening"):
            prompt += (
                f"\nPitch it at IELTS band {target_band}: "
                f"{_BAND_GUIDANCE[target_band]}. Set 'target_band' to {target_band}."
            )
        if part is not None:
            prompt += f"\nThis must be Part {part}."

        problems: list[str] = []
        for attempt in range(1, MAX_ATTEMPTS + 1):
            ask = prompt
            if problems:
                # Hand back the exact failures; a vague "try again" tends to
                # produce a different exercise with the same class of fault.
                ask = (
                    f"{prompt}\n\nYour previous attempt was rejected by the "
                    "validator for these reasons:\n"
                    + "\n".join(f"- {p}" for p in problems)
                    + "\n\nWrite a corrected version that fixes every one."
                )
            try:
                payload = await self._ask(
                    ask, _SCHEMAS[section], max_tokens=GENERATION_TOKENS
                )
            except (json.JSONDecodeError, TruncatedResponse, FeedbackUnavailable) as exc:
                logger.warning(
                    "Malformed generation for %s (attempt %d): %s",
                    section, attempt, exc,
                )
                problems = [f"your previous reply was not usable JSON ({exc})"]
                continue
            except Exception:
                logger.warning(
                    "Exercise generation failed for %s (attempt %d)",
                    section, attempt, exc_info=True,
                )
                return None

            exercise = self._finalise(section, payload, level)
            problems = validate_exercise(section, exercise)
            if not problems:
                logger.info("Generated a new %s exercise: %s", section, exercise["id"])
                return exercise
            logger.info(
                "Generated %s exercise rejected (attempt %d): %s",
                section, attempt, "; ".join(problems),
            )

        logger.warning("Giving up on generating a %s exercise after %d attempts",
                       section, MAX_ATTEMPTS)
        return None

    @staticmethod
    def _clean_options(exercise: dict) -> None:
        """Strip 'A)' / 'B.' prefixes the model adds to multiple-choice options.

        The keyboard already letters the buttons, so leaving them produces
        'A. A) 22 %'. Done in place, before validation, because dropping a
        prefix must not shift the answer index.
        """
        for question in exercise.get("questions", []):
            # Speaking sets hold plain strings here, not question objects.
            if not isinstance(question, dict):
                continue
            # A word bank of one or two entries gives the answer away rather
            # than offering a choice; the model produces these on diagram
            # questions. Treat it as no bank instead of rejecting the exercise.
            if len(question.get("bank") or []) < 3:
                question.pop("bank", None)
            if question.get("type") not in ("mc", "multi", "match"):
                continue
            question["options"] = [
                _strip_label(option) for option in question.get("options", [])
            ]
            question["answer"] = _resolve_answer(question)

    @staticmethod
    def _finalise(section: str, payload: dict, level: str) -> dict:
        """Add the fields the bot needs but the model should not invent."""
        exercise = dict(payload)
        # Expand before anything looks at the questions: a `match` question has
        # no options of its own until the group is resolved onto it.
        from app.services.content import expand_groups

        expand_groups(exercise)
        TutorAgent._clean_options(exercise)
        exercise["id"] = f"gen-{section[0]}{uuid.uuid4().hex[:8]}"
        if section == "vocabulary":
            exercise.setdefault("title", exercise.get("topic", "Vocabulary"))
        exercise.setdefault("level", level)
        exercise["generated"] = True
        if section == "speaking":
            # Part 1 and 3 have no cue card; empty strings would fail nothing
            # but would render as a blank card, so drop them.
            if exercise.get("part") != 2:
                exercise.pop("cue_card", None)
                exercise.pop("cue_card_translation", None)
            exercise.setdefault("title", exercise.get("topic", "Speaking"))
        return exercise

    # --- Marking ----------------------------------------------------------

    async def evaluate(
        self, section: str, task: dict, answer: str
    ) -> Evaluation | None:
        """Mark a Writing or Speaking response against the band descriptors."""
        if not self.available:
            return None
        criteria = _WRITING_CRITERIA if section == "writing" else _SPEAKING_CRITERIA

        if section == "writing":
            context = (
                f"Writing Task {task.get('task', 2)}\n"
                f"PROMPT:\n{task.get('prompt', '')}\n\n"
                f"CANDIDATE RESPONSE:\n{answer}"
            )
        else:
            questions = task.get("questions") or []
            listed = "\n".join(f"- {q}" for q in questions) or "(none)"
            context = (
                f"Speaking Part {task.get('part', 1)} — {task.get('topic', '')}\n"
                f"QUESTIONS:\n{listed}\n\n"
                "The candidate typed this answer rather than speaking, so judge "
                "only what writing can show. Do not comment on pronunciation, "
                "accent, intonation or hesitation.\n"
                "This is a practice sample, and Part 1 answers are short by "
                "design. Judge the control of language shown, and do not mark "
                "down for brevity the format itself asks for.\n"
                f"CANDIDATE RESPONSE:\n{answer}"
            )

        prompt = (
            f"Mark this against the official IELTS band descriptors.\n\n{context}\n\n"
            "Give a band from 0 to 9 in half-band steps for each criterion. "
            "'comment' is two sentences on the overall impression. Give two "
            "strengths and three improvements; each improvement must quote "
            "the candidate's own words and show a better version. "
            "Fill the _ru fields with Russian translations of the same "
            "points, in the same order and the same number of entries, so "
            "a learner who cannot yet read the English can still act on them. "
            "In 'corrections', list every specific language error worth "
            "restudying: 'wrong' is the candidate's exact wording, 'right' is "
            "the corrected version, 'note' names the rule in a few words and "
            "'note_ru' is that note in Russian. Spelling and word-form errors "
            "belong here; style preferences do not."
        )

        try:
            payload = await self._ask(
                prompt, _evaluation_schema(criteria), max_tokens=MARKING_TOKENS
            )
        except Exception:
            logger.warning("Marking failed for %s", section, exc_info=True)
            return None

        from app.services.banding import round_band

        marks = {name: round_band(float(v)) for name, v in payload["criteria"].items()}
        return Evaluation(
            band=round_band(sum(marks.values()) / len(marks)),
            criteria=marks,
            strengths=payload.get("strengths", []),
            improvements=payload.get("improvements", []),
            comment=payload.get("comment", ""),
            strengths_ru=payload.get("strengths_ru", []),
            improvements_ru=payload.get("improvements_ru", []),
            comment_ru=payload.get("comment_ru", ""),
            corrections=payload.get("corrections", []),
        )
