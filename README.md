# IELTS Prep Bot 🎓

A Telegram bot for practising all four sections of the IELTS exam —
**Reading, Listening, Writing and Speaking** — plus vocabulary flashcards and
progress tracking. Built with Python and [aiogram 3](https://docs.aiogram.dev/).

## Features

| Section | What you get |
|---|---|
| 📖 **Reading** | Academic passages with auto-checked multiple-choice, true/false and gap-fill questions, each with an explanation. |
| 🎧 **Listening** | Comprehension exercises delivered as a **voice clip** (synthesized with gTTS) or transcript, followed by questions. |
| ✍️ **Writing** | Task 1 & Task 2 prompts with tips. Send your essay and get **examiner feedback** — AI-graded against the band descriptors if an Anthropic key is set, otherwise a built-in rule-based estimate. |
| 🗣 **Speaking** | Parts 1–3 with cue cards and model tips. Reply by voice or text and get guidance. |
| 🔤 **Vocabulary** | Flip-card decks for Band 7+ words and idioms. |
| 📊 **Progress** | Per-section attempts and scores, stored in SQLite. |

## Quick start

```bash
# 1. Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
#   → open .env and paste the token you get from @BotFather

# 3. Run
python -m app.main       # or: python run.py
```

Then open your bot in Telegram and send `/start`.

## Configuration (`.env`)

| Variable | Required | Purpose |
|---|---|---|
| `BOT_TOKEN` | ✅ | Bot token from [@BotFather](https://t.me/BotFather). |
| `ANTHROPIC_API_KEY` | — | Enables AI-graded Writing feedback. Without it a rule-based evaluator is used. |
| `ANTHROPIC_MODEL` | — | Model for AI feedback (default `claude-sonnet-5`). |
| `DB_PATH` | — | SQLite file path (default `data/ielts.db`). |

**Optional extras** — install to unlock more:
- `gTTS` → real voice clips in the Listening section (falls back to transcript text otherwise).
- `anthropic` → AI-graded Writing feedback.

## Project layout

```
app/
├── main.py            # entry point: wiring + polling
├── config.py          # env-based configuration
├── db.py              # SQLite (users, results, stats)
├── states.py          # FSM states
├── keyboards.py       # menu & inline keyboards
├── content/           # exercise data as JSON — edit to add more
│   ├── reading.json
│   ├── listening.json
│   ├── writing.json
│   ├── speaking.json
│   └── vocabulary.json
├── services/
│   ├── content.py     # loads/looks up exercises
│   ├── tts.py         # optional text-to-speech (gTTS)
│   └── evaluation.py  # essay grading (AI or rule-based)
└── handlers/          # one router per section
    ├── quiz.py        # shared Reading + Listening engine
    ├── writing.py
    ├── speaking.py
    ├── vocabulary.py
    ├── progress.py
    └── common.py      # /start, /help, /cancel, fallback
```

## Adding content

Every exercise lives in a JSON file under `app/content/`. To add a Reading
passage, append an object to `reading.json` with a unique `id`, a `passage`,
and a `questions` list (`mc`, `tf` or `gap`). No code changes needed — the bot
picks it up on restart.

## Notes

- Speaking answers are collected as voice/text and the bot responds with model
  tips; automatic speech scoring is intentionally out of scope for this version.
- The rule-based Writing band estimate checks structure and length only; use an
  Anthropic key for feedback on grammar, vocabulary and argument quality.
